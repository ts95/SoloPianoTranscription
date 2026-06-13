"""Regression tests for the quantize grid: a coarser default, and a hard
onset-fit gate that refuses a grid the onsets do not actually sit on.

Run: .venv/bin/python scripts/test_quantize_grid.py

Background (docs/WHY_MIDI_TO_SCORE_IS_HARD.md, sec 3.1 & 6.0): a wrong or
over-fine grid is the single biggest score-wrecker. quantize must (a) default
to a readable 1/16 grid rather than the busiest 1/32, and (b) measure how well
its grid explains the onsets and refuse to emit a mis-snapped score silently.

Scope of the gate (verified): it catches a *grossly misaligned* grid only.
A wrong metrical level (octave-off BPM) is NOT caught — onset fit is base-rate-
invariant to it on dense pieces — so the off-grid fixture below is a uniform
half-slot offset (fit ~ 0), the unambiguous gross-misalignment case.
"""
import json
import os
import subprocess
import sys
import tempfile

import pretty_midi

SCRIPT = os.path.join(os.path.dirname(__file__), "transcription_cleanup.py")
PY = sys.executable


def _on_grid_midi(path, bpm=120):
    # Eighth notes: at 120 BPM every 0.25 s, i.e. exactly on a 1/16 grid.
    pm = pretty_midi.PrettyMIDI(initial_tempo=bpm)
    inst = pretty_midi.Instrument(program=0)
    for k in range(32):
        t = k * 0.25
        inst.notes.append(pretty_midi.Note(velocity=80, pitch=60 + (k % 5),
                                            start=t, end=t + 0.24))
    pm.instruments.append(inst)
    pm.write(path)


def _off_grid_midi(path):
    # Every onset shifted half a 16th (0.125 QL) off the t=0-anchored grid:
    # at 120 BPM a 0.0625 s offset puts nothing on a grid slot -> fit ~ 0.
    pm = pretty_midi.PrettyMIDI(initial_tempo=120)
    inst = pretty_midi.Instrument(program=0)
    for k in range(32):
        t = 0.0625 + k * 0.25
        inst.notes.append(pretty_midi.Note(velocity=80, pitch=60 + (k % 5),
                                            start=t, end=t + 0.24))
    pm.instruments.append(inst)
    pm.write(path)


def _run(mid, out, *extra):
    return subprocess.run([PY, SCRIPT, "quantize", mid, out, *extra],
                          capture_output=True, text=True)


def test_default_grid_is_sixteenth():
    with tempfile.TemporaryDirectory() as d:
        mid, out = os.path.join(d, "g.mid"), os.path.join(d, "g.musicxml")
        _on_grid_midi(mid)
        r = _run(mid, out, "--bpm", "120")  # no --grid
        assert r.returncode == 0, r.stderr
        summary = json.loads(r.stdout)
        assert summary["grid"] == "1/16", f"default grid not 1/16: {summary['grid']}"
    print("ok: default grid is 1/16")


def test_good_grid_reports_high_fit():
    with tempfile.TemporaryDirectory() as d:
        mid, out = os.path.join(d, "g.mid"), os.path.join(d, "g.musicxml")
        _on_grid_midi(mid)
        r = _run(mid, out, "--bpm", "120")
        assert r.returncode == 0, r.stderr
        summary = json.loads(r.stdout)
        assert "onset_grid_fit" in summary, "fit not reported in summary"
        assert summary["onset_grid_fit"] >= 0.9, summary["onset_grid_fit"]
    print("ok: on-grid onsets report high fit")


def test_low_fit_grid_is_refused():
    with tempfile.TemporaryDirectory() as d:
        mid, out = os.path.join(d, "b.mid"), os.path.join(d, "b.musicxml")
        _off_grid_midi(mid)
        r = _run(mid, out, "--bpm", "120")
        assert r.returncode != 0, "low-fit grid was not refused"
        assert "onset_grid_fit" in r.stdout, r.stdout
        assert not os.path.exists(out), "score written despite refusal"
    print("ok: low-fit grid refused")


def test_force_overrides_low_fit():
    with tempfile.TemporaryDirectory() as d:
        mid, out = os.path.join(d, "b.mid"), os.path.join(d, "b.musicxml")
        _off_grid_midi(mid)
        r = _run(mid, out, "--bpm", "120", "--force")
        assert r.returncode == 0, r.stderr
        assert os.path.exists(out), "score not written under --force"
    print("ok: --force overrides the gate")


if __name__ == "__main__":
    test_default_grid_is_sixteenth()
    test_good_grid_reports_high_fit()
    test_low_fit_grid_is_refused()
    test_force_overrides_low_fit()
    print("all grid tests passed")
