#!/usr/bin/env python3
"""Beat-grid diagnosis and declarative repair.

diagnose: tempo map + windowed probe + free scans over flagged spans —
numbers only; classifying a span (level hop / lost pulse / rubato) is the
grid-surgery skill's job.
repair: execute a surgery-plan JSON (splice / lattice / tail ops) with all
seam, parity and monotonicity mechanics owned here.
"""
import argparse
import json
import os
import statistics
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from transcription_cleanup import (  # noqa: E402
    grid_fit_probe, nudge_beats_to_onsets,
)


def _onsets(mid_path, midi_shift):
    import pretty_midi
    pm = pretty_midi.PrettyMIDI(mid_path)
    return sorted(n.start + midi_shift
                  for i in pm.instruments for n in i.notes)


def tempo_map(beats, block=32):
    per = [b - a for a, b in zip(beats, beats[1:])]
    out = []
    for i0 in range(0, len(per) - block, block):
        m = statistics.median(per[i0:i0 + block])
        out.append({"beats": [i0, i0 + block],
                    "bars": [i0 // 4 + 1, (i0 + block) // 4],
                    "t_start": round(beats[i0], 1),
                    "median_period": round(m, 3),
                    "bpm": round(60 / m, 1)})
    return out


def free_scan(onsets, t0, t1, plo, phi):
    """Best (fit, bpm) for a uniform grid with free phase over [t0, t1)."""
    w = np.array([t for t in onsets if t0 <= t < t1])
    if len(w) < 8:
        return None, None
    best = (0.0, None)
    for p in np.arange(plo, phi, 0.002):
        for ph in np.arange(0, p, p / 40):
            x = (w - t0 + ph) / p * 4
            f = float(np.mean(np.abs(x - np.round(x)) / 4 <= 0.07))
            if f > best[0]:
                best = (f, p)
    return round(best[0], 3), (round(60 / best[1], 1) if best[1] else None)


def _clusters(windows):
    """Merge overlapping/adjacent flagged windows into spans of beat indices."""
    spans = []
    for wnd in sorted(windows, key=lambda w: w["beats"][0]):
        b0, b1 = wnd["beats"]
        if spans and b0 <= spans[-1][1]:
            spans[-1][1] = max(spans[-1][1], b1)
        else:
            spans.append([b0, b1])
    return spans


def diagnose(mid_path, beats_json, midi_shift):
    beats = json.load(open(beats_json))["beats"]
    ons = _onsets(mid_path, midi_shift)
    probe = grid_fit_probe(mid_path, beats, midi_shift)
    med = statistics.median(b - a for a, b in zip(beats, beats[1:]))
    clusters = []
    flagged = probe["weak_windows"] + probe["level_hop_suspects"]
    for b0, b1 in _clusters(flagged):
        t0, t1 = beats[b0], beats[min(b1, len(beats) - 1)]
        qf, qb = free_scan(ons, t0, t1, med * 0.8, med * 1.2)
        sf, sb = free_scan(ons, t0, t1, med * 0.8 * 0.75, med * 1.2 * 0.75)
        seg = [t for t in ons if t0 <= t < t1]
        gfit = None
        if seg:
            import bisect
            n = 0
            for t in seg:
                i = bisect.bisect_right(beats, t) - 1
                i = max(0, min(i, len(beats) - 2))
                frac = i + (t - beats[i]) / (beats[i + 1] - beats[i])
                f = frac - int(frac)
                n += abs(f - round(f * 4) / 4) <= 0.07
            gfit = round(n / len(seg), 3)
        clusters.append({
            "beats": [b0, b1], "bars": [b0 // 4 + 1, b1 // 4 + 1],
            "span_s": [round(t0, 2), round(t1, 2)],
            "grid_fit": gfit,
            "quarter_scan": {"fit": qf, "bpm": qb},
            "sublevel_scan": {"fit": sf, "bpm": sb},
        })
    return {"tempo_map": tempo_map(beats), "probe": probe,
            "flag_clusters": clusters}


def cmd_diagnose(args):
    rep = diagnose(args.mid, args.beats, args.midi_shift)
    text = json.dumps(rep, indent=2)
    if args.output:
        with open(args.output, "w") as f:
            f.write(text)
    print(text)
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(required=True)
    d = sub.add_parser("diagnose")
    d.add_argument("mid")
    d.add_argument("beats")
    d.add_argument("--midi-shift", type=float, default=0.0)
    d.add_argument("--output")
    d.set_defaults(fn=cmd_diagnose)
    args = ap.parse_args()
    sys.exit(args.fn(args))


if __name__ == "__main__":
    main()
