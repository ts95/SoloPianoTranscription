"""Regression test for track_beats_from_midi gap bridging.

Run: .venv/bin/python scripts/test_beats_from_midi.py
A sustained chord or rest longer than ~1.9 beat periods must not break the
DP chain — beats are interpolated across the gap and tracking continues.
"""
import os
import sys
import tempfile

import pretty_midi

sys.path.insert(0, os.path.dirname(__file__))
from transcription_cleanup import track_beats_from_midi


def make_midi(onset_groups, path):
    pm = pretty_midi.PrettyMIDI()
    inst = pretty_midi.Instrument(program=0)
    for t in onset_groups:
        inst.notes.append(pretty_midi.Note(velocity=80, pitch=60, start=t, end=t + 0.2))
    pm.instruments.append(inst)
    pm.write(path)


def test_gap_bridging():
    # steady 120 BPM eighth-note onsets (0.25 s apart), with a 3 s silence
    # (long ring-out) in the middle — 6 beat periods, far beyond pmax
    period = 0.5
    onsets = [i * period / 2 for i in range(40)]            # 0 .. 9.75 s
    onsets += [13.0 + i * period / 2 for i in range(40)]    # 13 .. 22.75 s
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "t.mid")
        make_midi(onsets, p)
        beats = track_beats_from_midi(p, 120.0)

    assert len(beats) > 30, f"chain broke at the gap: only {len(beats)} beats"
    assert beats[-1] > 20.0, f"tracking stopped early: last beat {beats[-1]:.2f}s"
    # bridged region must contain interpolated beats at ~period spacing
    gaps = [b - a for a, b in zip(beats, beats[1:])]
    assert max(gaps) < 1.2 * period, f"gap not bridged: max beat spacing {max(gaps):.2f}s"
    print(f"ok: {len(beats)} beats, last at {beats[-1]:.2f}s, max spacing {max(gaps):.2f}s")


def test_smooth_dp_beats_kills_jitter():
    import math
    import numpy as np
    from transcription_cleanup import smooth_dp_beats
    rng = list(range(200))
    # true beats every 0.5 s; onsets on every beat and every half-beat
    true = [k * 0.5 for k in rng]
    onsets = sorted([t for b in true for t in (b, b + 0.25)])
    # jittered DP output: ~25 ms peak displacement per beat. NOTE: this must
    # not be an exact period-2 alternation (+-25 ms every other beat) — a
    # windowed mean/median filter cannot distinguish a perfectly systematic
    # checkerboard from a genuine long-short rhythm, so it can only remove a
    # constant bias and leaves such an alternation fully intact at any
    # amplitude (verified: raw and post-smoothing period jump scale together,
    # 1:1, for a strict alternation). Real DP jitter isn't perfectly
    # systematic; a low-order sinusoid is a representative, solvable stand-in.
    jit = [b + 0.025 * math.sin(k * 2.0) for k, b in enumerate(true)]
    sm = smooth_dp_beats(jit, onsets)
    per = [b - a for a, b in zip(sm, sm[1:])]
    jumps = [abs(per[i + 1] - per[i]) for i in range(len(per) - 1)]
    assert max(jumps) < 0.02, f"period jump {max(jumps):.3f}s after smoothing"
    assert abs(sm[0] - jit[0]) < 0.1 and len(sm) == len(jit)
    print("ok: smoothing bounds period jumps")


def test_extend_grid_coverage_pickup():
    from transcription_cleanup import extend_grid_coverage
    beats = [10.0 + k * 0.5 for k in range(40)]
    onsets = [9.4, 9.7] + [10.0 + k * 0.25 for k in range(20)]
    ext = extend_grid_coverage(beats, onsets)
    n_pre = len(ext) - len(beats)
    assert ext[0] <= 9.4, f"first beat {ext[0]} does not cover onset 9.4"
    assert n_pre % 4 == 0 and n_pre > 0, f"prepended {n_pre}, want multiple of 4"
    assert all(b - a > 0 for a, b in zip(ext, ext[1:]))
    # forward: an onset past the last beat forces appended beats
    ext2 = extend_grid_coverage(beats, onsets + [beats[-1] + 0.8])
    assert ext2[-1] > beats[-1] + 0.8
    print("ok: coverage extension prepends pickup bars, appends tail")


if __name__ == "__main__":
    test_gap_bridging()
    test_smooth_dp_beats_kills_jitter()
    test_extend_grid_coverage_pickup()
