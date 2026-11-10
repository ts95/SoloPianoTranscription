#!/usr/bin/env python3
"""Analysis and cleanup helpers for Transkun piano transcriptions.

The MIDI -> MusicXML stage is DuET (see scripts/duet.sh); this script handles the
MIDI-side analysis and pre-clean around it.

Subcommands:
  analyze   <in.mid>                     print a JSON report (read-only)
  clean     <in.mid> <out.mid> [opts]    MIDI-level pre-clean (artifacts, trim, meta)
  verify    <score.musicxml> <audio>     render the score, DTW-align chroma to the
                                         recording per bar — targets listening time
  consensus <primary.mid> alt.mid:SEMI   flag notes missing from pitch-shifted
                                         re-transcriptions (suspects, never deletions)

All decisions that require judgment (key, meter, thresholds) are passed in as
flags; this script only does the mechanical work and reports what it did.
"""
import argparse
import json
import os
import statistics
import subprocess
import sys
import warnings

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


def scale_for_clean(notes, key_arg):
    """Scale pitch classes for the artifact music-prior: the ground-truth
    --key when given, else the top statistical estimate."""
    if key_arg:
        n = pretty_midi.key_name_to_key_number(key_arg)
        base = MAJOR_SCALE_PCS if n < 12 else MINOR_SCALE_PCS
        return {(n % 12 + pc) % 12 for pc in base}
    return key_scale_pcs(key_estimate(notes)[0]["key"])


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
        "dense_clusters": clusters,
        "fast_runs": runs,
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
    scale = scale_for_clean(notes, args.key)
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


def bar_times_from_midi(path):
    """Bar start times (s) of a MIDI file, plus its end time as the last element.
    Honors every tempo and time-signature change."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # mscore puts tempo events on track 1
        pm = pretty_midi.PrettyMIDI(path)
    end = float(pm.get_end_time())
    return [float(d) for d in pm.get_downbeats() if d < end - 1e-6] + [end]


def render_ok(mscore, score, target):
    """Run `mscore score -o target`; True iff target exists and is non-empty.
    The exit code is ignored: mscore can exit 134 on shutdown after a good write."""
    subprocess.run([mscore, score, "-o", target], capture_output=True)
    return os.path.exists(target) and os.path.getsize(target) > 0


def bar_similarity(vr, va):
    """Cosine similarity of the rendered and recorded chroma of one bar; None when
    either side is silent (e.g. DTW parks the last bars on a video's silent outro)."""
    denom = float(np.linalg.norm(vr) * np.linalg.norm(va))
    if not np.isfinite(denom) or denom == 0:
        return None
    return round(float(vr @ va / denom), 6)


def cmd_verify(args):
    """Objective score-vs-recording check: render the score with mscore, DTW-align
    CQT chroma of render and recording, score per-bar cosine similarity, and
    cross-check repeated sections. Writes verify.json; worst bars belong in
    CLEANUP_NOTES so listening time goes where the score is most wrong."""
    import tempfile
    from music21 import converter as m21converter

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        import librosa

    score = m21converter.parse(args.score)
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
        render_mid = f"{td}/render.mid"
        for target in (render_wav, render_mid):
            if not render_ok(args.mscore, args.score, target):
                print(json.dumps({"error": f"mscore render failed: {os.path.basename(target)}"}))
                return 1
        times = bar_times_from_midi(render_mid)
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
    n_bars = min(n_bars, len(times) - 1)
    bars = []
    silent = []
    for k in range(n_bars):
        f0 = int(times[k] * fps)
        f1 = max(f0 + 1, int(times[k + 1] * fps))
        afs = sorted(a for f in range(f0, min(f1, cr.shape[1]))
                     for a in audio_for_render.get(f, []))
        if not afs:
            continue
        a0, a1 = afs[0], max(afs[-1] + 1, afs[0] + 1)
        vr = cr[:, f0:min(f1, cr.shape[1])].mean(axis=1)
        va = ca[:, a0:min(a1, ca.shape[1])].mean(axis=1)
        sim = bar_similarity(vr, va)
        if sim is None:
            silent.append(k + 1)
            continue
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
        "render_seconds": round(times[-1], 1),
        "bars_compared": len(bars),
        "silent_bars_skipped": silent,
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

    v = sub.add_parser("verify", help="render the score and compare to the recording "
                                      "per bar (chroma DTW) — targets listening time")
    v.add_argument("score", help="the score .musicxml")
    v.add_argument("audio", help="the original recording (wav/mp3)")
    v.add_argument("--output", help="write the full JSON report here (verify.json)")
    v.add_argument("--worst", type=int, default=10, help="how many worst bars to list")
    v.add_argument("--mscore", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "mscore.sh"),
                   help="MuseScore CLI (default: scripts/mscore.sh, which honours $MSCORE)")
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

    args = ap.parse_args()
    sys.exit(args.fn(args))


if __name__ == "__main__":
    main()
