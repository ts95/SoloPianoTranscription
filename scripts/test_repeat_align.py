"""Regression test: repeat-consistency pre-snap alignment (repeat_align).

Spec: docs/superpowers/specs/2026-07-17-repeat-consistency-design.md
Run: .venv/bin/python scripts/test_repeat_align.py
"""
import sys, os, json, subprocess, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from transcription_cleanup import repeat_align
import pretty_midi

# the recurring figure: (in-bar beat, pitch) — 6 notes, both "hands"
FIGURE = [(0.0, 36), (0.0, 60), (0.5, 62), (1.0, 64), (1.75, 65), (2.5, 67)]


def bar_events(bar, shift=0.0, jitter=None, extra=None, start_id=0):
    evs = []
    for k, (off, p) in enumerate(FIGURE):
        j = jitter[k] if jitter else 0.0
        evs.append((start_id + k, bar * 4 + off + shift + j, p))
    if extra:
        evs.append((start_id + len(FIGURE), bar * 4 + extra[0], extra[1]))
    return evs


def test_uniform_rush_fixed():
    evs = (bar_events(0, start_id=0)
           + bar_events(1, shift=0.24, start_id=100)
           + bar_events(2, start_id=200))
    deltas, report = repeat_align(evs, 4)
    rushed_ids = {100 + k for k in range(len(FIGURE))}
    assert set(deltas) == rushed_ids, f"wrong notes corrected: {sorted(deltas)}"
    assert all(abs(float(d) - 0.24) < 0.02 for d in deltas.values()), deltas
    applied = [e for e in report if e.get("applied")]
    assert len(applied) == 1 and applied[0]["window"] == 2 \
        and applied[0]["reference_window"] in (1, 3), report
    print("ok: uniform rush corrected toward the clean reference")


def test_variation_flagged_not_touched():
    jitter = [0.0, 0.30, 0.05, 0.35, -0.10, 0.28]  # non-uniform: trimmed resid >> 0.07
    evs = (bar_events(0, start_id=0)
           + bar_events(1, jitter=jitter, extra=(2.75, 72), start_id=100)
           + bar_events(2, start_id=200))
    deltas, report = repeat_align(evs, 4)
    assert not deltas, f"variation was modified: {deltas}"
    flagged = [e for e in report if not e.get("applied") and e["window"] == 2]
    assert flagged and "reason" in flagged[0], report
    print("ok: non-uniform variation flagged, never touched")


def test_subthreshold_untouched_unflagged():
    evs = (bar_events(0, start_id=0)
           + bar_events(1, shift=0.05, start_id=100)
           + bar_events(2, start_id=200))
    deltas, report = repeat_align(evs, 4)
    assert not deltas, deltas
    assert not [e for e in report if e["window"] == 2], (
        f"sub-threshold shift should not even be flagged: {report}")
    print("ok: sub-threshold shift left alone silently")


def test_boundary_pickup_outlier_still_applied():
    # figure uniformly shifted 0.24 except the last note only 0.11 (a
    # differently-placed boundary pickup) -> trimmed uniformity test passes
    evs = (bar_events(0, start_id=0)
           + bar_events(1, shift=0.24, jitter=[0, 0, 0, 0, 0, -0.13], start_id=100)
           + bar_events(2, start_id=200))
    deltas, report = repeat_align(evs, 4)
    applied = [e for e in report if e.get("applied") and e["window"] == 2]
    assert applied, f"uniform body with one boundary outlier should apply: {report}"
    assert {100 + k for k in range(len(FIGURE))} == set(deltas), deltas
    print("ok: boundary pickup outlier trimmed; uniform body still auto-applied")


