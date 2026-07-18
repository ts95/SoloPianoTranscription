# Grid Surgery & Score-Refinement Toolkit

**Date:** 2026-07-18 (rewritten same day, consolidating 10 addenda)
**Status:** Approved design
**Case studies backing each rule:** docs/WHY_MIDI_TO_SCORE_IS_HARD.md and the
2026-07 piece directories (Cry Me A River, I Wish You All The Luck, Strobe,
Mirrors rerun).

## Goal

Move every mechanical operation of grid repair and score refinement into
deterministic scripts; reserve model reasoning for classification, repair
strategy, and by-ear judgment; dispatch subagents on the cheapest model tier
that each step needs.

## 1. Division of labor

**Deterministic (scripts):** fit measurement, tempo maps, window scans,
lattice construction, nudging, splicing, tail tracking, MIDI window trims,
score queries (bar/family/layout diffs), defect-class sweeps, the rebuild
chain, all file-format mechanics.

**Model (skill-guided):** classifying flagged spans (level hop vs lost pulse
vs genuine rubato vs fermata), designing discriminating measurements,
choosing repair spans/anchors by musical structure, family-based fine
adjustments, CLEANUP_NOTES authorship.

**Model tiers (dispatch explicitly per step):**

| Tier | Use |
|---|---|
| Haiku | Run a script, relay its digest: rebuilds, bake-off builds, verify, sweeps, exports, test runs. |
| Sonnet | Rubric-guided judgment: key/enharmonic choice (lint decides), clean-probe bake-off verdicts, PDF checklist passes, CLEANUP_NOTES drafts. |
| Opus | Default per-piece orchestrator: sequences stages, interprets diagnostics, writes surgery plans for known failure classes, runs targeted ear-feedback diagnosis. |
| Fable | Novel failure modes only: unclassifiable diagnostics, root-causing new defect classes into code+tests, phase-ambiguous surgery design. Opus escalates after stalling twice on the same defect. |

## 2. Already implemented (this session; keep, do not rebuild)

- `grid_fit_probe()` windowed probe; `beats --refine/--from-midi` report
  `onset_grid_fit`, `weak_windows`, `level_hop_suspects`.
- Repeat-align windows are bar-true (bar phase inferred before alignment).
- Arpeggio marks require > 90 ms chord spread.
- `apply_harmony_pedal.py`: `--anacrusis N` (pickup-bar conversion, runs
  before pedaling), forced-BeamMode strip, irregular-measure pedal ticks.
- `quantize`: no one-slot tie-fill appendices; exact fills poking ≤ 1 slot
  past a barline end flush.
- `clean_musicxml --source generated`: collapses any surviving within-bar
  one-slot tie stub (final invariant; unit test still owed — see §5).
- Tests: repeat-align suite, anacrusis, beam strip, updated tie-fill policy.

## 3. Toolkit to build

### 3.1 `scripts/grid_surgery.py`

`diagnose <cleaned.mid> <beats.json> --midi-shift S [--output F]` → one JSON:
- `tempo_map`: per-32-beat block (beat/bar range, start time, median period, BPM)
- `probe`: `grid_fit_probe` output plus `subdivision_fit` (see §3.2)
- `flag_clusters`: contiguous flagged windows merged to spans; per span, free
  period×phase scans at the quarter range (global median period ±20%) and the
  sublevel range (¾ of quarter), each reporting best BPM + fit, plus the
  grid's own fit in the span. Numbers only; classification is the skill's job.

`repair <plan.json>` — declarative surgery plan, paths relative to the plan:

```json
{ "base": "beats.frommidi.json", "midi": "<slug>.cleaned.mid",
  "midi_shift": 4.183,
  "repairs": [
    {"span_s": [156.2, 222.0], "op": "splice",  "source": "beats.refine128.json"},
    {"span_s": [222.0, 254.2], "op": "lattice", "period": 0.492},
    {"span_s": [328.1, "end"], "op": "lattice",
     "pieces": [[355, 0.455], [395, 0.448], ["end", 0.486]]} ],
  "output": "beats.json" }
```

