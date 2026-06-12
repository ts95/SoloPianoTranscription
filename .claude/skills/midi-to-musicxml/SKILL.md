---
name: midi-to-musicxml
description: Convert a MIDI file to MusicXML and a native MuseScore 4 file (.mscz) by quantizing with the project script (never MuseScore's MIDI import). Use for stage 3 of the transcription pipeline, or whenever the user wants a .mid as editable sheet music.
---

# Convert MIDI to MusicXML and MuseScore (.mscz)

Input: a path to a `.mid` file. Pipeline convention: `output/<slug>/<slug>.mid` → `output/<slug>/<slug>.musicxml` + `output/<slug>/<slug>.mscz`.

**Never feed a `.mid` to MuseScore.** Its import quantization auto-detects its own tempo — ignoring the tempo and time-signature meta events — and can lock onto a sub-pulse (e.g. the dotted-eighth of a 3-3-2 groove, 4/3 of the true BPM), which wrongs every barline and sprays fake tuplets. Quantization always goes through `scripts/transcription_cleanup.py quantize`; MuseScore is used **only** for the `.musicxml` → `.mscz` format conversion.

By default export **both** formats — `.mscz` for editing directly in MuseScore 4, `.musicxml` for interchange with other notation software. If the user asked for only one, export just that one.

## 1. Pick the BPM (the grid depends on it)

In order of preference:

1. The user said it, or web ground truth states it (original-song BPM for covers — see the `cleanup-score` skill's lookup step).
2. `analyze` candidates as fallback:

```bash
.venv/bin/python scripts/transcription_cleanup.py analyze '<input>.mid'
```

Treat `bpm_candidates` with suspicion: autocorrelation locks onto the dominant *pulse*, which can be a subdivision of the real beat (2×, half, or 4/3 for dotted grooves). Sanity-check against the piece's character, and verify after quantizing (below).

## 2. Quantize to MusicXML

```bash
.venv/bin/python scripts/transcription_cleanup.py quantize \
  '<input>.mid' '<output>.musicxml' --bpm <bpm> \
  --title '<piece>' --composer '<original composer/artist>'
```

Add `--key 'D major'` / `--time-sig '4/4'` when known. **Metadata rule**: always pass `--title` and `--composer`; add `--arranger` (cover/arrangement author) and `--performer` (pianist) when known — generated scores must identify the piece in their header. In the JSON summary, `score_seconds_at_bpm` must be within a few percent of `audio_seconds` — a big mismatch means the BPM is wrong; pick another candidate.

**Pedal rule**: the score must reflect the MIDI's actual pedaling. If the `.mid` carries CC64 events (Transkun transcriptions do), engrave them:

```bash
.venv/bin/python scripts/transcription_cleanup.py post \
  '<output>.musicxml' '<output>.musicxml' --pedal-from '<input>.mid'
```

(Without `--key`/`--time-sig` this is pedal-only — no re-bar, no respelling.) Check the summary: `pedal_marks` should be close to `analyze`'s `pedal_cc64_regions` count; `0` plus a `pedal_note` means the regions could not be mapped — deliver anyway but say the pedaling is missing. Skip this step only when the MIDI genuinely has no CC64 (then there is no pedaling to reflect).

## 3. Convert to .mscz with MuseScore (format conversion only)

```bash
MSCORE="/Applications/MuseScore 4.app/Contents/MacOS/mscore"
"$MSCORE" '<output>.musicxml' -o '<output>.mscz'
```

- `mscore` often prints Qt/plugin warnings to stderr even when it succeeds. Judge success by the exit code and by the output file existing and being non-empty.
- Use `.musicxml` (uncompressed) rather than `.mxl` so the result is diffable and inspectable.

Report both output paths and suggest:

- running `/cleanup-score` for the full treatment (artifact removal, ground-truth key/meter, pedal, dynamics, verify-by-ear report);
- opening the `.mscz` in MuseScore 4 for by-ear cleanup (durations are conservatively short — capped at the next onset — and the hand split is a single pitch threshold).

## Fallback: no MuseScore

If `mscore` fails or is unavailable, deliver the `.musicxml` alone (the quantizer is pure music21 and doesn't need MuseScore) and say the `.mscz` could not be produced.