def test_agogic_ramp_per_beat_fixed():
    """Per-beat-group shift (v1.1): bar 2 is rushed with a RAMP, not a
    uniform shift — front beats pushed harder (~0.23), later beats less
    (~0.13, ~0.03), mirroring the measured Mirrors bar 2 (per-beat deltas
    -0.231/-0.223/-0.132/-0.028). A whole-bar median both fails the
    uniformity gate and overshoots the relaxed tail; a per-beat-group shift
    should apply cleanly with a descending-magnitude shift list."""
    # >=2 notes per beat so each beat-group's median is well-defined.
    RAMP_FIGURE = [
        (0.0, 60), (0.1, 62),   # beat 0
        (1.0, 64), (1.2, 65),   # beat 1
        (2.0, 67), (2.3, 69),   # beat 2
        (3.0, 71), (3.5, 72),   # beat 3
    ]
    RAMP = [0.23, 0.22, 0.13, 0.03]  # per-beat shift applied to bar 1 only

    def ramp_bar_events(bar, shifts, start_id):
        evs = []
        for k, (off, p) in enumerate(RAMP_FIGURE):
            g = int(off)
            evs.append((start_id + k, bar * 4 + off + shifts[g], p))
        return evs

    zero = [0.0, 0.0, 0.0, 0.0]
    evs = (ramp_bar_events(0, zero, start_id=0)
           + ramp_bar_events(1, RAMP, start_id=100)
           + ramp_bar_events(2, zero, start_id=200))
    deltas, report = repeat_align(evs, 4)
    applied = [e for e in report if e.get("applied") and e["window"] == 2]
    assert applied, f"agogic ramp should auto-apply per beat-group: {report}"
    sb = applied[0]["shift_beats_by_beat"]
    assert len(sb) == 4, sb
    assert all(sb[i] >= sb[i + 1] for i in range(len(sb) - 1)), (
        f"expected descending-magnitude ramp: {sb}")
    assert sb[0] > 0.15 and sb[-1] < 0.10, f"ramp endpoints off: {sb}"
    ramped_ids = {100 + k for k in range(len(RAMP_FIGURE))}
    assert ramped_ids <= set(deltas), (
        f"every window-2 note id should be in deltas: missing "
        f"{ramped_ids - set(deltas)}")
    print("ok: agogic ramp fixed with a descending per-beat-group shift")


def test_sparse_texture_not_cloned():
    """Fix A (evidence gate): a bar whose every beat-group is a single pair
    (one note per beat) offers zero within-group uniformity evidence, so ANY
    per-note delta pattern — even maximally scattered / sign-alternating —
    would otherwise auto-apply, cloning deliberate variation. It must instead
    be flagged 'insufficient uniformity evidence' and touch nothing."""
    FIG = [(0.0, 60), (1.0, 64), (2.0, 67), (3.0, 72)]  # one note per beat

    def sparse_bar(bar, jitter, start_id):
        return [(start_id + k, bar * 4 + off + (jitter[k] if jitter else 0.0), p)
                for k, (off, p) in enumerate(FIG)]

    scatter = [+0.30, -0.28, +0.35, -0.20]  # each note its own beat-group
    evs = (sparse_bar(0, None, start_id=0)
           + sparse_bar(1, scatter, start_id=100)
           + sparse_bar(2, None, start_id=200))
    deltas, report = repeat_align(evs, 4)
    assert not deltas, f"sparse scattered bar was cloned: {deltas}"
    flagged = [e for e in report if not e.get("applied") and e["window"] == 2]
    assert flagged, f"window 2 not flagged: {report}"
    assert "insufficient uniformity evidence" in flagged[0].get("reason", ""), report
    print("ok: sparse single-pair-group texture not auto-cloned")


