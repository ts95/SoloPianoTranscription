#!/usr/bin/env python3
"""Relabel a score's meter to another meter of the SAME bar length.

DuET hears a 6/8 piece as 3/4 (six eighths per bar either way) — it has no
meter override, and re-barring is not a mechanical edit, but relabelling is:
the notes and bar lines stay exactly where they are; only the time signature,
the beaming and the tempo mark's beat unit change.

    relabel_meter.py <in.musicxml> <out.musicxml> --from 3/4 --to 6/8

Works on a raw DuET score.musicxml and on a MuseScore export alike. Run it
after normalize_tempo.py (it expects one metronome mark). What changes:
  - every time signature equal to --from becomes --to (other meters are left
    alone and reported — e.g. one stretched final bar)
  - all beams, system/page breaks and a MuseScore export's <supports>
    declarations are dropped, so MuseScore re-beams and re-flows by the new meter
  - if --to is compound (6/8, 9/8, 12/8) a single quarter-note metronome mark
    becomes dotted-quarter = N, with playback unchanged (the playback tempo
    stays the equivalent quarter-note tempo)
Notes that straddle the new beat (a quarter starting on the third eighth of a
6/8 bar) are NOT re-spelled as tied notes; regroup them in MuseScore
(Tools > Regroup Rhythms).
"""
import argparse
import json
import os
import sys
import xml.etree.ElementTree as ET
from fractions import Fraction

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from musicxml_io import let_musescore_rebeam, load, save  # noqa: E402


def relabel(root, src, dst):
    """src/dst: (beats, beat_type). Mutates root; returns the report."""
    if Fraction(*src) != Fraction(*dst):
        raise ValueError(f"{src[0]}/{src[1]} and {dst[0]}/{dst[1]} are not the same bar length")
    times = list(root.iter("time"))
    if not times:
        raise ValueError("no <time> found in the score")
    relabelled, other = 0, set()
    for time in times:
        current = (int(time.findtext("beats")), int(time.findtext("beat-type")))
        if current == src:
            time.find("beats").text, time.find("beat-type").text = str(dst[0]), str(dst[1])
            relabelled += 1
        elif current != dst:
            other.add(f"{current[0]}/{current[1]}")
    report = {"time_signatures_relabelled": relabelled, "other_meters_left": sorted(other),
              "beams_removed": let_musescore_rebeam(root)}
    if dst[1] == 8 and dst[0] % 3 == 0 and dst[0] > 3:   # compound meter
        marks = list(root.iter("metronome"))
        if (len(marks) == 1 and marks[0].findtext("beat-unit") == "quarter"
                and marks[0].find("beat-unit-dot") is None):
            mark = marks[0]
            dotted = round(float(mark.findtext("per-minute")) * 2 / 3)
            mark.insert(list(mark).index(mark.find("beat-unit")) + 1, ET.Element("beat-unit-dot"))
            mark.find("per-minute").text = str(dotted)
            for sound in root.iter("sound"):
                if sound.get("tempo") is not None:
                    # playback is in quarter notes per minute: keep it equal to the printed mark
                    sound.set("tempo", f"{dotted * 1.5:g}")
                    break
            report["tempo_mark"] = f"dotted quarter = {dotted}"
        else:
            report["tempo_mark"] = "left alone"
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("output")
    ap.add_argument("--from", dest="src", required=True, help="meter in the score, e.g. 3/4")
    ap.add_argument("--to", dest="dst", required=True, help="meter to print, e.g. 6/8")
    args = ap.parse_args()

    prolog, root = load(args.input)
    try:
        report = relabel(root, tuple(int(x) for x in args.src.split("/")),
                         tuple(int(x) for x in args.dst.split("/")))
    except ValueError as e:
        print(f"relabel_meter: {e}", file=sys.stderr)
        return 1
    save(args.output, prolog, root)
    print(json.dumps({"input": args.input, "output": args.output, **report}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
