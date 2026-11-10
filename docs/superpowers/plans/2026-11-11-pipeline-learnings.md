# Pipeline Learnings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fold what the 1x1 and Strangers transcriptions taught us into the pipeline: measure bar timing instead of trusting DuET's meter/tempo, keep the raw DuET score, make the tempo/meter scripts work on MuseScore exports, retry MuseScore inside its wrapper, and stop `verify` scoring silent bars.

**Architecture:** Four independent code lanes run concurrently (each owns disjoint files), then one docs lane. The three MusicXML editing scripts move onto a shared ElementTree loader so they accept both raw DuET output and MuseScore exports.

**Tech Stack:** Python 3.11 (`.venv/bin/python`), `numpy`, `pretty_midi`, stdlib `xml.etree.ElementTree`, bash.

**Spec:** None; the six changes were agreed in conversation and are restated per task.

## Global Constraints

- Run Python only as `.venv/bin/python`. Never `pip install`.
- Never prefix a command with `cd`. All paths are relative to the repo root (the working directory).
- Tests are plain scripts in `scripts/`, run as `.venv/bin/python scripts/test_<name>.py` (or `bash scripts/test_<name>.sh`); each test function prints `ok: <description>`; the `__main__` block calls every test in file order. No pytest, no fixture files.
- Do not read, write or delete anything under `output/` except where a step gives the exact command.
- **Only the orchestrator runs git.** A subagent never runs any `git` command.
- Touch only the files your lane lists. Other agents are editing other files in the same working tree at the same time.
- Code blocks are copied verbatim. If an "Expected" output does not appear, stop and report the actual output; do not improvise.

## Review Focus

1. **MuseScore-exported MusicXML** (pretty-printed, attributes on tags, dotted-quarter metronome) into `normalize_tempo.py` and `relabel_meter.py` → must work, not exit 1. (Tests in Task C.)
2. **MuseScore exits 134 after writing** → wrapper returns 0; **exits 0 without writing** → wrapper returns non-zero. (Tests in Task D.)
3. **A failed export must not destroy the previous output file.** (Test in Task D.)
4. **A bar whose rendered or recorded audio is silent** → skipped and listed, not scored 0.0. (Test in Task E.)
5. **`score.npz` bar count differs from the engraved score's** → `bar_timing.py` reports `stretched_bars: null`, no crash. (Test in Task A.)

## Execution Waves

Dispatch with the Agent tool (`subagent_type: "general-purpose"`, `model: "sonnet"`), all lanes of a wave in one message. No worktree isolation (tests need `.venv/`). Each prompt: read this plan's Global Constraints and the lane's task, execute it, run no git, report every verification command's output.

| Wave | Lane | Task | Files it owns |
|------|------|------|---------------|
| 1 | A | bar timing | `scripts/bar_timing.py`, `scripts/test_bar_timing.py` |
| 1 | C | MusicXML scripts on ElementTree | `scripts/musicxml_io.py`, `scripts/normalize_tempo.py`, `scripts/relabel_meter.py`, `scripts/fill_rests.py`, `scripts/test_normalize_tempo.py`, `scripts/test_relabel_meter.py` |
| 1 | D | MuseScore wrapper retry | `scripts/mscore.sh`, `scripts/test_mscore_wrapper.sh` |
| 1 | E | verify skips silent bars | `scripts/transcription_cleanup.py`, `scripts/test_transcription_cleanup.py` |
| 2 | F | docs | `CLAUDE.md`, `README.md`, `.claude/skills/midi-to-musicxml/SKILL.md`, `.claude/skills/cleanup-score/SKILL.md` |

After Wave 1 the orchestrator re-runs every test, runs the integration checks in **Orchestrator Checks**, and commits one commit per lane. After Wave 2 it commits the docs.

---

### Task A: `scripts/bar_timing.py`

**Files:** Create `scripts/bar_timing.py`, `scripts/test_bar_timing.py`.

