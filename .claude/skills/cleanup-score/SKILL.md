---
name: cleanup-score
description: Clean up a transcribed score — remove MIDI transcription artifacts, cross-check key/meter/tempo against web ground truth, engrave with DuET if the score isn't made yet, then write a report flagging what needs human review by ear. Use after the transcribe pipeline, on a piece directory under output/.
---

# Clean up a transcribed score

Input: a piece directory `output/<slug>/` (or any transcription `.mid`). Requires the raw `.mid`; the cleaned MIDI is rebuilt from it. **Never overwrite the originals** (the raw `<slug>.mid`, `<slug>.wav`, `<slug>.mp3`).

Deliverables:
- `<slug>.cleaned.mid` — the faithful, editable "recording" (artifacts removed, trimmed, correct tempo/meter/key meta). This is what DuET engraves from.
- The score as a **single** set `<slug>.musicxml` / `<slug>.mscz` / `<slug>.pdf` (DuET engraving + metadata + harmony pedaling baked into the one file — never a separate "cleaned" vs "pedaled" variant).
- `CLEANUP_NOTES.md` — what was done automatically + the verify-by-ear checklist.

The score is a foundation to finish by hand (dynamics are added manually), not a final edition.

**MIDI-only mode**: if the user asked for just a cleaned MIDI (no sheet music), run steps 1–3 and stop — `<slug>.cleaned.mid` is complete on its own (artifacts removed, trimmed, correct tempo/meter/key meta). Skip the DuET engraving and base `CLEANUP_NOTES.md` on the clean report alone.

Core principle: fix what is decidable from the data (or from published facts about the piece); anything that requires hearing the recording gets **flagged, not changed**.

Tools: `scripts/transcription_cleanup.py` (run with `.venv/bin/python`) for `analyze`/`clean`/`verify`; DuET via `scripts/duet.sh` for the engraving (see the `midi-to-musicxml` skill); MuseScore via `scripts/mscore.sh`.

## 1. Ground-truth lookup (web)

Identify the piece from the slug / video title (composer, work, movement). Web-search for authoritative facts: **key signature, meter, tempo marking, and the composer/arranger/performer credits** (needed for the score header). Good sources: Wikipedia, IMSLP, composer catalogs; for unpublished pieces, the video description/comments or reviews often still state key or meter. Record everything found with source URLs. Finding nothing is fine — analysis is the fallback.

