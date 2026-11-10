#!/usr/bin/env python3
"""Print the arranger on the score, at the left of the title frame.

set_score_metadata.py records the arranger in the file's metadata, but MuseScore
only prints the title and the composer on the page. This adds a text at the left
of the title frame, level with the composer on the right, read from the score's
own arranger tag:

    Arr. RoLee Piano                                   Bring Me The Horizon

    credit_arranger.py <file.mscz>

Edits the .mscz in place. Does nothing when the score has no arranger tag, no
composer text, or already shows the arranger. (A MusicXML <credit> cannot do
this: without page coordinates MuseScore imports it as unstyled, misplaced text.)
"""
import argparse
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from musescore_pedal_lib import extract_mscz, generate_eid, repackage_mscz  # noqa: E402

ARRANGER_TAG = re.compile(r'<metaTag name="arranger">([^<]*)</metaTag>')
COMPOSER = re.compile(r'<Text>(?:(?!</Text>).)*?<style>composer</style>(?:(?!</Text>).)*?</Text>', flags=re.S)


def with_arranger(mscx):
    """Returns (new_mscx, status): status is 'added', or why nothing was done."""
    tag = ARRANGER_TAG.search(mscx)
    arranger = tag.group(1).strip() if tag else ""
    if not arranger:
        return mscx, "no arranger in the score's metadata"
    credit = f"Arr. {arranger}"
    composer = COMPOSER.search(mscx)
    if not composer:
        return mscx, "no composer text in the title frame"
    # an earlier version of this script put the credit on a second composer line
    block = composer.group(0).replace(f"\n{credit}</text>", "</text>")
    if f"<text>{credit}</text>" in mscx:
        status = "already shown"
    else:
        # MuseScore's "lyricist" text style sits at the LEFT of the title frame. The
        # explicit bottom alignment puts it level with the composer on the right;
        # without it MuseScore places the text at the top, beside the title.
        block += (f"\n        <Text>\n          <eid>{generate_eid()}</eid>\n          <style>lyricist</style>"
                  f"\n          <align>left,bottom</align>"
                  f"\n          <text>{credit}</text>\n          </Text>")
        status = "added"
    return mscx[:composer.start()] + block + mscx[composer.end():], status


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mscz")
    args = ap.parse_args()
    with tempfile.TemporaryDirectory() as td:
        path = extract_mscz(args.mscz, os.path.join(td, "x"))
        with open(path, encoding="utf-8") as f:
            mscx = f.read()
        new, status = with_arranger(mscx)
        if new != mscx:
            with open(path, "w", encoding="utf-8") as f:
                f.write(new)
            repackage_mscz(args.mscz, os.path.join(td, "x"))
    print(f"arranger credit: {status}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
