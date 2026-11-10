#!/usr/bin/env python3
"""Measure how long each engraved bar really lasted in the performance.

DuET infers meter and tempo and can be wrong in ways the score alone does not
show: stray longer bars, invented tempo changes, a pickup of the wrong length.
The recording settles it. This lines up DuET's bar grid (score.npz) with the
performed note times (the MIDI DuET engraved) and reports whether the piece is
steady, its real tempo, the real pickup length, and what to do about it.

    bar_timing.py <cleaned.mid> <score.npz> [--score <raw DuET .musicxml>]

Run it right after DuET. With --score it also compares the engraved bar lengths
and playback tempos against the measurement and prints recommendations.
"""
import argparse
import collections
import json
import sys
import xml.etree.ElementTree as ET

import numpy as np
import pretty_midi

STEADY_TOLERANCE = 0.08   # a bar within 8% of the median seconds-per-quarter is on tempo
STEADY_SHARE = 0.9        # the piece is steady when this share of its bars are


def analyze(times, onsets, bar_starts, bar_lengths):
    """times: performed onset (s) per note; onsets: DuET position (quarters) per note."""
    uq = np.unique(onsets)
    ut = np.array([np.median(times[onsets == q]) for q in uq])
    edges = np.append(bar_starts, bar_starts[-1] + bar_lengths[-1])
    dur = np.diff(np.interp(edges, uq, ut))
    spq = dur / bar_lengths                      # seconds per quarter, per bar
    body = slice(1, -1)                          # the first and last bar are partial
    med = float(np.median(spq[body]))
    on_tempo = np.abs(spq[body] / med - 1) <= STEADY_TOLERANCE
    share = float(on_tempo.mean())
    lengths = collections.Counter(float(x) for x in bar_lengths[body])
    written = float(edges[1] - onsets.min())
    measured = float(np.round(dur[0] / med * 2) / 2)   # to the nearest eighth
    return {
        "bars": int(len(bar_lengths)),
        "bar_quarters": lengths.most_common(1)[0][0],
        "seconds_per_quarter": round(med, 4),
        "measured_tempo_quarter_bpm": round(60 / med, 1),
        "steady": share >= STEADY_SHARE,
        "steady_share": round(share, 2),
        "unsteady_bars": [int(i) + 2 for i in np.flatnonzero(~on_tempo)],
        "pickup_written_quarters": written,
        "pickup_measured_quarters": measured,
        "pickup_mismatch": abs(written - measured) >= 0.5,
    }


def engraved_bar_quarters(xml_path):
    """Length in quarters of every measure, from the time signatures in force."""
    with open(xml_path, encoding="utf-8") as f:
        text = f.read()
    root = ET.fromstring(text[text.index("<score-partwise"):])
    out, quarters = [], 4.0
    for measure in root.find("part").findall("measure"):
        time = measure.find("attributes/time")
        if time is not None:
            quarters = int(time.findtext("beats")) * 4 / int(time.findtext("beat-type"))
        out.append(quarters)
    return out


def stretched_bars(engraved, bar_lengths):
    """1-based numbers of the bars (first and last excluded) whose engraved length
    differs from DuET's raw bar length; None when the two bar counts differ."""
    if len(engraved) != len(bar_lengths):
        return None
    return [i + 1 for i in range(1, len(engraved) - 1) if engraved[i] != float(bar_lengths[i])]


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("performance_mid", help="the .mid DuET engraved (normally <slug>.cleaned.mid)")
    ap.add_argument("npz", help="score.npz from that DuET run")
    ap.add_argument("--score", help="the raw DuET .musicxml, to compare its bars and tempos")
    args = ap.parse_args()

    pm = pretty_midi.PrettyMIDI(args.performance_mid)
    played = sorted((n for inst in pm.instruments for n in inst.notes),
                    key=lambda n: (n.start, n.pitch))
    z = np.load(args.npz)
    rows = z["notes"]
    if len(rows) != len(played) or any(n.pitch != int(p) for n, p in zip(played, rows[:, 0])):
        sys.exit("score.npz does not match the performance MIDI — pass the .mid that DuET "
                 "engraved and its own score.npz")
    report = analyze(np.array([n.start for n in played]), rows[:, 1],
                     z["bar_starts"], z["bar_lengths"])
    advice = []
    if args.score:
        engraved = engraved_bar_quarters(args.score)
        with open(args.score, encoding="utf-8") as f:
            text = f.read()
        root = ET.fromstring(text[text.index("<score-partwise"):])
        tempos = sorted({s.get("tempo") for s in root.iter("sound") if s.get("tempo")})
        stretched = stretched_bars(engraved, z["bar_lengths"])
        report["engraved_bar_quarters"] = dict(collections.Counter(engraved))
        report["stretched_bars"] = stretched
        report["playback_tempos"] = tempos
        bpm = round(report["measured_tempo_quarter_bpm"])
        if report["steady"] and stretched:
            advice.append(f"re-run DuET with grid_count_fix false: bars {stretched} are steady "
                          "in the recording but were engraved at a different length")
        if report["steady"] and len(tempos) > 1:
            advice.append(f"normalize_tempo.py --tempo {bpm}: the recording is steady but the "
                          f"score has {len(tempos)} playback tempos")
    if report["pickup_mismatch"]:
        advice.append(f"check the pickup bar by ear: written {report['pickup_written_quarters']} "
                      f"quarters, played {report['pickup_measured_quarters']}")
    if report["bar_quarters"] == 3.0:
        advice.append("bars are 3 quarters long: 3/4 or 6/8 is a labelling choice — decide by "
                      "style, then relabel_meter.py --from 3/4 --to 6/8")
    report["recommendations"] = advice
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
