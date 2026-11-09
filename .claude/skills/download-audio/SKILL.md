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
- **`Sign in to confirm you're not a bot` / `Requested format is not available` / only images available** — YouTube now routinely throws two separate barriers; clearing them needs **both** of the following (confirm each with the user first — one is a system install, the other reads their browser session):
  - **A JS runtime** to solve the signature / "n challenge" — without it yt-dlp falls back to image-only formats and the audio download fails. `brew install deno` (the warning `No supported JavaScript runtime could be found` is the tell). deno is on the default `--js-runtimes` list, so no extra flag is needed once it's installed; just ensure `/opt/homebrew/bin` is on `PATH`.
  - **Browser cookies** to clear the bot check: add `--cookies-from-browser <browser>` (e.g. `chrome`, `safari`) to the `yt-dlp` command — it pulls the user's logged-in YouTube session. Chrome may prompt for Keychain access; Safari may need the terminal to have Full Disk Access. Ask which browser they're signed into YouTube on.
  - These often co-occur: cookies get you past the bot check and into the player API, then the signature solve still fails without deno. Apply both. (Updating yt-dlp alone will *not* fix either.)
