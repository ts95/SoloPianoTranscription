"""Regression test: split_hands_midi follows DuET's per-note staff assignment.

Run: .venv/bin/python scripts/test_split_hands_midi.py
"""
import numpy as np
import pretty_midi

from split_hands_midi import split
from transcription_cleanup import all_notes


def performance():
    pm = pretty_midi.PrettyMIDI(initial_tempo=120.0)
    inst = pretty_midi.Instrument(program=0)
    for i in range(8):  # bass line under a melody, same onsets
        t = i * 0.5
        inst.notes.append(pretty_midi.Note(velocity=80, pitch=72 + i, start=t, end=t + 0.5))
        inst.notes.append(pretty_midi.Note(velocity=80, pitch=40 + i, start=t, end=t + 0.5))
    pm.instruments.append(inst)
    return pm


def test_split_follows_the_staff_column():
    pm = performance()
    pitches = np.array([n.pitch for n in all_notes(pm)])
    staff = np.array([1 if p < 60 else 0 for p in pitches])
    staff[1] = 1  # DuET put the first melody note (72) on the lower staff: a crossing
    lo = split(pm, pitches, staff, "bass")
    hi = split(pm, pitches, staff, "treble")
    assert len(lo) == 9 and len(hi) == 7, (len(lo), len(hi))
    assert 72 in [n.pitch for n in lo], "the crossed note must follow DuET's staff, not a pitch threshold"
    print("ok: hands follow DuET's staff column, including a crossed note")


def test_mismatched_npz_is_refused():
    pm = performance()
    pitches = np.array([n.pitch for n in all_notes(pm)])
    staff = np.zeros(len(pitches), dtype=int)
    for bad_p, bad_s in ((pitches[:-1], staff[:-1]), (pitches + 1, staff)):
        try:
            split(pm, bad_p, bad_s, "bass")
        except SystemExit as e:
            assert "does not match" in str(e), e
        else:
            raise AssertionError("expected SystemExit")
    print("ok: a score.npz from a different MIDI is refused")


if __name__ == "__main__":
    test_split_follows_the_staff_column()
    test_mismatched_npz_is_refused()
