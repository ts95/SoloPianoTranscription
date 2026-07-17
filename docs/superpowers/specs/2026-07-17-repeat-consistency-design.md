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

**Cross-window candidate pool (Fix NEW-1).** `w = int(on // beats_per_bar)`
hard-slices before pairing, so a note rushed *earlier* than its in-bar offset
lands in the previous window (and one dragged late in the next); a ±0.45 search
inside one hard-sliced window cannot reach it, and the whole match silently
dissolves — no fix and no flag. So pairing draws its candidate pool for a window
`k` from windows `{k-1, k, k+1}`, each note re-expressed in `k`'s frame at
`offset_in_k = absolute_beat − k·beats_per_bar`, keeping those in
`[−0.45, beats_per_bar + 0.45)`. Coverage denominators stay the **home** note
counts, so a neighbour's fringe never inflates coverage; the widening is purely
additive (no leak ⇒ pool = home window ⇒ pairing unchanged). A reclaimed fringe
note is corrected by the window it truly belongs to. One fringe note can appear
in two adjacent pools; the claim is resolved toward the note's physical home
window (Fix C). A note whose framed offset in window `k` is `>= beats_per_bar`
belongs to a *later* bar — a clean next-bar downbeat sits at exactly
`beats_per_bar` and shares interior_dist `0.0` with its true home window `k+1`
(where it sits at offset `0.0`) — so window `k` never claims it; the earlier
window may never shift a note whose musical home is a later bar. Among the
remaining candidates (framed offset `< beats_per_bar`, including the left-fringe
early-rushed notes a window reclaims) the more-interior claim wins. A paired
("claimed") note is never re-moved by any window's unpaired-note fallback, so no
note is shifted twice.

Candidate pairs chain into groups by union-find.

### 3. Reference selection and the auto-fix gate

Per group, the **reference** is the group's most representative clean instance.
For a 2-member group it is the instance with minimum mean distance from its
onsets to the nearest `1/grid` slot (mean slot error). For a **group of ≥ 3
(Fix NEW-2)** slot error alone is unsafe — it is mod-slot, so an instance
dragged by exactly one grid slot (e.g. +0.25) reads as perfectly clean and can
hijack the reference, rewriting the true majority onto the wrong slots. Instead
pick the **consensus / most-central** instance: the member minimizing the sum
over the others of `|median(pairwise onset deltas)|`, so two mutually-agreeing
instances outvote one slot-aligned loner; ties (and the 2-member case) break by
slot error. The chosen reference must still itself be clean: mean slot error
≤ 0.05 beat. No clean instance → no auto-fix for the group (flag only).

For each non-reference instance, estimate one constant shift
`δ = median(paired onset deltas vs reference)`. Auto-fix applies **only when
all three gates hold**:

1. `|δ| ≥ 0.10` beat — small shifts don't change the snap; don't touch them.
2. the worst-15%-trimmed residual after removing δ ≤ 0.07 beat (a
   uniformly-rushed figure body qualifies even when a couple of boundary
   pickup notes are placed differently) — it is genuinely one uniform
   rush, not free timing.
3. pairing coverage ≥ 85% (from §2).
4. **evidence (Fix NEW-3):** at least one beat-group actually *tested* local
   uniformity, i.e. had ≥ 2 paired notes. A bar whose every beat-group is a
   single pair (a sparse one-note-per-beat texture) offers zero within-group
   evidence, so gate 2 is vacuous and any per-note delta pattern — even a
   maximally scattered, sign-alternating one — would otherwise auto-apply,
   cloning deliberate variation. With no ≥ 2-pair group, refuse and flag
   `"insufficient uniformity evidence (no beat-group has 2+ paired notes)"`.

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

## v1.1 — per-beat-group shift (supersedes the whole-bar shift)

**Motivation (measured on Mirrors bar 2).** The rush of a repeated bar is often
not one constant offset but an *agogic ramp*: the player pushes into the phrase
and relaxes back to tempo across the bar. Bar 2 vs bar 4 (its matched
reference) has per-beat median deltas −0.231 / −0.223 / −0.132 / −0.028 —
smooth, and *locally uniform within each beat*, but with a whole-bar spread the
uniformity gate (correctly) rejects. A single per-bar shift also overshoots the
relaxed tail (one note spills into the next bar). One shift **per beat-group**
lands all 14/14 notes on the reference's exact grid slots.

This replaces §3's single δ. A perfectly uniform rush is the special case where
every group's δ is equal, so v1.0 behavior is preserved; the v1.0 boundary-trim
(worst-15%) is subsumed — a differently-placed pickup note simply belongs to
its own beat-group and gets that group's shift.

**Beat-group assignment.** Each paired note belongs to beat-group
`g = int(reference-partner in-bar offset)`, clamped to `[0, beats_per_bar-1]`.
`δ_g = median(paired deltas whose reference offset is in g)`. A group is
*estimable* if it has ≥1 pair.

**Gating** (all bar-level gates from §2/§3 still apply first: pitch match,
coverage ≥ 0.85, a clean reference). Then:

1. **Local uniformity, per group:** every estimable group with ≥2 pairs must
   have worst-15%-trimmed residual (its deltas minus `δ_g`) ≤ 0.07 beat.
   Single-pair groups are trivially uniform. If any group fails → the bar is
   genuinely scattered → flag `"non-uniform timing (beat N)"`, touch nothing.
2. **Magnitude:** at least one group has `|δ_g| ≥ 0.10` beat. If none does, the
   rush is below the snap-changing threshold → no report entry (as in v1.0).
3. **Evidence (Fix NEW-3):** at least one group must be non-trivial (≥ 2 pairs).
   If *every* group is a single pair, gate 1 is vacuous and gate 2 alone would
   clone an arbitrary scatter → flag `"insufficient uniformity evidence"`,
   touch nothing. (See §3 gate 4.)

**Applying.** Each paired note is shifted by `δ_g` of its reference partner's
group. An *unpaired* note (no reference match) is shifted by `δ_g` of the group
its own unshifted offset falls in, or 0 if that group is not estimable — so a
note moves consistently with its beat neighbours. Groups with no estimable δ
contribute 0.

**Boundary safety.** Adjacent notes across a beat boundary can receive
different shifts; because both are aligned toward the reference's own valid slot
ordering and every downstream measure is grid-snapped and balance-linted, a
reordering would surface as an unbalanced measure. No explicit clamp in v1.1;
revisit if a real piece trips the lint.

**Reporting.** An applied entry gains `shift_beats_by_beat: [δ_0, δ_1, …]`;
`shift_beats` stays (now the median of the applied per-note shifts) for
at-a-glance reading.

**Acceptance.** Mirrors bars 2 and 4 engrave identically straight from the
pipeline (no hand edit); the existing five `test_repeat_align.py` cases still
pass (uniform rush, variation-flagged, sub-threshold, boundary-pickup,
coverage) plus a new per-beat-ramp case.

## Out of scope (v2 candidates)

- Sub-bar and transposed figure matching.
- Consensus-template re-engraving (majority rhythm across a group).
- Tuplet-beat auto-fix.
- Continuous (linear-fit) ramp instead of a per-beat step — only if a real
  piece shows within-beat ramps the step model can't seat.
