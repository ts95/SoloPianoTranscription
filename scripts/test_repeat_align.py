"""Regression test: repeat-consistency pre-snap alignment (repeat_align).

Spec: docs/superpowers/specs/2026-07-17-repeat-consistency-design.md
Run: .venv/bin/python scripts/test_repeat_align.py
"""
import sys, os, json, subprocess, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from transcription_cleanup import repeat_align
import pretty_midi

# the recurring figure: (in-bar beat, pitch) — 6 notes, both "hands"
FIGURE = [(0.0, 36), (0.0, 60), (0.5, 62), (1.0, 64), (1.75, 65), (2.5, 67)]


def bar_events(bar, shift=0.0, jitter=None, extra=None, start_id=0):
    evs = []
    for k, (off, p) in enumerate(FIGURE):
        j = jitter[k] if jitter else 0.0
        evs.append((start_id + k, bar * 4 + off + shift + j, p))
    if extra:
        evs.append((start_id + len(FIGURE), bar * 4 + extra[0], extra[1]))
    return evs


def test_uniform_rush_fixed():
    evs = (bar_events(0, start_id=0)
           + bar_events(1, shift=0.24, start_id=100)
           + bar_events(2, start_id=200))
    deltas, report = repeat_align(evs, 4)
    rushed_ids = {100 + k for k in range(len(FIGURE))}
    assert set(deltas) == rushed_ids, f"wrong notes corrected: {sorted(deltas)}"
    assert all(abs(float(d) - 0.24) < 0.02 for d in deltas.values()), deltas
    applied = [e for e in report if e.get("applied")]
    assert len(applied) == 1 and applied[0]["window"] == 2 \
        and applied[0]["reference_window"] in (1, 3), report
    print("ok: uniform rush corrected toward the clean reference")


def test_variation_flagged_not_touched():
    jitter = [0.0, 0.30, 0.05, 0.35, -0.10, 0.28]  # non-uniform: p90 >> 0.07
    evs = (bar_events(0, start_id=0)
           + bar_events(1, jitter=jitter, extra=(2.75, 72), start_id=100)
           + bar_events(2, start_id=200))
    deltas, report = repeat_align(evs, 4)
    assert not deltas, f"variation was modified: {deltas}"
    flagged = [e for e in report if not e.get("applied") and e["window"] == 2]
    assert flagged and "reason" in flagged[0], report
    print("ok: non-uniform variation flagged, never touched")


def test_subthreshold_untouched_unflagged():
    evs = (bar_events(0, start_id=0)
           + bar_events(1, shift=0.05, start_id=100)
           + bar_events(2, start_id=200))
    deltas, report = repeat_align(evs, 4)
    assert not deltas, deltas
    assert not [e for e in report if e["window"] == 2], (
        f"sub-threshold shift should not even be flagged: {report}")
    print("ok: sub-threshold shift left alone silently")


def test_boundary_pickup_outlier_still_applied():
    # figure uniformly shifted 0.24 except the last note only 0.11 (a
    # differently-placed boundary pickup) -> trimmed uniformity test passes
    evs = (bar_events(0, start_id=0)
           + bar_events(1, shift=0.24, jitter=[0, 0, 0, 0, 0, -0.13], start_id=100)
           + bar_events(2, start_id=200))
    deltas, report = repeat_align(evs, 4)
    applied = [e for e in report if e.get("applied") and e["window"] == 2]
    assert applied, f"uniform body with one boundary outlier should apply: {report}"
    assert {100 + k for k in range(len(FIGURE))} == set(deltas), deltas
    print("ok: boundary pickup outlier trimmed; uniform body still auto-applied")


