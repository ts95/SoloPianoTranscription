#!/usr/bin/env python3
"""Re-annotate a score's dynamics from the performed velocities, hairpins included.

DuET writes one block dynamic every eight bars. The cleaned transcription MIDI
knows how hard every key was struck, so the shape of the performance — where it
steps up, where it fades — can be read off it and written into the score.

    annotate_dynamics.py <in.musicxml> <cleaned.mid> <score.npz> <out.musicxml> [--range p-f]

Pass the .mid DuET engraved and the score.npz from that run (they say which bar
and which hand every performed note belongs to). The score must still have the
same bars as that run. Works on a raw DuET score and on a MuseScore export.

How the marks are chosen:
  - loudness per bar = mean velocity of all its notes, both hands (the melody
    alone is jumpier and misses a soft accompaniment under it), lightly smoothed
    (median of 3 bars)
  - the performance's own range (5th-95th percentile of those bars) is cut into
    equal bands, one per level of --range — levels are relative to THIS pianist,
    since transcribed velocity is not absolute loudness
  - a level must hold for 2 bars to count; a mark is written where the level changes
  - a hairpin leads into a mark when, bar by bar, the loudness moved steadily toward
    it for at least 2 bars and 8 velocity units before the mark; a mark the hairpin
    passes through is dropped. A change that happens in one bar is just the mark.
All existing dynamics and hairpins in the score are replaced.
"""
import argparse
import json
import os
import statistics
import sys
import xml.etree.ElementTree as ET

import numpy as np
import pretty_midi

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from musicxml_io import load, save  # noqa: E402

LEVELS = ["pp", "p", "mp", "mf", "f", "ff"]
MIN_RUN = 2            # bars a level must hold to get its own mark
HAIRPIN_MIN_BARS = 2   # shortest hairpin
HAIRPIN_MAX_BARS = 6   # longest hairpin
HAIRPIN_MIN_CHANGE = 8.0   # velocity units the loudness must travel under a hairpin
STEP = 1.0             # per-bar movement that counts as "still getting louder/softer"
FLAT = 6.0             # a range narrower than this is one level


