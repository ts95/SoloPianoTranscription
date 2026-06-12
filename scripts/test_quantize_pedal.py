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


if __name__ == "__main__":
    test_pedal_smear_not_engraved()
    test_pedal_marks_from_mid()
