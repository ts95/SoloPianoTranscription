#!/usr/bin/env python3
"""Normalize a DuET score's meter and tempo.

DuET infers the meter and per-section tempo from the model. For a piece whose
true meter/tempo is known (from the web ground-truth), this rewrites the score
to a single constant meter and a single constant tempo, and trims any bar that
is overfull for the target meter (removing the trailing extra beats).

It is a targeted text edit of the raw MusicXML (NOT a music21 round-trip), so
the engraved content — grace notes, glissandi, spelling, voices — is left
byte-for-byte intact except for the specific metronome / time-signature /
trimmed-note changes.

Usage:
  normalize_meter_tempo.py <in.musicxml> <out.musicxml> \
      --tempo 93 --meter 3/4

Notes:
  - --tempo sets ONE metronome mark (quarter note = N BPM) at the first
    measure and removes every other metronome mark.
  - --meter B/T rewrites every <time> to B/T and trims any measure whose
    per-voice content exceeds B beats, dropping the trailing beats. Positioning
    uses the <duration> ticks (not the <type>), and a note's <duration> is kept
    consistent with its <type> when it is truncated. Chord notes (which share
    their base note's duration) are handled as one event with their base.
"""
import argparse
import json
import re
import sys

# duration in beats -> (note type, number of dots)
DUR_NOTATION = {
    0.25: ('16th', 0), 0.5: ('eighth', 0), 0.75: ('16th', 1),
    1.0: ('quarter', 0), 1.5: ('quarter', 1), 2.0: ('half', 0),
    3.0: ('half', 1), 4.0: ('whole', 0),
}
EPS = 1e-6


def voice_of(body: str) -> int:
    vn = re.search(r'<voice>(\d+)</voice>', body)
    return int(vn.group(1)) if vn else 1


def label_of(body: str) -> str:
    """A short human label for a note/rest body (its pitch letter, or 'rest')."""
    if '<rest' in body:
        return 'rest'
    sm = re.search(r'<step>(\w)</step>', body)
    return sm.group(1) if sm else '?'


def set_duration_ticks(body: str, ticks: int, div: int):
    """Rewrite a note/rest body's <duration>, <type> and <dot/> for `ticks`."""
    beats = ticks / div
    if round(beats, 6) not in DUR_NOTATION:
        return None  # not representable on the quarter-note grid
    ntype, ndots = DUR_NOTATION[round(beats, 6)]
    body = re.sub(r'<duration>\d+</duration>', f'<duration>{ticks}</duration>', body)
    body = re.sub(r'<type>\w+</type>', f'<type>{ntype}</type>', body)
    body = re.sub(r'(<dot/>\s*)+', '', body)
    body = re.sub(r'(<type>' + ntype + r'</type>)',
                  r'\1' + '<dot/>' * ndots, body, count=1)
    return body


def measure_ticks(mxml: str):
    """Per-voice total ticks (grace + chord notes excluded)."""
    voices = {}
    for nm in re.finditer(r'<note>(.*?)</note>', mxml, flags=re.S):
        body = nm.group(1)
        if '<grace' in body or '<appella' in body or '<chord/>' in body:
            continue
        dm = re.search(r'<duration>(\d+)</duration>', body)
        if not dm:
            continue
        v = voice_of(body)
        voices[v] = voices.get(v, 0) + int(dm.group(1))
    return voices


