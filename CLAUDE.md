# SoloPianoTranscription

Pipeline for transcribing solo piano performances from YouTube into editable sheet music: YouTube link → 44.1 kHz WAV (yt-dlp + `scripts/prepare_audio.sh`) → MIDI (Transkun v2) → cleaned MIDI (artifact removal) → MusicXML (DuET, via `scripts/duet.sh`) → .mscz (MuseScore 4 CLI, format conversion only) + harmony pedaling. Used for pieces where no published sheet music exists.

## Environment

- Always use the project venv binaries — never global installs:
  - `.venv/bin/python`
  - `.venv/bin/yt-dlp`
  - `.venv/bin/transkun`
- **DuET** (the MIDI → MusicXML stage) lives in a SEPARATE repo with its own venv. Always invoke it via the wrapper `scripts/duet.sh <args…>` (never the raw path) — the wrapper has a stable, space-free path so a single permission rule `Bash(scripts/duet.sh *)` covers every call. It execs `~/Repos/DuET/.venv/bin/duet` (override with the `DUET` env var). DuET's model (`Wayne42/DuET`) is downloaded from Hugging Face on first use and cached locally; run with `--device cpu` on a Mac.
- MuseScore CLI: always invoke via the wrapper `scripts/mscore.sh <args…>` (never the raw binary or a `$MSCORE` variable) — the wrapper has a stable, space-free path so a single permission rule `Bash(scripts/mscore.sh *)` covers every call. It execs `/Applications/MuseScore 4.app/Contents/MacOS/mscore` (override with the `MSCORE` env var). Same pass-through semantics: `scripts/mscore.sh <in> -o <out>`.
- ffmpeg is at `/opt/homebrew/bin/ffmpeg` (needed by yt-dlp).
- If `.venv` doesn't exist: `python3.11 -m venv .venv && .venv/bin/pip install transkun yt-dlp music21 'llvmlite==0.42.0' 'numba==0.59.1' librosa` (pulls PyTorch, ~2 GB; llvmlite/numba are pinned because newer releases ship no x86_64 macOS wheels).
- `scripts/transcription_cleanup.py` (run with `.venv/bin/python`) provides `analyze` / `clean` / `verify` / `consensus` subcommands used by the pipeline and `cleanup-score` skills. (The MIDI → MusicXML stage is DuET, not this script.)
- `scripts/set_score_metadata.py <in> <out> --title --composer [--arranger] [--performer]` — sets the score header metadata on a DuET `score.musicxml`, editing only the `<work>`/`<identification>` header so the engraved content is left untouched.
- `scripts/normalize_tempo.py <in> <out> --tempo <bpm>` — overrides DuET's model-inferred tempo with the ground truth: sets ONE constant quarter-note tempo (first metronome mark and first `<sound tempo>`; every other mark and hidden playback tempo change is removed; *rit.* / *a tempo* text stays). Run it right after DuET on the raw `<slug>.musicxml` — it exits 1 on a MuseScore-regenerated file. Targeted text edit (NOT a music21 round-trip). There is no meter override: a wrong meter is flagged in `CLEANUP_NOTES.md` for hand re-barring.
- `scripts/prepare_audio.sh <in> <out.wav>` — one static gain toward −16 LUFS (capped so the true peak stays ≤ −1.5 dBTP) + 44.1 kHz resample; run on all audio before Transkun.
- `scripts/apply_harmony_pedal.py <file.mscz>` — adds harmony-aware legato pedaling to a `.mscz` from the engraved harmony (one pedal per bar, split at harmony changes), via `analyze_pedaling.py` + `musescore_pedal_lib.py`. Use instead of CC64-derived pedal, which is binary and doesn't track harmony. It replaces the pedal marks DuET itself writes. Known limitation: "harmony change" means the lowest bass note at the half-bar differs from beat 1, so an arpeggiated left hand is over-split.
- `scripts/simplify_score.py <in.musicxml> -o <out.musicxml>` — optional playability reduction for dense/stacked scores: thins off-beat repeat strikes to the melody skeleton, reduces large LH stacks to bass+partner, and caps voice spans by dropping doubled pitch classes or octave-folding (never losing the harmony). Standalone MusicXML→MusicXML; run on a DuET score when it's too dense to play. Unlike the other score scripts it IS a music21 round-trip, so re-inspect the result.
- `scripts/split_hands_midi.py <cleaned.mid> <score.npz> <out.mid> [--hand bass|treble]` — one-hand MIDI (the performance with the other hand muted), using DuET's per-note staff assignment from `score.npz`. Pass the same `.mid` DuET engraved; a mismatch is refused.

## Output layout

One directory per piece, named by the slugified video title:

