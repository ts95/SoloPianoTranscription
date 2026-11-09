#!/usr/bin/env python3
"""Set the score header metadata (title / composer / arranger / performer) on a
DuET `score.musicxml`.

DuET writes only a title (from the input filename) and a fixed arranger credit.
This step rewrites just the <work> and <identification> elements so the engraved
musical content — grace notes, glissandi, key signatures, voices — is left
byte-for-byte intact. It is a targeted text edit, NOT a music21 round-trip,
precisely so the engraving survives untouched.

Usage:
  set_score_metadata.py <in.musicxml> <out.musicxml> \
      --title '<piece>' --composer '<original composer/artist>' \
      [--arranger '<arranger>'] [--performer '<pianist>']

Only the roles you pass are written; omit the ones that don't apply.
"""
import argparse
import html
import json
import re
import sys


def esc(s: str) -> str:
    return html.escape(s, quote=False)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("input")
    ap.add_argument("output")
    ap.add_argument("--title", help="piece title (replaces DuET's filename-derived title)")
    ap.add_argument("--composer", help="original composer/artist")
    ap.add_argument("--arranger", help="arranger (cover/arrangement author), if applicable")
    ap.add_argument("--performer", help="performer/pianist, if known")
    args = ap.parse_args()

    with open(args.input, encoding="utf-8") as f:
        xml = f.read()

    changed = {}

    if args.title:
        new = f"<work-title>{esc(args.title)}</work-title>"
        if re.search(r"<work-title>.*?</work-title>", xml, flags=re.S):
            xml, n = re.subn(r"<work-title>.*?</work-title>", new, xml, count=1, flags=re.S)
            changed["title"] = args.title if n else "no <work-title> found"
        else:
            # no <work> block at all — insert one right after the <score-partwise> open tag
            xml, n = re.subn(r"(<score-partwise[^>]*>)",
                             r"\1\n<work><work-title>%s</work-title></work>" % esc(args.title),
                             xml, count=1)
            changed["title"] = args.title if n else "no <score-partwise> found"

    creators = []
    if args.composer:
        creators.append(f'<creator type="composer">{esc(args.composer)}</creator>')
    if args.arranger:
        creators.append(f'<creator type="arranger">{esc(args.arranger)}</creator>')
    if args.performer:
        creators.append(f'<creator type="performer">{esc(args.performer)}</creator>')
    if creators:
        # Preserve DuET's existing <encoding> block (software/date) inside
        # <identification>; only the <creator> elements are replaced.
        m = re.search(r"<identification>(.*?)</identification>", xml, flags=re.S)
        existing = m.group(1) if m else ""
        enc = re.search(r"<encoding>.*?</encoding>", existing, flags=re.S)
        encoding = enc.group(0) if enc else '<encoding><software>engrave</software></encoding>'
        block = "<identification>" + "".join(creators) + encoding + "</identification>"
        xml, n = re.subn(r"<identification>.*?</identification>", block, xml, count=1, flags=re.S)
        changed["identification"] = (
            [c.split('"')[1] for c in creators] if n else "no <identification> found")

    with open(args.output, "w", encoding="utf-8") as f:
        f.write(xml)

    print(json.dumps({"input": args.input, "output": args.output, "changed": changed}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
