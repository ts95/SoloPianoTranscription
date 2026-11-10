#!/usr/bin/env python3
"""Replace a score's pedaling with harmony-aware legato pedal marks.

Reads the NOTATED harmony from the .mscz (where in each bar does a new bass
note land?) and lays one syncopated pedal per measure, re-pedalled at every
such point. This is independent of the transcriber's CC64, which is only
binary (0/127) and under-segments fast re-pedaling, so it does not track the
harmony. Edits the .mscz in place (the .bak the library writes is removed
unless --keep-backup).

Usage: apply_harmony_pedal.py <file.mscz> [--staff 2] [--keep-backup]
"""
import argparse
import os
import tempfile
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from musescore_pedal_lib import (
    extract_mscz, extract_measure_data, add_pedals, ticks_to_frac,
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

    td = tempfile.TemporaryDirectory()  # private: concurrent runs must not share an extract dir
    mscx = extract_mscz(args.mscz, os.path.join(td.name, "analyze"))
    measures = extract_measure_data(mscx, staff_ids=("1", "2"))
    results = [analyze_measure(m) for m in measures]
    split_ticks = {r["number"]: r["split_ticks"] for r in results}
    review = {r["number"] for r in results if r["recommendation"] == "review"}
    ticks = {r["number"]: r["ticks"] for r in results}
    splits = {m for m, s in split_ticks.items() if s}

    def cfg(mnum, gap=60):
        """One legato pedal per segment between the bar's bass arrivals: down
        `gap` ticks after each boundary, up `gap` ticks before the next."""
        bounds = [0] + split_ticks.get(mnum, []) + [ticks.get(mnum, 1920)]
        return [(a + gap, b - gap, ticks_to_frac(b - a - 2 * gap))
                for a, b in zip(bounds, bounds[1:])]

    add_pedals(args.mscz, cfg, staff_id=args.staff, extract_dir=os.path.join(td.name, "write"))
    td.cleanup()

    if not args.keep_backup:
        bak = args.mscz + ".bak"
        if os.path.exists(bak):
            os.remove(bak)

    print(f"\nharmony pedal: {len(results)} measures, {len(splits)} re-pedalled at a "
          f"new bass ({sum(len(v) for v in split_ticks.values())} extra pedals), "
          f"{len(results) - len(splits)} single"
          + (f"; review (verify by ear): {sorted(review)}" if review else ""))


if __name__ == "__main__":
    main()