```
output/<slug>/
├── <slug>.wav        # prepared audio (44.1 kHz, loudness-normalized) — transcription input  [original, never overwrite]
├── <slug>.mp3        # listening copy  [original]
├── <slug>.mid        # raw Transkun transcription (performance timing, unquantized)  [original]
├── <slug>.cleaned.mid  # DELIVERABLE: cleaned MIDI (artifacts removed, tempo/meter/key meta) — the faithful "recording"; DuET's input
├── <slug>.musicxml   # ┐ DELIVERABLE: the ONE score (DuET engraving + metadata + harmony
├── <slug>.mscz       # ┤ pedaling, all baked in). mscz for editing, musicxml for interchange, pdf for
├── <slug>.pdf        # ┘ printing + visual inspection. No separate "cleaned"/"pedaled" variants.
├── score.mid         # DuET listening MIDI (score-aligned, separate upper/lower-staff tracks)
├── review.json       # DuET: spots the engraving was unsure about (key changes, low-margin spellings, runs that may be tuplets)
├── report.json       # DuET: model identity, input cleanup, engraving version
├── notes.json, score.npz, frames.csv  # DuET raw predictions (note-aligned, assembled score, 50 Hz frames)
├── clean_report.json # machine summary of the MIDI clean pass
├── verify.json       # per-bar score-vs-recording similarity (chroma DTW)
└── CLEANUP_NOTES.md  # what was decided automatically + the prioritized hand-off (finish by ear)
```

## Pipeline stage commands

```bash
# 1. Download audio (slug comes from --restrict-filenames); decode once to WAV,
#    normalize linearly, derive a listening mp3 — never feed a re-encoded mp3 to Transkun
.venv/bin/yt-dlp -x --audio-format wav --restrict-filenames \
  -o 'output/%(title)s/%(title)s.source.%(ext)s' '<url>'
scripts/prepare_audio.sh 'output/<slug>/<slug>.source.wav' 'output/<slug>/<slug>.wav' \
  && rm 'output/<slug>/<slug>.source.wav'
/opt/homebrew/bin/ffmpeg -i 'output/<slug>/<slug>.wav' -codec:a libmp3lame -q:a 0 \
  'output/<slug>/<slug>.mp3'

# 2. Audio → MIDI
.venv/bin/transkun 'output/<slug>/<slug>.wav' 'output/<slug>/<slug>.mid' --device cpu

# 3. Clean the MIDI. Ground-truth key/meter/tempo + composer/arranger/performer from the
#    web (see the cleanup-score skill); analyze for a statistical second opinion; strip
#    artifacts. DuET copies every input note, so this is what keeps ghosts/duplicates out
#    of the engraving — not optional.
.venv/bin/python scripts/transcription_cleanup.py analyze 'output/<slug>/<slug>.mid'
.venv/bin/python scripts/transcription_cleanup.py clean \
  'output/<slug>/<slug>.mid' 'output/<slug>/<slug>.cleaned.mid' \
  --time-sig '<ts>' --key '<key>' --tempo <bpm> --report 'output/<slug>/clean_report.json'

# 4. MIDI → MusicXML (DuET — NEVER MuseScore's MIDI import). DuET infers its own
#    key/meter/tempo and engraves runs/glissandi/hands. -o must be a directory that does
#    NOT exist yet (DuET creates it and refuses to overwrite an existing one — passing a
#    pre-created `mktemp -d` dir fails with "File exists"), so point it at a fresh subdir
#    under a mktemp base; move the outputs in, rename the score to the slug.
D=$(mktemp -d)/duet
scripts/duet.sh 'output/<slug>/<slug>.cleaned.mid' -o "$D" --device cpu
mv "$D"/* 'output/<slug>/'
mv 'output/<slug>/score.musicxml' 'output/<slug>/<slug>.musicxml'
rm -rf "$(dirname "$D")"

# 4b. (Optional) Override DuET's inferred tempo with the ground truth. DuET infers
#     a tempo per section (visible marks plus hidden playback changes). Run when the
#     web ground-truth tempo is known and differs: sets one constant tempo. There is
#     no meter override — flag a wrong meter in CLEANUP_NOTES.md.
.venv/bin/python scripts/normalize_tempo.py \
  'output/<slug>/<slug>.musicxml' 'output/<slug>/<slug>.musicxml' --tempo <bpm>

# 5. Set the score header metadata (DuET only writes a filename-derived title)
.venv/bin/python scripts/set_score_metadata.py \
  'output/<slug>/<slug>.musicxml' 'output/<slug>/<slug>.musicxml' \
  --title '<t>' --composer '<c>' [--arranger '<a>'] [--performer '<p>']

# 6. → .mscz, then harmony-aware pedaling on it, then regenerate .musicxml + .pdf FROM
#    the pedaled .mscz so all three formats agree. Pedaling is from the engraved harmony,
#    NOT CC64 (binary, doesn't track harmony).
scripts/mscore.sh 'output/<slug>/<slug>.musicxml' -o 'output/<slug>/<slug>.mscz'
.venv/bin/python scripts/apply_harmony_pedal.py 'output/<slug>/<slug>.mscz'
scripts/mscore.sh 'output/<slug>/<slug>.mscz' -o 'output/<slug>/<slug>.musicxml'
scripts/mscore.sh 'output/<slug>/<slug>.mscz' -o 'output/<slug>/<slug>.pdf'

# 7. QA: verify (render the score, DTW-align chroma against the recording)
.venv/bin/python scripts/transcription_cleanup.py verify \
  'output/<slug>/<slug>.musicxml' 'output/<slug>/<slug>.mp3' --output 'output/<slug>/verify.json'
```

