---
name: download-audio
description: Download the audio of a YouTube video as mp3 into output/<slug>/. Use when the user gives a YouTube link and wants just the audio downloaded (stage 1 of the transcription pipeline).
---

# Download YouTube audio as mp3

Input: a YouTube URL. If none was given, ask for one. Sanity-check it looks like a YouTube link (`youtube.com/watch`, `youtu.be/`, `youtube.com/shorts/`); if it's some other site, confirm with the user before proceeding — yt-dlp supports many sites but this project is about YouTube.

```bash
.venv/bin/yt-dlp -x --audio-format mp3 --audio-quality 0 --restrict-filenames \
  -o 'output/%(title)s/%(title)s.%(ext)s' '<url>'
```

- `-x --audio-format mp3` extracts audio only and converts to mp3 via ffmpeg.
- `--audio-quality 0` = best quality.
- `--restrict-filenames` produces a safe ASCII slug from the video title; the slug names both the directory and the files for the rest of the pipeline.

After it finishes, find the actual output path (yt-dlp prints it; or `ls output/`) and report it. Verify the file exists and is non-trivially sized (`ls -lh`).

## Troubleshooting

- `ffmpeg not found`: ffmpeg must be on PATH (`/opt/homebrew/bin/ffmpeg`).
- Age-restricted or members-only videos fail without authentication — tell the user rather than trying workarounds.
- If yt-dlp fails with extraction errors, it may be outdated (YouTube changes frequently): `.venv/bin/pip install -U yt-dlp` and retry once.
- The warning `No supported JavaScript runtime could be found` is harmless as long as the download succeeds. If formats are actually missing, `brew install deno` and retry.
