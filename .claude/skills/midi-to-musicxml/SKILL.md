---
name: midi-to-musicxml
description: Convert a MIDI file to MusicXML and a native MuseScore 4 file (.mscz) using the MuseScore 4 CLI. Use for stage 3 of the transcription pipeline, or whenever the user wants a .mid as editable sheet music.
---

# Convert MIDI to MusicXML and MuseScore (.mscz) with MuseScore 4

Input: a path to a `.mid` file. Pipeline convention: `output/<slug>/<slug>.mid` → `output/<slug>/<slug>.musicxml` + `output/<slug>/<slug>.mscz`.

By default export **both** formats — `.mscz` for editing directly in MuseScore 4, `.musicxml` for interchange with other notation software. If the user asked for only one, export just that one.

```bash
MSCORE="/Applications/MuseScore 4.app/Contents/MacOS/mscore"
"$MSCORE" '<input>.mid' -o '<output>.musicxml'
"$MSCORE" '<input>.mid' -o '<output>.mscz'
```

- The output format is inferred from the `-o` extension, so the same command shape works for both.
- MuseScore quantizes the performance-timing MIDI on import — that's why it's preferred over a plain programmatic conversion.
- `mscore` often prints Qt/plugin warnings to stderr even when it succeeds. Judge success by the exit code and by the output file existing and being non-empty.
- Use `.musicxml` (uncompressed) rather than `.mxl` so the result is diffable and inspectable.

Report both output paths and suggest opening the `.mscz` in MuseScore 4 for cleanup (beaming, voicing, key/time signature, tempo are best-guess on transcribed MIDI).

## Fallback: music21

If `mscore` fails (e.g., MuseScore not installed or a crash on a malformed MIDI), convert with music21 instead — quality is worse on unquantized MIDI, so say so:

```bash
.venv/bin/pip install music21   # if not already installed
.venv/bin/python -c "
from music21 import converter
s = converter.parse('<input>.mid')
s.write('musicxml', fp='<output>.musicxml')
"
```
