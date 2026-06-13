"""Regression test: pedal smear must not become engraved held notes.

Run: .venv/bin/python scripts/test_quantize_pedal.py
With the sustain pedal down, the transcriber reports acoustic ring (seconds
of "duration") rather than finger holds. Quantize must not legato-fill a
sparse stab across its multi-beat silence (drone instead of groove), nor
keep a pedal-carried ring as a sustained second voice (voice/rest spray) —
the pedal marks already convey the sustain.
"""
import json
import os
import subprocess
import sys
import tempfile

import pretty_midi

SCRIPT = os.path.join(os.path.dirname(__file__), "transcription_cleanup.py")
PY = sys.executable


def make_midi(path):
    pm = pretty_midi.PrettyMIDI(initial_tempo=120)
    inst = pretty_midi.Instrument(program=0)
    # RH: continuous eighths for 8 bars (120 BPM, 4/4 -> bar = 2 s)
    for k in range(64):
        t = k * 0.25
        inst.notes.append(pretty_midi.Note(velocity=80, pitch=72 + (k % 2) * 2,
                                           start=t, end=t + 0.6))
    # LH: one stab per bar, pedal ring smearing most of the bar
    for b in range(8):
        t = b * 2.0
        inst.notes.append(pretty_midi.Note(velocity=90, pitch=36,
                                           start=t, end=t + 1.8))
    # one extreme ring crossing several bars (would trigger sustained-voice-2)
    inst.notes.append(pretty_midi.Note(velocity=85, pitch=33,
                                       start=4.0, end=11.0))
    # sustain pedal down for the whole piece
    inst.control_changes.append(pretty_midi.ControlChange(64, 100, 0.0))
    inst.control_changes.append(pretty_midi.ControlChange(64, 0, 16.5))
    pm.instruments.append(inst)
    pm.write(path)


def test_pedal_marks_from_mid():
    """post --pedal-from <mid>: the engraved pedal must reflect the MIDI's
    actual CC64 regions, with no clean-report JSON required (stage 3)."""
    with tempfile.TemporaryDirectory() as d:
        mid = os.path.join(d, "t.mid")
        xml = os.path.join(d, "t.musicxml")
        out = os.path.join(d, "t.pedal.musicxml")
        make_midi(mid)
        subprocess.run([PY, SCRIPT, "quantize", mid, xml, "--bpm", "120",
                        "--time-sig", "4/4", "--bar-phase", "0"],
                       capture_output=True, text=True, check=True)
        r = subprocess.run([PY, SCRIPT, "post", xml, out, "--pedal-from", mid],
                           capture_output=True, text=True, check=True)
        summary = json.loads(r.stdout)
        assert summary["pedal_marks"] == 1, (
            f"expected 1 pedal mark for the single CC64 region, "
            f"got {summary['pedal_marks']} (note: {summary.get('pedal_note')})")
        assert_pedal_on_bass_staff(open(out).read())

        # the re-bar path (cleanup flow) exports one merged 2-staff part —
        # there the pedal directions must carry <staff>2</staff>
        out2 = os.path.join(d, "t.rebar.musicxml")
        r = subprocess.run([PY, SCRIPT, "post", xml, out2, "--time-sig", "4/4",
                            "--pedal-from", mid],
                           capture_output=True, text=True, check=True)
        assert json.loads(r.stdout)["pedal_marks"] == 1
        assert_pedal_on_bass_staff(open(out2).read())
    print("ok: pedal engraved as bass-staff lines from the MIDI's CC64")


def assert_pedal_on_bass_staff(xml_text):
    """Pedal must be engraved as a line and attributed to the bass staff,
    whatever the part structure (merged 2-staff part or two parts)."""
    import re
    assert "<pedal" in xml_text, "no <pedal> direction in MusicXML"
    assert 'line="yes"' in xml_text, "pedal not engraved as a line"
    for m in re.finditer(r"<direction[^>]*>(?:(?!</direction>).)*?<pedal",
                         xml_text, re.S):
        block = xml_text[m.start():xml_text.index("</direction>", m.start())]
        staff = re.search(r"<staff>(\d+)</staff>", block)
        if staff:  # merged 2-staff part: explicit staff attribution
            assert staff.group(1) == "2", (
                f"pedal direction on staff {staff.group(1)}, not bass: {block[:200]}")
        else:      # two single-staff parts: must sit in the low (bass) part
            part_start = xml_text.rfind("<part ", 0, m.start())
            part_end = xml_text.find("</part>", m.start())
            octaves = [int(o) for o in re.findall(
                r"<octave>(\d)</octave>", xml_text[part_start:part_end])]
            assert octaves and max(octaves) <= 4, (
                "pedal direction in a part that is not the bass staff "
                f"(octaves {sorted(set(octaves))})")


