# SoloPianoTranscription

Pipeline for transcribing solo piano performances from YouTube into editable sheet music: YouTube link → mp3 (yt-dlp) → MIDI (Transkun v2) → MusicXML (`transcription_cleanup.py quantize`) → .mscz (MuseScore 4 CLI, format conversion only). Used for pieces where no published sheet music exists.

## Environment

- Always use the project venv binaries — never global installs:
  - `.venv/bin/python`
  - `.venv/bin/yt-dlp`
  - `.venv/bin/transkun`
- MuseScore CLI path (constant): `/Applications/MuseScore 4.app/Contents/MacOS/mscore`
- ffmpeg is at `/opt/homebrew/bin/ffmpeg` (needed by yt-dlp).
- If `.venv` doesn't exist: `python3.11 -m venv .venv && .venv/bin/pip install transkun yt-dlp music21` (pulls PyTorch, ~2 GB).
- `scripts/transcription_cleanup.py` (run with `.venv/bin/python`) provides `analyze` / `clean` / `quantize` / `post` subcommands used by the pipeline and `cleanup-score` skills.

## Output layout

One directory per piece, named by the slugified video title:

```
output/<slug>/
├── <slug>.mp3        # downloaded audio
├── <slug>.mid        # Transkun transcription (performance timing, unquantized)
├── <slug>.musicxml   # quantized score (interchange format)
├── <slug>.mscz       # native MuseScore 4 file (for direct editing)
├── <slug>.cleaned.*  # cleanup-score products (mid/musicxml/mscz) — originals stay untouched
├── clean_report.json # machine summary of the MIDI clean pass
└── CLEANUP_NOTES.md  # what was changed + what to verify by ear
```

## Pipeline stage commands

```bash
# 1. Download audio (slug comes from --restrict-filenames)
.venv/bin/yt-dlp -x --audio-format mp3 --audio-quality 0 --restrict-filenames \
  -o 'output/%(title)s/%(title)s.%(ext)s' '<url>'

# 2. Audio → MIDI
.venv/bin/transkun 'output/<slug>/<slug>.mp3' 'output/<slug>/<slug>.mid' --device cpu

# 3. MIDI → MusicXML (script quantizer — NEVER MuseScore's MIDI import),
#    then .mscz via mscore (format conversion only).
#    BPM from the user / web ground truth, else an analyze candidate;
#    verify via score_seconds_at_bpm ≈ audio_seconds in the summary.
.venv/bin/python scripts/transcription_cleanup.py quantize \
  'output/<slug>/<slug>.mid' 'output/<slug>/<slug>.musicxml' --bpm <bpm>
MSCORE="/Applications/MuseScore 4.app/Contents/MacOS/mscore"
"$MSCORE" 'output/<slug>/<slug>.musicxml' -o 'output/<slug>/<slug>.mscz'
```

## Skills

- `transcribe` — full pipeline from a YouTube URL; use for "transcribe this video" requests
- `download-audio` — stage 1 only
- `audio-to-midi` — stage 2 only (also works on local audio files the user provides)
- `midi-to-musicxml` — stage 3 only (exports both .musicxml and .mscz)
- `cleanup-score` — post-pipeline cleanup: web ground-truth lookup (key/meter), artifact removal, notation repair, velocity-derived dynamics/hairpins, `CLEANUP_NOTES.md` with verify-by-ear flags. Changes only what's decidable from data; never overwrites originals.

## Notation sanity (reason about the score, don't just convert)

After producing any score, inspect it for statistical outliers — transcription and quantization errors look like values that don't belong in the piece's rhythm profile:

- Build a note-type histogram (`grep -o "<type>[a-z0-9]*</type>" <file>.musicxml | sort | uniq -c`). A handful of 32nds/64ths/128ths in a piece that is overwhelmingly 16ths-and-eighths are almost certainly artifacts (onset jitter, ghost notes, split sustains), not music — find them, and either fix what's clearly decidable (e.g. merge a 32nd+rest pair that sums to the prevailing 16th) or flag them for by-ear review.
- The same applies to rests: isolated tiny rests punched into an otherwise continuous 16th-note texture are quantization gaps (duration snapped down past the next onset), not phrasing.
- Judge outliers in context: a 32nd-note run in one contiguous passage is likely a real ornament/flourish; the same values scattered randomly one-at-a-time through the piece are noise.
- A tuplet explosion, or a histogram dominated by values one "level" off from what the piece sounds like, means the BPM/grid was wrong — requantize rather than patching notes.

## Git

- Commit automatically after every delivered change (new/updated skills, scripts, docs, pipeline fixes) — one commit per delivery with a descriptive message. Don't wait to be asked.
- `output/` and `.venv/` are gitignored; only project sources are versioned.
- When a previously working stage regresses, use `git bisect` with a script that runs the failing conversion (e.g. mscore exit code on a kept test artifact) to find the breaking commit.

## Gotchas

- Transkun expects 44.1 kHz mp3/wav input; the yt-dlp command above produces compatible mp3s. If transcribing user-supplied audio in another format/rate, convert with ffmpeg first.
- Stage 2 takes a few minutes per piece on CPU — run it in the background and don't assume it hung.
- Stages are re-run safe by convention: before running a stage, check whether its output file already exists and is non-empty, and skip it unless the user asked to redo it.
- `mscore` may print Qt warnings to stderr even on success — judge by exit code and whether the output file was written.
- Quote all paths: video-title slugs can still contain characters that need quoting, and the mscore path contains a space.
- **Never import a `.mid` into MuseScore** (CLI or GUI) — its quantization auto-detects its own tempo, ignores the tempo and time-signature meta events, and can lock onto a sub-pulse (e.g. the dotted-eighth of a 3-3-2 groove → 4/3 of the true BPM), wronging every barline and spraying fake tuplets. All MIDI → MusicXML goes through `transcription_cleanup.py quantize --bpm <bpm>`; mscore is only for `.musicxml` → `.mscz`/PDF format conversion.
- The quantize grid stands or falls with the BPM. Prefer the user / web ground truth over statistical candidates, and check the quantize summary: `score_seconds_at_bpm` must be within a few percent of `audio_seconds`.
- music21 `makeMeasures()` does not split notes at barlines — always follow with `makeTies()`, or MuseScore rejects the overfull measures (exit 40).
- zsh does not word-split unquoted variables; don't stash multi-word commands in shell variables.
