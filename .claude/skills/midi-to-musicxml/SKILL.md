---
name: midi-to-musicxml
description: Convert a MIDI file to a readable engraved MusicXML score and a native MuseScore 4 file (.mscz) using DuET (never MuseScore's MIDI import). Use for stages 4–6 of the transcription pipeline, or whenever the user wants a .mid as editable sheet music.
---

# Convert MIDI to an engraved score (MusicXML + MuseScore .mscz) with DuET

Input: a path to a `.mid` file. In the pipeline this is the cleaned `output/<slug>/<slug>.cleaned.mid`. Deliverables: `output/<slug>/<slug>.musicxml` + `<slug>.mscz` + `<slug>.pdf` (the ONE score), plus DuET's auxiliary outputs (`score.mid`, `review.json`, `report.json`, `notes.json`, `score.npz`, `frames.csv`).

**Never feed a `.mid` to MuseScore.** Its import quantization auto-detects its own tempo (ignoring the tempo and time-signature meta events) and can lock onto a sub-pulse — wronging every barline and spraying fake tuplets. MIDI → MusicXML always goes through **DuET** (`scripts/duet.sh`); MuseScore is used **only** for the `.musicxml` → `.mscz`/`.pdf` format conversion.

**DuET** is a learned model (note + frame dual encoding) that maps the performance MIDI to cleanly engraved notation. It infers its own key signatures, note spelling, hand/staff assignment, bar structure, meters, runs→grace notes, and glissandi. It also writes block dynamics (a first draft the user refines by hand) and its own pedal marks (replaced by harmony pedaling in step 5). It sets only the title from the input filename (add the rest in step 3).

**Re-run safe:** before running, check whether `<slug>.musicxml` already exists and is non-empty — if so, skip (unless the user asked to redo it).

## 1. Run DuET

DuET's `-o` must point at a directory that **does not exist yet** — it creates that directory and refuses to overwrite an existing one (a pre-created `mktemp -d` dir fails with "File exists"). Point it at a fresh subdir under a mktemp base, then move the outputs in:

```bash
D=$(mktemp -d)/duet
scripts/duet.sh 'output/<slug>/<slug>.cleaned.mid' -o "$D" --device cpu
mv "$D"/* 'output/<slug>/'
mv 'output/<slug>/score.musicxml' 'output/<slug>/<slug>.musicxml'
rm -rf "$(dirname "$D")"
```

- `--device cpu` on a Mac (no CUDA). Takes a couple of minutes per piece — run it in the background and wait; slow is normal, don't assume it hung.
- Outputs: `score.musicxml` (the engraved score → renamed to `<slug>.musicxml`), `score.mid` (listening MIDI, separate upper/lower-staff tracks), `review.json` (spots the engraving was unsure about — feed these to CLEANUP_NOTES), `report.json` (model identity, input cleanup, engraving version), `notes.json` / `score.npz` / `frames.csv` (raw predictions).
- Engraving knobs (all on by default): `--no-auto-keys`, `--no-auto-spelling`, `--no-auto-runs`, `--no-auto-gliss`, and `--key-switch`/`--key-model-cost` for reproducible key decisions. Leave the defaults unless the user asks to change them.

## 2. (Optional) Normalize the tempo to the ground truth

DuET infers a tempo per section — visible metronome marks plus hidden `<sound tempo>` playback changes — and **has no override flag**. If the web ground-truth tempo is known and differs from what DuET engraved, force it. Check the engraved meter/tempo first:

```bash
grep -oE '<time><beats>[^<]*</beats><beat-type>[^<]*</beat-type>' 'output/<slug>/<slug>.musicxml' | sort | uniq -c
grep -oE '<per-minute>[0-9]+|<sound tempo="[0-9]+' 'output/<slug>/<slug>.musicxml'
```

If the tempo disagrees with the ground truth, run the normalizer (right after DuET, on the raw DuET file, before metadata — it exits 1 on a MuseScore-regenerated file):

```bash
.venv/bin/python scripts/normalize_tempo.py \
  'output/<slug>/<slug>.musicxml' 'output/<slug>/<slug>.musicxml' --tempo <bpm>
```

It sets ONE constant quarter-note tempo: the first metronome mark and first playback tempo are set, all others removed; *rit.* / *a tempo* text stays. It is a targeted text edit (not a music21 round-trip), so the rest of the engraving is intact. Skip this step when DuET's tempo already matches. **Meter has no override**: if the engraved meter disagrees with the ground truth, do not try to fix it — tell the user and record it for `CLEANUP_NOTES.md` (re-barring is done by hand in MuseScore).

## 3. Set the score metadata (rule)

Every delivered score must identify the piece in its header. DuET only wrote a filename-derived title, so set the real metadata:

```bash
.venv/bin/python scripts/set_score_metadata.py \
  'output/<slug>/<slug>.musicxml' 'output/<slug>/<slug>.musicxml' \
  --title '<piece>' --composer '<original composer/artist>' \
  [--arranger '<arranger>'] [--performer '<pianist>']
```

`--title` and `--composer` always (original composer for classical, original artist for pop/game covers); `--arranger` when the arrangement has a known author (cover channel / arranger credit from the video title or description); `--performer` when the pianist is known. Omit roles that don't apply. This edits only the `<work>`/`<identification>` header — the engraved content is left byte-for-byte intact.

## 4. Convert to .mscz + .pdf with MuseScore (format conversion only)

```bash
scripts/mscore.sh 'output/<slug>/<slug>.musicxml' -o 'output/<slug>/<slug>.mscz'
scripts/mscore.sh 'output/<slug>/<slug>.mscz' -o 'output/<slug>/<slug>.pdf'
```

- `mscore` often prints Qt/plugin warnings to stderr even on success. Judge by the exit code and the output file existing and being non-empty. It occasionally aborts with exit 134 (crash-reporter noise on shutdown) — retry once or twice.

## 5. Harmony pedaling

Pedal is added from the *engraved harmony*, not CC64. Run it on the `.mscz`, then regenerate `.musicxml` + `.pdf` from the pedaled `.mscz` so all three formats agree:

```bash
.venv/bin/python scripts/apply_harmony_pedal.py 'output/<slug>/<slug>.mscz'
scripts/mscore.sh 'output/<slug>/<slug>.mscz' -o 'output/<slug>/<slug>.musicxml'
scripts/mscore.sh 'output/<slug>/<slug>.mscz' -o 'output/<slug>/<slug>.pdf'
```

## 6. Visual inspection (rule)

Read the generated PDF (the Read tool renders PDF pages directly; sample at least the first page, a busy middle page, and the final page). Look for what a text check cannot see: marks floating mid-system or doubled, pedal lines not under the bass staff, colliding elements, multi-voice clutter, drone durations that halt the texture, fragmented beaming. Fix what is decidable (then re-export `.mscz` and `.pdf` and re-inspect); flag the rest to the user.

Report the output paths (musicxml, mscz, pdf) and suggest running `/cleanup-score` for the full treatment (artifact removal, ground-truth key/meter cross-check, verify-by-ear report).

## Fallback: no MuseScore

If `mscore` fails or is unavailable, deliver the `.musicxml` alone (DuET doesn't need MuseScore) and say the `.mscz` could not be produced.
