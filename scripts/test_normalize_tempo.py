"""Regression test: normalize_tempo forces ONE constant tempo, on DuET and MuseScore files.

Run: .venv/bin/python scripts/test_normalize_tempo.py
"""
import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

from normalize_tempo import normalize_tempo

MARK = ('<direction placement="above"><direction-type><metronome><beat-unit>quarter</beat-unit>'
        '<per-minute>{0}</per-minute></metronome></direction-type><staff>1</staff>'
        '<sound tempo="{0}"/></direction>')
DYN = '<direction><direction-type><dynamics><mp/></dynamics></direction-type><staff>1</staff></direction>'
HIDDEN = '<direction><direction-type><words/></direction-type><staff>1</staff><sound tempo="150"/></direction>'
RIT = '<direction><direction-type><words font-style="italic">rit.</words></direction-type><staff>1</staff></direction>'
DUET = ('<score-partwise><part id="P1"><measure number="1">' + MARK.format(141) + DYN + '</measure>'
        '<measure number="2">' + HIDDEN + RIT + '</measure>'
        '<measure number="3">' + MARK.format(153) + '</measure></part></score-partwise>')
MUSESCORE = '''<score-partwise version="4.0">
  <part id="P1">
    <measure number="1" width="244.72">
      <direction placement="above">
        <direction-type>
          <metronome parentheses="no" default-x="-37.68" relative-y="20">
            <beat-unit>quarter</beat-unit>
            <beat-unit-dot/>
            <per-minute>61</per-minute>
            </metronome>
          </direction-type>
        <staff>1</staff>
        <sound tempo="91.5"/>
        </direction>
      </measure>
    </part>
  </score-partwise>'''


def state(root):
    return ([m.findtext("per-minute") for m in root.iter("metronome")],
            [s.get("tempo") for s in root.iter("sound") if s.get("tempo")])


def test_duet_score_gets_one_constant_tempo():
    root = ET.fromstring(DUET)
    report = normalize_tempo(root, 93)
    assert state(root) == (["93"], ["93"]), state(root)
    assert [w.text for w in root.iter("words")] == ["rit."] and root.find(".//dynamics") is not None
    assert [len(m.findall("direction")) for m in root.iter("measure")] == [2, 1, 0]
    assert report == {"bpm": 93, "metronome_marks_removed": 1,
                      "sound_tempos_removed": 2, "empty_directions_removed": 2}, report
    print("ok: one metronome mark, one playback tempo, hidden changes gone, rit./dynamics kept")


def test_musescore_export_is_accepted():
    root = ET.fromstring(MUSESCORE)
    normalize_tempo(root, 93)
    mark = root.find(".//metronome")
    assert state(root) == (["93"], ["93"]) and mark.find("beat-unit-dot") is None
    assert mark.get("parentheses") == "no"
    print("ok: a MuseScore export (attributes, dotted-quarter mark) is normalized to quarter = N")


def test_no_metronome_is_an_error():
    try:
        normalize_tempo(ET.fromstring('<score-partwise><part id="P1"><measure number="1"/></part></score-partwise>'), 93)
    except ValueError as e:
        assert "metronome" in str(e)
    else:
        raise AssertionError("expected ValueError")
    print("ok: a score with no metronome mark raises instead of silently succeeding")


def test_cli():
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "normalize_tempo.py")
    with tempfile.TemporaryDirectory() as td:
        good, bad, out = (os.path.join(td, n) for n in ("good.xml", "bad.xml", "out.xml"))
        with open(good, "w") as f:
            f.write('<?xml version="1.0" encoding="UTF-8"?>\n' + DUET)
        with open(bad, "w") as f:
            f.write('<score-partwise><part id="P1"><measure number="1"/></part></score-partwise>')
        r = subprocess.run([sys.executable, script, good, out, "--tempo", "92.6"], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        with open(out) as f:
            text = f.read()
        assert text.startswith('<?xml version="1.0" encoding="UTF-8"?>') and "<per-minute>93</per-minute>" in text
        os.remove(out)
        r = subprocess.run([sys.executable, script, bad, out, "--tempo", "93"], capture_output=True, text=True)
        assert r.returncode == 1 and not os.path.exists(out), (r.returncode, r.stderr)
    print("ok: CLI keeps the XML declaration, rounds --tempo, exits 1 and writes nothing on error")


if __name__ == "__main__":
    test_duet_score_gets_one_constant_tempo()
    test_musescore_export_is_accepted()
    test_no_metronome_is_an_error()
    test_cli()
