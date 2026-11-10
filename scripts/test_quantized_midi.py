"""Regression test: score notes take the velocity of the matching performed note.

Run: .venv/bin/python scripts/test_quantized_midi.py
"""
from quantized_midi import assign_velocities


def test_each_score_note_takes_its_own_performed_velocity():
    # the same pitch struck three times: each score note gets ITS strike, not the nearest twice
    perf = [(0.0, 60, 40), (1.0, 60, 80), (2.0, 60, 100), (0.0, 64, 55)]
    score = [(0.0, 60), (0.0, 64), (1.0, 60), (2.25, 60)]  # last one nudged by hand
    vel, matched = assign_velocities(score, perf)
    assert (vel, matched) == ([40, 55, 80, 100], 4), (vel, matched)
    print("ok: repeated notes each take their own performed velocity")


def test_unmatched_note_is_filled_from_its_neighbours():
    perf = [(0.0, 60, 40), (1.0, 62, 60), (40.0, 72, 110)]
    score = [(0.0, 60), (1.0, 62), (1.0, 67),   # 67 was added by hand: no performed G4
             (40.0, 72), (80.0, 50)]            # 50: nothing matched anywhere near
    vel, matched = assign_velocities(score, perf)
    assert matched == 3 and vel[2] == 50, (vel, matched)   # mean of 40 and 60
    assert vel[4] == 60, vel                               # falls back to the median
    print("ok: a hand-added note takes the average of the matched notes around it")


def test_a_shortened_pickup_bar_does_not_break_the_match():
    # DuET placed everything one quarter later than the hand-fixed score (pickup cut by a beat)
    perf = [(1.0 + i, 60 + i % 3, 30 + 10 * i) for i in range(8)]
    score = [(float(i), 60 + i % 3) for i in range(8)]
    vel, matched = assign_velocities(score, perf)
    assert matched == 8 and vel == [30 + 10 * i for i in range(8)], (vel, matched)
    print("ok: a constant shift from an edited pickup bar is absorbed")


if __name__ == "__main__":
    test_a_shortened_pickup_bar_does_not_break_the_match()
    test_each_score_note_takes_its_own_performed_velocity()
    test_unmatched_note_is_filled_from_its_neighbours()
