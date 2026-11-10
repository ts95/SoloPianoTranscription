"""Regression test: the bass harmony is the pitch class of the LOWEST NOTE.

Run: .venv/bin/python scripts/test_analyze_pedaling.py
"""
from analyze_pedaling import analyze_measure


def measure(bass_events):
    return {"number": 1, "time_sig": "4/4", "ticks": 1920,
            "staves": {"2": {"voices": {"1": bass_events}}}}


def chord(tick, pitches):
    return {"type": "Chord", "tick": tick, "dur": 960,
            "pitches": sorted(pitches), "pcs": sorted({p % 12 for p in pitches})}


def test_same_bass_note_is_not_a_harmony_change():
    # G2+C3 then G2+B2: the bass is G both times (C is merely the smallest pc number)
    r = analyze_measure(measure([chord(0, [43, 48]), chord(960, [43, 47])]))
    assert (r["bass_start_pc"], r["bass_mid_pc"]) == (7, 7), r
    assert r["recommendation"] == "single", r
    print("ok: bass pc is taken from the lowest note, not the smallest pc number")


def test_real_bass_change_still_splits():
    r = analyze_measure(measure([chord(0, [36, 43]), chord(960, [41, 48])]))  # C2 -> F2
    assert (r["bass_start_pc"], r["bass_mid_pc"]) == (0, 5), r
    assert r["recommendation"] == "split", r
    print("ok: a real bass change at the half-bar still splits")


def test_chord_without_pitches_does_not_crash():
    r = analyze_measure(measure([chord(0, []), chord(960, [])]))
    assert (r["bass_start_pc"], r["bass_mid_pc"]) == (None, None), r
    assert r["recommendation"] == "single", r
    print("ok: a bass chord with no pitches yields None, not a crash")


if __name__ == "__main__":
    test_same_bass_note_is_not_a_harmony_change()
    test_real_bass_change_still_splits()
    test_chord_without_pitches_does_not_crash()
