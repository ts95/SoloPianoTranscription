---
name: transcribe
description: Full pipeline - transcribe a solo piano YouTube video to sheet music. Takes a YouTube URL, downloads the audio, transcribes it to MIDI with Transkun v2, and converts the MIDI to MusicXML. Use when the user gives a YouTube link and wants sheet music / a transcription.
---

# Transcribe a YouTube solo piano video to MusicXML

Input: a YouTube URL (in the skill arguments or the user's message). If no URL was given, ask for one.

Run the three stages below in order. **Before each stage, check whether its output file already exists and is non-empty — if so, skip the stage** (unless the user asked to redo it). This makes re-runs after a failure cheap.

## Stage 1 — Download audio

Follow the `download-audio` skill:

```bash
.venv/bin/yt-dlp -x --audio-format mp3 --audio-quality 0 --restrict-filenames \
  -o 'output/%(title)s/%(title)s.%(ext)s' '<url>'
```

Note the resulting mp3 path; it determines `<slug>` for the next stages.

## Stage 2 — Audio → MIDI

Follow the `audio-to-midi` skill:

```bash
.venv/bin/transkun 'output/<slug>/<slug>.mp3' 'output/<slug>/<slug>.mid' --device cpu
```

This takes a few minutes on CPU — run it in the background and wait for it; don't assume it hung.

## Stage 3 — MIDI → MusicXML + MuseScore file

Follow the `midi-to-musicxml` skill (exports both formats):

```bash
MSCORE="/Applications/MuseScore 4.app/Contents/MacOS/mscore"
"$MSCORE" 'output/<slug>/<slug>.mid' -o 'output/<slug>/<slug>.musicxml'
"$MSCORE" 'output/<slug>/<slug>.mid' -o 'output/<slug>/<slug>.mscz'
```

## Wrap up

Report all artifact paths (mp3, mid, musicxml, mscz) and remind the user:

- Suggest running `/cleanup-score output/<slug>/` next — it fixes key/meter/tempo and transcription artifacts automatically and produces a verify-by-ear checklist.
- The `.mid` can be auditioned to check transcription quality before investing cleanup time.
- The `.musicxml` is for other notation software; the `.mscz` opens directly in MuseScore 4.
