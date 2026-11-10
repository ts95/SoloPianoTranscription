# Audit Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the defects found in the 2026-11-10 project audit: a script that cannot run, an audio normalizer that silently compresses, a tempo/meter normalizer that corrupts scores, a `verify` that assumes constant tempo, a wrong bass-note rule in pedaling, and docs that contradict what DuET actually does.

**Architecture:** Seven tasks in two concurrent waves (see **Execution Waves**). Tasks 1–6 each fix one script with one plain-script test file; Task 7 rewrites every doc/skill line the earlier tasks made false. No new modules beyond test files; one script is renamed.

**Tech Stack:** Python 3.11 (`.venv/bin/python`), `pretty_midi`, `mido`, `numpy`, `music21` (all already installed), bash + `/opt/homebrew/bin/ffmpeg`, MuseScore 4 via `scripts/mscore.sh`.

**Spec:** None. The audit lives in the conversation that produced this plan; every decision it led to is written into the tasks below. The four product decisions the owner made are:

1. DuET's dynamics **stay** in the score; docs must stop claiming DuET writes none.
2. The `--meter` trimming feature is **removed**; only tempo normalization remains.
3. Harmony pedaling **stays** (replacing DuET's own pedal); only the bass-note bug is fixed.
4. `split_hands_midi.py` is **rebuilt** on DuET's `score.npz` staff assignment.

## Global Constraints

- Run Python only as `.venv/bin/python`. Never `python3`, never `pip install` anything. (`scripts/prepare_audio.sh` itself keeps using bare `python3` for its JSON one-liner, as today.)
- Never prefix a command with `cd`. All paths are relative to the repo root, which is already the working directory.
- Tests are plain scripts in `scripts/`, run as `.venv/bin/python scripts/test_<name>.py` (or `bash scripts/test_<name>.sh`). Each test function ends by printing `ok: <description>`; the `if __name__ == "__main__":` block calls every test function in file order. No pytest, no fixtures on disk — build every fixture inside the test.
- Do not read, write or delete anything under `output/` except where a step gives the exact command.
- Do not edit `.claude/settings.json` or `.claude/settings.local.json`.
- Do not change any behaviour, name, or wording this plan does not name. No refactors, no extra tests, no extra docs.
- One commit per task, with exactly the message the task gives, ending with the trailer line `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`. **Only the orchestrator runs git** (see Execution Waves); a subagent never runs any `git` command and skips its task's "Commit" step.
- If a step's "Expected" output does not appear, stop and report the actual output. Do not improvise a different fix.
- Docs are edited only in Task 7. Between Task 2 and Task 7 the docs will name a script that no longer exists; that is expected.

## Review Focus

1. **Silent audio file** into `prepare_audio.sh` → must exit non-zero with `prepare_audio: input is silent`, not hand ffmpeg `volume=infdB`. (Test in Task 1.)
2. **`normalize_tempo.py` run on a MuseScore-regenerated `.musicxml`** (no compact `<metronome>` tag) → must exit 1 and write nothing, not report success. (Test in Task 2.)
3. **MuseScore exits 134 after writing its output** (known shutdown crash) → `verify` must accept the render; an exit 0 with no file must be rejected. (Test in Task 3.)
4. **`score.npz` from a different MIDI** than the one passed to `split_hands_midi.py` → must refuse with a clear message, not mis-assign hands. (Test in Task 6.)
5. **Bass chord event with no pitches** in pedal analysis → must yield `None`, not crash on `min([])`. (Test in Task 5.)

## Execution Waves

The orchestrator dispatches subagents with the Agent tool (`subagent_type: "general-purpose"`, `model: "sonnet"`), all lanes of a wave **in one message** so they run concurrently. Lanes within a wave touch disjoint files, so they share the one working tree — do **not** use worktree isolation (a worktree has no `.venv/` or `output/`, and every test needs them).

Each subagent prompt is exactly: the full text of **Global Constraints**, the full text of its lane's task(s) (for Wave 2: the Task 7 preamble with S1 and S2, plus the listed steps), and the sentence "Do the steps in order. Do not run any git command; skip the Commit step. Touch only the files your task lists. Report each verification command's actual output."

| Wave | Lane | Work | Files it owns |
|------|------|------|---------------|
| 1 | A | Task 1 | `scripts/prepare_audio.sh`, `scripts/test_prepare_audio.sh` |
| 1 | B | Task 2 | `scripts/normalize_meter_tempo.py` → `scripts/normalize_tempo.py`, `scripts/test_normalize_tempo.py` |
| 1 | C | Task 3, then Task 4 (same agent, sequential — both edit the same two files) | `scripts/transcription_cleanup.py`, `scripts/test_transcription_cleanup.py` |
| 1 | D | Task 5 | `scripts/analyze_pedaling.py`, `scripts/apply_harmony_pedal.py`, `scripts/test_analyze_pedaling.py` |
| 1 | E | Task 6 | `scripts/split_hands_midi.py`, `scripts/test_split_hands_midi.py` |
| 2 | F | Task 7 step 1 | `CLAUDE.md` |
| 2 | G | Task 7 steps 2–3 | `README.md`, `docs/WHY_MIDI_TO_SCORE_IS_HARD.md` |
| 2 | H | Task 7 steps 4–9 | `scripts/simplify_score.py`, the five `.claude/skills/*/SKILL.md` |

Lane E imports `all_notes` from `transcription_cleanup.py` while lane C edits that file; lane C never changes `all_notes`, and a half-saved file can only cause a transient import error — if lane E's test fails with a `SyntaxError` or `ImportError` in `transcription_cleanup`, it re-runs the test once after 30 seconds before reporting.

**After Wave 1** (all five lanes reported success), the orchestrator:

1. Runs every Wave-1 test once more itself: `bash scripts/test_prepare_audio.sh && for t in normalize_tempo transcription_cleanup analyze_pedaling split_hands_midi; do .venv/bin/python scripts/test_$t.py || break; done` → 14 lines starting `ok:`.
2. Commits in task order, using each task's Commit step verbatim, with two differences forced by the shared file in lane C and the rename in lane B:
   - Task 2: `git add -A scripts/normalize_meter_tempo.py scripts/normalize_tempo.py scripts/test_normalize_tempo.py`
   - Tasks 3 and 4 become **one** commit: `git add scripts/transcription_cleanup.py scripts/test_transcription_cleanup.py` with message `verify: real bar times via rendered MIDI + scripts/mscore.sh; clean: music-prior uses --key; drop dead analysis code`
3. If any lane failed, commits the lanes that passed, stops, and reports the failing lane's output. Wave 2 does not start.

**After Wave 2**, the orchestrator runs Task 7 step 10 itself, then Task 7 step 11 (the commit).

---

### Task 1: `prepare_audio.sh` applies one static gain

**Files:**
- Modify: `scripts/prepare_audio.sh` (whole file)
- Create: `scripts/test_prepare_audio.sh`

**Interfaces:**
- Produces: `scripts/prepare_audio.sh <in> <out.wav>` — unchanged CLI. Output is 44.1 kHz; gain is `min(-16 - input_i, -1.5 - input_tp)` dB.

- [ ] **Step 1: Write the failing test** — create `scripts/test_prepare_audio.sh` with exactly:

```bash
#!/bin/bash
# Regression test: prepare_audio.sh must apply ONE static gain (no compression).
# Run: bash scripts/test_prepare_audio.sh
set -euo pipefail
FFMPEG=/opt/homebrew/bin/ffmpeg
FFPROBE=/opt/homebrew/bin/ffprobe
T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT

# crest factor (max_volume - mean_volume, dB) of a file
crest() {
  "$FFMPEG" -hide_banner -nostats -i "$1" -af volumedetect -f null - 2>&1 |
    awk '/mean_volume/{m=$5}/max_volume/{x=$5}END{printf "%.1f %.1f\n", x-m, x}'
}

# Peaky signal: quiet tone with 5 ms near-full-scale bursts (crest ~30 dB).
"$FFMPEG" -y -hide_banner -loglevel error -f lavfi \
  -i "aevalsrc='sin(2*PI*440*t)*if(lt(mod(t,3),0.005),0.9,0.02)':d=30:s=48000" "$T/in.wav"
scripts/prepare_audio.sh "$T/in.wav" "$T/out.wav" >/dev/null 2>&1

read -r CIN _ < <(crest "$T/in.wav")
read -r COUT MAXOUT < <(crest "$T/out.wav")
python3 -c "import sys; d=abs($COUT-$CIN); sys.exit(0 if d < 1.0 else 'FAIL: crest changed by %.1f dB (compression)' % d)"
python3 -c "import sys; sys.exit(0 if $MAXOUT <= -1.0 else 'FAIL: peak $MAXOUT dB above -1.0')"
echo "ok: static gain preserves crest factor and keeps peak <= -1.0 dB"

RATE=$("$FFPROBE" -v error -show_entries stream=sample_rate -of csv=p=0 "$T/out.wav")
[ "$RATE" = "44100" ] || { echo "FAIL: sample rate $RATE"; exit 1; }
echo "ok: output is 44.1 kHz"

"$FFMPEG" -y -hide_banner -loglevel error -f lavfi -i "anullsrc=r=48000:cl=mono" -t 2 "$T/silent.wav"
if scripts/prepare_audio.sh "$T/silent.wav" "$T/silent.out.wav" >"$T/log" 2>&1; then
  echo "FAIL: silent input accepted"; exit 1
fi
grep -q "prepare_audio: input is silent" "$T/log" || { echo "FAIL: no silent-input message"; cat "$T/log"; exit 1; }
echo "ok: silent input is rejected"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `bash scripts/test_prepare_audio.sh`
Expected: exits non-zero printing `FAIL: crest changed by 15.8 dB (compression)` (the number may differ by a few tenths).

- [ ] **Step 3: Replace `scripts/prepare_audio.sh`** with exactly:

```bash
#!/bin/bash
# Prepare audio for Transkun: ONE static gain per file (never a compressor —
# compression would skew the velocities Transkun emits), resampled to the
# 44.1 kHz the model expects.
#
# The gain moves the file toward -16 LUFS integrated, capped so the true peak
# stays <= -1.5 dBTP. A peaky recording therefore ends up quieter than -16 LUFS
# rather than being limited. (ffmpeg's two-pass loudnorm is NOT used for the
# gain: with linear=true it silently falls back to dynamic mode whenever the
# peak or loudness range exceeds its targets.)
#
# Usage: prepare_audio.sh <input-audio> <output.wav>
set -euo pipefail

FFMPEG=/opt/homebrew/bin/ffmpeg
IN="$1"
OUT="$2"
TARGET_I=-16
TARGET_TP=-1.5

STATS=$("$FFMPEG" -hide_banner -nostats -i "$IN" \
  -af "loudnorm=I=$TARGET_I:TP=$TARGET_TP:LRA=11:print_format=json" -f null - 2>&1 | sed -n '/^{/,/^}/p')

GAIN=$(printf '%s' "$STATS" | python3 -c "
import json, math, sys
d = json.load(sys.stdin)
g = min($TARGET_I - float(d['input_i']), $TARGET_TP - float(d['input_tp']))
if not math.isfinite(g):
    sys.exit('prepare_audio: input is silent')
print(round(g, 2))")

"$FFMPEG" -y -hide_banner -nostats -i "$IN" -af "volume=${GAIN}dB" -ar 44100 "$OUT"

echo "wrote $OUT (44.1 kHz, static gain ${GAIN} dB)"
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `bash scripts/test_prepare_audio.sh`
Expected: three lines, each starting `ok:`, exit 0.

- [ ] **Step 5: Commit**

```bash
git add scripts/prepare_audio.sh scripts/test_prepare_audio.sh
git commit -m "prepare_audio: one static gain instead of loudnorm (which silently went dynamic)"
```

---

### Task 2: `normalize_meter_tempo.py` → tempo-only `normalize_tempo.py`

**Files:**
- Rename: `scripts/normalize_meter_tempo.py` → `scripts/normalize_tempo.py` (plain `mv`; the orchestrator stages the rename), then rewrite its whole content
- Create: `scripts/test_normalize_tempo.py`

**Interfaces:**
- Produces: `normalize_tempo(xml: str, bpm: int) -> tuple[str, dict]` in `scripts/normalize_tempo.py`. Raises `ValueError` when `xml` contains no `<metronome>…</metronome>`.
- Produces: CLI `scripts/normalize_tempo.py <in.musicxml> <out.musicxml> --tempo <bpm>` (`--tempo` required, float, rounded to int). Exit 0 and a JSON report on stdout on success; on `ValueError`, prints the message to stderr, writes no output file, exits 1.

- [ ] **Step 1: Rename the file**

Run: `mv scripts/normalize_meter_tempo.py scripts/normalize_tempo.py`

- [ ] **Step 2: Write the failing test** — create `scripts/test_normalize_tempo.py` with exactly:

```python
"""Regression test: normalize_tempo forces ONE constant tempo on a raw DuET score.

Run: .venv/bin/python scripts/test_normalize_tempo.py
"""
import os
import subprocess
import sys
import tempfile

from normalize_tempo import normalize_tempo

MARK = ('<direction placement="above"><direction-type><metronome><beat-unit>quarter</beat-unit>'
        '<per-minute>{0}</per-minute></metronome></direction-type><staff>1</staff>'
        '<sound tempo="{0}"/></direction>')
DYN = ('<direction placement="below"><direction-type><dynamics><mp/></dynamics></direction-type>'
       '<staff>1</staff></direction>')
HIDDEN = '<direction><direction-type><words/></direction-type><staff>1</staff><sound tempo="150"/></direction>'
RIT = ('<direction placement="above"><direction-type><words font-style="italic">rit.</words>'
       '</direction-type><staff>1</staff></direction>')

RAW = ('<measure number="1">' + MARK.format(141) + DYN + '</measure>'
       '<measure number="2">' + HIDDEN + RIT + '</measure>'
       '<measure number="3">' + MARK.format(153) + '</measure>')
WANT = ('<measure number="1">' + MARK.format(93) + DYN + '</measure>'
        '<measure number="2">' + RIT + '</measure>'
        '<measure number="3"></measure>')


def test_one_constant_tempo():
    out, report = normalize_tempo(RAW, 93)
    assert out == WANT, out
    assert report == {"bpm": 93, "metronome_marks_removed": 1,
                      "sound_tempos_removed": 2, "empty_directions_removed": 2}, report
    print("ok: one metronome mark, one sound tempo, hidden tempo changes gone, rit./dynamics kept")


def test_no_metronome_is_an_error():
    try:
        normalize_tempo('<measure number="1"><metronome parentheses="no"></metronome></measure>', 93)
    except ValueError as e:
        assert "raw DuET" in str(e), e
    else:
        raise AssertionError("expected ValueError")
    print("ok: a score without a compact <metronome> raises instead of silently succeeding")


def test_cli_exit_codes():
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "normalize_tempo.py")
    with tempfile.TemporaryDirectory() as td:
        good, bad, out = (os.path.join(td, n) for n in ("good.xml", "bad.xml", "out.xml"))
        with open(good, "w") as f:
            f.write(RAW)
        with open(bad, "w") as f:
            f.write('<measure number="1"></measure>')
        r = subprocess.run([sys.executable, script, good, out, "--tempo", "92.6"], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        with open(out) as f:
            assert f.read() == WANT
        os.remove(out)
        r = subprocess.run([sys.executable, script, bad, out, "--tempo", "93"], capture_output=True, text=True)
        assert r.returncode == 1 and not os.path.exists(out), (r.returncode, r.stderr)
    print("ok: CLI rounds --tempo, exits 1 and writes nothing when no metronome is found")


if __name__ == "__main__":
    test_one_constant_tempo()
    test_no_metronome_is_an_error()
    test_cli_exit_codes()
```

- [ ] **Step 3: Run it to verify it fails**

Run: `.venv/bin/python scripts/test_normalize_tempo.py`
Expected: `ImportError: cannot import name 'normalize_tempo'`.

- [ ] **Step 4: Rewrite `scripts/normalize_tempo.py`** — replace the whole file with exactly:

```python
#!/usr/bin/env python3
"""Force ONE constant tempo on a raw DuET score.

DuET infers a tempo per section: visible metronome marks plus hidden
<sound tempo> playback changes. When the true tempo is known (web ground
truth), this rewrites the score to a single quarter-note tempo.

Run it on the RAW DuET score.musicxml, right after DuET and before MuseScore
regenerates the file: it is a targeted text edit (NOT a music21 round-trip)
that matches DuET's compact tags, and it exits 1 if it finds no metronome mark.

There is deliberately no meter override. Re-barring is not a text edit; a
wrong meter is flagged in CLEANUP_NOTES.md and fixed by hand in MuseScore.

Usage:
  normalize_tempo.py <in.musicxml> <out.musicxml> --tempo 93

What changes:
  - the first <metronome> becomes quarter = N; every other <metronome> is removed
  - the first <sound tempo> becomes N; every other <sound tempo> is removed
  - directions left empty by those removals are removed
  - text directions (rit., a tempo) and everything else are untouched
"""
import argparse
import json
import re
import sys

METRONOME = re.compile(r'<metronome>.*?</metronome>', flags=re.S)
SOUND_TEMPO = re.compile(r'<sound tempo="[^"]*"/>')
EMPTY_DIRECTION = re.compile(
    r'<direction[^>]*><direction-type>(?:<words/>)?</direction-type><staff>\d+</staff></direction>')


def _keep_first(pattern, xml, first):
    """Replace the first match of `pattern` with `first`, delete the rest.
    Returns (new_xml, number_deleted)."""
    matches = list(pattern.finditer(xml))
    for m in reversed(matches[1:]):
        xml = xml[:m.start()] + xml[m.end():]
    m = matches[0]
    return xml[:m.start()] + first + xml[m.end():], len(matches) - 1


def normalize_tempo(xml, bpm):
    if not METRONOME.search(xml):
        raise ValueError("no <metronome> found — run this on the raw DuET score.musicxml, "
                         "before MuseScore regenerates it")
    xml, marks_removed = _keep_first(
        METRONOME, xml,
        f'<metronome><beat-unit>quarter</beat-unit><per-minute>{bpm}</per-minute></metronome>')
    sounds_removed = 0
    if SOUND_TEMPO.search(xml):
        xml, sounds_removed = _keep_first(SOUND_TEMPO, xml, f'<sound tempo="{bpm}"/>')
    xml, empties_removed = EMPTY_DIRECTION.subn('', xml)
    return xml, {"bpm": bpm, "metronome_marks_removed": marks_removed,
                 "sound_tempos_removed": sounds_removed,
                 "empty_directions_removed": empties_removed}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('input')
    ap.add_argument('output')
    ap.add_argument('--tempo', type=float, required=True,
                    help='constant quarter-note BPM for the whole piece')
    args = ap.parse_args()

    with open(args.input, encoding='utf-8') as f:
        xml = f.read()
    try:
        xml, report = normalize_tempo(xml, int(round(args.tempo)))
    except ValueError as e:
        print(f"normalize_tempo: {e}", file=sys.stderr)
        return 1
    with open(args.output, 'w', encoding='utf-8') as f:
        f.write(xml)
    print(json.dumps({"input": args.input, "output": args.output, **report}, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `.venv/bin/python scripts/test_normalize_tempo.py`
Expected: three lines starting `ok:`, exit 0.

- [ ] **Step 6: Commit**

```bash
git add -A scripts/normalize_meter_tempo.py scripts/normalize_tempo.py scripts/test_normalize_tempo.py
git commit -m "normalize_tempo: tempo-only, really constant (sound tempos too); drop the meter trimmer"
```

---

### Task 3: `verify` uses real bar times and the MuseScore wrapper

**Files:**
- Modify: `scripts/transcription_cleanup.py` — imports (lines 18–24), `cmd_verify` (lines 366–493), the `verify` argparse block (lines 592–599)
- Create: `scripts/test_transcription_cleanup.py`

**Interfaces:**
- Produces: `bar_times_from_midi(path: str) -> list[float]` — bar start times in seconds plus the end time as the last element (length = bars + 1).
- Produces: `render_ok(mscore: str, score: str, target: str) -> bool` — runs `mscore score -o target`; `True` iff `target` exists and is non-empty afterwards, whatever the exit code.
- Task 4 appends tests to the test file created here.

- [ ] **Step 1: Write the failing tests** — create `scripts/test_transcription_cleanup.py` with exactly:

```python
"""Regression tests for transcription_cleanup helpers.

Run: .venv/bin/python scripts/test_transcription_cleanup.py
"""
import os
import stat
import tempfile

import mido

from transcription_cleanup import bar_times_from_midi, render_ok


def test_bar_times_follow_tempo_and_meter_changes():
    # 2 bars of 4/4 at 120 BPM (2 s each), then 2 bars of 3/4 at 60 BPM (3 s each)
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "t.mid")
        m = mido.MidiFile(ticks_per_beat=480)
        t = mido.MidiTrack()
        m.tracks.append(t)
        t.append(mido.MetaMessage("set_tempo", tempo=500000, time=0))
        t.append(mido.MetaMessage("time_signature", numerator=4, denominator=4, time=0))
        t.append(mido.Message("note_on", note=60, velocity=80, time=0))
        t.append(mido.MetaMessage("set_tempo", tempo=1000000, time=3840))
        t.append(mido.MetaMessage("time_signature", numerator=3, denominator=4, time=0))
        t.append(mido.Message("note_off", note=60, velocity=0, time=2880))
        m.save(path)
        times = [round(x, 6) for x in bar_times_from_midi(path)]
    assert times == [0.0, 2.0, 4.0, 7.0, 10.0], times
    print("ok: bar times follow tempo and time-signature changes")


def _fake_mscore(td, name, body):
    path = os.path.join(td, name)
    with open(path, "w") as f:
        f.write("#!/bin/sh\n" + body + "\n")
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)
    return path


