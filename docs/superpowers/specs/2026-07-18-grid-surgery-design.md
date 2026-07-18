# Grid Surgery: deterministic toolkit + reasoning skill

**Date:** 2026-07-18
**Status:** Approved design

## Problem

On three consecutive pieces (Cry Me A River, I Wish You All The Luck Of The
World, Strobe) the beat grid needed hand surgery after the bake-off: the
winning tracker had localized failures (dotted-eighth level hops in 16th
washes, lost pulse in sparse texture, untracked ritardandi). The repair code
was rewritten inline each time — per-region fit tables, free period×phase
scans, anchored lattice construction, refine-style nudging, cluster tail
tracking, splice assembly with downbeat/parity bookkeeping. The math is
identical every time; only the *interpretation* (what is wrong, what to test,
what to rebuild) needs model reasoning. The parity bookkeeping is exactly
where hand-written code grows bugs (one occurred during the Strobe assembly).

## Split: what is deterministic vs what needs the model

**Deterministic (→ `scripts/grid_surgery.py`):**
- Windowed/region onset-fit measurement (extends the existing
  `grid_fit_probe`)
- Coarse tempo map (median beat period per block)
- Free uniform scans over a time window: period × phase grid search, run at
  both the quarter range and the sublevel (3/4) range, reporting both
- Onset-cluster tables (attack times + gaps) for a window
- Anchored lattice construction: uniform or piecewise periods from a seam
  anchor, beat-count parity (multiple of 4) enforced
- Refine-style nudge: shrinking-window median-residual smoothing with
  endpoint pinning (extracted from `refine_fixed_grid_to_midi` so both share
  one implementation)
- Cluster-tracked ritardando tail (beat = 4 × local 16th gap, greedy snap)
- Splice assembly: seam snapping to base downbeats, monotonicity checks,
  automatic re-probe, before/after per-region fit report
- Plan validation: refuse overlapping spans, seams off downbeats, or a result
  that regresses fit in untouched regions

**Model reasoning (→ `.claude/skills/grid-surgery/SKILL.md`):**
- Classifying a flagged window: level hop vs genuine rubato vs lost pulse vs
  fermata (identical headline symptoms, different fixes)
- Designing the discriminating measurement for ambiguous cases
- Choosing spans and anchors from musical structure; real-tempo-push vs hop
  decisions by continuity (in a 16th wash, onset fit cannot decide level or
  phase — only continuity can)
- Knowing when to stop: performance-class fit ceilings (sequenced ≈ 1.0,
  steady human ≈ 0.99, rubato ballad ≈ 0.94–0.98, jittery syncopated
  ≈ 0.85–0.90)
- Repeat-alignment distribution sanity (fixes concentrated in rubato spans =
  feature working; spread across a steady ostinato = grid suspect)
- Authoring CLEANUP_NOTES flags

## Toolkit: `scripts/grid_surgery.py`

CLI with two subcommands, run with `.venv/bin/python`.

### `diagnose`

```
grid_surgery.py diagnose <cleaned.mid> <beats.json> --midi-shift <s> \
    [--output diagnose.json]
```

Emits one JSON report:
- `tempo_map`: per-32-beat block — beat range, bar range, start time, median
  period, BPM
- `probe`: the existing `grid_fit_probe` output (global fit, weak_windows,
  level_hop_suspects)
- `flag_clusters`: contiguous flagged windows merged into spans; for each
  span, automatic free scans over its time range at the quarter range
  (global median period ±20%) and the sublevel range (3/4 of the quarter
  range), each reporting best BPM + fit, plus the grid's own fit in the span. Numbers only — no classification field; interpretation is
  the skill's job.

### `repair`

```
grid_surgery.py repair <plan.json>
```

