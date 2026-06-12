---
name: cleanup-score
description: Clean up a transcribed score - remove transcription artifacts, fix key/meter/tempo using online ground truth plus statistical analysis, repair notation, regenerate MusicXML/.mscz, and write a report flagging what needs human review by ear. Use after the transcribe pipeline, on a piece directory under output/.
---

# Clean up a transcribed score

Input: a piece directory `output/<slug>/` (or any transcription `.mid`). Requires the raw `.mid`; the cleaned score is reconverted from it. **Never overwrite originals** — all products use the `.cleaned.*` suffix, plus a `CLEANUP_NOTES.md` report.

**MIDI-only mode**: if the user asked for just a cleaned MIDI (no sheet music), run steps 1–3 and stop — `<slug>.cleaned.mid` is complete on its own (artifacts removed, trimmed, correct tempo/meter/key meta). Skip quantize/post/mscz, and base `CLEANUP_NOTES.md` on the clean report alone. If the performance has rubato or tempo changes, add `--tempo-map 'output/<slug>/beats.json'` to `clean` so the MIDI carries a beat-aligned tempo map (DAW bar grids follow the performance).

**Articulation (rule)**: if the user wasn't already asked at transcription time, ask before quantizing whether to diverge from the legato default. If yes, pass `--no-legato-fill` to `quantize` and derive articulations from the MIDI (consistent raw durations well below the gap to the next onset = staccato/detached — add marks via a bespoke music21 pass where the pattern is clear, flag where it isn't).

**Lint (rule)**: `quantize` and `post` output a `lint` block — unbalanced measures must be 0 and the printed-accidental ratio sane (verdict "ok") before the score ships.

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
- **Rubato**: check `tempo_stability.verdict`, and run the audio beat tracker for a second opinion:

  ```bash
  .venv/bin/python scripts/transcription_cleanup.py beats \
    'output/<slug>/<slug>.wav' 'output/<slug>/beats.json' --bpm-hint <bpm>
  ```

  (Works on the mp3 too for pre-WAV pieces.) Always pass `--bpm-hint` when ground truth exists — it pins the metrical level; without it the tracker can lock onto a sub-pulse exactly like the autocorrelation does. **Grid choice**: if the beats report says "steady", use the fixed `--bpm` grid in step 4 (cleaner notation); if "some rubato"/"rubato", use `--beats` so barlines follow the performance. Heavy rubato still gets flagged prominently either way.

  **Validate the grid before quantizing with it** — fraction of MIDI onsets within 0.07 beat of a 16th slot (`onset_grid_fit` in the `--refine` report; compute the same metric by hand for other grids). A grid scoring ~0.25 mis-snaps most notes (shifted melody, false dotted rhythms). On syncopated grooves (3-3-2) *both* the audio tracker and `--from-midi` chase the accent layer; there use `beats --refine <mid> --bpm-hint <bpm> --midi-shift <trim_shift_s>` — fixed grid scanned around the hint, smoothly refined to the onsets, level-locked. ~0.7 with onset-position peaks centered on the 16th slots is healthy for human grooves.
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
# Steady piece: fixed grid. Rubato piece: swap --bpm 78 for
#   --beats 'output/<slug>/beats.json' --beats-shift <trim_shift_s from clean_report>
# and pass the same --beats/--beats-shift to post (plus --offset-shift if the
# quantize summary asked for it).
.venv/bin/python scripts/transcription_cleanup.py quantize \
  'output/<slug>/<slug>.cleaned.mid' 'output/<slug>/<slug>.tmp.musicxml' \
  --bpm 78 --key 'D major' --time-sig '3/4' \
  --title '<piece>' --composer '<original composer/artist>' \
  # plus --arranger / --performer when known
.venv/bin/python scripts/transcription_cleanup.py post \
  'output/<slug>/<slug>.tmp.musicxml' 'output/<slug>/<slug>.cleaned.musicxml' \
  --key 'D major' --time-sig '3/4' \
  --pedal-from 'output/<slug>/clean_report.json' \
  --dynamics-from 'output/<slug>/<slug>.cleaned.mid'
