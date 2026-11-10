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


def seq(pairs, time_sig="4/4", ticks=1920):
    m = measure([note(t, p) for t, p in pairs])
    m["time_sig"], m["ticks"] = time_sig, ticks
    return analyze_measure(m)["split_ticks"]


def test_bass_arrivals_anywhere_in_the_bar():
    # off-beat drop: tenor run C4 D4 Eb4 C4, then the bass G2 lands on the "and" of beat 2
    assert seq([(0, 60), (120, 62), (240, 63), (480, 60), (720, 43), (840, 50), (1080, 58)]) == [720]
    # one pedal per bass in a walking line: C2 | A1 | F1 | G1 (each a drop or a non-triad rise)
    assert seq([(0, 36), (480, 33), (960, 29), (1440, 31)]) == [480, 960, 1440]
    # 3/4 now splits on a beat too: C2 G2 | F2 C3 | (beat 3 continues F)
    assert seq([(0, 36), (240, 43), (480, 41), (720, 48), (960, 45)], "3/4", 1440) == [480]
    print("ok: a new bass splits wherever it lands — off the beat, on every beat, in 3/4")


def test_pedal_segments_are_at_least_a_beat():
    # a deeper drop within a beat of the previous drop MOVES the split (E3 at 600, then B2 at 840)
    assert seq([(0, 64), (120, 61), (360, 57), (600, 52), (840, 47), (1080, 54)]) == [840]
    # a new bass in the last fraction of the bar (anticipating the next bar) does not split
    assert seq([(0, 43), (480, 50), (960, 55), (1680, 41)]) == []
    print("ok: no pedal segment is shorter than a beat")


def test_leap_to_a_tone_of_the_same_chord_is_not_a_new_bass():
    # C#4 leaps down to E3 (still C#m), then B2 F#3: ONE change, at the real new bass
    assert seq([(0, 61), (480, 52), (960, 47), (1440, 54)]) == [960]
    # ...but a same-chord drop into the bass register is a bass: Ab1 Ab2 | Eb1 Eb2
    assert seq([(0, 32), (120, 44), (960, 27), (1080, 39)]) == [960]
    print("ok: a quarter-note left hand leaping within one chord is not re-pedalled on every beat")


def test_pickup_bar_uses_its_real_length():
    import os
    import tempfile
    from musescore_pedal_lib import extract_measure_data
    mscx = ('<museScore><Score><Staff id="2">'
            '<Measure len="1/2"><voice><TimeSig><sigN>4</sigN><sigD>4</sigD></TimeSig></voice></Measure>'
            '<Measure><voice/></Measure></Staff></Score></museScore>')
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "s.mscx")
        with open(path, "w") as f:
            f.write(mscx)
        ms = extract_measure_data(path, staff_ids=("2",))
    assert [m["ticks"] for m in ms] == [960, 1920], ms
    print("ok: a pickup bar reports its real length, so no pedal runs past its end")


if __name__ == "__main__":
    test_pickup_bar_uses_its_real_length()
    test_leap_to_a_tone_of_the_same_chord_is_not_a_new_bass()
    test_bass_arrivals_anywhere_in_the_bar()
    test_pedal_segments_are_at_least_a_beat()
    test_arpeggiated_single_harmony_is_not_split()
    test_new_bass_on_the_half_bar_splits_under_an_arpeggio()
    test_empty_bass_staff_is_not_split()
    test_same_bass_note_is_not_a_harmony_change()
    test_real_bass_change_still_splits()
    test_chord_without_pitches_does_not_crash()
