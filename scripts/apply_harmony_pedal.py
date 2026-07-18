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
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from musescore_pedal_lib import (
    extract_mscz, extract_measure_data, add_pedals, make_syncopated_pedal_config,
    repackage_mscz, _find_score_staves,
)
from analyze_pedaling import analyze_measure

_REST_QL = {"whole": 4.0, "half": 2.0, "quarter": 1.0, "eighth": 0.5,
            "16th": 0.25, "32nd": 0.125, "64th": 0.0625}


def make_anacrusis(root, pad_beats):
    """Convert measure 1 from a padded full bar into a true pickup measure.

    quantize models a pickup by opening bar 1 with `pad_beats` beats of rest;
    engraved properly that bar is an anacrusis: a short implicit measure
    holding only the pickup. Strip the leading rests from every staff's first
    measure, shrink the measure (len attribute) and exclude it from the
    measure count. Runs BEFORE pedals are added — pedal spanners carry
    relative <location> anchors that rest removal would corrupt.
    """
    from fractions import Fraction
    pad = Fraction(pad_beats).limit_denominator(16)
    staves = _find_score_staves(root)
    plans = []
    for staff in staves:
        m1 = staff.find("Measure")
        if m1 is None:
            raise SystemExit("anacrusis: staff without measures")
        removed = Fraction(0)
        doomed = []
        for voice in m1.findall("voice"):
            for el in list(voice):
                if removed >= pad:
                    break
                if el.tag in ("Clef", "KeySig", "TimeSig", "Tempo", "eid",
                              "location", "BarLine"):
                    continue
                if el.tag != "Rest":
                    raise SystemExit(
                        f"anacrusis: found <{el.tag}> before {pad} beats of "
                        "leading rest — measure 1 does not match the pickup pad")
                dt = el.findtext("durationType")
                if dt == "measure":
                    raise SystemExit("anacrusis: full-measure rest in bar 1 — "
                                     "nothing to convert")
                ql = Fraction(_REST_QL[dt]).limit_denominator(64)
                dots = int(el.findtext("dots") or 0)
                ql = ql * (2 - Fraction(1, 2 ** dots))
                doomed.append((voice, el))
                removed += ql
            break  # leading rests live in voice 1; other voices start later
        if removed != pad:
            raise SystemExit(f"anacrusis: leading rests sum to {removed}, "
                             f"expected {pad}")
        plans.append((m1, doomed))
    # all staves matched — apply
    ts = root.find(".//TimeSig")
    bar_beats = Fraction(int(ts.findtext("sigN")) * 4, int(ts.findtext("sigD")))
    rem = bar_beats - pad
    ln = Fraction(rem, 4)
    for m1, doomed in plans:
        for voice, el in doomed:
            voice.remove(el)
        m1.set("len", f"{ln.numerator}/{ln.denominator}")
        irr = ET.SubElement(m1, "irregular")
        irr.text = "1"
    print(f"anacrusis: measure 1 shrunk to {rem} beat(s) "
          f"(len {ln.numerator}/{ln.denominator}), leading rests removed, "
          "excluded from measure count")


def apply_anacrusis(mscz_path, pad_beats,
                    extract_dir="/tmp/mscz_anacrusis"):
    mscx = extract_mscz(mscz_path, extract_dir)
    tree = ET.parse(mscx)
    make_anacrusis(tree.getroot(), pad_beats)
    tree.write(mscx, encoding="UTF-8", xml_declaration=True)
    repackage_mscz(mscz_path, extract_dir)


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
    ap.add_argument("--anacrusis", type=float, metavar="PAD_BEATS",
                    help="convert measure 1 from a padded bar (quantize's "
                         "pickup: PAD_BEATS beats of leading rest) into a true "
                         "anacrusis measure; runs before pedaling")
    args = ap.parse_args()
    if args.midi and not args.beats:
        ap.error("--midi requires --beats")

    if not os.path.exists(args.mscz):
        print(f"ERROR: not found: {args.mscz}", file=sys.stderr)
        sys.exit(1)

    if args.anacrusis:
        apply_anacrusis(args.mscz, args.anacrusis)

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