def test_render_judged_by_output_file_not_exit_code():
    with tempfile.TemporaryDirectory() as td:
        crashy = _fake_mscore(td, "crashy.sh", 'printf x > "$3"\nexit 134')
        silent = _fake_mscore(td, "silent.sh", "exit 0")
        assert render_ok(crashy, "score.musicxml", os.path.join(td, "a.mid")) is True
        assert render_ok(silent, "score.musicxml", os.path.join(td, "b.mid")) is False
    print("ok: a render counts when the file was written (exit 134 tolerated), not when exit is 0 with no file")


if __name__ == "__main__":
    test_bar_times_follow_tempo_and_meter_changes()
    test_render_judged_by_output_file_not_exit_code()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/python scripts/test_transcription_cleanup.py`
Expected: `ImportError: cannot import name 'bar_times_from_midi'`.

- [ ] **Step 3: Add the imports and the two helpers.** In `scripts/transcription_cleanup.py`:

Replace the import block

```python
import argparse
import json
import statistics
import sys
```

with

```python
import argparse
import json
import os
import statistics
import subprocess
import sys
import warnings
```

Insert these two functions immediately above `def cmd_verify(args):`:

```python
def bar_times_from_midi(path):
    """Bar start times (s) of a MIDI file, plus its end time as the last element.
    Honors every tempo and time-signature change."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # mscore puts tempo events on track 1
        pm = pretty_midi.PrettyMIDI(path)
    end = float(pm.get_end_time())
    return [float(d) for d in pm.get_downbeats() if d < end - 1e-6] + [end]


def render_ok(mscore, score, target):
    """Run `mscore score -o target`; True iff target exists and is non-empty.
    The exit code is ignored: mscore can exit 134 on shutdown after a good write."""
    subprocess.run([mscore, score, "-o", target], capture_output=True)
    return os.path.exists(target) and os.path.getsize(target) > 0
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python scripts/test_transcription_cleanup.py`
Expected: two lines starting `ok:`.

- [ ] **Step 5: Rewire `cmd_verify`.** Make exactly these six edits inside `cmd_verify`:

(a) Delete these three lines at the top of the function (now module-level imports):

```python
    import subprocess
    import tempfile
    import warnings
```

and put back only `import tempfile` in their place (one line, same indentation).

(b) Delete these four lines:

```python
    mm = score.recurse().getElementsByClass("MetronomeMark").first()
    bpm = float(mm.number) if mm is not None else 120.0
    ts = score.recurse().getElementsByClass("TimeSignature").first()
    bar_ql = float(ts.barDuration.quarterLength) if ts is not None else 4.0
```

(c) Replace

```python
        render_wav = f"{td}/render.mp3"
        res = subprocess.run([args.mscore, args.score, "-o", render_wav],
                             capture_output=True)
        if res.returncode != 0 or not __import__("os").path.getsize(render_wav):
            print(json.dumps({"error": f"mscore render failed ({res.returncode})"}))
            return 1
```

with

```python
        render_wav = f"{td}/render.mp3"
        render_mid = f"{td}/render.mid"
        for target in (render_wav, render_mid):
            if not render_ok(args.mscore, args.score, target):
                print(json.dumps({"error": f"mscore render failed: {os.path.basename(target)}"}))
                return 1
        times = bar_times_from_midi(render_mid)
```

(d) Replace

```python
    fps = SR / HOP
    bar_seconds_render = bar_ql * 60.0 / bpm
    bars = []
    for k in range(n_bars):
        f0 = int(k * bar_seconds_render * fps)
        f1 = max(f0 + 1, int((k + 1) * bar_seconds_render * fps))
```

with

```python
    fps = SR / HOP
    n_bars = min(n_bars, len(times) - 1)
    bars = []
    for k in range(n_bars):
        f0 = int(times[k] * fps)
        f1 = max(f0 + 1, int(times[k + 1] * fps))
```

(e) In the `report = {` dict replace the line `"render_bpm": bpm,` with `"render_seconds": round(times[-1], 1),`.

(f) In `main()`, replace

```python
    v.add_argument("score", help="the .cleaned.musicxml (must carry a metronome mark)")
```

with

```python
    v.add_argument("score", help="the score .musicxml")
```

and replace

```python
    v.add_argument("--mscore", default="/Applications/MuseScore 4.app/Contents/MacOS/mscore")
```

with

```python
    v.add_argument("--mscore", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "mscore.sh"),
                   help="MuseScore CLI (default: scripts/mscore.sh, which honours $MSCORE)")
```

- [ ] **Step 6: Confirm nothing stale remains**

Run: `grep -n "bar_seconds_render\|render_bpm\|bar_ql\|__import__" scripts/transcription_cleanup.py`
Expected: no output.

- [ ] **Step 7: Integration check on an existing piece** (reads from `output/`, writes only to a temp file)

Run:
```bash
.venv/bin/python scripts/transcription_cleanup.py verify output/1x1_-_Bring_me_the_horizon_ft._Nova_Twins_FULL_VERSION_ROLEE_Piano_Cover/1x1_-_Bring_me_the_horizon_ft._Nova_Twins_FULL_VERSION_ROLEE_Piano_Cover.musicxml output/1x1_-_Bring_me_the_horizon_ft._Nova_Twins_FULL_VERSION_ROLEE_Piano_Cover/1x1_-_Bring_me_the_horizon_ft._Nova_Twins_FULL_VERSION_ROLEE_Piano_Cover.mp3 --output "$(mktemp -d)/verify.json"
```
Expected (takes ~1–2 min): exit 0; printed JSON contains `"bars_compared"` with a value between 130 and 138, and a `"render_seconds"` key. If that directory does not exist, skip this step and say so in the task report.

- [ ] **Step 8: Re-run the unit tests, then commit**

Run: `.venv/bin/python scripts/test_transcription_cleanup.py` → two `ok:` lines.

```bash
git add scripts/transcription_cleanup.py scripts/test_transcription_cleanup.py
git commit -m "verify: map bars via the rendered MIDI's real bar times; use scripts/mscore.sh"
```

---

### Task 4: `clean` honours `--key`; delete dead analysis code

**Files:**
- Modify: `scripts/transcription_cleanup.py`
- Modify: `scripts/test_transcription_cleanup.py` (append)

**Interfaces:**
- Consumes: the test file from Task 3.
- Produces: `scale_for_clean(notes, key_arg) -> set[int]` — scale pitch classes used by the artifact music-prior. `key_arg` is the `--key` string (e.g. `"D Major"`, `"C# minor"`, `"Eb Major"`) or `None`.

- [ ] **Step 1: Write the failing test.** In `scripts/test_transcription_cleanup.py`:

Change the import line to
```python
from transcription_cleanup import bar_times_from_midi, render_ok, scale_for_clean
```

Add this function above the `if __name__` block:

```python
def test_clean_uses_the_given_key():
    assert scale_for_clean([], "D Major") == {2, 4, 6, 7, 9, 11, 1}
    assert scale_for_clean([], "C# minor") == {1, 3, 4, 6, 8, 9, 11}
    assert scale_for_clean([], "Eb Major") == {3, 5, 7, 8, 10, 0, 2}
    print("ok: the artifact music-prior uses --key when given")
```

and add `test_clean_uses_the_given_key()` as the last line of the `if __name__` block.

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/python scripts/test_transcription_cleanup.py`
Expected: `ImportError: cannot import name 'scale_for_clean'`.

- [ ] **Step 3: Implement.** In `scripts/transcription_cleanup.py`, insert directly below the `key_estimate` function:

```python
def scale_for_clean(notes, key_arg):
    """Scale pitch classes for the artifact music-prior: the ground-truth
    --key when given, else the top statistical estimate."""
    if key_arg:
        n = pretty_midi.key_name_to_key_number(key_arg)
        base = MAJOR_SCALE_PCS if n < 12 else MINOR_SCALE_PCS
        return {(n % 12 + pc) % 12 for pc in base}
    return key_scale_pcs(key_estimate(notes)[0]["key"])
```

In `cmd_clean`, replace

```python
    scale = key_scale_pcs(key_estimate(notes)[0]["key"])
```

with

```python
    scale = scale_for_clean(notes, args.key)
```

- [ ] **Step 4: Delete the dead code.** In `scripts/transcription_cleanup.py` delete, in full:

- the function `hand_split`
- the constant `DYNAMIC_LEVELS`
- the functions `velocity_profile`, `dynamic_level`, `find_hairpins`
- in `cmd_analyze`'s `report` dict: the line `"hand_split": hand_split(notes),` and the whole `"dynamics_preview": { … },` entry (7 lines, from `"dynamics_preview": {` through its closing `},`)

- [ ] **Step 5: Verify**

Run: `.venv/bin/python scripts/test_transcription_cleanup.py`
Expected: three lines starting `ok:`.

Run: `grep -n "hand_split\|DYNAMIC_LEVELS\|velocity_profile\|dynamic_level\|find_hairpins\|dynamics_preview" scripts/transcription_cleanup.py`
Expected: no output.

Run: `.venv/bin/python scripts/transcription_cleanup.py analyze output/1x1_-_Bring_me_the_horizon_ft._Nova_Twins_FULL_VERSION_ROLEE_Piano_Cover/1x1_-_Bring_me_the_horizon_ft._Nova_Twins_FULL_VERSION_ROLEE_Piano_Cover.mid | tail -3`
Expected: exit 0, valid JSON tail ending in `}` (skip if the directory does not exist, and say so).

- [ ] **Step 6: Commit**

```bash
git add scripts/transcription_cleanup.py scripts/test_transcription_cleanup.py
git commit -m "clean: music-prior uses --key when given; drop dead hand_split/dynamics-preview code"
```

---

### Task 5: Pedal analysis reads the lowest note; no shared temp dirs

**Files:**
- Modify: `scripts/analyze_pedaling.py:107`
- Modify: `scripts/apply_harmony_pedal.py` (`main`)
- Create: `scripts/test_analyze_pedaling.py`

**Interfaces:**
- Consumes: `analyze_measure(mdata) -> dict` (existing), `add_pedals(mscz_path, get_pedals_fn, staff_id='2', extract_dir=None, post_process=None)` (existing, in `musescore_pedal_lib.py` — do not modify that file).

- [ ] **Step 1: Write the failing test** — create `scripts/test_analyze_pedaling.py` with exactly:

```python
"""Regression test: the bass harmony is the pitch class of the LOWEST NOTE.

