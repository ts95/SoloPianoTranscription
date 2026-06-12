---
name: cleanup-score
description: Clean up a transcribed score - remove transcription artifacts, fix key/meter/tempo using online ground truth plus statistical analysis, repair notation, regenerate MusicXML/.mscz, and write a report flagging what needs human review by ear. Use after the transcribe pipeline, on a piece directory under output/.
---

# Clean up a transcribed score

Input: a piece directory `output/<slug>/` (or any transcription `.mid`). Requires the raw `.mid`; the cleaned score is reconverted from it. **Never overwrite originals** — all products use the `.cleaned.*` suffix, plus a `CLEANUP_NOTES.md` report.

Core principle: fix what is decidable from the data (or from published facts about the piece); anything that requires hearing the recording gets **flagged, not changed**.

Tools: `scripts/transcription_cleanup.py` (run with `.venv/bin/python`), mscore at `/Applications/MuseScore 4.app/Contents/MacOS/mscore`, music21 in the venv for bespoke fixes.

## 1. Ground-truth lookup (web)

Identify the piece from the slug / video title (composer, work, movement). Web-search for authoritative facts: **key signature, meter, tempo marking**. Good sources: Wikipedia, IMSLP, composer catalogs; for unpublished pieces, the video description/comments or reviews often still state key or meter. Record everything found with source URLs. Finding nothing is fine — analysis is the fallback.

## 2. Analyze

```bash
.venv/bin/python scripts/transcription_cleanup.py analyze 'output/<slug>/<slug>.mid'
```

Interpret the JSON with musical judgment:

- **Key**: prefer web ground truth; else top `key_estimates` entry. If ground truth and analysis disagree on a published work, trust ground truth and flag the disagreement. If neither is confident, omit `--key` and flag.
- **Meter**: prefer ground truth. Statistically, the strongest `grouping_scores` entry suggests beats per bar — sanity-check `bpm_candidates` against the piece's character (a value can be double/half the true tempo).
- **Tempo**: the BPM drives the entire quantization grid in step 4, so get it right. Prefer ground truth / the user's word over the statistical candidates: autocorrelation locks onto the dominant *pulse*, which can be a subdivision — not just 2×/half but e.g. the dotted-eighth of a 3-3-2 groove (4/3 of the true BPM; observed on an EDM cover where candidates said 171/86 and the truth was 125). Validate with the `quantize` summary's `score_seconds_at_bpm` vs `audio_seconds` fields, and check that `duration ÷ (60/bpm × beats-per-bar)` gives a plausible bar count.
- **Rubato**: if `tempo_stability.verdict` is "heavy rubato", barlines will drift regardless of meter — proceed but flag prominently.
- **Thresholds**: review the `artifact_candidates`/`ghost_candidates` samples. Be conservative: when a candidate might be a real grace note or ornament, keep it (raise `--vel-ratio` down / `--min-dur` down) and flag it instead.

## 3. Clean the MIDI

```bash
.venv/bin/python scripts/transcription_cleanup.py clean \
  'output/<slug>/<slug>.mid' 'output/<slug>/<slug>.cleaned.mid' \
  --time-sig '3/4' --key 'D Major' --tempo 78 \
  --report 'output/<slug>/clean_report.json'
```

(Flags per your step-2 decisions; `--keep-ghosts` if ghost candidates looked like real notes.) The tempo/key/time-sig meta events make the `.cleaned.mid` correct as a standalone deliverable; the score itself is built by `quantize` + `post` below.

## 4. Quantize and post-process

**Never feed a `.mid` to MuseScore** — its import quantization auto-detects its own tempo (ignoring the tempo and time-signature meta events) and can lock onto a sub-pulse, wronging every barline and spraying fake tuplets. Use the script's `quantize` instead; mscore is only used for the final `.musicxml` → `.mscz` format conversion.

