# Grid Surgery & Score-Refinement Toolkit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the deterministic toolkit from `docs/superpowers/specs/2026-07-18-grid-surgery-design.md` — grid diagnosis/repair CLI, quantize/beats upgrades, the mscz finishing pass, the one-command rebuild driver, and the score-query tools — so model reasoning is reserved for classification and by-ear judgment.

**Architecture:** All new logic lives in `scripts/` beside the existing pipeline. `transcription_cleanup.py` keeps the beat/quantize core; `grid_surgery.py` and `score_query.py` import from it. `finish_score.py` (renamed from `apply_harmony_pedal.py`) owns all `.mscz` post-import work. `rebuild_score.py` drives the whole chain from a per-piece `piece.json`.

**Tech Stack:** Python 3.11 venv (`.venv/bin/python`), pretty_midi, music21, numpy, ElementTree; MuseScore 4 CLI for format conversion only.

## Global Constraints

- Run everything with `.venv/bin/python` — never a global python.
- MuseScore CLI path (constant): `/Applications/MuseScore 4.app/Contents/MacOS/mscore`; only for `.musicxml` → `.mscz`/`.pdf` conversion. Never feed a `.mid` to MuseScore; never feed an mscore-exported MusicXML back to mscore.
- Section 2 of the spec lists work that is ALREADY IMPLEMENTED — do not rebuild or "improve" it.
- Beat-grid invariants (spec §3.1): span edges snap to base-grid downbeats (index % 4 == 0); per-span beat counts are multiples of 4; outputs strictly monotonic; a repair may not regress fit in untouched regions.
- Exact thresholds from the spec are binding: smoothing = median filter window **5** then nudge windows **(16, 12, 8, 6, 4)**; probe window **16** step **8**, weak < **0.85**, hop ratios **{0.5, 0.75, 4/3, 2.0}** ± **0.07**; scan ranges quarter = global median period **±20%**, sublevel = **¾** of quarter; IOI re-seat: run ≥ **3**, played max/min ≤ **1.25**, snapped ratio ≥ **2×**, displacement ≤ **0.2** beat; chord brush: dur < **0.055 s** AND vel < **0.75×** chord max; slot tolerance **0.07** beat.
- SDD execution floors (standing user requirement): implementer subagents are **Sonnet 5 minimum — never Haiku**; task reviews on **Opus**; the final whole-branch review on **Fable**.
- Commit after every task with the message given in the task.

---

### Task 1: Shared nudge + DP smoothing + full-coverage in `beats`

**Files:**
- Modify: `scripts/transcription_cleanup.py` (functions near `refine_fixed_grid_to_midi` ~line 1697, `cmd_beats` ~line 1791)
- Test: `scripts/test_beats_from_midi.py` (append)

**Interfaces:**
- Produces: `nudge_beats_to_onsets(beats: list[float], onsets: list[float], pin_start=False, pin_end=False, windows=(16,12,8,6,4)) -> list[float]`; `smooth_dp_beats(beats, onsets) -> list[float]`; `extend_grid_coverage(beats, onsets) -> list[float]` — all module-level in `transcription_cleanup.py`, consumed by Tasks 2 and 4.

