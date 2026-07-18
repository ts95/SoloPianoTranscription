"""Regression test: harmony-pedal schedule -> CC64 in a MIDI.

Run: .venv/bin/python scripts/test_midi_pedal.py
"""
import json
import os
import tempfile

import pretty_midi

from apply_harmony_pedal import strip_beam_modes, write_midi_pedal
from musescore_pedal_lib import make_syncopated_pedal_config


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


if __name__ == "__main__":
    test_cc64_from_schedule()
    test_strip_beam_modes()
