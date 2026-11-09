---
name: transcribe
description: Full pipeline - transcribe a solo piano YouTube video to sheet music. Takes a YouTube URL, downloads the audio, transcribes it to MIDI with Transkun v2, cleans the MIDI, and engraves it to a readable MusicXML score + MuseScore file with DuET. Use when the user gives a YouTube link and wants sheet music / a transcription.
---

# Transcribe a YouTube solo piano video to an engraved score

Input: a YouTube URL (in the skill arguments or the user's message). If no URL was given, ask for one.

Run the stages below in order. **Before each stage, check whether its output file already exists and is non-empty — if so, skip the stage** (unless the user asked to redo it). This makes re-runs after a failure cheap.

## Stage 1 — Download audio

Follow the `download-audio` skill (WAV for transcription, mp3 for listening — never feed a re-encoded mp3 to Transkun):

```bash
.venv/bin/yt-dlp -x --audio-format wav --restrict-filenames \
  -o 'output/%(title)s/%(title)s.%(ext)s' '<url>'
scripts/prepare_audio.sh 'output/<slug>/<slug>.wav' 'output/<slug>/<slug>.prepared.wav'
mv 'output/<slug>/<slug>.prepared.wav' 'output/<slug>/<slug>.wav'
/opt/homebrew/bin/ffmpeg -i 'output/<slug>/<slug>.wav' -codec:a libmp3lame -q:a 0 \
  'output/<slug>/<slug>.mp3'
```

The wav path determines `<slug>` for the next stages.

## Stage 2 — Audio → MIDI

Follow the `audio-to-midi` skill:

```bash
.venv/bin/transkun 'output/<slug>/<slug>.wav' 'output/<slug>/<slug>.mid' --device cpu
```

This takes a few minutes on CPU — run it in the background and wait for it; don't assume it hung.

## Stage 3 — Clean the MIDI (ground truth + artifact removal)

Follow the `cleanup-score` skill, steps 1–3: web ground-truth lookup (key/meter/tempo + composer/arranger/performer credits), `analyze` for a statistical second opinion, then `clean` to strip artifacts into `<slug>.cleaned.mid`. **Artifact removal is not optional** — DuET copies every input note into the score, so ghosts/duplicates removed here never reach the engraving.

## Stage 4 — Engrave the score with DuET

Follow the `midi-to-musicxml` skill: run DuET on `<slug>.cleaned.mid` → `<slug>.musicxml`, set the metadata (title/composer/arranger/performer from stage 3), convert to `.mscz`/`.pdf`, and add harmony pedaling. DuET infers the score's own key/meter/tempo and engraves runs, glissandi, and hand assignment — there is no BPM grid to pick.

**Visual inspection (rule)**: Read the PDF (at least first, a busy middle, and final page) and look for obvious engraving issues — floating/doubled marks, pedal not under the bass staff, collisions, voice clutter, rest spray, drone durations. Fix what is decidable, re-export, re-inspect; flag the rest.

## Wrap up

Report all artifact paths (mp3, mid, cleaned.mid, musicxml, mscz, pdf) and:

- Suggest running `/cleanup-score output/<slug>/` next — it runs the `verify` pass (score-vs-recording chroma) and writes `CLEANUP_NOTES.md` with a verify-by-ear checklist, including DuET's `review.json` items.
- The `.cleaned.mid` can be auditioned to check transcription quality.
- The `.musicxml` is for other notation software; the `.mscz` opens directly in MuseScore 4.
- **Dynamics are not engraved** — the user adds them by hand from the recording.
