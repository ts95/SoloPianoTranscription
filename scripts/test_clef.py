"""The bass staff switches to treble clef only for SUSTAINED high passages.

A high left-hand run (several bars at/above the top of the bass staff) reads
better in treble clef than under a pile of ledger lines. But an isolated high
bar should keep bass clef — a clef that lasts a bar or two is less readable
than the ledger lines it replaces. assign_bass_clefs encodes that hysteresis.

Run: .venv/bin/python scripts/test_clef.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from transcription_cleanup import assign_bass_clefs
from music21 import clef, note, stream


def _score(min_pitches):
    """Two-staff score; bass staff has one whole note per bar at min_pitches[i]."""
    sc = stream.Score()
    tr, bs = stream.PartStaff(), stream.PartStaff()
    for i, mp in enumerate(min_pitches):
        mt = stream.Measure(number=i + 1)
        mt.append(note.Note(76, quarterLength=4))
        tr.append(mt)
        mb = stream.Measure(number=i + 1)
        mb.append(note.Note(mp, quarterLength=4))
        bs.append(mb)
    sc.insert(0, tr)
    sc.insert(0, bs)
    return sc, bs


def _clefs(bass):
    out = {}
    for m in bass.getElementsByClass(stream.Measure):
        cl = m.getElementsByClass(clef.Clef)
        if cl:
            out[m.number] = cl[0].sign
    return out


def test_sustained_high_run_gets_treble():
    sc, bass = _score([40, 40, 64, 64, 64, 64, 40, 40])  # 4-bar high run
    n = assign_bass_clefs(sc, min_run=3)
    assert n == 2, f"expected treble-in + bass-out = 2 clef changes, got {n}"
    cl = _clefs(bass)
    assert cl.get(3) == "G", f"no treble clef at the high-run start: {cl}"
    assert cl.get(7) == "F", f"bass clef not restored after the run: {cl}"
    print("ok: sustained high bass run switched to treble clef")


def test_isolated_high_bars_stay_bass():
    sc, bass = _score([40, 64, 40, 64, 40])  # scattered single high bars
    n = assign_bass_clefs(sc, min_run=3)
    assert n == 0, f"isolated high bars must not change clef, got {n}"
    print("ok: isolated high bars keep bass clef (ledger lines)")


if __name__ == "__main__":
    test_sustained_high_run_gets_treble()
    test_isolated_high_bars_stay_bass()
    print("all clef tests passed")
