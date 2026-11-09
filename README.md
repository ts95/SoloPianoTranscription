# Solo Piano Transcription

Transcribe solo piano performances from YouTube into editable sheet music, for pieces where no published sheet music exists.

> **What this produces is a foundation, not a finished score.** The engraved
> output is a *starting point* that does the mechanical, time-consuming part of
> transcription for you — it is **not** a performance-ready edition. Converting a
> performance to notation is fundamentally lossy and imperfect (see
> [§ Limitations](#limitations-the-score-is-a-foundation)), so the result will
> contain wrong/missed notes, approximate rhythms, and rough voicing and pedaling,
> and **no dynamics** (add those by hand). **The rest is expected to be finished
> by hand** in MuseScore, guided by `CLEANUP_NOTES.md` and the recording. The goal
> is to get you to ~80% in minutes instead of hours, not to hand you a final score.

```
YouTube link
    │  yt-dlp + prepare_audio.sh (decode once, linear loudness-normalize, 44.1 kHz)
    ▼
output/<slug>/<slug>.wav  (+ <slug>.mp3 listening copy)
    │  Transkun v2 (automatic piano transcription)
    ▼
output/<slug>/<slug>.mid          ← raw transcription (the faithful "recording")
    │  cleanup-score: remove MIDI artifacts (ghosts, duplicates), then
    │  DuET (a learned MIDI→score model) engraves readable notation — its own
    │  key/meter/tempo, spelling, hand assignment, runs→grace notes, glissandi —
    │  set the header metadata, add harmony-aware pedaling, render via MuseScore 4 CLI
    ▼
output/<slug>/
    ├── <slug>.cleaned.mid                       ← cleaned MIDI (the editable "recording")
    ├── <slug>.mscz / .musicxml / .pdf           ← THE score foundation (one deliverable)
    ├── score.mid, review.json, report.json, …   ← DuET's listening MIDI + diagnostics
    └── CLEANUP_NOTES.md                         ← what to finish by hand, by ear
```

The two deliverables are the **cleaned MIDI** (a faithful, expressive capture of the
performance — play it back and it sounds like the recording) and the **score** (one
`.mscz`/`.musicxml`/`.pdf`, the readable-but-imperfect foundation you hand-finish).

Two design rules learned the hard way:

- **MuseScore never imports MIDI.** Its import quantization auto-detects its own tempo (ignoring the tempo/time-signature meta events) and can lock onto a sub-pulse — which wrongs every barline and sprays fake tuplets. MIDI → MusicXML goes through **DuET** (`scripts/duet.sh`), a learned model that maps the performance to engraved notation; MuseScore only converts formats.
- **Audio is decoded once.** YouTube serves lossy audio; re-encoding it to mp3 before transcription adds a second lossy generation. The transcription input is a WAV with linear (non-dynamic) loudness normalization, so the model sees a consistent level without compressed dynamics.

## Prerequisites

- macOS
- [ffmpeg](https://ffmpeg.org/) — `brew install ffmpeg`
- [MuseScore 4](https://musescore.org/) installed in `/Applications` (its `mscore` CLI converts `.musicxml` to `.mscz`; the pipeline calls it through the `scripts/mscore.sh` wrapper, which honours an `MSCORE` env var if MuseScore lives elsewhere)
- **DuET** — the MIDI → MusicXML model. It lives in a separate repo (`~/Repos/DuET`) with its own venv and a cached model; the pipeline calls it through the `scripts/duet.sh` wrapper (override the path with the `DUET` env var). See [DuET](https://github.com/wei-zeng98/DuET).
- Python 3.11
- [deno](https://deno.com/) — `brew install deno`. A JS runtime yt-dlp needs to solve YouTube's signature challenge; without it the download falls back to image-only formats. YouTube may *also* demand `--cookies-from-browser <browser>` to clear its bot check (see the `download-audio` skill).

## Setup

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install transkun yt-dlp music21 'llvmlite==0.42.0' 'numba==0.59.1' librosa
```

Note: `transkun` depends on PyTorch, so the install downloads roughly 2 GB. The Transkun v2 model weights ship with the pip package — no separate download needed. DuET is a separate install (its own venv + model, see Prerequisites); the pipeline only needs `scripts/duet.sh` to reach it.

## Usage

The easiest way is via Claude Code from this directory:

```
/transcribe https://www.youtube.com/watch?v=...
```

This runs all the stages and leaves the artifacts in `output/<slug>/`.

Each stage is also available as its own skill, useful for re-running a single step:

- `/download-audio <youtube-url>` — download + prepare audio (normalized 44.1 kHz wav for transcription, mp3 for listening)
- `/audio-to-midi <audio-file>` — transcribe audio to MIDI with Transkun
- `/midi-to-musicxml <midi-file>` — engrave MIDI to a readable MusicXML score with DuET, set the header metadata, convert to native MuseScore (.mscz), and add harmony-aware pedaling
- `/cleanup-score output/<slug>/` — the full MIDI → score step. Looks up the piece's real key/meter/tempo and credits online, removes transcription artifacts (ghost notes at piano-partial intervals, duplicates — pedal- and harmony-aware, so in-key consonant notes are flagged rather than deleted), engraves the cleaned MIDI with DuET (its own key/meter/tempo, spelling, hand assignment, runs→grace notes, glissandi), sets the header metadata, adds **harmony-aware pedaling** (one legato pedal per bar, re-pedalled where the bass harmony changes — derived from the engraved harmony, not the transcriber's coarse binary CC64), renders and compares bar-by-bar against the recording (chroma DTW — worst bars, barline drift, and repeat inconsistencies become listening priorities), and writes `CLEANUP_NOTES.md` flagging everything to finish by ear (including DuET's own `review.json` unsure spots). Produces one score deliverable (`.mscz`/`.musicxml`/`.pdf`). Can also stop at the cleaned `.mid` if that's all you want

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

# 3. MIDI → score. Clean the MIDI, engrave with DuET, set metadata, add
#    harmony-aware pedaling, render. (Usually just run /cleanup-score, which
#    also does the web ground-truth lookup and the report.)
.venv/bin/python scripts/transcription_cleanup.py clean \
  output/<slug>/<slug>.mid output/<slug>/<slug>.cleaned.mid --time-sig <ts> --key '<key>' --tempo <bpm>

D=$(mktemp -d)/duet
scripts/duet.sh output/<slug>/<slug>.cleaned.mid -o "$D" --device cpu
mv "$D"/* output/<slug>/
mv output/<slug>/score.musicxml output/<slug>/<slug>.musicxml
rm -rf "$(dirname "$D")"

# (Optional) If DuET's inferred meter/tempo disagree with the ground truth,
# force a constant tempo + one consistent meter (trims overfull bars).
.venv/bin/python scripts/normalize_meter_tempo.py \
  output/<slug>/<slug>.musicxml output/<slug>/<slug>.musicxml --tempo <bpm> --meter <B/T>

.venv/bin/python scripts/set_score_metadata.py \
  output/<slug>/<slug>.musicxml output/<slug>/<slug>.musicxml \
  --title '<title>' --composer '<composer>'
scripts/mscore.sh output/<slug>/<slug>.musicxml -o output/<slug>/<slug>.mscz
.venv/bin/python scripts/apply_harmony_pedal.py output/<slug>/<slug>.mscz   # pedal from harmony, not CC64
scripts/mscore.sh output/<slug>/<slug>.mscz -o output/<slug>/<slug>.musicxml        # regenerate so all formats agree
scripts/mscore.sh output/<slug>/<slug>.mscz -o output/<slug>/<slug>.pdf
```

`transcription_cleanup.py` also provides `analyze` (read-only JSON report: key/meter/tempo estimates, artifact candidates, fast runs), `verify` (render + per-bar chroma comparison against the recording), and `consensus` (cross-check against pitch-shifted re-transcriptions). The MIDI → MusicXML stage itself is DuET, not this script.

## Limitations: the score is a foundation

**The engraved score is a foundation to finish by hand, not a final deliverable.**
MIDI-to-notation is an open research problem and a fundamentally lossy projection
(see [docs/WHY_MIDI_TO_SCORE_IS_HARD.md](docs/WHY_MIDI_TO_SCORE_IS_HARD.md)) — even
state-of-the-art systems produce scores their own authors call "far from
satisfactory." DuET does the mechanical 80%: a correct-key, readably-engraved,
pedalled, two-staff score with metadata. It does **not** produce a finished edition.
Expect to fix, by hand in MuseScore:

- **Wrong and missing notes.** The transcriber and the engraving model mishear notes,
  especially in dense or fast passages; the pipeline cannot see what it cannot hear.
  `CLEANUP_NOTES.md` lists the bars whose audio least matches the score (your first
  listening pass), but pitch errors elsewhere remain possible.
- **Rhythm and barlines** under rubato — DuET infers the meter and bar structure from
  the model; some figures want re-grouping, and barlines may drift against the performance.
- **Voicing, articulation, and ornaments** — hand/staff assignment, trills written out
  as fast runs (often engraved as grace notes or glissandi), and beaming are approximate.
- **Dynamics are absent** — DuET writes none; add them by hand from the recording.
  **Pedaling** is harmony-derived (one pedal per bar, re-pedalled at harmony changes)
  and is a sensible default to refine, not an interpretive decision.

The companion **cleaned MIDI** is the faithful capture — if you want it to *sound*
like the performance, use the MIDI; the score is *instructions to a future
performer* that you complete. `CLEANUP_NOTES.md` is the hand-off: it records what
was decided automatically and the prioritized list of what to verify by ear.

## Other notes

- Transkun is trained on **solo piano**. Recordings with other instruments, vocals, or heavy room noise will transcribe poorly.
- The MIDI Transkun produces has **performance timing** (exactly as played, unquantized). DuET engraves it into notation: it infers the key signature, meter, and tempo from the model, spells notes against the key, assigns hands and staff, turns fast runs into grace notes, and writes glissandi as glissando lines. It copies every input note into the score, so the artifact-removal clean pass is what keeps Transkun ghosts and duplicates out of the engraving. Generated scores carry title/composer/arranger/performer metadata in the document header (set by `scripts/set_score_metadata.py`). The `cleanup-score` skill handles the data-decidable part; what remains for a human ear is verifying pitches against the recording, the downbeat/pickup anchor, rubato barlines, ornaments, and dynamics/phrasing — listed per piece in `CLEANUP_NOTES.md`.
- DuET infers the meter and tempo from the model, and that inference can be wrong (e.g. a 3/4 piece rendered with mixed meters and tempo changes). When the true meter/tempo is known, `scripts/normalize_meter_tempo.py --tempo <bpm> --meter <B/T>` forces a constant tempo and one consistent meter (trimming overfull bars) — run it right after DuET.
- Transcription (Transkun) and engraving (DuET) each run on CPU by default; expect a few minutes per piece.
- **The engraved score will feel less expressive than the cleaned MIDI, and that is partly unavoidable.** A score is a lossy, discrete re-interpretation of a performance; engraving necessarily deletes the micro-timing, true durations, and continuous dynamics that make the MIDI sound alive. See [docs/WHY_MIDI_TO_SCORE_IS_HARD.md](docs/WHY_MIDI_TO_SCORE_IS_HARD.md) for the research literature on why this conversion is uniquely hard, which of our failures are irreducible vs. fixable, and the concrete roadmap for the fixable ones.
- Only transcribe recordings for personal study/use, and respect the rights of performers and composers.

## References

- [Why MIDI-to-score is hard](docs/WHY_MIDI_TO_SCORE_IS_HARD.md) — cited survey of the performance-to-score literature + this pipeline's roadmap

- DuET: https://github.com/wei-zeng98/DuET (MIDI → score engraving model)
- Transkun: https://github.com/Yujia-Yan/Transkun
- yt-dlp: https://github.com/yt-dlp/yt-dlp
- MuseScore CLI: https://handbook.musescore.org/appendix/command-line-usage
