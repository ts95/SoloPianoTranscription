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


def _snap_downbeat(beats, t, side):
    """Index of the base-grid downbeat (idx % 4 == 0) nearest t, biased
    before (side='start') or after (side='end')."""
    import bisect
    i = bisect.bisect_left(beats, t)
    cands = [j for j in range(max(0, i - 4), min(len(beats), i + 5))
             if j % 4 == 0]
    if not cands:
        raise SystemExit(f"repair: no downbeat near t={t}")
    if side == "start":
        before = [j for j in cands if beats[j] <= t + 1e-6]
        return before[-1] if before else cands[0]
    after = [j for j in cands if beats[j] >= t - 1e-6]
    return after[0] if after else cands[-1]


def _fit_region(ons, beats, t0, t1):
    import bisect
    seg = [t for t in ons if t0 <= t < t1]
    if not seg:
        return None
    n = 0
    for t in seg:
        i = bisect.bisect_right(beats, t) - 1
        i = max(0, min(i, len(beats) - 2))
        frac = i + (t - beats[i]) / (beats[i + 1] - beats[i])
        f = frac - int(frac)
        n += abs(f - round(f * 4) / 4) <= 0.07
    return round(n / len(seg), 3)


def repair(plan_path):
    plan_dir = os.path.dirname(os.path.abspath(plan_path))
    plan = json.load(open(plan_path))
    rel = lambda p: os.path.join(plan_dir, p)
    base = json.load(open(rel(plan["base"])))
    beats = list(base["beats"])
    ons = _onsets(rel(plan["midi"]), plan["midi_shift"])
    t_end_all = ons[-1] + 0.6

    spans = []
    for r in plan["repairs"]:
        lo = r["span_s"][0]
        hi = t_end_all if r["span_s"][1] == "end" else r["span_s"][1]
        spans.append((lo, hi, r))
    spans.sort()
    for (a0, a1, _), (b0, b1, _) in zip(spans, spans[1:]):
        if b0 < a1 - 1e-6:
            raise SystemExit(f"repair: overlapping spans {a1} > {b0}")

    before = grid_fit_probe(rel(plan["midi"]), beats, plan["midi_shift"])
    region_before = {}

    for lo, hi, r in reversed(spans):        # right-to-left keeps left indices
        i0 = _snap_downbeat(beats, lo, "start")
        open_end = r["span_s"][1] == "end"
        i1 = len(beats) - 1 if open_end else _snap_downbeat(beats, hi, "end")
        t0, t1 = beats[i0], (t_end_all if open_end else beats[i1])
        region_before[f"{round(t0, 2)}-{round(t1, 2)}"] = _fit_region(
            ons, beats, t0, t1)

        if r["op"] == "splice":
            src = json.load(open(rel(r["source"])))["beats"]
            seg = [t for t in src if t0 + 1e-6 < t < t1 - 1e-6]
            while (len(seg) + 1) % 4 != 0:
                seg = seg[:-1]
            new_seg = seg
        elif r["op"] == "lattice":
            pieces = r.get("pieces") or [["end", r["period"]]]
            g = [t0]
            for lim, p in pieces:
                stop = t1 if lim == "end" else min(float(lim), t1)
                while g[-1] + p < stop - 1e-6:
                    g.append(g[-1] + p)
            if not open_end:
                n = len(g)                    # beats strictly inside + anchor
                want = ((n + 2) // 4) * 4 - 1  # interior count ≡ 3 (mod 4)
                p_last = pieces[-1][1]
                while len(g) - 1 < want:
                    g.append(g[-1] + p_last)
                while len(g) - 1 > want and len(g) > 2:
                    g.pop()
                span = t1 - t0
                scale = span / (g[-1] + p_last - t0)
                g = [t0 + (x - t0) * scale for x in g]
            new_seg = nudge_beats_to_onsets(
                g + ([] if open_end else [t1]), ons,
                pin_start=True, pin_end=not open_end)
            new_seg = new_seg[1:] if open_end else new_seg[1:-1]
        elif r["op"] == "tail":
            clusters = []
            for t in [x for x in ons if x >= t0 - 0.1]:
                if clusters and t - clusters[-1][-1] < 0.05:
                    clusters[-1].append(t)
                else:
                    clusters.append([t])
            ctimes = [c[0] for c in clusters]
            new_seg, b = [], t0
            while b < t_end_all:
                win = [ctimes[i + 1] - ctimes[i]
                       for i in range(len(ctimes) - 1)
                       if b - 0.3 <= ctimes[i] <= b + 1.8
                       and ctimes[i + 1] - ctimes[i] < 0.6]
                p16 = statistics.median(win) if win else 0.3
                nxt = b + 4 * p16
                near = min(ctimes, key=lambda c: abs(c - nxt)) if ctimes else nxt
                if abs(near - nxt) <= 0.12:
                    nxt = near
                new_seg.append(round(nxt, 4))
                b = nxt
        else:
            raise SystemExit(f"repair: unknown op {r['op']!r}")

        tail = [] if open_end else beats[i1:]
        beats = beats[:i0 + 1] + [round(float(x), 4) for x in new_seg] + tail

    if not all(y > x for x, y in zip(beats, beats[1:])):
        raise SystemExit("repair: non-monotonic result")

    after = grid_fit_probe(rel(plan["midi"]), beats, plan["midi_shift"])
    # untouched-region regression guard (compare complement of spans)
    span_ts = [(lo, hi) for lo, hi, _ in spans]
    edges = [beats[0]] + [t for pair in span_ts for t in pair] + [beats[-1]]
    for j in range(0, len(edges) - 1, 2):
        t0, t1 = edges[j], edges[j + 1]
        if t1 - t0 < 2.0:
            continue
        fb = _fit_region(ons, base["beats"], t0, t1)
        fa = _fit_region(ons, beats, t0, t1)
        if fb and fa and fa < fb - 0.02:
            raise SystemExit(
                f"repair: fit regression in untouched region "
                f"[{t0:.1f},{t1:.1f}] {fb} -> {fa}")
    if after["onset_grid_fit"] < before["onset_grid_fit"] - 0.005:
        raise SystemExit(
            f"repair: global fit regressed "
            f"{before['onset_grid_fit']} -> {after['onset_grid_fit']}")

    out = dict(base)
    out["beats"] = beats
    out["n_beats"] = len(beats)
    out["source"] = f"grid_surgery repair: {os.path.basename(plan_path)}"
    per = [b - a for a, b in zip(beats, beats[1:])]
    out["tempo_median_bpm"] = round(60 / statistics.median(per), 1)
    out["beat_period_cv"] = round(statistics.pstdev(per) / statistics.mean(per), 3)
    out.update(after)
    with open(rel(plan["output"]), "w") as f:
        json.dump(out, f, indent=2)
    report = {"before": {k: before[k] for k in
                         ("onset_grid_fit", "subdivision_fit")},
              "after": {k: after[k] for k in
                        ("onset_grid_fit", "subdivision_fit")},
              "regions_before": region_before,
              "output": plan["output"]}
    print(json.dumps(report, indent=2))
    return report


def cmd_repair(args):
    repair(args.plan)
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
    r = sub.add_parser("repair")
    r.add_argument("plan")
    r.set_defaults(fn=cmd_repair)
    args = ap.parse_args()
    sys.exit(args.fn(args))


if __name__ == "__main__":
    main()
