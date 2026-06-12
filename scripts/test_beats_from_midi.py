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


if __name__ == "__main__":
    test_gap_bridging()
