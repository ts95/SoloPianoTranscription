#!/usr/bin/env python3
"""Give a score-exported MIDI the performed velocities.

The score MIDI (exported from the hand-finished .mscz) has perfectly quantized
rhythm but MuseScore's flat block dynamics; the cleaned transcription MIDI has
the real touch but performance timing. This copies each performed note's
velocity onto the matching score note, so the result plays the score's rhythm
with the recording's phrasing.

    scripts/mscore.sh '<slug>.mscz' -o '<tmp>/score.mid'      # export first
    .venv/bin/python scripts/quantized_midi.py <score.mid> <cleaned.mid> <score.npz> <out.mid>

Pass the .mid DuET engraved and the score.npz from that run: row i of
score.npz["notes"] is the i-th performed note in (start, pitch) order, and its
column 1 is where DuET placed that note in the score (in quarter notes). A
score note takes the velocity of the closest unused performed note of the same
pitch within MAX_DISTANCE quarters; a note with no match (added or re-pitched
by hand) takes the average velocity of the matched notes around it.

Only note-on velocities change — tempo, timing, tracks and pedal are the
score export's own.
"""
import argparse
import json
import statistics
import sys

import mido
import numpy as np
import pretty_midi

MAX_DISTANCE = 2.0   # quarters: how far a hand-moved note may sit from DuET's placement
NEIGHBOURHOOD = 2.0  # quarters: unmatched notes average the matched notes this close


def assign_velocities(score, perf):
    """score: [(quarter, pitch)], perf: [(quarter, pitch, velocity)].
    Returns (velocities aligned with `score`, number matched to a performed note)."""
    pairs = sorted((abs(sq - pq), si, pi)
                   for si, (sq, sp) in enumerate(score)
                   for pi, (pq, pp, _) in enumerate(perf)
                   if sp == pp and abs(sq - pq) <= MAX_DISTANCE)
    vel, used = {}, set()
    for _, si, pi in pairs:
        if si not in vel and pi not in used:
            vel[si] = perf[pi][2]
            used.add(pi)
    fallback = round(statistics.median(v for _, _, v in perf))
    out = []
    for si, (sq, _) in enumerate(score):
        if si in vel:
            out.append(vel[si])
            continue
        near = [vel[j] for j, (q, _) in enumerate(score) if j in vel and abs(q - sq) <= NEIGHBOURHOOD]
        out.append(round(sum(near) / len(near)) if near else fallback)
    return out, len(vel)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("score_mid", help="MIDI exported from the finished .mscz")
    ap.add_argument("performance_mid", help="the .mid DuET engraved (normally <slug>.cleaned.mid)")
    ap.add_argument("npz", help="score.npz from that DuET run")
    ap.add_argument("output")
    args = ap.parse_args()

    pm = pretty_midi.PrettyMIDI(args.performance_mid)
    played = sorted((n for inst in pm.instruments for n in inst.notes),
                    key=lambda n: (n.start, n.pitch))
    rows = np.load(args.npz)["notes"]
    if len(rows) != len(played) or any(n.pitch != int(p) for n, p in zip(played, rows[:, 0])):
        sys.exit("score.npz does not match the performance MIDI — pass the .mid that DuET "
                 "engraved and its own score.npz")
    perf = [(float(q), n.pitch, n.velocity) for n, q in zip(played, rows[:, 1])]

    mid = mido.MidiFile(args.score_mid)
    note_ons = []  # (quarter, pitch, message)
    for track in mid.tracks:
        tick = 0
        for msg in track:
            tick += msg.time
            if msg.type == "note_on" and msg.velocity > 0:
                note_ons.append((tick / mid.ticks_per_beat, msg.note, msg))
    velocities, matched = assign_velocities([(q, p) for q, p, _ in note_ons], perf)
    for (_, _, msg), v in zip(note_ons, velocities):
        msg.velocity = max(1, min(127, v))
    mid.save(args.output)

    print(json.dumps({"output": args.output, "score_notes": len(note_ons),
                      "matched_to_performance": matched,
                      "filled_from_neighbours": len(note_ons) - matched,
                      "performed_notes": len(perf)}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
