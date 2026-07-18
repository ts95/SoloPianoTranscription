# SoloPianoTranscription

Pipeline for transcribing solo piano performances from YouTube into editable sheet music: YouTube link → 44.1 kHz WAV (yt-dlp + `scripts/prepare_audio.sh`) → MIDI (Transkun v2) → MusicXML (`transcription_cleanup.py quantize`) → .mscz (MuseScore 4 CLI, format conversion only). Used for pieces where no published sheet music exists.

## Environment

- Always use the project venv binaries — never global installs:
  - `.venv/bin/python`
  - `.venv/bin/yt-dlp`
  - `.venv/bin/transkun`
- MuseScore CLI path (constant): `/Applications/MuseScore 4.app/Contents/MacOS/mscore`
- ffmpeg is at `/opt/homebrew/bin/ffmpeg` (needed by yt-dlp).
- If `.venv` doesn't exist: `python3.11 -m venv .venv && .venv/bin/pip install transkun yt-dlp music21 'llvmlite==0.42.0' 'numba==0.59.1' librosa` (pulls PyTorch, ~2 GB; llvmlite/numba are pinned because newer releases ship no x86_64 macOS wheels).
- `scripts/transcription_cleanup.py` (run with `.venv/bin/python`) provides `analyze` / `clean` / `beats` / `quantize` / `post` / `verify` / `consensus` subcommands used by the pipeline and `cleanup-score` skills.
- `scripts/prepare_audio.sh <in> <out.wav>` — two-pass linear loudness normalization + 44.1 kHz resample; run on all audio before Transkun.
- `scripts/finish_score.py <file.mscz>` — finishes a quantized `.mscz`: harmony-aware legato pedaling from the engraved harmony (one pedal per bar, split at harmony changes), via `analyze_pedaling.py` + `musescore_lib.py`. Use instead of CC64-derived pedal, which is binary and doesn't track harmony. Also strips every forced `<BeamMode>` from the mscx so MuseScore auto-beams by meter (the MusicXML import pins music21's holey beaming and turns beam-less stems into forced breaks — detached flagged runs that should be beamed), stale `<LayoutBreak>`s (frozen page/system breaks that break pagination after any content change), and solo-piano instrument long/short names (label leaks from MusicXML roundtrips). `--midi <cleaned.mid> --beats <beats.json>` also writes the same schedule into the MIDI as CC64 (replacing the transcriber's under-detected sustain; assumes bar-phase 0 / no pickup) — **only for under-detected pedal**; a real performance's CC64 stays in the cleaned MIDI.
- `scripts/clean_musicxml.py <file> --source generated` — final MusicXML cleanup (drops contradictory/duplicate dynamics, unpaired pedals); `--source generated` (default) skips OCR-only rules. `--source omr` for Audiveris input.
- `scripts/simplify_score.py <in.musicxml> -o <out.musicxml>` — **on request only** (an arrangement edit, not part of the default pipeline): playability reduction for Synthesia-style stacked scores. Thins off-beat chord re-strikes under the per-bar pedal to melody/bass skeleton, reduces LH stacks the RH already voices, caps hand spans at an octave (drop pitch-class-doubled notes, else octave-fold — never loses a pitch class; ties untouched). Runs between `post` and `clean_musicxml`; keeps the original key-aware spelling. The cleaned MIDI stays the faithful capture.
- `scripts/grid_surgery.py diagnose <cleaned.mid> <beats.json>` / `repair <plan.json>` — beat-grid diagnosis (windowed onset-fit probe, tempo map, free scans over flagged spans) and declarative repair (splice/lattice/tail-op surgery plans); used by the `grid-surgery` skill when a bake-off winner has flagged windows or fit below ~0.99.
- `scripts/score_query.py map|bar|family|sweep|layout <piece-dir> ...` — compact fixed-width score queries for targeted by-ear fixes: bar↔time mapping, two-staff aligned engraved-vs-played diffs, sibling-bar (family) matching, piece-wide defect-class sweeps, and post-rebuild `.mscz` layout checks.
- `scripts/rebuild_score.py <piece-dir>` — one-command re-delivery of a piece's score from its `piece.json` manifest: quantize → post → clean_musicxml → `edits.py` (if present) → mscore → `finish_score.py` → export `.musicxml`/`.pdf` → `verify`, with stage reports under `<piece-dir>/reports/`. The `.mscz` is a build product (sources: `.cleaned.mid` + `beats.json` + `piece.json` + `edits.py`) — never hand-edit it; change a source and rerun this.

## Output layout

One directory per piece, named by the slugified video title:

```
output/<slug>/
├── <slug>.wav        # prepared audio (44.1 kHz, loudness-normalized) — transcription input  [original, never overwrite]
├── <slug>.mp3        # listening copy  [original]
├── <slug>.mid        # raw Transkun transcription (performance timing, unquantized)  [original]
├── <slug>.cleaned.mid  # DELIVERABLE: cleaned MIDI (artifacts removed, tempo/meter/key meta) — the faithful "recording"
├── <slug>.musicxml   # ┐ DELIVERABLE: the ONE score (quantized + cleaned + clef changes + harmony
├── <slug>.mscz       # ┤ pedaling, all baked in). mscz for editing, musicxml for interchange, pdf for
├── <slug>.pdf        # ┘ printing + visual inspection. No separate "cleaned"/"pedaled" variants.
├── beats.json        # audio beat-tracking (librosa) — drives rubato-aware quantization
├── clean_report.json # machine summary of the MIDI clean pass
├── verify.json       # per-bar score-vs-recording similarity (chroma DTW)
├── piece.json        # rebuild manifest (key/time-sig/beats/metadata/flags) — source of truth for rebuild_score.py
├── edits.py          # optional: per-piece surgical patch (music21), re-run by rebuild_score.py
├── reports/          # per-stage rebuild_score.py output (quantize/post/clean_musicxml/edits/finish/verify)
└── CLEANUP_NOTES.md  # what was decided automatically + the prioritized hand-off (finish by ear)
```

## Pipeline stage commands

```bash
# 1. Download audio (slug comes from --restrict-filenames); decode once to WAV,
#    normalize linearly, derive a listening mp3 — never feed a re-encoded mp3 to Transkun
.venv/bin/yt-dlp -x --audio-format wav --restrict-filenames \
  -o 'output/%(title)s/%(title)s.%(ext)s' '<url>'
scripts/prepare_audio.sh 'output/<slug>/<slug>.wav' 'output/<slug>/<slug>.prepared.wav'
mv 'output/<slug>/<slug>.prepared.wav' 'output/<slug>/<slug>.wav'
/opt/homebrew/bin/ffmpeg -i 'output/<slug>/<slug>.wav' -codec:a libmp3lame -q:a 0 \
  'output/<slug>/<slug>.mp3'

# 2. Audio → MIDI
.venv/bin/transkun 'output/<slug>/<slug>.wav' 'output/<slug>/<slug>.mid' --device cpu

# 3. MIDI → MusicXML (script quantizer — NEVER MuseScore's MIDI import) → post
#    (spelling/ties/dynamics/clef changes) → clean_musicxml → .mscz → harmony
#    pedaling on the .mscz → regenerate .musicxml + .pdf from it (formats agree).
#    BPM from the user / web ground truth, else an analyze candidate.
#    Pedaling is from the engraved harmony, NOT CC64 (binary, doesn't track harmony).
.venv/bin/python scripts/transcription_cleanup.py quantize \
  'output/<slug>/<slug>.cleaned.mid' 'output/<slug>/<slug>.tmp.musicxml' --bpm <bpm> \
  --key '<key>' --time-sig '<ts>' --title '<t>' --composer '<c>'
.venv/bin/python scripts/transcription_cleanup.py post \
  'output/<slug>/<slug>.tmp.musicxml' 'output/<slug>/<slug>.musicxml' \
  --key '<key>' --time-sig '<ts>' --dynamics-from 'output/<slug>/<slug>.cleaned.mid'
rm 'output/<slug>/<slug>.tmp.musicxml'
.venv/bin/python scripts/clean_musicxml.py \
  'output/<slug>/<slug>.musicxml' -o 'output/<slug>/<slug>.musicxml' --source generated
MSCORE="/Applications/MuseScore 4.app/Contents/MacOS/mscore"
"$MSCORE" 'output/<slug>/<slug>.musicxml' -o 'output/<slug>/<slug>.mscz'
.venv/bin/python scripts/finish_score.py 'output/<slug>/<slug>.mscz'
"$MSCORE" 'output/<slug>/<slug>.mscz' -o 'output/<slug>/<slug>.musicxml'
"$MSCORE" 'output/<slug>/<slug>.mscz' -o 'output/<slug>/<slug>.pdf'
```

Once the choices above (key/time-sig/beats/metadata/anacrusis) are settled, write `output/<slug>/piece.json` (the manifest schema in the design spec) and use `scripts/rebuild_score.py 'output/<slug>/'` for every subsequent re-delivery — it re-runs this whole chain (quantize → post → clean_musicxml → `edits.py` if present → mscore → `finish_score.py` → export → `verify`) in one command instead of hand-typing it again.

## Skills

- `transcribe` — full pipeline from a YouTube URL; use for "transcribe this video" requests
- `download-audio` — stage 1 only
- `audio-to-midi` — stage 2 only (also works on local audio files the user provides). When the user's request is for a MIDI deliverable, always follow with `cleanup-score` in MIDI-only mode — a requested MIDI is delivered cleaned, never raw
- `midi-to-musicxml` — stage 3 only (exports both .musicxml and .mscz)
- `cleanup-score` — post-pipeline cleanup: web ground-truth lookup (key/meter), artifact removal, notation repair, velocity-derived dynamics/hairpins, `CLEANUP_NOTES.md` with verify-by-ear flags. Changes only what's decidable from data; never overwrites originals. Supports MIDI-only mode (steps 1–3, `.cleaned.mid` + notes, no MusicXML/.mscz) when the user wants just a cleaned MIDI. Ends by writing `piece.json`; re-deliveries go through `rebuild_score.py`.
- `grid-surgery` — diagnoses and repairs beat-grid failures (level hops, lost pulse, untracked ritardandi) flagged by the grid bake-off, and runs the targeted by-ear fix loop (`score_query` map/bar/family/sweep/layout) for any "bar N sounds wrong" report on a delivered score. Carries the model-tier dispatch table (Haiku executes scripts, Sonnet does rubric checks, Opus orchestrates, Fable only for novel failures) referenced by the other skills.

## Notation sanity (reason about the score, don't just convert)

- **Articulation question (rule)**: before starting transcription of a new piece, explicitly ask the user whether to diverge from the legato default. Legato default = note durations fill to the next onset (`quantize` does this automatically). If the user opts out, pass `quantize --no-legato-fill` and use the MIDI's performed durations to decide musically where staccato/other articulation marks belong (short raw durations against long gaps = detached playing). Either way `quantize` is pedal-aware: fill never bridges a same-staff silence longer than ~a beat (under pedal the note holds to the beat boundary; pedal-up it keeps the performed length), and pedal-carried rings never become sustained second voices — Transkun durations under pedal are acoustic smear, and engraving them makes drones, voice stacks, and padding-rest spray. When Transkun **under-detects CC64** (synth/washy sources — check `pedal down fraction` against what you hear), the pedal-up path fires everywhere and engraves note + rest spray; since the delivered score gets per-bar harmony pedaling anyway, pass `quantize --pedal-sustain always` to apply the under-pedal fill rule to the whole piece.
- **Repeat alignment**: `quantize` de-shifts a uniformly rushed/dragged instance of a repeated bar toward the group's cleanest instance before snapping — per beat-group, not a single whole-bar shift, so it also seats an agogic ramp (push into the phrase, relax back to tempo) that a whole-bar shift would overshoot. Reported in the summary as `repeat_alignment`, each applied entry carrying `shift_beats_by_beat` (`--no-repeat-align` disables). Gated hard — non-uniform divergence is only flagged (also by `verify` as `repeat_inconsistencies` kind "rhythm"); copy non-applied flags into CLEANUP_NOTES.
- **Balanced measures (rule)**: every measure and every voice must sum exactly to the bar duration — notes plus explicit rests, never invisible gaps. `quantize` and `post` print a `lint` block (unbalanced-measure count + printed-accidental ratio) with every generated score; a verdict other than "ok" must be fixed before delivering.
- **Visual inspection (rule)**: every final `.mscz` gets a PDF (`"$MSCORE" <file>.mscz -o <file>.pdf`), and the PDF must be inspected visually (Read the PDF pages directly) before delivery. Look for what the lint cannot see: marks floating mid-system or doubled, pedal lines not under the bass staff, colliding elements, multi-voice clutter / padding-rest spray, drone durations that halt the texture, fragmented beaming. Fix what is decidable and re-export; flag the rest.

After producing any score, inspect it for statistical outliers — transcription and quantization errors look like values that don't belong in the piece's rhythm profile:

- Build a note-type histogram (`grep -o "<type>[a-z0-9]*</type>" <file>.musicxml | sort | uniq -c`). A handful of 32nds/64ths/128ths in a piece that is overwhelmingly 16ths-and-eighths are almost certainly artifacts (onset jitter, ghost notes, split sustains), not music — find them, and either fix what's clearly decidable (e.g. merge a 32nd+rest pair that sums to the prevailing 16th) or flag them for by-ear review.
- The same applies to rests: isolated tiny rests punched into an otherwise continuous 16th-note texture are quantization gaps (duration snapped down past the next onset), not phrasing.
- Judge outliers in context: a 32nd-note run in one contiguous passage is likely a real ornament/flourish; the same values scattered randomly one-at-a-time through the piece are noise.
- A tuplet explosion, or a histogram dominated by values one "level" off from what the piece sounds like, means the BPM/grid was wrong — requantize rather than patching notes.
- After cleanup, run `verify` (renders the score, DTW-aligns chroma against the recording): its `worst_bars`, `drift_suspects`, and `repeat_inconsistencies` are the listening priorities for CLEANUP_NOTES. Chroma is octave-blind — a guide, not proof.

## Docs

- **Keep README.md and CLAUDE.md in sync with reality and each other.** Whenever a change makes either outdated (pipeline stages, commands, file layout, dependencies, skills), update both in the same delivery — README.md for humans (overview, setup, usage), CLAUDE.md for the agent (commands, paths, gotchas). Never describe the old pipeline in one file and the new one in the other.
- `docs/WHY_MIDI_TO_SCORE_IS_HARD.md` — cited survey of the performance-to-score literature (Cemgil, Nakamura, Desain & Honing, MV2H, neural/GNN approaches) plus the fixable-vs-irreducible breakdown and a tiered improvement roadmap for this pipeline. Read it before proposing structural changes to `quantize`/`post`: the two load-bearing verdicts are (a) quantization is a simplicity-vs-accuracy trade-off you *tune* (default coarser grids, deepen only on onset-histogram evidence), not a grid you snap to; (b) voice separation and rhythm are *one* coupled problem — our sequential quantize→assign-hands is the main architectural debt. When the user says the score feels worse than the MIDI, part of that gap is irreducible (a score is a lossy abstraction of a performance) — set that expectation rather than chasing it.

## Git

- Commit automatically after every delivered change (new/updated skills, scripts, docs, pipeline fixes) — one commit per delivery with a descriptive message. Don't wait to be asked.
- `output/` and `.venv/` are gitignored; only project sources are versioned.
- When a previously working stage regresses, use `git bisect` with a script that runs the failing conversion (e.g. mscore exit code on a kept test artifact) to find the breaking commit.

## Gotchas

- Transkun expects 44.1 kHz input; `scripts/prepare_audio.sh` guarantees it (and applies linear loudness normalization — never dynamic-mode loudnorm, which compresses dynamics and skews velocities). Run it on all audio before Transkun, including user-supplied files.
- Stage 2 takes a few minutes per piece on CPU — run it in the background and don't assume it hung.
- Stages are re-run safe by convention: before running a stage, check whether its output file already exists and is non-empty, and skip it unless the user asked to redo it.
- `mscore` may print Qt warnings to stderr even on success — judge by exit code and whether the output file was written.
- Quote all paths: video-title slugs can still contain characters that need quoting, and the mscore path contains a space.
- **Never import a `.mid` into MuseScore** (CLI or GUI) — its quantization auto-detects its own tempo, ignores the tempo and time-signature meta events, and can lock onto a sub-pulse (e.g. the dotted-eighth of a 3-3-2 groove → 4/3 of the true BPM), wronging every barline and spraying fake tuplets. All MIDI → MusicXML goes through `transcription_cleanup.py quantize --bpm <bpm>`; mscore is only for `.musicxml` → `.mscz`/PDF format conversion.
- The quantize grid stands or falls with the BPM. Prefer the user / web ground truth over statistical candidates, and check the quantize summary: `score_seconds_at_bpm` must be within a few percent of `audio_seconds`.
- Grid choice: steady performance → fixed `--bpm` grid (cleaner notation); rubato → `beats` subcommand + `quantize --beats` (barlines follow the performance). Always seed `beats --bpm-hint` with ground truth — audio beat trackers lock onto sub-pulses just like autocorrelation (this is also why `quantize` infers the downbeat phase and may open bar 1 with pickup rests — when the inference confidence is marginal and the evidence disagrees, override with `quantize --bar-phase 0`).
- For heavy rubato / deep ritardandi, prefer `beats --from-midi <cleaned.mid> --midi-shift <trim_shift_s>`: it DP-tracks the transcription's own onsets. The audio tracker pinned to a hint cannot follow a deep slowdown — it falls behind, then races ahead at a fake fast tempo and mangles every barline after it. Sanity metric: the fraction of MIDI onsets within 0.07 beat of a 16th slot of the grid should be ≳0.95.
- **Grid choice is a measured comparison, not a genre guess (rule).** When `analyze` says rubato, do NOT override it because the piece "sounds steady" — build BOTH grids (`--refine` and `--from-midi`), compute the onset-fit for each against the same cleaned MIDI, and take the winner. Coffin Dance (2026-07): analyze said heavy rubato (CV 0.35); it was dismissed as figuration noise and the refine grid (fit 0.67–0.78) shipped — engraving straight eighths as dotted figures + 144 spurious 16ths, and making `repeat_alignment` fire on 5 phantom "rushed repeats" (identical bars drifting against the grid). The from-midi grid scored **0.994**, collapsed the piece to its true straight-eighth profile (16ths 144 → 9, repeat_alignment 0 — correctly), and tracked the closing ritardando exactly. Symptom signature of a drifting grid: fit ~0.7 with off-slot histogram peaks, dotted-rhythm/16th confetti in a piece that sounds straight, and repeat-alignment "fixing" many bars of an ostinato. A refine fit ~0.7 is only acceptable when the onset histogram peaks are centered ON slots *and* from-midi doesn't beat it.
- For near-steady grooves with strong syncopation (e.g. 3-3-2), *both* trackers can chase the accent layer — the audio tracker's beats land off the true quarters, and the onset DP's period histogram can smear between the quarter and the dotted eighth. `beats --refine <mid> --bpm-hint <bpm> --midi-shift <trim_shift_s>` (fixed grid scanned around the hint, then smoothly refined to the MIDI onsets; metrical level locked by construction) is the safe candidate — but it is a *candidate*, not the answer: Make Things For Smile (2026-07, a 3-3-2 Skrillex groove with the textbook 85.7/171.4 autocorrelation signature) was won by `--from-midi` at fit 0.874 vs refine's 0.79–0.83. Sweep refine over a few hints (its fit varied 0.61–0.83 across 120/125/128.5) and measure everything.
- **Trusting from-midi on a syncopated piece requires the accent-chasing probe — and the probe must be windowed, not global**: `beats --refine/--from-midi` now reports it (`onset_grid_fit` + `weak_windows` + `level_hop_suspects`; `grid_fit_probe()` in the script for hand-built grids). Genuine tracking = smooth periods (CV ≲0.1, few >15% jumps, no fast/slow alternation like 0.35/0.7 s) *and clean windows*. Global stats hide localized hops: Cry Me A River (2026-07) scored 0.94 globally with smooth-looking CV 0.072 while the bridge tracked the dotted-eighth layer (×3/4 period, engraved as a fake ♩=91) and the final ritardando raced at a fake-fast tempo. Both regions were continuous even-16th washes, where **every sub-multiple grid and every 16th-shifted phase fits the onsets perfectly** — onset fit cannot discriminate level or phase there; only continuity with the neighboring sections can. Repair = hybrid splice: keep clean-windowed spans, rebuild flagged spans as a continuous lattice anchored on the last good downbeat (phase/level from continuity, refine-style nudged to onsets), track a closing rit from note-cluster spacing (beat = 4 × local 16th gap); re-probe until windows are clean (Cry Me A River: 0.94 broken → 0.978 clean). A deep genuine rit can also trip `level_hop_suspects` — real rit periods *grow smoothly*; hops *sit at a ratio*.
- **Onset-fit ceilings calibrate by performance type** — judge the winner against the right ceiling, don't chase absolutes: sequenced/synthesia ≈ 1.0 (Jojo), steady human ≈ 0.99 (Coffin Dance from-midi), jittery syncopated human ≈ 0.85–0.90 is the realistic ceiling (Make Things For Smile 0.874 engraved a coherent, usable score). A grid at ~0.7 that LOSES to another candidate is bad; the best-available grid at 0.87 on a jittery groove is fine.
- **repeat_alignment behavior is itself a grid diagnostic**: many applied "fixes" on an ostinato piece = suspect the grid (identical bars drifting against it look like phantom rushes — Coffin Dance applied 5 on the bad grid, 0 on the good one); 0 applied with a handful flagged on a syncopated human take = healthy restraint.
- Pieces with several tempi/keys are supported: `quantize --beats` engraves a metronome-mark change per sustained tempo plateau (>12% for 16+ beats; more than 4 levels = rubato, single median mark), `post` engraves real key-signature changes for persistent modulations (guarded: the region must actually leave the incumbent key's pitch collection — chord emphasis like an A♭-heavy chorus in E♭ is skipped; the global key is restored afterwards unless the modulation runs to the final bar), and `clean --tempo-map beats.json` writes a beat-aligned MIDI tempo map so DAW bar grids follow the performance.
- **Score metadata rule**: every generated `.musicxml`/`.mscz` must carry the piece metadata in its header via `quantize --title/--composer/--arranger/--performer` — title and original composer/artist always; arranger when it's an arrangement/cover with a known author; performer when the pianist is known. Only include roles that make sense for the piece.
- **Enharmonic key spelling**: when the detected key has 6+ accidentals (A♭ minor, C♭ major, C♯ major…), quantize with the simpler enharmonic too and keep the spelling with the lower lint `printed_accidental_ratio` — Cry Me A River's A♭ minor (7 flats) scored 0.49 = PROBLEM; the same notes as G♯ minor (5 sharps) scored 0.38 = ok.
- **Performed CC64 stays in the cleaned MIDI**: `finish_score.py --midi/--beats` *replaces* the cleaned MIDI's sustain with the harmony schedule — only for under-detected pedal (synth/washy sources). A real performance's transcribed CC64 is part of the faithful capture; if overwritten, re-run `clean` to restore it.
- **Never feed an mscore-exported MusicXML back to mscore** — its layout freezes as `LayoutBreak`s and breaks pagination (sibling of the never-import-a-.mid rule); surgical edits go in `output/<slug>/edits.py` and re-run through `rebuild_score.py`.
- music21 `makeMeasures()` does not split notes at barlines — always follow with `makeTies()`, or MuseScore rejects the overfull measures (exit 40).
- music21 `makeMeasures()` attaches `Accidental('natural')` objects to notes; if they're not stripped before computing accidental display (`normalize_accidentals` in the cleanup script), the export prints an accidental on literally every note.
- zsh does not word-split unquoted variables; don't stash multi-word commands in shell variables.
