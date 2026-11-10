"""Regression test: relabel_meter changes the label, the beams and the tempo unit — not the notes.

Run: .venv/bin/python scripts/test_relabel_meter.py
"""
from relabel_meter import relabel

NOTE = '<note><pitch><step>C</step><octave>4</octave></pitch><duration>12</duration><type>eighth</type>{}</note>'
RAW = ('<measure number="1"><attributes><time><beats>3</beats><beat-type>4</beat-type></time></attributes>'
       '<direction><direction-type><metronome><beat-unit>quarter</beat-unit><per-minute>92</per-minute>'
       '</metronome></direction-type><sound tempo="92"/></direction>'
       + NOTE.format('<beam number="1">begin</beam>') + NOTE.format('<beam number="1">end</beam>')
       + '</measure><measure number="2"><attributes><time><beats>4</beats><beat-type>4</beat-type></time>'
       '</attributes></measure>')


def test_three_four_becomes_six_eight():
    out, report = relabel(RAW, (3, 4), (6, 8))
    assert '<time><beats>6</beats><beat-type>8</beat-type></time>' in out
    assert '<time><beats>4</beats><beat-type>4</beat-type></time>' in out   # other meters untouched
    assert '<beam' not in out and out.count('<note>') == 2 and out.count('<duration>12</duration>') == 2
    assert '<beat-unit>quarter</beat-unit><beat-unit-dot/><per-minute>61</per-minute>' in out
    assert '<sound tempo="91.5"/>' in out                                    # playback unchanged in effect
    assert report == {"time_signatures_relabelled": 1, "other_meters_left": ["4/4"],
                      "beams_removed": 2, "tempo_mark": "dotted quarter = 61"}, report
    print("ok: 3/4 -> 6/8 relabels the meter, drops beams, prints a dotted-quarter tempo, keeps the notes")


def test_different_bar_length_is_refused():
    try:
        relabel(RAW, (3, 4), (4, 4))
    except ValueError as e:
        assert "same bar length" in str(e)
    else:
        raise AssertionError("expected ValueError")
    print("ok: a meter of a different bar length is refused (that would be re-barring)")


if __name__ == "__main__":
    test_three_four_becomes_six_eight()
    test_different_bar_length_is_refused()
