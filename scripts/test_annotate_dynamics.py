"""Regression test: dynamics and hairpins planned from per-bar velocities.

Run: .venv/bin/python scripts/test_annotate_dynamics.py
"""
import xml.etree.ElementTree as ET

from annotate_dynamics import plan_dynamics, write_dynamics

P_TO_F = ["p", "mp", "mf", "f"]
# per-bar mean velocities of the "Strangers" cover (bar 0 = pickup)
STRANGERS = [61, 53, 54, 54, 53, 57, 59, 54, 57, 72, 72, 76, 77, 75, 73, 72, 76, 85, 85, 85, 83, 85,
             85, 78, 75, 60, 58, 58, 51, 85, 88, 84, 82, 86, 87, 86, 87, 89, 85, 84, 80, 83, 86, 84,
             75, 90, 86, 88, 79, 82, 84, 77, 83, 87, 89, 87, 81, 84, 88, 79, 78, 62, 58, 55, 56]


def test_a_real_performance():
    marks, hairpins = plan_dynamics([float(v) for v in STRANGERS], P_TO_F)
    assert marks == {0: "p", 9: "mf", 17: "f", 25: "p", 29: "f", 61: "p"}, marks
    assert hairpins == [(23, 24, "diminuendo"), (59, 60, "diminuendo")], hairpins
    print("ok: block levels become marks; two-bar fades become hairpins; one-bar dips are ignored")


def test_sudden_step_is_a_mark_not_a_hairpin():
    marks, hairpins = plan_dynamics([50.0] * 8 + [90.0] * 8, P_TO_F)
    assert marks == {0: "p", 8: "f"} and hairpins == [], (marks, hairpins)
    print("ok: a change within one bar is a mark with no hairpin")


def test_gradual_rise_is_one_hairpin_between_two_marks():
    marks, hairpins = plan_dynamics([50.0] * 6 + [58.0, 66.0, 74.0, 82.0] + [90.0] * 6, P_TO_F)
    # f is marked on the bar that first reaches the f band (82); mp and mf, passed through, are dropped
    assert marks == {0: "p", 9: "f"}, marks
    assert hairpins == [(6, 8, "crescendo")], hairpins
    print("ok: a steady rise is one crescendo from p into f")


def test_flat_performance_gets_one_mark():
    marks, hairpins = plan_dynamics([70.0, 71.0, 69.0, 70.0, 72.0, 70.0], P_TO_F)
    assert marks == {0: "mf"} and hairpins == [], (marks, hairpins)
    print("ok: a performance with no dynamic range gets a single mark")


def test_old_dynamics_are_replaced_in_the_score():
    root = ET.fromstring(
        '<score-partwise><part id="P1">'
        '<measure number="1"><attributes><divisions>1</divisions></attributes>'
        '<direction><direction-type><dynamics><mp/></dynamics></direction-type><sound dynamics="71"/></direction>'
        '<direction><direction-type><pedal type="start"/></direction-type></direction><note/></measure>'
        '<measure number="2"><note/></measure>'
        '<measure number="3"><note/><barline location="right"/></measure></part></score-partwise>')
    removed = write_dynamics(root, {0: "f", 2: "p"}, [(1, 1, "diminuendo")])
    ms = root.find("part").findall("measure")
    assert removed == 1 and root.find(".//mp") is None and root.find(".//pedal") is not None
    assert [c.tag for c in ms[0]][:2] == ["attributes", "direction"] and ms[0][1].find(".//f") is not None
    assert ms[1][0].find(".//wedge").get("type") == "diminuendo" and ms[1][-1].find(".//wedge").get("type") == "stop"
    assert ms[2][0].find(".//p") is not None and ms[2][-1].tag == "barline"
    print("ok: old dynamics go, pedal stays, marks open their bar, a hairpin spans its bars")


if __name__ == "__main__":
    test_a_real_performance()
    test_sudden_step_is_a_mark_not_a_hairpin()
    test_gradual_rise_is_one_hairpin_between_two_marks()
    test_flat_performance_gets_one_mark()
    test_old_dynamics_are_replaced_in_the_score()
