#!/usr/bin/env python3
"""Print the arranger on the score, under the composer.

set_score_metadata.py records the arranger in the file's metadata, but MuseScore
only prints the title and the composer on the page. This adds a second line to
the composer text of the title frame, read from the score's own arranger tag:

    Bring Me The Horizon
    Arr. RoLee Piano

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
from musescore_pedal_lib import extract_mscz, repackage_mscz  # noqa: E402

ARRANGER_TAG = re.compile(r'<metaTag name="arranger">([^<]*)</metaTag>')
COMPOSER_TEXT = re.compile(r'(<style>composer</style>\s*<text>)(.*?)(</text>)', flags=re.S)


def with_arranger(mscx):
    """Returns (new_mscx, status): status is 'added', or why nothing was done."""
    tag = ARRANGER_TAG.search(mscx)
    arranger = tag.group(1).strip() if tag else ""
    if not arranger:
        return mscx, "no arranger in the score's metadata"
    text = COMPOSER_TEXT.search(mscx)
    if not text:
        return mscx, "no composer text in the title frame"
    if arranger in text.group(2):
        return mscx, "already shown"
    line = f"{text.group(2)}\nArr. {arranger}"
    return mscx[:text.start(2)] + line + mscx[text.end(2):], "added"


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
        if status == "added":
            with open(path, "w", encoding="utf-8") as f:
                f.write(new)
            repackage_mscz(args.mscz, os.path.join(td, "x"))
    print(f"arranger credit: {status}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