These facts serve two purposes: (a) they set the `<slug>.cleaned.mid` tempo/meter/key meta (step 3), and (b) they cross-check **DuET's own inferred key/meter** — DuET decides the score's key and meter from the model, so if ground truth disagrees with what DuET engraved, flag it prominently (DuET's `report.json`/`review.json` record its key decisions).

## 2. Analyze (statistical second opinion)

```bash
.venv/bin/python scripts/transcription_cleanup.py analyze 'output/<slug>/<slug>.mid'
```

Interpret with musical judgment:

- **Key**: prefer web ground truth; else the top `key_estimates` entry. If ground truth and analysis disagree on a published work, trust ground truth and flag the disagreement.
- **Meter**: prefer ground truth; the strongest `grouping_scores` entry suggests beats per bar.
- **Tempo**: prefer ground truth / the user's word over the statistical candidates — autocorrelation locks onto the dominant *pulse*, which can be a subdivision (2×, half, or 4/3 for dotted grooves).
- **Thresholds**: review the `artifact_candidates`/`ghost_candidates` samples. Be conservative: when a candidate might be a real grace note or ornament, keep it (lower `--vel-ratio` / `--min-dur`) and flag it instead.

## 3. Clean the MIDI

```bash
.venv/bin/python scripts/transcription_cleanup.py clean \
  'output/<slug>/<slug>.mid' 'output/<slug>/<slug>.cleaned.mid' \
  --time-sig '3/4' --key 'D Major' --tempo 78 \
  --report 'output/<slug>/clean_report.json'
```

(Flags per your step-1/2 decisions; `--keep-ghosts` if ghost candidates looked like real notes.) **DuET copies every input note into the score, so this artifact removal is what keeps ghosts/duplicates out of the engraving — it is not optional.** The tempo/key/time-sig meta make the `.cleaned.mid` correct as a standalone deliverable.

## 4. Engrave the score with DuET (skip if `<slug>.musicxml` already exists)

Follow the `midi-to-musicxml` skill: run DuET on `<slug>.cleaned.mid` → `<slug>.musicxml`, set the metadata (title/composer/arranger/performer from step 1), convert to `.mscz`/`.pdf`, and add harmony pedaling. DuET infers the score's own key/meter/tempo and engraves runs, glissandi, and hand assignment — there is no BPM grid to pick and no quantize/post step.

## 5. Verify

Structural checks: mscore exited 0 for the `.mscz`; originals untouched; the score's engraved key/meter (from `report.json`) matches ground truth or is flagged.

**Note-type histogram**: `grep -o "<type>[a-z0-9]*</type>" '<slug>.musicxml' | sort | uniq -c`. A handful of 32nds/64ths/128ths scattered one-at-a-time through an otherwise steady texture are artifacts; the same values in one contiguous run are likely a real flourish. Judge outliers in context.

**Visual inspection (rule)**: export `scripts/mscore.sh '<slug>.mscz' -o '<slug>.pdf'` and Read the PDF (at least first, a busy middle, and final page). Look for what a text check cannot see: floating/doubled marks, pedal lines not under the bass staff, collisions, multi-voice clutter, drone durations that halt the texture, fragmented beaming. Fix what is decidable, re-export, re-inspect; flag the rest in the notes.

Then the objective check — render the score and compare it to the recording bar by bar:

```bash
.venv/bin/python scripts/transcription_cleanup.py verify \
  'output/<slug>/<slug>.musicxml' 'output/<slug>/<slug>.mp3' \
  --output 'output/<slug>/verify.json'
```

Interpret: `median_similarity` ≥ ~0.95 means the score broadly matches; `worst_bars` (with mm:ss) are where to listen first; `drift_suspects` mark bars whose alignment stretches; `repeat_inconsistencies` are bar pairs where the audio repeats but the transcribed pitch classes differ. All of these go into CLEANUP_NOTES, not into automatic fixes (chroma is octave-blind; a listening guide, not proof).

Optional deep check when the user wants extra confidence (~3× stage-2 time): re-transcribe pitch-shifted audio and cross-check —

```bash
/opt/homebrew/bin/ffmpeg -i '<slug>.wav' -af 'asetrate=44100*1.059463,aresample=44100,atempo=0.943874' shifted_up.wav
.venv/bin/transkun shifted_up.wav alt_up.mid --device cpu
.venv/bin/python scripts/transcription_cleanup.py consensus '<slug>.cleaned.mid' 'alt_up.mid:1'
```

Suspects (notes that vanish under pitch shift) are flagged in the notes, never deleted.

## 6. Write `output/<slug>/CLEANUP_NOTES.md`

Three sections:

1. **Ground truth used** — piece identification and the key/meter/tempo + composer/arranger/performer facts applied, with source URLs (or "none found — used statistical analysis"). Note where DuET's engraved key/meter agrees or disagrees with ground truth.
2. **Changed automatically** — every transform with counts: artifact/ghost/duplicate removals (from `clean_report.json`), the DuET engraving version (from `report.json`), metadata set, harmony-pedal measures.
3. **Verify by ear** — each flag with ≈measure + timestamp. Lead with the `verify.json` results (worst bars with mm:ss, drift suspects, repeat inconsistencies) and any consensus suspects. Then DuET's `review.json` items (key changes, borrowed chords vs modulation, low-margin spellings, runs that may be tuplets, notes written away from where they were played). Then the standing items:
   - verify pitches against the recording (the model cannot hear; wrong/missed notes are invisible in the data)
   - the downbeat anchor: if the piece opens with a pickup, every barline is shifted
   - **dynamics are absent by design** — add them by hand from the recording (DuET writes none)
   - dense clusters (possible pedal smear) to thin by ear
   - fast runs DuET engraved as grace notes / glissandi — confirm they're ornaments, not missed notes

## 7. Report in chat

Artifact paths plus the top human-attention items, so the user knows where to spend their listening time.
