#!/usr/bin/env python3
"""Write a one-hand MIDI from a cleaned transcription.

The hand of each note is DuET's own staff assignment (score.npz, written next
to the score when DuET engraved this MIDI), so the extracted hand matches what
the bass (or treble) staff shows. A static pitch threshold is NOT used: solo
piano hands overlap in register and cross, which a threshold cannot follow.

    .venv/bin/python scripts/split_hands_midi.py <cleaned.mid> <score.npz> <out.mid> [--hand bass|treble]

Pass the SAME .mid DuET engraved (normally <slug>.cleaned.mid) and the
score.npz from that run; a mismatch is refused. Tempo / time-signature / key
meta and the performed CC64 are carried over verbatim: the result is the same
recording with one hand muted.
"""
import argparse
import os
import sys

import numpy as np
import pretty_midi

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from transcription_cleanup import all_notes  # noqa: E402

STAFF_OF_HAND = {"treble": 0, "bass": 1}  # score.npz notes[:, 3]: 0 upper, 1 lower


def split(pm, npz_pitches, npz_staff, hand):
    """Notes of `pm` that DuET put on `hand`'s staff. Row i of the npz arrays
    is the i-th note of `pm` in (start, pitch) order — the order all_notes returns."""
    notes = all_notes(pm)
    if len(notes) != len(npz_pitches) or any(
            n.pitch != int(p) for n, p in zip(notes, npz_pitches)):
        raise SystemExit(
            f"score.npz does not match this MIDI ({len(npz_pitches)} vs {len(notes)} notes, "
            "or different pitches) — pass the .mid that DuET engraved and its own score.npz")
    want = STAFF_OF_HAND[hand]
    return [n for n, s in zip(notes, npz_staff) if int(s) == want]


def write_hand(in_path, npz_path, out_path, hand):
    pm = pretty_midi.PrettyMIDI(in_path)
    rows = np.load(npz_path)["notes"]
    kept = split(pm, rows[:, 0], rows[:, 3], hand)

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


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", help="the .mid DuET engraved (normally <slug>.cleaned.mid)")
    ap.add_argument("npz", help="score.npz from that DuET run")
    ap.add_argument("output", help="destination .mid")
    ap.add_argument("--hand", choices=("bass", "treble"), default="bass",
                    help="bass = lower staff / left hand (default), treble = upper staff / right hand")
    args = ap.parse_args()

    kept, total = write_hand(args.input, args.npz, args.output, args.hand)
    print(f"{args.output}: {kept} of {total} notes ({args.hand})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