Ops: `splice` (another grid's beats over the span, seam-snapped), `lattice`
(uniform `period` or piecewise `pieces`, anchored on the span's start seam,
onset-nudged; both seams pinned unless the span ends at `"end"`), `tail`
(cluster-tracked ritardando: beat = 4 × local 16th gap, to the last onset).

Executor owns all mechanics: span edges snap to base-grid downbeats
(index % 4 == 0); per-span beat-count parity forced to a multiple of 4;
repairs execute in time order; overlapping spans are an error; output must be
strictly monotonic; result is auto-probed with a per-region before/after
report; fit regression in an untouched region is an error. The plan file
stays in the piece directory as the audit record; the output's `source`
field names it.

Shared internals: extract the shrinking-window nudge from
`refine_fixed_grid_to_midi` into one module-level function used by refine,
the smoothing pass (§3.2), and `repair`.

### 3.2 `transcription_cleanup.py` changes

- **DP smoothing (default for `--from-midi`)**: moving-median period filter
  (window 5) rebuilds the sequence, then the shrinking-window nudge
  (16, 12, 8, 6, 4) re-seats it on the onsets. Report `raw_fit` alongside the
  (smoothed) `onset_grid_fit`. Rationale: raw DP beats jitter (16 ms median
  period jump) and displace notes across slot boundaries near barlines.
- **Full-coverage rule**: the final grid must cover every onset. Extend
  backward/forward by extrapolating the boundary period, prepending in
  multiples of 4 beats (early free material becomes pickup content).
  `quantize` warns loudly if any onset falls outside the grid.
- **`subdivision_fit`**: fit computed over non-beat slots only, reported by
  `beats` and `grid_fit_probe`. Rationale: the DP anchors beats on onsets, so
  on-beat fit is partly self-fulfilling; subdivision fit is the honest
  comparator between grid families.
- **IOI-ratio re-seat (post-snap repair in `quantize`)**: detect runs of ≥ 3
  same-staff onsets whose played IOIs are near-equal (max/min ≤ 1.25) but
  whose snapped IOIs differ by ≥ 2×; re-seat the run on the grid value
  nearest the median played IOI, anchored on the run's best-snapped onset.
  Fire only if re-seated positions stay within 0.2 beat of the played
  onsets. Report `ioi_reseated` (count + bars).
- **Chord-brush ghost drop (at chord merge in `quantize`)**: a slot-merged
  chord member with raw duration < 0.055 s AND velocity < 0.75 × the chord's
  maximum is dropped (key/pedal brush). Exception: keep it when a
  pitch-family sibling chord contains the same pitch (brushed voicing).
  Report count + bars.
- **`clean --keep-window <lo_s>:<hi_s>`**: strip notes and CC64 outside the
  window (cleaned-MIDI time), re-zero to the first kept onset, report the
  resulting audio-domain shift. For video intro/outro jingles; boundary
  choice stays with the model (onset-gap table in `score_query bar`).
- **`verify --audio-window <lo_s>:<hi_s>`**: trim the recording internally
  before chroma-DTW.

### 3.3 `scripts/finish_score.py` (rename of `apply_harmony_pedal.py`)

One CLI for the post-import `.mscz` finishing pass:
`finish_score.py <file.mscz> [--anacrusis N] [--midi <cleaned.mid> --beats
<beats.json>] [--staff N] [--keep-backup]`.

Order: anacrusis conversion → harmony-pedal analysis + insertion →
hygiene strip (forced BeamMode, `LayoutBreak` elements, solo-piano
instrument long/short names) → repackage. `apply_harmony_pedal.py` is
deleted; `musescore_pedal_lib.py` renames to `musescore_lib.py`;
`test_midi_pedal.py` renames to `test_finish_score.py`. All references
(skills, CLAUDE.md, README, pipeline blocks) update in the same delivery —
no alias.

`--midi` (CC64 write-back) remains only for under-detected pedal sources; a
real performance's CC64 stays in the cleaned MIDI.

### 3.4 `scripts/rebuild_score.py` + `piece.json`

Per-piece manifest (written at first delivery):

```json
{ "slug": "...", "key": "Eb major", "time_sig": "4/4",
  "beats": "beats.json", "beats_shift": 13.754,
  "title": "Mirrors", "composer": "Justin Timberlake",
  "performer": "Pianistmiri", "arranger": null,
  "anacrusis": 3, "dynamics_from_cleaned_midi": true,
  "quantize_flags": [], "post_flags": [] }
```

`rebuild_score.py <piece-dir>` runs: quantize → post → clean_musicxml →
`edits.py` (if present) → mscore → finish_score → export .musicxml/.pdf →
verify, persisting every stage summary under `output/<slug>/reports/` and
printing one compact combined digest. Any re-delivery is one command; no
arguments are ever retyped.

### 3.5 `scripts/score_query.py`

Compact fixed-width output designed for model reading; **all note views show
both staves** (single-staff views caused a one-staff fix).

- `map <piece-dir> <bar-or-time>`: printed-bar ↔ XML-measure ↔ quantize-
  window ↔ grid-beat ↔ MIDI-second ↔ audio-second table for a span.
- `bar <piece-dir> <n>[-<m>]`: per-bar aligned diff — engraved elements
  (offset, duration, pitches, ties, marks) against played onsets (beat
  position, nearest slot, deviation, velocity, raw duration), plus the
  span's onset-gap table.
- `family <piece-dir> <n>`: the bar's siblings by BOTH matchers — pitch
  family (repeat-align's multiset Jaccard) and rhythm family (in-bar
  onset-pattern similarity, transposition-invariant) — with engraved rhythms
  side by side and divergences marked.
- `sweep <piece-dir>`: all defect-class detectors in one pass: one-slot tie
  stubs, chord-brush ghosts, IOI-inconsistent runs, family-skeleton
  near-misses (≤ 2 slot moves from a skeleton occurring ≥ 3×), arpeggio
  spreads, unbalanced measures.
- `layout <piece-dir>`: bars-per-page/system distribution from the `.mscz`;
  flags orphan pages, stale LayoutBreaks, instrument-label leaks.

### 3.6 `.claude/skills/grid-surgery/SKILL.md`

Fires from cleanup-score when the bake-off winner's probe flags windows, and
for all targeted ear-feedback work.

**Grid loop:** diagnose → classify each flag cluster → plan → repair →
re-diagnose. Classification rubric:
- period ratio near ¾, 4/3, 2, ½ → **level hop**. In a continuous 16th wash
  every sub-multiple grid and every 16th-shifted phase fits the onsets
  perfectly; decide level and phase by continuity with neighboring sections,
  never by local fit.
- ratio ≈ 1.0 with low fit → free-scan the span: strong fit at a different
  tempo → **lost pulse** (lattice at the scanned tempo); weak everywhere →
  **genuine rubato/fermata** (flag, don't fix).
- periods growing smoothly at the end → **real ritardando** (tail op if the
  tracker raced it).

**Stop criterion:** onset fit ≈ 0.99 (subdivision_fit close behind).
Below target, escalate through methods (smoothing variants, per-section
scanned lattices, finer piecewise splits, per-span candidate swaps) and keep
the measured best. Stopping below target requires written proof of
irreducibility in CLEANUP_NOTES: name the residual spans and the measurement
showing no lattice fits them. Historical class ceilings are expectations,
not stop lines.

**Grid diagnostics from other features:** many applied repeat-alignments on
an ostinato piece, or repeat-alignment counts that drop on a candidate grid,
are grid evidence.

**Targeted ear-feedback loop (one-shot doctrine):** for every ear report —
1. Map the report (`score_query map`), produce the two-staff aligned diff
   (`score_query bar`).
2. Characterize the defect **as a class** (mechanical predicate) and sweep
   the whole piece for it (`score_query sweep`).
3. Find the figure's family (`score_query family`, both matchers). Cleanly
   played siblings are ground truth: the correction target is the family
   skeleton, not the locally-nearest slot. Family evidence outranks local
   heuristics in both directions. Only figures with no clean sibling are
   decided by local evidence (IOI ratios, slots).
4. Discriminate performance vs pipeline: identical across all instances →
   performance; divergent from clean instances → pipeline.
5. Fix at the deepest sensible level: producer policy (quantize) > end-of-
   chain invariant (clean_musicxml) > per-piece `edits.py` instance patch.
   Code fixes ship with a regression test.
6. Verify the region, not the patch: re-audit the edited bar ± 1 **in both
   staves** plus the whole family against the sweep checklist; re-run the
   class sweep to zero; `rebuild_score.py` for the re-delivery.

### 3.7 Pipeline integration

- The `.mscz` is a **build product**. Sources: `cleaned.mid` + `beats.json`
  + `piece.json` + `edits.py`. Never edit a roundtripped file; never feed an
  mscore-exported MusicXML back to mscore (add to CLAUDE.md gotchas beside
  "never import a .mid").
- `edits.py` holds by-ear surgical corrections (music21, against the fresh
  pre-MuseScore MusicXML), run automatically by `rebuild_score.py`; each
  edit carries a structural gate (balance, expected content) so a drifted
  baseline aborts the build instead of corrupting it.
- cleanup-score's wrap-up invites targeted ear feedback in bar/time terms;
  CLEANUP_NOTES records grid choice, surgeries (plan files), edits, and the
  verify-by-ear list.
- cleanup-score's grid section shrinks to: run the bake-off (build refine
  hints sweep + from-midi on the same cleaned MIDI; compare onset_grid_fit
  AND subdivision_fit; probe must be clean), else invoke grid-surgery.

## 4. Files

| Action | Path |
|---|---|
| Create | `scripts/grid_surgery.py`, `scripts/test_grid_surgery.py` |
| Create | `scripts/score_query.py`, `scripts/test_score_query.py` |
| Create | `scripts/rebuild_score.py` (+ per-piece `piece.json`) |
| Create | `scripts/finish_score.py`, `scripts/test_finish_score.py` (renames; old files deleted) |
| Create | `.claude/skills/grid-surgery/SKILL.md` |
| Rename | `scripts/musescore_pedal_lib.py` → `scripts/musescore_lib.py` |
| Modify | `scripts/transcription_cleanup.py` (§3.2; extract shared nudge) |
| Modify | `scripts/clean_musicxml.py` (stub-invariant unit test) |
| Modify | `.claude/skills/cleanup-score/SKILL.md`, `.claude/skills/transcribe/SKILL.md` (tier dispatch per §1, tool calls per §3) |
| Modify | `CLAUDE.md`, `README.md` (new tools, renames, gotchas) |

## 5. Testing

Synthetic fixtures throughout (constructed MIDIs with known defects):
- grid_surgery: a known dotted-eighth hop span and a known rit tail —
  diagnose flags them, a plan repairs them, re-probe clean; plan-validation
  errors (overlap, untouched-region regression).
- beats smoothing: jittered DP output → smoothed fit ≥ raw, period jumps
  bounded; coverage: onsets before beat 0 → prepended pickup beats.
- quantize: IOI re-seat (the Mirrors bar-6 pattern), chord-brush drop (with
  the family-voicing exception), out-of-grid warning.
- clean --keep-window (notes + CC64 + shift report), verify --audio-window.
- clean_musicxml: one-slot stub collapse unit test.
- score_query: map round-trip on a pickup piece; family finds a transposed
  rhythm sibling; sweep detects each planted defect class; layout flags a
  planted orphan page.
- rebuild_score: manifest round-trip reproduces byte-identical .musicxml on
  a fixture piece with an edits.py.

## 6. Out of scope

- Workflow-tool multi-agent orchestration beyond the tier dispatch in §1.
- Changes to Transkun, prepare_audio, or the download stage.
- Automatic classification of flagged windows inside scripts (model's job).
- Non-4/4 parity logic in grid surgery (revisit when a non-4/4 piece needs
  surgery).
- Sub-bar repeat-align auto-fixes (v2; `score_query family` provides the
  evidence for manual ones now).