Run: .venv/bin/python scripts/test_analyze_pedaling.py
"""
from analyze_pedaling import analyze_measure


def measure(bass_events):
    return {"number": 1, "time_sig": "4/4", "ticks": 1920,
            "staves": {"2": {"voices": {"1": bass_events}}}}


def chord(tick, pitches):
    return {"type": "Chord", "tick": tick, "dur": 960,
            "pitches": sorted(pitches), "pcs": sorted({p % 12 for p in pitches})}


def test_same_bass_note_is_not_a_harmony_change():
    # G2+C3 then G2+B2: the bass is G both times (C is merely the smallest pc number)
    r = analyze_measure(measure([chord(0, [43, 48]), chord(960, [43, 47])]))
    assert (r["bass_start_pc"], r["bass_mid_pc"]) == (7, 7), r
    assert r["recommendation"] == "single", r
    print("ok: bass pc is taken from the lowest note, not the smallest pc number")


def test_real_bass_change_still_splits():
    r = analyze_measure(measure([chord(0, [36, 43]), chord(960, [41, 48])]))  # C2 -> F2
    assert (r["bass_start_pc"], r["bass_mid_pc"]) == (0, 5), r
    assert r["recommendation"] == "split", r
    print("ok: a real bass change at the half-bar still splits")


def test_chord_without_pitches_does_not_crash():
    r = analyze_measure(measure([chord(0, []), chord(960, [])]))
    assert (r["bass_start_pc"], r["bass_mid_pc"]) == (None, None), r
    assert r["recommendation"] == "single", r
    print("ok: a bass chord with no pitches yields None, not a crash")


if __name__ == "__main__":
    test_same_bass_note_is_not_a_harmony_change()
    test_real_bass_change_still_splits()
    test_chord_without_pitches_does_not_crash()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/python scripts/test_analyze_pedaling.py`
Expected: `AssertionError` in `test_same_bass_note_is_not_a_harmony_change` (start pc is 0, recommendation `split`).

- [ ] **Step 3: Fix the bass rule.** In `scripts/analyze_pedaling.py`, replace

```python
            lowest_pc = min(ev['pcs']) if ev['pcs'] else None
```

with

```python
            lowest_pc = min(ev['pitches']) % 12 if ev['pitches'] else None
```

Then, in the sustained-bass loop of the same function, replace

```python
            if ev['dur'] >= 960 and min(ev['pitches']) < 48:
```

with

```python
            if ev['pitches'] and ev['dur'] >= 960 and min(ev['pitches']) < 48:
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python scripts/test_analyze_pedaling.py`
Expected: three lines starting `ok:`.

- [ ] **Step 5: Use private temp dirs in `scripts/apply_harmony_pedal.py`.** Replace

```python
    mscx = extract_mscz(args.mscz, os.path.join(tempfile.gettempdir(), "harmony_pedal_analyze"))
    measures = extract_measure_data(mscx, staff_ids=("1", "2"))
    results = [analyze_measure(m) for m in measures]
```

with

```python
    td = tempfile.TemporaryDirectory()  # private: concurrent runs must not share an extract dir
    mscx = extract_mscz(args.mscz, os.path.join(td.name, "analyze"))
    measures = extract_measure_data(mscx, staff_ids=("1", "2"))
    results = [analyze_measure(m) for m in measures]
```

and replace

```python
    add_pedals(args.mscz, cfg, staff_id=args.staff)
```

with

```python
    add_pedals(args.mscz, cfg, staff_id=args.staff, extract_dir=os.path.join(td.name, "write"))
    td.cleanup()
```

- [ ] **Step 6: Integration check on a COPY of an existing score**

Run:
```bash
T=$(mktemp -d) && cp output/1x1_-_Bring_me_the_horizon_ft._Nova_Twins_FULL_VERSION_ROLEE_Piano_Cover/1x1_-_Bring_me_the_horizon_ft._Nova_Twins_FULL_VERSION_ROLEE_Piano_Cover.mscz "$T/t.mscz" && .venv/bin/python scripts/apply_harmony_pedal.py "$T/t.mscz" | tail -1 && scripts/mscore.sh "$T/t.mscz" -o "$T/t.pdf"; ls -la "$T/t.pdf"
```
Expected: a line starting `harmony pedal: 138 measures,` and a non-empty `t.pdf` (judge by the file, not mscore's exit code). Skip if the directory does not exist, and say so.

- [ ] **Step 7: Commit**

```bash
git add scripts/analyze_pedaling.py scripts/apply_harmony_pedal.py scripts/test_analyze_pedaling.py
git commit -m "pedal: bass harmony from the lowest note (not the smallest pc); private temp dirs"
```

---

### Task 6: Rebuild `split_hands_midi.py` on DuET's staff assignment

**Files:**
- Modify: `scripts/split_hands_midi.py` (whole file)
- Create: `scripts/test_split_hands_midi.py`

**Interfaces:**
- Consumes: `all_notes(pm)` from `transcription_cleanup` (existing; returns notes sorted by `(start, pitch)`).
- Fact this relies on (verified): row *i* of `score.npz["notes"]` is the *i*-th note of the MIDI DuET engraved, in `(start, pitch)` order. Column 0 is the MIDI pitch, column 3 is the staff (0 = upper/treble, 1 = lower/bass).
- Produces: `split(pm, npz_pitches, npz_staff, hand) -> list[pretty_midi.Note]`; `write_hand(in_path, npz_path, out_path, hand) -> tuple[int, int]`; CLI `scripts/split_hands_midi.py <cleaned.mid> <score.npz> <out.mid> [--hand bass|treble]` (default `bass`).

- [ ] **Step 1: Write the failing test** — create `scripts/test_split_hands_midi.py` with exactly:

```python
"""Regression test: split_hands_midi follows DuET's per-note staff assignment.

