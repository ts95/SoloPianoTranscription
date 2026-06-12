---
name: transcribe
description: Full pipeline - transcribe a solo piano YouTube video to sheet music. Takes a YouTube URL, downloads the audio, transcribes it to MIDI with Transkun v2, and converts the MIDI to MusicXML. Use when the user gives a YouTube link and wants sheet music / a transcription.
---

# Transcribe a YouTube solo piano video to MusicXML

Input: a YouTube URL (in the skill arguments or the user's message). If no URL was given, ask for one.

Run the three stages below in order. **Before each stage, check whether its output file already exists and is non-empty — if so, skip the stage** (unless the user asked to redo it). This makes re-runs after a failure cheap.

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

## Stage 3 — MIDI → MusicXML + MuseScore file

Follow the `midi-to-musicxml` skill (exports both formats). **Never feed the `.mid` to MuseScore** — its import quantization is unreliable (auto-detects its own tempo, can lock onto the wrong pulse). Quantize with the project script, then use mscore only for the `.musicxml` → `.mscz` format conversion:

```bash
# BPM: prefer the user / web ground truth (original-song BPM for covers);
# else an analyze candidate — see the midi-to-musicxml skill for validation.
.venv/bin/python scripts/transcription_cleanup.py quantize \
  'output/<slug>/<slug>.mid' 'output/<slug>/<slug>.musicxml' --bpm <bpm>
MSCORE="/Applications/MuseScore 4.app/Contents/MacOS/mscore"
"$MSCORE" 'output/<slug>/<slug>.musicxml' -o 'output/<slug>/<slug>.mscz'
```

Check the quantize summary: `score_seconds_at_bpm` must be within a few percent of `audio_seconds`, otherwise the BPM is wrong — try another candidate.

## Wrap up

Report all artifact paths (mp3, mid, musicxml, mscz) and remind the user:

- Suggest running `/cleanup-score output/<slug>/` next — it fixes key/meter/tempo and transcription artifacts automatically and produces a verify-by-ear checklist.
- The `.mid` can be auditioned to check transcription quality before investing cleanup time.
- The `.musicxml` is for other notation software; the `.mscz` opens directly in MuseScore 4.