def test_consensus_reference_beats_slot_aligned_loner():
    """Fix B (consensus reference): slot_err is mod-slot, so a bar dragged by
    exactly one grid slot (+0.25) reads as perfectly clean (slot_err 0) and,
    under the old min-slot_err rule, hijacked the reference — rewriting the
    true clean majority onto the wrong slots. With >=3 members the reference
    must be the most CENTRAL instance, so bars 1 and 3 outvote the loner."""
    # small jitter, still clean; downbeat (offset-0.0) notes stay positive so
    # they don't leak across the bar boundary (that is Fix C's concern, not B's)
    jit1 = [0.03, 0.02, 0.02, -0.03, 0.02, -0.02]
    jit3 = [0.02, 0.03, -0.03, 0.02, -0.02, 0.03]
    evs = (bar_events(0, jitter=jit1, start_id=0)
           + bar_events(1, shift=0.25, start_id=100)   # dragged exactly one slot
           + bar_events(2, jitter=jit3, start_id=200))
    deltas, report = repeat_align(evs, 4)
    applied = [e for e in report if e.get("applied")]
    assert applied, f"the dragged loner should be corrected: {report}"
    # reference must be a clean bar (window 1 or 3), NEVER the slot-aligned loner
    assert all(e["reference_window"] in (1, 3) for e in report), report
    assert all(e["window"] == 2 for e in applied), applied
    # the clean bars must not receive a -0.25 (or any) correction
    loner_ids = {100 + k for k in range(len(FIGURE))}
    assert set(deltas) <= loner_ids, (
        f"clean bars 1/3 were wrongly corrected: {sorted(set(deltas) - loner_ids)}")
    print("ok: consensus reference outvotes the slot-aligned loner")


def test_rushed_early_downbeat_figure():
    """Fix C (cross-window pairing): w = int(on // beats_per_bar) hard-slices
    before pairing, so a note rushed EARLIER than its in-bar offset lands in
    the PREVIOUS window. The rushed bar then looks short a note (count/coverage
    anomaly) and, before the fix, silently dissolves — no fix AND no flag.

    Branch asserted: FULL cross-window pairing — window 2 is applied with the
    correct negative shift and its rushed-early first note (id 100) is in the
    corrected deltas. (It must never return silently with no entry.)"""
    # one note per beat 0; the whole figure recurs cleanly in bars 1 & 3.
    FIG = [(0.0, 60), (1.0, 64), (1.5, 65), (2.0, 67), (3.0, 71), (3.5, 72)]

    def cbar(bar, shift, start_id):
        return [(start_id + k, bar * 4 + off + shift, p)
                for k, (off, p) in enumerate(FIG)]

    # bar 2 (index 1 -> window 2) rushed early 0.22: its downbeat (id 100)
    # lands at absolute beat 3.78, hard-sliced into window 1.
    evs = cbar(0, 0.0, 0) + cbar(1, -0.22, 100) + cbar(2, 0.0, 200)
    deltas, report = repeat_align(evs, 4)
    win2 = [e for e in report if e["window"] == 2]
    assert win2, f"window 2 dissolved silently (boundary leak): {report}"
    applied = [e for e in win2 if e.get("applied")]
    assert applied, f"window 2 not applied: {report}"
    sb = applied[0]["shift_beats"]
    assert sb < -0.15, f"expected a negative (rushed-early) shift: {sb}"
    assert 100 in deltas, (
        f"the rushed-early downbeat (id 100) was not reclaimed/corrected: "
        f"{sorted(deltas)}")
    assert float(deltas[100]) < -0.15, f"downbeat shift wrong: {deltas[100]}"
    print("ok: rushed-early downbeat reclaimed across the bar line (full pairing)")


def test_boundary_tie_no_clean_downbeat_shift():
    """Fix C boundary-tie: a repeated tone plays at the downbeat AND just before
    the next barline (pitch 99 at offsets 0.0 and 3.9 — a bass/pedal point).
    When a middle bar is dragged LATE its pre-barline note crosses into the next
    window; the NEXT bar's clean downbeat lands at framed offset == beats_per_bar
    in the dragged window, ties on interior_dist, and before the fix is STOLEN by
    the earlier (dragged) window and shifted. Invariant: a note whose physical
    home window is k+1 must never be claimed/corrected by an earlier window k."""
    FIG = [(0.0, 99), (0.5, 60), (1.0, 62), (2.0, 64), (3.0, 65), (3.9, 99)]

    def cbar(bar, shift, start_id):
        return [(start_id + k, bar * 4 + off + shift, p)
                for k, (off, p) in enumerate(FIG)]

    # bars 1 & 2 dragged LATE +0.20 (each pre-barline note crosses into the next
    # window); bars 0 & 3 clean. Bar 3's downbeat is id 300 at absolute beat 12.0.
    evs = (cbar(0, 0.0, 0) + cbar(1, 0.20, 100)
           + cbar(2, 0.20, 200) + cbar(3, 0.0, 300))
    deltas, report = repeat_align(evs, 4)
    assert 300 not in deltas or float(deltas[300]) == 0.0, (
        f"clean bar-3 downbeat (id 300) was shifted by an earlier window: "
        f"delta={deltas.get(300)}")
    print("ok: clean downbeat not stolen across the barline by an earlier window")


