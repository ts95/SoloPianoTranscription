"""Regression test: normalize_tempo forces ONE constant tempo on a raw DuET score.

Run: .venv/bin/python scripts/test_normalize_tempo.py
"""
import os
import subprocess
import sys
import tempfile

from normalize_tempo import normalize_tempo

MARK = ('<direction placement="above"><direction-type><metronome><beat-unit>quarter</beat-unit>'
        '<per-minute>{0}</per-minute></metronome></direction-type><staff>1</staff>'
        '<sound tempo="{0}"/></direction>')
DYN = ('<direction placement="below"><direction-type><dynamics><mp/></dynamics></direction-type>'
       '<staff>1</staff></direction>')
HIDDEN = '<direction><direction-type><words/></direction-type><staff>1</staff><sound tempo="150"/></direction>'
RIT = ('<direction placement="above"><direction-type><words font-style="italic">rit.</words>'
       '</direction-type><staff>1</staff></direction>')

RAW = ('<measure number="1">' + MARK.format(141) + DYN + '</measure>'
       '<measure number="2">' + HIDDEN + RIT + '</measure>'
       '<measure number="3">' + MARK.format(153) + '</measure>')
WANT = ('<measure number="1">' + MARK.format(93) + DYN + '</measure>'
        '<measure number="2">' + RIT + '</measure>'
        '<measure number="3"></measure>')


def test_one_constant_tempo():
    out, report = normalize_tempo(RAW, 93)
    assert out == WANT, out
    assert report == {"bpm": 93, "metronome_marks_removed": 1,
                      "sound_tempos_removed": 2, "empty_directions_removed": 2}, report
    print("ok: one metronome mark, one sound tempo, hidden tempo changes gone, rit./dynamics kept")


def test_no_metronome_is_an_error():
    try:
        normalize_tempo('<measure number="1"><metronome parentheses="no"></metronome></measure>', 93)
    except ValueError as e:
        assert "raw DuET" in str(e), e
    else:
        raise AssertionError("expected ValueError")
    print("ok: a score without a compact <metronome> raises instead of silently succeeding")


def test_cli_exit_codes():
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "normalize_tempo.py")
    with tempfile.TemporaryDirectory() as td:
        good, bad, out = (os.path.join(td, n) for n in ("good.xml", "bad.xml", "out.xml"))
        with open(good, "w") as f:
            f.write(RAW)
        with open(bad, "w") as f:
            f.write('<measure number="1"></measure>')
        r = subprocess.run([sys.executable, script, good, out, "--tempo", "92.6"], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        with open(out) as f:
            assert f.read() == WANT
        os.remove(out)
        r = subprocess.run([sys.executable, script, bad, out, "--tempo", "93"], capture_output=True, text=True)
        assert r.returncode == 1 and not os.path.exists(out), (r.returncode, r.stderr)
    print("ok: CLI rounds --tempo, exits 1 and writes nothing when no metronome is found")


if __name__ == "__main__":
    test_one_constant_tempo()
    test_no_metronome_is_an_error()
    test_cli_exit_codes()
