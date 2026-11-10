"""Regression test: relabel_meter changes the label, the beams and the tempo unit — not the notes.

Run: .venv/bin/python scripts/test_relabel_meter.py
"""
import xml.etree.ElementTree as ET

from relabel_meter import relabel

NOTE = '<note><pitch><step>C</step><octave>4</octave></pitch><duration>12</duration><type>eighth</type>{}</note>'
RAW = ('<score-partwise><identification><encoding><supports element="beam" type="yes"/></encoding></identification>'
       '<part id="P1"><measure number="1"><print new-system="yes"/>'
       '<attributes><time><beats>3</beats><beat-type>4</beat-type></time></attributes>'
       '<direction><direction-type><metronome parentheses="no"><beat-unit>quarter</beat-unit>'
       '<per-minute>92</per-minute></metronome></direction-type><sound tempo="92"/></direction>'
       + NOTE.format('<beam number="1">begin</beam>') + NOTE.format('<beam number="1">end</beam>')
       + '</measure><measure number="2"><attributes><time><beats>4</beats><beat-type>4</beat-type></time>'
       '</attributes></measure></part></score-partwise>')


def test_three_four_becomes_six_eight():
    root = ET.fromstring(RAW)
    report = relabel(root, (3, 4), (6, 8))
    assert [(t.findtext("beats"), t.findtext("beat-type")) for t in root.iter("time")] == [("6", "8"), ("4", "4")]
    assert root.find(".//beam") is None and root.find(".//supports") is None
    assert root.find(".//print").get("new-system") is None
    assert [n.findtext("duration") for n in root.iter("note")] == ["12", "12"]
    mark = root.find(".//metronome")
    assert [c.tag for c in mark] == ["beat-unit", "beat-unit-dot", "per-minute"] and mark.findtext("per-minute") == "61"
    assert root.find(".//sound").get("tempo") == "91.5"
    assert report == {"time_signatures_relabelled": 1, "other_meters_left": ["4/4"],
                      "beams_removed": 2, "tempo_mark": "dotted quarter = 61"}, report
    print("ok: 3/4 -> 6/8 relabels the meter, drops beams and layout hints, prints a dotted-quarter tempo, keeps the notes")


def test_already_dotted_mark_is_left_alone():
    root = ET.fromstring(RAW.replace("<beat-unit>quarter</beat-unit>", "<beat-unit>quarter</beat-unit><beat-unit-dot/>"))
    report = relabel(root, (3, 4), (6, 8))
    assert root.find(".//metronome").findtext("per-minute") == "92" and report["tempo_mark"] == "left alone"
    print("ok: a tempo mark that is already dotted is not rescaled twice")


def test_different_bar_length_is_refused():
    try:
        relabel(ET.fromstring(RAW), (3, 4), (4, 4))
    except ValueError as e:
        assert "same bar length" in str(e)
    else:
        raise AssertionError("expected ValueError")
    print("ok: a meter of a different bar length is refused (that would be re-barring)")


if __name__ == "__main__":
    test_three_four_becomes_six_eight()
    test_already_dotted_mark_is_left_alone()
    test_different_bar_length_is_refused()