**Interfaces (produces):**
- `analyze(times, onsets, bar_starts, bar_lengths) -> dict` — all four are 1-D numpy arrays (`times`: performed onset in seconds per note; `onsets`: DuET's position in quarters per note; bars in quarters).
- `engraved_bar_quarters(xml_path: str) -> list[float]` — length in quarters of every measure of a MusicXML file.
- `stretched_bars(engraved: list[float], bar_lengths) -> list[int] | None` — 1-based bar numbers (first and last bar excluded) whose engraved length differs from DuET's raw length; `None` when the counts differ.
- CLI: `bar_timing.py <cleaned.mid> <score.npz> [--score <musicxml>]` prints one JSON object.

- [ ] **Step 1: Write the failing test** — create `scripts/test_bar_timing.py`:

```python
"""Regression test: bar_timing measures what the performance did, bar by bar.

Run: .venv/bin/python scripts/test_bar_timing.py
"""
import os
import tempfile

import numpy as np

from bar_timing import analyze, engraved_bar_quarters, stretched_bars


def piece(spq_per_bar, pickup=((3.0, 0.0), (3.5, 0.25)), bar1_time=0.5):
    """A 4-quarter pickup bar, then len(spq_per_bar) bars of 3 quarters in eighths.
    spq_per_bar: seconds per quarter of each 3-quarter bar. pickup: (quarter, seconds)."""
    starts, lengths = [0.0], [4.0]
    onsets, times = [q for q, _ in pickup], [t for _, t in pickup]
    t = bar1_time
    for i, spq in enumerate(spq_per_bar):
        start = 4.0 + 3.0 * i
        starts.append(start)
        lengths.append(3.0)
        for k in range(6):
            onsets.append(start + 0.5 * k)
            times.append(t + 0.5 * k * spq)
        t += 3.0 * spq
    return tuple(np.array(a) for a in (times, onsets, starts, lengths))


def test_steady_piece():
    r = analyze(*piece([0.5] * 11))
    assert r["bars"] == 12 and r["bar_quarters"] == 3.0
    assert r["measured_tempo_quarter_bpm"] == 120.0
    assert r["steady"] is True and r["unsteady_bars"] == []
    assert (r["pickup_written_quarters"], r["pickup_measured_quarters"], r["pickup_mismatch"]) == (1.0, 1.0, False)
    print("ok: a metronomic piece is steady, with its real tempo and pickup")


def test_rubato_piece():
    r = analyze(*piece([0.4, 0.6] * 5 + [0.4]))
    assert r["steady"] is False and r["steady_share"] == 0.0
    assert r["unsteady_bars"] == list(range(2, 12))
    print("ok: bars that swing 20% around the median are not steady")


def test_pickup_written_longer_than_played():
    r = analyze(*piece([0.5] * 11, pickup=((2.0, 0.0), (3.0, 0.25))))
    assert (r["pickup_written_quarters"], r["pickup_measured_quarters"], r["pickup_mismatch"]) == (2.0, 1.0, True)
    print("ok: a pickup written twice as long as it was played is flagged")


def test_engraved_lengths_and_stretched_bars():
    xml = ('<score-partwise><part id="P1">'
           '<measure number="0" implicit="yes"><attributes><time><beats>4</beats><beat-type>4</beat-type></time></attributes></measure>'
           '<measure number="1"><attributes><time><beats>3</beats><beat-type>4</beat-type></time></attributes></measure>'
           '<measure number="2"/>'
           '<measure number="3"><attributes><time><beats>4</beats><beat-type>4</beat-type></time></attributes></measure>'
           '<measure number="4"><attributes><time><beats>6</beats><beat-type>8</beat-type></time></attributes></measure>'
           '</part></score-partwise>')
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "s.musicxml")
        with open(path, "w") as f:
            f.write('<?xml version="1.0"?>\n' + xml)
        engraved = engraved_bar_quarters(path)
    assert engraved == [4.0, 3.0, 3.0, 4.0, 3.0], engraved
    assert stretched_bars(engraved, np.array([4.0, 3.0, 3.0, 3.0, 3.0])) == [4]
    assert stretched_bars(engraved, np.array([4.0, 3.0, 3.0])) is None
    print("ok: engraved bar lengths are read per measure; a bar DuET stretched is found; a count mismatch is None")


if __name__ == "__main__":
    test_steady_piece()
    test_rubato_piece()
    test_pickup_written_longer_than_played()
    test_engraved_lengths_and_stretched_bars()
```

- [ ] **Step 2: Run it** — `.venv/bin/python scripts/test_bar_timing.py` → expected `ModuleNotFoundError: No module named 'bar_timing'`.

- [ ] **Step 3: Create `scripts/bar_timing.py`:**

```python
#!/usr/bin/env python3
"""Measure how long each engraved bar really lasted in the performance.

DuET infers meter and tempo and can be wrong in ways the score alone does not
show: stray longer bars, invented tempo changes, a pickup of the wrong length.
The recording settles it. This lines up DuET's bar grid (score.npz) with the
performed note times (the MIDI DuET engraved) and reports whether the piece is
steady, its real tempo, the real pickup length, and what to do about it.

    bar_timing.py <cleaned.mid> <score.npz> [--score <raw DuET .musicxml>]

Run it right after DuET. With --score it also compares the engraved bar lengths
and playback tempos against the measurement and prints recommendations.
"""
import argparse
import collections
import json
import sys
import xml.etree.ElementTree as ET

import numpy as np
import pretty_midi

STEADY_TOLERANCE = 0.08   # a bar within 8% of the median seconds-per-quarter is on tempo
STEADY_SHARE = 0.9        # the piece is steady when this share of its bars are


def analyze(times, onsets, bar_starts, bar_lengths):
    """times: performed onset (s) per note; onsets: DuET position (quarters) per note."""
    uq = np.unique(onsets)
    ut = np.array([np.median(times[onsets == q]) for q in uq])
    edges = np.append(bar_starts, bar_starts[-1] + bar_lengths[-1])
    dur = np.diff(np.interp(edges, uq, ut))
    spq = dur / bar_lengths                      # seconds per quarter, per bar
    body = slice(1, -1)                          # the first and last bar are partial
    med = float(np.median(spq[body]))
    on_tempo = np.abs(spq[body] / med - 1) <= STEADY_TOLERANCE
    share = float(on_tempo.mean())
    lengths = collections.Counter(float(x) for x in bar_lengths[body])
    written = float(edges[1] - onsets.min())
    measured = float(np.round(dur[0] / med * 2) / 2)   # to the nearest eighth
    return {
        "bars": int(len(bar_lengths)),
        "bar_quarters": lengths.most_common(1)[0][0],
        "seconds_per_quarter": round(med, 4),
        "measured_tempo_quarter_bpm": round(60 / med, 1),
        "steady": share >= STEADY_SHARE,
        "steady_share": round(share, 2),
        "unsteady_bars": [int(i) + 2 for i in np.flatnonzero(~on_tempo)],
        "pickup_written_quarters": written,
        "pickup_measured_quarters": measured,
        "pickup_mismatch": abs(written - measured) >= 0.5,
    }


def engraved_bar_quarters(xml_path):
    """Length in quarters of every measure, from the time signatures in force."""
    with open(xml_path, encoding="utf-8") as f:
        text = f.read()
    root = ET.fromstring(text[text.index("<score-partwise"):])
    out, quarters = [], 4.0
    for measure in root.find("part").findall("measure"):
        time = measure.find("attributes/time")
        if time is not None:
            quarters = int(time.findtext("beats")) * 4 / int(time.findtext("beat-type"))
        out.append(quarters)
    return out


def stretched_bars(engraved, bar_lengths):
    """1-based numbers of the bars (first and last excluded) whose engraved length
    differs from DuET's raw bar length; None when the two bar counts differ."""
    if len(engraved) != len(bar_lengths):
        return None
    return [i + 1 for i in range(1, len(engraved) - 1) if engraved[i] != float(bar_lengths[i])]


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("performance_mid", help="the .mid DuET engraved (normally <slug>.cleaned.mid)")
    ap.add_argument("npz", help="score.npz from that DuET run")
    ap.add_argument("--score", help="the raw DuET .musicxml, to compare its bars and tempos")
    args = ap.parse_args()

    pm = pretty_midi.PrettyMIDI(args.performance_mid)
    played = sorted((n for inst in pm.instruments for n in inst.notes),
                    key=lambda n: (n.start, n.pitch))
    z = np.load(args.npz)
    rows = z["notes"]
    if len(rows) != len(played) or any(n.pitch != int(p) for n, p in zip(played, rows[:, 0])):
        sys.exit("score.npz does not match the performance MIDI — pass the .mid that DuET "
                 "engraved and its own score.npz")
    report = analyze(np.array([n.start for n in played]), rows[:, 1],
                     z["bar_starts"], z["bar_lengths"])
    advice = []
    if args.score:
        engraved = engraved_bar_quarters(args.score)
        with open(args.score, encoding="utf-8") as f:
            text = f.read()
        root = ET.fromstring(text[text.index("<score-partwise"):])
        tempos = sorted({s.get("tempo") for s in root.iter("sound") if s.get("tempo")})
        stretched = stretched_bars(engraved, z["bar_lengths"])
        report["engraved_bar_quarters"] = dict(collections.Counter(engraved))
        report["stretched_bars"] = stretched
        report["playback_tempos"] = tempos
        bpm = round(report["measured_tempo_quarter_bpm"])
        if report["steady"] and stretched:
            advice.append(f"re-run DuET with grid_count_fix false: bars {stretched} are steady "
                          "in the recording but were engraved at a different length")
        if report["steady"] and len(tempos) > 1:
            advice.append(f"normalize_tempo.py --tempo {bpm}: the recording is steady but the "
                          f"score has {len(tempos)} playback tempos")
    if report["pickup_mismatch"]:
        advice.append(f"check the pickup bar by ear: written {report['pickup_written_quarters']} "
                      f"quarters, played {report['pickup_measured_quarters']}")
    if report["bar_quarters"] == 3.0:
        advice.append("bars are 3 quarters long: 3/4 or 6/8 is a labelling choice — decide by "
                      "style, then relabel_meter.py --from 3/4 --to 6/8")
    report["recommendations"] = advice
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the test** — expected four lines starting `ok:`.

- [ ] **Step 5: Integration check** (read-only):

Run: `.venv/bin/python scripts/bar_timing.py output/Bring_Me_The_Horizon_BMTH_-_Strangers_Piano_Keyboard_Cover/Bring_Me_The_Horizon_BMTH_-_Strangers_Piano_Keyboard_Cover.cleaned.mid output/Bring_Me_The_Horizon_BMTH_-_Strangers_Piano_Keyboard_Cover/score.npz`

Expected: JSON with `"bars": 65`, `"bar_quarters": 3.0`, `"steady": true`, `"measured_tempo_quarter_bpm"` between 90 and 93, `"pickup_measured_quarters": 1.0`, and a recommendation mentioning `3/4 or 6/8`. Report the whole JSON.

---

### Task C: MusicXML scripts on ElementTree

**Files:** Create `scripts/musicxml_io.py`. Rewrite `scripts/normalize_tempo.py`, `scripts/relabel_meter.py`, `scripts/test_normalize_tempo.py`, `scripts/test_relabel_meter.py`. Modify `scripts/fill_rests.py`.

**Interfaces (produces):**
- `musicxml_io.load(path) -> (prolog: str, root: Element)`, `musicxml_io.save(path, prolog, root)`, `musicxml_io.let_musescore_rebeam(root) -> int` (beams removed).
- `normalize_tempo(root, bpm: int) -> dict` — mutates `root`; raises `ValueError` if the score has no `<metronome>`.
- `relabel(root, src: tuple[int, int], dst: tuple[int, int]) -> dict` — mutates `root`; raises `ValueError` on different bar lengths or no `<time>`.
- CLIs unchanged: `normalize_tempo.py <in> <out> --tempo <bpm>`, `relabel_meter.py <in> <out> --from A/B --to C/D`. Exit 1 with a message on `ValueError`, writing nothing.

- [ ] **Step 1: Create `scripts/musicxml_io.py`:**

```python
"""Read and write MusicXML through ElementTree, keeping the file's prolog.

Used by the score-editing scripts so each works on a raw DuET score and on a
MuseScore export alike (ElementTree does not care about whitespace or tag
attributes; the XML declaration and DOCTYPE are carried over as text).
"""
import xml.etree.ElementTree as ET


def load(path):
    """Returns (prolog, root): the text before <score-partwise>, and the parsed score."""
    with open(path, encoding="utf-8") as f:
        text = f.read()
    start = text.index("<score-partwise")
    return text[:start], ET.fromstring(text[start:])


def save(path, prolog, root):
    with open(path, "w", encoding="utf-8") as f:
        f.write(prolog + ET.tostring(root, encoding="unicode") + "\n")


def let_musescore_rebeam(root):
    """Drop every <beam>, so MuseScore beams by the meter on import. A MuseScore
    export also declares <supports element="beam"/"print">, which would make the
    next import trust the file's (now absent) beams and its old system/page
    breaks — those declarations and breaks go too. Returns the beams removed."""
    beams = 0
    for note in root.iter("note"):
        for beam in note.findall("beam"):
            note.remove(beam)
            beams += 1
    for encoding in root.iter("encoding"):
        for supports in encoding.findall("supports"):
            encoding.remove(supports)
    for pr in root.iter("print"):
        pr.attrib.pop("new-system", None)
        pr.attrib.pop("new-page", None)
    return beams
```

- [ ] **Step 2: Switch `scripts/fill_rests.py` to it.** (a) Add `from musicxml_io import let_musescore_rebeam, load, save` below `import xml.etree.ElementTree as ET`, preceded by these two lines so the import works from any directory:

```python
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
```
(place `import os` with the other imports, in alphabetical order, and the `sys.path.insert` line directly above the `from musicxml_io` import).

(b) In `fill_rests(root)`, replace everything from the line `    beams = 0` through the line `        pr.attrib.pop("new-page", None)` with the single line `    stats["beams_removed"] = let_musescore_rebeam(root)`.

(c) In `main()`, replace the block from `    with open(args.input, encoding="utf-8") as f:` through the `f.write(...)` line with:

```python
    prolog, root = load(args.input)
    stats = fill_rests(root)
    save(args.output, prolog, root)
```

Run: `.venv/bin/python scripts/test_fill_rests.py` → four lines starting `ok:`.

- [ ] **Step 3: Rewrite the tests.** Replace `scripts/test_normalize_tempo.py` with:

```python
"""Regression test: normalize_tempo forces ONE constant tempo, on DuET and MuseScore files.

Run: .venv/bin/python scripts/test_normalize_tempo.py
"""
import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

from normalize_tempo import normalize_tempo

MARK = ('<direction placement="above"><direction-type><metronome><beat-unit>quarter</beat-unit>'
        '<per-minute>{0}</per-minute></metronome></direction-type><staff>1</staff>'
        '<sound tempo="{0}"/></direction>')
DYN = '<direction><direction-type><dynamics><mp/></dynamics></direction-type><staff>1</staff></direction>'
HIDDEN = '<direction><direction-type><words/></direction-type><staff>1</staff><sound tempo="150"/></direction>'
RIT = '<direction><direction-type><words font-style="italic">rit.</words></direction-type><staff>1</staff></direction>'
DUET = ('<score-partwise><part id="P1"><measure number="1">' + MARK.format(141) + DYN + '</measure>'
        '<measure number="2">' + HIDDEN + RIT + '</measure>'
        '<measure number="3">' + MARK.format(153) + '</measure></part></score-partwise>')
MUSESCORE = '''<score-partwise version="4.0">
  <part id="P1">
    <measure number="1" width="244.72">
      <direction placement="above">
        <direction-type>
          <metronome parentheses="no" default-x="-37.68" relative-y="20">
            <beat-unit>quarter</beat-unit>
            <beat-unit-dot/>
            <per-minute>61</per-minute>
            </metronome>
          </direction-type>
        <staff>1</staff>
        <sound tempo="91.5"/>
        </direction>
      </measure>
    </part>
  </score-partwise>'''


def state(root):
    return ([m.findtext("per-minute") for m in root.iter("metronome")],
            [s.get("tempo") for s in root.iter("sound") if s.get("tempo")])


def test_duet_score_gets_one_constant_tempo():
    root = ET.fromstring(DUET)
    report = normalize_tempo(root, 93)
    assert state(root) == (["93"], ["93"]), state(root)
    assert [w.text for w in root.iter("words")] == ["rit."] and root.find(".//dynamics") is not None
    assert [len(m.findall("direction")) for m in root.iter("measure")] == [2, 1, 0]
    assert report == {"bpm": 93, "metronome_marks_removed": 1,
                      "sound_tempos_removed": 2, "empty_directions_removed": 2}, report
    print("ok: one metronome mark, one playback tempo, hidden changes gone, rit./dynamics kept")


def test_musescore_export_is_accepted():
    root = ET.fromstring(MUSESCORE)
    normalize_tempo(root, 93)
    mark = root.find(".//metronome")
    assert state(root) == (["93"], ["93"]) and mark.find("beat-unit-dot") is None
    assert mark.get("parentheses") == "no"
    print("ok: a MuseScore export (attributes, dotted-quarter mark) is normalized to quarter = N")


def test_no_metronome_is_an_error():
    try:
        normalize_tempo(ET.fromstring('<score-partwise><part id="P1"><measure number="1"/></part></score-partwise>'), 93)
    except ValueError as e:
        assert "metronome" in str(e)
    else:
        raise AssertionError("expected ValueError")
    print("ok: a score with no metronome mark raises instead of silently succeeding")


def test_cli():
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "normalize_tempo.py")
    with tempfile.TemporaryDirectory() as td:
        good, bad, out = (os.path.join(td, n) for n in ("good.xml", "bad.xml", "out.xml"))
        with open(good, "w") as f:
            f.write('<?xml version="1.0" encoding="UTF-8"?>\n' + DUET)
        with open(bad, "w") as f:
            f.write('<score-partwise><part id="P1"><measure number="1"/></part></score-partwise>')
        r = subprocess.run([sys.executable, script, good, out, "--tempo", "92.6"], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        with open(out) as f:
            text = f.read()
        assert text.startswith('<?xml version="1.0" encoding="UTF-8"?>') and "<per-minute>93</per-minute>" in text
        os.remove(out)
        r = subprocess.run([sys.executable, script, bad, out, "--tempo", "93"], capture_output=True, text=True)
        assert r.returncode == 1 and not os.path.exists(out), (r.returncode, r.stderr)
    print("ok: CLI keeps the XML declaration, rounds --tempo, exits 1 and writes nothing on error")


if __name__ == "__main__":
    test_duet_score_gets_one_constant_tempo()
    test_musescore_export_is_accepted()
    test_no_metronome_is_an_error()
    test_cli()
```

Replace `scripts/test_relabel_meter.py` with:

```python
"""Regression test: relabel_meter changes the label, the beams and the tempo unit — not the notes.

Run: .venv/bin/python scripts/test_relabel_meter.py
"""
import xml.etree.ElementTree as ET

from relabel_meter import relabel

NOTE = '<note><pitch><step>C</step><octave>4</octave></pitch><duration>12</duration><type>eighth</type>{}</note>'
RAW = ('<score-partwise><identification><encoding><supports element="beam" type="yes"/></encoding></identification>'
       '<part id="P1"><measure number="1"><print new-system="yes"/>'
       '<attributes><time><beats>3</beats><beat-type>4</beat-type></time></attributes>'
       '<direction><direction-type><metronome parentheses="no"><beat-unit>quarter</beat-unit>'
       '<per-minute>92</per-minute></metronome></direction-type><sound tempo="92"/></direction>'
       + NOTE.format('<beam number="1">begin</beam>') + NOTE.format('<beam number="1">end</beam>')
       + '</measure><measure number="2"><attributes><time><beats>4</beats><beat-type>4</beat-type></time>'
       '</attributes></measure></part></score-partwise>')


def test_three_four_becomes_six_eight():
    root = ET.fromstring(RAW)
    report = relabel(root, (3, 4), (6, 8))
    assert [(t.findtext("beats"), t.findtext("beat-type")) for t in root.iter("time")] == [("6", "8"), ("4", "4")]
    assert root.find(".//beam") is None and root.find(".//supports") is None
    assert root.find(".//print").get("new-system") is None
    assert [n.findtext("duration") for n in root.iter("note")] == ["12", "12"]
    mark = root.find(".//metronome")
    assert [c.tag for c in mark] == ["beat-unit", "beat-unit-dot", "per-minute"] and mark.findtext("per-minute") == "61"
    assert root.find(".//sound").get("tempo") == "91.5"
    assert report == {"time_signatures_relabelled": 1, "other_meters_left": ["4/4"],
                      "beams_removed": 2, "tempo_mark": "dotted quarter = 61"}, report
    print("ok: 3/4 -> 6/8 relabels the meter, drops beams and layout hints, prints a dotted-quarter tempo, keeps the notes")


def test_already_dotted_mark_is_left_alone():
    root = ET.fromstring(RAW.replace("<beat-unit>quarter</beat-unit>", "<beat-unit>quarter</beat-unit><beat-unit-dot/>"))
    report = relabel(root, (3, 4), (6, 8))
    assert root.find(".//metronome").findtext("per-minute") == "92" and report["tempo_mark"] == "left alone"
    print("ok: a tempo mark that is already dotted is not rescaled twice")


def test_different_bar_length_is_refused():
    try:
        relabel(ET.fromstring(RAW), (3, 4), (4, 4))
    except ValueError as e:
        assert "same bar length" in str(e)
    else:
        raise AssertionError("expected ValueError")
    print("ok: a meter of a different bar length is refused (that would be re-barring)")


if __name__ == "__main__":
    test_three_four_becomes_six_eight()
    test_already_dotted_mark_is_left_alone()
    test_different_bar_length_is_refused()
```

- [ ] **Step 4: Run both tests** — each fails (TypeError/AttributeError: the old functions take a string).

- [ ] **Step 5: Rewrite `scripts/normalize_tempo.py`:**

```python
#!/usr/bin/env python3
"""Force ONE constant tempo on a score.

DuET infers a tempo per section: visible metronome marks plus hidden
<sound tempo> playback changes. When the true tempo is known (measured by
bar_timing.py, or from the web), this rewrites the score to a single
quarter-note tempo.

Works on a raw DuET score.musicxml and on a MuseScore export alike.

There is deliberately no meter override. Re-barring is not a mechanical edit;
see relabel_meter.py for the one case that is.

Usage:
  normalize_tempo.py <in.musicxml> <out.musicxml> --tempo 93

What changes:
  - the first metronome mark becomes quarter = N; every other one is removed
  - the first playback tempo becomes N; every other one is removed
  - directions left empty by those removals are removed
  - text directions (rit., a tempo) and everything else are untouched
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from musicxml_io import load, save  # noqa: E402


def normalize_tempo(root, bpm):
    parents = {child: parent for parent in root.iter() for child in parent}
    marks = list(root.iter("metronome"))
    if not marks:
        raise ValueError("no <metronome> found in the score")
    first = marks[0]
    for dot in first.findall("beat-unit-dot"):
        first.remove(dot)
    first.find("beat-unit").text = "quarter"
    first.find("per-minute").text = str(bpm)
    for mark in marks[1:]:
        parents[mark].remove(mark)
    sounds = [s for s in root.iter("sound") if s.get("tempo") is not None]
    for s in sounds[:1]:
        s.set("tempo", str(bpm))
    for s in sounds[1:]:
        del s.attrib["tempo"]
        if not s.attrib and len(s) == 0:
            parents[s].remove(s)
    emptied = 0
    for direction in list(root.iter("direction")):
        content = [c for dt in direction.findall("direction-type") for c in dt
                   if not (c.tag == "words" and not (c.text or "").strip())]
        if not content and direction.find("sound") is None:
            parents[direction].remove(direction)
            emptied += 1
    return {"bpm": bpm, "metronome_marks_removed": len(marks) - 1,
            "sound_tempos_removed": max(0, len(sounds) - 1),
            "empty_directions_removed": emptied}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("output")
    ap.add_argument("--tempo", type=float, required=True,
                    help="constant quarter-note BPM for the whole piece")
    args = ap.parse_args()

    prolog, root = load(args.input)
    try:
        report = normalize_tempo(root, int(round(args.tempo)))
    except ValueError as e:
        print(f"normalize_tempo: {e}", file=sys.stderr)
        return 1
    save(args.output, prolog, root)
    print(json.dumps({"input": args.input, "output": args.output, **report}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 6: Rewrite `scripts/relabel_meter.py`:**

```python
#!/usr/bin/env python3
"""Relabel a score's meter to another meter of the SAME bar length.

DuET hears a 6/8 piece as 3/4 (six eighths per bar either way) — it has no
meter override, and re-barring is not a mechanical edit, but relabelling is:
the notes and bar lines stay exactly where they are; only the time signature,
the beaming and the tempo mark's beat unit change.

    relabel_meter.py <in.musicxml> <out.musicxml> --from 3/4 --to 6/8

Works on a raw DuET score.musicxml and on a MuseScore export alike. Run it
after normalize_tempo.py (it expects one metronome mark). What changes:
  - every time signature equal to --from becomes --to (other meters are left
    alone and reported — e.g. one stretched final bar)
  - all beams, system/page breaks and a MuseScore export's <supports>
    declarations are dropped, so MuseScore re-beams and re-flows by the new meter
  - if --to is compound (6/8, 9/8, 12/8) a single quarter-note metronome mark
    becomes dotted-quarter = N, with playback unchanged (the playback tempo
    stays the equivalent quarter-note tempo)
Notes that straddle the new beat (a quarter starting on the third eighth of a
6/8 bar) are NOT re-spelled as tied notes; regroup them in MuseScore
(Tools > Regroup Rhythms).
"""
import argparse
import json
import os
import sys
import xml.etree.ElementTree as ET
from fractions import Fraction

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from musicxml_io import let_musescore_rebeam, load, save  # noqa: E402


def relabel(root, src, dst):
    """src/dst: (beats, beat_type). Mutates root; returns the report."""
    if Fraction(*src) != Fraction(*dst):
        raise ValueError(f"{src[0]}/{src[1]} and {dst[0]}/{dst[1]} are not the same bar length")
    times = list(root.iter("time"))
    if not times:
        raise ValueError("no <time> found in the score")
    relabelled, other = 0, set()
    for time in times:
        current = (int(time.findtext("beats")), int(time.findtext("beat-type")))
        if current == src:
            time.find("beats").text, time.find("beat-type").text = str(dst[0]), str(dst[1])
            relabelled += 1
        elif current != dst:
            other.add(f"{current[0]}/{current[1]}")
    report = {"time_signatures_relabelled": relabelled, "other_meters_left": sorted(other),
              "beams_removed": let_musescore_rebeam(root)}
    if dst[1] == 8 and dst[0] % 3 == 0 and dst[0] > 3:   # compound meter
        marks = list(root.iter("metronome"))
        if (len(marks) == 1 and marks[0].findtext("beat-unit") == "quarter"
                and marks[0].find("beat-unit-dot") is None):
            mark = marks[0]
            dotted = round(float(mark.findtext("per-minute")) * 2 / 3)
            mark.insert(list(mark).index(mark.find("beat-unit")) + 1, ET.Element("beat-unit-dot"))
            mark.find("per-minute").text = str(dotted)
            for sound in root.iter("sound"):
                if sound.get("tempo") is not None:
                    # playback is in quarter notes per minute: keep it equal to the printed mark
                    sound.set("tempo", f"{dotted * 1.5:g}")
                    break
            report["tempo_mark"] = f"dotted quarter = {dotted}"
        else:
            report["tempo_mark"] = "left alone"
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("output")
    ap.add_argument("--from", dest="src", required=True, help="meter in the score, e.g. 3/4")
    ap.add_argument("--to", dest="dst", required=True, help="meter to print, e.g. 6/8")
    args = ap.parse_args()

    prolog, root = load(args.input)
    try:
        report = relabel(root, tuple(int(x) for x in args.src.split("/")),
                         tuple(int(x) for x in args.dst.split("/")))
    except ValueError as e:
        print(f"relabel_meter: {e}", file=sys.stderr)
        return 1
    save(args.output, prolog, root)
    print(json.dumps({"input": args.input, "output": args.output, **report}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 7: Run all three tests**

`.venv/bin/python scripts/test_normalize_tempo.py` → 4 `ok:` lines; `.venv/bin/python scripts/test_relabel_meter.py` → 3; `.venv/bin/python scripts/test_fill_rests.py` → 4.

---

### Task D: `scripts/mscore.sh` retries and never destroys a good output

**Files:** Rewrite `scripts/mscore.sh`. Create `scripts/test_mscore_wrapper.sh`.

**Interfaces (produces):** `scripts/mscore.sh <args…>` — unchanged call shape. When the arguments contain `-o <out>`: MuseScore writes to a temporary sibling file, up to 3 attempts; on a non-empty result it is moved onto `<out>` and the wrapper exits 0 (whatever MuseScore's exit code); if no attempt produced a file, `<out>` is left as it was and the wrapper exits non-zero. Without `-o`: plain pass-through.

- [ ] **Step 1: Write the failing test** — create `scripts/test_mscore_wrapper.sh`:

```bash
#!/bin/bash
# Regression test: scripts/mscore.sh retries, trusts the file not the exit code,
# and never destroys an existing output on failure.
# Run: bash scripts/test_mscore_wrapper.sh
set -uo pipefail
T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT

fake() { printf '#!/bin/sh\n%s\n' "$2" > "$T/$1"; chmod +x "$T/$1"; }
out_arg='while [ "$1" != "-o" ]; do shift; done; out="$2"'

# 1. writes the file, then crashes with 134 (MuseScore's shutdown abort)
fake crashy "$out_arg"'; printf x > "$out"; exit 134'
MSCORE="$T/crashy" scripts/mscore.sh in.mscz -o "$T/a.pdf"; code=$?
[ "$code" -eq 0 ] && [ -s "$T/a.pdf" ] || { echo "FAIL: exit 134 after a good write must succeed (got $code)"; exit 1; }
echo "ok: a write followed by exit 134 counts as success"

# 2. fails twice, succeeds on the third attempt
fake flaky "$out_arg"'; n=$(cat "'"$T"'/count" 2>/dev/null || echo 0); n=$((n+1)); echo $n > "'"$T"'/count"; [ "$n" -ge 3 ] && printf x > "$out"; exit 40'
MSCORE="$T/flaky" scripts/mscore.sh in.mscz -o "$T/b.pdf"; code=$?
[ "$code" -eq 0 ] && [ -s "$T/b.pdf" ] && [ "$(cat "$T/count")" = "3" ] || { echo "FAIL: third attempt should succeed (code $code, attempts $(cat "$T/count"))"; exit 1; }
echo "ok: retries up to three times"

# 3. never writes: non-zero exit, and the previous output survives
fake dead 'exit 0'
printf old > "$T/c.pdf"
MSCORE="$T/dead" scripts/mscore.sh in.mscz -o "$T/c.pdf"; code=$?
[ "$code" -ne 0 ] && [ "$(cat "$T/c.pdf")" = "old" ] || { echo "FAIL: no file written must fail and keep the old output (code $code)"; exit 1; }
[ -z "$(ls "$T" | grep mscore-tmp)" ] || { echo "FAIL: temp file left behind"; exit 1; }
echo "ok: exit 0 without a file is a failure, and the old output is kept"

# 4. without -o: plain pass-through of arguments and exit code
fake echoer 'echo "$@"; exit 7'
got=$(MSCORE="$T/echoer" scripts/mscore.sh --version "a b"); code=$?
[ "$code" -eq 7 ] && [ "$got" = "--version a b" ] || { echo "FAIL: pass-through (code $code, got '$got')"; exit 1; }
echo "ok: without -o the call passes straight through"
```

- [ ] **Step 2: Run it** — `bash scripts/test_mscore_wrapper.sh` → expected `FAIL: exit 134 after a good write must succeed (got 134)`.

- [ ] **Step 3: Replace `scripts/mscore.sh`:**

```bash
#!/bin/bash
# Wrapper around the MuseScore 4 CLI.
#
# 1. A stable, space-free command path (scripts/mscore.sh ...) so a single
#    permission rule — Bash(scripts/mscore.sh *) — covers every MuseScore call.
#    The real binary path contains a space. Override it with the MSCORE env var.
#
# 2. Reliable conversions. MuseScore often aborts (exit 134) on shutdown AFTER
#    writing its output, and occasionally fails outright and works on a retry.
#    So for a conversion (-o <out>) the wrapper judges by the file, not the exit
#    code: MuseScore writes to a temporary sibling of <out>, up to 3 attempts;
#    a non-empty result is moved onto <out> and the wrapper exits 0. If no
#    attempt produced a file, <out> is left untouched and the wrapper exits
#    non-zero.
#
# Without -o, arguments and exit code pass through unchanged.
MSCORE_BIN="${MSCORE:-/Applications/MuseScore 4.app/Contents/MacOS/mscore}"

out=""
args=("$@")
for ((i = 0; i < ${#args[@]}; i++)); do
  if [ "${args[i]}" = "-o" ] && [ $((i + 1)) -lt ${#args[@]} ]; then
    out="${args[i + 1]}"
    out_index=$((i + 1))
  fi
done

if [ -z "$out" ]; then
  exec "$MSCORE_BIN" "$@"
fi

# same directory and extension as <out>: MuseScore picks the format by extension
tmp="${out%.*}.mscore-tmp.$$.${out##*.}"
args[out_index]="$tmp"
code=1
for attempt in 1 2 3; do
  rm -f "$tmp"
  "$MSCORE_BIN" "${args[@]}"
  code=$?
  if [ -s "$tmp" ]; then
    mv -f "$tmp" "$out"
    exit 0
  fi
done
rm -f "$tmp"
[ "$code" -ne 0 ] || code=1
exit "$code"
```

- [ ] **Step 4: Run the test** — four lines starting `ok:`, exit 0.

- [ ] **Step 5: Real conversion check** (writes only to a temp dir):

Run: `T=$(mktemp -d) && scripts/mscore.sh output/Bring_Me_The_Horizon_BMTH_-_Strangers_Piano_Keyboard_Cover/Bring_Me_The_Horizon_BMTH_-_Strangers_Piano_Keyboard_Cover.mscz -o "$T/x.pdf" >/dev/null 2>&1; echo "exit $?"; ls -la "$T"`

Expected: `exit 0`, and `$T` contains only a non-empty `x.pdf` (no `mscore-tmp` file).

---

### Task E: `verify` skips silent bars

**Files:** Modify `scripts/transcription_cleanup.py`, `scripts/test_transcription_cleanup.py`.

**Interfaces (produces):** `bar_similarity(vr, va) -> float | None` — cosine similarity of two chroma vectors; `None` when either is silent (zero or non-finite norm). `verify.json` gains `"silent_bars_skipped": [bar numbers]`.

- [ ] **Step 1: Write the failing test.** In `scripts/test_transcription_cleanup.py` add `bar_similarity` to the `from transcription_cleanup import …` line, add `import numpy as np` with the other imports, add this function above the `if __name__` block and call it last in that block:

```python
def test_silent_bars_are_not_scored():
    a = np.array([1.0, 0.0, 2.0])
    assert bar_similarity(a, a * 3) == 1.0
    assert bar_similarity(a, np.zeros(3)) is None      # the recording is silent there (video outro)
    assert bar_similarity(np.zeros(3), a) is None      # the score is silent there
    assert bar_similarity(np.array([np.nan] * 3), a) is None
    print("ok: a bar with silent audio on either side is skipped, not scored 0.0")
```

- [ ] **Step 2: Run it** — `ImportError: cannot import name 'bar_similarity'`.

- [ ] **Step 3: Implement.** Insert above `def cmd_verify(args):`:

```python
def bar_similarity(vr, va):
    """Cosine similarity of the rendered and recorded chroma of one bar; None when
    either side is silent (e.g. DTW parks the last bars on a video's silent outro)."""
    denom = float(np.linalg.norm(vr) * np.linalg.norm(va))
    if not np.isfinite(denom) or denom == 0:
        return None
    return round(float(vr @ va / denom), 6)
```

In `cmd_verify`: (a) directly below the line `    bars = []` add `    silent = []`. (b) Replace

```python
        denom = (np.linalg.norm(vr) * np.linalg.norm(va))
        sim = float(vr @ va / denom) if denom > 0 else 0.0
```

with

```python
        sim = bar_similarity(vr, va)
        if sim is None:
            silent.append(k + 1)
            continue
```

(c) In the `report = {` dict add, directly below the `"bars_compared": len(bars),` line: `        "silent_bars_skipped": silent,`.

- [ ] **Step 4: Run the test** — four lines starting `ok:`. Do NOT run the `verify` subcommand itself (another agent is rewriting the MuseScore wrapper it calls); the orchestrator runs it afterwards.

---

### Orchestrator Checks (after Wave 1)

1. All tests: `bash scripts/test_prepare_audio.sh && bash scripts/test_mscore_wrapper.sh && for t in normalize_tempo relabel_meter fill_rests bar_timing transcription_cleanup analyze_pedaling split_hands_midi quantized_midi simplify_score; do .venv/bin/python scripts/test_$t.py || break; done` → 3 + 4 + 4 + 3 + 4 + 4 + 4 + 11 + 2 + 3 + 4 = 46 lines starting `ok:`.
2. MuseScore-export round trip: export the Strangers `.mscz` to a temp `.musicxml`, run `normalize_tempo.py --tempo 92` then `relabel_meter.py --from 6/8 --to 3/4` on it (the reverse relabel must run without error and report `time_signatures_relabelled` ≥ 1), and convert the result to a temp `.mscz` → non-empty.
3. `verify` on Strangers into a temp `verify.json` → `silent_bars_skipped` contains 65 and the worst bar is no longer bar 65.
4. Commit per lane.

---

### Task F: Docs

**Files:** `CLAUDE.md`, `README.md`, `.claude/skills/midi-to-musicxml/SKILL.md`, `.claude/skills/cleanup-score/SKILL.md`. Read each file first; make exactly these changes and no others.

- [ ] **F1 — keep the raw DuET score.** In every code block that contains the line `mv 'output/<slug>/score.musicxml' 'output/<slug>/<slug>.musicxml'` (README writes it without quotes), replace that one line with two lines (keep the file's own quoting style):

```bash
mv 'output/<slug>/score.musicxml' 'output/<slug>/<slug>.duet.musicxml'   # raw DuET score — never edited
cp 'output/<slug>/<slug>.duet.musicxml' 'output/<slug>/<slug>.musicxml'
```

In `CLAUDE.md`'s output-layout tree add, directly above the `├── <slug>.musicxml` line:
`├── <slug>.duet.musicxml  # raw DuET engraving, untouched — the reference for bar_timing.py and for redoing a step  [original]`

- [ ] **F2 — bar timing step.** In `CLAUDE.md`'s pipeline code block, directly below the DuET block's `rm -rf "$(dirname "$D")"` line, add:

```bash

# 4a. Measure the recording against DuET's bars BEFORE trusting its meter/tempo:
#     steady or not, the real tempo, the real pickup, stray stretched bars.
#     Act on its recommendations (re-run DuET with grid_count_fix false, normalize
#     the tempo to the MEASURED value, relabel 3/4 -> 6/8).
.venv/bin/python scripts/bar_timing.py 'output/<slug>/<slug>.cleaned.mid' \
  'output/<slug>/score.npz' --score 'output/<slug>/<slug>.duet.musicxml'
```

Add the same command (without the comment block) to README's manual-stages block directly after the DuET lines, preceded by the comment `# Measure each bar's real duration: is DuET's meter/tempo right? (prints recommendations)`.

In `CLAUDE.md`'s Environment list add, directly above the `scripts/normalize_tempo.py` bullet:
``- `scripts/bar_timing.py <cleaned.mid> <score.npz> [--score <slug>.duet.musicxml>]` — measures how long each of DuET's bars really lasted in the performance and prints: `steady`, the measured tempo, the pickup's written vs played length, bars DuET stretched, and recommendations. Run after every DuET pass; it is how a wrong meter or an invented tempo change is caught.``

In `.claude/skills/midi-to-musicxml/SKILL.md`, at the very start of the section `## 2. (Optional) Normalize the tempo to the ground truth` (directly under the heading) add this paragraph and code block:

```
First measure the recording against DuET's bars — this, not the look of the score, decides the tempo and meter steps:

​```bash
.venv/bin/python scripts/bar_timing.py 'output/<slug>/<slug>.cleaned.mid' \
  'output/<slug>/score.npz' --score 'output/<slug>/<slug>.duet.musicxml'
​```

Follow its `recommendations`. When `steady` is true, normalize to the **measured** tempo (`measured_tempo_quarter_bpm`) — it is the cover's real tempo; the web value describes the original recording and is only a cross-check. When `pickup_mismatch` is true, compare the pickup bar with the first notes of the cleaned MIDI and fix or flag it.
```
(the code fence inside is a normal triple-backtick fence — the zero-width characters above are only so this plan renders; type plain backticks).

- [ ] **F3 — scripts accept MuseScore exports.** Remove every statement that `normalize_tempo.py` or `relabel_meter.py` only works on the raw DuET file or exits 1 on a MuseScore-regenerated file, in all four files. Specifically:
  - `CLAUDE.md` `normalize_tempo.py` bullet: replace the two sentences ``Run it right after DuET on the raw `<slug>.musicxml` — it exits 1 on a MuseScore-regenerated file. Targeted text edit (NOT a music21 round-trip).`` with ``Works on a raw DuET score and on a MuseScore export alike (so it can be re-applied after hand edits: export the `.mscz`, run it, convert back). NOT a music21 round-trip.``
  - `CLAUDE.md` `relabel_meter.py` bullet: replace ``Run after `normalize_tempo.py`, before MuseScore.`` with ``Run after `normalize_tempo.py`; works on a raw DuET score and on a MuseScore export alike.`` and change "relabels a raw DuET score" to "relabels a score".
  - `.claude/skills/midi-to-musicxml/SKILL.md`: in the sentence beginning `If the tempo disagrees with the ground truth, run the normalizer`, delete the clause `, on the raw DuET file, before metadata — it exits 1 on a MuseScore-regenerated file` so it ends `(right after DuET):`. In the paragraph beginning `It sets ONE constant quarter-note tempo`, replace `It is a targeted text edit (not a music21 round-trip), so the rest of the engraving is intact.` with `It edits only the tempo marks (not a music21 round-trip) and works on a MuseScore export too, so it can be re-applied after hand edits.`

- [ ] **F4 — MuseScore wrapper.** In `CLAUDE.md` replace the whole gotcha bullet beginning ``- `mscore` may print Qt warnings to stderr even on success`` with:
``- `scripts/mscore.sh` judges a conversion by the output file, not the exit code: MuseScore often aborts (exit 134) on shutdown after a good write, so the wrapper writes to a temporary file, retries up to 3 times, moves a non-empty result into place and exits 0; if nothing was written it exits non-zero and leaves any previous output untouched. Don't add your own retry loops. Qt warnings on stderr are noise.``
  In `.claude/skills/midi-to-musicxml/SKILL.md` replace the whole bullet beginning ``- `mscore` often prints Qt/plugin warnings`` with:
``- `scripts/mscore.sh` retries up to 3 times and judges by the output file (MuseScore's exit-134 shutdown crash after a good write counts as success). A non-zero exit from the wrapper is a real failure — look at MuseScore's log in `~/Library/Application Support/MuseScore/MuseScore4/logs/`.``

- [ ] **F5 — verify.** In `.claude/skills/cleanup-score/SKILL.md`, in the paragraph beginning `Interpret: `, append the sentence: `` `silent_bars_skipped` lists bars with no sound on one side (typically the last bar landing on a video's silent outro) — they are not scored, so ignore them unless a bar in the middle of the piece appears there.``

- [ ] **F6 — check.** Run `grep -rn "exits 1 on a MuseScore\|raw DuET file, before metadata\|retry once or twice" CLAUDE.md README.md .claude/skills` → no output. Run `grep -c "duet.musicxml" CLAUDE.md README.md .claude/skills/midi-to-musicxml/SKILL.md` → every count ≥ 2.
