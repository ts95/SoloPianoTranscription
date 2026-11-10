#!/usr/bin/env python3
"""Force ONE constant tempo on a score.

DuET infers a tempo per section: visible metronome marks plus hidden
<sound tempo> playback changes. When the true tempo is known (measured by
bar_timing.py, or from the web), this rewrites the score to a single
quarter-note tempo.

Works on a raw DuET score.musicxml and on a MuseScore export alike.

There is deliberately no meter override. Re-barring is not a mechanical edit;
see relabel_meter.py for the one case that is.

Usage:
  normalize_tempo.py <in.musicxml> <out.musicxml> --tempo 93

What changes:
  - the first metronome mark becomes quarter = N; every other one is removed
  - the first playback tempo becomes N; every other one is removed
  - directions left empty by those removals are removed
  - text directions (rit., a tempo) and everything else are untouched
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from musicxml_io import load, save  # noqa: E402


def normalize_tempo(root, bpm):
    parents = {child: parent for parent in root.iter() for child in parent}
    marks = list(root.iter("metronome"))
    if not marks:
        raise ValueError("no <metronome> found in the score")
    first = marks[0]
    for dot in first.findall("beat-unit-dot"):
        first.remove(dot)
    first.find("beat-unit").text = "quarter"
    first.find("per-minute").text = str(bpm)
    for mark in marks[1:]:
        parents[mark].remove(mark)
    sounds = [s for s in root.iter("sound") if s.get("tempo") is not None]
    for s in sounds[:1]:
        s.set("tempo", str(bpm))
    for s in sounds[1:]:
        del s.attrib["tempo"]
        if not s.attrib and len(s) == 0:
            parents[s].remove(s)
    emptied = 0
    for direction in list(root.iter("direction")):
        content = [c for dt in direction.findall("direction-type") for c in dt
                   if not (c.tag == "words" and not (c.text or "").strip())]
        if not content and direction.find("sound") is None:
            parents[direction].remove(direction)
            emptied += 1
    return {"bpm": bpm, "metronome_marks_removed": len(marks) - 1,
            "sound_tempos_removed": max(0, len(sounds) - 1),
            "empty_directions_removed": emptied}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("output")
    ap.add_argument("--tempo", type=float, required=True,
                    help="constant quarter-note BPM for the whole piece")
    args = ap.parse_args()

    prolog, root = load(args.input)
    try:
        report = normalize_tempo(root, int(round(args.tempo)))
    except ValueError as e:
        print(f"normalize_tempo: {e}", file=sys.stderr)
        return 1
    save(args.output, prolog, root)
    print(json.dumps({"input": args.input, "output": args.output, **report}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
