"""Tests for clean_musicxml in THIS project's context.

The cleaner was lifted from an Audiveris OMR project, where aggressive OCR-garbage
rules are correct. On our *generated* MusicXML those rules misfire: they would
strip a legitimate short title (e.g. the cover literally titled "U") and remove
intentional ornaments. `source='generated'` (the default) must keep those, while
still applying the source-agnostic cleanups (dynamics dedup). `source='omr'` must
preserve the original behavior.

Run: .venv/bin/python scripts/test_clean_musicxml.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(__file__))
from clean_musicxml import clean_musicxml

FIXTURE = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="4.0">
  <credit><credit-words>U</credit-words></credit>
  <part-list><score-part id="P1"><part-name>Piano</part-name></score-part></part-list>
  <part id="P1">
    <measure number="55">
      <direction placement="below"><direction-type><dynamics><mf/></dynamics></direction-type><staff>1</staff></direction>
      <direction placement="below"><direction-type><dynamics><mp/></dynamics></direction-type><staff>1</staff></direction>
      <note><pitch><step>C</step><octave>5</octave></pitch><duration>4</duration><type>quarter</type>
        <notations><ornaments><trill-mark/></ornaments></notations></note>
    </measure>
  </part>
</score-partwise>"""


def _clean(source):
    with tempfile.NamedTemporaryFile("w", suffix=".musicxml", delete=False) as f:
        f.write(FIXTURE)
        path = f.name
    try:
        tree, _log = clean_musicxml(path, source=source)
    finally:
        os.unlink(path)
    return tree.getroot()


def test_generated_preserves_title_and_ornaments():
    root = _clean("generated")
    assert root.find("credit") is not None, \
        "short-title credit wrongly stripped in generated mode"
    assert root.find(".//ornaments") is not None, \
        "intentional ornament wrongly removed in generated mode"
    # source-agnostic dedup still applies: the contradictory mp is dropped
    dyns = root.findall(".//dynamics")
    assert len(dyns) == 1, f"expected dynamics dedup to 1, got {len(dyns)}"
    print("ok: generated mode keeps short title + ornaments, still dedups dynamics")


def test_omr_mode_keeps_legacy_behavior():
    root = _clean("omr")
    assert root.find("credit") is None, "omr mode should strip the garbage credit"
    assert root.find(".//ornaments") is None, \
        "omr mode should remove suspect ornaments (remove_all)"
    print("ok: omr mode preserves the original OCR cleanup")


if __name__ == "__main__":
    test_generated_preserves_title_and_ornaments()
    test_omr_mode_keeps_legacy_behavior()
    print("all clean_musicxml tests passed")