## Skills

- `transcribe` — full pipeline from a YouTube URL, including `verify` and `CLEANUP_NOTES.md`; use for "transcribe this video" requests
- `download-audio` — stage 1 only
- `audio-to-midi` — stage 2 only (also works on local audio files the user provides). When the user's request is for a MIDI deliverable, always follow with `cleanup-score` in MIDI-only mode — a requested MIDI is delivered cleaned, never raw
- `midi-to-musicxml` — stages 4–6 (DuET engraving + metadata + .mscz/.pdf + harmony pedaling)
- `cleanup-score` — post-pipeline cleanup: web ground-truth lookup (key/meter/tempo + credits), `analyze`, artifact removal, DuET engraving if not already done, `verify`, and `CLEANUP_NOTES.md` with verify-by-ear flags. Changes only what's decidable from data; never overwrites originals. Supports MIDI-only mode (steps 1–3, `.cleaned.mid` + notes, no score) when the user wants just a cleaned MIDI.

## Notation sanity (reason about the score, don't just convert)

- **Dynamics are DuET's first draft**: DuET writes block dynamics (roughly one mark per 8 bars, model-inferred). They ship in the score as a starting point; the user refines them by hand from the recording. Do not add further dynamics from velocity.
- **Balanced measures (rule)**: every measure and every voice must sum exactly to the bar duration — notes plus explicit rests, never invisible gaps. DuET's engraving should produce balanced measures; if a measure looks off (a gap or an overfull bar) it is a flag for by-ear review, not a silent patch.
- **Visual inspection (rule)**: every final `.mscz` gets a PDF (`scripts/mscore.sh <file>.mscz -o <file>.pdf`), and the PDF must be inspected visually (Read the PDF pages directly) before delivery. Look for what a text check cannot see: marks floating mid-system or doubled, pedal lines not under the bass staff, colliding elements, multi-voice clutter / padding-rest spray, drone durations that halt the texture, fragmented beaming. Fix what is decidable and re-export; flag the rest.

After producing any score, inspect it for statistical outliers — transcription and engraving errors look like values that don't belong in the piece's rhythm profile:

- Build a note-type histogram (`grep -o "<type>[a-z0-9]*</type>" <file>.musicxml | sort | uniq -c`). A handful of 32nds/64ths/128ths scattered one-at-a-time through an otherwise steady texture are almost certainly artifacts (ghost notes, split sustains), not music — find them, and either fix what's clearly decidable or flag them for by-ear review.
- The same applies to rests: isolated tiny rests punched into an otherwise continuous texture are engraving gaps, not phrasing.
- Judge outliers in context: a 32nd-note run in one contiguous passage is likely a real ornament/flourish (DuET may engrave it as grace notes); the same values scattered randomly one-at-a-time through the piece are noise.
- DuET may engrave fast runs as grace notes or glissandi — confirm those are ornaments, not missed notes, by ear.
- After cleanup, run `verify` (renders the score, DTW-aligns chroma against the recording): its `worst_bars`, `drift_suspects`, and `repeat_inconsistencies` are the listening priorities for CLEANUP_NOTES. Chroma is octave-blind — a guide, not proof.

## Docs

- **Keep README.md and CLAUDE.md in sync with reality and each other.** Whenever a change makes either outdated (pipeline stages, commands, file layout, dependencies, skills), update both in the same delivery — README.md for humans (overview, setup, usage), CLAUDE.md for the agent (commands, paths, gotchas). Never describe the old pipeline in one file and the new one in the other.
- `docs/WHY_MIDI_TO_SCORE_IS_HARD.md` — cited survey of the performance-to-score literature (Cemgil, Nakamura, Desain & Honing, MV2H, neural/GNN approaches) plus the fixable-vs-irreducible breakdown. Historical context for why the old `quantize`/`post` grid approach was hard; DuET now handles the MIDI → score step with a learned model. When the user says the score feels worse than the MIDI, part of that gap is irreducible (a score is a lossy abstraction of a performance) — set that expectation rather than chasing it.

