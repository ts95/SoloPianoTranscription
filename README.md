# Solo Piano Transcription

Transcribe solo piano performances from YouTube into editable sheet music, for pieces where no published sheet music exists.

> **What this produces is a foundation, not a finished score.** The engraved
> output is a *starting point* that does the mechanical, time-consuming part of
> transcription for you — it is **not** a performance-ready edition. Converting a
> performance to notation is fundamentally lossy and imperfect (see
> [§ Limitations](#limitations-the-score-is-a-foundation)), so the result will
> contain wrong/missed notes, approximate rhythms, and rough voicing, pedaling,
> and dynamics. **The rest is expected to be finished by hand** in MuseScore,
> guided by `CLEANUP_NOTES.md` and the recording. The goal is to get you to ~80%
> in minutes instead of hours, not to hand you a final score.

```
YouTube link
    │  yt-dlp + prepare_audio.sh (decode once, linear loudness-normalize, 44.1 kHz)
    ▼
output/<slug>/<slug>.wav  (+ <slug>.mp3 listening copy)
    │  Transkun v2 (automatic piano transcription)
    ▼
output/<slug>/<slug>.mid          ← raw transcription (the faithful "recording")
    │  cleanup-score: clean the MIDI, quantize (music21; fixed-BPM grid, or a
    │  beat-tracked grid from librosa when the performance has rubato), engrave
    │  notation (spelling, ties, clef changes, velocity dynamics), add harmony-
    │  aware pedaling, clean the MusicXML, render via MuseScore 4 CLI
    ▼
output/<slug>/
    ├── <slug>.cleaned.mid                       ← cleaned MIDI (the editable "recording")
    ├── <slug>.mscz / .musicxml / .pdf           ← THE score foundation (one deliverable)
    └── CLEANUP_NOTES.md                         ← what to finish by hand, by ear
```

The two deliverables are the **cleaned MIDI** (a faithful, expressive capture of the
performance — play it back and it sounds like the recording) and the **score** (one
`.mscz`/`.musicxml`/`.pdf`, the readable-but-imperfect foundation you hand-finish).

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
pip install transkun yt-dlp music21 'llvmlite==0.42.0' 'numba==0.59.1' librosa
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
- `/cleanup-score output/<slug>/` — the full MIDI → score step. Looks up the piece's real key/meter/tempo online, removes transcription artifacts (ghost notes at piano-partial intervals, duplicates — pedal- and harmony-aware, so in-key consonant notes are flagged rather than deleted), re-quantizes onto the verified BPM grid, repairs notation (key-aware enharmonic spelling, modulation detection, staff assignment, **treble-clef switches for sustained high left-hand passages**, **whole-note bass under sustained pedal** instead of clipped notes + rests), adds **harmony-aware pedaling** (one legato pedal per bar, re-pedalled where the bass harmony changes — derived from the engraved harmony, not the transcriber's coarse binary CC64), derives dynamics and cresc./dim. hairpins from MIDI velocities, renders and compares bar-by-bar against the recording (chroma DTW — worst bars, barline drift, and repeat inconsistencies become listening priorities), and writes `CLEANUP_NOTES.md` flagging everything to finish by ear. Produces one score deliverable (`.mscz`/`.musicxml`/`.pdf`). Can also stop at the cleaned `.mid` if that's all you want

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

# 3. MIDI → score. Clean the MIDI, quantize at a chosen BPM, engrave notation,
#    add harmony-aware pedaling, render. (Usually just run /cleanup-score, which
#    also does the web ground-truth lookup, rubato handling, and the report.)
.venv/bin/python scripts/transcription_cleanup.py clean \
  output/<slug>/<slug>.mid output/<slug>/<slug>.cleaned.mid --time-sig <ts> --key '<key>'
.venv/bin/python scripts/transcription_cleanup.py quantize \
  output/<slug>/<slug>.cleaned.mid output/<slug>/<slug>.tmp.musicxml --bpm <bpm> \
  --key '<key>' --time-sig <ts> --title '<title>' --composer '<composer>'
.venv/bin/python scripts/transcription_cleanup.py post \
  output/<slug>/<slug>.tmp.musicxml output/<slug>/<slug>.musicxml \
  --key '<key>' --time-sig <ts> --dynamics-from output/<slug>/<slug>.cleaned.mid
rm output/<slug>/<slug>.tmp.musicxml
.venv/bin/python scripts/clean_musicxml.py \
  output/<slug>/<slug>.musicxml -o output/<slug>/<slug>.musicxml --source generated
MSCORE="/Applications/MuseScore 4.app/Contents/MacOS/mscore"
"$MSCORE" output/<slug>/<slug>.musicxml -o output/<slug>/<slug>.mscz
.venv/bin/python scripts/apply_harmony_pedal.py output/<slug>/<slug>.mscz   # pedal from harmony, not CC64
"$MSCORE" output/<slug>/<slug>.mscz -o output/<slug>/<slug>.musicxml        # regenerate so all formats agree
"$MSCORE" output/<slug>/<slug>.mscz -o output/<slug>/<slug>.pdf
```

`transcription_cleanup.py` also provides `analyze` (read-only JSON report: key/meter/tempo estimates, artifact candidates, rubato, fast runs), `beats` (beat tracking seeded with a known BPM — librosa on the recording, or `--from-midi` to DP-track the transcription's own onsets, which follows deep ritardandi the audio tracker cannot, or `--refine` to lock a fixed grid to the hinted tempo and smoothly refine it to the onsets — best for steady syncopated grooves that mislead both trackers), `verify` (render + per-bar chroma comparison against the recording), `consensus` (cross-check against pitch-shifted re-transcriptions), and `clean`/`post` (the cleanup-score machinery).

## Limitations: the score is a foundation

**The engraved score is a foundation to finish by hand, not a final deliverable.**
MIDI-to-notation is an open research problem and a fundamentally lossy projection
(see [docs/WHY_MIDI_TO_SCORE_IS_HARD.md](docs/WHY_MIDI_TO_SCORE_IS_HARD.md)) — even
state-of-the-art systems produce scores their own authors call "far from
satisfactory." This pipeline does the mechanical 80%: a correct-meter, correct-key,
readably-quantized, pedalled, two-staff score with dynamics and metadata. It does
**not** produce a finished edition. Expect to fix, by hand in MuseScore:

- **Wrong and missing notes.** The transcriber mishears notes, especially in dense
  or fast passages; the pipeline cannot see what it cannot hear. `CLEANUP_NOTES.md`
  lists the bars whose audio least matches the score (your first listening pass),
  but pitch errors elsewhere remain possible.
- **Rhythm and barlines** under rubato — the grid is a best fit, not ground truth;
  some figures want re-grouping, and barlines may drift against the performance.
- **Voicing, articulation, ornaments, and the fine layout** — voice splitting,
  staccato/slur/accent marks, trills written out as fast runs, and beaming are
  approximate or absent.
- **Pedaling and dynamics** are derived (harmony for pedal, MIDI velocity for
  dynamics) and are sensible defaults to refine, not interpretive decisions.

The companion **cleaned MIDI** is the faithful capture — if you want it to *sound*
like the performance, use the MIDI; the score is *instructions to a future
performer* that you complete. `CLEANUP_NOTES.md` is the hand-off: it records what
was decided automatically and the prioritized list of what to verify by ear.

## Other notes

- Transkun is trained on **solo piano**. Recordings with other instruments, vocals, or heavy room noise will transcribe poorly.
- The MIDI Transkun produces has **performance timing** (exactly as played, unquantized). Quantization is deliberate and conservative — a fixed BPM grid for steady performances, a beat-tracked grid (librosa, seeded with the piece's known BPM, refined to MIDI onsets) when there's rubato, with downbeat/pickup inference from bass/harmony/agogic cues: each beat picks its own subdivision (genuine triplets become real tuplets; swing is detected and notated straight with a Swing direction), hands are assigned by a cost model that handles crossings, the bass staff switches to treble clef for sustained high passages, and durations are pedal-aware: under a sustained pedal a note rings to the next onset up to one bar (a once-per-bar bass note becomes a whole note, not a clipped note + rests), since a rest under pedal is acoustically impossible — while gaps longer than a bar stay short to avoid multi-bar drones (`--pedal-sustain beat` keeps stabs short for grooves; `--no-legato-fill` keeps performed lengths for articulation-faithful engraving). Pieces with several tempi or keys are handled: sustained tempo plateaus become metronome-mark changes, persistent modulations become real key-signature changes, and `clean --tempo-map` writes a beat-aligned MIDI tempo map so DAW bar grids follow the performance. Generated scores carry title/composer/arranger/performer metadata in the document header. The `cleanup-score` skill handles the data-decidable part; what remains for a human ear is verifying pitches against the recording, the downbeat/pickup anchor, rubato barlines, tuplet decisions, ornaments, and dynamics/phrasing — listed per piece in `CLEANUP_NOTES.md`.
- Transcription runs on CPU by default; expect a few minutes per piece.
- **The engraved score will feel less expressive than the cleaned MIDI, and that is partly unavoidable.** A score is a lossy, discrete re-interpretation of a performance; quantization and note-value rounding necessarily delete the micro-timing, true durations, and continuous dynamics that make the MIDI sound alive. See [docs/WHY_MIDI_TO_SCORE_IS_HARD.md](docs/WHY_MIDI_TO_SCORE_IS_HARD.md) for the research literature on why this conversion is uniquely hard, which of our failures are irreducible vs. fixable, and the concrete roadmap for the fixable ones.
- Only transcribe recordings for personal study/use, and respect the rights of performers and composers.

## References

- [Why MIDI-to-score is hard](docs/WHY_MIDI_TO_SCORE_IS_HARD.md) — cited survey of the performance-to-score literature + this pipeline's roadmap

- Transkun: https://github.com/Yujia-Yan/Transkun
- yt-dlp: https://github.com/yt-dlp/yt-dlp
- MuseScore CLI: https://handbook.musescore.org/appendix/command-line-usage
