# Repeat Alignment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Model assignments (user requirement):** implementer subagents run **Sonnet 5 (`claude-sonnet-5`) or stronger — never Haiku**; per-task review subagents run **Opus** (`model: "opus"`); the final end-to-end review runs on **Fable** (the session model / `model: "fable"`). Pass the model explicitly on every Agent dispatch.

**Goal:** Quantize detects bars that repeat a figure and removes a uniform rush/drag from unclean instances before snapping, so repeated phrases engrave with identical rhythms; verify flags rhythm-divergent repeat pairs it didn't fix.

**Architecture:** A pure module-level function `repeat_align()` in `scripts/transcription_cleanup.py` computes per-note beat-domain corrections from bar-window matching (spec: `docs/superpowers/specs/2026-07-17-repeat-consistency-design.md`). `cmd_quantize` calls it right after hand-clustering and routes every note-time-to-beat conversion through corrected accessors. `cmd_verify` gains an engraved-rhythm comparison on its existing audio-repeat bar pairs.

**Tech Stack:** Python 3.11 (`.venv/bin/python`), music21, pretty_midi. Tests are standalone `assert`-style scripts like the existing `scripts/test_*.py`.

## Global Constraints

- **Subagent model floor: Sonnet 5 — never Haiku** (see header note; applies to implementer AND reviewer subagents).
- Always use `.venv/bin/python` — never a global python.
- Run every command from the repo root `/Users/toni/PrivateWork/SoloPianoTranscription`.
- MuseScore CLI: `MSCORE="/Applications/MuseScore 4.app/Contents/MacOS/mscore"` (quote it — the path has a space).
- Existing test scripts must stay green: `scripts/test_quantize_pedal.py`, `test_quantize_grid.py`, `test_voicing.py`, `test_clef.py`, `test_modulation_guard.py`, `test_simplify_score.py`, `test_midi_pedal.py`, `test_clean_musicxml.py`, `test_beats_from_midi.py`.
- Commit after each task with a descriptive message ending in `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
- Spec thresholds (do not change without updating the spec): MIN_NOTES 4, JACCARD 0.8, PAIR_WINDOW 0.45 beat, COVERAGE 0.85, REF_CLEAN 0.05 beat, MIN_SHIFT 0.10 beat, MAX_RESIDUAL_P90 0.07 beat.

---

### Task 1: `repeat_align()` pure function + unit tests

**Files:**
- Modify: `scripts/transcription_cleanup.py` (add module-level function directly above `def cmd_quantize` — find it with `grep -n "^def cmd_quantize" scripts/transcription_cleanup.py`)
- Test: `scripts/test_repeat_align.py` (create)

**Interfaces:**
- Produces: `repeat_align(events, beats_per_bar, grid=16) -> (deltas, report)` where `events` is `[(note_id, onset_beats: float, pitch: int)]` covering ALL notes (both hands); `deltas` is `{note_id: Fraction}` (beats to SUBTRACT from that note's onset and end); `report` is a list of dicts with keys `window`, `reference_window`, `coverage`, and either `shift_beats` + `applied: True` or `applied: False` + `reason`. Windows are numbered 1-based (`window == bar` when there is no pickup).

- [ ] **Step 1: Write the failing unit tests**

Create `scripts/test_repeat_align.py`:

```python
"""Regression test: repeat-consistency pre-snap alignment (repeat_align).

Spec: docs/superpowers/specs/2026-07-17-repeat-consistency-design.md
Run: .venv/bin/python scripts/test_repeat_align.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from transcription_cleanup import repeat_align

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
    jitter = [0.0, 0.30, 0.05, 0.35, -0.10, 0.28]  # non-uniform: p90 >> 0.07
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


if __name__ == "__main__":
    test_uniform_rush_fixed()
    test_variation_flagged_not_touched()
    test_subthreshold_untouched_unflagged()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python scripts/test_repeat_align.py`
Expected: `ImportError: cannot import name 'repeat_align'`

- [ ] **Step 3: Implement `repeat_align`**

Insert directly above `def cmd_quantize(` in `scripts/transcription_cleanup.py`:

```python
def repeat_align(events, beats_per_bar, grid=16):
    """Repeat-consistency pre-snap alignment.

    A piece's own cleanly played repetitions are ground truth for its rushed
    ones (spec: docs/superpowers/specs/2026-07-17-repeat-consistency-design.md).
    Bar windows with matching pitch content whose onsets differ from the
    group's cleanest instance by ONE uniform shift get that shift removed
    before quantization; matches failing any evidence gate are reported but
    never touched, so deliberate variation survives.

    events: [(note_id, onset_beats, pitch)] for ALL notes, both hands.
    Returns (deltas {note_id: Fraction beats to subtract}, report [dict]).
    """
    import statistics
    from collections import Counter, defaultdict

    MIN_NOTES, JACCARD, PAIR_WINDOW = 4, 0.8, 0.45
    COVERAGE, REF_CLEAN, MIN_SHIFT, MAX_RESIDUAL_P90 = 0.85, 0.05, 0.10, 0.07

    if not beats_per_bar or beats_per_bar < 2:
        return {}, []
    slot = 4.0 / grid

    wins = defaultdict(list)  # window -> [(in-bar onset, pitch, note_id)]
    for nid, on, pitch in events:
        w = int(on // beats_per_bar)
        wins[w].append((on - w * beats_per_bar, pitch, nid))
    keys = [k for k in sorted(wins) if len(wins[k]) >= MIN_NOTES]

    def multiset_jaccard(wa, wb):
        ca = Counter(p for _, p, _ in wa)
        cb = Counter(p for _, p, _ in wb)
        union = sum((ca | cb).values())
        return sum((ca & cb).values()) / union if union else 0.0

    def pair_deltas(ref, other):
        """other-minus-ref onset delta per pitch-matched pair (greedy,
        nearest within PAIR_WINDOW), walking the reference in time order."""
        by_pitch = defaultdict(list)
        for i, (off, p, _) in enumerate(other):
            by_pitch[p].append((off, i))
        used, deltas = set(), []
        for off, p, _ in sorted(ref):
            best = None
            for off2, i in by_pitch.get(p, ()):
                if i in used:
                    continue
                d = off2 - off
                if abs(d) <= PAIR_WINDOW and (best is None or abs(d) < abs(best[0])):
                    best = (d, i)
            if best is not None:
                used.add(best[1])
                deltas.append(best[0])
        return deltas

    def slot_err(win):
        return statistics.mean(
            abs(off - round(off / slot) * slot) for off, _, _ in win)

    def ternaryish(win):
        def err(div):
            unit = 1.0 / div
            return statistics.mean(
                abs(off - round(off / unit) * unit) for off, _, _ in win)
        return err(3) < err(4)

    parent = {k: k for k in keys}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for ai in range(len(keys)):
        for bi in range(ai + 1, len(keys)):
            a, b = keys[ai], keys[bi]
            wa, wb = wins[a], wins[b]
            if min(len(wa), len(wb)) / max(len(wa), len(wb)) < 0.9:
                continue
            if multiset_jaccard(wa, wb) < JACCARD:
                continue
            ds = pair_deltas(wa, wb)
            if len(ds) / max(len(wa), len(wb)) < COVERAGE:
                continue
            parent[find(a)] = find(b)

    groups = defaultdict(list)
    for k in keys:
        groups[find(k)].append(k)

    deltas_by_id, report = {}, []
    for members in groups.values():
        if len(members) < 2:
            continue
        ref = min(members, key=lambda k: slot_err(wins[k]))
        if slot_err(wins[ref]) > REF_CLEAN:
            report.extend({"window": k + 1, "reference_window": ref + 1,
                           "applied": False, "reason": "no clean reference"}
                          for k in members if k != ref)
            continue
        for k in members:
            if k == ref:
                continue
            ds = pair_deltas(wins[ref], wins[k])
            cov = len(ds) / max(len(wins[ref]), len(wins[k]))
            entry = {"window": k + 1, "reference_window": ref + 1,
                     "coverage": round(cov, 2), "applied": False}
            if cov < COVERAGE:
                entry["reason"] = "pairing coverage below 0.85"
                report.append(entry)
                continue
            delta = statistics.median(ds)
            if abs(delta) < MIN_SHIFT:
                continue  # snap already agrees — silently leave alone
            entry["shift_beats"] = round(delta, 3)
            resid = sorted(abs(d - delta) for d in ds)
            p90 = resid[min(len(resid) - 1, int(0.9 * len(resid)))]
            if ternaryish(wins[ref]) or ternaryish(wins[k]):
                entry["reason"] = "tuplet window (auto-fix exempt in v1)"
            elif p90 > MAX_RESIDUAL_P90:
                entry["reason"] = f"non-uniform timing (residual p90 {p90:.2f})"
            else:
                entry["applied"] = True
                d = Fraction(str(round(delta, 4)))
                for _, _, nid in wins[k]:
                    deltas_by_id[nid] = d
            report.append(entry)
    return deltas_by_id, report
```

`Fraction` is already imported at module top of `transcription_cleanup.py` (`from fractions import Fraction`) — verify with `grep -n "^from fractions" scripts/transcription_cleanup.py`.

- [ ] **Step 4: Run unit tests to verify they pass**

Run: `.venv/bin/python scripts/test_repeat_align.py`
Expected: three `ok:` lines.

- [ ] **Step 5: Commit**

```bash
git add scripts/transcription_cleanup.py scripts/test_repeat_align.py
git commit -m "quantize: repeat_align core — uniform-rush detection across repeated bars

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: wire repeat alignment into `cmd_quantize`

**Files:**
- Modify: `scripts/transcription_cleanup.py` (`cmd_quantize` + the `quantize` argparse block)
- Test: `scripts/test_repeat_align.py` (append integration test)

**Interfaces:**
- Consumes: `repeat_align(events, beats_per_bar, grid)` from Task 1.
- Produces: quantize summary key `repeat_alignment` (the report list, present only when non-empty); CLI flag `--no-repeat-align`; corrected note-time accessors `n_on(n)` / `n_end(n)` / `cl_on(cl)` used by all downstream beat-domain reads.

- [ ] **Step 1: Append the failing integration test**

Append to `scripts/test_repeat_align.py` (and add `import json, subprocess, tempfile` plus `import pretty_midi` at the top, and the new call at the bottom of `__main__`):

```python
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
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/python scripts/test_repeat_align.py`
Expected: the three unit tests pass, then the integration test FAILS (no `repeat_alignment` in summary / bars differ).

- [ ] **Step 3: Integrate into `cmd_quantize`**

3a. Move the `beats_per_bar` computation earlier. Find it (`grep -n "beats_per_bar = int(ts_parts" scripts/transcription_cleanup.py`) — it currently sits in the bar-phase section:

```python
    ts_parts = (args.time_sig or "4/4").split("/")
    beats_per_bar = int(ts_parts[0]) * 4 // int(ts_parts[1]) \
        if (int(ts_parts[0]) * 4) % int(ts_parts[1]) == 0 else 0
```

Cut those three lines and re-insert them immediately BEFORE the hand-clustering block (the comment `# Cluster near-simultaneous onsets per hand first`). The bar-phase section keeps using the variable.

3b. Immediately AFTER the `def cluster_onset(cl):` definition, insert:

```python
    # Repeat-consistency alignment (spec 2026-07-17): a uniformly rushed
    # instance of a repeated bar is de-shifted BEFORE division selection and
    # snapping, using the group's cleanest instance as reference.
    rep_deltas, rep_report = {}, []
    if not args.no_repeat_align:
        rep_deltas, rep_report = repeat_align(
            [(id(n), float(to_ql(n.start)), n.pitch) for n in notes],
            beats_per_bar, args.grid)
    if rep_report:
        summary["repeat_alignment"] = rep_report

    def n_on(n):
        return to_ql(n.start) - rep_deltas.get(id(n), 0)

    def n_end(n):
        return to_ql(n.end) - rep_deltas.get(id(n), 0)

    def cl_on(cl):
        return n_on(cl[len(cl) // 2])
```

3c. Route the downstream beat-domain reads through the accessors. Each is a single line — find with the greps shown:

| grep | old | new |
|---|---|---|
| `grep -n "float(to_ql(cluster_onset(cl)))" …` | `q = float(to_ql(cluster_onset(cl)))` | `q = float(cl_on(cl))` |
| `grep -n "to_ql(n.start)), n.pitch, n.velocity" …` | `events = [(float(to_ql(n.start)), n.pitch, n.velocity, float(to_ql(n.end) - to_ql(n.start))) for n in notes]` | `events = [(float(n_on(n)), n.pitch, n.velocity, float(n_end(n) - n_on(n))) for n in notes]` |
| `grep -n "treble_last = max" …` | `treble_last = max((float(to_ql(n.start)) for n in notes` | `treble_last = max((float(n_on(n)) for n in notes` |
| `grep -n "snap(to_ql(cluster_onset(cl)))" …` | `slots.setdefault(snap(to_ql(cluster_onset(cl))), []).extend(cl)` | `slots.setdefault(snap(cl_on(cl)), []).extend(cl)` |
| `grep -n "global_last_on = max" …` | `global_last_on = max(to_ql(n.start) for n in notes)` | `global_last_on = max(n_on(n) for n in notes)` |
| `grep -n "raw_dur = max(to_ql(n.end)" …` | `raw_dur = max(to_ql(n.end) - off for n in group)` | `raw_dur = max(n_end(n) - off for n in group)` |

Do NOT touch `pedal_iv` / `pedal_covered` (they consume CC64 times, not note times) or the `spread` roll check (seconds within one cluster — a uniform shift cancels out).

3d. Add the CLI flag to the `quantize` argparse block (next to `--no-legato-fill`):

```python
    q.add_argument("--no-repeat-align", action="store_true",
                   help="disable repeat-consistency alignment (de-shifting a "
                        "uniformly rushed instance of a repeated bar toward "
                        "the group's cleanest instance before snapping)")
```

- [ ] **Step 4: Run the full test file and the regression suite**

Run: `.venv/bin/python scripts/test_repeat_align.py`
Expected: four `ok:` lines.

Run: `for t in scripts/test_quantize_pedal.py scripts/test_quantize_grid.py scripts/test_voicing.py scripts/test_clef.py scripts/test_modulation_guard.py; do .venv/bin/python "$t" | tail -1; done`
Expected: every file ends with its usual `ok`/`all ... passed` line.

- [ ] **Step 5: Commit**

```bash
git add scripts/transcription_cleanup.py scripts/test_repeat_align.py
git commit -m "quantize: apply repeat alignment before division selection and snap

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: verify-side rhythm cross-check

**Files:**
- Modify: `scripts/transcription_cleanup.py` (`cmd_verify`, the repeat-flags loop — `grep -n "Repeated-section cross-check" scripts/transcription_cleanup.py`)

**Interfaces:**
- Consumes: the existing `bars` list (with per-bar `chroma`) and `bar_pitch_sets` in `cmd_verify`.
- Produces: additional `repeat_inconsistencies` entries with `"kind": "rhythm"`; existing pitch entries gain `"kind": "pitch"`.

- [ ] **Step 1: Locate the existing structures**

Run: `grep -n "bar_pitch_sets" scripts/transcription_cleanup.py`
`bar_pitch_sets` is built earlier in `cmd_verify` from the parsed score, one pitch set per bar. In the same loop that builds it, the score's measures are iterated — extend that loop to also record onset patterns. Read the surrounding ~20 lines first to match its exact iteration variables.

- [ ] **Step 2: Record per-bar onset patterns**

Where `bar_pitch_sets` is appended (one entry per bar, from the parsed score's measures), add a parallel list — adapt the iteration variable names to what the loop actually uses:

```python
    # engraved in-bar onset pattern (both staves merged, 1/8-beat resolution,
    # tie continuations excluded) — for the rhythm repeat cross-check
    bar_onset_patterns = []
```

and inside the per-measure loop, mirroring the pitch-set append:

```python
        pattern = sorted({round(float(el.offset) * 8) / 8
                          for el in measure.notes
                          if el.tie is None or el.tie.type == "start"})
        bar_onset_patterns.append(tuple(pattern))
```

If the loop iterates parts separately (two staves), merge: collect offsets from both parts' measure `k` into one set before appending (the pitch sets will show how the existing code merges — mirror it exactly).

- [ ] **Step 3: Extend the repeat-flags loop**

In the existing loop over near-identical-audio bar pairs (`if denom == 0 or vi @ vj / denom < 0.99: continue`), the pitch check flags `jac < 0.6`. Add `"kind": "pitch"` to that existing entry dict, and after it add the rhythm branch:

```python
            if jac >= 0.6:
                pi_ = bar_onset_patterns[bars[i]["bar"] - 1]
                pj_ = bar_onset_patterns[bars[j]["bar"] - 1]
                if pi_ and pj_ and pi_ != pj_:
                    repeat_flags.append({
                        "kind": "rhythm",
                        "bars": [bars[i]["bar"], bars[j]["bar"]],
                        "audio_similarity": round(float(vi @ vj / denom), 3),
                        "rhythms": [" ".join(str(x) for x in pi_),
                                    " ".join(str(x) for x in pj_)],
                        "hint": "audio repeats and pitches agree but the engraved "
                                "rhythms differ — align to the cleaner instance "
                                "by ear (quantize's repeat alignment declined "
                                "or missed this pair)"})
```

- [ ] **Step 4: Sanity-run verify on the existing Mirrors output**

```bash
B='output/Justin_Timberlake_-_Mirrors_Piano_Cover_by_Pianistmiri/Justin_Timberlake_-_Mirrors_Piano_Cover_by_Pianistmiri'
S='/private/tmp/claude-501/-Users-toni-PrivateWork-SoloPianoTranscription/a0be0d70-5514-4398-ac99-6cb59cb63a15/scratchpad'
.venv/bin/python scripts/transcription_cleanup.py verify "$B.musicxml" "$S/mirrors_arrangement.wav" --output "$S/verify_rhythm_check.json"
```

(If the trimmed wav is gone, recreate: `/opt/homebrew/bin/ffmpeg -y -ss 13.2 -to 498.6 -i "$B.wav" "$S/mirrors_arrangement.wav"`.)
Expected: runs clean; `repeat_inconsistencies` entries (if any) carry `kind` fields; median_similarity unchanged (0.98x).

- [ ] **Step 5: Commit**

```bash
git add scripts/transcription_cleanup.py
git commit -m "verify: flag rhythm-divergent repeat pairs (post-hoc net for repeat alignment)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: Mirrors live acceptance + docs sync

**Files:**
- Modify: `README.md` (quantization paragraph), `CLAUDE.md` (notation-sanity / articulation bullet area)
- Modify: `output/Justin_Timberlake_-_Mirrors_Piano_Cover_by_Pianistmiri/CLEANUP_NOTES.md`
- Modify (regenerate): the Mirrors score deliverables

**Interfaces:**
- Consumes: everything above, plus the standard stage-3 chain from CLAUDE.md.

- [ ] **Step 1: Re-run the Mirrors chain into scratch and check bars 2 vs 4**

The delivered score contains a HAND fix for bar 2; the pipeline must now reproduce it on its own. Run quantize+post to scratch first — do not overwrite deliverables yet:

```bash
B='output/Justin_Timberlake_-_Mirrors_Piano_Cover_by_Pianistmiri/Justin_Timberlake_-_Mirrors_Piano_Cover_by_Pianistmiri'
D='output/Justin_Timberlake_-_Mirrors_Piano_Cover_by_Pianistmiri'
S='/private/tmp/claude-501/-Users-toni-PrivateWork-SoloPianoTranscription/a0be0d70-5514-4398-ac99-6cb59cb63a15/scratchpad'
.venv/bin/python scripts/transcription_cleanup.py quantize "$B.cleaned.mid" "$S/mirrors_ra.musicxml" \
  --beats "$D/beats.json" --key 'Eb major' --time-sig '4/4' --title 'Mirrors' \
  --composer 'Justin Timberlake' --arranger 'Pianistmiri' --performer 'Pianistmiri' \
  | .venv/bin/python -c "import json,sys; d=json.load(sys.stdin); print(json.dumps(d.get('repeat_alignment','MISSING')[:8], indent=1)); print(d['lint'])"
```

Expected: `repeat_alignment` contains an applied entry for window 2 with `shift_beats` ≈ −0.24 or +0.24 (sign = instance minus reference; the rush is EARLY so expect ≈ −0.24), `lint` verdict ok. Then compare bars 2 and 4:

```bash
.venv/bin/python - <<'EOF'
from music21 import converter
s = converter.parse('/private/tmp/claude-501/-Users-toni-PrivateWork-SoloPianoTranscription/a0be0d70-5514-4398-ac99-6cb59cb63a15/scratchpad/mirrors_ra.musicxml')
for pi, p in enumerate(s.parts):
    r = []
    for n in (2, 4):
        m = p.getElementsByClass('Measure')[n-1]
        r.append([(float(e.offset), float(e.duration.quarterLength)) for e in m.notes
                  if e.tie is None or e.tie.type == 'start'])
    assert r[0] == r[1], f"part{pi+1}: bar2 {r[0]} != bar4 {r[1]}"
print("ok: bars 2 and 4 engrave identically from the pipeline")
EOF
```

If bar 2 ≠ bar 4, STOP and debug (dump `repeat_alignment` in full: which gate failed for window 2?). Do not proceed to Step 2 until this passes.

- [ ] **Step 2: Promote — full chain over the deliverables**

```bash
B='output/Justin_Timberlake_-_Mirrors_Piano_Cover_by_Pianistmiri/Justin_Timberlake_-_Mirrors_Piano_Cover_by_Pianistmiri'
D='output/Justin_Timberlake_-_Mirrors_Piano_Cover_by_Pianistmiri'
MSCORE="/Applications/MuseScore 4.app/Contents/MacOS/mscore"
.venv/bin/python scripts/transcription_cleanup.py quantize "$B.cleaned.mid" "$B.tmp.musicxml" --beats "$D/beats.json" --key 'Eb major' --time-sig '4/4' --title 'Mirrors' --composer 'Justin Timberlake' --arranger 'Pianistmiri' --performer 'Pianistmiri' > /dev/null
.venv/bin/python scripts/transcription_cleanup.py post "$B.tmp.musicxml" "$B.musicxml" --key 'Eb major' --time-sig '4/4' --dynamics-from "$B.cleaned.mid" --beats "$D/beats.json" | grep '"verdict"'
rm "$B.tmp.musicxml"
.venv/bin/python scripts/clean_musicxml.py "$B.musicxml" -o "$B.musicxml" --source generated | tail -1
"$MSCORE" "$B.musicxml" -o "$B.mscz" 2>/dev/null
.venv/bin/python scripts/apply_harmony_pedal.py "$B.mscz" | tail -1
"$MSCORE" "$B.mscz" -o "$B.musicxml" 2>/dev/null
"$MSCORE" "$B.mscz" -o "$B.pdf" 2>/dev/null
```

Expected: verdicts ok throughout.

- [ ] **Step 3: verify + PDF inspection**

```bash
S='/private/tmp/claude-501/-Users-toni-PrivateWork-SoloPianoTranscription/a0be0d70-5514-4398-ac99-6cb59cb63a15/scratchpad'
.venv/bin/python scripts/transcription_cleanup.py verify "$B.musicxml" "$S/mirrors_arrangement.wav" --output "$D/verify.json" > /dev/null
.venv/bin/python -c "import json; d=json.load(open('$D/verify.json')); print(d['median_similarity'], [f for f in d['repeat_inconsistencies'] if f.get('kind')=='rhythm'][:3])"
```

Expected: median ≥ 0.983 (no regression). Read the PDF (page 1 at minimum) with the Read tool and confirm bars 2 and 4 look identical and nothing else regressed (beams, pedal under bass staff, no staff labels).

- [ ] **Step 4: Docs sync + notes**

README.md — in the quantization paragraph (`grep -n "deliberate and conservative" README.md`), after the pedal-aware clause, add:

```
Repeated bars keep each other honest: when the same figure recurs and one instance was played with a uniform rush/drag, quantize de-shifts it toward the group's cleanest instance before snapping (evidence-gated so genuine variation is flagged, never rewritten; `--no-repeat-align` disables), and `verify` flags rhythm-divergent repeat pairs it didn't fix.
```

CLAUDE.md — in the Notation sanity section, after the articulation bullet, add:

```
- **Repeat alignment**: `quantize` de-shifts a uniformly rushed instance of a repeated bar toward the group's cleanest instance before snapping (report in summary `repeat_alignment`; `--no-repeat-align` disables). Gated hard — non-uniform divergence is only flagged (also by `verify` as `repeat_inconsistencies` kind "rhythm"); copy non-applied flags into CLEANUP_NOTES.
```

CLEANUP_NOTES.md (Mirrors) — replace the "bar 2 aligned to its bar-4 reference" section's last sentence with a note that the pipeline now does this automatically (repeat alignment), and add any non-applied `repeat_alignment` flags from the Step 2 quantize summary as verify-by-ear items.

- [ ] **Step 5: Full test suite + commit**

```bash
for t in scripts/test_repeat_align.py scripts/test_quantize_pedal.py scripts/test_quantize_grid.py scripts/test_voicing.py scripts/test_clef.py scripts/test_modulation_guard.py scripts/test_simplify_score.py scripts/test_midi_pedal.py; do .venv/bin/python "$t" | tail -1; done
git add README.md CLAUDE.md
git commit -m "docs: repeat alignment in quantize + verify rhythm cross-check

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

Expected: all test files green; commit lands.
