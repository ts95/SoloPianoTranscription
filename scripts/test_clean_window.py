"""clean --keep-window: strip jingles, re-zero, report the shift.
Run: .venv/bin/python scripts/test_clean_window.py"""
import json
import os
import subprocess
import sys
import tempfile

import pretty_midi

SCRIPT = os.path.join(os.path.dirname(__file__), "transcription_cleanup.py")
PY = sys.executable


def test_keep_window():
    with tempfile.TemporaryDirectory() as d:
        mid = os.path.join(d, "t.mid")
        out = os.path.join(d, "t.cleaned.mid")
        pm = pretty_midi.PrettyMIDI(initial_tempo=120)
        inst = pretty_midi.Instrument(program=0)
        for t in (0.0, 1.0):                       # intro jingle
            inst.notes.append(pretty_midi.Note(80, 72, t, t + 0.3))
        for k in range(16):                        # arrangement: 5.0 .. 13.0
            t = 5.0 + k * 0.5
            inst.notes.append(pretty_midi.Note(80, 60, t, t + 0.3))
        for t in (20.0, 21.0):                     # outro jingle
            inst.notes.append(pretty_midi.Note(80, 84, t, t + 0.3))
        inst.control_changes.append(pretty_midi.ControlChange(64, 100, 5.1))
        inst.control_changes.append(pretty_midi.ControlChange(64, 0, 12.0))
        inst.control_changes.append(pretty_midi.ControlChange(64, 100, 20.5))
        pm.instruments.append(inst)
        pm.write(mid)
        r = subprocess.run(
            [PY, SCRIPT, "clean", mid, out, "--keep-window", "4.5:14.0"],
            capture_output=True, text=True, check=True)
        s = json.loads(r.stdout)
        assert s["kept_notes"] == 16, s["kept_notes"]
        kw = s["keep_window"]
        # first onset was 0.0 -> trim shift 0; window start 5.0 becomes t=0
        assert abs(kw["extra_shift_s"] - 5.0) < 0.01, kw
        out_pm = pretty_midi.PrettyMIDI(out)
        notes = [n for i in out_pm.instruments for n in i.notes]
        assert abs(min(n.start for n in notes)) < 0.01
        ccs = [c for i in out_pm.instruments for c in i.control_changes
               if c.number == 64]
        assert ccs and all(c.time < 8.0 for c in ccs), (
            "outro CC64 must be stripped")
    print("ok: keep-window strips, re-zeros, reports the shift")


if __name__ == "__main__":
    test_keep_window()
