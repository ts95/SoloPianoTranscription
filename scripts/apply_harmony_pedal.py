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


def write_midi_pedal(midi_path, get_pedals_fn, measure_numbers, ticks_map,
                     beats_path):
    """Write the harmony-pedal schedule into a MIDI as CC64, REPLACING any
    existing sustain events (the transcriber's CC64 under-detects pedal on
    synth/washy sources). Measure ticks (480/quarter) map to global beats,
    then to seconds through beats.json — so this assumes the MIDI starts on
    the grid's bar 1 beat 1 (bar-phase 0, no pickup)."""
    import json

    import pretty_midi

    with open(beats_path) as f:
        beats = json.load(f)["beats"]

    def beat_to_s(b):
        i = max(0, min(int(b), len(beats) - 2))
        return beats[i] + (b - i) * (beats[i + 1] - beats[i])

    events = []
    cursor = 0.0  # global beat of the current measure's downbeat
    for mnum in measure_numbers:
        mt = ticks_map[mnum]
        for start_tick, end_tick, _span in get_pedals_fn(mnum):
            events.append((beat_to_s(cursor + start_tick / 480), 127))
            events.append((beat_to_s(cursor + end_tick / 480), 0))
        cursor += mt / 480

    pm = pretty_midi.PrettyMIDI(midi_path)
    inst = pm.instruments[0]
    inst.control_changes = [c for c in inst.control_changes if c.number != 64]
    for t, v in events:
        inst.control_changes.append(
            pretty_midi.ControlChange(64, v, max(0.0, t)))
    inst.control_changes.sort(key=lambda c: c.time)
    pm.write(midi_path)
    return len(events) // 2


def strip_beam_modes(root):
    """Remove every explicit <BeamMode> so MuseScore auto-beams by meter.

    MuseScore's MusicXML import pins each stem's beaming: music21's beam pass
    leaves holes (and the import turns every beam-less stem into a forced
    BeamMode "no" break), which engraves runs of detached flagged notes that
    should be beamed. Generated scores never carry intentional beam breaks,
    so auto-beam authority is always right for them.
    """
    removed = 0
    for parent in root.iter():
        for child in [c for c in parent if c.tag == "BeamMode"]:
            parent.remove(child)
            removed += 1
    print(f"beam cleanup: {removed} forced BeamMode elements removed "
          "(MuseScore auto-beams by meter)")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("mscz")
    ap.add_argument("--staff", default="2", help="staff to pedal (default 2 = bass)")
    ap.add_argument("--keep-backup", action="store_true")
    ap.add_argument("--midi", help="also write the pedal schedule into this "
                                   ".mid as CC64 (replaces existing sustain)")
    ap.add_argument("--beats", help="beats.json mapping beats to seconds "
                                    "(required with --midi)")
    args = ap.parse_args()
    if args.midi and not args.beats:
        ap.error("--midi requires --beats")

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

    # a measure with no notes in either staff has nothing to sustain —
    # pedaling engraved silence is wrong (e.g. a pause before an outro)
    empty = {m["number"] for m in measures
             if not any(ev["type"] == "Chord"
                        for st in m["staves"].values()
                        for v in st["voices"].values()
                        for ev in v)}
    base_cfg = cfg
    cfg = lambda mnum: [] if mnum in empty else base_cfg(mnum)

    add_pedals(args.mscz, cfg, staff_id=args.staff,
               post_process=strip_beam_modes)

    if args.midi:
        ordered = [r["number"] for r in results]
        n = write_midi_pedal(args.midi, cfg, ordered,
                             {r["number"]: r["ticks"] for r in results},
                             args.beats)
        print(f"CC64 pedal written to {args.midi}: {n} regions "
              "(replaced existing sustain)")

    if not args.keep_backup:
        bak = args.mscz + ".bak"
        if os.path.exists(bak):
            os.remove(bak)

    print(f"\nharmony pedal: {len(results)} measures, {len(splits)} split at a "
          f"harmony change, {len(results) - len(splits)} single"
          + (f"; review (verify by ear): {sorted(review)}" if review else ""))


if __name__ == "__main__":
    main()
