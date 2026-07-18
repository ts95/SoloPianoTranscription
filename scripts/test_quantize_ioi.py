"""IOI-ratio re-seat: equal played IOIs must engrave as equal values.

The dragged-run pattern: onsets at beats 0.0, 0.32, 0.63, 0.95 (near-equal
played IOIs, ~0.317 beat apart) currently snap per-onset to 0.0/0.25/0.75/1.0
-- an uneven 0.25/0.5/0.25 split (the middle gap is 2x the others) because
the note at 0.63 lands just past the tolerance boundary between the 0.5 and
0.75 grid slots. The re-seat must land the run on equal 0.25 steps:
0.0/0.25/0.5/0.75. Run: .venv/bin/python scripts/test_quantize_ioi.py

NOTE: the brief's illustrative numbers (0.88/1.15/1.42, engraved as
0.75/1.25/1.5) do not reproduce under the current per-beat division
selection: with only two onsets in beat 0 (0.0 and 0.88), best_div commits
that beat to division 1, and 0.88 rounds up to the *next full beat* (1.0)
under nearest-rounding at every division from 1 to 4 alike -- it is simply
closer to 1.0 (distance 0.12) than to 0.75 (distance 0.13). The resulting
per-onset snap (0.0/1.0/1.25/1.5) is already uniformly spaced (0.25 apart),
so there is nothing for the re-seat to fix. The fixture below was verified
against the actual `snap`/`best_div` pipeline to reproduce a genuine
ratio->=2x split, which is what the re-seat's Global Constraints target.
"""
import json
import os
import subprocess
import sys
import tempfile

import pretty_midi

SCRIPT = os.path.join(os.path.dirname(__file__), "transcription_cleanup.py")
PY = sys.executable


def test_equal_iois_engrave_equal():
    with tempfile.TemporaryDirectory() as d:
        mid = os.path.join(d, "t.mid")
        out = os.path.join(d, "t.musicxml")
        pm = pretty_midi.PrettyMIDI(initial_tempo=60)   # beat = 1 s
        inst = pretty_midi.Instrument(program=0)
        for bar in range(4):
            t0 = bar * 4.0
            # the dragged equal-IOI figure, then on-grid filler
            for t in (0.0, 0.32, 0.63, 0.95, 2.0, 3.0):
                inst.notes.append(pretty_midi.Note(80, 72, t0 + t, t0 + t + 0.15))
            inst.notes.append(pretty_midi.Note(85, 40, t0, t0 + 0.5))
        pm.instruments.append(inst)
        pm.write(mid)
        r = subprocess.run([PY, SCRIPT, "quantize", mid, out, "--bpm", "60",
                            "--time-sig", "4/4", "--bar-phase", "0",
                            "--no-repeat-align"],
                           capture_output=True, text=True, check=True)
        s = json.loads(r.stdout)
        assert s.get("ioi_reseated", {}).get("count", 0) >= 4, s.get("ioi_reseated")
        from music21 import converter
        treble = converter.parse(out).parts[0]
        m = treble.measure(1)
        offs = sorted(float(n.offset) for n in m.recurse().notes)
        assert offs[:4] == [0.0, 0.25, 0.5, 0.75], f"got {offs[:4]}"
    print("ok: equal played IOIs re-seated onto equal slots")


if __name__ == "__main__":
    test_equal_iois_engrave_equal()
