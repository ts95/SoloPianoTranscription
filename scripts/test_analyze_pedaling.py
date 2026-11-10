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


def note(tick, pitch, dur=240):
    return {"type": "Chord", "tick": tick, "dur": dur, "pitches": [pitch], "pcs": [pitch % 12]}


def test_arpeggiated_single_harmony_is_not_split():
    # G#m arpeggio: the half-bar note (B3) is a chord tone far above the bass
    arp = [44, 51, 56, 51, 59, 51, 56, 51]  # Ab2 Eb3 Ab3 Eb3 | B3 Eb3 Ab3 Eb3
    r = analyze_measure(measure([note(i * 240, p) for i, p in enumerate(arp)]))
    assert r["recommendation"] == "single", r
    # quarter-note arpeggio whose root never returns: Db3+Db4, Ab3 | E4, Ab3
    r = analyze_measure(measure([chord(0, [49, 61]), note(480, 56), note(960, 64), note(1440, 56)]))
    assert r["recommendation"] == "single", r
    # the bass returns late in the bar, after a chord tone on the half-bar: ... | Db4 Ab3 Db2 Ab2
    late = [37, 44, 52, 56, 61, 56, 37, 44]
    r = analyze_measure(measure([note(i * 240, p) for i, p in enumerate(late)]))
    assert r["recommendation"] == "single", r
    print("ok: an arpeggiated single harmony is one pedal, not a split")


def test_new_bass_on_the_half_bar_splits_under_an_arpeggio():
    # G#m -> D#: Ab1 Ab2 | Eb1 Eb2 (new bass struck on the half-bar, below the old one)
    r = analyze_measure(measure([note(0, 32), note(120, 44), note(960, 27), note(1080, 39)]))
    assert r["recommendation"] == "split", r
    print("ok: a new bass note landing on the half-bar still splits")


def test_empty_bass_staff_is_not_split():
    m = {"number": 1, "time_sig": "4/4", "ticks": 1920, "staves": {
        "1": {"voices": {"1": [note(0, 72), note(960, 76)]}},
        "2": {"voices": {"1": [{"type": "Rest", "tick": 0, "dur": 1920}]}}}}
    assert analyze_measure(m)["recommendation"] == "single"
    print("ok: a bar with an empty bass staff is not split on the melody")


if __name__ == "__main__":
    test_arpeggiated_single_harmony_is_not_split()
    test_new_bass_on_the_half_bar_splits_under_an_arpeggio()
    test_empty_bass_staff_is_not_split()
    test_same_bass_note_is_not_a_harmony_change()
    test_real_bass_change_still_splits()
    test_chord_without_pitches_does_not_crash()
