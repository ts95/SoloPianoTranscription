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