Run: .venv/bin/python scripts/test_split_hands_midi.py
"""
import numpy as np
import pretty_midi

from split_hands_midi import split
from transcription_cleanup import all_notes


def performance():
    pm = pretty_midi.PrettyMIDI(initial_tempo=120.0)
    inst = pretty_midi.Instrument(program=0)
    for i in range(8):  # bass line under a melody, same onsets
        t = i * 0.5
        inst.notes.append(pretty_midi.Note(velocity=80, pitch=72 + i, start=t, end=t + 0.5))
        inst.notes.append(pretty_midi.Note(velocity=80, pitch=40 + i, start=t, end=t + 0.5))
    pm.instruments.append(inst)
    return pm


def test_split_follows_the_staff_column():
    pm = performance()
    pitches = np.array([n.pitch for n in all_notes(pm)])
    staff = np.array([1 if p < 60 else 0 for p in pitches])
    staff[1] = 1  # DuET put the first melody note (72) on the lower staff: a crossing
    lo = split(pm, pitches, staff, "bass")
    hi = split(pm, pitches, staff, "treble")
    assert len(lo) == 9 and len(hi) == 7, (len(lo), len(hi))
    assert 72 in [n.pitch for n in lo], "the crossed note must follow DuET's staff, not a pitch threshold"
    print("ok: hands follow DuET's staff column, including a crossed note")


def test_mismatched_npz_is_refused():
    pm = performance()
    pitches = np.array([n.pitch for n in all_notes(pm)])
    staff = np.zeros(len(pitches), dtype=int)
    for bad_p, bad_s in ((pitches[:-1], staff[:-1]), (pitches + 1, staff)):
        try:
            split(pm, bad_p, bad_s, "bass")
        except SystemExit as e:
            assert "does not match" in str(e), e
        else:
            raise AssertionError("expected SystemExit")
    print("ok: a score.npz from a different MIDI is refused")


if __name__ == "__main__":
    test_split_follows_the_staff_column()
    test_mismatched_npz_is_refused()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/python scripts/test_split_hands_midi.py`
Expected: `ImportError: cannot import name 'assign_hands' from 'transcription_cleanup'`.

- [ ] **Step 3: Replace `scripts/split_hands_midi.py`** with exactly:

```python
#!/usr/bin/env python3
"""Write a one-hand MIDI from a cleaned transcription.

