#!/usr/bin/env python3
"""Analysis and cleanup helpers for Transkun piano transcriptions.

Subcommands:
  analyze  <in.mid>                       print a JSON report (read-only)
  clean    <in.mid> <out.mid> [opts]      MIDI-level pre-clean (artifacts, trim, meta)
  beats    <in.wav> <out.json>            beat-track the recording with librosa
  quantize <in.mid> <out.musicxml>        MIDI -> MusicXML on a fixed --bpm grid or a
                                          beat-tracked --beats warp (replaces MuseScore's
                                          MIDI import, which auto-detects its own tempo
                                          and must never be used)
  post     <in.musicxml> <out.musicxml>   music21 notation-level fixes

All decisions that require judgment (key, meter, thresholds) are passed in as
flags; this script only does the mechanical work and reports what it did.
"""
import argparse
import json
import statistics
import sys

import numpy as np
import pretty_midi

GHOST_INTERVALS = {12, 19, 24, 28}  # piano partials 2,3,4,5: 8ve, 12th, 15th, 17th above
SUB_GHOST_INTERVALS = {12}          # octave BELOW a louder note (sub-harmonic error)
ONSET_TOLERANCE = 0.03              # seconds: "same onset" for ghost/duplicate checks

MAJOR_SCALE_PCS = {0, 2, 4, 5, 7, 9, 11}
MINOR_SCALE_PCS = {0, 2, 3, 5, 7, 8, 10}

KRUMHANSL_MAJOR = [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]
KRUMHANSL_MINOR = [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]
PITCH_NAMES = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]


def all_notes(pm):
    notes = [n for inst in pm.instruments if not inst.is_drum for n in inst.notes]
    return sorted(notes, key=lambda n: (n.start, n.pitch))


def note_dict(n):
    return {
        "pitch": pretty_midi.note_number_to_name(n.pitch),
        "start": round(n.start, 3),
        "duration": round(n.end - n.start, 3),
        "velocity": n.velocity,
    }


def find_artifacts(notes, min_dur, vel_ratio):
    med_vel = statistics.median(n.velocity for n in notes)
    return [
        n for n in notes
        if (n.end - n.start) < min_dur and n.velocity < med_vel * vel_ratio
    ]


def find_ghosts(notes, vel_ratio=0.55, pedal=None):
    """Quiet notes at a harmonic interval from a louder note with the same onset.

    With pedal regions supplied, the velocity threshold is raised during
    pedal-down (sympathetic resonance breeds false positives there) and
    lowered with the pedal up (a quiet harmonic note is more plausibly real).
    """
    med_vel = statistics.median(n.velocity for n in notes)

    def pedal_down(t):
        return pedal is not None and any(r["down"] <= t <= r["up"] for r in pedal)

    ghosts = []
    for n in notes:
        ratio = vel_ratio * (1.15 if pedal_down(n.start) else 0.8)
        if n.velocity >= med_vel * ratio:
            continue
        for m in notes:
            if m is n:
                continue
            if abs(m.start - n.start) > ONSET_TOLERANCE:
                continue
            iv = n.pitch - m.pitch
            if (iv in GHOST_INTERVALS or -iv in SUB_GHOST_INTERVALS) \
                    and m.velocity > n.velocity * 1.5:
                ghosts.append(n)
                break
    return ghosts


def key_scale_pcs(key_name):
    """Pitch classes of the named key's scale, e.g. 'D major' -> {2,4,6,7,9,11,1}."""
    tonic, mode = key_name.split()
    t = PITCH_NAMES.index(tonic)
    base = MAJOR_SCALE_PCS if mode == "major" else MINOR_SCALE_PCS
    return {(t + pc) % 12 for pc in base}


def looks_musical(n, notes, scale):
    """Music prior for short/quiet artifact candidates: keep (flag, don't delete)
    a candidate that is in-key AND not a semitone/major-7th clash against a
    louder simultaneous note. Out-of-key dissonant blips are deleted."""
    if n.pitch % 12 not in scale:
        return False
    for m in notes:
        if m is n or abs(m.start - n.start) > ONSET_TOLERANCE:
            continue
        if m.velocity > n.velocity and (abs(n.pitch - m.pitch) % 12) in (1, 11):
            return False
    return True


def find_duplicates(notes):
    """Same pitch, overlapping in time: keep the louder, drop the rest."""
    drops = []
    by_pitch = {}
    for n in notes:
        by_pitch.setdefault(n.pitch, []).append(n)
    for group in by_pitch.values():
        group.sort(key=lambda n: n.start)
        for a, b in zip(group, group[1:]):
            if b.start < a.end - 0.01 and abs(b.start - a.start) < ONSET_TOLERANCE:
                drops.append(b if b.velocity <= a.velocity else a)
    return drops


def key_estimate(notes):
    """Krumhansl-Schmuckler over a duration*velocity-weighted pitch-class histogram."""
    hist = np.zeros(12)
    for n in notes:
        hist[n.pitch % 12] += (n.end - n.start) * n.velocity
    results = []
    for profile, mode in ((KRUMHANSL_MAJOR, "major"), (KRUMHANSL_MINOR, "minor")):
        prof = np.array(profile)
        for tonic in range(12):
            rotated = np.roll(hist, -tonic)
            r = float(np.corrcoef(rotated, prof)[0, 1])
            results.append({"key": f"{PITCH_NAMES[tonic]} {mode}", "correlation": round(r, 3)})
    results.sort(key=lambda k: -k["correlation"])
    return results[:3]


def onset_envelope(notes, frame=0.05):
    end = max(n.end for n in notes)
    env = np.zeros(int(end / frame) + 2)
    for n in notes:
        env[int(n.start / frame)] += n.velocity / 127.0
    return env, frame


def meter_estimate(notes):
    """Autocorrelate the onset envelope: find the beat, then score bar groupings."""
    env, frame = onset_envelope(notes)
    env = env - env.mean()
    ac = np.correlate(env, env, "full")[len(env) - 1:]
    if ac[0] <= 0:
        return {"error": "degenerate onset envelope"}
    ac = ac / ac[0]
    lo, hi = int(0.25 / frame), int(1.5 / frame)
    if hi >= len(ac):
        return {"error": "audio too short for meter analysis"}
    beat_lag = lo + int(np.argmax(ac[lo:hi]))
    beat_period = beat_lag * frame
    scores = {}
    for group in (2, 3, 4, 6):
        lag = group * beat_lag
        scores[str(group)] = round(float(ac[lag]), 3) if lag < len(ac) else None
    return {
        "beat_period_s": round(beat_period, 3),
        "bpm_candidates": [round(60 / beat_period, 1),
                           round(30 / beat_period, 1),
                           round(120 / beat_period, 1)],
        "grouping_scores": scores,
        "note": "grouping_scores = autocorrelation at N*beat; the strongest N suggests beats per bar",
    }


def tempo_stability(notes, window=20.0):
    """Per-window beat estimate; high spread suggests rubato (barlines unreliable)."""
    end = max(n.end for n in notes)
    periods = []
    t = 0.0
    while t < end:
        chunk = [n for n in notes if t <= n.start < t + window]
        if len(chunk) >= 12:
            m = meter_estimate(chunk)
            if "beat_period_s" in m:
                periods.append(m["beat_period_s"])
        t += window
    if len(periods) < 2:
        return {"windows": periods, "verdict": "too little data"}
    cv = statistics.stdev(periods) / statistics.mean(periods)
    return {
        "window_beat_periods_s": periods,
        "coefficient_of_variation": round(cv, 3),
        "verdict": "steady" if cv < 0.08 else ("some rubato" if cv < 0.2 else "heavy rubato"),
    }


def pedal_regions(pm, shift=0.0):
    """CC64 down/up regions, optionally shifted by the clean-pass time offset."""
    ccs = sorted(
        (cc for inst in pm.instruments for cc in inst.control_changes if cc.number == 64),
        key=lambda c: c.time,
    )
    regions, down = [], None
    for cc in ccs:
        if cc.value >= 64 and down is None:
            down = cc.time
        elif cc.value < 64 and down is not None:
            regions.append({"down": round(down - shift, 3), "up": round(cc.time - shift, 3)})
            down = None
    if down is not None:
        regions.append({"down": round(down - shift, 3), "up": round(pm.get_end_time() - shift, 3)})
    return regions


def clusters_and_runs(notes):
    clusters = []
    for i, n in enumerate(notes):
        co = [m for m in notes if m.start <= n.start < m.end or abs(m.start - n.start) < ONSET_TOLERANCE]
        if len(co) > 6:
            clusters.append({"time": round(n.start, 2), "simultaneous_notes": len(co)})
    # dedupe nearby cluster reports
    pruned = []
    for c in clusters:
        if not pruned or c["time"] - pruned[-1]["time"] > 1.0:
            pruned.append(c)
    runs, current = [], [notes[0]]
    for a, b in zip(notes, notes[1:]):
        if 0 < b.start - a.start < 0.12:
            current.append(b)
        else:
            if len(current) >= 6:
                runs.append({"start": round(current[0].start, 2), "notes": len(current)})
            current = [b]
    if len(current) >= 6:
        runs.append({"start": round(current[0].start, 2), "notes": len(current)})
    return pruned[:20], runs[:20]


def hand_split(notes):
    pitches = sorted(n.pitch for n in notes)
    hist = {}
    for p in pitches:
        hist[p] = hist.get(p, 0) + 1
    # largest pitch gap in the middle register is the natural split candidate
    mid = [p for p in range(48, 72)]
    best_gap, split = 0, 60
    present = sorted(set(pitches))
    for a, b in zip(present, present[1:]):
        if a in range(48, 72) and (b - a) > best_gap:
            best_gap, split = b - a, (a + b) // 2
    return {"suggested_split": pretty_midi.note_number_to_name(split), "gap_semitones": best_gap}


