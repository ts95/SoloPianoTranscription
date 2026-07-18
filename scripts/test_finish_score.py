"""Regression test: harmony-pedal schedule -> CC64 in a MIDI.

Run: .venv/bin/python scripts/test_finish_score.py
"""
import json
import os
import tempfile

import pretty_midi

from finish_score import make_anacrusis, strip_beam_modes, write_midi_pedal
from musescore_lib import make_syncopated_pedal_config


def test_cc64_from_schedule():
    with tempfile.TemporaryDirectory() as d:
        mid = os.path.join(d, "t.mid")
        beats_json = os.path.join(d, "beats.json")
        # 120 BPM: beat k at k * 0.5 s; 3 bars of 4/4
        json.dump({"beats": [k * 0.5 for k in range(16)]}, open(beats_json, "w"))
        pm = pretty_midi.PrettyMIDI(initial_tempo=120)
        inst = pretty_midi.Instrument(program=0)
        inst.notes.append(pretty_midi.Note(velocity=80, pitch=60,
                                           start=0.0, end=6.0))
        # stale transcriber pedal that must be replaced
        inst.control_changes.append(pretty_midi.ControlChange(64, 127, 5.0))
        pm.instruments.append(inst)
        pm.write(mid)

        cfg = make_syncopated_pedal_config(1920, split_measures={2})
        n = write_midi_pedal(mid, cfg, [1, 2, 3], {1: 1920, 2: 1920, 3: 1920},
                             beats_json)
        assert n == 4, f"expected 4 pedal regions (1 + split 2 + 1), got {n}"

        out = pretty_midi.PrettyMIDI(mid)
        ccs = [c for c in out.instruments[0].control_changes if c.number == 64]
        assert not any(abs(c.time - 5.0) < 1e-6 for c in ccs), (
            "stale transcriber CC64 not replaced")
        downs = [c.time for c in ccs if c.value >= 64]
        # gap = 60 ticks = 1/8 beat = 0.0625 s at 120 BPM
        expected = [0.0625, 2.0625, 3.0625, 4.0625]
        # pretty_midi rounds event times to its tick grid on write (~2.3 ms)
        assert all(abs(a - b) < 0.005 for a, b in zip(sorted(downs), expected)), (
            f"pedal-down times {sorted(downs)} != {expected}")
    print("ok: harmony pedal schedule lands as CC64 at the right seconds")


def test_strip_beam_modes():
    import xml.etree.ElementTree as ET
    root = ET.fromstring(
        "<Score><Staff><Measure><voice>"
        "<Chord><BeamMode>no</BeamMode><durationType>16th</durationType></Chord>"
        "<Chord><BeamMode>begin16</BeamMode><durationType>16th</durationType></Chord>"
        "<Chord><durationType>eighth</durationType></Chord>"
        "</voice></Measure></Staff></Score>")
    strip_beam_modes(root)
    assert not list(root.iter("BeamMode")), "BeamMode elements survived"
    assert len(list(root.iter("Chord"))) == 3, "a Chord went missing"
    print("ok: strip_beam_modes removes every forced BeamMode, keeps chords")


def test_make_anacrusis():
    import xml.etree.ElementTree as ET
    xml = """<museScore><Score>
      <Staff id="1"><Measure><voice>
        <Clef><concertClefType>G</concertClefType></Clef>
        <TimeSig><sigN>4</sigN><sigD>4</sigD></TimeSig>
        <Rest><durationType>half</durationType></Rest>
        <Rest><durationType>quarter</durationType></Rest>
        <Chord><durationType>16th</durationType></Chord>
      </voice></Measure></Staff>
      <Staff id="2"><Measure><voice>
        <TimeSig><sigN>4</sigN><sigD>4</sigD></TimeSig>
        <Rest><durationType>half</durationType></Rest>
        <Rest><durationType>quarter</durationType></Rest>
        <Rest><durationType>16th</durationType></Rest>
        <Chord><durationType>16th</durationType></Chord>
      </voice></Measure></Staff>
    </Score></museScore>"""
    root = ET.fromstring(xml)
    make_anacrusis(root, 3)
    for staff in root.iter("Staff"):
        m1 = staff.find("Measure")
        assert m1.get("len") == "1/4", f"len={m1.get('len')}"
        assert m1.findtext("irregular") == "1"
        rests = m1.findall("voice/Rest")
        # staff 1 keeps none, staff 2 keeps its in-pickup 16th rest
        assert all(r.findtext("durationType") == "16th" for r in rests)
    assert len(list(root.iter("Chord"))) == 2
    print("ok: anacrusis strips pad rests, shrinks measure, keeps pickup content")


def test_strip_layout_and_labels():
    import xml.etree.ElementTree as ET
    from finish_score import strip_layout_and_labels
    root = ET.fromstring(
        "<museScore><Score>"
        "<Part><Instrument><longName>Piano</longName>"
        "<shortName>Pno</shortName></Instrument></Part>"
        "<Staff id=\"1\"><Measure><LayoutBreak><subtype>line</subtype>"
        "</LayoutBreak><voice/></Measure></Staff>"
        "</Score></museScore>")
    strip_layout_and_labels(root)
    assert not list(root.iter("LayoutBreak"))
    assert not list(root.iter("longName")) and not list(root.iter("shortName"))
    print("ok: stale layout breaks and instrument labels stripped")


if __name__ == "__main__":
    test_cc64_from_schedule()
    test_strip_beam_modes()
    test_make_anacrusis()
    test_strip_layout_and_labels()
