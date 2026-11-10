"""Regression test: the arranger is printed under the composer.

Run: .venv/bin/python scripts/test_credit_arranger.py
"""
from credit_arranger import with_arranger

FRAME = ('<VBox><Text><style>title</style><text>Strangers</text></Text>'
         '<Text>\n  <eid>x</eid>\n  <style>composer</style>\n  <text>Bring Me The Horizon</text>\n  </Text></VBox>')


def score(arranger):
    return FRAME + f'<metaTag name="arranger">{arranger}</metaTag><metaTag name="composer">Bring Me The Horizon</metaTag>'


def test_arranger_is_added_once():
    new, status = with_arranger(score("RoLee Piano"))
    assert status == "added" and "<text>Bring Me The Horizon\nArr. RoLee Piano</text>" in new
    assert "<text>Strangers</text>" in new
    again, status = with_arranger(new)
    assert status == "already shown" and again == new
    print("ok: the arranger becomes a second line of the composer text, once")


def test_nothing_to_do():
    for mscx, why in ((score(""), "no arranger"), ('<metaTag name="arranger">X</metaTag>', "no composer text")):
        new, status = with_arranger(mscx)
        assert new == mscx and status.startswith(why), status
    print("ok: no arranger tag or no composer text leaves the score alone")


if __name__ == "__main__":
    test_arranger_is_added_once()
    test_nothing_to_do()
