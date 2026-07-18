"""Regression tests for grid_surgery. Run: .venv/bin/python scripts/test_grid_surgery.py"""
import json
import os
import sys
import tempfile

import pretty_midi

sys.path.insert(0, os.path.dirname(__file__))
from grid_surgery import diagnose  # noqa: E402
from grid_surgery import repair  # noqa: E402


def make_hop_fixture(d):
    """120 BPM 4/4, continuous 16ths. Beats correct except beats 40-80,
    where the grid runs at 3/4 of the true period (dotted-eighth hop)."""
    mid = os.path.join(d, "t.mid")
    bj = os.path.join(d, "beats.json")
    pm = pretty_midi.PrettyMIDI(initial_tempo=120)
    inst = pretty_midi.Instrument(program=0)
    for k in range(120 * 4):          # 120 beats of 16ths at 0.125 s
        t = k * 0.125
        inst.notes.append(pretty_midi.Note(velocity=80, pitch=60 + k % 12,
                                           start=t, end=t + 0.1))
    pm.instruments.append(inst)
    pm.write(mid)
    beats = [k * 0.5 for k in range(41)]                    # good: 0..20 s
    t = beats[-1]
    for _ in range(53):                                     # hop: period 0.375
        t += 0.375
        beats.append(round(t, 4))
    while len(beats) < 121:                                 # good again
        t += 0.5
        beats.append(round(t, 4))
    json.dump({"beats": beats}, open(bj, "w"))
    return mid, bj


def test_diagnose_flags_hop():
    with tempfile.TemporaryDirectory() as d:
        mid, bj = make_hop_fixture(d)
        rep = diagnose(mid, bj, 0.0)
        assert rep["probe"]["level_hop_suspects"], "hop span not flagged"
        assert rep["flag_clusters"], "no flag clusters emitted"
        cl = rep["flag_clusters"][0]
        for key in ("span_s", "grid_fit", "quarter_scan", "sublevel_scan"):
            assert key in cl, f"cluster missing {key}"
        assert cl["quarter_scan"]["fit"] > 0.9, (
            "free quarter scan should recover the true 120 BPM lattice")
        assert len(rep["tempo_map"]) >= 3
    print("ok: diagnose flags the hop and scans the span")


def test_repair_lattice_fixes_hop():
    with tempfile.TemporaryDirectory() as d:
        mid, bj = make_hop_fixture(d)
        base = json.load(open(bj))
        # the hop span runs t=20.0 .. beats[93]; repair with a 0.5 s lattice
        plan = {"base": "beats.json", "midi": "t.mid", "midi_shift": 0.0,
                "repairs": [{"span_s": [20.0, 40.0],
                             "op": "lattice", "period": 0.5}],
                "output": "beats.repaired.json"}
        pp = os.path.join(d, "plan.json")
        json.dump(plan, open(pp, "w"))
        rep = repair(pp)
        fixed = json.load(open(os.path.join(d, "beats.repaired.json")))
        assert not fixed.get("level_hop_suspects"), "hop survived repair"
        assert rep["after"]["onset_grid_fit"] > rep["before"]["onset_grid_fit"]
        b = fixed["beats"]
        assert all(y > x for x, y in zip(b, b[1:]))
    print("ok: lattice repair removes the hop and improves fit")


def test_repair_rejects_overlap_and_regression():
    with tempfile.TemporaryDirectory() as d:
        mid, bj = make_hop_fixture(d)
        plan = {"base": "beats.json", "midi": "t.mid", "midi_shift": 0.0,
                "repairs": [
                    {"span_s": [20.0, 40.0], "op": "lattice", "period": 0.5},
                    {"span_s": [30.0, 45.0], "op": "lattice", "period": 0.5}],
                "output": "x.json"}
        pp = os.path.join(d, "plan.json")
        json.dump(plan, open(pp, "w"))
        try:
            repair(pp)
            raise AssertionError("overlapping spans accepted")
        except SystemExit:
            pass
        # regression guard: "repairing" a good span with a wrong period must fail
        plan2 = {"base": "beats.json", "midi": "t.mid", "midi_shift": 0.0,
                 "repairs": [{"span_s": [2.0, 10.0],
                              "op": "lattice", "period": 0.41}],
                 "output": "y.json"}
        json.dump(plan2, open(pp, "w"))
        try:
            repair(pp)
            raise AssertionError("fit regression accepted")
        except SystemExit:
            pass
    print("ok: repair rejects overlapping spans and fit regressions")


if __name__ == "__main__":
    test_diagnose_flags_hop()
    test_repair_lattice_fixes_hop()
    test_repair_rejects_overlap_and_regression()
