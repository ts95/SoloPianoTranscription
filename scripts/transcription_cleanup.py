#!/usr/bin/env python3
"""Analysis and cleanup helpers for Transkun piano transcriptions.

Subcommands:
  analyze <in.mid>                      print a JSON report (read-only)
  clean   <in.mid> <out.mid> [opts]     MIDI-level pre-clean before MuseScore import
  post    <in.musicxml> <out.musicxml>  music21 notation-level fixes after import

All decisions that require judgment (key, meter, thresholds) are passed in as
flags; this script only does the mechanical work and reports what it did.
"""
import argparse
import json
import statistics
import sys

import numpy as np
import pretty_midi

GHOST_INTERVALS = {12, 19, 24}  # octave, twelfth, double octave above a real note
ONSET_TOLERANCE = 0.03          # seconds: "same onset" for ghost/duplicate checks

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


def find_ghosts(notes, vel_ratio=0.55):
    """Quiet notes at a harmonic interval above a louder note with the same onset."""
    med_vel = statistics.median(n.velocity for n in notes)
    ghosts = []
    for i, n in enumerate(notes):
        if n.velocity >= med_vel * vel_ratio:
            continue
        for m in notes:
            if m is n:
                continue
            if abs(m.start - n.start) > ONSET_TOLERANCE:
                continue
            if n.pitch - m.pitch in GHOST_INTERVALS and m.velocity > n.velocity * 1.5:
                ghosts.append(n)
                break
    return ghosts


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
    ghosts = find_ghosts(notes)
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
    artifacts = find_artifacts(notes, args.min_dur, args.vel_ratio)
    drop.update(id(n) for n in artifacts)
    ghosts = find_ghosts(notes) if not args.keep_ghosts else []
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
        "removed_ghosts": {"count": len(ghosts), "sample": [note_dict(n) for n in ghosts[:50]]},
        "removed_duplicates": {"count": len(dups), "sample": [note_dict(n) for n in dups[:50]]},
        "trim_shift_s": round(shift, 3),
        "tempo_bpm": tempo,
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
    changes = {"respelled": 0, "ties_merged": "stripTies applied", "rehand_moved": 0,
               "rebarred": None, "pedal_marks": 0, "pedal_note": None,
               "dynamics_inserted": 0, "hairpins_inserted": 0, "dynamics_note": None}

    # Merge fragmented tied chains; export re-creates only the ties barlines require.
    score = score.stripTies()

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

    # MuseScore 4's MIDI import ignores time-signature meta events, so re-bar here:
    # same note offsets/durations (the quantization grid is beat-level), new grouping.
    # Build a fresh Score from the re-barred parts — mutating the original PartStaffs
    # in place corrupts the two-staff merge at MusicXML export (overfull measures,
    # mscore exit 40).
    if args.time_sig:
        from music21 import layout, stream as m21stream
        new_parts = []
        for part in list(score.parts):
            flat = part.flatten()
            for old in list(flat.getElementsByClass(meter.TimeSignature)):
                flat.remove(old)
            ts = meter.TimeSignature(args.time_sig)
            flat.insert(0, ts)
            # Split notes at the new barlines while the stream is still flat —
            # makeTies on overlapping (unvoiced) measure content mis-splits.
            bar_ql = ts.barDuration.quarterLength
            bar_offsets = [i * bar_ql for i in range(1, int(flat.highestTime // bar_ql) + 1)]
            flat.sliceAtOffsets(bar_offsets, addTies=True, inPlace=True)
            # No manual makeVoices here: voices built with fillGaps=False export
            # broken <forward> arithmetic (overfull measures, mscore exit 40);
            # music21's own export-time notation pass voices overlaps correctly.
            rebarred = flat.makeMeasures()
            ps = m21stream.PartStaff(id=part.id)
            for el in rebarred:
                ps.insert(el.offset, el)
            new_parts.append(ps)
        new_score = m21stream.Score()
        for ps in new_parts:
            new_score.insert(0, ps)
        if len(new_parts) == 2:
            new_score.insert(0, layout.StaffGroup(new_parts, symbol="brace", barTogether=True))
        score = new_score
        parts = new_parts
        treble = sorted(parts, key=avg_pitch, reverse=True)[0] if len(parts) == 2 else None
        changes["rebarred"] = f"{args.time_sig} across {len(new_parts)} staves"

    if args.key:
        k = m21key.Key(args.key.split()[0], args.key.split()[1] if " " in args.key else "major")
        prefer_flats = k.sharps < 0
        for n in score.recurse().notes:
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
                        changes["respelled"] += 1

    # Seconds -> quarterLength scale. MuseScore's MIDI import picks its own
    # quantization grid (it ignores tempo meta just like time signatures), so
    # derive the true scale from the score itself rather than any tempo number.
    qps = None
    if args.dynamics_from:
        pm_timing = pretty_midi.PrettyMIDI(args.dynamics_from)
        end_t = pm_timing.get_end_time()
        if end_t > 0 and score.highestTime > 0:
            qps = float(score.highestTime) / end_t

    # Set a metronome mark matching the grid, so playback matches the recording.
    if qps:
        from music21 import tempo as m21tempo
        for mm in list(score.recurse().getElementsByClass(m21tempo.MetronomeMark)):
            if mm.activeSite is not None:
                mm.activeSite.remove(mm)
        target = parts[0] if parts else score
        first_m = target.getElementsByClass("Measure").first()
        (first_m if first_m is not None else target).insert(
            0, m21tempo.MetronomeMark(number=round(qps * 60)))
        changes["tempo_marked_bpm"] = round(qps * 60)

    # Pedal markings from CC64 regions captured by the clean pass.
    if args.pedal_from:
        with open(args.pedal_from) as f:
            clean_report = json.load(f)
        regions = clean_report.get("pedal_regions", [])
        tempo = clean_report.get("tempo_bpm")
        if qps is None and tempo:
            qps = tempo / 60.0  # fallback when --dynamics-from wasn't given
        if not hasattr(expressions, "PedalMark"):
            changes["pedal_note"] = (f"{len(regions)} pedal regions in report, but this music21 "
                                     "lacks PedalMark — add pedal manually in MuseScore")
        elif not qps:
            changes["pedal_note"] = "no timing scale available; cannot map pedal times to offsets"
        else:
            flat_notes = sorted(score.recurse().notes, key=lambda n: n.getOffsetInHierarchy(score))
            for r in regions:
                start_q, end_q = r["down"] * qps, r["up"] * qps
                inside = [n for n in flat_notes
                          if start_q - 0.5 <= n.getOffsetInHierarchy(score) <= end_q]
                if len(inside) >= 1:
                    pmark = expressions.PedalMark()
                    pmark.addSpannedElements([inside[0], inside[-1]])
                    score.insert(0, pmark)
                    changes["pedal_marks"] += 1

    # Dynamics from MIDI velocities: level marks at changes, hairpins on trends.
    if args.dynamics_from:
        if not qps:
            changes["dynamics_note"] = "no timing scale available; cannot map times to offsets"
        else:
            profile = velocity_profile(pm_timing)
            hairpins = find_hairpins(profile)
            anchor_part = treble if treble is not None else score
            anchored = sorted(anchor_part.recurse().notes,
                              key=lambda n: n.getOffsetInHierarchy(score))

            def note_at(t_seconds):
                q = t_seconds * qps
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

    score.write("musicxml", fp=args.output)
    changes["output"] = args.output
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
    c.add_argument("--report", help="also write the JSON summary to this file")
    c.set_defaults(fn=cmd_clean)

    p = sub.add_parser("post", help="music21 notation fixes on MuseScore-exported MusicXML")
    p.add_argument("input")
    p.add_argument("output")
    p.add_argument("--key", help='e.g. "D major" — drives enharmonic respelling')
    p.add_argument("--time-sig", help='e.g. "3/4" — re-bar (MuseScore MIDI import ignores the meta event)')
    p.add_argument("--pedal-from", help="clean-pass JSON report containing pedal_regions")
    p.add_argument("--dynamics-from", help="cleaned .mid — derive dynamics/hairpins from velocities")
    p.add_argument("--no-rehand", action="store_true")
    p.set_defaults(fn=cmd_post)

    args = ap.parse_args()
    sys.exit(args.fn(args))


if __name__ == "__main__":
    main()