The hand of each note is DuET's own staff assignment (score.npz, written next
to the score when DuET engraved this MIDI), so the extracted hand matches what
the bass (or treble) staff shows. A static pitch threshold is NOT used: solo
piano hands overlap in register and cross, which a threshold cannot follow.

    .venv/bin/python scripts/split_hands_midi.py <cleaned.mid> <score.npz> <out.mid> [--hand bass|treble]

Pass the SAME .mid DuET engraved (normally <slug>.cleaned.mid) and the
score.npz from that run; a mismatch is refused. Tempo / time-signature / key
meta and the performed CC64 are carried over verbatim: the result is the same
recording with one hand muted.
"""
import argparse
import os
import sys

import numpy as np
import pretty_midi

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from transcription_cleanup import all_notes  # noqa: E402

STAFF_OF_HAND = {"treble": 0, "bass": 1}  # score.npz notes[:, 3]: 0 upper, 1 lower


def split(pm, npz_pitches, npz_staff, hand):
    """Notes of `pm` that DuET put on `hand`'s staff. Row i of the npz arrays
    is the i-th note of `pm` in (start, pitch) order — the order all_notes returns."""
    notes = all_notes(pm)
    if len(notes) != len(npz_pitches) or any(
            n.pitch != int(p) for n, p in zip(notes, npz_pitches)):
        raise SystemExit(
            f"score.npz does not match this MIDI ({len(npz_pitches)} vs {len(notes)} notes, "
            "or different pitches) — pass the .mid that DuET engraved and its own score.npz")
    want = STAFF_OF_HAND[hand]
    return [n for n, s in zip(notes, npz_staff) if int(s) == want]


def write_hand(in_path, npz_path, out_path, hand):
    pm = pretty_midi.PrettyMIDI(in_path)
    rows = np.load(npz_path)["notes"]
    kept = split(pm, rows[:, 0], rows[:, 3], hand)

    _, tempi = pm.get_tempo_changes()
    out = pretty_midi.PrettyMIDI(initial_tempo=float(tempi[0]) if len(tempi) else 120.0)
    out.time_signature_changes = list(pm.time_signature_changes)
    out.key_signature_changes = list(pm.key_signature_changes)

    inst = pretty_midi.Instrument(program=0, name=f"Piano ({hand})")
    for n in kept:
        inst.notes.append(pretty_midi.Note(
            velocity=n.velocity, pitch=n.pitch, start=n.start, end=n.end))
    # ponytail: pedal is shared by both hands, so it is copied whole, not split.
    for src in pm.instruments:
        for cc in src.control_changes:
            if cc.number == 64:
                inst.control_changes.append(
                    pretty_midi.ControlChange(64, cc.value, cc.time))
    out.instruments.append(inst)
    out.write(out_path)
    return len(kept), len(all_notes(pm))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", help="the .mid DuET engraved (normally <slug>.cleaned.mid)")
    ap.add_argument("npz", help="score.npz from that DuET run")
    ap.add_argument("output", help="destination .mid")
    ap.add_argument("--hand", choices=("bass", "treble"), default="bass",
                    help="bass = lower staff / left hand (default), treble = upper staff / right hand")
    args = ap.parse_args()

    kept, total = write_hand(args.input, args.npz, args.output, args.hand)
    print(f"{args.output}: {kept} of {total} notes ({args.hand})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python scripts/test_split_hands_midi.py`
Expected: two lines starting `ok:`.

- [ ] **Step 5: Integration check** (writes only to a temp dir)

Run:
```bash
.venv/bin/python scripts/split_hands_midi.py output/1x1_-_Bring_me_the_horizon_ft._Nova_Twins_FULL_VERSION_ROLEE_Piano_Cover/1x1_-_Bring_me_the_horizon_ft._Nova_Twins_FULL_VERSION_ROLEE_Piano_Cover.cleaned.mid output/1x1_-_Bring_me_the_horizon_ft._Nova_Twins_FULL_VERSION_ROLEE_Piano_Cover/score.npz "$(mktemp -d)/bass.mid"
```
Expected: a line ending `742 of 1861 notes (bass)`. Skip if the directory does not exist, and say so.

- [ ] **Step 6: Commit**

```bash
git add scripts/split_hands_midi.py scripts/test_split_hands_midi.py
git commit -m "split_hands_midi: rebuild on DuET's score.npz staff assignment (assign_hands is gone)"
```

---

### Task 7: Make the docs and skills true again

**Files (all Modify):** `CLAUDE.md`, `README.md`, `docs/WHY_MIDI_TO_SCORE_IS_HARD.md`, `scripts/simplify_score.py`, `.claude/skills/transcribe/SKILL.md`, `.claude/skills/download-audio/SKILL.md`, `.claude/skills/audio-to-midi/SKILL.md`, `.claude/skills/midi-to-musicxml/SKILL.md`, `.claude/skills/cleanup-score/SKILL.md`

Every edit below is "find the text on the left, replace it with the text on the right". "Whole bullet" / "whole paragraph" means from the quoted beginning through the end of that bullet or paragraph (up to the next blank line or next list item). Quoted beginnings are unique in their file. Text given as replacement is exact — copy it verbatim, including em dashes.

**Shared replacement S1 — the stage-1 command block.** Wherever a code block contains the four lines beginning `.venv/bin/yt-dlp -x`, `scripts/prepare_audio.sh`, `mv `, and `/opt/homebrew/bin/ffmpeg -i` (or `ffmpeg -i` in README), replace **those lines only** (keep surrounding comment lines) with:

```bash
.venv/bin/yt-dlp -x --audio-format wav --restrict-filenames \
  -o 'output/%(title)s/%(title)s.source.%(ext)s' '<url>'
scripts/prepare_audio.sh 'output/<slug>/<slug>.source.wav' 'output/<slug>/<slug>.wav' \
  && rm 'output/<slug>/<slug>.source.wav'
/opt/homebrew/bin/ffmpeg -i 'output/<slug>/<slug>.wav' -codec:a libmp3lame -q:a 0 \
  'output/<slug>/<slug>.mp3'
```

S1 applies in four places: `CLAUDE.md`, `README.md`, `.claude/skills/transcribe/SKILL.md`, `.claude/skills/download-audio/SKILL.md`. (In `download-audio` the three commands sit under `# 1.`, `# 2.`, `# 3.` comment lines — keep those comments, each above its command.)

**Shared replacement S2 — the tempo-normalizer command.** Wherever a code block contains

```bash
.venv/bin/python scripts/normalize_meter_tempo.py \
  'output/<slug>/<slug>.musicxml' 'output/<slug>/<slug>.musicxml' \
  --tempo <bpm> --meter <B/T>
```

(README writes it without quotes, on two lines) replace it with

```bash
.venv/bin/python scripts/normalize_tempo.py \
  'output/<slug>/<slug>.musicxml' 'output/<slug>/<slug>.musicxml' --tempo <bpm>
```

S2 applies in three places: `CLAUDE.md`, `README.md`, `.claude/skills/midi-to-musicxml/SKILL.md`.

- [ ] **Step 1: `CLAUDE.md`** — apply S1, S2, and:

| # | Find | Replace with |
|---|------|--------------|
| C1 | whole bullet beginning ``- `scripts/normalize_meter_tempo.py <in> <out> --tempo <bpm> --meter <B/T>` `` | ``- `scripts/normalize_tempo.py <in> <out> --tempo <bpm>` — overrides DuET's model-inferred tempo with the ground truth: sets ONE constant quarter-note tempo (first metronome mark and first `<sound tempo>`; every other mark and hidden playback tempo change is removed; *rit.* / *a tempo* text stays). Run it right after DuET on the raw `<slug>.musicxml` — it exits 1 on a MuseScore-regenerated file. Targeted text edit (NOT a music21 round-trip). There is no meter override: a wrong meter is flagged in `CLEANUP_NOTES.md` for hand re-barring.`` |
| C2 | whole bullet beginning ``- `scripts/prepare_audio.sh <in> <out.wav>` `` | ``- `scripts/prepare_audio.sh <in> <out.wav>` — one static gain toward −16 LUFS (capped so the true peak stays ≤ −1.5 dBTP) + 44.1 kHz resample; run on all audio before Transkun.`` |
| C3 | the sentence ``Use instead of CC64-derived pedal, which is binary and doesn't track harmony.`` | ``Use instead of CC64-derived pedal, which is binary and doesn't track harmony. It replaces the pedal marks DuET itself writes. Known limitation: "harmony change" means the lowest bass note at the half-bar differs from beat 1, so an arpeggiated left hand is over-split.`` |
| C4 | the sentence ``Standalone MusicXML→MusicXML; run on a DuET score when it's too dense to play.`` | ``Standalone MusicXML→MusicXML; run on a DuET score when it's too dense to play. Unlike the other score scripts it IS a music21 round-trip, so re-inspect the result.`` followed by a new bullet on the next line: ``- `scripts/split_hands_midi.py <cleaned.mid> <score.npz> <out.mid> [--hand bass\|treble]` — one-hand MIDI (the performance with the other hand muted), using DuET's per-note staff assignment from `score.npz`. Pass the same `.mid` DuET engraved; a mismatch is refused.`` (write the pipe as a plain `|` — the backslash is only table escaping here) |
| C5 | the comment lines ``# 4b. (Optional) Override DuET's inferred meter/tempo with the ground truth. DuET`` through ``#     overfull bars. Verify the trimmed beats by ear.`` (5 comment lines) | ``# 4b. (Optional) Override DuET's inferred tempo with the ground truth. DuET infers`` / ``#     a tempo per section (visible marks plus hidden playback changes). Run when the`` / ``#     web ground-truth tempo is known and differs: sets one constant tempo. There is`` / ``#     no meter override — flag a wrong meter in CLEANUP_NOTES.md.`` (4 comment lines) |
| C6 | ``- `midi-to-musicxml` — stage 3 only (DuET engraving + metadata + .mscz/.pdf + harmony pedaling)`` | ``- `midi-to-musicxml` — stages 4–6 (DuET engraving + metadata + .mscz/.pdf + harmony pedaling)`` |
| C7 | ``- `transcribe` — full pipeline from a YouTube URL; use for "transcribe this video" requests`` | ``- `transcribe` — full pipeline from a YouTube URL, including `verify` and `CLEANUP_NOTES.md`; use for "transcribe this video" requests`` |
| C8 | whole bullet beginning ``- **Dynamics are out of scope**`` | ``- **Dynamics are DuET's first draft**: DuET writes block dynamics (roughly one mark per 8 bars, model-inferred). They ship in the score as a starting point; the user refines them by hand from the recording. Do not add further dynamics from velocity.`` |
| C9 | ``(and applies linear loudness normalization — never dynamic-mode loudnorm, which compresses dynamics and skews velocities)`` | ``(and applies one static gain — never ffmpeg's two-pass `loudnorm`, which silently falls back to dynamic compression when the peak or loudness range exceeds its targets, skewing velocities)`` |
| C10 | whole bullet beginning ``- Stages are re-run safe by convention`` | ``- Stages are re-run safe by convention: before running a stage, check whether its output file already exists and is non-empty, and skip it unless the user asked to redo it. Stage 1 is complete only when `<slug>.wav` exists AND `<slug>.source.wav` does not (a leftover `.source.wav` means preparation did not finish — re-run `prepare_audio.sh`).`` |
| C11 | whole bullet beginning ``- **DuET infers meter and tempo from the model — they can be wrong.**`` | ``- **DuET infers meter and tempo from the model — they can be wrong.** Tempo: if the web ground-truth tempo is known and differs, run `scripts/normalize_tempo.py --tempo <bpm>` right after DuET; it forces one constant tempo (visible marks and hidden playback changes). Meter: there is no override, in DuET or here — record the mismatch in `CLEANUP_NOTES.md` for hand re-barring in MuseScore.`` |

- [ ] **Step 2: `README.md`** — apply S1 (keep its `<youtube-url>` placeholder in place of `<url>`), S2, and:

| # | Find | Replace with |
|---|------|--------------|
| R0 | ``yt-dlp + prepare_audio.sh (decode once, linear loudness-normalize, 44.1 kHz)`` | ``yt-dlp + prepare_audio.sh (decode once, one static gain, 44.1 kHz)`` |
| R1 | ``> and **no dynamics** (add those by hand). **The rest is expected to be finished`` | ``> and only block-level draft dynamics (refine those by hand). **The rest is expected to be finished`` |
| R2 | ``← raw transcription (the faithful "recording")`` | ``← raw transcription (untouched original)`` |
| R3 | ``removes transcription artifacts (ghost notes at piano-partial intervals, duplicates — pedal- and harmony-aware, so in-key consonant notes are flagged rather than deleted)`` | ``removes transcription artifacts (short quiet blips — kept and flagged instead when in-key and consonant; quiet notes at piano-partial intervals above a louder simultaneous note, with a pedal-aware threshold; duplicates)`` |
| R4 | the two comment lines ``# (Optional) If DuET's inferred meter/tempo disagree with the ground truth,`` and ``# force a constant tempo + one consistent meter (trims overfull bars).`` | ``# (Optional) If DuET's inferred tempo disagrees with the ground truth,`` and ``# force one constant tempo. (No meter override — re-bar by hand in MuseScore.)`` |
| R5 | the sentence ``The MIDI → MusicXML stage itself is DuET, not this script.`` | ``The MIDI → MusicXML stage itself is DuET, not this script. `scripts/split_hands_midi.py <cleaned.mid> <score.npz> <out.mid> [--hand bass|treble]` writes a one-hand MIDI (the performance with the other hand muted) from DuET's staff assignment.`` |
| R6 | whole bullet beginning ``- **Dynamics are absent**`` — but only its first sentence, ``- **Dynamics are absent** — DuET writes none; add them by hand from the recording.`` | ``- **Dynamics are a first draft** — DuET writes block dynamics (roughly one mark per 8 bars); refine them by hand from the recording.`` |
| R7 | whole bullet beginning ``- DuET infers the meter and tempo from the model, and that inference can be wrong`` | ``- DuET infers the meter and tempo from the model, and that inference can be wrong. When the true tempo is known, `scripts/normalize_tempo.py --tempo <bpm>` forces one constant tempo — run it right after DuET. There is no meter override; a wrong meter is flagged in `CLEANUP_NOTES.md` and re-barred by hand.`` |
| R8 | ``which of our failures are irreducible vs. fixable, and the concrete roadmap for the fixable ones.`` | ``and which failures are irreducible vs. fixable (its §6 roadmap describes the retired pre-DuET quantizer and is historical).`` |
| R9 | ``— cited survey of the performance-to-score literature + this pipeline's roadmap`` | ``— cited survey of the performance-to-score literature (§6 is historical: it describes the retired pre-DuET quantizer)`` |

- [ ] **Step 3: `docs/WHY_MIDI_TO_SCORE_IS_HARD.md`**

- Directly below the heading line `## 6. What concretely can be done here` insert a blank line and then:

  ``> **Historical (pre-DuET).** This section describes the in-house quantizer (`quantize`, `post`, `beats --refine`, `test_quantize_grid.py`) that was retired when DuET took over the MIDI → score step. None of those commands exist any more. It is kept as a record of why that approach was hard.``

- Replace ``forbids it and quantizes in-house`` with ``forbids it (it quantized in-house when this was written; DuET does that step now)``.

- [ ] **Step 4: `scripts/simplify_score.py`**

- In the module docstring replace the two lines

  ```
  C. Cap hand span at an octave: drop inner notes whose pitch class is still
     present in the same-time two-hand aggregate until the chord fits a hand.
  ```
  with
  ```
  C. Cap hand span at an octave: shrink from the unprotected end (RH drops its
     bottom note, LH its top) — dropping a note whose pitch class is still
     present in the same-time two-hand aggregate, otherwise folding it an
     octave inward — until the chord fits a hand.
  ```
- Delete the line `            prev_pitches = set(ps)` (and the blank line directly above it).
- Run: `.venv/bin/python scripts/test_simplify_score.py` → four lines starting `ok:`.

- [ ] **Step 5: `.claude/skills/download-audio/SKILL.md`** — apply S1, and replace the whole bullet beginning ``- `scripts/prepare_audio.sh` does two-pass EBU R128 loudnorm`` with:

  ``- `scripts/prepare_audio.sh` measures EBU R128 loudness and true peak, then applies **one static gain** toward −16 LUFS, capped so the true peak stays ≤ −1.5 dBTP (a peaky recording ends quieter than −16 rather than being compressed — compression would skew the velocities Transkun emits), and resamples to the 44.1 kHz the model expects. The `&& rm` removes the unprepared download only on success: a leftover `.source.wav` means preparation did not finish.``

- [ ] **Step 6: `.claude/skills/audio-to-midi/SKILL.md`**

| Find | Replace with |
|------|--------------|
| ``it also applies linear loudness normalization, which keeps velocities in the model's comfortable range`` | ``it also applies one static gain toward −16 LUFS, which keeps velocities in the model's comfortable range`` |
| ``python3.11 -m venv .venv && .venv/bin/pip install transkun yt-dlp`.`` | ``python3.11 -m venv .venv && .venv/bin/pip install transkun yt-dlp music21 'llvmlite==0.42.0' 'numba==0.59.1' librosa`.`` |

- [ ] **Step 7: `.claude/skills/midi-to-musicxml/SKILL.md`** — apply S2, and:

| # | Find | Replace with |
|---|------|--------------|
| M1 | in the frontmatter `description:`, ``Use for stage 3 of the transcription pipeline`` | ``Use for stages 4–6 of the transcription pipeline`` |
| M2 | ``It does **not** write dynamics (add those by hand) and it sets only the title from the input filename (add the rest in step 2).`` | ``It also writes block dynamics (a first draft the user refines by hand) and its own pedal marks (replaced by harmony pedaling in step 5). It sets only the title from the input filename (add the rest in step 3).`` |
| M3 | the heading ``## 2. (Optional) Normalize meter/tempo to the ground truth`` | ``## 2. (Optional) Normalize the tempo to the ground truth`` |
| M4 | whole paragraph beginning ``DuET infers the meter and per-section tempo from the model, and **has no override flag**`` | ``DuET infers a tempo per section — visible metronome marks plus hidden `<sound tempo>` playback changes — and **has no override flag**. If the web ground-truth tempo is known and differs from what DuET engraved, force it. Check the engraved meter/tempo first:`` |
| M5 | the line ``grep -oE '<per-minute>[0-9]+' 'output/<slug>/<slug>.musicxml'`` | ``grep -oE '<per-minute>[0-9]+\|<sound tempo="[0-9]+' 'output/<slug>/<slug>.musicxml'`` (write the alternation as a plain `|`) |
| M6 | ``If they disagree with the ground truth, run the normalizer (right after DuET, before metadata):`` | ``If the tempo disagrees with the ground truth, run the normalizer (right after DuET, on the raw DuET file, before metadata — it exits 1 on a MuseScore-regenerated file):`` |
| M7 | whole paragraph beginning ``It sets ONE constant quarter-note tempo and rewrites every bar to a single meter`` | ``It sets ONE constant quarter-note tempo: the first metronome mark and first playback tempo are set, all others removed; *rit.* / *a tempo* text stays. It is a targeted text edit (not a music21 round-trip), so the rest of the engraving is intact. Skip this step when DuET's tempo already matches. **Meter has no override**: if the engraved meter disagrees with the ground truth, do not try to fix it — tell the user and record it for `CLEANUP_NOTES.md` (re-barring is done by hand in MuseScore).`` |

- [ ] **Step 8: `.claude/skills/cleanup-score/SKILL.md`**

| # | Find | Replace with |
|---|------|--------------|
| K1 | ``The score is a foundation to finish by hand (dynamics are added manually), not a final edition.`` | ``The score is a foundation to finish by hand (its dynamics are DuET's block-level draft, refined manually), not a final edition.`` |
| K2 | the sentence beginning ``For meter/tempo there is a fix: run `scripts/normalize_meter_tempo.py`` through the end of that paragraph | ``For tempo there is a fix: run `scripts/normalize_tempo.py --tempo <bpm>` on `<slug>.musicxml` right after DuET (see the `midi-to-musicxml` skill, step 2). For meter there is none — flag the mismatch.`` |
| K3 | ``**normalize the meter/tempo to ground truth if they disagree** (step 2 of that skill — DuET infers both from the model and has no override flag; a common failure is a piece in one meter rendered with mixed meters and tempo changes)`` | ``**normalize the tempo to ground truth if it disagrees** (step 2 of that skill — DuET infers it per section and has no override flag; a wrong meter cannot be normalized and is flagged instead)`` |
| K4 | ``if the meter/tempo were normalized, every measure is tick-balanced for the target meter and there is exactly one metronome mark at the ground-truth BPM.`` | ``if the tempo was normalized, there is exactly one metronome mark and one `<sound tempo>` at the ground-truth BPM.`` |
| K5 | ``meter/tempo normalization (from the normalizer's report: which measures were trimmed and what was removed — trimmed beats are *removed content*, so they go in the verify-by-ear list), metadata set`` | ``tempo normalization (from the normalizer's report: marks and hidden tempo changes removed), metadata set`` |
| K6 | the line ``   - **dynamics are absent by design** — add them by hand from the recording (DuET writes none)`` | two lines: ``   - **dynamics are DuET's block-level draft** (roughly one mark per 8 bars) — refine them by hand from the recording`` and ``   - **meter**: if DuET's engraved meter disagrees with ground truth, say which bars — there is no automatic fix; re-bar by hand in MuseScore`` |

- [ ] **Step 9: `.claude/skills/transcribe/SKILL.md`** — apply S1, and:

| # | Find | Replace with |
|---|------|--------------|
| T1 | ``run DuET on `<slug>.cleaned.mid` → `<slug>.musicxml`, set the metadata`` | ``run DuET on `<slug>.cleaned.mid` → `<slug>.musicxml`, normalize the tempo to ground truth if it disagrees, set the metadata`` |
| T2 | the heading ``## Wrap up`` | a new section followed by the heading: ``## Stage 5 — Verify and write the hand-off`` / blank line / ``Follow the `cleanup-score` skill, steps 5–6: the note-type histogram, the `verify` pass (score-vs-recording chroma, written to `verify.json`), and `CLEANUP_NOTES.md` with the verify-by-ear checklist, including DuET's `review.json` items. Do not redo steps 1–4 — the cleaned MIDI and the score already exist.`` / blank line / ``## Wrap up`` |
| T3 | ``Report all artifact paths (mp3, mid, cleaned.mid, musicxml, mscz, pdf) and:`` | ``Report all artifact paths (mp3, mid, cleaned.mid, musicxml, mscz, pdf, CLEANUP_NOTES.md), the top human-attention items from `CLEANUP_NOTES.md`, and:`` |
| T4 | whole bullet beginning ``- Suggest running `/cleanup-score output/<slug>/` next`` | delete the bullet |
| T5 | ``- **Dynamics are not engraved** — the user adds them by hand from the recording.`` | ``- **Dynamics are DuET's block-level draft** — the user refines them by hand from the recording.`` |

- [ ] **Step 10: Verify nothing stale remains**

Run:
```bash
grep -rn "normalize_meter_tempo\|--meter\|writes none\|not write dynamics\|absent by design\|not engraved\|\.prepared\.wav\|linear loudness\|linear loudnorm\|trimming\|trimmed beats\|overfull" CLAUDE.md README.md .claude/skills scripts
```
Expected: no output.

Run: `grep -c "source.wav" CLAUDE.md README.md .claude/skills/transcribe/SKILL.md .claude/skills/download-audio/SKILL.md`
Expected: every file shows a count of at least 3.

Run all tests:
```bash
bash scripts/test_prepare_audio.sh && for t in normalize_tempo transcription_cleanup analyze_pedaling split_hands_midi simplify_score; do .venv/bin/python scripts/test_$t.py || break; done
```
Expected: 18 lines starting `ok:` (prepare_audio 3, normalize_tempo 3, transcription_cleanup 3, analyze_pedaling 3, split_hands_midi 2, simplify_score 4), no traceback.

- [ ] **Step 11: Commit**

```bash
git add CLAUDE.md README.md docs/WHY_MIDI_TO_SCORE_IS_HARD.md scripts/simplify_score.py .claude/skills
git commit -m "docs+skills: match reality — DuET writes dynamics/pedal, tempo-only normalizer, static gain, transcribe runs verify"
```
