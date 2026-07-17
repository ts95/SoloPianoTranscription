"""Regression test: post's key-change collection guard.

A chord-emphasis region inside the incumbent key (G-heavy bars in C major)
must NOT trigger a key-signature change; a region that leaves the collection
(E major bars) MUST. Run: .venv/bin/python scripts/test_modulation_guard.py
"""
import json
import os
import subprocess
import sys
import tempfile

import pretty_midi

SCRIPT = os.path.join(os.path.dirname(__file__), "transcription_cleanup.py")
PY = sys.executable


def add_bar_chords(inst, bar_start, pitch_sets):
    """One chord per beat (120 BPM, beat=0.5s), each pitch set one beat."""
    for k, ps in enumerate(pitch_sets):
        t = bar_start + k * 0.5
        for p in ps:
            inst.notes.append(pretty_midi.Note(velocity=80, pitch=p,
                                               start=t, end=t + 0.45))


def test_guard():
    with tempfile.TemporaryDirectory() as d:
        mid = os.path.join(d, "t.mid")
        xml = os.path.join(d, "t.musicxml")
        out = os.path.join(d, "t.post.musicxml")
        pm = pretty_midi.PrettyMIDI(initial_tempo=120)
        inst = pretty_midi.Instrument(program=0)
        C = [(48, 60, 64, 67)] * 4          # C major bar
        G = [(43, 55, 59, 62)] * 4          # G-emphasis bar (all in C)
        E = [(40, 56, 59, 64), (40, 52, 56, 63)] * 2  # E major bar (G#, C#)
        E = [(40, 52, 56, 61), (44, 52, 59, 64)] * 2  # E, G#, C#, B
        bars = [C] * 10 + [G] * 16 + [C] * 4 + [E] * 16 + [C] * 10
        for b, chords in enumerate(bars):
            add_bar_chords(inst, b * 2.0, chords)
        pm.instruments.append(inst)
        pm.write(mid)

        subprocess.run([PY, SCRIPT, "quantize", mid, xml, "--bpm", "120",
                        "--time-sig", "4/4", "--bar-phase", "0",
                        "--key", "C major"],
                       capture_output=True, text=True, check=True)
        r = subprocess.run([PY, SCRIPT, "post", xml, out, "--key", "C major",
                            "--time-sig", "4/4", "--dynamics-from", mid],
                           capture_output=True, text=True, check=True)
        summary = json.loads(r.stdout)
        flags = summary.get("modulation_flags", [])
        skipped = [f for f in flags if "skipped" in f]
        engraved_sharps = set()
        from music21 import converter, key as m21key
        for k in converter.parse(out).recurse().getElementsByClass(
                m21key.KeySignature):
            engraved_sharps.add(k.sharps)
        assert 4 in engraved_sharps, (
            f"real E-major modulation not engraved: {engraved_sharps}, {flags}")
        assert 1 not in engraved_sharps and -1 not in engraved_sharps, (
            f"emphasis region engraved as key change: {engraved_sharps}")
    print("ok: emphasis regions skipped, real modulations engraved")


if __name__ == "__main__":
    test_guard()
