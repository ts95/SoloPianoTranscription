"""Regression test: rests after a note are filled by lengthening the note.

Run: .venv/bin/python scripts/test_fill_rests.py
"""
import xml.etree.ElementTree as ET

from fill_rests import fill_rests


def note(step, dur, typ, dots=0, voice=1, chord=False, extra=""):
    return ("<note>" + ("<chord/>" if chord else "") + f"<pitch><step>{step}</step><octave>4</octave></pitch>"
            f"<duration>{dur}</duration>{extra}<voice>{voice}</voice><type>{typ}</type>" + "<dot/>" * dots
            + "<beam number=\"1\">begin</beam></note>")


def rest(dur, typ, dots=0, voice=1):
    return f"<note><rest/><duration>{dur}</duration><voice>{voice}</voice><type>{typ}</type>" + "<dot/>" * dots + "</note>"


def run(*measures):
    xml = ("<score-partwise><part id=\"P1\">" + "".join(
        f"<measure number=\"{i + 1}\">" + ("<attributes><divisions>4</divisions></attributes>" if i == 0 else "")
        + m + "</measure>" for i, m in enumerate(measures)) + "</part></score-partwise>")
    root = ET.fromstring(xml)
    stats = fill_rests(root)
    bars = [[("rest" if n.find("rest") is not None else n.findtext("pitch/step"),
              int(n.findtext("duration")), n.findtext("type"), len(n.findall("dot")),
              [t.get("type") for t in n.findall("tie")]) for n in m.findall("note")]
            for m in root.iter("measure")]
    return bars, stats, root


def test_the_users_example():
    # 6/8 (div 4: eighth = 2): dotted 8th, 16th tied to an 8th, then 8th rest + quarter rest
    bars, stats, root = run(
        note("B", 3, "eighth", 1) + note("A", 1, "16th", extra='<tie type="start"/>')
        + note("A", 2, "eighth", extra='<tie type="stop"/>') + rest(2, "eighth") + rest(4, "quarter"))
    assert bars[0] == [("B", 3, "eighth", 1, []), ("A", 1, "16th", 0, ["start"]),
                       ("A", 8, "half", 0, ["stop"])], bars[0]
    assert stats["merged"] == 2 and stats["rests_left"] == 0 and root.find(".//beam") is None
    print("ok: a tied eighth followed by rests becomes a half note filling the bar")


def test_opening_rest_stays_and_notes_stop_at_the_bar_line():
    bars, stats, _ = run(rest(2, "eighth") + note("C", 2, "eighth") + rest(2, "eighth") + note("D", 6, "quarter", 1),
                         rest(12, "half", 1))
    assert bars[0] == [("rest", 2, "eighth", 0, []), ("C", 4, "quarter", 0, []), ("D", 6, "quarter", 1, [])], bars[0]
    assert bars[1] == [("rest", 12, "half", 1, [])] and stats["rests_left"] == 2
    print("ok: a rest that opens a bar stays; nothing grows past its bar")


def test_a_value_that_is_not_one_note_becomes_a_tie():
    # quarter (4) + 16th rest (1) = 5 sixteenths: no single note value -> quarter tied to a 16th
    bars, stats, _ = run(note("C", 4, "quarter") + note("E", 4, "quarter", chord=True) + rest(1, "16th")
                         + note("D", 7, "quarter", 2))
    assert bars[0][:4] == [("C", 4, "quarter", 0, ["start"]), ("E", 4, "quarter", 0, ["start"]),
                           ("C", 1, "16th", 0, ["stop"]), ("E", 1, "16th", 0, ["stop"])], bars[0]
    assert stats["tied"] == 1
    print("ok: a chord plus a rest that is no single value is tied across, every chord note included")


def test_voices_are_independent():
    bars, _, _ = run(note("G", 6, "quarter", 1) + note("G", 6, "quarter", 1)
                     + "<backup><duration>12</duration></backup>"
                     + note("C", 2, "eighth", voice=2) + rest(4, "quarter", voice=2) + rest(6, "quarter", 1, voice=2))
    assert bars[0][2] == ("C", 12, "half", 1, []), bars[0]
    print("ok: each voice fills its own rests")


if __name__ == "__main__":
    test_the_users_example()
    test_opening_rest_stays_and_notes_stop_at_the_bar_line()
    test_a_value_that_is_not_one_note_becomes_a_tie()
    test_voices_are_independent()