```bash
.venv/bin/python scripts/transcription_cleanup.py quantize \
  'output/<slug>/<slug>.cleaned.mid' 'output/<slug>/<slug>.tmp.musicxml' \
  --bpm 78 --key 'D major'
.venv/bin/python scripts/transcription_cleanup.py post \
  'output/<slug>/<slug>.tmp.musicxml' 'output/<slug>/<slug>.cleaned.musicxml' \
  --key 'D major' --time-sig '3/4' \
  --pedal-from 'output/<slug>/clean_report.json' \
  --dynamics-from 'output/<slug>/<slug>.cleaned.mid'
MSCORE="/Applications/MuseScore 4.app/Contents/MacOS/mscore"
"$MSCORE" 'output/<slug>/<slug>.cleaned.musicxml' -o 'output/<slug>/<slug>.cleaned.mscz'
rm 'output/<slug>/<slug>.tmp.musicxml'
```

`quantize` snaps onsets to a fixed grid at the chosen BPM (default 32nd notes; `--grid` to change), merges same-slot notes into chords, caps durations at the next onset in the same staff (pedal marks carry the sustain), and splits hands at the analyzer-suggested pitch (`--split` to override). Check its summary: `score_seconds_at_bpm` must be within a few percent of `audio_seconds`, and `post`'s `tempo_marked_bpm` should land on (or very near) your chosen BPM — a mismatch means the BPM was wrong; go back to step 2.

`post` does the canned notation fixes: enharmonic respelling toward the key, merging fragmented tied chains, moving clearly out-of-range notes to the correct staff, pedal markings from CC64, and **dynamics from MIDI velocities** — level marks (pp–ff) at changes plus cresc./dim. hairpins where the velocity profile trends steadily. Check `dynamics_preview` in the analyze report first; if the proposed levels look like noise (e.g. constant-velocity synthesized audio), drop `--dynamics-from`.

## 5. Bespoke repair pass (model judgment)

Inspect the cleaned MusicXML and compare against the analyze report:

- Note-type histogram (`grep -o "<type>[a-z0-9]*</type>" | sort | uniq -c`): stray 32nds/64ths in a piece whose rhythm profile is slow are quantization mangling. Chains of tiny tied values that sum to a simple duration are really one note under rubato. Tuplets should be rare-to-absent (the grid is binary); a tuplet explosion means something upstream went wrong.
- Possible triplet regions (from `fast_runs` / IOI reasoning): the binary grid forces genuine triplets/swing onto the nearest 32nd positions — passages that should be tuplets need renotating (or at least flagging).
- Voice separation oddities (overlapping voices, chords split oddly), and the hand split: it's a single pitch threshold, so crossing-hands passages land on the wrong staff.

Write targeted music21 snippets against specific measures to repair what you're **confident** about; anything uncertain goes in the report instead. This judgment step is the reason cleanup is a skill and not just a script.

## 6. Verify

- `.cleaned.musicxml` has the chosen `<fifths>`/`<beats>` values; note-type histogram improved vs the raw conversion; mscore exited 0 for the `.mscz`; originals untouched.

## 7. Write `output/<slug>/CLEANUP_NOTES.md`

Three sections:

1. **Ground truth used** — piece identification and the key/meter/tempo facts applied, with source URLs (or "none found — used statistical analysis").
2. **Changed automatically** — every transform with counts and timestamps (artifact/ghost/duplicate removals, respellings, tie merges, staff moves, pedal marks, meter/key/tempo set, bespoke repairs with measure numbers).
3. **Verify by ear** — each flag with ≈measure + timestamp (measure ≈ `time / (60/bpm × beats-per-bar)`, counting from the trim shift). Always include the standing items:
   - verify pitches against the recording (the model cannot hear; wrong/missed notes are invisible in the data)
   - the downbeat anchor: the first sounded note is placed on bar 1 beat 1 — if the piece opens with a pickup, every barline is shifted
   - note durations are conservative (capped at the next onset, snapped down; pedal carries the sustain) — lengthen melody notes that should sing
   - rubato regions where barlines may drift
   - tuplet-vs-straight decisions made, and their alternatives
   - dense clusters (possible pedal smear) to thin by ear
   - fast runs that may be ornaments (trills/turns) to renotate
   - dynamics are velocity-derived: pedal and texture skew perceived loudness, so the pp–ff levels and hairpin placement are starting points to refine by ear

## 8. Report in chat

Artifact paths plus the top human-attention items, so the user knows where to spend their listening time.