Plan schema (all paths relative to the plan file's directory):

```json
{
  "base": "beats.frommidi.json",
  "midi": "<slug>.cleaned.mid",
  "midi_shift": 4.183,
  "repairs": [
    {"span_s": [156.2, 222.0], "op": "splice",  "source": "beats.refine128.json"},
    {"span_s": [222.0, 254.2], "op": "lattice", "period": 0.492},
    {"span_s": [328.1, "end"], "op": "lattice",
     "pieces": [[355, 0.455], [395, 0.448], [430, 0.474], ["end", 0.486]]}
  ],
  "output": "beats.json"
}
```

(A `tail` example, from Cry Me A River: `{"span_s": [293.4, "end"], "op":
"tail"}` — spans within one plan must not overlap.)

Ops (the three shapes every surgery this session needed):
- `splice`: replace the span's beats with another grid's beats over the same
  time range, seam-snapped
- `lattice`: uniform (`period`) or piecewise (`pieces`: list of
  `[until_time_s | "end", period_s]`) lattice anchored on the span's start
  seam, onset-nudged (both seams pinned; end seam free when span ends at
  `"end"`)
- `tail`: cluster-tracked ritardando from the span start to the last onset

Executor mechanics (all owned by the script, never the model):
- Span starts/ends snap to the nearest base-grid downbeat (index % 4 == 0);
  `"end"` means past the last onset
- Beat-count parity per span forced to a multiple of 4 (adjusting lattice N
  or dropping/stretching one seam interval), so downstream bar phase is
  preserved unless the repair's true beat count differs — in which case
  downstream phase follows the repaired count (continuity)
- Repairs execute in time order; overlapping spans are an error
- Output must be strictly monotonic; assembled grid is auto-probed; report
  prints global fit and per-region before/after (regions = each repair span
  plus the untouched remainder); a fit regression in untouched regions is an
  error
- The plan file stays in the piece directory as the audit record; the output
  beats.json `source` field names the plan file

## Skill: `.claude/skills/grid-surgery/SKILL.md`

Fires from cleanup-score when the bake-off winner's probe shows weak windows
or level-hop suspects. The loop:

1. `diagnose` the winner.
2. Classify each flag cluster with the rubric:
   - period ratio near 3/4, 4/3, 2, or 1/2 → **level hop** (in a continuous
     16th wash every sub-multiple grid and 16th-shifted phase fits perfectly;
     decide level/phase by continuity, never by local fit)
   - ratio ≈ 1.0, low fit → run the free-scan discrimination: strong
     free-scan fit at a *different* tempo than the grid → **lost pulse**
     (rebuild with lattice at the scanned tempo); free scan weak everywhere →
     **genuine rubato / fermata** (flag for the ear, do not fix)
   - periods growing smoothly toward the end → **real ritardando** (tail op
     if the tracker raced it, otherwise leave)
3. Write the surgery plan; `repair`; re-`diagnose`.
4. Iterate until windows are clean and fit ≈ 0.99 — escalating through
   methods per Addendum 3; stopping below target requires written proof of
   irreducibility, not a class-ceiling citation.
5. Record the surgery (plan file name, before/after fit) in CLEANUP_NOTES,
   including the standing caveat that repaired-span bar phase was chosen by
   continuity.

cleanup-score's current inline "hybrid repair recipe" prose is replaced by a
pointer to this skill.

## Files (updated per Addendum 4's restructuring)

- Create: `scripts/grid_surgery.py` — `diagnose` / `repair` CLI
- Create: `scripts/test_grid_surgery.py` — synthetic fixtures: a constructed
  MIDI with (a) a known dotted-eighth hop span and (b) a known rit tail;
  assert diagnose flags them, a plan repairs them, re-probe is clean; plus
  plan-validation error cases (overlap, regression)
- Create: `scripts/finish_score.py` — rename/absorption of
  `apply_harmony_pedal.py` (see Addendum 4); `apply_harmony_pedal.py` deleted
- Rename: `scripts/musescore_pedal_lib.py` → `scripts/musescore_lib.py`
- Create: `.claude/skills/grid-surgery/SKILL.md`
- Modify: `scripts/transcription_cleanup.py` — extract the nudge from
  `refine_fixed_grid_to_midi` into a shared module-level function; DP
  smoothing + full-coverage extension in `cmd_beats`; `subdivision_fit`;
  `clean --keep-window`; `verify --audio-window`; quantize out-of-grid
  warning
- Modify: `scripts/test_midi_pedal.py` → rename `scripts/test_finish_score.py`
  (imports follow the rename)
- Modify: `.claude/skills/cleanup-score/SKILL.md` — grid section points at
  the grid-surgery skill; pipeline commands use `finish_score.py`
- Modify: `CLAUDE.md`, `README.md` — new scripts, renames, pipeline commands

## Addendum (2026-07-18, from the Mirrors rerun)

A final validation transcription (Mirrors, full video, fresh run) exercised
the standardized flow end-to-end. The grid path needed **zero hand code** —
bake-off, probe, quantize all ran clean (from-midi 0.980, no flags,
overturning the first delivery's refine grid at 0.925). Exactly two
hand-written snippets remained, both deterministic; add them to the toolkit
scope:

1. **`clean --keep-window <lo_s>:<hi_s>`** — strip notes and CC64 outside the
   window (in cleaned-MIDI time), re-zero to the first kept onset, and report
   the resulting audio-domain shift (`trim_shift_s` + window start) for
   `--midi-shift`/`--beats-shift`. Used for video intro/outro jingles.
   Deciding the boundaries (which onset gaps are jingle seams) stays with the
   model — `diagnose`-style support comes free from the onset-gap table.
2. **`verify --audio-window <lo_s>:<hi_s>`** — trim the recording internally
   before chroma-DTW, so a windowed piece doesn't need a hand-made ffmpeg
   copy.

Skill-rubric addition: **repeat_alignment count is grid evidence** — the
Mirrors rerun's better grid took the applied count from 1 to 0 while bars
2 and 4 still engraved identically; a candidate grid that reduces applied
repeat-fixes (without introducing rhythm divergence in verify) is preferred.

## Addendum 2 (2026-07-18, from the Mirrors rerun's ear-reported defects)

The user heard two defects in the rerun ("the very first bar rushes — onsets
and durations wrong" and "at the boundary between bars, the rhythm is
sometimes off"). Both were measured, root-caused, fixed by hand, and belong
in the toolkit as defaults:

1. **DP grids must be smoothed (`beats --from-midi` default post-pass).**
   The onset-DP places beats *at* played onsets, so its beat-to-beat periods
   jitter (Mirrors: median period jump 16 ms, 161 jumps >30 ms across 614
   beats — vs 6 ms for refine). A beat displaced 40+ ms pushes notes played
   on adjacent 16ths across slot boundaries → wrong engraved rhythms near
   barlines, invisible in aggregate fit. Fix, now standard: moving-median
   period filter (window 5) to rebuild the sequence, then the shrinking-
   window nudge (16, 12, 8, 6, 4) back onto the onsets. Mirrors result: fit
   0.980 → 0.989, subdivision fit 0.972 → 0.988, median jump 16 → 5 ms,
   >30 ms jumps 161 → 15. The smoothing runs inside `cmd_beats` for
   `--from-midi`; the report carries `raw_fit` and (smoothed) `onset_grid_fit`.

2. **Full-coverage rule: the grid must cover every onset.** The DP starts at
   its strongest chain, which can leave early free material (Mirrors: five
   opening-sweep notes over 0.585 s) *before* beat 0 — quantize silently
   crams those notes into bar 1 (the "rushed first bar"). Fix, now standard:
   extend the grid backward (and forward) by extrapolating the boundary
   period, prepending in **multiples of 4 beats** so downbeat phase is
   preserved and the early material becomes pickup content in a mostly-rest
   bar 1. Bonus observed: with real coverage, quantize's pickup inference
   fired correctly (confidence 0.62, "bar 1 opens with 3 beats of rest").
   `quantize` additionally gets a loud warning when any onset falls outside
   the beat grid.

3. **`subdivision_fit` joins the metrics.** Because the DP anchors beats on
   onsets, on-beat fit is partly self-fulfilling (Mirrors slot histogram:
   1341 on-beat for from-midi vs 878 for refine on the same notes). The
   honest comparator is fit over non-beat slots only. `beats` reports and
   `grid_fit_probe` computes `subdivision_fit`; the bake-off compares both
   (a from-midi win that holds on subdivision_fit is real — Mirrors: 0.972
   vs refine's 0.928, so the ranking stood).

## Addendum 3 (2026-07-18): the fit target is ~0.99 — iterate until reached or provably irreducible

The stop criterion changes. The old "performance-class ceilings"
(jittery syncopated ≈ 0.85–0.90 etc.) were calibrated on *raw* grids; the
smoothing pass showed they were partly artifacts of the method, not the
performance (Mirrors: raw 0.980 → smoothed 0.989). The loop's goal is now:

- **Target: onset fit ≈ 0.99** (and subdivision_fit close behind).
- Below target, do not stop — escalate through methods: smoothing variants
  (window sizes, median vs mean), per-section lattices with scanned periods,
  finer piecewise splits, span-local re-anchoring, tail cluster-tracking,
  alternative candidates per span (each grid family per region), and any
  new deterministic method that the diagnosis suggests. Each attempt is
  measured; keep the best.
- Stopping below ~0.99 requires **written proof of irreducibility** in
  CLEANUP_NOTES: name the residual spans and the discriminating measurement
  showing no lattice can fit them (e.g. free per-window scans also score low
  → genuine rubato/fermata; asynchronous rolled attacks wider than the 0.07
  tolerance). "This class of piece usually scores X" is no longer an
  acceptable stop reason on its own.
- The old class ceilings survive only as *expectations* (what typically
  needs escalation), not as stop lines.

## Addendum 4 (2026-07-18): script naming and structure cleanup

`apply_harmony_pedal.py` has accreted unrelated responsibilities (harmony
pedaling, CC64-to-MIDI write, forced-beam stripping, anacrusis conversion)
— it is really the **post-import .mscz finishing pass**, and its name no
longer describes it. Restructure during implementation:

- **`scripts/finish_score.py`** (new home, `apply_harmony_pedal.py` deleted):
  one CLI over the finishing pass on a fresh `.mscz` —
  `finish_score.py <file.mscz> [--anacrusis N] [--midi <cleaned.mid>
  --beats <beats.json>] [--staff N] [--keep-backup]`.
  Order of operations: anacrusis conversion → harmony-pedal analysis +
  insertion → forced-BeamMode strip → repackage. Internals live in named
  functions (`make_anacrusis`, `strip_beam_modes`, `write_midi_pedal`,
  pedaling flow) so each stays independently testable.
- **`scripts/musescore_lib.py`** (rename of `musescore_pedal_lib.py`): the
  mscx plumbing (extract/repackage, staff/measure access) is general
  MuseScore-file infrastructure, not pedal-specific; the pedal-schedule
  helpers stay in it (moving them further is not worth a third module).
- `scripts/test_midi_pedal.py` → `scripts/test_finish_score.py`.
- `analyze_pedaling.py` unchanged (single clear responsibility).
- All pipeline commands, skills, CLAUDE.md and README references update to
  `finish_score.py` in the same delivery — no transition period, no alias.

## Addendum 5 (2026-07-18): the ear-feedback loop is a pipeline stage, with purpose-built query tools

The Mirrors session established the working pattern: **the pipeline does its
best autonomously; the user then reports what sounds wrong ("bar 6–7 is
weird", "the arpeggios don't sound right", "the first pedal is too long");
the model does targeted analysis of exactly those spots with the raw MIDI
and all tools, root-causes, fixes, and re-delivers.** That loop found three
genuine code bugs in one pass (repeat-align windows straddling barlines in
pickup pieces; arpeggio marks firing on ordinary 40 ms hand asynchrony; the
anacrusis measure getting a full-bar pedal span). It becomes a standing
stage:

- cleanup-score's wrap-up explicitly invites targeted feedback in bar/time
  terms, and CLEANUP_NOTES states that ear reports will be investigated
  against the raw MIDI.
- The grid-surgery skill gains a "targeted diagnosis" section: given a
  bar/time report, (1) map it to grid beats and MIDI time, (2) produce the
  aligned engraved-vs-played diff for the span, (3) check whether the defect
  recurs at similar bars (the repeat family), (4) discriminate performance
  vs pipeline (a defect that recurs at every family instance identically is
  the performance; one that differs from clean instances is the pipeline),
  (5) fix code (with regression test) or the piece, then re-deliver.

**Token-efficient purpose-built tools** (the session's hand-written inline
analyses, hardened into one CLI — `scripts/score_query.py`):

- `map <score> <beats.json> <bar-or-time>` — the printed-bar ↔ XML-measure ↔
  quantize-window ↔ grid-beat ↔ MIDI-second ↔ audio-second correspondence
  table for a span. (Getting this mapping wrong by one cost more tokens than
  any other single mistake in the session — three different numbering frames
  exist, plus pickup exclusion.)
- `bar <score> <cleaned.mid> <beats.json> <n>[-<m>]` — per-bar aligned diff:
  engraved elements (offset, duration, pitches, ties, marks) against played
  onsets (beat position, nearest slot, deviation, velocity, raw duration),
  one compact table per bar.
- `family <score> <n>` — find the bar's repeat family (pitch-multiset
  similarity, reusing repeat_align's matcher) and print the instances'
  engraved rhythms side by side with divergences highlighted.
- All output is compact fixed-width text designed to be read by the model —
  no JSON envelopes, no prose.

These are deterministic, reuse existing internals (`grid_fit_probe`,
`repeat_align`'s matching, music21 parsing), and replace the ~10 bespoke
inline scripts this session wrote for the same purposes.

Regression tests added by this addendum's bug fixes (already in code, plan
must keep them): bar-true repeat-align windows on pickup pieces, the 90 ms
arpeggio threshold, irregular-measure pedal ticks.

## Addendum 6 (2026-07-18): IOI-ratio consistency — equal played intervals must engrave as equal values

Second ear pass on Mirrors bar 6: the treble figure should read dotted-8th,
16th, 16th but engraved as dotted-8th, 8th, 16th. The played onsets sat at
beat positions 0.88 / 1.15 / 1.42 — **equally spaced** (IOIs 0.27, 0.27),
dragged ~0.15 behind the grid as a group. Per-onset snapping sent each to its
independently-nearest slot (0.75 / 1.25 / 1.5), splitting the equal intervals
into an 8th + 16th. This violates the classic quantization principle (Desain
& Honing): inter-onset *ratios* carry the rhythm, not absolute positions.

New deterministic post-snap repair in `quantize` (with regression test on the
bar-6 pattern):

- Detect runs of ≥3 successive same-staff onsets whose played IOIs are
  near-equal (max/min ≤ ~1.25) but whose snapped IOIs are unequal (some
  differing by ≥2×).
- Re-seat the run: anchor on the run's best-snapped onset, lay the remaining
  onsets at the run's median snapped IOI (choosing the grid value nearest the
  median played IOI), respecting the bar and neighbouring onsets.
- Gate conservatively: only fire when the re-seated positions stay within
  ~0.2 beat of the played onsets (an agogic drag/rush, not a rewrite), and
  report every application in the summary (`ioi_reseated` count + bars) for
  CLEANUP_NOTES.

This complements repeat alignment (which needs family evidence): IOI
consistency is *self-evidence* — it fires on figures that appear only once.

## Addendum 7 (2026-07-18): surgical edits rebuild from source — never round-trip the .mscz

Editing the delivered score by round-tripping (mscz → exported musicxml →
edit → re-import) broke the file: MuseScore's MusicXML export embeds its
layout, and re-importing froze 50 stale system/page breaks as LayoutBreaks
(pages with a single bar), re-pinned beams, and surfaced instrument labels.
Patching the patched file compounded it (16-page layout). Standing rules:

- **The `.mscz` is a build product.** A piece's sources are `cleaned.mid` +
  `beats.json` + the deterministic chain + its surgical edits. Any
  correction re-runs the chain; nothing edits a roundtripped file.
- **Surgical edits live at the pre-MuseScore stage**: a per-piece edit script
  (`output/<slug>/edits.py`, music21 against the fresh
  quantize→post→clean_musicxml output) applied between `clean_musicxml` and
  the `.mscz` conversion. The cleanup-score chain runs it automatically when
  present, so re-deliveries are reproducible with one command and ear-fix
  history is versioned in the piece directory (documented in CLEANUP_NOTES).
- **Never feed an mscore-exported MusicXML back to mscore.** (Sibling of the
  "never import a .mid" rule; add to CLAUDE.md gotchas at implementation.)
- `finish_score.py` defensively strips `LayoutBreak` elements and solo-piano
  instrument long/short names in its hygiene pass, alongside BeamMode.

## Out of scope (YAGNI)

- Workflow-tool multi-agent orchestration (bake-off parallelism is already
  cheap in bash; diagnosis is sequential reasoning)
- Changes to quantize/post
- Automatic classification of flagged windows in the script (that judgment is
  the model's job by design)
- Time-signature changes / non-4-beat bars in the parity logic (all pipeline
  pieces so far are engraved in a single meter; revisit if a 3/4 piece needs
  surgery)