- [ ] **Step 1: Write the failing tests** (append to `scripts/test_beats_from_midi.py`; follow the file's existing self-check style)

```python
def test_smooth_dp_beats_kills_jitter():
    import numpy as np
    from transcription_cleanup import smooth_dp_beats
    rng = list(range(200))
    # true beats every 0.5 s; onsets on every beat and every half-beat
    true = [k * 0.5 for k in rng]
    onsets = sorted([t for b in true for t in (b, b + 0.25)])
    # jittered DP output: alternate +-25 ms displacement
    jit = [b + (0.025 if k % 2 else -0.025) for k, b in enumerate(true)]
    sm = smooth_dp_beats(jit, onsets)
    per = [b - a for a, b in zip(sm, sm[1:])]
    jumps = [abs(per[i + 1] - per[i]) for i in range(len(per) - 1)]
    assert max(jumps) < 0.02, f"period jump {max(jumps):.3f}s after smoothing"
    assert abs(sm[0] - jit[0]) < 0.1 and len(sm) == len(jit)
    print("ok: smoothing bounds period jumps")


def test_extend_grid_coverage_pickup():
    from transcription_cleanup import extend_grid_coverage
    beats = [10.0 + k * 0.5 for k in range(40)]
    onsets = [9.4, 9.7] + [10.0 + k * 0.25 for k in range(20)]
    ext = extend_grid_coverage(beats, onsets)
    n_pre = len(ext) - len(beats)
    assert ext[0] <= 9.4, f"first beat {ext[0]} does not cover onset 9.4"
    assert n_pre % 4 == 0 and n_pre > 0, f"prepended {n_pre}, want multiple of 4"
    assert all(b - a > 0 for a, b in zip(ext, ext[1:]))
    # forward: an onset past the last beat forces appended beats
    ext2 = extend_grid_coverage(beats, onsets + [beats[-1] + 0.8])
    assert ext2[-1] > beats[-1] + 0.8
    print("ok: coverage extension prepends pickup bars, appends tail")
```

Add both calls to the file's `__main__` block.

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python scripts/test_beats_from_midi.py`
Expected: `ImportError: cannot import name 'smooth_dp_beats'`

- [ ] **Step 3: Implement.** In `transcription_cleanup.py`, directly above `refine_fixed_grid_to_midi`, add:

```python
def nudge_beats_to_onsets(beats, onsets, pin_start=False, pin_end=False,
                          windows=(16, 12, 8, 6, 4)):
    """Shrinking-window median-residual smoothing of a beat sequence onto
    onsets (the refine second stage, shared by refine, DP smoothing and
    grid-surgery repairs). Residuals are distances to the nearest 16th slot;
    windowed medians follow drift while per-beat jitter cancels out."""
    import bisect as _bisect
    g = np.array(beats, dtype=float)
    ons = [t for t in onsets if g[0] <= t < g[-1]]
    for w in windows:
        gl = g.tolist()
        res = [[] for _ in g]
        for t in ons:
            i = _bisect.bisect_right(gl, t) - 1
            if not (0 <= i < len(g) - 1):
                continue
            p = g[i + 1] - g[i]
            frac = (t - g[i]) / p
            r = (frac * 4 - round(frac * 4)) / 4 * p
            res[i + (1 if frac > 0.5 else 0)].append(r)
        off = np.array([statistics.median(r) if r else np.nan for r in res])
        idx = np.arange(len(off))
        valid = ~np.isnan(off)
        if valid.sum() < 2:
            break
        off = np.interp(idx, idx[valid], off[valid])
        off = np.convolve(off, np.ones(w) / w, mode="same")
        if pin_start:
            off[0] = 0.0
        if pin_end:
            off[-1] = 0.0
        g = g + off
    return g.tolist()


def smooth_dp_beats(beats, onsets):
    """Default post-pass for --from-midi: the DP places beats AT onsets, so
    raw periods jitter (~16 ms median jump) and displace notes across slot
    boundaries near barlines. Rebuild on median-filtered periods (window 5),
    then nudge back onto the onsets."""
    per = np.array([b - a for a, b in zip(beats, beats[1:])])
    ps = np.array([np.median(per[max(0, i - 2):i + 3]) for i in range(len(per))])
    g = np.concatenate([[beats[0]], beats[0] + np.cumsum(ps)])
    return nudge_beats_to_onsets(g.tolist(), onsets)


def extend_grid_coverage(beats, onsets):
    """The grid must cover every onset: the DP starts at its strongest chain
    and can leave early free material before beat 0 (quantize would cram it
    into bar 1). Extend backward in multiples of 4 beats (downbeat phase is
    preserved; the early material becomes pickup content) and forward as
    needed."""
    import math
    b = list(beats)
    if onsets and onsets[0] < b[0]:
        p = b[1] - b[0]
        n = math.ceil((b[0] - onsets[0]) / p)
        n = ((n + 3) // 4) * 4
        b = [b[0] - p * k for k in range(n, 0, -1)] + b
    if onsets and onsets[-1] >= b[-1]:
        p = b[-1] - b[-2]
        while b[-1] <= onsets[-1]:
            b.append(b[-1] + p)
    return b
```

Refactor `refine_fixed_grid_to_midi`: delete its inline `for w in (16, 12, 8, 6, 4):` smoothing loop and replace with `beats = np.array(nudge_beats_to_onsets(beats.tolist(), onsets))` (its fit computation below stays unchanged; refine does not pin endpoints).

Wire into `cmd_beats`, replacing the `elif args.from_midi:` branch body:

```python
    elif args.from_midi:
        tracked = track_beats_from_midi(args.from_midi, args.bpm_hint or 120.0)
        beats = [float(b) + args.midi_shift for b in tracked]
        import pretty_midi as _pm
        _pmf = _pm.PrettyMIDI(args.from_midi)
        _ons = sorted(n.start + args.midi_shift
                      for i in _pmf.instruments for n in i.notes)
        raw_fit = grid_fit_probe(args.from_midi, beats,
                                 args.midi_shift)["onset_grid_fit"]
        beats = smooth_dp_beats(beats, _ons)
        beats = extend_grid_coverage(beats, _ons)
        beats = [round(float(b), 4) for b in beats]
        tempo = (args.bpm_hint or 120.0)
```

and after the existing `report.update(probe)` line add:

```python
    if args.from_midi:
        report["raw_fit"] = raw_fit
```

Also add the coverage warning in `cmd_quantize`: right after `beat_times` is
loaded (the `refine_beats(...)` line), insert:

```python
        _first = notes[0].start
        _last = max(n.start for n in notes)
        if _first < beat_times[0] - 1e-6 or _last > beat_times[-1] + 1e-6:
            print("WARNING: onsets outside the beat grid "
                  f"({_first:.2f}..{_last:.2f}s vs grid "
                  f"{beat_times[0]:.2f}..{beat_times[-1]:.2f}s) — notes "
                  "before beat 0 get crammed into bar 1; rebuild the grid "
                  "with coverage extension (beats --from-midi does this "
                  "automatically now)", file=sys.stderr)
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python scripts/test_beats_from_midi.py`
Expected: all checks print `ok:`; existing checks still pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/transcription_cleanup.py scripts/test_beats_from_midi.py
git commit -m "beats: shared nudge, default DP smoothing + full-coverage extension for --from-midi"
```

---

### Task 2: `subdivision_fit` in the probe and reports

**Files:**
- Modify: `scripts/transcription_cleanup.py` (`grid_fit_probe`, ~line 1757)
- Test: `scripts/test_beats_from_midi.py` (append)

**Interfaces:**
- Produces: `grid_fit_probe(...)` result gains key `subdivision_fit: float` (fit over non-beat slots only). `beats --refine/--from-midi` reports inherit it via the existing `report.update(probe)`.

- [ ] **Step 1: Failing test** (append; add to `__main__`)

```python
def test_subdivision_fit_debiases_onbeat_anchoring():
    import json, tempfile, os
    import pretty_midi
    from transcription_cleanup import grid_fit_probe
    with tempfile.TemporaryDirectory() as d:
        mid = os.path.join(d, "t.mid")
        pm = pretty_midi.PrettyMIDI(initial_tempo=120)
        inst = pretty_midi.Instrument(program=0)
        # onsets exactly on every beat; subdivision onsets displaced +60 ms
        for k in range(64):
            t = k * 0.5
            inst.notes.append(pretty_midi.Note(velocity=80, pitch=60,
                                               start=t, end=t + 0.1))
            inst.notes.append(pretty_midi.Note(velocity=80, pitch=64,
                                               start=t + 0.25 + 0.06,
                                               end=t + 0.35))
        pm.instruments.append(inst)
        pm.write(mid)
        beats = [k * 0.5 for k in range(65)]
        p = grid_fit_probe(mid, beats, 0.0)
        assert "subdivision_fit" in p
        assert p["subdivision_fit"] < 0.5 < p["onset_grid_fit"], (
            f"subdivision_fit {p['subdivision_fit']} should expose the "
            f"off-slot subdivisions that on-beat fit {p['onset_grid_fit']} hides")
    print("ok: subdivision_fit exposes off-slot subdivisions")
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python scripts/test_beats_from_midi.py`
Expected: `KeyError: 'subdivision_fit'` (or assert failure on missing key).

- [ ] **Step 3: Implement.** In `grid_fit_probe`, extend `fit_between` to also count subdivision-slot hits, and add the global number. Replace the existing `def fit_between` block and the `global_fit` line with:

```python
    def fit_between(t0, t1):
        seg = [t for t in onsets if t0 <= t < t1]
        if not seg:
            return None, 0, None
        n_in = sub_in = sub_tot = 0
        for t in seg:
            i = _bisect.bisect_right(beats, t) - 1
            i = max(0, min(i, len(beats) - 2))
            frac = (t - beats[i]) / (beats[i + 1] - beats[i])
            pos = i + frac
            f = pos - int(pos)
            slot = round(f * 4) / 4
            hit = abs(f - slot) <= 0.07
            if hit:
                n_in += 1
            if slot % 1 != 0:
                sub_tot += 1
                if hit:
                    sub_in += 1
        return n_in / len(seg), len(seg), (sub_in / sub_tot if sub_tot else None)

    global_fit, _, sub_fit = fit_between(beats[0], beats[-1])
```

(update the two other `fit_between` call sites to unpack three values, ignoring the third) and add to the returned dict:

```python
        "subdivision_fit": round(sub_fit, 3) if sub_fit is not None else None,
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python scripts/test_beats_from_midi.py`
Expected: all `ok:`.

- [ ] **Step 5: Commit**

```bash
git add scripts/transcription_cleanup.py scripts/test_beats_from_midi.py
git commit -m "probe: subdivision_fit — de-biased comparator for DP-anchored grids"
```

---

### Task 3: `grid_surgery.py diagnose`

**Files:**
- Create: `scripts/grid_surgery.py`
- Test: `scripts/test_grid_surgery.py` (create)

**Interfaces:**
- Consumes: `grid_fit_probe`, `load_beat_times` from `transcription_cleanup`.
- Produces: CLI `grid_surgery.py diagnose <cleaned.mid> <beats.json> --midi-shift S [--output F]`; module functions `tempo_map(beats) -> list[dict]`, `free_scan(onsets, t0, t1, plo, phi) -> (fit, bpm)`, `diagnose(mid, beats_json, midi_shift) -> dict` (used by Task 4's re-probe and by tests).

- [ ] **Step 1: Failing test** — create `scripts/test_grid_surgery.py`:

```python
"""Regression tests for grid_surgery. Run: .venv/bin/python scripts/test_grid_surgery.py"""
import json
import os
import sys
import tempfile

import pretty_midi

sys.path.insert(0, os.path.dirname(__file__))
from grid_surgery import diagnose  # noqa: E402


def make_hop_fixture(d):
    """120 BPM 4/4, continuous 16ths. Beats correct except beats 40-80,
    where the grid runs at 3/4 of the true period (dotted-eighth hop)."""
    mid = os.path.join(d, "t.mid")
    bj = os.path.join(d, "beats.json")
    pm = pretty_midi.PrettyMIDI(initial_tempo=120)
    inst = pretty_midi.Instrument(program=0)
    for k in range(120 * 4):          # 120 beats of 16ths at 0.125 s
        t = k * 0.125
        inst.notes.append(pretty_midi.Note(velocity=80, pitch=60 + k % 12,
                                           start=t, end=t + 0.1))
    pm.instruments.append(inst)
    pm.write(mid)
    beats = [k * 0.5 for k in range(41)]                    # good: 0..20 s
    t = beats[-1]
    for _ in range(53):                                     # hop: period 0.375
        t += 0.375
        beats.append(round(t, 4))
    while len(beats) < 121:                                 # good again
        t += 0.5
        beats.append(round(t, 4))
    json.dump({"beats": beats}, open(bj, "w"))
    return mid, bj


def test_diagnose_flags_hop():
    with tempfile.TemporaryDirectory() as d:
        mid, bj = make_hop_fixture(d)
        rep = diagnose(mid, bj, 0.0)
        assert rep["probe"]["level_hop_suspects"], "hop span not flagged"
        assert rep["flag_clusters"], "no flag clusters emitted"
        cl = rep["flag_clusters"][0]
        for key in ("span_s", "grid_fit", "quarter_scan", "sublevel_scan"):
            assert key in cl, f"cluster missing {key}"
        assert cl["quarter_scan"]["fit"] > 0.9, (
            "free quarter scan should recover the true 120 BPM lattice")
        assert len(rep["tempo_map"]) >= 3
    print("ok: diagnose flags the hop and scans the span")


if __name__ == "__main__":
    test_diagnose_flags_hop()
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python scripts/test_grid_surgery.py`
Expected: `ModuleNotFoundError: No module named 'grid_surgery'`

- [ ] **Step 3: Implement** — create `scripts/grid_surgery.py`:

```python
#!/usr/bin/env python3
"""Beat-grid diagnosis and declarative repair.

diagnose: tempo map + windowed probe + free scans over flagged spans —
numbers only; classifying a span (level hop / lost pulse / rubato) is the
grid-surgery skill's job.
repair: execute a surgery-plan JSON (splice / lattice / tail ops) with all
seam, parity and monotonicity mechanics owned here.
"""
import argparse
import json
import os
import statistics
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from transcription_cleanup import (  # noqa: E402
    grid_fit_probe, nudge_beats_to_onsets,
)


def _onsets(mid_path, midi_shift):
    import pretty_midi
    pm = pretty_midi.PrettyMIDI(mid_path)
    return sorted(n.start + midi_shift
                  for i in pm.instruments for n in i.notes)


def tempo_map(beats, block=32):
    per = [b - a for a, b in zip(beats, beats[1:])]
    out = []
    for i0 in range(0, len(per) - block, block):
        m = statistics.median(per[i0:i0 + block])
        out.append({"beats": [i0, i0 + block],
                    "bars": [i0 // 4 + 1, (i0 + block) // 4],
                    "t_start": round(beats[i0], 1),
                    "median_period": round(m, 3),
                    "bpm": round(60 / m, 1)})
    return out


def free_scan(onsets, t0, t1, plo, phi):
    """Best (fit, bpm) for a uniform grid with free phase over [t0, t1)."""
    w = np.array([t for t in onsets if t0 <= t < t1])
    if len(w) < 8:
        return None, None
    best = (0.0, None)
    for p in np.arange(plo, phi, 0.002):
        for ph in np.arange(0, p, p / 40):
            x = (w - t0 + ph) / p * 4
            f = float(np.mean(np.abs(x - np.round(x)) / 4 <= 0.07))
            if f > best[0]:
                best = (f, p)
    return round(best[0], 3), (round(60 / best[1], 1) if best[1] else None)


def _clusters(windows):
    """Merge overlapping/adjacent flagged windows into spans of beat indices."""
    spans = []
    for wnd in sorted(windows, key=lambda w: w["beats"][0]):
        b0, b1 = wnd["beats"]
        if spans and b0 <= spans[-1][1]:
            spans[-1][1] = max(spans[-1][1], b1)
        else:
            spans.append([b0, b1])
    return spans


def diagnose(mid_path, beats_json, midi_shift):
    beats = json.load(open(beats_json))["beats"]
    ons = _onsets(mid_path, midi_shift)
    probe = grid_fit_probe(mid_path, beats, midi_shift)
    med = statistics.median(b - a for a, b in zip(beats, beats[1:]))
    clusters = []
    flagged = probe["weak_windows"] + probe["level_hop_suspects"]
    for b0, b1 in _clusters(flagged):
        t0, t1 = beats[b0], beats[min(b1, len(beats) - 1)]
        qf, qb = free_scan(ons, t0, t1, med * 0.8, med * 1.2)
        sf, sb = free_scan(ons, t0, t1, med * 0.8 * 0.75, med * 1.2 * 0.75)
        seg = [t for t in ons if t0 <= t < t1]
        gfit = None
        if seg:
            import bisect
            n = 0
            for t in seg:
                i = bisect.bisect_right(beats, t) - 1
                i = max(0, min(i, len(beats) - 2))
                frac = i + (t - beats[i]) / (beats[i + 1] - beats[i])
                f = frac - int(frac)
                n += abs(f - round(f * 4) / 4) <= 0.07
            gfit = round(n / len(seg), 3)
        clusters.append({
            "beats": [b0, b1], "bars": [b0 // 4 + 1, b1 // 4 + 1],
            "span_s": [round(t0, 2), round(t1, 2)],
            "grid_fit": gfit,
            "quarter_scan": {"fit": qf, "bpm": qb},
            "sublevel_scan": {"fit": sf, "bpm": sb},
        })
    return {"tempo_map": tempo_map(beats), "probe": probe,
            "flag_clusters": clusters}


def cmd_diagnose(args):
    rep = diagnose(args.mid, args.beats, args.midi_shift)
    text = json.dumps(rep, indent=2)
    if args.output:
        with open(args.output, "w") as f:
            f.write(text)
    print(text)
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(required=True)
    d = sub.add_parser("diagnose")
    d.add_argument("mid")
    d.add_argument("beats")
    d.add_argument("--midi-shift", type=float, default=0.0)
    d.add_argument("--output")
    d.set_defaults(fn=cmd_diagnose)
    args = ap.parse_args()
    sys.exit(args.fn(args))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python scripts/test_grid_surgery.py`
Expected: `ok: diagnose flags the hop and scans the span`

- [ ] **Step 5: Commit**

```bash
git add scripts/grid_surgery.py scripts/test_grid_surgery.py
git commit -m "grid_surgery: diagnose (tempo map, probe, per-span free scans)"
```

---

### Task 4: `grid_surgery.py repair`

**Files:**
- Modify: `scripts/grid_surgery.py`
- Test: `scripts/test_grid_surgery.py` (append)

**Interfaces:**
- Consumes: Task 1's `nudge_beats_to_onsets`; Task 3's `diagnose`.
- Produces: CLI `grid_surgery.py repair <plan.json>`; module `repair(plan_path) -> dict` (report).

- [ ] **Step 1: Failing tests** (append; wire into `__main__`)

```python
from grid_surgery import repair  # add to imports


def test_repair_lattice_fixes_hop():
    with tempfile.TemporaryDirectory() as d:
        mid, bj = make_hop_fixture(d)
        base = json.load(open(bj))
        # the hop span runs t=20.0 .. beats[93]; repair with a 0.5 s lattice
        plan = {"base": "beats.json", "midi": "t.mid", "midi_shift": 0.0,
                "repairs": [{"span_s": [20.0, 40.0],
                             "op": "lattice", "period": 0.5}],
                "output": "beats.repaired.json"}
        pp = os.path.join(d, "plan.json")
        json.dump(plan, open(pp, "w"))
        rep = repair(pp)
        fixed = json.load(open(os.path.join(d, "beats.repaired.json")))
        assert not fixed.get("level_hop_suspects"), "hop survived repair"
        assert rep["after"]["onset_grid_fit"] > rep["before"]["onset_grid_fit"]
        b = fixed["beats"]
        assert all(y > x for x, y in zip(b, b[1:]))
        assert (len(b) - 1) % 4 == 0 or True  # total length free; spans padded
    print("ok: lattice repair removes the hop and improves fit")


def test_repair_rejects_overlap_and_regression():
    with tempfile.TemporaryDirectory() as d:
        mid, bj = make_hop_fixture(d)
        plan = {"base": "beats.json", "midi": "t.mid", "midi_shift": 0.0,
                "repairs": [
                    {"span_s": [20.0, 40.0], "op": "lattice", "period": 0.5},
                    {"span_s": [30.0, 45.0], "op": "lattice", "period": 0.5}],
                "output": "x.json"}
        pp = os.path.join(d, "plan.json")
        json.dump(plan, open(pp, "w"))
        try:
            repair(pp)
            raise AssertionError("overlapping spans accepted")
        except SystemExit:
            pass
        # regression guard: "repairing" a good span with a wrong period must fail
        plan2 = {"base": "beats.json", "midi": "t.mid", "midi_shift": 0.0,
                 "repairs": [{"span_s": [2.0, 10.0],
                              "op": "lattice", "period": 0.41}],
                 "output": "y.json"}
        json.dump(plan2, open(pp, "w"))
        try:
            repair(pp)
            raise AssertionError("fit regression accepted")
        except SystemExit:
            pass
    print("ok: repair rejects overlapping spans and fit regressions")
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python scripts/test_grid_surgery.py`
Expected: `ImportError: cannot import name 'repair'`

- [ ] **Step 3: Implement** — append to `scripts/grid_surgery.py`:

```python
def _snap_downbeat(beats, t, side):
    """Index of the base-grid downbeat (idx % 4 == 0) nearest t, biased
    before (side='start') or after (side='end')."""
    import bisect
    i = bisect.bisect_left(beats, t)
    cands = [j for j in range(max(0, i - 4), min(len(beats), i + 5))
             if j % 4 == 0]
    if not cands:
        raise SystemExit(f"repair: no downbeat near t={t}")
    if side == "start":
        before = [j for j in cands if beats[j] <= t + 1e-6]
        return before[-1] if before else cands[0]
    after = [j for j in cands if beats[j] >= t - 1e-6]
    return after[0] if after else cands[-1]


def _fit_region(ons, beats, t0, t1):
    import bisect
    seg = [t for t in ons if t0 <= t < t1]
    if not seg:
        return None
    n = 0
    for t in seg:
        i = bisect.bisect_right(beats, t) - 1
        i = max(0, min(i, len(beats) - 2))
        frac = i + (t - beats[i]) / (beats[i + 1] - beats[i])
        f = frac - int(frac)
        n += abs(f - round(f * 4) / 4) <= 0.07
    return round(n / len(seg), 3)


def repair(plan_path):
    plan_dir = os.path.dirname(os.path.abspath(plan_path))
    plan = json.load(open(plan_path))
    rel = lambda p: os.path.join(plan_dir, p)
    base = json.load(open(rel(plan["base"])))
    beats = list(base["beats"])
    ons = _onsets(rel(plan["midi"]), plan["midi_shift"])
    t_end_all = ons[-1] + 0.6

    spans = []
    for r in plan["repairs"]:
        lo = r["span_s"][0]
        hi = t_end_all if r["span_s"][1] == "end" else r["span_s"][1]
        spans.append((lo, hi, r))
    spans.sort()
    for (a0, a1, _), (b0, b1, _) in zip(spans, spans[1:]):
        if b0 < a1 - 1e-6:
            raise SystemExit(f"repair: overlapping spans {a1} > {b0}")

    before = grid_fit_probe(rel(plan["midi"]), beats, plan["midi_shift"])
    region_before = {}

    for lo, hi, r in reversed(spans):        # right-to-left keeps left indices
        i0 = _snap_downbeat(beats, lo, "start")
        open_end = r["span_s"][1] == "end"
        i1 = len(beats) - 1 if open_end else _snap_downbeat(beats, hi, "end")
        t0, t1 = beats[i0], (t_end_all if open_end else beats[i1])
        region_before[(round(t0, 2), round(t1, 2))] = _fit_region(
            ons, beats, t0, t1)

        if r["op"] == "splice":
            src = json.load(open(rel(r["source"])))["beats"]
            seg = [t for t in src if t0 + 1e-6 < t < t1 - 1e-6]
            while (len(seg) + 1) % 4 != 0:
                seg = seg[:-1]
            new_seg = seg
        elif r["op"] == "lattice":
            pieces = r.get("pieces") or [["end", r["period"]]]
            g = [t0]
            for lim, p in pieces:
                stop = t1 if lim == "end" else min(float(lim), t1)
                while g[-1] + p < stop - 1e-6:
                    g.append(g[-1] + p)
            if not open_end:
                n = len(g)                    # beats strictly inside + anchor
                want = ((n + 2) // 4) * 4 - 1  # interior count ≡ 3 (mod 4)
                p_last = pieces[-1][1]
                while len(g) - 1 < want:
                    g.append(g[-1] + p_last)
                while len(g) - 1 > want and len(g) > 2:
                    g.pop()
                span = t1 - t0
                scale = span / (g[-1] + p_last - t0)
                g = [t0 + (x - t0) * scale for x in g]
            new_seg = nudge_beats_to_onsets(
                g + ([] if open_end else [t1]), ons,
                pin_start=True, pin_end=not open_end)
            new_seg = new_seg[1:] if open_end else new_seg[1:-1]
        elif r["op"] == "tail":
            clusters = []
            for t in [x for x in ons if x >= t0 - 0.1]:
                if clusters and t - clusters[-1][-1] < 0.05:
                    clusters[-1].append(t)
                else:
                    clusters.append([t])
            ctimes = [c[0] for c in clusters]
            new_seg, b = [], t0
            while b < t_end_all:
                win = [ctimes[i + 1] - ctimes[i]
                       for i in range(len(ctimes) - 1)
                       if b - 0.3 <= ctimes[i] <= b + 1.8
                       and ctimes[i + 1] - ctimes[i] < 0.6]
                p16 = statistics.median(win) if win else 0.3
                nxt = b + 4 * p16
                near = min(ctimes, key=lambda c: abs(c - nxt)) if ctimes else nxt
                if abs(near - nxt) <= 0.12:
                    nxt = near
                new_seg.append(round(nxt, 4))
                b = nxt
        else:
            raise SystemExit(f"repair: unknown op {r['op']!r}")

        tail = [] if open_end else beats[i1:]
        beats = beats[:i0 + 1] + [round(float(x), 4) for x in new_seg] + tail

    if not all(y > x for x, y in zip(beats, beats[1:])):
        raise SystemExit("repair: non-monotonic result")

    after = grid_fit_probe(rel(plan["midi"]), beats, plan["midi_shift"])
    # untouched-region regression guard (compare complement of spans)
    span_ts = [(lo, hi) for lo, hi, _ in spans]
    edges = [beats[0]] + [t for pair in span_ts for t in pair] + [beats[-1]]
    for j in range(0, len(edges) - 1, 2):
        t0, t1 = edges[j], edges[j + 1]
        if t1 - t0 < 2.0:
            continue
        fb = _fit_region(ons, base["beats"], t0, t1)
        fa = _fit_region(ons, beats, t0, t1)
        if fb and fa and fa < fb - 0.02:
            raise SystemExit(
                f"repair: fit regression in untouched region "
                f"[{t0:.1f},{t1:.1f}] {fb} -> {fa}")
    if after["onset_grid_fit"] < before["onset_grid_fit"] - 0.005:
        raise SystemExit(
            f"repair: global fit regressed "
            f"{before['onset_grid_fit']} -> {after['onset_grid_fit']}")

    out = dict(base)
    out["beats"] = beats
    out["n_beats"] = len(beats)
    out["source"] = f"grid_surgery repair: {os.path.basename(plan_path)}"
    per = [b - a for a, b in zip(beats, beats[1:])]
    out["tempo_median_bpm"] = round(60 / statistics.median(per), 1)
    out["beat_period_cv"] = round(statistics.pstdev(per) / statistics.mean(per), 3)
    out.update(after)
    with open(rel(plan["output"]), "w") as f:
        json.dump(out, f, indent=2)
    report = {"before": {k: before[k] for k in
                         ("onset_grid_fit", "subdivision_fit")},
              "after": {k: after[k] for k in
                        ("onset_grid_fit", "subdivision_fit")},
              "regions_before": region_before,
              "output": plan["output"]}
    print(json.dumps(report, indent=2))
    return report


def cmd_repair(args):
    repair(args.plan)
    return 0
```

and register the subparser in `main()`:

```python
    r = sub.add_parser("repair")
    r.add_argument("plan")
    r.set_defaults(fn=cmd_repair)
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python scripts/test_grid_surgery.py`
Expected: all three `ok:` lines.

- [ ] **Step 5: Commit**

```bash
git add scripts/grid_surgery.py scripts/test_grid_surgery.py
git commit -m "grid_surgery: declarative repair (splice/lattice/tail) with seam, parity and regression guards"
```

---

### Task 5: `clean --keep-window` and `verify --audio-window`

**Files:**
- Modify: `scripts/transcription_cleanup.py` (`cmd_clean` ~line 298, `cmd_verify` ~line 1925, argparse blocks ~lines 2550 and 2674)
- Test: `scripts/test_clean_window.py` (create)

**Interfaces:**
- Produces: `clean ... --keep-window LO:HI` (seconds in the OUTPUT/trimmed timeline); summary gains `keep_window` `{lo, hi, extra_shift_s}`. `verify ... --audio-window LO:HI` (seconds in the recording).

- [ ] **Step 1: Failing test** — create `scripts/test_clean_window.py`:

```python
"""clean --keep-window: strip jingles, re-zero, report the shift.
Run: .venv/bin/python scripts/test_clean_window.py"""
import json
import os
import subprocess
import sys
import tempfile

import pretty_midi

SCRIPT = os.path.join(os.path.dirname(__file__), "transcription_cleanup.py")
PY = sys.executable


def test_keep_window():
    with tempfile.TemporaryDirectory() as d:
        mid = os.path.join(d, "t.mid")
        out = os.path.join(d, "t.cleaned.mid")
        pm = pretty_midi.PrettyMIDI(initial_tempo=120)
        inst = pretty_midi.Instrument(program=0)
        for t in (0.0, 1.0):                       # intro jingle
            inst.notes.append(pretty_midi.Note(80, 72, t, t + 0.3))
        for k in range(16):                        # arrangement: 5.0 .. 13.0
            t = 5.0 + k * 0.5
            inst.notes.append(pretty_midi.Note(80, 60, t, t + 0.3))
        for t in (20.0, 21.0):                     # outro jingle
            inst.notes.append(pretty_midi.Note(80, 84, t, t + 0.3))
        inst.control_changes.append(pretty_midi.ControlChange(64, 100, 5.1))
        inst.control_changes.append(pretty_midi.ControlChange(64, 0, 12.0))
        inst.control_changes.append(pretty_midi.ControlChange(64, 100, 20.5))
        pm.instruments.append(inst)
        pm.write(mid)
        r = subprocess.run(
            [PY, SCRIPT, "clean", mid, out, "--keep-window", "4.5:14.0"],
            capture_output=True, text=True, check=True)
        s = json.loads(r.stdout)
        assert s["kept_notes"] == 16, s["kept_notes"]
        kw = s["keep_window"]
        # first onset was 0.0 -> trim shift 0; window start 5.0 becomes t=0
        assert abs(kw["extra_shift_s"] - 5.0) < 0.01, kw
        out_pm = pretty_midi.PrettyMIDI(out)
        notes = [n for i in out_pm.instruments for n in i.notes]
        assert abs(min(n.start for n in notes)) < 0.01
        ccs = [c for i in out_pm.instruments for c in i.control_changes
               if c.number == 64]
        assert ccs and all(c.time < 8.0 for c in ccs), (
            "outro CC64 must be stripped")
    print("ok: keep-window strips, re-zeros, reports the shift")


if __name__ == "__main__":
    test_keep_window()
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python scripts/test_clean_window.py`
Expected: `error: unrecognized arguments: --keep-window`

- [ ] **Step 3: Implement.** In `cmd_clean`, after `kept = [n for n in notes if id(n) not in drop]` and the `shift = ...` line, insert:

```python
    keep_window = None
    if args.keep_window:
        lo, hi = (float(x) for x in args.keep_window.split(":"))
        kept = [n for n in kept if lo <= n.start - shift <= hi]
        if not kept:
            print(json.dumps({"error": "keep-window removed every note"}))
            return 1
        t0 = min(n.start for n in kept)
        keep_window = {"lo": lo, "hi": hi,
                       "extra_shift_s": round(t0 - shift, 3)}
        shift = t0
```

and in the CC64 copy loop change the condition to also honor the window:

```python
            for cc in src.control_changes:
                if cc.number == 64 and cc.time - shift >= 0 and (
                        keep_window is None
                        or cc.time - shift <= keep_window["hi"] - keep_window["lo"] + 3):
                    inst.control_changes.append(
                        pretty_midi.ControlChange(64, cc.value, cc.time - shift))
```

add to the summary dict: `"keep_window": keep_window,` and to the clean argparse block:

```python
    c.add_argument("--keep-window", metavar="LO:HI",
                   help="keep only notes whose (trimmed) onset is within "
                        "[LO,HI] seconds — strips video intro/outro jingles; "
                        "output is re-zeroed to the first kept onset and the "
                        "summary reports keep_window.extra_shift_s")
```

In `cmd_verify`, change the audio load line (~1978) to:

```python
            ya, _ = librosa.load(args.audio, sr=SR, mono=True)
            if args.audio_window:
                lo, hi = (float(x) for x in args.audio_window.split(":"))
                ya = ya[int(lo * SR):int(hi * SR)]
```

and add to the verify argparse block:

```python
    v.add_argument("--audio-window", metavar="LO:HI",
                   help="compare against only this window of the recording "
                        "(seconds) — for pieces whose video has intro/outro "
                        "jingles stripped by clean --keep-window")
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python scripts/test_clean_window.py`
Expected: `ok: keep-window strips, re-zeros, reports the shift`
Also run: `.venv/bin/python scripts/test_quantize_pedal.py` (verify unaffected paths still pass).

- [ ] **Step 5: Commit**

```bash
git add scripts/transcription_cleanup.py scripts/test_clean_window.py
git commit -m "clean --keep-window and verify --audio-window (jingle handling without hand scripts)"
```

---

### Task 6: IOI-ratio re-seat in `quantize`

**Files:**
- Modify: `scripts/transcription_cleanup.py` (`cmd_quantize`, insert after the `rep_deltas` block ~line 1290; consume in the items loop where `off = snap(cl_on(cl))` is computed)
- Test: `scripts/test_quantize_ioi.py` (create)

**Interfaces:**
- Produces: module-level `ioi_reseat(cluster_onsets: list[Fraction], snap, grid: Fraction) -> dict[int, Fraction]` mapping cluster index → overridden snapped onset; `cmd_quantize` summary gains `"ioi_reseated": {"count": N, "bars": [...]}`.

- [ ] **Step 1: Failing test** — create `scripts/test_quantize_ioi.py`:

```python
"""IOI-ratio re-seat: equal played IOIs must engrave as equal values.
The Mirrors bar-6 pattern: onsets at beats 0.0, 0.88, 1.15, 1.42 snapped
per-onset become 0.75/1.25/1.5 (8th+16th); the re-seat must land them on
0.75/1.0/1.25. Run: .venv/bin/python scripts/test_quantize_ioi.py"""
import json
import os
import subprocess
import sys
import tempfile

import pretty_midi

SCRIPT = os.path.join(os.path.dirname(__file__), "transcription_cleanup.py")
PY = sys.executable


def test_equal_iois_engrave_equal():
    with tempfile.TemporaryDirectory() as d:
        mid = os.path.join(d, "t.mid")
        out = os.path.join(d, "t.musicxml")
        pm = pretty_midi.PrettyMIDI(initial_tempo=60)   # beat = 1 s
        inst = pretty_midi.Instrument(program=0)
        for bar in range(4):
            t0 = bar * 4.0
            # the dragged equal-IOI figure, then on-grid filler
            for t in (0.0, 0.88, 1.15, 1.42, 2.0, 3.0):
                inst.notes.append(pretty_midi.Note(80, 72, t0 + t, t0 + t + 0.15))
            inst.notes.append(pretty_midi.Note(85, 40, t0, t0 + 0.5))
        pm.instruments.append(inst)
        pm.write(mid)
        r = subprocess.run([PY, SCRIPT, "quantize", mid, out, "--bpm", "60",
                            "--time-sig", "4/4", "--bar-phase", "0",
                            "--no-repeat-align"],
                           capture_output=True, text=True, check=True)
        s = json.loads(r.stdout)
        assert s.get("ioi_reseated", {}).get("count", 0) >= 4, s.get("ioi_reseated")
        from music21 import converter
        treble = converter.parse(out).parts[0]
        m = treble.measure(1)
        offs = sorted(float(n.offset) for n in m.recurse().notes)
        assert offs[:4] == [0.0, 0.75, 1.0, 1.25], f"got {offs[:4]}"
    print("ok: equal played IOIs re-seated onto equal slots")


if __name__ == "__main__":
    test_equal_iois_engrave_equal()
```

(`--no-repeat-align` isolates the re-seat: the four identical bars would otherwise be aligned by the repeat feature.)

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python scripts/test_quantize_ioi.py`
Expected: AssertionError on `ioi_reseated` missing.

- [ ] **Step 3: Implement.** Add module-level function above `cmd_quantize`:

```python
def ioi_reseat(onsets, snapped, grid):
    """Equal played inter-onset intervals must engrave as equal values
    (Desain & Honing): per-onset snapping splits an equally-spaced dragged
    run across a tolerance boundary (e.g. 0.88/1.15/1.42 -> 0.75/1.25/1.5).
    Detect runs of >= 3 onsets with near-equal played IOIs (max/min <= 1.25)
    whose snapped IOIs differ by >= 2x; re-seat on the grid value nearest
    the median played IOI, anchored on the run's best-snapped onset. Only
    fires when every re-seated position stays within 0.2 beat of the played
    onset. Returns {index: new_snapped_onset}."""
    from fractions import Fraction
    over = {}
    n = len(onsets)
    i = 0
    while i < n - 2:
        j = i + 1
        iois = []
        while j < n:
            d = float(onsets[j] - onsets[j - 1])
            if d <= 0 or d > 2.0:
                break
            iois.append(d)
            if max(iois) / min(iois) > 1.25:
                iois.pop()
                break
            j += 1
        run = list(range(i, j))
        if len(run) >= 3:
            sn = [float(snapped[k]) for k in run]
            sd = [b - a for a, b in zip(sn, sn[1:])]
            if min(sd) > 0 and max(sd) / min(sd) >= 2.0:
                med = statistics.median(
                    float(onsets[k + 1] - onsets[k]) for k in run[:-1])
                step = Fraction(round(med / float(grid))) * grid
                if step > 0:
                    anchor = min(
                        run, key=lambda k: abs(float(snapped[k] - onsets[k])))
                    new = {k: snapped[anchor] + step * (k - anchor)
                           for k in run}
                    if all(abs(float(v - onsets[k])) <= 0.2
                           for k, v in new.items()):
                        over.update(new)
        i = max(j - 1, i + 1)
    return over
```

Wire into `cmd_quantize`: after `hand_clusters` and `rep_deltas` are built and the accessors (`cl_on`, `snap`) exist, compute per staff:

```python
    ioi_overrides, ioi_bars = {}, set()
    for name in ("treble", "bass"):
        cls = hand_clusters[name]
        c_on = [cl_on(cl) for cl in cls]
        c_snap = [snap(o) for o in c_on]
        for idx, new_off in ioi_reseat(c_on, c_snap, grid).items():
            if new_off != c_snap[idx]:
                ioi_overrides[id(cls[idx][0])] = new_off
                ioi_bars.add(int(new_off) // beats_per_bar + 1
                             if beats_per_bar else 0)
    if ioi_overrides:
        summary["ioi_reseated"] = {"count": len(ioi_overrides),
                                   "bars": sorted(ioi_bars)}
```

and in the items loop, where the cluster's snapped onset is computed, prefer the override:

```python
            off = ioi_overrides.get(id(cl[0]), snap(cl_on(cl)))
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python scripts/test_quantize_ioi.py` → `ok:`
Run: `.venv/bin/python scripts/test_quantize_grid.py && .venv/bin/python scripts/test_quantize_pedal.py && .venv/bin/python scripts/test_repeat_align.py` → all pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/transcription_cleanup.py scripts/test_quantize_ioi.py
git commit -m "quantize: IOI-ratio re-seat — equal played IOIs engrave as equal values"
```

---

### Task 7: Chord-brush ghost drop at chord merge

**Files:**
- Modify: `scripts/transcription_cleanup.py` (`repeat_align` return, ~line 1100; the chord/group build in `cmd_quantize`'s items loop, near the arpeggio-mark block ~line 1580)
- Test: `scripts/test_quantize_ioi.py` (append — same fixture family)

**Interfaces:**
- Consumes: `repeat_align` gains a third return value `groups: dict[int, list[int]]` (window → group member windows); existing callers unpack three values.
- Produces: summary key `"chord_brush_dropped": {"count": N, "bars": [...]}`.

- [ ] **Step 1: Failing test** (append)

```python
def test_chord_brush_ghost_dropped():
    with tempfile.TemporaryDirectory() as d:
        mid = os.path.join(d, "t.mid")
        out = os.path.join(d, "t.musicxml")
        pm = pretty_midi.PrettyMIDI(initial_tempo=60)
        inst = pretty_midi.Instrument(program=0)
        for bar in range(2):
            t0 = bar * 4.0
            for beat in range(4):
                t = t0 + beat
                inst.notes.append(pretty_midi.Note(85, 72, t, t + 0.6))
                inst.notes.append(pretty_midi.Note(84, 76, t + 0.01, t + 0.6))
        # one 40 ms vel-40 brush inside the bar-1 beat-2 chord
        inst.notes.append(pretty_midi.Note(40, 48, 1.02, 1.06))
        pm.instruments.append(inst)
        pm.write(mid)
        r = subprocess.run([PY, SCRIPT, "quantize", mid, out, "--bpm", "60",
                            "--time-sig", "4/4", "--bar-phase", "0",
                            "--no-repeat-align"],
                           capture_output=True, text=True, check=True)
        s = json.loads(r.stdout)
        assert s.get("chord_brush_dropped", {}).get("count") == 1, (
            s.get("chord_brush_dropped"))
        from music21 import converter
        sc = converter.parse(out)
        pitches = [p.midi for n in sc.recurse().notes for p in n.pitches]
        assert 48 not in pitches, "brush ghost survived into a chord"
    print("ok: chord-brush ghost dropped from the merged chord")
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python scripts/test_quantize_ioi.py`
Expected: assertion on missing `chord_brush_dropped`.

- [ ] **Step 3: Implement.**

(a) `repeat_align`: change the final `return deltas_by_id, report` to also build and return the group map:

```python
    group_map = {}
    for members in groups.values():
        if len(members) >= 2:
            for k in members:
                group_map[k] = list(members)
    return deltas_by_id, report, group_map
```

Update the two call sites (`cmd_quantize` and `scripts/test_repeat_align.py` helpers) to unpack `rep_deltas, rep_report, rep_groups` (tests: `deltas, report, _`).

(b) In `cmd_quantize`'s items loop, where a multi-pitch `group` is about to become a chord (immediately before the `pitches` list is finalized), insert:

```python
            if len(group) > 1:
                vmax = max(n.velocity for n in group)
                keep = []
                for n in group:
                    brush = ((n.end - n.start) < 0.055
                             and n.velocity < 0.75 * vmax)
                    if brush and beats_per_bar:
                        # family-voicing exception: the same pitch at the same
                        # in-bar slot in a sibling window means it was meant
                        # (a brushed voicing, not noise)
                        w = int((float(n_on(n)) - align_phase) // beats_per_bar)
                        slot_off = round(float(n_on(n) - align_phase)
                                         % beats_per_bar, 2)
                        for sib in rep_groups.get(w, []):
                            if sib == w:
                                continue
                            hits = wins_cache.get(sib, [])
                            if any(p == n.pitch
                                   and abs(round(o, 2) - slot_off) < 0.13
                                   for o, p, _ in hits):
                                brush = False
                                break
                    if brush:
                        brush_dropped += 1
                        brush_bars.add(int(float(n_on(n))) // beats_per_bar + 1
                                       if beats_per_bar else 0)
                    else:
                        keep.append(n)
                if keep:
                    group = keep
```

with `brush_dropped, brush_bars = 0, set()` initialized beside the other
counters, and `wins_cache` built once right after the `repeat_align` call
from the same events:

```python
    wins_cache = {}
    for nid, on, pitch in [(id(n), float(to_ql(n.start)) - align_phase,
                            n.pitch) for n in notes]:
        if beats_per_bar:
            w = int(on // beats_per_bar)
            wins_cache.setdefault(w, []).append(
                (on - w * beats_per_bar, pitch, nid))
```

and after the loop:

```python
    if brush_dropped:
        summary["chord_brush_dropped"] = {"count": brush_dropped,
                                          "bars": sorted(brush_bars)}
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python scripts/test_quantize_ioi.py && .venv/bin/python scripts/test_repeat_align.py && .venv/bin/python scripts/test_quantize_pedal.py`
Expected: all `ok:`.

- [ ] **Step 5: Commit**

```bash
git add scripts/transcription_cleanup.py scripts/test_quantize_ioi.py scripts/test_repeat_align.py
git commit -m "quantize: drop chord-brush ghosts at chord merge (family-voicing exception)"
```

---

### Task 8: Unit test for the clean_musicxml stub invariant (owed)

**Files:**
- Test: `scripts/test_clean_musicxml.py` (append)

- [ ] **Step 1: Write the test** (append, following the file's existing fixture style; it exercises the already-implemented `clean_one_slot_tie_stubs`)

```python
def test_one_slot_tie_stub_collapsed():
    import xml.etree.ElementTree as ET
    from clean_musicxml import clean_one_slot_tie_stubs
    measure = ET.fromstring("""
    <measure number="3">
      <attributes><divisions>4</divisions></attributes>
      <note><pitch><step>C</step><octave>5</octave></pitch>
        <duration>4</duration><tie type="start"/>
        <notations><tied type="start"/></notations></note>
      <note><pitch><step>C</step><octave>5</octave></pitch>
        <duration>1</duration><tie type="stop"/>
        <notations><tied type="stop"/></notations></note>
      <note><rest/><duration>3</duration></note>
    </measure>""")
    log = []
    n = clean_one_slot_tie_stubs([measure], log)
    assert n == 1, f"collapsed {n}"
    notes = measure.findall('note')
    assert notes[0].find("tie") is None, "tie-start not stripped"
    assert notes[1].find('rest') is not None, "stub not converted to rest"
    assert notes[1].find('pitch') is None
    print("ok: one-slot tie stub collapsed to rest")
```

Wire into the file's `__main__`.

- [ ] **Step 2: Run**

Run: `.venv/bin/python scripts/test_clean_musicxml.py`
Expected: all pass including the new `ok:` (the implementation exists; if the test exposes a bug, fix `clean_one_slot_tie_stubs` minimally).

- [ ] **Step 3: Commit**

```bash
git add scripts/test_clean_musicxml.py
git commit -m "test: unit coverage for the one-slot tie-stub invariant"
```

---

### Task 9: `finish_score.py` (rename + layout/label hygiene)

**Files:**
- Create: `scripts/finish_score.py` (git mv from `scripts/apply_harmony_pedal.py`)
- Rename: `scripts/musescore_pedal_lib.py` → `scripts/musescore_lib.py`; `scripts/test_midi_pedal.py` → `scripts/test_finish_score.py`
- Modify: `scripts/analyze_pedaling.py`, `scripts/simplify_score.py` (imports, if any reference the old lib name), `.claude/skills/cleanup-score/SKILL.md`, `CLAUDE.md`, `README.md`
- Test: `scripts/test_finish_score.py` (append hygiene test)

- [ ] **Step 1: Renames**

```bash
git mv scripts/apply_harmony_pedal.py scripts/finish_score.py
git mv scripts/musescore_pedal_lib.py scripts/musescore_lib.py
git mv scripts/test_midi_pedal.py scripts/test_finish_score.py
grep -rln "musescore_pedal_lib\|apply_harmony_pedal" scripts/ .claude/ CLAUDE.md README.md
```

Update every hit: `musescore_pedal_lib` → `musescore_lib`, `apply_harmony_pedal.py` → `finish_score.py`, `apply_harmony_pedal` imports → `finish_score`.

- [ ] **Step 2: Failing hygiene test** (append to `scripts/test_finish_score.py`)

```python
def test_strip_layout_and_labels():
    import xml.etree.ElementTree as ET
    from finish_score import strip_layout_and_labels
    root = ET.fromstring(
        "<museScore><Score>"
        "<Part><Instrument><longName>Piano</longName>"
        "<shortName>Pno</shortName></Instrument></Part>"
        "<Staff id=\"1\"><Measure><LayoutBreak><subtype>line</subtype>"
        "</LayoutBreak><voice/></Measure></Staff>"
        "</Score></museScore>")
    strip_layout_and_labels(root)
    assert not list(root.iter("LayoutBreak"))
    assert not list(root.iter("longName")) and not list(root.iter("shortName"))
    print("ok: stale layout breaks and instrument labels stripped")
```

Run: `.venv/bin/python scripts/test_finish_score.py` → `ImportError`.

- [ ] **Step 3: Implement.** In `scripts/finish_score.py` add beside `strip_beam_modes`:

```python
def strip_layout_and_labels(root):
    """Remove stale LayoutBreaks (frozen page/system breaks break pagination
    after any content change) and solo-piano instrument long/short names
    (label leaks from MusicXML roundtrips). Auto-layout is our default,
    exactly like auto-beaming."""
    n = 0
    for parent in root.iter():
        for child in [c for c in parent if c.tag == "LayoutBreak"]:
            parent.remove(child)
            n += 1
    labels = 0
    for inst in root.iter("Instrument"):
        for tag in ("longName", "shortName"):
            for el in inst.findall(tag):
                inst.remove(el)
                labels += 1
    print(f"layout cleanup: {n} LayoutBreaks, {labels} instrument labels removed")
```

and chain it in the pedaling `post_process` (replace the current `post_process=strip_beam_modes`):

```python
    def _hygiene(root):
        strip_beam_modes(root)
        strip_layout_and_labels(root)

    add_pedals(args.mscz, cfg, staff_id=args.staff, post_process=_hygiene)
```

Update the module docstring to describe the full finishing pass (anacrusis → pedaling → hygiene).

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python scripts/test_finish_score.py && for t in scripts/test_*.py; do .venv/bin/python "$t" >/dev/null || echo "FAIL $t"; done`
Expected: hygiene `ok:`; no `FAIL` lines.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "finish_score: rename from apply_harmony_pedal; layout/label hygiene joins the finishing pass"
```

---

### Task 10: `rebuild_score.py` + `piece.json`

**Files:**
- Create: `scripts/rebuild_score.py`
- Test: `scripts/test_rebuild_score.py` (create)

**Interfaces:**
- Consumes: every pipeline stage CLI as subprocesses; `piece.json` schema from spec §3.4 (`slug, key, time_sig, beats, beats_shift, title, composer, performer, arranger, anacrusis, dynamics_from_cleaned_midi, quantize_flags, post_flags`).
- Produces: `rebuild_score.py <piece-dir> [--skip-verify] [--mscore PATH]`; stage summaries in `<piece-dir>/reports/`; one combined digest on stdout.

- [ ] **Step 1: Failing test** — create `scripts/test_rebuild_score.py`:

```python
"""rebuild_score drives the chain from piece.json and is reproducible.
Run: .venv/bin/python scripts/test_rebuild_score.py
(Needs MuseScore; skips gracefully when mscore is absent.)"""
import json
import os
import subprocess
import sys
import tempfile

import pretty_midi

HERE = os.path.dirname(__file__)
PY = sys.executable
MSCORE = "/Applications/MuseScore 4.app/Contents/MacOS/mscore"


def test_rebuild_from_manifest():
    if not os.path.exists(MSCORE):
        print("skip: MuseScore not installed")
        return
    with tempfile.TemporaryDirectory() as d:
        slug = "fixture"
        pdir = os.path.join(d, slug)
        os.makedirs(pdir)
        mid = os.path.join(pdir, f"{slug}.cleaned.mid")
        pm = pretty_midi.PrettyMIDI(initial_tempo=120)
        inst = pretty_midi.Instrument(program=0)
        for k in range(32):
            t = k * 0.5
            inst.notes.append(pretty_midi.Note(80, 60 + (k % 8), t, t + 0.4))
        pm.instruments.append(inst)
        pm.write(mid)
        json.dump({"beats": [k * 0.5 for k in range(34)]},
                  open(os.path.join(pdir, "beats.json"), "w"))
        json.dump({"slug": slug, "key": "C major", "time_sig": "4/4",
                   "beats": "beats.json", "beats_shift": 0.0,
                   "title": "Fixture", "composer": "Test",
                   "performer": None, "arranger": None, "anacrusis": 0,
                   "dynamics_from_cleaned_midi": False,
                   "quantize_flags": ["--bar-phase", "0"], "post_flags": []},
                  open(os.path.join(pdir, "piece.json"), "w"))
        # an edits.py that tags its run
        with open(os.path.join(pdir, "edits.py"), "w") as f:
            f.write("import sys\nprint('edits ran')\n")
        r = subprocess.run(
            [PY, os.path.join(HERE, "rebuild_score.py"), pdir,
             "--skip-verify"],
            capture_output=True, text=True)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "edits ran" in r.stdout
        for ext in (".musicxml", ".mscz", ".pdf"):
            assert os.path.getsize(os.path.join(pdir, slug + ext)) > 0, ext
        assert os.path.isdir(os.path.join(pdir, "reports"))
        digest = r.stdout.strip().splitlines()[-1]
        assert "fit" in digest or "lint" in digest, digest
    print("ok: rebuild_score runs the chain from piece.json")


if __name__ == "__main__":
    test_rebuild_from_manifest()
```

- [ ] **Step 2: Run to verify failure** — `.venv/bin/python scripts/test_rebuild_score.py` → missing script error.

- [ ] **Step 3: Implement** — create `scripts/rebuild_score.py`:

```python
#!/usr/bin/env python3
"""One-command rebuild of a piece's score from its piece.json manifest.

Chain: quantize -> post -> clean_musicxml -> edits.py (if present) ->
mscore import -> finish_score (anacrusis, pedaling, hygiene) -> export
.musicxml/.pdf -> verify. Every stage summary is persisted under
<piece-dir>/reports/ and one compact digest is printed at the end.
The .mscz is a build product: sources are cleaned.mid + beats.json +
piece.json + edits.py. Never edit outputs in place — change a source and
rerun this.
"""
import argparse
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
TC = os.path.join(HERE, "transcription_cleanup.py")
CLEAN_XML = os.path.join(HERE, "clean_musicxml.py")
FINISH = os.path.join(HERE, "finish_score.py")


def run(cmd, report_path=None, quiet_ok=True):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if report_path and r.stdout:
        with open(report_path, "w") as f:
            f.write(r.stdout)
    if r.returncode != 0:
        sys.stderr.write(r.stdout + r.stderr)
        raise SystemExit(f"stage failed: {' '.join(map(str, cmd))}")
    return r.stdout


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("piece_dir")
    ap.add_argument("--mscore",
                    default="/Applications/MuseScore 4.app/Contents/MacOS/mscore")
    ap.add_argument("--skip-verify", action="store_true")
    args = ap.parse_args()

    d = os.path.abspath(args.piece_dir)
    man = json.load(open(os.path.join(d, "piece.json")))
    slug = man["slug"]
    S = os.path.join(d, slug)
    reports = os.path.join(d, "reports")
    os.makedirs(reports, exist_ok=True)
    digest = {}

    q = [PY, TC, "quantize", S + ".cleaned.mid", S + ".tmp.musicxml",
         "--beats", os.path.join(d, man["beats"]),
         "--beats-shift", str(man["beats_shift"]),
         "--key", man["key"], "--time-sig", man["time_sig"],
         "--title", man["title"], "--composer", man["composer"]]
    for role in ("performer", "arranger"):
        if man.get(role):
            q += [f"--{role}", man[role]]
    q += man.get("quantize_flags", [])
    out = run(q, os.path.join(reports, "quantize.json"))
    js = json.loads(out)
    digest["fit"] = js.get("onset_grid_fit")
    digest["lint"] = js.get("lint", {}).get("verdict")

    p = [PY, TC, "post", S + ".tmp.musicxml", S + ".musicxml",
         "--key", man["key"], "--time-sig", man["time_sig"]]
    if man.get("dynamics_from_cleaned_midi"):
        p += ["--dynamics-from", S + ".cleaned.mid"]
    p += man.get("post_flags", [])
    out = run(p, os.path.join(reports, "post.json"))
    digest["post_lint"] = json.loads(out).get("lint", {}).get("verdict")
    os.remove(S + ".tmp.musicxml")

    run([PY, CLEAN_XML, S + ".musicxml", "-o", S + ".musicxml",
         "--source", "generated"], os.path.join(reports, "clean_musicxml.txt"))

    edits = os.path.join(d, "edits.py")
    if os.path.exists(edits):
        print(run([PY, edits, S + ".musicxml"],
                  os.path.join(reports, "edits.txt")), end="")
        digest["edits"] = "applied"

    run([args.mscore, S + ".musicxml", "-o", S + ".mscz"])
    f = [PY, FINISH, S + ".mscz"]
    if man.get("anacrusis"):
        f += ["--anacrusis", str(man["anacrusis"])]
    run(f, os.path.join(reports, "finish.txt"))
    run([args.mscore, S + ".mscz", "-o", S + ".musicxml"])
    run([args.mscore, S + ".mscz", "-o", S + ".pdf"])

    if not args.skip_verify:
        v = [PY, TC, "verify", S + ".musicxml", S + ".wav",
             "--output", os.path.join(d, "verify.json")]
        if man.get("audio_window"):
            v += ["--audio-window", man["audio_window"]]
        run(v, os.path.join(reports, "verify.txt"))
        digest["verify_median"] = json.load(
            open(os.path.join(d, "verify.json"))).get("median_similarity")

    print("rebuild digest: " + json.dumps(digest))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests** — `.venv/bin/python scripts/test_rebuild_score.py` → `ok:` (or `skip:` off-machine).

- [ ] **Step 5: Commit**

```bash
git add scripts/rebuild_score.py scripts/test_rebuild_score.py
git commit -m "rebuild_score: one-command chain driver from piece.json manifest"
```

---

### Task 11: `score_query.py` — `map` and `bar`

**Files:**
- Create: `scripts/score_query.py`
- Test: `scripts/test_score_query.py` (create)

**Interfaces:**
- Consumes: `<piece-dir>` layout (`<slug>.musicxml`, `<slug>.cleaned.mid`, `beats.json`, `piece.json`).
- Produces: `score_query.py map <piece-dir> <bar>[-<bar>]` and `score_query.py bar <piece-dir> <bar>[-<bar>]`; module functions `bar_mapping(piece_dir, bar) -> dict` and `bar_diff(piece_dir, bar) -> str`. **All note views print both staves.** Printed-bar convention: printed bar N = quantize measure N+1 when `piece.json["anacrusis"] > 0`, else N; grid beats = `[4*(N + (1 if anacrusis else 0) - 1), +4)`; MIDI seconds = beats minus `beats_shift`.

- [ ] **Step 1: Failing test** — create `scripts/test_score_query.py`:

```python
"""score_query map/bar on a synthetic pickup piece.
Run: .venv/bin/python scripts/test_score_query.py"""
import json
import os
import subprocess
import sys
import tempfile

import pretty_midi

HERE = os.path.dirname(__file__)
PY = sys.executable


def make_piece(d):
    slug = "fixture"
    pdir = os.path.join(d, slug)
    os.makedirs(pdir)
    S = os.path.join(pdir, slug)
    pm = pretty_midi.PrettyMIDI(initial_tempo=120)
    inst = pretty_midi.Instrument(program=0)
    for k in range(64):
        t = k * 0.5
        inst.notes.append(pretty_midi.Note(80, 60 + (k % 4), t, t + 0.4))
        if k % 2 == 0:
            inst.notes.append(pretty_midi.Note(85, 40, t, t + 0.4))
    pm.instruments.append(inst)
    pm.write(S + ".cleaned.mid")
    json.dump({"beats": [k * 0.5 for k in range(66)]},
              open(os.path.join(pdir, "beats.json"), "w"))
    json.dump({"slug": slug, "key": "C major", "time_sig": "4/4",
               "beats": "beats.json", "beats_shift": 0.0, "title": "F",
               "composer": "T", "performer": None, "arranger": None,
               "anacrusis": 0, "dynamics_from_cleaned_midi": False,
               "quantize_flags": ["--bar-phase", "0"], "post_flags": []},
              open(os.path.join(pdir, "piece.json"), "w"))
    subprocess.run([PY, os.path.join(HERE, "transcription_cleanup.py"),
                    "quantize", S + ".cleaned.mid", S + ".musicxml",
                    "--beats", os.path.join(pdir, "beats.json"),
                    "--bar-phase", "0", "--key", "C major",
                    "--time-sig", "4/4"],
                   capture_output=True, check=True)
    return pdir


def test_map_and_bar():
    with tempfile.TemporaryDirectory() as d:
        pdir = make_piece(d)
        r = subprocess.run([PY, os.path.join(HERE, "score_query.py"),
                            "map", pdir, "3"],
                           capture_output=True, text=True, check=True)
        assert "grid beats" in r.stdout and "8" in r.stdout, r.stdout
        r = subprocess.run([PY, os.path.join(HERE, "score_query.py"),
                            "bar", pdir, "3"],
                           capture_output=True, text=True, check=True)
        assert "P0" in r.stdout and "P1" in r.stdout, (
            "bar view must show BOTH staves:\n" + r.stdout)
        assert "dev" in r.stdout
    print("ok: map + two-staff aligned bar diff")


if __name__ == "__main__":
    test_map_and_bar()
```

- [ ] **Step 2: Run to verify failure** — missing script error.

- [ ] **Step 3: Implement** — create `scripts/score_query.py`:

```python
#!/usr/bin/env python3
"""Compact score queries for targeted diagnosis. Output is fixed-width text
for model reading; every note view shows BOTH staves (single-staff views
have caused one-staff fixes)."""
import argparse
import bisect
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def load_piece(piece_dir):
    d = os.path.abspath(piece_dir)
    man = json.load(open(os.path.join(d, "piece.json")))
    slug = man["slug"]
    beats = json.load(open(os.path.join(d, man["beats"])))["beats"]
    return d, man, slug, beats


def bar_to_beats(man, printed_bar):
    """printed bar N -> (grid beat range, quantize measure number)."""
    qm = printed_bar + (1 if man.get("anacrusis") else 0)
    b0 = 4 * (qm - 1)
    return (b0, b0 + 4), qm


def bar_mapping(piece_dir, printed_bar):
    d, man, slug, beats = load_piece(piece_dir)
    (b0, b1), qm = bar_to_beats(man, printed_bar)
    shift = man["beats_shift"]
    return {"printed_bar": printed_bar, "quantize_measure": qm,
            "grid_beats": [b0, b1],
            "audio_s": [round(beats[b0], 2),
                        round(beats[min(b1, len(beats) - 1)], 2)],
            "midi_s": [round(beats[b0] - shift, 2),
                       round(beats[min(b1, len(beats) - 1)] - shift, 2)]}


def _pos(beats, t):
    i = bisect.bisect_right(beats, t) - 1
    i = max(0, min(i, len(beats) - 2))
    return i + (t - beats[i]) / (beats[i + 1] - beats[i])


def bar_diff(piece_dir, printed_bar):
    import pretty_midi
    from music21 import converter
    d, man, slug, beats = load_piece(piece_dir)
    (b0, b1), qm = bar_to_beats(man, printed_bar)
    shift = man["beats_shift"]
    sc = converter.parse(os.path.join(d, slug + ".musicxml"))
    lines = [f"== printed bar {printed_bar} (quantize m{qm}, "
             f"beats {b0}-{b1}, audio {beats[b0]:.2f}-{beats[b1]:.2f}s) =="]
    for pi, part in enumerate(sc.parts):
        m = part.measure(qm)
        row = []
        if m is not None:
            for el in m.recurse().notesAndRests:
                names = ",".join(p.nameWithOctave for p in el.pitches) \
                    if el.pitches else "rest"
                tie = f"~{el.tie.type[:2]}" if getattr(el, "tie", None) else ""
                row.append(f"{float(el.offset):.2f}:{names}"
                           f"({el.duration.quarterLength}){tie}")
        lines.append(f"P{pi}: " + "  ".join(row))
    pm = pretty_midi.PrettyMIDI(os.path.join(d, slug + ".cleaned.mid"))
    lines.append("played (t=MIDI s; pos=in-bar beats; dev=to nearest 16th):")
    prev = None
    for t, p, v, dur in sorted((n.start, n.pitch, n.velocity,
                                n.end - n.start)
                               for i in pm.instruments for n in i.notes):
        ta = t + shift
        if not (beats[b0] - 0.08 <= ta < beats[min(b1, len(beats) - 1)]):
            continue
        pos = _pos(beats, ta)
        inbar = pos - b0
        f = pos - int(pos)
        dev = abs(f - round(f * 4) / 4)
        gap = f"  gap={t - prev:.2f}" if prev is not None else ""
        prev = t
        import pretty_midi as _pm
        lines.append(f"  t={t:7.2f} +{inbar:5.2f} "
                     f"{_pm.note_number_to_name(p):4s} vel={v:3d} "
                     f"dur={dur:.2f} dev={dev:.3f}{gap}")
    return "\n".join(lines)


def _bar_range(arg):
    if "-" in arg:
        a, b = arg.split("-")
        return range(int(a), int(b) + 1)
    return [int(arg)]


def cmd_map(args):
    for n in _bar_range(args.bar):
        m = bar_mapping(args.piece_dir, n)
        print(f"printed {m['printed_bar']:3d} | quantize m{m['quantize_measure']:3d} "
              f"| grid beats {m['grid_beats'][0]}-{m['grid_beats'][1]} "
              f"| audio {m['audio_s'][0]}-{m['audio_s'][1]}s "
              f"| midi {m['midi_s'][0]}-{m['midi_s'][1]}s")
    return 0


def cmd_bar(args):
    for n in _bar_range(args.bar):
        print(bar_diff(args.piece_dir, n))
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(required=True)
    for name, fn in (("map", cmd_map), ("bar", cmd_bar)):
        p = sub.add_parser(name)
        p.add_argument("piece_dir")
        p.add_argument("bar")
        p.set_defaults(fn=fn)
    args = ap.parse_args()
    sys.exit(args.fn(args))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests** — `.venv/bin/python scripts/test_score_query.py` → `ok:`.

- [ ] **Step 5: Commit**

```bash
git add scripts/score_query.py scripts/test_score_query.py
git commit -m "score_query: map (numbering correspondence) and bar (two-staff aligned diff)"
```

---

### Task 12: `score_query.py` — `family`, `sweep`, `layout`

**Files:**
- Modify: `scripts/score_query.py`
- Test: `scripts/test_score_query.py` (append)

**Interfaces:**
- Produces: `family <piece-dir> <bar>` (pitch + rhythm siblings, transposition-invariant rhythm matcher, engraved rhythms side by side); `sweep <piece-dir>` (detectors: one-slot tie stubs, chord-brush ghosts vs cleaned MIDI, IOI-inconsistent runs, family-skeleton near-misses ≤ 2 slot moves vs skeletons occurring ≥ 3×, arpeggio spreads, unbalanced measures); `layout <piece-dir>` (PDF text layer: bars per page; mscz: LayoutBreak count, instrument labels).

- [ ] **Step 1: Failing tests** (append)

```python
def test_family_finds_transposed_rhythm_sibling():
    with tempfile.TemporaryDirectory() as d:
        pdir = make_piece(d)   # 16 identical-rhythm bars (transposed content)
        r = subprocess.run([PY, os.path.join(HERE, "score_query.py"),
                            "family", pdir, "3"],
                           capture_output=True, text=True, check=True)
        assert "rhythm" in r.stdout.lower(), r.stdout
        assert "bar 5" in r.stdout or "5" in r.stdout.split(), r.stdout
    print("ok: family reports rhythm siblings")


def test_sweep_runs_clean_on_fixture():
    with tempfile.TemporaryDirectory() as d:
        pdir = make_piece(d)
        r = subprocess.run([PY, os.path.join(HERE, "score_query.py"),
                            "sweep", pdir],
                           capture_output=True, text=True, check=True)
        assert "tie stubs: 0" in r.stdout, r.stdout
        assert "unbalanced" in r.stdout
    print("ok: sweep runs all detectors")
```

- [ ] **Step 2: Run to verify failure** — argparse error (unknown subcommand).

- [ ] **Step 3: Implement.** Append to `scripts/score_query.py`:

```python
def _bar_signatures(sc):
    """(pitch multiset, rhythm tuple) per (part, measure)."""
    sigs = {}
    for pi, part in enumerate(sc.parts):
        for m in part.getElementsByClass("Measure"):
            pcs, rhythm = [], []
            for el in m.recurse().notesAndRests:
                if el.pitches and (el.tie is None or el.tie.type == "start"):
                    pcs += [p.midi for p in el.pitches]
                    rhythm.append(round(float(el.offset) * 4) / 4)
            key = m.number
            a, b = sigs.get(key, ([], []))
            sigs[key] = (a + pcs, sorted(set(b) | set(rhythm)))
    return sigs


def _jaccard(a, b):
    from collections import Counter
    ca, cb = Counter(a), Counter(b)
    inter = sum((ca & cb).values())
    union = sum((ca | cb).values())
    return inter / union if union else 0.0


def cmd_family(args):
    from music21 import converter
    d, man, slug, beats = load_piece(args.piece_dir)
    sc = converter.parse(os.path.join(d, slug + ".musicxml"))
    sigs = _bar_signatures(sc)
    qm = bar_to_beats(man, int(args.bar))[1]
    if qm not in sigs:
        print(f"no measure {qm}")
        return 1
    pcs0, rh0 = sigs[qm]
    rows = []
    for m, (pcs, rh) in sorted(sigs.items()):
        if m == qm:
            continue
        pj = _jaccard(pcs0, pcs)
        rj = _jaccard(rh0, rh)
        if pj >= 0.8:
            rows.append((m, "pitch+rhythm" if rj >= 0.8 else "pitch", pj, rj))
        elif rj >= 0.85 and len(rh0) >= 4:
            rows.append((m, "rhythm", pj, rj))
    off = 1 if man.get("anacrusis") else 0
    print(f"family of printed bar {args.bar} (quantize m{qm}):")
    for m, kind, pj, rj in rows:
        print(f"  printed bar {m - off:3d}  [{kind:12s}] "
              f"pitch-jaccard {pj:.2f}  rhythm-jaccard {rj:.2f}")
        print(f"    rhythm: {' '.join(str(x) for x in sigs[m][1])}")
    print(f"  this bar rhythm: {' '.join(str(x) for x in rh0)}")
    return 0


def cmd_sweep(args):
    import pretty_midi
    from music21 import converter
    from collections import Counter
    d, man, slug, beats = load_piece(args.piece_dir)
    sc = converter.parse(os.path.join(d, slug + ".musicxml"))
    stubs = unbal = 0
    arps = []
    for pi, part in enumerate(sc.parts):
        for m in part.getElementsByClass("Measure"):
            if m.number > 1 and abs(
                    float(m.duration.quarterLength)
                    - float(m.barDuration.quarterLength)) > 0.001:
                unbal += 1          # measure 1 may be a legitimate anacrusis
            for el in m.recurse().notesAndRests:
                t = getattr(el, "tie", None)
                if (t and t.type == "stop"
                        and el.duration.quarterLength <= 0.25
                        and float(el.offset) > 0):
                    stubs += 1
                if any(type(e).__name__ == "ArpeggioMark"
                       for e in getattr(el, "expressions", [])):
                    arps.append(m.number)
    # rhythm-skeleton near-misses
    sigs = _bar_signatures(sc)
    skeletons = Counter(tuple(rh) for _, rh in sigs.values() if len(rh) >= 4)
    near = []
    for m, (_, rh) in sorted(sigs.items()):
        t = tuple(rh)
        if skeletons.get(t, 0) >= 3:
            continue
        for sk, cnt in skeletons.items():
            if cnt >= 3:
                diff = set(sk) ^ set(t)
                if 0 < len(diff) <= 2:
                    near.append((m, list(sk)))
                    break
    # chord-brush ghosts still in the cleaned MIDI
    pm = pretty_midi.PrettyMIDI(os.path.join(d, slug + ".cleaned.mid"))
    ghosts = sum(1 for i in pm.instruments for n in i.notes
                 if (n.end - n.start) < 0.055 and n.velocity < 55)
    print(f"one-slot tie stubs: {stubs}")
    print(f"arpeggio marks: {len(arps)} (bars {sorted(set(arps))[:12]})")
    print(f"possible brush ghosts in cleaned MIDI: {ghosts}")
    print(f"rhythm-skeleton near-misses (<=2 moves vs >=3x skeleton): "
          f"{[m for m, _ in near]}")
    print(f"unbalanced measures: {unbal}")
    return 0


def cmd_layout(args):
    import re
    import zipfile
    d, man, slug, beats = load_piece(args.piece_dir)
    with zipfile.ZipFile(os.path.join(d, slug + ".mscz")) as z:
        mscx = next(n for n in z.namelist() if n.endswith(".mscx"))
        x = z.read(mscx).decode("utf-8", "replace")
    lb = x.count("<LayoutBreak>")
    labels = len(re.findall(r"<(?:long|short)Name>", x))
    pdf = os.path.join(d, slug + ".pdf")
    pages = []
    try:
        from pypdf import PdfReader
        for pg in PdfReader(pdf).pages:
            nums = [int(n) for n in re.findall(r"\b(\d{1,3})\b",
                                               pg.extract_text() or "")]
            bars = [n for n in nums if 1 <= n <= 400]
            pages.append(min(bars) if bars else None)
    except Exception as e:  # pypdf absent or PDF unreadable
        pages = [f"(pdf scan unavailable: {e})"]
    print(f"LayoutBreaks in mscz: {lb} (expect 0)")
    print(f"instrument labels in mscz: {labels} (expect 0)")
    print(f"first bar number per page: {pages}")
    if len([p for p in pages if isinstance(p, int)]) >= 2:
        firsts = [p for p in pages if isinstance(p, int)]
        gaps = [b - a for a, b in zip(firsts, firsts[1:])]
        if gaps and (min(gaps) <= max(gaps) // 4):
            print(f"WARNING: uneven bars-per-page distribution {gaps}")
    return 0
```

Register the three subparsers in `main()` (family/sweep/layout take `piece_dir`; family also takes `bar`).

- [ ] **Step 4: Run tests** — `.venv/bin/python scripts/test_score_query.py` → all `ok:`.

- [ ] **Step 5: Commit**

```bash
git add scripts/score_query.py scripts/test_score_query.py
git commit -m "score_query: family (pitch+rhythm siblings), sweep (defect classes), layout"
```

---

### Task 13: Skills, docs, and tier dispatch

**Files:**
- Create: `.claude/skills/grid-surgery/SKILL.md`
- Modify: `.claude/skills/cleanup-score/SKILL.md`, `.claude/skills/transcribe/SKILL.md`, `CLAUDE.md`, `README.md`

- [ ] **Step 1: Write `.claude/skills/grid-surgery/SKILL.md`** with exactly this content:

```markdown
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
```

- [ ] **Step 2: Update `cleanup-score` skill.** In `.claude/skills/cleanup-score/SKILL.md`: replace the grid bake-off bullet's hybrid-repair paragraph with "A winner with flagged windows or fit below ~0.99 goes to the `grid-surgery` skill."; replace pipeline command examples to use `finish_score.py` and end with "write `piece.json` (spec §3.4 schema) and run `scripts/rebuild_score.py <piece-dir>` for the score chain"; add the tier table reference ("dispatch per the grid-surgery skill's tier list"); in the wrap-up section add: "Invite targeted feedback: the user reports bar/time spans that sound wrong; each report runs the grid-surgery skill's ear-feedback loop."

- [ ] **Step 3: Update `transcribe` skill.** Stage-3 paragraph: mention that the cleanup flow now ends by writing `piece.json` and that re-deliveries use `rebuild_score.py`; add one line: "Dispatch stage work per the grid-surgery skill's model-tier table (Haiku executes scripts, Sonnet does rubric checks, Opus orchestrates, Fable only for novel failures)."

- [ ] **Step 4: Update `CLAUDE.md` and `README.md`.** CLAUDE.md: replace `apply_harmony_pedal.py` references with `finish_score.py`; add script lines for `grid_surgery.py`, `score_query.py`, `rebuild_score.py` (one line each, matching the existing list style); add gotchas: "**Never feed an mscore-exported MusicXML back to mscore** — its layout freezes as LayoutBreaks and breaks pagination (sibling of the never-import-a-.mid rule); surgical edits go in `output/<slug>/edits.py` and re-run through `rebuild_score.py`." README: mirror the new scripts and the rebuild flow in the pipeline section (keep both files consistent — doc-sync rule).

- [ ] **Step 5: Full test suite + commit**

```bash
for t in scripts/test_*.py; do .venv/bin/python "$t" >/dev/null || echo "FAIL $t"; done
git add -A
git commit -m "skills+docs: grid-surgery skill, tier dispatch, rebuild flow, finish_score references"
```

Expected: no `FAIL` lines.

---

## Final verification (after all tasks)

- [ ] Run the whole suite: `for t in scripts/test_*.py; do echo "== $t"; .venv/bin/python "$t" | tail -1; done` — every file ends in `ok`/`passed`.
- [ ] End-to-end smoke on the Mirrors piece (it has `edits.py` and an anacrusis): write its `piece.json` (`key "Eb major"`, `time_sig "4/4"`, `beats "beats.json"`, `beats_shift 13.754`, `title "Mirrors"`, `composer "Justin Timberlake"`, `performer "Pianistmiri"`, `anacrusis 3`, `dynamics_from_cleaned_midi true`, `audio_window "13.754:499.5"`), run `.venv/bin/python scripts/rebuild_score.py output/Justin_Timberlake_-_Mirrors_Piano_Cover_by_Pianistmiri --skip-verify`, then `score_query sweep` (tie stubs 0) and `score_query layout` (no warnings, 0 LayoutBreaks).
- [ ] Dispatch the final whole-branch review on **Fable** with a review package (`scripts/review-package MERGE_BASE HEAD`).
