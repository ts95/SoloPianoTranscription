# Solo Piano Transcription

Transcribe solo piano performances from YouTube into editable sheet music, for pieces where no published sheet music exists.

```
YouTube link
    │  yt-dlp + prepare_audio.sh (decode once, linear loudness-normalize, 44.1 kHz)
    ▼
output/<slug>/<slug>.wav  (+ <slug>.mp3 listening copy)
    │  Transkun v2 (automatic piano transcription)
    ▼
output/<slug>/<slug>.mid
    │  transcription_cleanup.py quantize (fixed-BPM grid quantization, music21)
    │  MuseScore 4 CLI (.musicxml → .mscz format conversion only)
    ▼
output/<slug>/<slug>.musicxml + <slug>.mscz
    │  cleanup-score (optional: AI cleanup + human review report)
    ▼
output/<slug>/<slug>.cleaned.musicxml + .cleaned.mscz + CLEANUP_NOTES.md
```

Two design rules learned the hard way:

- **MuseScore never imports MIDI.** Its import quantization auto-detects its own tempo (ignoring the tempo/time-signature meta events) and can lock onto a sub-pulse — e.g. the dotted-eighth of a 3-3-2 groove, 4/3 of the true BPM — which wrongs every barline and sprays fake tuplets. All quantization happens in `scripts/transcription_cleanup.py quantize` at a caller-chosen BPM; MuseScore only converts formats.
- **Audio is decoded once.** YouTube serves lossy audio; re-encoding it to mp3 before transcription adds a second lossy generation. The transcription input is a WAV with linear (non-dynamic) loudness normalization, so the model sees a consistent level without compressed dynamics.

## Prerequisites

- macOS
- [ffmpeg](https://ffmpeg.org/) — `brew install ffmpeg`
- [MuseScore 4](https://musescore.org/) installed in `/Applications` (its `mscore` CLI converts `.musicxml` to `.mscz`)
- Python 3.11

## Setup

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install transkun yt-dlp music21
```

Note: `transkun` depends on PyTorch, so the install downloads roughly 2 GB. The Transkun v2 model weights ship with the pip package — no separate download needed.

## Usage

The easiest way is via Claude Code from this directory:

```
/transcribe https://www.youtube.com/watch?v=...
```

This runs all three stages and leaves the artifacts in `output/<slug>/`.

Each stage is also available as its own skill, useful for re-running a single step:

- `/download-audio <youtube-url>` — download + prepare audio (normalized 44.1 kHz wav for transcription, mp3 for listening)
- `/audio-to-midi <audio-file>` — transcribe audio to MIDI with Transkun
- `/midi-to-musicxml <midi-file>` — quantize MIDI to MusicXML at a chosen BPM and convert to native MuseScore (.mscz)
- `/cleanup-score output/<slug>/` — AI cleanup of a transcribed score: looks up the piece's real key/meter/tempo online, removes transcription artifacts (ghost notes at piano-partial intervals, duplicates — pedal- and harmony-aware, so in-key consonant notes are flagged rather than deleted), re-quantizes onto the verified BPM grid, repairs notation (key-aware and melodic-direction-aware enharmonic spelling, modulation detection, staff assignment, pedal marks), derives dynamics and cresc./dim. hairpins from MIDI velocities, and writes `CLEANUP_NOTES.md` flagging everything that needs verification by ear

### Running the stages manually

```bash
# 1. Download + prepare audio (decode once to wav, normalize, 44.1 kHz; mp3 for listening)
.venv/bin/yt-dlp -x --audio-format wav --restrict-filenames \
  -o 'output/%(title)s/%(title)s.%(ext)s' '<youtube-url>'
scripts/prepare_audio.sh output/<slug>/<slug>.wav output/<slug>/<slug>.prepared.wav
mv output/<slug>/<slug>.prepared.wav output/<slug>/<slug>.wav
ffmpeg -i output/<slug>/<slug>.wav -codec:a libmp3lame -q:a 0 output/<slug>/<slug>.mp3

# 2. Transcribe to MIDI (takes a few minutes on CPU)
.venv/bin/transkun output/<slug>/<slug>.wav output/<slug>/<slug>.mid --device cpu

# 3. Quantize to MusicXML (BPM from ground truth or analysis), then convert to .mscz
.venv/bin/python scripts/transcription_cleanup.py quantize \
  output/<slug>/<slug>.mid output/<slug>/<slug>.musicxml --bpm <bpm>
MSCORE="/Applications/MuseScore 4.app/Contents/MacOS/mscore"
"$MSCORE" output/<slug>/<slug>.musicxml -o output/<slug>/<slug>.mscz
```

`transcription_cleanup.py` also provides `analyze` (read-only JSON report: key/meter/tempo estimates, artifact candidates, rubato, fast runs) and `clean`/`post` (the cleanup-score machinery).

## Limitations and notes

- Transkun is trained on **solo piano**. Recordings with other instruments, vocals, or heavy room noise will transcribe poorly.
- The MIDI Transkun produces has **performance timing** (exactly as played, unquantized). Quantization onto a fixed BPM grid is deliberate and conservative: durations are capped at the next onset (pedal marks carry the sustain), and the grid is binary (real triplets/swing get flagged for the ear). The `cleanup-score` skill handles the data-decidable part; what remains for a human ear is verifying pitches against the recording, the downbeat/pickup anchor, rubato barlines, tuplet decisions, ornaments, and dynamics/phrasing — listed per piece in `CLEANUP_NOTES.md`.
- Transcription runs on CPU by default; expect a few minutes per piece.
- Only transcribe recordings for personal study/use, and respect the rights of performers and composers.

## References

- Transkun: https://github.com/Yujia-Yan/Transkun
- yt-dlp: https://github.com/yt-dlp/yt-dlp
- MuseScore CLI: https://handbook.musescore.org/appendix/command-line-usage
