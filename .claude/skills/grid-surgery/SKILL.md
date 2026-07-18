---
name: grid-surgery
description: Diagnose and repair beat-grid failures (level hops, lost pulse, untracked ritardandi) and run targeted by-ear fix loops on delivered scores. Use when a grid bake-off winner has weak_windows/level_hop_suspects, when onset fit is below ~0.99, or when the user reports something sounding wrong in specific bars.
---

# Grid surgery and targeted score refinement

Tools (all `.venv/bin/python`): `scripts/grid_surgery.py` (diagnose/repair),
`scripts/score_query.py` (map/bar/family/sweep/layout),
`scripts/rebuild_score.py` (one-command re-delivery from piece.json).

## Model tiers (dispatch subagents accordingly)

- Haiku: run any script above and relay its digest (rebuilds, diagnose runs,
  sweeps, exports, tests).
- Sonnet: rubric-guided verdicts — clean-probe bake-off comparisons, PDF
  checklist passes, CLEANUP_NOTES drafts.
- Opus (default): orchestrates this skill — interprets diagnostics, writes
  surgery plans for the known classes below, runs the ear-feedback loop.
- Fable: only for diagnostics that match no known class, new defect classes
  needing code+test fixes, or phase-ambiguous surgery. Escalate after one
  stalled attempt.

## Grid loop

1. `grid_surgery.py diagnose <cleaned.mid> <beats.json> --midi-shift S`
2. Classify each flag cluster:
   - window period ratio near 3/4, 4/3, 2, 1/2 -> **level hop**. In a
     continuous 16th wash EVERY sub-multiple grid and every 16th-shifted
     phase fits the onsets perfectly — decide level and phase by continuity
     with neighboring sections, never by local fit.
   - ratio ~1.0 with low fit -> compare the cluster's `quarter_scan` to its
     `grid_fit`: scan much better at a different BPM -> **lost pulse**
     (lattice at the scanned tempo); scan also weak -> **genuine
     rubato/fermata** (flag for the ear, do not fix).
   - periods growing smoothly at the end -> **real ritardando** (tail op if
     the tracker raced it).
3. Write the surgery plan (spec §3.1 schema), `grid_surgery.py repair`,
   re-diagnose.
4. Target: onset fit ~0.99 with subdivision_fit close behind. Below target,
   escalate methods (smoothing variants, per-section scanned lattices, finer
   piecewise splits, per-span candidate swaps) and keep the measured best.
   Stopping below target requires written proof of irreducibility in
   CLEANUP_NOTES (name the spans + the measurement showing no lattice fits).
5. Grid evidence from other features: many applied repeat-alignments on an
   ostinato = suspect the grid; a candidate grid that reduces applied
   repeat-fixes without new verify divergences is preferred.

## Targeted ear-feedback loop (one-shot doctrine)

For every user report ("bar N sounds wrong"):

1. `score_query map` the span; `score_query bar` for the two-staff aligned
   diff (engraved vs played). Fixes ALWAYS consider both staves — a
   performance drag or rush is almost always two-handed.
2. Characterize the defect as a CLASS (mechanical predicate) and
   `score_query sweep` the whole piece for it. The report names one bar;
   the class names the scope.
3. `score_query family` for siblings (pitch AND transposition-invariant
   rhythm matches). Cleanly played siblings are ground truth: the correction
   target is the family skeleton, not the locally-nearest slot. Only
   figures with no clean sibling are decided by local evidence (IOI ratios,
   slots).
4. Discriminate performance vs pipeline: identical across all instances ->
   performance; divergent from clean instances -> pipeline.
5. Fix at the deepest sensible level: quantize policy > clean_musicxml
   invariant > per-piece `edits.py` patch (music21 against the fresh
   pre-MuseScore MusicXML, with a structural gate so a drifted baseline
   aborts). Code fixes ship with a regression test.
6. Verify the region, not the patch: re-audit the edited bar +-1 in BOTH
   staves plus the whole family; re-run the class sweep to zero; re-deliver
   with `rebuild_score.py <piece-dir>`; `score_query layout` after any
   .mscz rebuild.

Never edit a roundtripped file; the .mscz is a build product
(sources: cleaned.mid + beats.json + piece.json + edits.py).
