---
name: transcribe
description: Full pipeline - transcribe a solo piano YouTube video to sheet music. Takes a YouTube URL, downloads the audio, transcribes it to MIDI with Transkun v2, and converts the MIDI to MusicXML. Use when the user gives a YouTube link and wants sheet music / a transcription.
---

# Transcribe a YouTube solo piano video to MusicXML

Input: a YouTube URL (in the skill arguments or the user's message). If no URL was given, ask for one.

**Before stage 1, ask the user** whether to diverge from the legato default (rule): legato fills each note to the next onset — clean engraving, pedal carries sustain; opting out (`quantize --no-legato-fill`) keeps performed lengths so detached/staccato playing stays visible and can be marked. Then run the three stages below in order. **Before each stage, check whether its output file already exists and is non-empty — if so, skip the stage** (unless the user asked to redo it). This makes re-runs after a failure cheap.

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

## Stage 3 — MIDI → score (the full cleanup flow)

Follow the `cleanup-score` skill start to finish — it IS stage 3. "Run the pipeline" means the delivered score, not a raw conversion: ground-truth lookup (key/BPM), `clean`, the **grid bake-off** (build `--refine` and `--from-midi` candidates, compare `onset_grid_fit`, check `weak_windows`/`level_hop_suspects`, hybrid-repair a winner with flagged windows), `quantize --beats` → `post` → `clean_musicxml` → `.mscz` → harmony pedaling → regenerated `.musicxml`/`.pdf` from the pedaled `.mscz`, then `verify`, PDF visual inspection, and `CLEANUP_NOTES.md`.

Non-negotiables carried by that skill: never feed a `.mid` to MuseScore; the lint verdict must be "ok" before delivering; every final `.mscz` gets a visually-inspected PDF; a real performance's CC64 stays in the cleaned MIDI.

(For a quick single-file conversion outside the pipeline, the `midi-to-musicxml` skill still covers the minimal path.)

## Wrap up

Report all artifact paths (mp3, cleaned.mid, musicxml, mscz, pdf) plus the top verify-by-ear items from `CLEANUP_NOTES.md`, so the user knows where to spend their listening time. The `.musicxml` is for other notation software; the `.mscz` opens directly in MuseScore 4.
