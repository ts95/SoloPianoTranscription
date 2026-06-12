---
name: download-audio
description: Download the audio of a YouTube video into output/<slug>/ as a normalized 44.1 kHz WAV (for transcription) plus an mp3 (for listening). Use when the user gives a YouTube link and wants the audio downloaded (stage 1 of the transcription pipeline).
---

# Download YouTube audio (WAV for Transkun + mp3 for listening)

Input: a YouTube URL. If none was given, ask for one. Sanity-check it looks like a YouTube link (`youtube.com/watch`, `youtu.be/`, `youtube.com/shorts/`); if it's some other site, confirm with the user before proceeding — yt-dlp supports many sites but this project is about YouTube.

YouTube serves lossy audio (opus/m4a). Decode it **once** to WAV — never re-encode to mp3 for the transcription input; a second lossy generation costs the model accuracy. The mp3 exists only for human listening.

```bash
# 1. Best audio → WAV (one lossy generation: YouTube's own encode)
.venv/bin/yt-dlp -x --audio-format wav --restrict-filenames \
  -o 'output/%(title)s/%(title)s.%(ext)s' '<url>'

# 2. Loudness-normalize (linear gain — preserves dynamics/velocities) + 44.1 kHz
scripts/prepare_audio.sh 'output/<slug>/<slug>.wav' 'output/<slug>/<slug>.prepared.wav'
mv 'output/<slug>/<slug>.prepared.wav' 'output/<slug>/<slug>.wav'

# 3. Listening copy
/opt/homebrew/bin/ffmpeg -i 'output/<slug>/<slug>.wav' -codec:a libmp3lame -q:a 0 \
  'output/<slug>/<slug>.mp3'
```

- `--restrict-filenames` produces a safe ASCII slug from the video title; the slug names both the directory and the files for the rest of the pipeline.
- `scripts/prepare_audio.sh` does two-pass EBU R128 loudnorm in **linear** mode (a single static gain — dynamic mode would compress the dynamics and skew the velocities Transkun emits) and resamples to the 44.1 kHz the model expects.

After it finishes, verify both files exist and are non-trivially sized (`ls -lh`), and report the paths. The `.wav` is the transcription input; the `.mp3` is for the user's ears.

## Troubleshooting

- `ffmpeg not found`: ffmpeg must be at `/opt/homebrew/bin/ffmpeg`.
- Age-restricted or members-only videos fail without authentication — tell the user rather than trying workarounds.
- If yt-dlp fails with extraction errors, it may be outdated (YouTube changes frequently): `.venv/bin/pip install -U yt-dlp` and retry once.
- The warning `No supported JavaScript runtime could be found` is harmless as long as the download succeeds. If formats are actually missing, `brew install deno` and retry.
