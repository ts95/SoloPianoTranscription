# Repeat-consistency quantization ("repeat alignment")

**Date:** 2026-07-17
**Status:** approved
**Motivating case:** Mirrors (Pianistmiri cover) — the verse figure was played
on-grid in bar 4 but rushed by a uniform ~0.24 beat in bar 2. Nearest-slot
snapping engraved the rush as a *different rhythm*; the fix was done by hand
after the user identified bar 4 as the reference. This feature does that
automatically: a piece's own cleanly played repetitions are ground truth for
its rushed ones.

## Decisions (user-confirmed)

- **Auto-align strong cases; flag the rest.** A hard evidence gate separates
  "one uniform rush of the same figure" (fixed) from "variation or sloppiness"
  (flagged, never touched).
- **Inside `quantize`,** as a pre-snap pass — not score surgery after the fact.
- **Whole-bar granularity.** Sub-bar/transposed figure matching is out of
  scope for v1.

## Architecture

New pass in `cmd_quantize` (`transcription_cleanup.py`), running after onset
clustering and warp mapping, **before** per-beat division selection
(`fracs_by_beat`) — corrected onsets must inform both the subdivision choice
and the snap. Enabled by default; `--no-repeat-align` disables. `post` and the
engraved score are never mutated by this feature.

Corrections live in the beat domain as a per-note offset map consulted where
note times enter the beat domain (equivalent to shifting the note before
quantization); durations ride along unshortened.

### 1. Bar windows

Slice the beat domain into windows of `beats_per_bar` (from `--time-sig`),
anchored at beat 0 (pre-pickup-padding). A window contains **all notes of both
staves** — matching and shifting treat the bar as one phrase event. A constant phase offset is harmless
for matching: recurring content recurs at bar period regardless of where the
window boundary falls. Pieces without a usable `beats_per_bar` skip the pass.

### 2. Matching (candidate pairs and groups)

Windows *i*, *j* are a candidate pair when:

- note counts within ±10% (and both ≥ 4 notes), and
- exact-pitch multiset Jaccard ≥ 0.8 (same figure at same pitch — octave-blind
  or transposed matching is v2), and
- pairing notes pitch-to-pitch in time order, searching ±0.45 beat around the
  expected position (the reference note's in-bar offset, so a rush leaking
  across the window boundary still pairs), covers ≥ 85% of both windows'
  notes.

Candidate pairs chain into groups by union-find.

### 3. Reference selection and the auto-fix gate

Per group, the **reference** is the instance with minimum mean distance from
its onsets to the nearest `1/grid` slot, and it must itself be clean: mean
slot error ≤ 0.05 beat. No clean instance → no auto-fix for the group (flag
only).

For each non-reference instance, estimate one constant shift
`δ = median(paired onset deltas vs reference)`. Auto-fix applies **only when
all three gates hold**:

1. `|δ| ≥ 0.10` beat — small shifts don't change the snap; don't touch them.
2. the worst-15%-trimmed residual after removing δ ≤ 0.07 beat (a
   uniformly-rushed figure body qualifies even when a couple of boundary
   pickup notes are placed differently) — it is genuinely one uniform
   rush, not free timing.
3. pairing coverage ≥ 85% (from §2).

Applying the fix subtracts δ from **all onsets in that window, both staves**
(a rush is a phrase event — the Mirrors case shifted treble and bass
identically). Matches failing any gate are flagged, never modified —
deliberate variation survives by construction.

### 4. Reporting

`summary["repeat_alignment"]`: one entry per matched non-reference window:
`{window, reference_window, shift_beats, coverage, applied, reason}` where
`reason` names the failed gate when `applied` is false. The cleanup-score flow
copies non-applied flags into `CLEANUP_NOTES.md` as verify-by-ear items.

### 5. verify: rhythm cross-check (the post-hoc net)

`cmd_verify` already pairs bars whose audio is near-identical (chroma cosine
≥ 0.99, ≥ 4 bars apart) and compares pitch-class sets. Add: for pairs whose
pitch classes agree (Jaccard ≥ 0.6 — i.e. not already pitch-flagged), compare
the engraved in-bar onset patterns (sorted note-head offsets per bar, both
staves). Differing patterns → a `repeat_inconsistencies` entry of kind
"rhythm", printing both patterns. verify has no grid, so it names no
reference — the ear picks. This catches whatever quantize declined to fix.

## Error handling

- No matches / no clean reference / all gates fail → pass is a no-op with
  flags; never an error.
- Windows with tuplet (ternary) beats participate in matching but are exempt
  from auto-fix in v1 (shift + tuplet re-snap interactions untested).
- The pass runs identically for `--bpm` and `--beats` grids (it operates in
  the beat domain after warping).

## Testing

`scripts/test_repeat_align.py` (self-check style, like the other test
scripts):

1. **Positive:** figure on-grid in bars 1 and 3, same figure rushed by a
   uniform 0.24 beat in bar 2 → all three bars engrave identical rhythms;
   summary records the applied shift for bar 2.
2. **Variation guard:** a bar sharing pitches but with an extra note and
   non-uniform timing → untouched, flagged with the failed gate.
3. **Sub-threshold:** the same figure shifted by 0.05 beat → untouched and
   not flagged (snap already agrees).

Live acceptance: re-run the Mirrors stage-3 chain from `cleaned.mid` and
assert bars 2 and 4 engrave identically with no hand edit; visually inspect
page 1 and re-run `verify` (median must not regress from 0.983).

## Out of scope (v2 candidates)

- Sub-bar and transposed figure matching.
- Consensus-template re-engraving (majority rhythm across a group).
- Tuplet-beat auto-fix.
