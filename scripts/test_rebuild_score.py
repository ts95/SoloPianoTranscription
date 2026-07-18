"""rebuild_score drives the chain from piece.json and is reproducible.
Run: .venv/bin/python scripts/test_rebuild_score.py
(Needs MuseScore; skips gracefully when mscore is absent.)"""
import json
import os
import subprocess
import sys
import tempfile

import pretty_midi

HERE = os.path.dirname(__file__)
PY = sys.executable
MSCORE = "/Applications/MuseScore 4.app/Contents/MacOS/mscore"


def test_rebuild_from_manifest():
    if not os.path.exists(MSCORE):
        print("skip: MuseScore not installed")
        return
    with tempfile.TemporaryDirectory() as d:
        slug = "fixture"
        pdir = os.path.join(d, slug)
        os.makedirs(pdir)
        mid = os.path.join(pdir, f"{slug}.cleaned.mid")
        pm = pretty_midi.PrettyMIDI(initial_tempo=120)
        inst = pretty_midi.Instrument(program=0)
        for k in range(32):
            t = k * 0.5
            inst.notes.append(pretty_midi.Note(80, 60 + (k % 8), t, t + 0.4))
        pm.instruments.append(inst)
        pm.write(mid)
        json.dump({"beats": [k * 0.5 for k in range(34)]},
                  open(os.path.join(pdir, "beats.json"), "w"))
        json.dump({"slug": slug, "key": "C major", "time_sig": "4/4",
                   "beats": "beats.json", "beats_shift": 0.0,
                   "title": "Fixture", "composer": "Test",
                   "performer": None, "arranger": None, "anacrusis": 0,
                   "dynamics_from_cleaned_midi": False,
                   "quantize_flags": ["--bar-phase", "0"], "post_flags": []},
                  open(os.path.join(pdir, "piece.json"), "w"))
        # an edits.py that tags its run
        with open(os.path.join(pdir, "edits.py"), "w") as f:
            f.write("import sys\nprint('edits ran')\n")
        r = subprocess.run(
            [PY, os.path.join(HERE, "rebuild_score.py"), pdir,
             "--skip-verify"],
            capture_output=True, text=True)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "edits ran" in r.stdout
        for ext in (".musicxml", ".mscz", ".pdf"):
            assert os.path.getsize(os.path.join(pdir, slug + ext)) > 0, ext
        assert os.path.isdir(os.path.join(pdir, "reports"))
        digest = r.stdout.strip().splitlines()[-1]
        assert "fit" in digest or "lint" in digest, digest
    print("ok: rebuild_score runs the chain from piece.json")


if __name__ == "__main__":
    test_rebuild_from_manifest()