MSCORE="/Applications/MuseScore 4.app/Contents/MacOS/mscore"
"$MSCORE" 'output/<slug>/<slug>.cleaned.musicxml' -o 'output/<slug>/<slug>.cleaned.mscz'
rm 'output/<slug>/<slug>.tmp.musicxml'
```

`quantize` chooses a subdivision per beat (binary or ternary — genuine triplets become real tuplets; swing is detected and notated straight with a "Swing" direction), merges same-slot notes into chords, assigns hands with a cost model (span/movement/register — handles crossings; `--split E3` forces a static threshold), and caps durations at the next onset — except lone melody/bass notes that clearly ring over other registers, which become a second voice in the staff (check `sustained_as_second_voice` in the summary). Duration decisions are **pedal-aware** (CC64): a ring that only the pedal carries is acoustic smear, so it never becomes a sustained second voice, and legato fill never bridges a same-staff silence longer than ~a beat — under pedal the note holds to the next beat boundary (stabs stay stabs), pedal-up it keeps the performed length (real silence stays rests). With `--beats` the grid is the tracked beat sequence (refined to MIDI onsets), so rubato and drift don't corrupt barlines, and persistent tempo deviations get `rit.`/`accel.`/`a tempo` text. Pass `--time-sig` so it can infer the **downbeat phase** from bass/harmony/agogic cues — if the piece starts mid-bar it opens bar 1 with rests and reports a pickup flag (always relay this to "verify by ear").

Check the summaries: fixed-grid `score_seconds_at_bpm` must be within a few percent of `audio_seconds`, and `post`'s `tempo_marked_bpm` should land near the chosen/tracked BPM — a mismatch means the BPM was wrong; go back to step 2. If quantize reports `offset_shift_beats`, pass that value to `post --offset-shift`.

Multi-tempo / multi-key pieces: with `--beats`, sustained tempo plateaus (>12% for 16+ beats) are engraved as metronome-mark changes (`tempo_plateaus` in the summary); `post` engraves real key-signature changes for persistent modulations (`key_signatures_inserted`) and restores the global key after — always relay both to "verify by ear". For the MIDI deliverable, `clean --tempo-map 'output/<slug>/beats.json'` writes a beat-aligned tempo map so DAW bar grids follow the performance.

**Score metadata (rule)**: every generated `.musicxml`/`.mscz` carries header metadata — `--title` and `--composer` (the original composer for classical, the original artist for pop/game covers) always; `--arranger` when the arrangement has a known author (cover channel / arranger credit from the video title or description); `--performer` when the pianist is known. Omit roles that don't apply.

`post` does the canned notation fixes: enharmonic respelling toward the key, merging fragmented tied chains, moving clearly out-of-range notes to the correct staff, pedal markings from CC64, and **dynamics from MIDI velocities** — level marks (pp–ff) at changes plus cresc./dim. hairpins where the velocity profile trends steadily. Check `dynamics_preview` in the analyze report first; if the proposed levels look like noise (e.g. constant-velocity synthesized audio), drop `--dynamics-from`.

## 5. Bespoke repair pass (model judgment)

Inspect the cleaned MusicXML and compare against the analyze report:

- Note-type histogram (`grep -o "<type>[a-z0-9]*</type>" | sort | uniq -c`): stray 32nds/64ths in a piece whose rhythm profile is slow are quantization mangling. Chains of tiny tied values that sum to a simple duration are really one note under rubato. Tuplets should be rare-to-absent (the grid is binary); a tuplet explosion means something upstream went wrong.
- Possible triplet regions (from `fast_runs` / IOI reasoning): the binary grid forces genuine triplets/swing onto the nearest 32nd positions — passages that should be tuplets need renotating (or at least flagging).
- Voice separation oddities (overlapping voices, chords split oddly), and the hand split: it's a single pitch threshold, so crossing-hands passages land on the wrong staff.
- **Voices per measure & clef (rule)**: assess the voice count of every measure in each staff. A second voice is only justified where it carries actual notes — if one voice holds all the notes and the other voice is rests-only for the whole measure, delete the rest-only voice and renumber so the measure is single-voice. The pipeline tends to let a second voice linger as full-measure rests in measures after (or between) passages that genuinely needed two voices; those padding rests are clutter, not music. A voice that contains any note in the measure stays, even if it's mostly rests.

Write targeted music21 snippets against specific measures to repair what you're **confident** about; anything uncertain goes in the report instead. This judgment step is the reason cleanup is a skill and not just a script.

## 6. Verify

Structural checks: `.cleaned.musicxml` has the chosen `<fifths>`/`<beats>` values; note-type histogram improved vs the raw conversion; mscore exited 0 for the `.mscz`; originals untouched.

Then the objective check — render the score and compare it to the recording bar by bar:

```bash
.venv/bin/python scripts/transcription_cleanup.py verify \
  'output/<slug>/<slug>.cleaned.musicxml' 'output/<slug>/<slug>.mp3' \
  --output 'output/<slug>/verify.json'
```

Interpret: `median_similarity` ≥ ~0.95 means the score broadly matches; `worst_bars` (with mm:ss timestamps) are where to listen first; `drift_suspects` mark bars whose local alignment stretches — possible barline drift; `repeat_inconsistencies` are bar pairs where the audio repeats but the transcribed pitch classes differ — one of each pair is probably wrong. All of these go into CLEANUP_NOTES, not into automatic fixes (chroma is octave-blind; treat it as a listening guide, not proof).

Optional deep check when the user wants extra confidence (~3x stage-2 time): re-transcribe pitch-shifted audio and cross-check —

```bash
/opt/homebrew/bin/ffmpeg -i '<slug>.wav' -af 'asetrate=44100*1.059463,aresample=44100,atempo=0.943874' shifted_up.wav
.venv/bin/transkun shifted_up.wav alt_up.mid --device cpu
.venv/bin/python scripts/transcription_cleanup.py consensus '<slug>.cleaned.mid' 'alt_up.mid:1'
```

Suspects (notes that vanish under pitch shift) are flagged in the notes, never deleted.

## 7. Write `output/<slug>/CLEANUP_NOTES.md`

Three sections:

1. **Ground truth used** — piece identification and the key/meter/tempo facts applied, with source URLs (or "none found — used statistical analysis").
2. **Changed automatically** — every transform with counts and timestamps (artifact/ghost/duplicate removals, respellings, tie merges, staff moves, pedal marks, meter/key/tempo set, bespoke repairs with measure numbers).
3. **Verify by ear** — each flag with ≈measure + timestamp (measure ≈ `time / (60/bpm × beats-per-bar)`, counting from the trim shift). Lead with the `verify.json` results: worst bars (with their mm:ss), drift suspects, repeat inconsistencies, and any consensus suspects. Then the standing items:
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