def cmd_analyze(args):
    pm = pretty_midi.PrettyMIDI(args.input)
    notes = all_notes(pm)
    if not notes:
        print(json.dumps({"error": "no notes found"}))
        return 1
    artifacts = find_artifacts(notes, args.min_dur, args.vel_ratio)
    ghosts = find_ghosts(notes, pedal=pedal_regions(pm))
    dups = find_duplicates(notes)
    clusters, runs = clusters_and_runs(notes)
    vels = [n.velocity for n in notes]
    durs = [n.end - n.start for n in notes]
    report = {
        "file": args.input,
        "notes": len(notes),
        "duration_s": round(pm.get_end_time(), 1),
        "first_onset_s": round(notes[0].start, 3),
        "velocity": {"min": min(vels), "median": statistics.median(vels), "max": max(vels)},
        "note_duration_s": {"min": round(min(durs), 3),
                            "median": round(statistics.median(durs), 3),
                            "max": round(max(durs), 3)},
        "artifact_candidates": {"count": len(artifacts), "sample": [note_dict(n) for n in artifacts[:25]]},
        "ghost_candidates": {"count": len(ghosts), "sample": [note_dict(n) for n in ghosts[:25]]},
        "duplicate_candidates": {"count": len(dups), "sample": [note_dict(n) for n in dups[:25]]},
        "key_estimates": key_estimate(notes),
        "meter": meter_estimate(notes),
        "tempo_pretty_midi_bpm": round(float(pm.estimate_tempo()), 1),
        "tempo_stability": tempo_stability(notes),
        "pedal_cc64_regions": len(pedal_regions(pm)),
        "hand_split": hand_split(notes),
        "dense_clusters": clusters,
        "fast_runs": runs,
        "dynamics_preview": {
            "profile": [{"t": round(t, 1), "vel": round(v, 1), "level": dynamic_level(v)}
                        for t, v in velocity_profile(pm)[::5]],
            "hairpins": [{"start": round(a, 1), "end": round(b, 1), "kind": k}
                         for a, b, k in find_hairpins(velocity_profile(pm))],
        },
    }
    print(json.dumps(report, indent=2))
    return 0


def cmd_clean(args):
    pm = pretty_midi.PrettyMIDI(args.input)
    notes = all_notes(pm)
    if not notes:
        print(json.dumps({"error": "no notes found"}))
        return 1

    drop = set()
    scale = key_scale_pcs(key_estimate(notes)[0]["key"])
    candidates = find_artifacts(notes, args.min_dur, args.vel_ratio)
    artifacts = [n for n in candidates if not looks_musical(n, notes, scale)]
    kept_suspects = [n for n in candidates if looks_musical(n, notes, scale)]
    drop.update(id(n) for n in artifacts)
    pedal = pedal_regions(pm)
    ghosts = find_ghosts(notes, pedal=pedal) if not args.keep_ghosts else []
    drop.update(id(n) for n in ghosts)
    dups = find_duplicates(notes)
    drop.update(id(n) for n in dups)
    kept = [n for n in notes if id(n) not in drop]

    shift = kept[0].start if args.trim else 0.0
    tempo = args.tempo or round(float(pm.estimate_tempo()), 1)

    out = pretty_midi.PrettyMIDI(initial_tempo=tempo)
    if args.time_sig:
        num, den = (int(x) for x in args.time_sig.split("/"))
        out.time_signature_changes.append(pretty_midi.TimeSignature(num, den, 0))
    if args.key:
        out.key_signature_changes.append(
            pretty_midi.KeySignature(pretty_midi.key_name_to_key_number(args.key), 0))
    tempo_map_events = None
    if args.tempo_map:
        # Beat-aligned tempo map: ticks follow the tracked beats, so DAW bar
        # grids track the performance through rubato and tempo changes. The
        # warp's bar-1 rebase makes the trim implicit; original times go in.
        beats = load_beat_times(args.tempo_map)
        ccs = [(cc.value, cc.time) for src in pm.instruments
               for cc in src.control_changes if cc.number == 64]
        tempo_map_events = write_tempo_mapped_midi(
            args.output, kept, ccs, beats, args.time_sig, args.key)
    else:
        inst = pretty_midi.Instrument(program=0, name="Piano")
        for n in kept:
            inst.notes.append(pretty_midi.Note(
                velocity=n.velocity, pitch=n.pitch,
                start=max(0.0, n.start - shift), end=max(0.0, n.end - shift)))
        for src in pm.instruments:
            for cc in src.control_changes:
                if cc.number == 64 and cc.time - shift >= 0:
                    inst.control_changes.append(
                        pretty_midi.ControlChange(64, cc.value, cc.time - shift))
        out.instruments.append(inst)
        out.write(args.output)

    summary = {
        "input": args.input,
        "output": args.output,
        "kept_notes": len(kept),
        "removed_artifacts": {"count": len(artifacts), "sample": [note_dict(n) for n in artifacts[:50]]},
        "kept_suspects": {"count": len(kept_suspects),
                          "note": "short+quiet but in-key and consonant — kept; verify by ear",
                          "sample": [note_dict(n) for n in kept_suspects[:50]]},
        "removed_ghosts": {"count": len(ghosts), "sample": [note_dict(n) for n in ghosts[:50]]},
        "removed_duplicates": {"count": len(dups), "sample": [note_dict(n) for n in dups[:50]]},
        "trim_shift_s": round(shift, 3),
        "tempo_bpm": tempo,
        "tempo_map": (f"{tempo_map_events} tempo events from {args.tempo_map} "
                      "(bar grid follows the performance)") if tempo_map_events else None,
        "time_sig": args.time_sig,
        "key": args.key,
        "pedal_regions": pedal_regions(pm, shift),
    }
    text = json.dumps(summary, indent=2)
    if args.report:
        with open(args.report, "w") as f:
            f.write(text)
    print(text)
    return 0


# Single-symbol note values (incl. dotted), longest first, for duration snapping.
EXPRESSIBLE_QL = [6, 4, 3, 2, 1.5, 1, 0.75, 0.5, 0.375, 0.25, 0.1875, 0.125, 0.0625]
# Tuplet durations music21 can express as single symbols (triplet 4th/8th/16th/32nd).
TUPLET_QL = ["2/3", "1/3", "1/6", "1/12"]


def snap_dur_down_ql(ql):
    """Largest single-symbol binary duration <= ql (clip repair stays binary —
    a stray tuplet value outside a ternary context corrupts tuplet groups)."""
    from fractions import Fraction
    for c in sorted((Fraction(str(x)) for x in EXPRESSIBLE_QL), reverse=True):
        if c <= ql:
            return c
    return Fraction(1, 16)


