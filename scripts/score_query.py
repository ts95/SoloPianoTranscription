#!/usr/bin/env python3
"""Compact score queries for targeted diagnosis. Output is fixed-width text
for model reading; every note view shows BOTH staves (single-staff views
have caused one-staff fixes)."""
import argparse
import bisect
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def load_piece(piece_dir):
    d = os.path.abspath(piece_dir)
    man = json.load(open(os.path.join(d, "piece.json")))
    slug = man["slug"]
    beats = json.load(open(os.path.join(d, man["beats"])))["beats"]
    return d, man, slug, beats


def bar_to_beats(man, printed_bar):
    """printed bar N -> (grid beat range, quantize measure number)."""
    qm = printed_bar + (1 if man.get("anacrusis") else 0)
    b0 = 4 * (qm - 1)
    return (b0, b0 + 4), qm


def bar_mapping(piece_dir, printed_bar):
    d, man, slug, beats = load_piece(piece_dir)
    (b0, b1), qm = bar_to_beats(man, printed_bar)
    shift = man["beats_shift"]
    return {"printed_bar": printed_bar, "quantize_measure": qm,
            "grid_beats": [b0, b1],
            "audio_s": [round(beats[b0], 2),
                        round(beats[min(b1, len(beats) - 1)], 2)],
            "midi_s": [round(beats[b0] - shift, 2),
                       round(beats[min(b1, len(beats) - 1)] - shift, 2)]}


def _pos(beats, t):
    i = bisect.bisect_right(beats, t) - 1
    i = max(0, min(i, len(beats) - 2))
    return i + (t - beats[i]) / (beats[i + 1] - beats[i])


def bar_diff(piece_dir, printed_bar):
    import pretty_midi
    from music21 import converter
    d, man, slug, beats = load_piece(piece_dir)
    (b0, b1), qm = bar_to_beats(man, printed_bar)
    shift = man["beats_shift"]
    sc = converter.parse(os.path.join(d, slug + ".musicxml"))
    lines = [f"== printed bar {printed_bar} (quantize m{qm}, "
             f"beats {b0}-{b1}, audio {beats[b0]:.2f}-{beats[b1]:.2f}s) =="]
    for pi, part in enumerate(sc.parts):
        m = part.measure(qm)
        row = []
        if m is not None:
            for el in m.recurse().notesAndRests:
                names = ",".join(p.nameWithOctave for p in el.pitches) \
                    if el.pitches else "rest"
                tie = f"~{el.tie.type[:2]}" if getattr(el, "tie", None) else ""
                row.append(f"{float(el.offset):.2f}:{names}"
                           f"({el.duration.quarterLength}){tie}")
        lines.append(f"P{pi}: " + "  ".join(row))
    pm = pretty_midi.PrettyMIDI(os.path.join(d, slug + ".cleaned.mid"))
    lines.append("played (t=MIDI s; pos=in-bar beats; dev=to nearest 16th):")
    prev = None
    for t, p, v, dur in sorted((n.start, n.pitch, n.velocity,
                                n.end - n.start)
                               for i in pm.instruments for n in i.notes):
        ta = t + shift
        if not (beats[b0] - 0.08 <= ta < beats[min(b1, len(beats) - 1)]):
            continue
        pos = _pos(beats, ta)
        inbar = pos - b0
        f = pos - int(pos)
        dev = abs(f - round(f * 4) / 4)
        gap = f"  gap={t - prev:.2f}" if prev is not None else ""
        prev = t
        import pretty_midi as _pm
        lines.append(f"  t={t:7.2f} +{inbar:5.2f} "
                     f"{_pm.note_number_to_name(p):4s} vel={v:3d} "
                     f"dur={dur:.2f} dev={dev:.3f}{gap}")
    return "\n".join(lines)


def _bar_range(arg):
    if "-" in arg:
        a, b = arg.split("-")
        return range(int(a), int(b) + 1)
    return [int(arg)]


def cmd_map(args):
    for n in _bar_range(args.bar):
        m = bar_mapping(args.piece_dir, n)
        print(f"printed {m['printed_bar']:3d} | quantize m{m['quantize_measure']:3d} "
              f"| grid beats {m['grid_beats'][0]}-{m['grid_beats'][1]} "
              f"| audio {m['audio_s'][0]}-{m['audio_s'][1]}s "
              f"| midi {m['midi_s'][0]}-{m['midi_s'][1]}s")
    return 0


def cmd_bar(args):
    for n in _bar_range(args.bar):
        print(bar_diff(args.piece_dir, n))
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(required=True)
    for name, fn in (("map", cmd_map), ("bar", cmd_bar)):
        p = sub.add_parser(name)
        p.add_argument("piece_dir")
        p.add_argument("bar")
        p.set_defaults(fn=fn)
    args = ap.parse_args()
    sys.exit(args.fn(args))


if __name__ == "__main__":
    main()
