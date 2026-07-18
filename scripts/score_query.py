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


def _bar_signatures(sc):
    """(pitch multiset, rhythm tuple) per (part, measure)."""
    sigs = {}
    for pi, part in enumerate(sc.parts):
        for m in part.getElementsByClass("Measure"):
            pcs, rhythm = [], []
            for el in m.recurse().notesAndRests:
                if el.pitches and (el.tie is None or el.tie.type == "start"):
                    pcs += [p.midi for p in el.pitches]
                    rhythm.append(round(float(el.offset) * 4) / 4)
            key = m.number
            a, b = sigs.get(key, ([], []))
            sigs[key] = (a + pcs, sorted(set(b) | set(rhythm)))
    return sigs


def _jaccard(a, b):
    from collections import Counter
    ca, cb = Counter(a), Counter(b)
    inter = sum((ca & cb).values())
    union = sum((ca | cb).values())
    return inter / union if union else 0.0


def cmd_family(args):
    from music21 import converter
    d, man, slug, beats = load_piece(args.piece_dir)
    sc = converter.parse(os.path.join(d, slug + ".musicxml"))
    sigs = _bar_signatures(sc)
    qm = bar_to_beats(man, int(args.bar))[1]
    if qm not in sigs:
        print(f"no measure {qm}")
        return 1
    pcs0, rh0 = sigs[qm]
    rows = []
    for m, (pcs, rh) in sorted(sigs.items()):
        if m == qm:
            continue
        pj = _jaccard(pcs0, pcs)
        rj = _jaccard(rh0, rh)
        if pj >= 0.8:
            rows.append((m, "pitch+rhythm" if rj >= 0.8 else "pitch", pj, rj))
        elif rj >= 0.85 and len(rh0) >= 4:
            rows.append((m, "rhythm", pj, rj))
    off = 1 if man.get("anacrusis") else 0
    print(f"family of printed bar {args.bar} (quantize m{qm}):")
    for m, kind, pj, rj in rows:
        print(f"  printed bar {m - off:3d}  [{kind:12s}] "
              f"pitch-jaccard {pj:.2f}  rhythm-jaccard {rj:.2f}")
        print(f"    rhythm: {' '.join(str(x) for x in sigs[m][1])}")
    print(f"  this bar rhythm: {' '.join(str(x) for x in rh0)}")
    return 0


def cmd_sweep(args):
    import pretty_midi
    from music21 import converter
    from collections import Counter
    d, man, slug, beats = load_piece(args.piece_dir)
    sc = converter.parse(os.path.join(d, slug + ".musicxml"))
    stubs = unbal = 0
    arps = []
    for pi, part in enumerate(sc.parts):
        for m in part.getElementsByClass("Measure"):
            if m.number > 1 and abs(
                    float(m.duration.quarterLength)
                    - float(m.barDuration.quarterLength)) > 0.001:
                unbal += 1          # measure 1 may be a legitimate anacrusis
            for el in m.recurse().notesAndRests:
                t = getattr(el, "tie", None)
                if (t and t.type == "stop"
                        and el.duration.quarterLength <= 0.25
                        and float(el.offset) > 0):
                    stubs += 1
                if any(type(e).__name__ == "ArpeggioMark"
                       for e in getattr(el, "expressions", [])):
                    arps.append(m.number)
    # rhythm-skeleton near-misses
    sigs = _bar_signatures(sc)
    skeletons = Counter(tuple(rh) for _, rh in sigs.values() if len(rh) >= 4)
    near = []
    for m, (_, rh) in sorted(sigs.items()):
        t = tuple(rh)
        if skeletons.get(t, 0) >= 3:
            continue
        for sk, cnt in skeletons.items():
            if cnt >= 3:
                diff = set(sk) ^ set(t)
                if 0 < len(diff) <= 2:
                    near.append((m, list(sk)))
                    break
    # chord-brush ghosts still in the cleaned MIDI
    pm = pretty_midi.PrettyMIDI(os.path.join(d, slug + ".cleaned.mid"))
    ghosts = sum(1 for i in pm.instruments for n in i.notes
                 if (n.end - n.start) < 0.055 and n.velocity < 55)
    print(f"one-slot tie stubs: {stubs}")
    print(f"arpeggio marks: {len(arps)} (bars {sorted(set(arps))[:12]})")
    print(f"possible brush ghosts in cleaned MIDI: {ghosts}")
    print(f"rhythm-skeleton near-misses (<=2 moves vs >=3x skeleton): "
          f"{[m for m, _ in near]}")
    print(f"unbalanced measures: {unbal}")
    return 0


def cmd_layout(args):
    import re
    import zipfile
    d, man, slug, beats = load_piece(args.piece_dir)
    with zipfile.ZipFile(os.path.join(d, slug + ".mscz")) as z:
        mscx = next(n for n in z.namelist() if n.endswith(".mscx"))
        x = z.read(mscx).decode("utf-8", "replace")
    lb = x.count("<LayoutBreak>")
    labels = len(re.findall(r"<(?:long|short)Name>", x))
    pdf = os.path.join(d, slug + ".pdf")
    pages = []
    try:
        from pypdf import PdfReader
        for pg in PdfReader(pdf).pages:
            nums = [int(n) for n in re.findall(r"\b(\d{1,3})\b",
                                               pg.extract_text() or "")]
            bars = [n for n in nums if 1 <= n <= 400]
            pages.append(min(bars) if bars else None)
    except Exception as e:  # pypdf absent or PDF unreadable
        pages = [f"(pdf scan unavailable: {e})"]
    print(f"LayoutBreaks in mscz: {lb} (expect 0)")
    print(f"instrument labels in mscz: {labels} (expect 0)")
    print(f"first bar number per page: {pages}")
    if len([p for p in pages if isinstance(p, int)]) >= 2:
        firsts = [p for p in pages if isinstance(p, int)]
        gaps = [b - a for a, b in zip(firsts, firsts[1:])]
        if gaps and (min(gaps) <= max(gaps) // 4):
            print(f"WARNING: uneven bars-per-page distribution {gaps}")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(required=True)
    for name, fn in (("map", cmd_map), ("bar", cmd_bar)):
        p = sub.add_parser(name)
        p.add_argument("piece_dir")
        p.add_argument("bar")
        p.set_defaults(fn=fn)
    for name, fn in (("sweep", cmd_sweep), ("layout", cmd_layout)):
        p = sub.add_parser(name)
        p.add_argument("piece_dir")
        p.set_defaults(fn=fn)
    p = sub.add_parser("family")
    p.add_argument("piece_dir")
    p.add_argument("bar")
    p.set_defaults(fn=cmd_family)
    args = ap.parse_args()
    sys.exit(args.fn(args))


if __name__ == "__main__":
    main()