def build_measured_part(items, marks, ts_str, part_id):
    """Re-bar possibly-overlapping (offset, Note/Chord) items into a PartStaff.

    Overlaps (sustained melody/bass notes ringing over other onsets) are split
    greedily into at most two non-overlapping layers, each layer is sliced at
    barlines and measured, and the layers are zipped into per-measure music21
    Voices — naive makeMeasures on overlapping flat content lays the layers
    out SEQUENTIALLY (3x-overfull measures, mscore exit 40). A third
    concurrent layer clips the earlier note instead. `marks` are zero-duration
    elements (key/time signatures, text directions) for layer 1.
    """
    from fractions import Fraction
    from music21 import meter as m21meter, stream as m21stream
    from music21.stream import Measure, Voice

    layers, ends = [[], []], [None, None]
    for off, el in sorted(items, key=lambda x: x[0]):
        dur = el.duration.quarterLength
        idx = next((i for i in range(2) if ends[i] is None or ends[i] <= off), None)
        if idx is None:
            idx = 0 if ends[0] <= ends[1] else 1
            prev_off, prev = layers[idx][-1]
            clipped = snap_dur_down_ql(max(off - prev_off, Fraction(1, 16)))
            prev.duration.quarterLength = clipped
        layers[idx].append((off, el))
        ends[idx] = off + el.duration.quarterLength

    ts = m21meter.TimeSignature(ts_str)
    bar_ql = ts.barDuration.quarterLength
    top = max((e for e in ends if e is not None), default=0)
    bar_offsets = [i * bar_ql for i in range(1, int(float(top) // float(bar_ql)) + 1)]

    rebarred = []
    for li, layer in enumerate(layers):
        if not layer:
            continue
        s = m21stream.Stream()
        s.insert(0, m21meter.TimeSignature(ts_str))
        if li == 0:
            for off, mk in marks:
                s.insert(off, mk)
        for off, el in layer:
            s.insert(off, el)
        s.sliceAtOffsets(bar_offsets, addTies=True, inPlace=True)
        measured = s.makeMeasures()
        # Every gap gets explicit, VISIBLE rests. Left unfilled, music21's
        # exporter pads gaps with print-object="no" rests, which MuseScore
        # shows as grayed-out ghost rests — the score must carry its rests
        # as real engraved symbols, not exporter artifacts. Gaps are split
        # into simple values aligned to their own size (whole bar, half on
        # beats 1/3, quarter on beats, ...), never dotted-rest oddities.
        from music21 import note as m21note

        def gap_rests(off, rem):
            while rem > 0:
                for p in (Fraction(4), Fraction(2), Fraction(1),
                          Fraction(1, 2), Fraction(1, 4), Fraction(1, 8)):
                    if rem >= p and off % p == 0:
                        yield off, p
                        off, rem = off + p, rem - p
                        break
                else:
                    yield off, rem  # finer than the grid; emit as-is
                    return

        for meas in measured.getElementsByClass(Measure):
            bar_len = Fraction(meas.barDuration.quarterLength)
            cur = Fraction(0)
            spans = []
            for el in sorted(meas.notesAndRests, key=lambda e: e.offset):
                el_off = Fraction(el.offset)
                if el_off > cur:
                    spans.append((cur, el_off - cur))
                cur = max(cur, el_off + Fraction(el.duration.quarterLength))
            if cur < bar_len:
                spans.append((cur, bar_len - cur))
            for span_off, span_len in spans:
                for r_off, r_len in gap_rests(span_off, span_len):
                    meas.insert(float(r_off), m21note.Rest(quarterLength=float(r_len)))
        rebarred.append(measured)

    ps = m21stream.PartStaff(id=part_id)
    if len(rebarred) == 1:
        for el in rebarred[0]:
            ps.insert(el.offset, el)
        return ps
    second = {m.measureNumber: m for m in rebarred[1].getElementsByClass(Measure)}
    for m1 in rebarred[0]:
        if isinstance(m1, Measure):
            m2 = second.get(m1.measureNumber)
            if m2 is not None and m2.notes:
                v1, v2 = Voice(id="1"), Voice(id="2")
                for el in list(m1.notesAndRests):
                    off_in_m = el.getOffsetBySite(m1)  # before remove: offset
                    m1.remove(el)                      # falls back to another site
                    v1.insert(off_in_m, el)
                for el in list(m2.notesAndRests):
                    off_in_m = el.getOffsetBySite(m2)
                    m2.remove(el)
                    v2.insert(off_in_m, el)
                m1.insert(0, v1)
                m1.insert(0, v2)
        ps.insert(m1.offset, m1)
    return ps


def normalize_accidentals(score):
    """Strip stale natural-accidental objects, then recompute accidental display
    against the key context. makeMeasures attaches Accidental('natural') objects
    along the way; left in place, the export prints an accidental on literally
    every note (sharps on in-key notes, naturals on every white key)."""
    for n in score.recurse().notes:
        for p in (n.pitches if hasattr(n, "pitches") else [n.pitch]):
            if p.accidental is not None and p.accidental.alter == 0:
                p.accidental = None
    for part in score.parts:
        part.makeAccidentals(inPlace=True, overrideStatus=True,
                             cautionaryNotImmediateRepeat=False)


def lint_score(path):
    """Structural invariants for generated MusicXML — every measure and every
    voice must sum exactly to the bar duration (notes + rests balanced), and
    accidentals must not be printed wholesale. Returned with every score so
    regressions surface immediately instead of in the user's MuseScore."""
    from music21 import converter
    s = converter.parse(path)
    bad = []
    n_notes = n_acc = 0
    for part in s.parts:
        measures = list(part.getElementsByClass("Measure"))
        for m in measures[:-1] if len(measures) > 1 else measures:
            bar = m.barDuration.quarterLength
            for c in (list(m.voices) or [m]):
                length = max((e.offset + e.duration.quarterLength
                              for e in c.notesAndRests), default=bar)
                if abs(float(length) - float(bar)) > 1e-3:
                    bad.append({"part": str(part.id)[-8:], "measure": m.number,
                                "voice": getattr(c, "id", None),
                                "content_ql": float(length), "bar_ql": float(bar)})
    for n in s.recurse().notes:
        for p in (n.pitches if hasattr(n, "pitches") else [n.pitch]):
            n_notes += 1
            if p.accidental is not None and p.accidental.displayStatus:
                n_acc += 1
    return {"unbalanced_measures": len(bad), "examples": bad[:10],
            "printed_accidental_ratio": round(n_acc / n_notes, 2) if n_notes else 0,
            "verdict": ("ok" if not bad and (not n_notes or n_acc / n_notes < 0.4)
                        else "PROBLEM — inspect before delivering")}


def assign_hands(notes):
    """Greedy time-ordered hand assignment. For each onset slot, choose the
    split of its (pitch-sorted) notes that minimizes: within-hand span beyond
    a 9th, movement from each hand's previous position, and out-of-register
    placement. Handles crossings and sweeping arpeggios that a static pitch
    threshold cannot. Returns {id(note): "treble"|"bass"}."""
    slots, cur = [], [notes[0]]
    for a, b in zip(notes, notes[1:]):
        if b.start - a.start <= ONSET_TOLERANCE:
            cur.append(b)
        else:
            slots.append(cur)
            cur = [b]
    slots.append(cur)

    out, left, right = {}, None, None
    for slot in slots:
        ps = sorted(slot, key=lambda n: n.pitch)
        best_cost, best_k = None, len(ps)
        for k in range(len(ps) + 1):
            lo, hi = ps[:k], ps[k:]
            cost = 0.0
            for grp in (lo, hi):
                if grp:
                    span = grp[-1].pitch - grp[0].pitch
                    if span > 14:  # beyond a 9th: unplayable as one hand
                        cost += (span - 14) * 2.0
            mlo = lo[len(lo) // 2].pitch if lo else None
            mhi = hi[len(hi) // 2].pitch if hi else None
            if mlo is not None and left is not None:
                cost += abs(mlo - left) * 0.25
            if mhi is not None and right is not None:
                cost += abs(mhi - right) * 0.25
            if mlo is not None and mlo > 67:  # LH far above G4
                cost += (mlo - 67) * 0.6
            if mhi is not None and mhi < 52:  # RH far below E3
                cost += (52 - mhi) * 0.6
            if best_cost is None or cost < best_cost:
                best_cost, best_k = cost, k
        lo, hi = ps[:best_k], ps[best_k:]
        for n in lo:
            out[id(n)] = "bass"
        for n in hi:
            out[id(n)] = "treble"
        if lo:
            left = lo[len(lo) // 2].pitch
        if hi:
            right = hi[len(hi) // 2].pitch
    return out


def load_beat_times(path, shift=0.0):
    """Beat times (seconds) from a `beats` subcommand JSON, shifted into the
    timeline of a trimmed MIDI (pass the clean pass's trim_shift_s)."""
    with open(path) as f:
        data = json.load(f)
    return [b - shift for b in data["beats"]]


def beat_warp(beats):
    """Piecewise-linear map seconds -> beat position (1 beat = 1 quarterLength).
    Extrapolates beyond the tracked range at the median beat period."""
    import bisect
    if not beats or len(beats) < 2:
        return None
    med = statistics.median(b - a for a, b in zip(beats, beats[1:]))

    def f(t):
        if t <= beats[0]:
            return (t - beats[0]) / med
        if t >= beats[-1]:
            return len(beats) - 1 + (t - beats[-1]) / med
        i = bisect.bisect_right(beats, t) - 1
        return i + (t - beats[i]) / (beats[i + 1] - beats[i])

    return f


def tempo_plateaus(periods, min_beats=16, threshold=0.12):
    """Segment beat periods into stable tempo plateaus: [(start_beat, period_s)].
    A new plateau needs min_beats consecutive (smoothed) periods all deviating
    >threshold from the current level — short rubato swings don't count."""
    if not periods:
        return []
    smooth = [statistics.median(periods[max(0, k - 3):k + 4]) for k in range(len(periods))]
    plats = [(0, statistics.median(smooth[:min_beats]) if len(smooth) >= min_beats
              else smooth[0])]
    k = min_beats
    while k + min_beats <= len(smooth):
        cur = plats[-1][1]
        window = smooth[k:k + min_beats]
        if all(abs(s - cur) / cur > threshold for s in window):
            plats.append((k, statistics.median(window)))
            k += min_beats
        else:
            k += 1
    return plats


def write_tempo_mapped_midi(path, notes, pedal_ccs, beats, time_sig, key_name):
    """Write a MIDI whose tick grid follows the tracked beats: one tick-aligned
    tempo event per (changed) beat period, notes at their beat positions. Note
    SECONDS are preserved (the warp defines both ticks and tempo), but DAW bar
    grids now follow the performance through rubato and tempo changes."""
    import math

    import mido
    TPQ = 480
    warp = beat_warp(beats)
    base = math.floor(warp(notes[0].start)) if notes else 0

    def tick(t):
        return max(0, round((warp(t) - base) * TPQ))

    events = []  # (tick, priority, mido message with time=0)
    if time_sig:
        num, den = (int(x) for x in time_sig.split("/"))
        events.append((0, 0, mido.MetaMessage("time_signature",
                                              numerator=num, denominator=den, time=0)))
    if key_name:
        parts = key_name.split()
        mido_key = parts[0] + ("m" if len(parts) > 1 and parts[1].lower() == "minor" else "")
        events.append((0, 0, mido.MetaMessage("key_signature", key=mido_key, time=0)))
    last_us = None
    for k, (a, b) in enumerate(zip(beats, beats[1:])):
        if k - base < 0:
            continue
        us = int((b - a) * 1e6)
        if last_us is None or abs(us - last_us) > last_us * 0.01:
            events.append(((k - base) * TPQ, 0, mido.MetaMessage("set_tempo", tempo=us, time=0)))
            last_us = us
    for n in notes:
        events.append((tick(n.start), 1, mido.Message("note_on", note=n.pitch,
                                                      velocity=n.velocity, time=0)))
        events.append((max(tick(n.end), tick(n.start) + 1), 1,
                       mido.Message("note_off", note=n.pitch, velocity=0, time=0)))
    for value, t in pedal_ccs:
        if warp(t) - base < -0.5:
            continue
        events.append((tick(t), 1, mido.Message("control_change", control=64,
                                                value=value, time=0)))

    events.sort(key=lambda e: (e[0], e[1]))
    track = mido.MidiTrack()
    prev = 0
    for tk, _, msg in events:
        msg.time = tk - prev
        prev = tk
        track.append(msg)
    mid = mido.MidiFile(ticks_per_beat=TPQ)
    mid.tracks.append(track)
    mid.save(path)
    return sum(1 for _, p, m in events if m.type == "set_tempo")


def refine_beats(beats, notes, window=0.05):
    """Snap tracked beat times to the nearest MIDI onset within `window` s.
    Audio beat tracking has frame-level jitter (~23 ms); the MIDI onsets are
    precise, and the pianist's onsets ARE the beat where they coincide."""
    import bisect
    onsets = sorted({round(n.start, 4) for n in notes})
    refined = []
    for b in beats:
        i = bisect.bisect_left(onsets, b)
        best, bd = b, window
        for j in (i - 1, i):
            if 0 <= j < len(onsets) and abs(onsets[j] - b) < bd:
                best, bd = onsets[j], abs(onsets[j] - b)
        refined.append(best)
    out = [refined[0]]
    for r in refined[1:]:  # keep strictly increasing
        out.append(max(r, out[-1] + 1e-3))
    return out


def infer_bar_phase(events, beats_per_bar):
    """Which beat is the downbeat? Score each candidate phase with the classic
    meter-induction cues (Lerdahl & Jackendoff): bass-register onsets on strong
    beats, harmonic-rhythm (pitch-class set) changes on downbeats, and agogic
    accents (longer notes on strong beats). events = [(beat_pos, pitch,
    velocity, dur_beats)]. Returns (phase, confidence 0..1, cue breakdown)."""
    B = beats_per_bar
    if B < 2 or not events:
        return 0, 0.0, {}
    n_beats = int(max(e[0] for e in events)) + 1
    pcs_per_beat = [set() for _ in range(n_beats + 1)]
    bass_w = [0.0] * B
    agogic = [0.0] * B
    for pos, pitch, vel, dur in events:
        k = int(round(pos))
        if abs(pos - k) > 0.15 or k >= n_beats:
            continue  # only on-beat onsets vote
        pcs_per_beat[k].add(pitch % 12)
        if pitch < 55:  # below ~G3: bass register
            bass_w[k % B] += vel / 127.0
        agogic[k % B] += min(dur, float(B))
    harm = [0.0] * B
    for k in range(1, n_beats):
        a, b = pcs_per_beat[k - 1], pcs_per_beat[k]
        if not a or not b:
            continue
        change = 1.0 - len(a & b) / len(a | b)
        harm[k % B] += change

    def z(xs):
        m = sum(xs) / len(xs)
        sd = (sum((x - m) ** 2 for x in xs) / len(xs)) ** 0.5
        return [0.0] * len(xs) if sd == 0 else [(x - m) / sd for x in xs]

    totals = [a + b + c for a, b, c in zip(z(bass_w), z(harm), z(agogic))]
    ranked = sorted(range(B), key=lambda p: -totals[p])
    best, second = ranked[0], ranked[1]
    spread = max(totals) - min(totals)
    conf = (totals[best] - totals[second]) / spread if spread > 0 else 0.0
    breakdown = {"bass": [round(x, 2) for x in bass_w],
                 "harmonic_change": [round(x, 2) for x in harm],
                 "agogic": [round(x, 2) for x in agogic]}
    return best, round(conf, 2), breakdown


def cmd_quantize(args):
    """MIDI -> MusicXML quantized with music21 — never MuseScore's MIDI import
    (it auto-detects its own tempo, ignores the meta events, and can lock onto
    a sub-pulse, e.g. 4/3 of the true BPM on a 3-3-2 groove).

    Two grids: a fixed BPM grid (--bpm), or a beat-tracked warp (--beats, from
    the `beats` subcommand) where the grid follows the performance through
    rubato and drift. Onsets snap to the grid, same-slot notes merge into
    chords, durations are capped at the next onset in the same staff (pedal
    marks carry sustain). Downbeat phase is inferred from bass/harmony/agogic
    cues so bar 1 beat 1 lands on a real downbeat (leading rests model a pickup).
    """
    from fractions import Fraction
    from music21 import (chord as m21chord, duration as m21dur, expressions as m21expr,
                         key as m21key, meter as m21meter, note as m21note,
                         stream as m21stream)

    pm = pretty_midi.PrettyMIDI(args.input)
    notes = all_notes(pm)
    if not notes:
        print(json.dumps({"error": "no notes found"}))
        return 1
    if not args.bpm and not args.beats:
        print(json.dumps({"error": "need --bpm or --beats"}))
        return 1

    grid = Fraction(4, args.grid)  # e.g. --grid 32 -> 1/8 quarterLength
    expressible_binary = sorted((Fraction(str(x)) for x in EXPRESSIBLE_QL), reverse=True)
    # Inside a ternary beat only tuplet-family values are allowed — a stray
    # binary duration there produces incomplete tuplet groups that MuseScore
    # rejects as corrupt (exit 40).
    expressible_ternary = sorted((Fraction(x) for x in ["1"] + TUPLET_QL), reverse=True)

    summary = {"input": args.input, "output": args.output,
               "grid": f"1/{args.grid}", "staves": {}}

    # Hand assignment: cost-based (span/movement/register, handles crossings)
    # unless a fixed split pitch was requested. Falls back to the static split
    # if the cost model disagrees with it implausibly often.
    static_split = pretty_midi.note_name_to_number(
        hand_split(notes)["suggested_split"] if args.split == "auto" else args.split)
    if args.split == "auto":
        hands = assign_hands(notes)
        moved = sum(1 for n in notes
                    if hands[id(n)] != ("treble" if n.pitch >= static_split else "bass"))
        if moved > 0.4 * len(notes):
            hands = {id(n): ("treble" if n.pitch >= static_split else "bass")
                     for n in notes}
            summary["hand_split"] = {"mode": "static (cost model disagreed on "
                                             f"{moved} notes — suspicious, kept it simple)"}
        else:
            summary["hand_split"] = {"mode": "cost-based",
                                     "differs_from_static_split": moved}
    else:
        hands = {id(n): ("treble" if n.pitch >= static_split else "bass")
                 for n in notes}
        summary["hand_split"] = {"mode": f"static at {args.split}"}

    warp, beat_times, warp_base = None, None, 0
    if args.beats:
        beat_times = refine_beats(load_beat_times(args.beats, args.beats_shift), notes)
        warp = beat_warp(beat_times)
        periods = [b - a for a, b in zip(beat_times, beat_times[1:])]
        med_period = statistics.median(periods)
        # Rebase so the first note lands in bar 1: the tracker's grid starts
        # wherever the audio starts, which may be many beats before the
        # (trimmed) MIDI's t=0.
        import math
        warp_base = math.floor(warp(notes[0].start))
        summary["mode"] = "beat-tracked"
        summary["tempo_median_bpm"] = round(60 / med_period, 1)
        bpm = Fraction(str(round(60 / med_period, 3)))
    else:
        bpm = Fraction(str(args.bpm))
        summary["mode"] = "fixed-grid"
        summary["bpm"] = float(bpm)

    def to_ql(t):
        if warp:
            return Fraction(warp(t) - warp_base).limit_denominator(100000)
        return Fraction(t).limit_denominator(100000) * bpm / 60

    def dur_down(ql, ternary=False):
        for c in (expressible_ternary if ternary else expressible_binary):
            if c <= ql:
                return c
        return grid

    # Cluster near-simultaneous onsets per hand first: rolled/arpeggiated chord
    # attacks spread 10-80 ms, and snapping each note separately engraves a
    # chain of 32nds instead of one chord.
    hand_clusters = {}
    for name in ("treble", "bass"):
        hand = sorted((n for n in notes if hands[id(n)] == name),
                      key=lambda x: x.start)
        clusters = []
        for n in hand:
            if clusters and n.start - clusters[-1][-1].start <= 0.06:
                clusters[-1].append(n)
            else:
                clusters.append([n])
        hand_clusters[name] = clusters

    def cluster_onset(cl):
        return cl[len(cl) // 2].start

    # Per-beat subdivision selection: each beat picks the division (binary or
    # ternary) that best explains its onsets, with a complexity prior and a
    # bonus for the piece's prevailing division (Temperley-style). Genuine
    # triplets become real tuplets instead of being forced onto a binary grid.
    fracs_by_beat = {}
    for cl in (c for cs in hand_clusters.values() for c in cs):
        q = float(to_ql(cluster_onset(cl)))
        b = max(0, int(q))
        fracs_by_beat.setdefault(b, []).append(max(0.0, q - b))

    # Swing: off-eighths clustering at 2/3 of the beat instead of 1/2 are
    # notated straight + a "Swing" text, per engraving convention.
    def near(f, x, tol=0.07):
        return abs(f - x) <= tol
    straight8 = sum(1 for fs in fracs_by_beat.values() for f in fs if near(f, 0.5))
    swung8 = sum(1 for fs in fracs_by_beat.values() for f in fs if near(f, 2 / 3))
    swing = swung8 >= 24 and swung8 > 2 * straight8
    if swing:
        summary["swing"] = (f"{swung8} off-eighths near 2/3 vs {straight8} near 1/2 — "
                            "notated straight with a Swing direction")

    DIV_COMPLEXITY = {1: 0.0, 2: 0.0, 4: 0.05, 3: 0.12, 6: 0.2, 8: 0.22}
    max_div = max(d for d in DIV_COMPLEXITY if d <= args.grid // 4) if args.grid >= 8 else 8

    def deswing(fs):
        return [0.5 if swing and 0.55 <= f <= 0.78 else f for f in fs]

    def best_div(fs, bonus_d=None):
        best, best_score = 8, None
        for d, comp in DIV_COMPLEXITY.items():
            if d > max_div:
                continue
            errs = [min(abs(f - k / d) for k in range(d + 1)) for f in fs]
            err = sum(errs) / len(fs)
            # An onset stranded more than 1/8 beat from every slot is not
            # jitter — the division fails to explain it. Mean error alone
            # dilutes one genuine 16th among on-slot onsets, so the beat
            # keeps division 2 and the 16th collapses into its neighbor's
            # chord (vanished onsets, block chords where the ear hears two).
            unexplained = 0.25 if max(errs) > 0.125 else 0.0
            score = err + comp + unexplained - (0.04 if d == bonus_d else 0.0)
            if best_score is None or score < best_score:
                best_score, best = score, d
        return best

    from collections import Counter
    first_pass = {b: best_div(deswing(fs)) for b, fs in fracs_by_beat.items()}
    mode_div = Counter(first_pass.values()).most_common(1)[0][0]
    div_by_beat = {b: best_div(deswing(fs), bonus_d=mode_div)
                   for b, fs in fracs_by_beat.items()}
    summary["subdivisions"] = dict(Counter(div_by_beat.values()))

    def snap(ql):
        q = float(ql)
        b = max(0, int(q))
        f = max(0.0, q - b)
        if swing and 0.55 <= f <= 0.78:
            f = 0.5
        d = div_by_beat.get(b, max_div)
        k = round(f * d)
        return Fraction(b) + Fraction(k, d)

    # Downbeat phase from meter-induction cues; bar 1 beat 1 should be a downbeat.
    ts_parts = (args.time_sig or "4/4").split("/")
    beats_per_bar = int(ts_parts[0]) * 4 // int(ts_parts[1]) \
        if (int(ts_parts[0]) * 4) % int(ts_parts[1]) == 0 else 0
    pad = Fraction(0)
    if beats_per_bar >= 2:
        events = [(float(to_ql(n.start)), n.pitch, n.velocity,
                   float(to_ql(n.end) - to_ql(n.start))) for n in notes]
        phase, conf, cues = infer_bar_phase(events, beats_per_bar)
        summary["bar_phase"] = {"downbeat_at_beat": phase, "confidence": conf,
                                "cues": cues}
        if args.bar_phase is not None:
            phase, conf = args.bar_phase % beats_per_bar, 1.0
            summary["bar_phase"]["override"] = phase
        if phase != 0 and conf >= 0.2:
            pad = Fraction(beats_per_bar - phase)
            summary["bar_phase"]["pickup"] = (
                f"first {phase} beat(s) are a pickup — bar 1 opens with "
                f"{beats_per_bar - phase} beat(s) of rest; verify by ear")
        elif phase != 0:
            summary["bar_phase"]["pickup"] = (
                "weak downbeat evidence — kept first onset on beat 1; verify by ear")

    # Tempo structure: sustained plateaus become real metronome-mark changes
    # (a piece may have several tempi); short swings within a plateau become
    # rit. / accel. / a tempo text.
    tempo_texts, tempo_mark_events = [], []
    if warp and beat_times:
        plats = tempo_plateaus(periods)
        if len(plats) > 4:
            # Wall-to-wall "plateaus" = rubato, not structure: one median mark.
            summary["tempo_plateaus"] = (f"{len(plats)} candidate tempo levels — "
                                         "rubato, marked the median only")
            plats = [(0, statistics.median(periods))]
        elif len(plats) == 1:
            # Single tempo: mark the whole-piece median, not the opening level
            # (a slow intro would otherwise bias the printed tempo).
            plats = [(0, statistics.median(periods))]

        def level_at(k):
            lv = plats[0][1]
            for start, p in plats:
                if k >= start:
                    lv = p
            return lv

        last_bpm = None
        for start, p in plats:
            bpm_v = round(60 / p)
            if bpm_v != last_bpm:
                tempo_mark_events.append((max(0, start - warp_base + int(pad)), bpm_v))
                last_bpm = bpm_v
        if len(tempo_mark_events) > 1:
            summary["tempo_plateaus"] = [{"beat": b, "bpm": v} for b, v in tempo_mark_events]
        state = None
        for k in range(len(periods) - 3):
            beat_off = k - warp_base + int(pad)
            if beat_off < 0:
                continue  # before the score starts
            window = statistics.mean(periods[k:k + 4])
            med = level_at(k)
            trend = ("rit." if window > med * 1.07
                     else "accel." if window < med * 0.93 else None)
            if trend != state and (trend or state):
                tempo_texts.append((beat_off, trend if trend else "a tempo"))
                state = trend
        if len(tempo_texts) > 12:
            summary["tempo_marks"] = (f"{len(tempo_texts)} tempo swings detected — too "
                                      "many to mark; treat the piece as rubato throughout")
            tempo_texts = []
        elif tempo_texts:
            summary["tempo_marks"] = [{"beat": b, "mark": m} for b, m in tempo_texts]
    else:
        tempo_mark_events = [(0, round(float(bpm)))]

    ts_str = args.time_sig or "4/4"
    # A mark inserted past a staff's last note gets dropped by makeMeasures —
    # host each tempo mark/text in a staff that still has content there.
    treble_last = max((float(to_ql(n.start)) for n in notes
                       if hands[id(n)] == "treble"), default=0.0) + float(pad)
    score = m21stream.Score()
    for name in ("treble", "bass"):
        slots = {}
        for cl in hand_clusters[name]:
            slots.setdefault(snap(to_ql(cluster_onset(cl))), []).extend(cl)
        onsets = sorted(slots)
        marks = []
        if args.key:
            tonic, mode = args.key.split()[0], (args.key.split() + ["major"])[1]
            marks.append((0, m21key.KeySignature(m21key.Key(tonic, mode).sharps)))
        if name == "treble" and swing:
            sw = m21expr.TextExpression("Swing")
            sw.style.fontStyle = "bold"
            marks.append((0, sw))
        from music21 import tempo as m21tempo
        for beat_k, bpm_v in tempo_mark_events:
            if (name == "treble") == (beat_k <= treble_last):
                marks.append((beat_k, m21tempo.MetronomeMark(number=bpm_v)))
        for beat_k, label in tempo_texts:
            if (name == "treble") == (beat_k <= treble_last):
                te = m21expr.TextExpression(label)
                te.style.fontStyle = "italic"
                marks.append((beat_k, te))
        items, capped, sustained, filled, arpeggiated = [], 0, 0, 0, 0
        for i, off in enumerate(onsets):
            group = slots[off]
            raw_dur = max(to_ql(n.end) - off for n in group)
            cap = onsets[i + 1] - off if i + 1 < len(onsets) else raw_dur
            pitches = sorted({n.pitch for n in group})
            dur = min(raw_dur, cap)
            # Sustain exception: a lone melody/bass note that clearly rings on
            # (>=1.5x the gap) over later onsets in other registers keeps its
            # length — it becomes voice 2 of the staff at re-barring. The pedal
            # marks carry whatever sustain this still clips.
            if (len(pitches) == 1 and raw_dur >= cap * Fraction(3, 2)
                    and not any(abs(p - pitches[0]) < 3
                                for j in range(i + 1, len(onsets))
                                if onsets[j] < off + raw_dur
                                for p in {m.pitch for m in slots[onsets[j]]})):
                dur = raw_dur
                sustained += 1
            elif raw_dur > cap:
                capped += 1
            elif not args.no_legato_fill:
                # Legato assumption (default): every note fills the gap to the
                # next same-hand onset, however early the key was released —
                # pedaled playing releases keys early while the pedal carries
                # the sustain, and flooring performed lengths leaves 32nd-rest
                # confetti. --no-legato-fill keeps performed lengths for
                # articulation-faithful engraving (staccato etc. by ear).
                filled += 1
                dur = cap
            # Keep durations metrically consistent with their beat's division:
            # ternary-beat notes stay inside the beat (tuplet values only);
            # binary durations may not END inside a ternary beat.
            b_on = int(off)
            ternary = div_by_beat.get(b_on, max_div) in (3, 6)
            if ternary:
                dur = min(dur, Fraction(b_on + 1) - off)
            else:
                end = off + dur
                eb = int(end)
                if end > eb and div_by_beat.get(eb) in (3, 6) and Fraction(eb) > off:
                    dur = Fraction(eb) - off
            el = (m21note.Note(pitches[0]) if len(pitches) == 1
                  else m21chord.Chord(pitches))
            el.duration = m21dur.Duration(dur_down(max(dur, grid), ternary))
            # A "chord" whose source onsets are spread in time is a rolled
            # chord — engrave the roll (arpeggiate squiggle), don't silently
            # flatten it into a block chord.
            if len(pitches) > 1:
                spread = max(n.start for n in group) - min(n.start for n in group)
                if spread > 0.04:
                    el.expressions.append(m21expr.ArpeggioMark())
                    arpeggiated += 1
            items.append((off + pad, el))
        score.insert(0, build_measured_part(items, marks, ts_str, f"P1-{name}"))
        summary["staves"][name] = {"events": len(onsets),
                                   "durations_capped_at_next_onset": capped,
                                   "legato_filled_to_next_onset": filled,
                                   "sustained_as_second_voice": sustained,
                                   "rolled_chords_arpeggiated": arpeggiated}

    # Both staves must span the same number of measures: music21 pads a
    # shorter part with truly EMPTY trailing measures at export, which
    # MuseScore rejects as corruption ("Found: 0/1. Expected: 4/4.").
    # Pad explicitly with full-bar rests.
    from music21.stream import Measure as M21Measure
    bar_ql = Fraction(m21meter.TimeSignature(ts_str).barDuration.quarterLength)
    part_list = list(score.parts)
    counts = [len(p.getElementsByClass(M21Measure)) for p in part_list]
    for p, cnt in zip(part_list, counts):
        if cnt < max(counts):
            last = p.getElementsByClass(M21Measure)[-1]
            for k in range(cnt, max(counts)):
                meas = M21Measure(number=k + 1)
                meas.insert(0, m21note.Rest(quarterLength=float(bar_ql)))
                p.insert(float(Fraction(last.offset) + bar_ql * (k - cnt + 1)), meas)

    normalize_accidentals(score)

    if any([args.title, args.composer, args.arranger, args.performer]):
        from music21 import metadata as m21meta
        md = m21meta.Metadata()
        if args.title:
            md.title = args.title
        if args.composer:
            md.composer = args.composer
        if args.arranger:
            md.addContributor(m21meta.Contributor(role="arranger", name=args.arranger))
        if args.performer:
            md.addContributor(m21meta.Contributor(role="performer", name=args.performer))
        score.metadata = md
        summary["metadata"] = {k: v for k, v in (("title", args.title),
                                                 ("composer", args.composer),
                                                 ("arranger", args.arranger),
                                                 ("performer", args.performer)) if v}

    score.write("musicxml", fp=args.output)
    end_t = pm.get_end_time()
    summary["audio_seconds"] = round(end_t, 1)
    if warp:
        last_beat = warp(notes[-1].end)
        summary["beats_tracked"] = len(beat_times)
        summary["beats_spanned_by_notes"] = round(last_beat, 1)
    else:
        summary["score_seconds_at_bpm"] = round(
            float(score.highestTime - pad) * 60 / float(bpm), 1)
        summary["note"] = ("score_seconds_at_bpm should be within a few percent of "
                           "audio_seconds; a big mismatch means the BPM is wrong")
    if pad:
        summary["offset_shift_beats"] = int(pad)
        summary["note_post"] = ("pass --offset-shift "
                                f"{int(pad)} to `post` so pedal/dynamics map correctly")
    summary["lint"] = lint_score(args.output)
    print(json.dumps(summary, indent=2))
    return 0


def track_beats_from_midi(mid_path, bpm_hint, lam=6.0, mu=1.0):
    """DP beat tracking on the transcribed MIDI's own onsets — far more precise
    than audio tracking when the transcription is trustworthy. Audio trackers
    pinned to a tempo hint cannot follow deep ritardandi: they fall behind,
    then race ahead at a fake fast tempo and mangle every barline after the
    slowdown. Here each onset cluster is a beat candidate scored by onset
    strength (velocity sum) minus a tempo-continuity penalty (log-period change
    vs the locally smoothed period, plus a weak pull toward the hint), so the
    grid follows rubato at full depth. Returns beat times in the MIDI timeline."""
    import bisect as _bisect
    import math
    import pretty_midi
    pm = pretty_midi.PrettyMIDI(mid_path)
    raw = sorted((n.start, float(n.velocity))
                 for inst in pm.instruments for n in inst.notes)
    clusters = []
    for s, v in raw:
        if clusters and s - clusters[-1][0] < 0.03:
            clusters[-1] = (clusters[-1][0], clusters[-1][1] + v)
        else:
            clusters.append((s, v))
    times = [c[0] for c in clusters]
    wmax = max(c[1] for c in clusters)
    weights = [c[1] / wmax for c in clusters]
    ph = 60.0 / bpm_hint
    pmin, pmax = 0.6 * ph, 1.9 * ph
    n = len(times)
    best, prev, per = [-1e9] * n, [-1] * n, [ph] * n
    for i in range(n):
        if times[i] - times[0] < 2.0:
            best[i] = weights[i]
        lo = _bisect.bisect_left(times, times[i] - pmax)
        for j in range(lo, i):
            p = times[i] - times[j]
            if not (pmin <= p <= pmax) or best[j] < -1e8:
                continue
            cost = lam * math.log(p / per[j]) ** 2 + mu * math.log(p / ph) ** 2
            sc = best[j] + weights[i] - cost
            if sc > best[i]:
                best[i], prev[i], per[i] = sc, j, 0.7 * per[j] + 0.3 * p
    end = max((i for i in range(n) if times[i] > times[-1] - 2.5),
              key=lambda i: best[i])
    seq = []
    i = end
    while i != -1:
        seq.append(times[i])
        i = prev[i]
    return sorted(seq)


def cmd_beats(args):
    """Beat-track the recording with librosa, or — with --from-midi — track the
    transcription's own onsets (preferred for heavy rubato); write beats.json."""
    if args.from_midi:
        tracked = track_beats_from_midi(args.from_midi, args.bpm_hint or 120.0)
        beats = [round(float(b) + args.midi_shift, 4) for b in tracked]
        tempo = (args.bpm_hint or 120.0)
    else:
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            import librosa
            y, sr = librosa.load(args.input, sr=22050, mono=True)
            oenv = librosa.onset.onset_strength(y=y, sr=sr)
            kwargs = {}
            if args.bpm_hint:
                # Pin the tempo: a soft start_bpm prior still lets the tracker lock
                # onto a sub-pulse (e.g. the dotted-eighth of a 3-3-2 groove at 4/3
                # of the true BPM). The DP still places each beat locally, so
                # drift/rubato is tracked — only the metrical level is forced.
                kwargs["bpm"] = args.bpm_hint
            else:
                kwargs["start_bpm"] = 120.0
            tempo, beats = librosa.beat.beat_track(
                onset_envelope=oenv, sr=sr, units="time", trim=False,
                tightness=args.tightness, **kwargs)
        beats = [round(float(b), 4) for b in beats]
    periods = [b - a for a, b in zip(beats, beats[1:])]
    cv = (statistics.stdev(periods) / statistics.mean(periods)) if len(periods) > 2 else None
    report = {
        "audio": args.input,
        "source": "midi-onsets" if args.from_midi else "audio",
        "bpm_hint": args.bpm_hint,
        "tempo_global_bpm": round(float(np.atleast_1d(tempo)[0]), 1),
        "tempo_median_bpm": round(60 / statistics.median(periods), 1) if periods else None,
        "n_beats": len(beats),
        "beat_period_cv": round(cv, 3) if cv is not None else None,
        "stability": ("steady" if cv is not None and cv < 0.05
                      else "some rubato" if cv is not None and cv < 0.15
                      else "rubato"),
        "beats": beats,
    }
    if args.bpm_hint and periods:
        ratio = (60 / statistics.median(periods)) / args.bpm_hint
        if abs(ratio - 1) > 0.08:
            report["warning"] = (f"tracked tempo is {ratio:.2f}x the hint — the tracker "
                                 "may be on a sub-pulse (check 4/3, 3/2, 2x) or the hint "
                                 "is wrong for this performance")
    with open(args.output, "w") as f:
        json.dump(report, f, indent=2)
    print(json.dumps({k: v for k, v in report.items() if k != "beats"}, indent=2))
    print(f"wrote {args.output}")
    return 0


def cmd_verify(args):
    """Objective score-vs-recording check: render the score with mscore, DTW-align
    CQT chroma of render and recording, score per-bar cosine similarity, and
    cross-check repeated sections. Writes verify.json; worst bars belong in
    CLEANUP_NOTES so listening time goes where the score is most wrong."""
    import subprocess
    import tempfile
    import warnings
    from music21 import converter as m21converter

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        import librosa

    score = m21converter.parse(args.score)
    mm = score.recurse().getElementsByClass("MetronomeMark").first()
    bpm = float(mm.number) if mm is not None else 120.0
    ts = score.recurse().getElementsByClass("TimeSignature").first()
    bar_ql = float(ts.barDuration.quarterLength) if ts is not None else 4.0
    parts = list(score.parts)
    n_bars = max(len(p.getElementsByClass("Measure")) for p in parts)
    bar_pitch_sets = []
    for k in range(1, n_bars + 1):
        pcs = set()
        for p in parts:
            m = p.measure(k)
            if m is not None:
                for n in m.recurse().notes:
                    for pt in (n.pitches if hasattr(n, "pitches") else [n.pitch]):
                        pcs.add(pt.midi)
        bar_pitch_sets.append(pcs)

    with tempfile.TemporaryDirectory() as td:
        # mp3, not wav: mscore's wav export can fail (exit 51) in environments
        # where mp3 export still works, and lossy encoding is irrelevant to
        # chroma DTW.
        render_wav = f"{td}/render.mp3"
        res = subprocess.run([args.mscore, args.score, "-o", render_wav],
                             capture_output=True)
        if res.returncode != 0 or not __import__("os").path.getsize(render_wav):
            print(json.dumps({"error": f"mscore render failed ({res.returncode})"}))
            return 1
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            HOP, SR = 2048, 22050
            yr, _ = librosa.load(render_wav, sr=SR, mono=True)
            ya, _ = librosa.load(args.audio, sr=SR, mono=True)
            cr = librosa.feature.chroma_cqt(y=yr, sr=SR, hop_length=HOP)
            ca = librosa.feature.chroma_cqt(y=ya, sr=SR, hop_length=HOP)
            D, wp = librosa.sequence.dtw(X=cr, Y=ca)
    wp = wp[::-1]  # (render_frame, audio_frame), ascending
    audio_for_render = {}
    for rf, af in wp:
        audio_for_render.setdefault(int(rf), []).append(int(af))

    fps = SR / HOP
    bar_seconds_render = bar_ql * 60.0 / bpm
    bars = []
    for k in range(n_bars):
        f0 = int(k * bar_seconds_render * fps)
        f1 = max(f0 + 1, int((k + 1) * bar_seconds_render * fps))
        afs = sorted(a for f in range(f0, min(f1, cr.shape[1]))
                     for a in audio_for_render.get(f, []))
        if not afs:
            continue
        a0, a1 = afs[0], max(afs[-1] + 1, afs[0] + 1)
        vr = cr[:, f0:min(f1, cr.shape[1])].mean(axis=1)
        va = ca[:, a0:min(a1, ca.shape[1])].mean(axis=1)
        denom = (np.linalg.norm(vr) * np.linalg.norm(va))
        sim = float(vr @ va / denom) if denom > 0 else 0.0
        stretch = ((a1 - a0) / (f1 - f0)) if f1 > f0 else 1.0
        bars.append({"bar": k + 1, "similarity": round(sim, 3),
                     "audio_time_s": round(a0 / fps, 1),
                     "audio_mmss": f"{int(a0 / fps) // 60}:{int(a0 / fps) % 60:02d}",
                     "stretch": round(stretch, 2),
                     "chroma": va})
    med_stretch = statistics.median(b["stretch"] for b in bars) if bars else 1.0
    for b in bars:
        b["drift_suspect"] = abs(b["stretch"] - med_stretch) > 0.2 * med_stretch

    # Repeated-section cross-check: bars whose AUDIO is near-identical should
    # contain the same pitch CLASSES (chroma is octave-blind, so exact-pitch
    # comparison would flag mere figuration changes); disagreement localizes
    # transcription errors.
    repeat_flags = []
    for i in range(len(bars)):
        for j in range(i + 4, len(bars)):  # skip trivial neighbors
            vi, vj = bars[i]["chroma"], bars[j]["chroma"]
            denom = np.linalg.norm(vi) * np.linalg.norm(vj)
            if denom == 0 or vi @ vj / denom < 0.99:
                continue
            si = {p % 12 for p in bar_pitch_sets[bars[i]["bar"] - 1]}
            sj = {p % 12 for p in bar_pitch_sets[bars[j]["bar"] - 1]}
            if not si and not sj:
                continue
            jac = len(si & sj) / len(si | sj) if (si | sj) else 1.0
            if jac < 0.6:
                repeat_flags.append({
                    "bars": [bars[i]["bar"], bars[j]["bar"]],
                    "audio_similarity": round(float(vi @ vj / denom), 3),
                    "pitch_class_overlap": round(jac, 2),
                    "hint": "audio repeats but the transcribed pitch content differs — "
                            "one of the two bars is probably wrong"})
    repeat_flags = repeat_flags[:15]

    for b in bars:
        del b["chroma"]
    ranked = sorted(bars, key=lambda b: b["similarity"])
    report = {
        "score": args.score,
        "audio": args.audio,
        "render_bpm": bpm,
        "bars_compared": len(bars),
        "median_similarity": round(statistics.median(b["similarity"] for b in bars), 3)
        if bars else None,
        "worst_bars": ranked[:args.worst],
        "drift_suspects": [b["bar"] for b in bars if b["drift_suspect"]],
        "repeat_inconsistencies": repeat_flags,
        "note": "similarity is chroma-based: octave errors and voicing changes are "
                "partly invisible; use worst_bars to prioritize listening, not as proof",
    }
    if args.output:
        with open(args.output, "w") as f:
            json.dump(report, f, indent=2)
    slim = dict(report)
    slim["worst_bars"] = report["worst_bars"][:5]
    print(json.dumps(slim, indent=2))
    return 0


def cmd_consensus(args):
    """Cross-check a transcription against re-transcriptions of pitch-shifted
    audio: notes of the primary MIDI with no match (same pitch, onset within
    tolerance) in EVERY alternative are reported as suspects — flag, don't delete."""
    primary = all_notes(pretty_midi.PrettyMIDI(args.primary))
    alts = []
    for spec in args.alt:
        path, semis = (spec.rsplit(":", 1) + ["0"])[:2] if ":" in spec else (spec, "0")
        pm = pretty_midi.PrettyMIDI(path)
        shift = int(semis)
        alts.append([(n.pitch - shift, n.start) for n in all_notes(pm)])
    suspects = []
    for n in primary:
        ok = all(any(p == n.pitch and abs(t - n.start) <= args.tolerance
                     for p, t in alt) for alt in alts)
        if not ok:
            suspects.append(note_dict(n))
    report = {"primary": args.primary, "alternatives": len(alts),
              "notes": len(primary), "suspects_count": len(suspects),
              "suspects": suspects[:100],
              "note": "suspects failed consensus across pitch-shifted re-transcriptions; "
                      "verify by ear before removing anything"}
    print(json.dumps(report, indent=2))
    return 0


DYNAMIC_LEVELS = [(30, "pp"), (45, "p"), (60, "mp"), (75, "mf"), (90, "f"), (200, "ff")]


def velocity_profile(pm, window=1.0, ):
    """Smoothed per-window median velocity: [(time_s, velocity)]."""
    notes = all_notes(pm)
    end = max(n.end for n in notes)
    buckets = [[] for _ in range(int(end / window) + 1)]
    for n in notes:
        buckets[int(n.start / window)].append(n.velocity)
    raw = [(i * window, statistics.median(b)) for i, b in enumerate(buckets) if b]
    return [
        (raw[i][0], sum(v for _, v in raw[max(0, i - 1):i + 2]) / len(raw[max(0, i - 1):i + 2]))
        for i in range(len(raw))
    ]


def dynamic_level(vel):
    for threshold, name in DYNAMIC_LEVELS:
        if vel < threshold:
            return name
    return "ff"


def find_hairpins(profile, min_delta=12, min_span=3.0):
    """Sustained monotonic velocity trends -> [(start_s, end_s, 'cresc'|'dim')]."""
    hairpins = []
    i = 0
    while i < len(profile) - 1:
        for direction in (1, -1):
            j = i
            while (j + 1 < len(profile)
                   and direction * (profile[j + 1][1] - profile[j][1]) > -1.5):
                j += 1
            delta = direction * (profile[j][1] - profile[i][1])
            span = profile[j][0] - profile[i][0]
            if delta >= min_delta and span >= min_span:
                hairpins.append((profile[i][0], profile[j][0],
                                 "cresc" if direction == 1 else "dim"))
                i = j
                break
        else:
            i += 1
    return hairpins


def cmd_post(args):
    from music21 import converter, dynamics as m21dyn, expressions, key as m21key, meter
    from music21.stream import Measure

    score = converter.parse(args.input)
    changes = {"respelled": 0, "respelled_directional": 0, "ties_merged": None,
               "rehand_moved": 0, "rebarred": None, "pedal_marks": 0, "pedal_note": None,
               "dynamics_inserted": 0, "hairpins_inserted": 0, "dynamics_note": None}

    # Merge tied chains ONLY when re-barring: that's what lets
    # build_measured_part re-slice them at the new meter. Without --time-sig
    # the quantize output is already barline-exact, and stripTies flattens
    # overlapping voices into one sequential line (overfull measures that
    # makeTies cannot repair).
    if args.time_sig:
        score = score.stripTies()
        changes["ties_merged"] = "stripTies applied (re-barring)"
    else:
        changes["ties_merged"] = "skipped (no re-bar; measures already barline-exact)"

    # Move clearly out-of-range notes to the other staff (piano = two PartStaffs).
    # Must happen before re-barring: makeMeasures rebuilds the measures consistently;
    # inserting into already-voiced measures afterwards produces content mscore rejects.
    def avg_pitch(part):
        ps = [p.midi for n in part.recurse().notes for p in
              (n.pitches if hasattr(n, "pitches") else [n.pitch])]
        return sum(ps) / len(ps) if ps else 60

    parts = list(score.parts)
    treble = None
    if len(parts) == 2:
        treble, bass = sorted(parts, key=avg_pitch, reverse=True)
    if treble is not None and not args.no_rehand:
        for n in list(treble.recurse().notes):
            top = max(p.midi for p in (n.pitches if hasattr(n, "pitches") else [n.pitch]))
            if top < 48:  # below C3: does not belong in the treble staff
                m = n.getContextByClass(Measure)
                target = bass.measure(m.number) if m is not None else None
                if m is not None and target is not None:
                    off = n.offset
                    m.remove(n, recurse=True)
                    target.insert(off, n)
                    changes["rehand_moved"] += 1

    # Re-bar at the requested meter. build_measured_part handles overlapping
    # content (sustained second-voice notes from quantize) by layering into
    # music21 Voices — naive makeMeasures on overlapping flat content lays the
    # layers out sequentially (overfull measures, mscore exit 40). Build a
    # fresh Score from the re-barred parts; mutating the original PartStaffs
    # in place corrupts the two-staff merge at MusicXML export.
    if args.time_sig:
        from music21 import expressions as m21expr, key as m21keymod, layout, \
            stream as m21stream, tempo as m21tempomod
        new_parts = []
        for part in list(score.parts):
            flat = part.flatten()
            items = [(n.offset, n) for n in flat.notes]
            marks = [(el.offset, el) for el in flat.getElementsByClass(
                (m21expr.TextExpression, m21keymod.KeySignature,
                 m21tempomod.MetronomeMark))]
            new_parts.append(build_measured_part(items, marks, args.time_sig, part.id))
        new_score = m21stream.Score()
        if score.metadata is not None:
            new_score.metadata = score.metadata  # title/composer/arranger/performer
        for ps in new_parts:
            new_score.insert(0, ps)
        if len(new_parts) == 2:
            new_score.insert(0, layout.StaffGroup(new_parts, symbol="brace", barTogether=True))
        score = new_score
        parts = new_parts
        treble = sorted(parts, key=avg_pitch, reverse=True)[0] if len(parts) == 2 else None
        changes["rebarred"] = f"{args.time_sig} across {len(new_parts)} staves"

    def m21_key(name):
        return m21key.Key(name.split()[0], name.split()[1] if " " in name else "major")

    def respell_toward(key_name, lo=None, hi=None):
        """Respell wrong-side/awkward accidentals toward key_name; optionally
        only notes whose score offset lies in [lo, hi)."""
        prefer_flats = m21_key(key_name).sharps < 0
        count = 0
        for n in score.recurse().notes:
            if lo is not None:
                off = n.getOffsetInHierarchy(score)
                if not (lo <= off < hi):
                    continue
            pitches = n.pitches if hasattr(n, "pitches") else [n.pitch]
            for p in pitches:
                acc = p.accidental
                if acc is None:
                    continue
                wrong_side = (prefer_flats and acc.alter > 0) or (not prefer_flats and acc.alter < 0)
                if wrong_side or abs(acc.alter) > 1 or p.name in ("E#", "B#", "C-", "F-"):
                    enh = p.getEnharmonic()
                    if enh.accidental is None or abs(enh.accidental.alter) <= 1:
                        p.step, p.accidental, p.octave = enh.step, enh.accidental, enh.octave
                        count += 1
        return count

    if args.key:
        changes["respelled"] += respell_toward(args.key)

        # Chromatic (out-of-key) tones spell by melodic direction — ascending
        # prefers the sharp spelling, descending the flat — overriding the
        # key-side rule above for single notes with a following note to judge by.
        scale_pcs = {p.pitchClass for p in m21_key(args.key).pitches}
        for part in score.parts:
            seq = sorted((n for n in part.recurse().notes if n.isNote),
                         key=lambda n: n.getOffsetInHierarchy(part))
            for cur, nxt in zip(seq, seq[1:]):
                p = cur.pitch
                if (p.accidental is None or p.accidental.alter == 0
                        or p.pitchClass in scale_pcs):
                    continue
                delta = nxt.pitch.ps - p.ps
                if delta == 0:
                    continue
                if (delta < 0) != (p.accidental.alter < 0):
                    enh = p.getEnharmonic()
                    if enh.accidental is not None and abs(enh.accidental.alter) == 1:
                        p.step, p.accidental, p.octave = enh.step, enh.accidental, enh.octave
                        changes["respelled_directional"] += 1

    # Seconds -> quarterLength mapping. With --beats, the beat warp follows the
    # performance through rubato; otherwise a single linear scale derived from
    # the score's own length (the quantize grid), never a trusted tempo number.
    qps, warp, mark_bpm, warp_base = None, None, None, 0
    shift_q = float(args.offset_shift)
    if args.dynamics_from:
        pm_timing = pretty_midi.PrettyMIDI(args.dynamics_from)
    if args.beats:
        bt = load_beat_times(args.beats, args.beats_shift)
        if args.dynamics_from:
            # Same onset refinement as quantize, so the two maps agree exactly.
            bt = refine_beats(bt, all_notes(pm_timing))
        warp = beat_warp(bt)
        if warp:
            import math
            first = all_notes(pm_timing) if args.dynamics_from else None
            warp_base = math.floor(warp(first[0].start if first else 0.0))
            mark_bpm = round(60 / statistics.median(
                b - a for a, b in zip(bt, bt[1:])))
    if args.dynamics_from:
        end_t = pm_timing.get_end_time()
        if end_t > 0 and score.highestTime > 0:
            qps = (float(score.highestTime) - shift_q) / end_t
            if mark_bpm is None:
                mark_bpm = round(qps * 60)

    def to_q(t):
        return ((warp(t) - warp_base) if warp else t * qps) + shift_q

    # Tempo marks: quantize now writes them (possibly several — plateaus), so
    # preserve any that exist; only synthesize a single mark on legacy input.
    if mark_bpm:
        from music21 import tempo as m21tempo
        existing = list(score.recurse().getElementsByClass(m21tempo.MetronomeMark))
        if existing:
            changes["tempo_marked_bpm"] = [int(mm.number) for mm in existing
                                           if mm.number is not None]
        else:
            target = parts[0] if parts else score
            first_m = target.getElementsByClass("Measure").first()
            (first_m if first_m is not None else target).insert(
                0, m21tempo.MetronomeMark(number=mark_bpm))
            changes["tempo_marked_bpm"] = mark_bpm

    # Pedal markings from CC64 regions captured by the clean pass.
    if args.pedal_from:
        with open(args.pedal_from) as f:
            clean_report = json.load(f)
        regions = clean_report.get("pedal_regions", [])
        tempo = clean_report.get("tempo_bpm")
        if qps is None and warp is None and tempo:
            qps = tempo / 60.0  # fallback when --dynamics-from wasn't given
        if not hasattr(expressions, "PedalMark"):
            changes["pedal_note"] = (f"{len(regions)} pedal regions in report, but this music21 "
                                     "lacks PedalMark — add pedal manually in MuseScore")
        elif not (qps or warp):
            changes["pedal_note"] = "no timing scale available; cannot map pedal times to offsets"
        else:
            flat_notes = sorted(score.recurse().notes, key=lambda n: n.getOffsetInHierarchy(score))
            for r in regions:
                start_q, end_q = to_q(r["down"]), to_q(r["up"])
                inside = [n for n in flat_notes
                          if start_q - 0.5 <= n.getOffsetInHierarchy(score) <= end_q]
                if len(inside) >= 1:
                    pmark = expressions.PedalMark()
                    pmark.addSpannedElements([inside[0], inside[-1]])
                    score.insert(0, pmark)
                    changes["pedal_marks"] += 1

    # Dynamics from MIDI velocities: level marks at changes, hairpins on trends.
    if args.dynamics_from:
        if not (qps or warp):
            changes["dynamics_note"] = "no timing scale available; cannot map times to offsets"
        else:
            profile = velocity_profile(pm_timing)
            hairpins = find_hairpins(profile)
            anchor_part = treble if treble is not None else score
            anchored = sorted(anchor_part.recurse().notes,
                              key=lambda n: n.getOffsetInHierarchy(score))

            def note_at(t_seconds):
                q = to_q(t_seconds)
                for n in anchored:
                    if n.getOffsetInHierarchy(score) >= q - 0.25:
                        return n
                return anchored[-1] if anchored else None

            for start_s, end_s, kind in hairpins:
                a, b = note_at(start_s), note_at(end_s)
                if a is not None and b is not None and a is not b:
                    wedge = m21dyn.Crescendo() if kind == "cresc" else m21dyn.Diminuendo()
                    wedge.addSpannedElements([a, b])
                    score.insert(0, wedge)
                    changes["hairpins_inserted"] += 1

            def inside_hairpin(t):
                return any(start_s < t < end_s for start_s, end_s, _ in hairpins)

            current = None
            for t, vel in profile:
                level = dynamic_level(vel)
                if level == current or inside_hairpin(t):
                    continue
                n = note_at(t)
                if n is None:
                    continue
                m = n.getContextByClass(Measure)
                if m is not None:
                    m.insert(n.offset, m21dyn.Dynamic(level))
                    changes["dynamics_inserted"] += 1
                    current = level
            changes["dynamics_note"] = ("derived from MIDI velocities; pedal and texture "
                                        "can skew perceived loudness — refine by ear")

    # Windowed key check: a persistent local key whose signature differs from the
    # global one marks a modulation — respell that region locally and flag it.
    if args.key and args.dynamics_from and (qps or warp):
        WIN = 15.0
        global_sharps = m21_key(args.key).sharps
        m_notes = all_notes(pm_timing)
        wins, t = [], 0.0
        while t < pm_timing.get_end_time():
            chunk = [n for n in m_notes if t <= n.start < t + WIN]
            if len(chunk) >= 12:
                wins.append((t, key_estimate(chunk)[0]["key"]))
            t += WIN
        flags, i = [], 0
        while i < len(wins):
            t0, kname = wins[i]
            if (kname.lower() == args.key.lower()
                    or m21_key(kname).sharps == global_sharps):
                i += 1
                continue
            j = i
            while j + 1 < len(wins) and wins[j + 1][1] == kname:
                j += 1
            if j > i:  # 2+ consecutive windows agree on the foreign key
                lo_s, hi_s = wins[i][0], wins[j][0] + WIN
                lo_q, hi_q = to_q(lo_s), to_q(hi_s)
                changes["respelled"] += respell_toward(kname, lo=lo_q, hi=hi_q)
                # Engrave the modulation: a real key-signature change at the
                # nearest barline, restored to the global key afterwards.
                for part in parts:
                    measures = list(part.getElementsByClass(Measure))
                    m_lo = m_hi = None
                    for m in measures:
                        if m.offset <= lo_q:
                            m_lo = m
                        if m.offset <= hi_q:
                            m_hi = m
                    if m_lo is None or m_lo is m_hi:
                        continue  # sub-bar region: flag only
                    for m, key_name in ((m_lo, kname), (m_hi, args.key)):
                        if m is None:
                            continue
                        for old in list(m.getElementsByClass(m21key.KeySignature)):
                            m.remove(old)
                        m.insert(0, m21key.KeySignature(m21_key(key_name).sharps))
                        changes["key_signatures_inserted"] = \
                            changes.get("key_signatures_inserted", 0) + 1
                flags.append({"approx_start_s": round(lo_s, 1),
                              "approx_end_s": round(hi_s, 1), "local_key": kname})
            i = j + 1
        if flags:
            changes["modulation_flags"] = flags

    normalize_accidentals(score)

    score.write("musicxml", fp=args.output)
    changes["output"] = args.output
    changes["lint"] = lint_score(args.output)
    print(json.dumps(changes, indent=2))
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("analyze", help="read-only JSON report on a transcription MIDI")
    a.add_argument("input")
    a.add_argument("--min-dur", type=float, default=0.06)
    a.add_argument("--vel-ratio", type=float, default=0.45)
    a.set_defaults(fn=cmd_analyze)

    c = sub.add_parser("clean", help="MIDI pre-clean: filter artifacts, set tempo/meter/key meta")
    c.add_argument("input")
    c.add_argument("output")
    c.add_argument("--min-dur", type=float, default=0.06)
    c.add_argument("--vel-ratio", type=float, default=0.45)
    c.add_argument("--keep-ghosts", action="store_true")
    c.add_argument("--tempo", type=float, help="BPM; default: estimated")
    c.add_argument("--time-sig", help='e.g. "3/4"')
    c.add_argument("--key", help='pretty_midi key name, e.g. "D Major" or "C minor"')
    c.add_argument("--trim", action=argparse.BooleanOptionalAction, default=True,
                   help="shift so the first note starts at 0 (bar 1 beat 1)")
    c.add_argument("--tempo-map", help="beats.json — write a beat-aligned tempo map "
                                       "(DAW bar grids follow the performance through "
                                       "rubato and tempo changes)")
    c.add_argument("--report", help="also write the JSON summary to this file")
    c.set_defaults(fn=cmd_clean)

    b = sub.add_parser("beats", help="beat-track the recording (audio) with librosa")
    b.add_argument("input", help="audio file (the prepared .wav)")
    b.add_argument("output", help="beats.json path")
    b.add_argument("--bpm-hint", type=float,
                   help="ground-truth/expected BPM to seed the tracker")
    b.add_argument("--tightness", type=float, default=100.0,
                   help="how strongly the tracker resists tempo change (default 100; "
                        "lower for heavy rubato)")
    b.add_argument("--from-midi",
                   help="track the (cleaned) MIDI's own onsets instead of the audio "
                        "— follows deep ritardandi the audio tracker cannot; the "
                        "audio argument is then used for the report only")
    b.add_argument("--midi-shift", type=float, default=0.0,
                   help="seconds to ADD to MIDI-tracked beats so beats.json stays in "
                        "the audio timeline (the clean pass's trim_shift_s)")
    b.set_defaults(fn=cmd_beats)

    q = sub.add_parser("quantize", help="MIDI -> MusicXML on a fixed BPM grid or "
                                        "beat-tracked warp (never MuseScore's MIDI import)")
    q.add_argument("input")
    q.add_argument("output")
    q.add_argument("--bpm", type=float,
                   help="fixed-grid tempo from ground truth/user/analyze — check the "
                        "sanity fields in the summary (alternative to --beats)")
    q.add_argument("--beats", help="beats.json from the `beats` subcommand — the grid "
                                   "follows the performance (preferred when available)")
    q.add_argument("--beats-shift", type=float, default=0.0,
                   help="seconds to subtract from beat times (the clean pass's "
                        "trim_shift_s) when quantizing a trimmed .mid")
    q.add_argument("--grid", type=int, default=32,
                   help="onset grid as a note-value denominator (default 32 = 32nd notes)")
    q.add_argument("--split", default="auto",
                   help='hand-split pitch, e.g. "E3"; default: auto from pitch-gap analysis')
    q.add_argument("--key", help='e.g. "D major" — inserts the key signature')
    q.add_argument("--time-sig", help='e.g. "3/4" — inserts the time signature and '
                                      'sets the bar length for downbeat inference')
    q.add_argument("--bar-phase", type=int,
                   help="force the downbeat phase (0 = first onset is a downbeat) "
                        "instead of trusting the inference — use when its "
                        "confidence is marginal and the ear disagrees")
    q.add_argument("--no-legato-fill", action="store_true",
                   help="keep performed note lengths instead of filling gaps to the "
                        "next onset (for articulation-faithful engraving)")
    q.add_argument("--title", help="piece title for the score header")
    q.add_argument("--composer", help="original composer/artist")
    q.add_argument("--arranger", help="arranger (cover/arrangement author), if applicable")
    q.add_argument("--performer", help="performer/pianist, if known")
    q.set_defaults(fn=cmd_quantize)

    v = sub.add_parser("verify", help="render the score and compare to the recording "
                                      "per bar (chroma DTW) — targets listening time")
    v.add_argument("score", help="the .cleaned.musicxml (must carry a metronome mark)")
    v.add_argument("audio", help="the original recording (wav/mp3)")
    v.add_argument("--output", help="write the full JSON report here (verify.json)")
    v.add_argument("--worst", type=int, default=10, help="how many worst bars to list")
    v.add_argument("--mscore", default="/Applications/MuseScore 4.app/Contents/MacOS/mscore")
    v.set_defaults(fn=cmd_verify)

    n = sub.add_parser("consensus", help="flag notes missing from pitch-shifted "
                                         "re-transcriptions (suspects, never deletions)")
    n.add_argument("primary", help="the transcription under test (.mid)")
    n.add_argument("alt", nargs="+",
                   help='alternative transcription(s), "path.mid:SEMITONES" where '
                        "SEMITONES is the shift applied to the audio (e.g. alt_up.mid:1)")
    n.add_argument("--tolerance", type=float, default=0.05,
                   help="onset match window in seconds (default 0.05)")
    n.set_defaults(fn=cmd_consensus)

    p = sub.add_parser("post", help="music21 notation fixes on quantized MusicXML")
    p.add_argument("input")
    p.add_argument("output")
    p.add_argument("--key", help='e.g. "D major" — drives enharmonic respelling')
    p.add_argument("--time-sig", help='e.g. "3/4" — re-bar at this meter')
    p.add_argument("--pedal-from", help="clean-pass JSON report containing pedal_regions")
    p.add_argument("--dynamics-from", help="cleaned .mid — derive dynamics/hairpins from velocities")
    p.add_argument("--beats", help="beats.json — map seconds to offsets through the beat "
                                   "warp (must match what quantize used)")
    p.add_argument("--beats-shift", type=float, default=0.0,
                   help="same shift passed to quantize --beats-shift")
    p.add_argument("--offset-shift", type=float, default=0.0,
                   help="quantize's offset_shift_beats (pickup padding), so "
                        "pedal/dynamics land on the shifted offsets")
    p.add_argument("--no-rehand", action="store_true")
    p.set_defaults(fn=cmd_post)

    args = ap.parse_args()
    sys.exit(args.fn(args))


if __name__ == "__main__":
    main()
