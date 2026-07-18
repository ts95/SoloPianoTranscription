"""score_query map/bar on a synthetic pickup piece.
Run: .venv/bin/python scripts/test_score_query.py"""
import json
import os
import subprocess
import sys
import tempfile

import pretty_midi

HERE = os.path.dirname(__file__)
PY = sys.executable


def make_piece(d):
    slug = "fixture"
    pdir = os.path.join(d, slug)
    os.makedirs(pdir)
    S = os.path.join(pdir, slug)
    pm = pretty_midi.PrettyMIDI(initial_tempo=120)
    inst = pretty_midi.Instrument(program=0)
    for k in range(64):
        t = k * 0.5
        inst.notes.append(pretty_midi.Note(80, 60 + (k % 4), t, t + 0.4))
        if k % 2 == 0:
            inst.notes.append(pretty_midi.Note(85, 40, t, t + 0.4))
    pm.instruments.append(inst)
    pm.write(S + ".cleaned.mid")
    json.dump({"beats": [k * 0.5 for k in range(66)]},
              open(os.path.join(pdir, "beats.json"), "w"))
    json.dump({"slug": slug, "key": "C major", "time_sig": "4/4",
               "beats": "beats.json", "beats_shift": 0.0, "title": "F",
               "composer": "T", "performer": None, "arranger": None,
               "anacrusis": 0, "dynamics_from_cleaned_midi": False,
               "quantize_flags": ["--bar-phase", "0"], "post_flags": []},
              open(os.path.join(pdir, "piece.json"), "w"))
    subprocess.run([PY, os.path.join(HERE, "transcription_cleanup.py"),
                    "quantize", S + ".cleaned.mid", S + ".musicxml",
                    "--beats", os.path.join(pdir, "beats.json"),
                    "--bar-phase", "0", "--key", "C major",
                    "--time-sig", "4/4"],
                   capture_output=True, check=True)
    return pdir


def test_map_and_bar():
    with tempfile.TemporaryDirectory() as d:
        pdir = make_piece(d)
        r = subprocess.run([PY, os.path.join(HERE, "score_query.py"),
                            "map", pdir, "3"],
                           capture_output=True, text=True, check=True)
        assert "grid beats" in r.stdout and "8" in r.stdout, r.stdout
        r = subprocess.run([PY, os.path.join(HERE, "score_query.py"),
                            "bar", pdir, "3"],
                           capture_output=True, text=True, check=True)
        assert "P0" in r.stdout and "P1" in r.stdout, (
            "bar view must show BOTH staves:\n" + r.stdout)
        assert "dev" in r.stdout
    print("ok: map + two-staff aligned bar diff")


def test_family_finds_transposed_rhythm_sibling():
    with tempfile.TemporaryDirectory() as d:
        pdir = make_piece(d)   # 16 identical-rhythm bars (transposed content)
        r = subprocess.run([PY, os.path.join(HERE, "score_query.py"),
                            "family", pdir, "3"],
                           capture_output=True, text=True, check=True)
        assert "rhythm" in r.stdout.lower(), r.stdout
        assert "bar 5" in r.stdout or "5" in r.stdout.split(), r.stdout
    print("ok: family reports rhythm siblings")


def test_sweep_runs_clean_on_fixture():
    with tempfile.TemporaryDirectory() as d:
        pdir = make_piece(d)
        r = subprocess.run([PY, os.path.join(HERE, "score_query.py"),
                            "sweep", pdir],
                           capture_output=True, text=True, check=True)
        assert "tie stubs: 0" in r.stdout, r.stdout
        assert "unbalanced" in r.stdout
    print("ok: sweep runs all detectors")


if __name__ == "__main__":
    test_map_and_bar()
    test_family_finds_transposed_rhythm_sibling()
    test_sweep_runs_clean_on_fixture()