def test_clean_sparse_repeat_not_flagged():
    """Fix (evidence-gate ordering): a sparse one-note-per-beat figure that
    recurs IDENTICALLY (all deltas ~0) has nothing wrong, so it must be SILENTLY
    skipped by the magnitude gate — not flagged 'insufficient uniformity
    evidence'. The evidence gate only makes sense for bars that carry a real
    (>= MIN_SHIFT) scatter; a clean sparse repeat never reaches it."""
    FIG = [(0.0, 60), (1.0, 64), (2.0, 67), (3.0, 72)]  # one note per beat

    def sparse_bar(bar, start_id):
        return [(start_id + k, bar * 4 + off, p)
                for k, (off, p) in enumerate(FIG)]

    evs = (sparse_bar(0, 0) + sparse_bar(1, 100) + sparse_bar(2, 200))
    deltas, report = repeat_align(evs, 4)
    assert not deltas, f"clean sparse repeat was modified: {deltas}"
    assert not [e for e in report if e["window"] in (2, 3)], (
        f"clean sparse repeat should be silently skipped, not flagged: {report}")
    print("ok: clean sparse repeat silently skipped, not flagged")


def test_quantize_engraves_repeats_identically():
    """End to end: bar 2 rushed 0.24 beat -> all three bars engrave the same."""
    PY, SCRIPT = sys.executable, os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "transcription_cleanup.py")
    with tempfile.TemporaryDirectory() as d:
        mid = os.path.join(d, "t.mid")
        out = os.path.join(d, "t.musicxml")
        pm = pretty_midi.PrettyMIDI(initial_tempo=120)  # beat = 0.5 s
        inst = pretty_midi.Instrument(program=0)
        figure = [(0.0, 36), (0.0, 60), (0.5, 62), (1.0, 64), (1.75, 65), (2.5, 67)]
        for bar, shift in ((0, 0.0), (1, 0.24), (2, 0.0)):
            for off, p in figure:
                t = (bar * 4 + off + shift) * 0.5
                inst.notes.append(pretty_midi.Note(velocity=80, pitch=p,
                                                   start=t, end=t + 0.2))
        pm.instruments.append(inst)
        pm.write(mid)
        r = subprocess.run([PY, SCRIPT, "quantize", mid, out, "--bpm", "120",
                            "--time-sig", "4/4", "--bar-phase", "0"],
                           capture_output=True, text=True, check=True)
        summary = json.loads(r.stdout)
        applied = [e for e in summary.get("repeat_alignment", [])
                   if e.get("applied")]
        assert applied and applied[0]["window"] == 2, summary.get("repeat_alignment")

        from music21 import converter
        s = converter.parse(out)
        def bar_rhythm(part, n):
            m = part.getElementsByClass('Measure')[n]
            return [(float(e.offset), float(e.duration.quarterLength))
                    for e in m.notes]
        for part in s.parts:
            b1, b2, b3 = (bar_rhythm(part, k) for k in range(3))
            assert b1 == b2 == b3, f"bars differ after alignment: {b1} / {b2} / {b3}"
    print("ok: quantize engraves the rushed bar identically to its references")


if __name__ == "__main__":
    test_uniform_rush_fixed()
    test_variation_flagged_not_touched()
    test_subthreshold_untouched_unflagged()
    test_boundary_pickup_outlier_still_applied()
    test_agogic_ramp_per_beat_fixed()
    test_sparse_texture_not_cloned()
    test_consensus_reference_beats_slot_aligned_loner()
    test_rushed_early_downbeat_figure()
    test_boundary_tie_no_clean_downbeat_shift()
    test_clean_sparse_repeat_not_flagged()
    test_quantize_engraves_repeats_identically()