def plan_dynamics(values, levels):
    """values: mean velocity per bar. levels: e.g. ['p','mp','mf','f'].
    Returns (marks, hairpins): marks = {bar_index: level}; hairpins =
    [(first_bar, last_bar, 'crescendo'|'diminuendo')], both bars inclusive, the
    hairpin ending at the mark on bar last_bar + 1."""
    n = len(values)
    smooth = [statistics.median(values[max(0, i - 1):i + 2]) for i in range(n)]
    lo, hi = np.percentile(smooth, [5, 95])
    if hi - lo < FLAT:
        return {0: levels[len(levels) // 2]}, []
    idx = [int(min(len(levels) - 1, max(0, (v - lo) / (hi - lo) * len(levels)))) for v in smooth]

    # a level that does not hold for MIN_RUN bars joins its neighbour
    runs = []   # [start, length, level]
    for i, lv in enumerate(idx):
        if runs and runs[-1][2] == lv:
            runs[-1][1] += 1
        else:
            runs.append([i, 1, lv])
    merged = []
    for start, length, lv in runs:
        if merged and (length < MIN_RUN or merged[-1][2] == lv):
            merged[-1][1] += length
        elif not merged and length < MIN_RUN and len(runs) > 1:
            merged.append([start, length, None])   # takes the next run's level
        else:
            if merged and merged[-1][2] is None:
                merged[-1][1] += length
                merged[-1][2] = lv
            else:
                merged.append([start, length, lv])
    starts = {start: lv for start, _, lv in merged}

    hairpins, dropped = [], set()
    order = sorted(starts)
    for prev, k in zip(order, order[1:]):
        direction = 1 if starts[k] > starts[prev] else -1
        # On the RAW bar values (smoothing smears a sudden step into a ramp): walk back
        # while the loudness was not moving AWAY from the new level, then drop the flat
        # lead-in. Bar j is the last bar before it starts to move; the hairpin covers the
        # bars after it, and must itself carry HAIRPIN_MIN_CHANGE — otherwise the change
        # is a sudden step into the mark, not a hairpin.
        j = k - 1
        while j > 0 and k - j <= HAIRPIN_MAX_BARS and (values[j] - values[j - 1]) * direction >= -STEP / 2:
            j -= 1
        while j < k - 1 and (values[j + 1] - values[j]) * direction < STEP:
            j += 1
        first, last = j + 1, k - 1
        if last - first + 1 >= HAIRPIN_MIN_BARS and (values[last] - values[j]) * direction >= HAIRPIN_MIN_CHANGE:
            hairpins.append((first, last, "crescendo" if direction > 0 else "diminuendo"))
            dropped.update(s for s in order if first <= s <= last)
    marks = {s: levels[lv] for s, lv in starts.items() if s not in dropped}
    return marks, hairpins


def bar_velocities(performance_mid, npz_path):
    """Mean velocity of all notes per DuET bar (the previous bar's value where a
    bar has no notes)."""
    pm = pretty_midi.PrettyMIDI(performance_mid)
    played = sorted((n for inst in pm.instruments for n in inst.notes),
                    key=lambda n: (n.start, n.pitch))
    z = np.load(npz_path)
    rows = z["notes"]
    if len(rows) != len(played) or any(n.pitch != int(p) for n, p in zip(played, rows[:, 0])):
        sys.exit("score.npz does not match the performance MIDI — pass the .mid that DuET "
                 "engraved and its own score.npz")
    vel = np.array([n.velocity for n in played], dtype=float)
    bar = np.searchsorted(z["bar_starts"], rows[:, 1], side="right") - 1
    out = []
    for k in range(len(z["bar_starts"])):
        notes = vel[bar == k]
        out.append(float(notes.mean()) if len(notes) else (out[-1] if out else float(vel.mean())))
    return out


def direction(child, staff="1"):
    d = ET.Element("direction", placement="below")
    ET.SubElement(d, "direction-type").append(child)
    ET.SubElement(d, "staff").text = staff
    return d


def write_dynamics(root, marks, hairpins):
    """Replace every dynamic and hairpin in the score with the planned ones."""
    removed = 0
    for parent in list(root.iter()):
        for d in [c for c in parent if c.tag == "direction"]:
            for dt in d.findall("direction-type"):
                if dt.find("dynamics") is not None or dt.find("wedge") is not None:
                    d.remove(dt)
                    removed += 1
            sound = d.find("sound")
            if sound is not None:
                sound.attrib.pop("dynamics", None)
                if not sound.attrib and len(sound) == 0:
                    d.remove(sound)
            if d.find("direction-type") is None:
                parent.remove(d)
    measures = root.find("part").findall("measure")

    def at_start(measure, el):
        i = 0
        while i < len(measure) and measure[i].tag in ("print", "attributes"):
            i += 1
        measure.insert(i, el)

    def at_end(measure, el):
        i = len(measure)
        while i > 0 and measure[i - 1].tag == "barline":
            i -= 1
        measure.insert(i, el)

    for first, last, kind in hairpins:
        at_start(measures[first], direction(ET.Element("wedge", type=kind, number="1")))
        at_end(measures[last], direction(ET.Element("wedge", type="stop", number="1")))
    for bar, level in marks.items():
        dyn = ET.Element("dynamics")
        ET.SubElement(dyn, level)
        at_start(measures[bar], direction(dyn))
    return removed


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("performance_mid", help="the .mid DuET engraved (normally <slug>.cleaned.mid)")
    ap.add_argument("npz", help="score.npz from that DuET run")
    ap.add_argument("output")
    ap.add_argument("--range", default="p-f", dest="span",
                    help="softest-loudest level to use, e.g. p-f (default) or pp-ff")
    args = ap.parse_args()

    soft, loud = args.span.split("-")
    levels = LEVELS[LEVELS.index(soft):LEVELS.index(loud) + 1]
    values = bar_velocities(args.performance_mid, args.npz)
    prolog, root = load(args.input)
    measures = root.find("part").findall("measure")
    if len(measures) != len(values):
        sys.exit(f"the score has {len(measures)} bars but DuET's run had {len(values)} — "
                 "bars were added or removed; dynamics cannot be placed")
    marks, hairpins = plan_dynamics(values, levels)
    removed = write_dynamics(root, marks, hairpins)
    save(args.output, prolog, root)
    number = [m.get("number") for m in measures]   # printed bar numbers
    print(json.dumps({
        "output": args.output, "levels": levels, "old_marks_removed": removed,
        "marks": [{"bar": number[b], "level": lv} for b, lv in sorted(marks.items())],
        "hairpins": [{"bars": f"{number[a]}-{number[b]}", "type": kind} for a, b, kind in hairpins],
        "bar_velocities": [round(v) for v in values],
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
