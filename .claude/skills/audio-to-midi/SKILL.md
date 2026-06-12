---
name: audio-to-midi
description: Transcribe a solo piano audio file (mp3/wav) to MIDI using Transkun v2. Use for stage 2 of the transcription pipeline, or when the user has a local piano recording they want as MIDI.
---

# Transcribe piano audio to MIDI with Transkun v2

Input: a path to an audio file (wav preferred; mp3 works). Pipeline convention: `output/<slug>/<slug>.wav` → `output/<slug>/<slug>.mid`. For a user-supplied file outside `output/`, write the `.mid` next to the source file.

```bash
.venv/bin/transkun '<input-audio>' '<output>.mid' --device cpu
```

- Transkun expects 44.1 kHz audio. The pipeline `.wav` (from `download-audio`) is already prepared. For user-supplied audio in any format/rate, run it through the normalizer first — it also applies linear loudness normalization, which keeps velocities in the model's comfortable range:
  `scripts/prepare_audio.sh '<input>' '<input>-prepared.wav'`
- Avoid feeding lossy re-encodes when a better source exists (e.g. don't convert flac/wav to mp3 first — each lossy generation costs accuracy).
- Transcription takes a few minutes per piece on CPU. Run the command in the background and wait for completion — slow is normal, don't kill it prematurely.
- The v2 model weights ship with the pip package; no flags needed to select them.

Afterwards verify the `.mid` exists and is non-empty (`ls -lh`), and report the path.

## Quality expectations

Transkun is trained on solo piano. Warn the user that results degrade with: other instruments or vocals in the mix, heavy reverb/noise, or low-bitrate audio. The output MIDI has performance timing (unquantized) — that's expected; quantization happens at the MusicXML stage.

## Troubleshooting

- `transkun: command not found` → venv missing or incomplete: `python3.11 -m venv .venv && .venv/bin/pip install transkun yt-dlp`.
- Out-of-memory or very long files: split the audio with ffmpeg and transcribe segments, or pass `--segmentSize`/`--segmentHopSize` (see `transkun --help`).
