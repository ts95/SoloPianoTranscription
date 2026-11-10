"""Regression test: bar_timing measures what the performance did, bar by bar.

Run: .venv/bin/python scripts/test_bar_timing.py
"""
import os
import tempfile

import numpy as np

from bar_timing import analyze, engraved_bar_quarters, stretched_bars


def piece(spq_per_bar, pickup=((3.0, 0.0), (3.5, 0.25)), bar1_time=0.5):
    """A 4-quarter pickup bar, then len(spq_per_bar) bars of 3 quarters in eighths.
    spq_per_bar: seconds per quarter of each 3-quarter bar. pickup: (quarter, seconds)."""
    starts, lengths = [0.0], [4.0]
    onsets, times = [q for q, _ in pickup], [t for _, t in pickup]
    t = bar1_time
    for i, spq in enumerate(spq_per_bar):
        start = 4.0 + 3.0 * i
        starts.append(start)
        lengths.append(3.0)
        for k in range(6):
            onsets.append(start + 0.5 * k)
            times.append(t + 0.5 * k * spq)
        t += 3.0 * spq
    return tuple(np.array(a) for a in (times, onsets, starts, lengths))


def test_steady_piece():
    r = analyze(*piece([0.5] * 11))
    assert r["bars"] == 12 and r["bar_quarters"] == 3.0
    assert r["measured_tempo_quarter_bpm"] == 120.0
    assert r["steady"] is True and r["unsteady_bars"] == []
    assert (r["pickup_written_quarters"], r["pickup_measured_quarters"], r["pickup_mismatch"]) == (1.0, 1.0, False)
    print("ok: a metronomic piece is steady, with its real tempo and pickup")


def test_rubato_piece():
    r = analyze(*piece([0.4, 0.6] * 5 + [0.4]))
    assert r["steady"] is False and r["steady_share"] == 0.0
    assert r["unsteady_bars"] == list(range(2, 12))
    print("ok: bars that swing 20% around the median are not steady")


def test_pickup_written_longer_than_played():
    r = analyze(*piece([0.5] * 11, pickup=((2.0, 0.0), (3.0, 0.25))))
    assert (r["pickup_written_quarters"], r["pickup_measured_quarters"], r["pickup_mismatch"]) == (2.0, 1.0, True)
    print("ok: a pickup written twice as long as it was played is flagged")


def test_engraved_lengths_and_stretched_bars():
    xml = ('<score-partwise><part id="P1">'
           '<measure number="0" implicit="yes"><attributes><time><beats>4</beats><beat-type>4</beat-type></time></attributes></measure>'
           '<measure number="1"><attributes><time><beats>3</beats><beat-type>4</beat-type></time></attributes></measure>'
           '<measure number="2"/>'
           '<measure number="3"><attributes><time><beats>4</beats><beat-type>4</beat-type></time></attributes></measure>'
           '<measure number="4"><attributes><time><beats>6</beats><beat-type>8</beat-type></time></attributes></measure>'
           '</part></score-partwise>')
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "s.musicxml")
        with open(path, "w") as f:
            f.write('<?xml version="1.0"?>\n' + xml)
        engraved = engraved_bar_quarters(path)
    assert engraved == [4.0, 3.0, 3.0, 4.0, 3.0], engraved
    assert stretched_bars(engraved, np.array([4.0, 3.0, 3.0, 3.0, 3.0])) == [4]
    assert stretched_bars(engraved, np.array([4.0, 3.0, 3.0])) is None
    print("ok: engraved bar lengths are read per measure; a bar DuET stretched is found; a count mismatch is None")


if __name__ == "__main__":
    test_steady_piece()
    test_rubato_piece()
    test_pickup_written_longer_than_played()
    test_engraved_lengths_and_stretched_bars()
