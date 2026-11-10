#!/usr/bin/env python3
"""Relabel a raw DuET score's meter to another meter of the SAME bar length.

DuET hears a 6/8 piece as 3/4 (six eighths per bar either way) — it has no
meter override, and re-barring is not a text edit, but relabelling is: the
notes and bar lines stay exactly where they are; only the time signature, the
beaming and the tempo mark's beat unit change.

    relabel_meter.py <in.musicxml> <out.musicxml> --from 3/4 --to 6/8

Run it on the RAW DuET score.musicxml, after normalize_tempo.py (it expects one
metronome mark) and before MuseScore regenerates the file. What changes:
  - every <time> equal to --from becomes --to (other meters are left alone and
    reported — e.g. one stretched final bar)
  - all <beam> elements are removed, so MuseScore re-beams by the new meter
  - if --to is compound (6/8, 9/8, 12/8) the metronome mark becomes
    dotted-quarter = N, with playback unchanged (<sound tempo> stays the
    equivalent quarter-note tempo)
Notes that straddle the new beat (a quarter starting on the third eighth of a
6/8 bar) are NOT re-spelled as tied notes — the report counts on none; regroup
them in MuseScore (Tools > Regroup Rhythms).
"""
import argparse
import json
import re
import sys
from fractions import Fraction

TIME = re.compile(r'<time><beats>(\d+)</beats><beat-type>(\d+)</beat-type></time>')
METRONOME = re.compile(r'<metronome><beat-unit>quarter</beat-unit><per-minute>(\d+)</per-minute></metronome>')
SOUND_TEMPO = re.compile(r'<sound tempo="[^"]*"/>')


def relabel(xml, src, dst):
    """src/dst: (beats, beat_type). Returns (new_xml, report)."""
    if Fraction(*src) != Fraction(*dst):
        raise ValueError(f"{src[0]}/{src[1]} and {dst[0]}/{dst[1]} are not the same bar length")
    if not TIME.search(xml):
        raise ValueError("no compact <time> found — run this on the raw DuET score.musicxml")
    other = sorted({f"{b}/{t}" for b, t in TIME.findall(xml) if (int(b), int(t)) != src})
    xml, n_time = re.subn(
        rf'<time><beats>{src[0]}</beats><beat-type>{src[1]}</beat-type></time>',
        f'<time><beats>{dst[0]}</beats><beat-type>{dst[1]}</beat-type></time>', xml)
    xml, n_beams = re.subn(r'<beam[^>]*>[^<]*</beam>', '', xml)
    report = {"time_signatures_relabelled": n_time, "other_meters_left": other,
              "beams_removed": n_beams}
    compound = dst[1] == 8 and dst[0] % 3 == 0 and dst[0] > 3
    marks = METRONOME.findall(xml)
    if compound and len(marks) == 1:
        quarter = int(marks[0])
        dotted = round(quarter * 2 / 3)
        xml = METRONOME.sub(
            f'<metronome><beat-unit>quarter</beat-unit><beat-unit-dot/>'
            f'<per-minute>{dotted}</per-minute></metronome>', xml)
        # playback is in quarter notes per minute: keep it equal to the printed mark
        xml = SOUND_TEMPO.sub(f'<sound tempo="{dotted * 1.5:g}"/>', xml, count=1)
        report["tempo_mark"] = f"dotted quarter = {dotted}"
    elif compound:
        report["tempo_mark"] = f"left alone ({len(marks)} metronome marks — run normalize_tempo.py first)"
    return xml, report


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("output")
    ap.add_argument("--from", dest="src", required=True, help="meter DuET engraved, e.g. 3/4")
    ap.add_argument("--to", dest="dst", required=True, help="meter to print, e.g. 6/8")
    args = ap.parse_args()

    with open(args.input, encoding="utf-8") as f:
        xml = f.read()
    try:
        xml, report = relabel(xml, tuple(int(x) for x in args.src.split("/")),
                              tuple(int(x) for x in args.dst.split("/")))
    except ValueError as e:
        print(f"relabel_meter: {e}", file=sys.stderr)
        return 1
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(xml)
    print(json.dumps({"input": args.input, "output": args.output, **report}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