def test_agogic_ramp_per_beat_fixed():
    """Per-beat-group shift (v1.1): bar 2 is rushed with a RAMP, not a
    uniform shift — front beats pushed harder (~0.23), later beats less
    (~0.13, ~0.03), mirroring the measured Mirrors bar 2 (per-beat deltas
    -0.231/-0.223/-0.132/-0.028). A whole-bar median both fails the
    uniformity gate and overshoots the relaxed tail; a per-beat-group shift
    should apply cleanly with a descending-magnitude shift list."""
    # >=2 notes per beat so each beat-group's median is well-defined.
    RAMP_FIGURE = [
        (0.0, 60), (0.1, 62),   # beat 0
        (1.0, 64), (1.2, 65),   # beat 1
        (2.0, 67), (2.3, 69),   # beat 2
        (3.0, 71), (3.5, 72),   # beat 3
    ]
    RAMP = [0.23, 0.22, 0.13, 0.03]  # per-beat shift applied to bar 1 only

    def ramp_bar_events(bar, shifts, start_id):
        evs = []
        for k, (off, p) in enumerate(RAMP_FIGURE):
            g = int(off)
            evs.append((start_id + k, bar * 4 + off + shifts[g], p))
        return evs

    zero = [0.0, 0.0, 0.0, 0.0]
    evs = (ramp_bar_events(0, zero, start_id=0)
           + ramp_bar_events(1, RAMP, start_id=100)
           + ramp_bar_events(2, zero, start_id=200))
    deltas, report = repeat_align(evs, 4)
    applied = [e for e in report if e.get("applied") and e["window"] == 2]
    assert applied, f"agogic ramp should auto-apply per beat-group: {report}"
    sb = applied[0]["shift_beats_by_beat"]
    assert len(sb) == 4, sb
    assert all(sb[i] >= sb[i + 1] for i in range(len(sb) - 1)), (
        f"expected descending-magnitude ramp: {sb}")
    assert sb[0] > 0.15 and sb[-1] < 0.10, f"ramp endpoints off: {sb}"
    ramped_ids = {100 + k for k in range(len(RAMP_FIGURE))}
    assert ramped_ids <= set(deltas), (
        f"every window-2 note id should be in deltas: missing "
        f"{ramped_ids - set(deltas)}")
    print("ok: agogic ramp fixed with a descending per-beat-group shift")


def test_quantize_engraves_repeats_identically():
    """End to end: bar 2 rushed 0.24 beat -> all three bars engrave the same."""
    PY, SCRIPT = sys.executable, os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "transcription_cleanup.py")
    with tempfile.TemporaryDirectory() as d:
        mid = os.path.join(d, "t.mid")
        out = os.path.join(d, "t.musicxml")
        pm = pretty_midi.PrettyMIDI(initial_tempo=120)  # beat = 0.5 s
        inst = pretty_midi.Instrument(program=0)
        figure = [(0.0, 36), (0.0, 60), (0.5, 62), (1.0, 64), (1.75, 65), (2.5, 67)]
        for bar, shift in ((0, 0.0), (1, 0.24), (2, 0.0)):
            for off, p in figure:
                t = (bar * 4 + off + shift) * 0.5
                inst.notes.append(pretty_midi.Note(velocity=80, pitch=p,
                                                   start=t, end=t + 0.2))
        pm.instruments.append(inst)
        pm.write(mid)
        r = subprocess.run([PY, SCRIPT, "quantize", mid, out, "--bpm", "120",
                            "--time-sig", "4/4", "--bar-phase", "0"],
                           capture_output=True, text=True, check=True)
        summary = json.loads(r.stdout)
        applied = [e for e in summary.get("repeat_alignment", [])
                   if e.get("applied")]
        assert applied and applied[0]["window"] == 2, summary.get("repeat_alignment")

        from music21 import converter
        s = converter.parse(out)
        def bar_rhythm(part, n):
            m = part.getElementsByClass('Measure')[n]
            return [(float(e.offset), float(e.duration.quarterLength))
                    for e in m.notes]
        for part in s.parts:
            b1, b2, b3 = (bar_rhythm(part, k) for k in range(3))
            assert b1 == b2 == b3, f"bars differ after alignment: {b1} / {b2} / {b3}"
    print("ok: quantize engraves the rushed bar identically to its references")


if __name__ == "__main__":
    test_uniform_rush_fixed()
    test_variation_flagged_not_touched()
    test_subthreshold_untouched_unflagged()
    test_boundary_pickup_outlier_still_applied()
    test_agogic_ramp_per_beat_fixed()
    test_quantize_engraves_repeats_identically()