## Git

- Commit automatically after every delivered change (new/updated skills, scripts, docs, pipeline fixes) — one commit per delivery with a descriptive message. Don't wait to be asked.
- `output/` and `.venv/` are gitignored; only project sources are versioned.
- When a previously working stage regresses, use `git bisect` with a script that runs the failing conversion (e.g. mscore exit code on a kept test artifact) to find the breaking commit.

## Gotchas

- Transkun expects 44.1 kHz input; `scripts/prepare_audio.sh` guarantees it (and applies one static gain — never ffmpeg's two-pass `loudnorm`, which silently falls back to dynamic compression when the peak or loudness range exceeds its targets, skewing velocities). Run it on all audio before Transkun, including user-supplied files.
- Stage 2 (Transkun) and stage 4 (DuET) each take a few minutes per piece on CPU — run them in the background and don't assume they hung.
- Stage 1 (yt-dlp) now usually needs **two** things to clear YouTube's gates, both requiring user confirmation: a JS runtime (`brew install deno`) to solve the signature/"n challenge" (without it only image formats download), and `--cookies-from-browser <browser>` to clear the "confirm you're not a bot" check. They co-occur; apply both. Updating yt-dlp alone won't fix it. See the `download-audio` skill's troubleshooting for detail.
- Stages are re-run safe by convention: before running a stage, check whether its output file already exists and is non-empty, and skip it unless the user asked to redo it. Stage 1 is complete only when `<slug>.wav` exists AND `<slug>.source.wav` does not (a leftover `.source.wav` means preparation did not finish — re-run `prepare_audio.sh`).
- `mscore` may print Qt warnings to stderr even on success — judge by exit code and whether the output file was written.
- Quote all paths: video-title slugs can still contain characters that need quoting. (The MuseScore binary path contains a space, but `scripts/mscore.sh` hides it — call the wrapper, never the raw path.)
- **Never import a `.mid` into MuseScore** (CLI or GUI) — its quantization auto-detects its own tempo, ignores the tempo and time-signature meta events, and can lock onto a sub-pulse, wronging every barline and spraying fake tuplets. All MIDI → MusicXML goes through **DuET** (`scripts/duet.sh`); mscore is only for `.musicxml` → `.mscz`/PDF format conversion.
- **DuET never overwrites**: `-o` must point at a directory that does not already exist (the default `results/<name>/` auto-numbers, but an explicit `-o` that exists is rejected with "File exists"). So point `-o` at a fresh *subdir* under a `mktemp -d` base (e.g. `D=$(mktemp -d)/duet`) — not at the pre-created base dir itself — and move the outputs in.
- **DuET copies every input note** into the score (one score record per retained input note, pitch copied from the input). Artifact removal in the clean pass is therefore what keeps Transkun ghosts/duplicates out of the engraving — don't skip it.
- **Cleanup is skippable (with a trade-off)**: you can feed the raw `<slug>.mid` (not `.cleaned.mid`) straight to DuET to skip artifact removal. The score then includes Transkun ghosts/duplicates. Use it only when you deliberately want the most faithful (if noisier) engraving — e.g. to compare against the cleaned version.
- **DuET infers meter and tempo from the model — they can be wrong.** Tempo: if the web ground-truth tempo is known and differs, run `scripts/normalize_tempo.py --tempo <bpm>` right after DuET; it forces one constant tempo (visible marks and hidden playback changes). Meter: there is no override, in DuET or here — record the mismatch in `CLEANUP_NOTES.md` for hand re-barring in MuseScore.
- **Score metadata rule**: every delivered `.musicxml`/`.mscz` must carry the piece metadata in its header via `scripts/set_score_metadata.py --title/--composer/--arranger/--performer` — title and original composer/artist always; arranger when it's an arrangement/cover with a known author; performer when the pianist is known. DuET only writes a filename-derived title, so this step is required.
- zsh does not word-split unquoted variables; don't stash multi-word commands in shell variables.
- **Never prepend `cd` to pipeline commands.** The Bash working directory is already the repo root and persists between calls, and every command here uses repo-relative paths (`.venv/bin/…`, `scripts/…`, `output/<slug>/…`) that resolve from there. Invoke them directly — a `cd … &&` prefix only adds a needless permission prompt.
