"""A short held note in a busy texture must NOT spawn a second voice.

A second voice costs padding rests in both voices, so it is only worth it for a
genuine pedal point — a note that rings a HALF NOTE or longer over moving notes
in another register of the same staff. A note held ~1 beat (common in dense or
sequenced arrangements) must be capped into a single voice, or the staff fills
with rest spray. The trigger is a LOW held note ringing over a moving higher
bass line (not a repeated same-pitch note).

Run: .venv/bin/python scripts/test_voicing.py
"""
import json
import os
import subprocess
import sys
import tempfile

import pretty_midi

SCRIPT = os.path.join(os.path.dirname(__file__), "transcription_cleanup.py")
PY = sys.executable


def _make(path, low_hold_beats):
    """beat = 0.5 s at 120 BPM. Bass staff: a low note (pitch 40) held
    low_hold_beats, ringing over a moving higher bass line (52-55) — both below
    the C4 split, so both land in the bass staff. Plus a high treble melody.
    No pedal."""
    pm = pretty_midi.PrettyMIDI(initial_tempo=120)
    inst = pretty_midi.Instrument(program=0)
    for k in range(16):  # treble eighths, 2 bars
        t = k * 0.25
        inst.notes.append(pretty_midi.Note(78, 72 + (k % 3), t, t + 0.24))
    for bar in range(2):
        base = bar * 2.0
        inst.notes.append(pretty_midi.Note(85, 40, base, base + low_hold_beats * 0.5))
        for j, p in enumerate((52, 54, 55)):  # moving higher bass line, on beats 2,3,4
            t = base + 0.5 * (j + 1)
            inst.notes.append(pretty_midi.Note(80, p, t, t + 0.45))
    pm.instruments.append(inst)
    pm.write(path)


def _sustained(mid):
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "o.musicxml")
        r = subprocess.run([PY, SCRIPT, "quantize", mid, out, "--bpm", "120",
                            "--time-sig", "4/4", "--split", "C4", "--bar-phase", "0"],
                           capture_output=True, text=True, check=True)
        s = json.loads(r.stdout)["staves"]
        return sum(v["sustained_as_second_voice"] for v in s.values())


def test_short_hold_does_not_spawn_second_voice():
    with tempfile.TemporaryDirectory() as d:
        mid = os.path.join(d, "t.mid")
        _make(mid, low_hold_beats=1.5)   # rings over one moving note — sub-half-note
        n = _sustained(mid)
        assert n == 0, f"{n} short (1.5-beat) holds wrongly engraved as a 2nd voice"
    print("ok: a ~1-beat hold over a moving bass line stays single-voice")


def test_long_pedal_point_keeps_second_voice():
    with tempfile.TemporaryDirectory() as d:
        mid = os.path.join(d, "t.mid")
        _make(mid, low_hold_beats=3.0)   # half-note+ pedal point over the line
        n = _sustained(mid)
        assert n >= 1, "genuine half-note+ pedal point lost its second voice"
    print("ok: a half-note+ pedal point still earns a second voice")


if __name__ == "__main__":
    test_short_hold_does_not_spawn_second_voice()
    test_long_pedal_point_keeps_second_voice()
    print("all voicing tests passed")
