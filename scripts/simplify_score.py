"""Playability reduction for engraved two-staff piano scores.

Turns a faithful-but-unplayable transcription (Synthesia-style full stacks
re-struck on every 16th) into a playable edition, without touching what makes
the arrangement: melody (RH top line), bass roots (LH bottom), the rhythm
pattern, and every harmony-change chord. The cleaned MIDI remains the
faithful capture; this is an ARRANGEMENT edit, so it is NOT part of the
default pipeline — run it only when the user asks for a playable/simplified
score.

Three rules, applied in order per chord event:

A. Thin re-strikes under pedal: a >=3-note chord that introduces no new
   pitch class over the previous same-staff event and is not on a downbeat
   is a repeat strike — the pedal already carries the harmony. Keep the top
   two notes (RH: melody + one inner) or the bottom note (LH: bass).
B. Reduce LH stacks the RH already covers: where the simultaneous RH event
   has >=3 notes, the LH keeps at most bass + octave/fifth.
C. Cap hand span at an octave: shrink from the unprotected end (RH drops its
   bottom note, LH its top) — dropping a note whose pitch class is still
   present in the same-time two-hand aggregate, otherwise folding it an
   octave inward — until the chord fits a hand.

Tied chords are left untouched (thinning one end of a tie orphans the other).

Usage: .venv/bin/python scripts/simplify_score.py in.musicxml -o out.musicxml
"""
import argparse
import json

from music21 import chord as m21chord
from music21 import converter
from music21 import note as m21note


def events_by_offset(part):
    """[(offset, element)] for all notes/chords, chronological."""
    evs = []
    for el in part.recurse().notes:
        evs.append((float(el.getOffsetInHierarchy(part)), el))
    evs.sort(key=lambda t: t[0])
    return evs


def pitches_of(el):
    return sorted(p.midi for p in el.pitches)


def is_tied(el):
    if el.tie is not None:
        return True
    return any(n.tie is not None for n in getattr(el, "notes", []))


def replace_pitches(part, el, keep_midis, stats):
    """Shrink a chord to keep_midis (a chord stays a chord, one note becomes
    a Note); duration/offset/expressions survive. Pitches are the ORIGINAL
    Pitch objects (octave-transposed for folded notes) so the key-aware
    spelling and accidental display already computed upstream survive —
    rebuilding from midi ints re-spells and sprays accidentals."""
    keep = sorted(set(keep_midis))
    if keep == pitches_of(el):
        return el
    stats["notes_removed"] += len(el.pitches) - len(keep)
    by_midi = {p.midi: p for p in el.pitches}
    pitches = []
    for m in keep:
        if m in by_midi:
            pitches.append(by_midi[m])
        else:  # octave-folded: same name, shifted octave
            src = next(p for p in el.pitches if (p.midi - m) % 12 == 0)
            pitches.append(src.transpose(12 * ((m - src.midi) // 12)))
    parent = el.activeSite
    if len(pitches) == 1:
        new = m21note.Note(pitches[0])
    else:
        new = m21chord.Chord(pitches)
    new.duration = el.duration
    new.expressions = el.expressions
    new.articulations = el.articulations
    new.beams = el.beams  # keep the beam group; a bare note un-beams its run
    parent.replace(el, new)
    return new


def simplify(score, bar_ql):
    parts = list(score.parts)
    rh, lh = parts[0], parts[-1]
    stats = {"repeat_strikes_thinned": 0, "lh_stacks_reduced": 0,
             "spans_capped": 0, "notes_removed": 0}

    all_evs = {id(p): events_by_offset(p) for p in (rh, lh)}
    # simultaneous aggregate, rebuilt lazily after edits is overkill —
    # removals only ever shrink chords, so the pre-pass map stays a valid
    # superset for the "pitch class still present" test in rule C
    aggregate = {}
    for p in (rh, lh):
        for off, el in all_evs[id(p)]:
            aggregate.setdefault(off, set()).update(pitches_of(el))

    for p in (rh, lh):
        is_rh = p is rh
        bar_pcs, bar_no = set(), -1
        for off, el in all_evs[id(p)]:
            ps = pitches_of(el)
            if is_tied(el):
                continue
            # the per-bar pedal carries every pitch class struck since the
            # downbeat, so "already sounding" is bar-scoped, not just the
            # previous event (chorus vamps alternate between two stacks)
            if int(off // bar_ql) != bar_no:
                bar_no, bar_pcs = int(off // bar_ql), set()
            new_pcs = {m % 12 for m in ps} - bar_pcs
            bar_pcs |= {m % 12 for m in ps}

            # A: repeat strike -> melody/bass skeleton
            if len(ps) >= 3 and not new_pcs:
                keep = ps[-2:] if is_rh else ps[:1]
                el = replace_pitches(p, el, keep, stats)
                stats["repeat_strikes_thinned"] += 1
                continue

            # B: LH stack the RH already voices -> bass + octave/fifth
            if not is_rh and len(ps) >= 4:
                rh_now = next((pitches_of(e) for o, e in all_evs[id(rh)]
                               if o == off), [])
                if len(rh_now) >= 3:
                    bass = ps[0]
                    partners = [m for m in ps[1:] if (m - bass) % 12 in (0, 7)]
                    keep = [bass] + partners[:1]
                    el = replace_pitches(p, el, keep, stats)
                    stats["lh_stacks_reduced"] += 1
                    ps = pitches_of(el)

            # C: cap the hand span at an octave via doubled-pc deletion —
            # shrink toward the protected end (RH keeps its top = melody,
            # LH keeps its bottom = bass), only dropping notes whose pitch
            # class survives in the same-time two-hand aggregate
            if len(ps) >= 2 and ps[-1] - ps[0] > 12:
                keep = list(ps)
                changed = False
                while keep[-1] - keep[0] > 12 and len(keep) > 1:
                    m = keep[0] if is_rh else keep[-1]
                    rest = set(keep) - {m}
                    agg_pcs = {x % 12 for x in (aggregate[off] - {m}) | rest}
                    keep.remove(m)
                    if m % 12 not in agg_pcs:
                        # pitch class not doubled anywhere: fold the note an
                        # octave inward (revoice) instead of dropping it
                        keep.append(m + 12 if is_rh else m - 12)
                        keep.sort()
                    changed = True
                if changed:
                    el = replace_pitches(p, el, keep, stats)
                    stats["spans_capped"] += 1
    return stats


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("input")
    ap.add_argument("-o", "--output", required=True)
    args = ap.parse_args()

    score = converter.parse(args.input)
    ts = score.recurse().getElementsByClass("TimeSignature").first()
    bar_ql = float(ts.barDuration.quarterLength) if ts is not None else 4.0
    stats = simplify(score, bar_ql)
    tot = disp = 0
    for el in score.recurse().notes:
        for pch in el.pitches:
            tot += 1
            disp += bool(pch.accidental is not None
                         and pch.accidental.displayStatus)
    stats["printed_accidental_ratio"] = round(disp / max(1, tot), 3)
    score.write("musicxml", fp=args.output)
    stats["output"] = args.output
    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