def trim_measure(mxml: str, target_ticks: int, div: int):
    """Bring a measure down to `target_ticks` per voice.

    Notes that start at/after the cut are deleted (with their chord partners);
    a note that starts before the cut but extends past it is truncated to end
    exactly at the cut (<duration>/<type>/<dot> kept consistent, chords included).
    Returns (new_measure_xml, changed_descs)."""
    notes = []
    pos = {}
    for nm in re.finditer(r'<note>(.*?)</note>', mxml, flags=re.S):
        body = nm.group(1)
        grace = '<grace' in body or '<appella' in body
        chord = '<chord/>' in body
        dm = re.search(r'<duration>(\d+)</duration>', body)
        dur = int(dm.group(1)) if dm else 0
        v = voice_of(body)
        p = pos.get(v, 0)
        notes.append({'s': nm.start(), 'e': nm.end(), 'voice': v, 'body': body,
                      'chord': chord, 'grace': grace, 'dur': dur, 'start': p})
        if not chord and not grace:
            pos[v] = p + dur

    # group into events: a primary note + its following chord notes
    events = []
    for n in notes:
        if n['grace']:
            continue
        if n['chord']:
            if events:
                events[-1].append(n)
        else:
            events.append([n])

    edits = []   # (span_s, span_e, replacement)
    changed = []
    for ev in events:
        primary = ev[0]
        start = primary['start']
        end = start + primary['dur']
        if start >= target_ticks - EPS:
            s = min(n['s'] for n in ev)
            e = max(n['e'] for n in ev)
            edits.append((s, e, ''))
            changed.append(f"V{primary['voice']} beat {start/div:.2f} removed {label_of(primary['body'])}")
        elif end > target_ticks + EPS:
            new_dur = target_ticks - start
            ok = True
            for n in ev:
                new_body = set_duration_ticks(n['body'], new_dur, div)
                if new_body is None:
                    ok = False
                    break
                # replace only the body: after '<note>' (6 chars) to before '</note>' (7)
                edits.append((n['s'] + 6, n['e'] - 7, new_body))
            if ok:
                changed.append(f"V{primary['voice']} beat {start/div:.2f} truncated {label_of(primary['body'])} "
                               f"{primary['dur']/div:.2f}->{new_dur/div:.2f}")
            else:
                changed.append(f"V{primary['voice']} beat {start/div:.2f} UNTRUNCATABLE "
                               f"(needs {new_dur/div:.3f} beats) — left as-is")

    new_xml = mxml
    for s, e, repl in sorted(edits, key=lambda x: x[0], reverse=True):
        new_xml = new_xml[:s] + repl + new_xml[e:]
    return new_xml, changed


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('input')
    ap.add_argument('output')
    ap.add_argument('--tempo', type=float, help='constant quarter-note BPM for the whole piece')
    ap.add_argument('--meter', help='target meter B/T, e.g. 3/4 (all bars forced to this)')
    args = ap.parse_args()

    with open(args.input, encoding='utf-8') as f:
        xml = f.read()

    div_m = re.search(r'<divisions>(\d+)</divisions>', xml)
    div = int(div_m.group(1)) if div_m else 24

    report = {'input': args.input, 'output': args.output, 'divisions': div}

    # ---- tempo: one constant metronome at the first measure ----------------
    if args.tempo is not None:
        bpm = int(round(args.tempo))
        marks = list(re.finditer(r'<metronome>.*?</metronome>', xml, flags=re.S))
        tempo_report = {'bpm': bpm, 'marks_found': len(marks),
                        'marks_removed': max(0, len(marks) - 1)}
        if marks:
            first = marks[0]
            new_mark = (f'<metronome><beat-unit>quarter</beat-unit>'
                        f'<per-minute>{bpm}</per-minute></metronome>')
            xml = xml[:first.start()] + new_mark + xml[first.end():]
            for m in reversed(marks[1:]):
                xml = xml[:m.start()] + xml[m.end():]
        else:
            tempo_report['note'] = 'no metronome found; nothing to set'  # type: ignore[dict-item]
        report['tempo'] = tempo_report

    # ---- meter: force B/T and trim overfull bars ---------------------------
    if args.meter:
        beats, beattype = (int(x) for x in args.meter.split('/'))
        xml, n_ts = re.subn(r'<time><beats>\d+</beats><beat-type>\d+</beat-type>',
                            f'<time><beats>{beats}</beats><beat-type>{beattype}</beat-type>', xml)
        report['meter'] = {'target': args.meter, 'time_sigs_rewritten': n_ts,
                           'trimmed_measures': []}
        # div is ticks per QUARTER; scale to the target beat unit (4 = quarter)
        target_ticks = int(round(beats * div * (4 / beattype)))
        parts = re.split(r'(?=<measure number=)', xml)
        for i, part in enumerate(parts):
            mb = measure_ticks(part)
            if not mb or all(t <= target_ticks + EPS for t in mb.values()):
                continue
            new_part, changed = trim_measure(part, target_ticks, div)
            mnum = re.match(r'<measure number="(\d+)"', part)
            report['meter']['trimmed_measures'].append(
                {'measure': mnum.group(1) if mnum else '?', 'changed': changed})
            parts[i] = new_part
        xml = ''.join(parts)

    with open(args.output, 'w', encoding='utf-8') as f:
        f.write(xml)

    print(json.dumps(report, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
