# Solo Piano Transcription

Transcribe solo piano performances from YouTube into editable sheet music, for pieces where no published sheet music exists.

The pipeline has three stages:

```
YouTube link
    │  yt-dlp (audio-only download)
    ▼
output/<slug>/<slug>.mp3
    │  Transkun v2 (automatic piano transcription)
    ▼
output/<slug>/<slug>.mid
    │  MuseScore 4 CLI (notation import + quantization)
    ▼
output/<slug>/<slug>.musicxml + <slug>.mscz
    │  cleanup-score (optional: AI cleanup + human review report)
    ▼
output/<slug>/<slug>.cleaned.musicxml + .cleaned.mscz + CLEANUP_NOTES.md
```

## Prerequisites

- macOS
- [ffmpeg](https://ffmpeg.org/) — `brew install ffmpeg` (required by yt-dlp for audio extraction)
- [MuseScore 4](https://musescore.org/) installed in `/Applications` (its `mscore` CLI does the MIDI → MusicXML conversion)
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

- `/download-audio <youtube-url>` — download audio as mp3
- `/audio-to-midi <audio-file>` — transcribe audio to MIDI with Transkun
- `/midi-to-musicxml <midi-file>` — convert MIDI to MusicXML and native MuseScore (.mscz) files
- `/cleanup-score output/<slug>/` — AI cleanup of a transcribed score: looks up the piece's real key/meter online, removes transcription artifacts (ghost notes, duplicates), fixes meter/key/tempo, repairs notation (enharmonic spelling, fragmented ties, staff assignment, pedal marks), derives dynamics and cresc./dim. hairpins from MIDI velocities, and writes `CLEANUP_NOTES.md` flagging everything that needs verification by ear

### Running the stages manually

```bash
# 1. Download audio
.venv/bin/yt-dlp -x --audio-format mp3 --audio-quality 0 --restrict-filenames \
  -o 'output/%(title)s/%(title)s.%(ext)s' '<youtube-url>'

# 2. Transcribe to MIDI (takes a few minutes on CPU)
.venv/bin/transkun output/<slug>/<slug>.mp3 output/<slug>/<slug>.mid --device cpu

# 3. Convert to MusicXML + native MuseScore file
MSCORE="/Applications/MuseScore 4.app/Contents/MacOS/mscore"
"$MSCORE" output/<slug>/<slug>.mid -o output/<slug>/<slug>.musicxml
"$MSCORE" output/<slug>/<slug>.mid -o output/<slug>/<slug>.mscz
```

## Limitations and notes

- Transkun is trained on **solo piano**. Recordings with other instruments, vocals, or heavy room noise will transcribe poorly.
- The MIDI Transkun produces has **performance timing** (exactly as played, unquantized). MuseScore quantizes on import, but the resulting MusicXML still needs cleanup. The `cleanup-score` skill handles the data-decidable part (key, meter, tempo, artifact notes, spelling, ties, staff assignment, pedal); what remains for a human ear is verifying pitches against the recording, rubato barlines, tuplet decisions, ornaments, and dynamics/phrasing — listed per piece in `CLEANUP_NOTES.md`.
- Transcription runs on CPU by default; expect a few minutes per piece.
- Only transcribe recordings for personal study/use, and respect the rights of performers and composers.

## References

- Transkun: https://github.com/Yujia-Yan/Transkun
- yt-dlp: https://github.com/yt-dlp/yt-dlp
- MuseScore CLI: https://handbook.musescore.org/appendix/command-line-usage
