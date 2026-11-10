#!/usr/bin/env python3
"""Write a one-hand MIDI from a cleaned transcription.

Reuses `transcription_cleanup.assign_hands` — the same greedy cost model the
score's staff assignment uses — so the extracted hand matches what the bass
(or treble) staff would engrave. A static pitch threshold is NOT used: solo
piano hands overlap in register and cross, which a threshold cannot follow.

    .venv/bin/python scripts/split_hands_midi.py <cleaned.mid> <out.mid> [--hand bass|treble]

Tempo / time-signature / key meta and the performed CC64 are carried over
verbatim: the result is the same recording with one hand muted.
"""
import argparse
import os
import sys

import pretty_midi

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from transcription_cleanup import all_notes, assign_hands  # noqa: E402


def split(pm, hand):
    """Notes of `pm` belonging to `hand` ("bass" = left, "treble" = right)."""
    notes = all_notes(pm)
    if not notes:
        return []
    hands = assign_hands(notes)
    return [n for n in notes if hands[id(n)] == hand]


def write_hand(in_path, out_path, hand):
    pm = pretty_midi.PrettyMIDI(in_path)
    kept = split(pm, hand)

    _, tempi = pm.get_tempo_changes()
    out = pretty_midi.PrettyMIDI(initial_tempo=float(tempi[0]) if len(tempi) else 120.0)
    out.time_signature_changes = list(pm.time_signature_changes)
    out.key_signature_changes = list(pm.key_signature_changes)

    inst = pretty_midi.Instrument(program=0, name=f"Piano ({hand})")
    for n in kept:
        inst.notes.append(pretty_midi.Note(
            velocity=n.velocity, pitch=n.pitch, start=n.start, end=n.end))
    # ponytail: pedal is shared by both hands, so it is copied whole, not split.
    for src in pm.instruments:
        for cc in src.control_changes:
            if cc.number == 64:
                inst.control_changes.append(
                    pretty_midi.ControlChange(64, cc.value, cc.time))
    out.instruments.append(inst)
    out.write(out_path)
    return len(kept), len(all_notes(pm))


def _self_check():
    """Two clearly-separated hands must split cleanly and lose no note."""
    pm = pretty_midi.PrettyMIDI(initial_tempo=120.0)
    inst = pretty_midi.Instrument(program=0)
    for i in range(8):  # walking bass under a treble melody, same onsets
        t = i * 0.5
        inst.notes.append(pretty_midi.Note(velocity=80, pitch=40 + i, start=t, end=t + 0.5))
        inst.notes.append(pretty_midi.Note(velocity=80, pitch=72 + i, start=t, end=t + 0.5))
    pm.instruments.append(inst)

    lo = split(pm, "bass")
    hi = split(pm, "treble")
    assert len(lo) == 8 and len(hi) == 8, (len(lo), len(hi))
    assert len(lo) + len(hi) == len(all_notes(pm)), "notes lost or duplicated"
    assert max(n.pitch for n in lo) < min(n.pitch for n in hi), "hands crossed"
    print("self-check ok")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", nargs="?", help="cleaned .mid")
    ap.add_argument("output", nargs="?", help="destination .mid")
    ap.add_argument("--hand", choices=("bass", "treble"), default="bass",
                    help="bass = left hand (default), treble = right hand")
    ap.add_argument("--self-check", action="store_true")
    args = ap.parse_args()

    if args.self_check:
        _self_check()
        return 0
    if not args.input or not args.output:
        ap.error("input and output are required")

    kept, total = write_hand(args.input, args.output, args.hand)
    print(f"{args.output}: {kept} of {total} notes ({args.hand})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