def test_pedal_smear_not_engraved():
    with tempfile.TemporaryDirectory() as d:
        mid = os.path.join(d, "t.mid")
        xml = os.path.join(d, "t.musicxml")
        make_midi(mid)
        out = subprocess.run(
            [PY, SCRIPT, "quantize", mid, xml, "--bpm", "120",
             "--time-sig", "4/4", "--bar-phase", "0"],
            capture_output=True, text=True, check=True)
        summary = json.loads(out.stdout)

        sustained = sum(s["sustained_as_second_voice"]
                        for s in summary["staves"].values())
        assert sustained == 0, (
            f"pedal-carried ring engraved as sustained second voice x{sustained}")

        from music21 import converter, stream
        score = converter.parse(xml)
        bass = score.parts[-1]
        too_long = [(n.measureNumber, float(n.duration.quarterLength))
                    for n in bass.recurse().notes
                    if n.duration.quarterLength > 1.0]
        assert not too_long, (
            f"bass stabs legato-filled across their silences (drones): {too_long}")
    print("ok: no pedal-smear sustains, no drone fills")


def make_pedal_fill_midi(path):
    """Under a held sustain pedal, a note released early before a *moderate*
    gap to the next onset must fill the gap (a longer note), not become
    note+rest — a rest under pedal is acoustically impossible (the strings
    ring). Bass stabs every 1.5 beats (> the 1.25-beat legato threshold),
    released after 0.4 beat, pedal down throughout. Distinct from the drone
    case: the gap is moderate (1.5 beat), not a multi-beat sparse silence."""
    pm = pretty_midi.PrettyMIDI(initial_tempo=120)  # beat = 0.5 s
    inst = pretty_midi.Instrument(program=0)
    # Treble: a clear sustained melody note per bar so the treble staff exists.
    for b in range(4):
        inst.notes.append(pretty_midi.Note(velocity=80, pitch=72,
                                           start=b * 2.0, end=b * 2.0 + 1.8))
    # Bass: stabs 0.75 s (1.5 beats) apart, key released after 0.2 s (0.4 beat).
    t = 0.0
    while t < 7.0:
        inst.notes.append(pretty_midi.Note(velocity=85, pitch=40,
                                           start=t, end=t + 0.2))
        t += 0.75
    inst.control_changes.append(pretty_midi.ControlChange(64, 100, 0.0))
    inst.control_changes.append(pretty_midi.ControlChange(64, 0, t + 0.5))
    pm.instruments.append(inst)
    pm.write(path)


def test_pedal_fills_short_gaps_no_rest():
    with tempfile.TemporaryDirectory() as d:
        mid = os.path.join(d, "t.mid")
        out = os.path.join(d, "t.musicxml")
        make_pedal_fill_midi(mid)
        r = subprocess.run([PY, SCRIPT, "quantize", mid, out, "--bpm", "120",
                            "--time-sig", "4/4", "--split", "C4", "--bar-phase", "0"],
                           capture_output=True, text=True, check=True)
        summary = json.loads(r.stdout)

        from music21 import converter
        score = converter.parse(out)
        bass = score.parts[-1]
        notes = list(bass.recurse().notes)
        rests = list(bass.recurse().getElementsByClass("Rest"))
        assert notes, "no bass notes engraved"
        maxql = max(float(n.duration.quarterLength) for n in notes)
        assert maxql >= 1.25, (
            f"bass notes not filled under pedal — max quarterLength {maxql} "
            "(clipped to a beat + rest instead of a held note)")
        last_note_off = max(n.getOffsetInHierarchy(score) for n in notes)
        interior = [r for r in rests
                    if r.getOffsetInHierarchy(score) < last_note_off]
        assert not interior, (
            f"{len(interior)} interior rest(s) under sustained pedal — "
            "acoustically impossible; the note should fill the gap")
        assert summary["staves"]["bass"].get("pedal_gap_filled", 0) > 0, (
            "summary does not report any under-pedal gap fills")
    print("ok: rests under sustained pedal filled into held notes")


if __name__ == "__main__":
    test_pedal_smear_not_engraved()
    test_pedal_marks_from_mid()
    test_pedal_fills_short_gaps_no_rest()
