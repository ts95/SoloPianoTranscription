#!/usr/bin/env python3
"""Replace a score's pedaling with harmony-aware legato pedal marks.

Reads the NOTATED harmony from the .mscz (bass pitch-class at beat 1 vs the
half-bar) and lays one syncopated pedal per measure, split mid-bar where the
harmony changes. This is independent of the transcriber's CC64, which is only
binary (0/127) and under-segments fast re-pedaling, so it does not track the
harmony. Edits the .mscz in place (the .bak the library writes is removed
unless --keep-backup).

Usage: apply_harmony_pedal.py <file.mscz> [--staff 2] [--keep-backup]
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from musescore_pedal_lib import (
    extract_mscz, extract_measure_data, add_pedals, make_syncopated_pedal_config,
)
from analyze_pedaling import analyze_measure


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("mscz")
    ap.add_argument("--staff", default="2", help="staff to pedal (default 2 = bass)")
    ap.add_argument("--keep-backup", action="store_true")
    args = ap.parse_args()

    if not os.path.exists(args.mscz):
        print(f"ERROR: not found: {args.mscz}", file=sys.stderr)
        sys.exit(1)

    mscx = extract_mscz(args.mscz, "/tmp/harmony_pedal_analyze")
    measures = extract_measure_data(mscx, staff_ids=("1", "2"))
    results = [analyze_measure(m) for m in measures]
    splits = {r["number"] for r in results if r["recommendation"] == "split"}
    review = {r["number"] for r in results if r["recommendation"] == "review"}
    ticks = {r["number"]: r["ticks"] for r in results}
    sigs = {r["number"]: r["time_sig"] for r in results}

    cfg = make_syncopated_pedal_config(
        lambda m: ticks.get(m, 1920),
        split_measures=splits,
        time_sig_fn=lambda m: sigs.get(m, "4/4"))

    add_pedals(args.mscz, cfg, staff_id=args.staff)

    if not args.keep_backup:
        bak = args.mscz + ".bak"
        if os.path.exists(bak):
            os.remove(bak)

    print(f"\nharmony pedal: {len(results)} measures, {len(splits)} split at a "
          f"harmony change, {len(results) - len(splits)} single"
          + (f"; review (verify by ear): {sorted(review)}" if review else ""))


if __name__ == "__main__":
    main()
