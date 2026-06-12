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
- **Rubato**: if `tempo_stability.verdict` is "heavy rubato", barlines will drift regardless of meter — proceed but flag prominently.
- **Thresholds**: review the `artifact_candidates`/`ghost_candidates` samples. Be conservative: when a candidate might be a real grace note or ornament, keep it (raise `--vel-ratio` down / `--min-dur` down) and flag it instead.

## 3. Clean the MIDI

```bash
.venv/bin/python scripts/transcription_cleanup.py clean \
  'output/<slug>/<slug>.mid' 'output/<slug>/<slug>.cleaned.mid' \
  --time-sig '3/4' --key 'D Major' --tempo 78 \
  --report 'output/<slug>/clean_report.json'
```

(Flags per your step-2 decisions; `--keep-ghosts` if ghost candidates looked like real notes.) The tempo/key meta events drive MuseScore's quantization grid, which is why this happens before reconversion. **MuseScore 4's MIDI import ignores the time-signature meta event** — that's why `--time-sig` must be passed again to `post`, which re-bars the score with music21.

## 4. Reconvert and post-process

```bash
MSCORE="/Applications/MuseScore 4.app/Contents/MacOS/mscore"
"$MSCORE" 'output/<slug>/<slug>.cleaned.mid' -o 'output/<slug>/<slug>.tmp.musicxml'
.venv/bin/python scripts/transcription_cleanup.py post \
  'output/<slug>/<slug>.tmp.musicxml' 'output/<slug>/<slug>.cleaned.musicxml' \
  --key 'D major' --time-sig '3/4' \
  --pedal-from 'output/<slug>/clean_report.json' \
  --dynamics-from 'output/<slug>/<slug>.cleaned.mid'
"$MSCORE" 'output/<slug>/<slug>.cleaned.musicxml' -o 'output/<slug>/<slug>.cleaned.mscz'
rm 'output/<slug>/<slug>.tmp.musicxml'
```

`post` does the canned notation fixes: enharmonic respelling toward the key, merging fragmented tied chains, moving clearly out-of-range notes to the correct staff, pedal markings from CC64, and **dynamics from MIDI velocities** — level marks (pp–ff) at changes plus cresc./dim. hairpins where the velocity profile trends steadily. Check `dynamics_preview` in the analyze report first; if the proposed levels look like noise (e.g. constant-velocity synthesized audio), drop `--dynamics-from`.

## 5. Bespoke repair pass (model judgment)

Inspect the cleaned MusicXML and compare against the analyze report:

- Note-type histogram (`grep -o "<type>[a-z0-9]*</type>" | sort | uniq -c`): stray 32nds/64ths in a piece whose rhythm profile is slow are quantization mangling. Chains of tiny tied values that sum to a simple duration are really one note under rubato.
- Possible triplet regions (from `fast_runs` / IOI reasoning): grid quantizers mangle triplets into dotted patterns.
- Voice separation oddities (overlapping voices, chords split oddly).

Write targeted music21 snippets against specific measures to repair what you're **confident** about; anything uncertain goes in the report instead. This judgment step is the reason cleanup is a skill and not just a script.

## 6. Verify

- `.cleaned.musicxml` has the chosen `<fifths>`/`<beats>` values; note-type histogram improved vs the raw conversion; mscore exited 0 for the `.mscz`; originals untouched.

## 7. Write `output/<slug>/CLEANUP_NOTES.md`

Three sections:

1. **Ground truth used** — piece identification and the key/meter/tempo facts applied, with source URLs (or "none found — used statistical analysis").
2. **Changed automatically** — every transform with counts and timestamps (artifact/ghost/duplicate removals, respellings, tie merges, staff moves, pedal marks, meter/key/tempo set, bespoke repairs with measure numbers).
3. **Verify by ear** — each flag with ≈measure + timestamp (measure ≈ `time / (60/bpm × beats-per-bar)`, counting from the trim shift). Always include the standing items:
   - verify pitches against the recording (the model cannot hear; wrong/missed notes are invisible in the data)
   - rubato regions where barlines may drift
   - tuplet-vs-straight decisions made, and their alternatives
   - dense clusters (possible pedal smear) to thin by ear
   - fast runs that may be ornaments (trills/turns) to renotate
   - dynamics are velocity-derived: pedal and texture skew perceived loudness, so the pp–ff levels and hairpin placement are starting points to refine by ear

## 8. Report in chat

Artifact paths plus the top human-attention items, so the user knows where to spend their listening time.
