#!/usr/bin/env python3
"""Analyze a MuseScore file and recommend pedal placement per measure.

Usage:
    python3 analyze_pedaling.py <file.mscz> [--staff 2] [--json] [--dump]

Inspects the grand staff and reports per-measure:
- Harmony changes (bass pitch class at beat 1 vs half-bar) → split recommendation
- Density (unique pitch classes, note count) → review flag
- Sustained bass (low notes held half note+) → informational flag only
- Articulation conflicts (staccato) → review flag
- Grand-staff rests (both staves empty) → informational flag only
- Time signature tracking → dynamic ticks per measure

Recommendations are always `single`, `split`, or `review` — the workflow no
longer emits `skip`; silent/sustained bars still get a single pedal.
"""

import argparse
import json
import os
import sys
import shutil

from musescore_pedal_lib import (
    extract_mscz, extract_measure_data, find_mscx_in_dir,
    PC_NAMES, get_time_sig_ticks, _HALF_BAR_OK,
)


def analyze_measure(mdata):
    """Analyze a single measure's data and return recommendation dict.

    Returns dict with keys:
        number, time_sig, ticks, bass_start_pc, bass_mid_pc,
        unique_pcs, note_count, flags, recommendation
    """
    mnum = mdata['number']
    time_sig = mdata['time_sig']
    ticks = mdata['ticks']
    half_tick = ticks // 2

    result = {
        'number': mnum,
        'time_sig': time_sig,
        'ticks': ticks,
        'split_tick': None,
        'bass_start_pc': None,
        'bass_mid_pc': None,
        'unique_pcs': 0,
        'note_count': 0,
        'flags': [],
        'recommendation': 'single',
    }

    # Collect all chord events across both staves
    all_chords = []  # (staff_id, voice_key, event)
    has_chords_staff = {}  # staff_id -> bool

    for sid, sdata in mdata.get('staves', {}).items():
        staff_has_chords = False
        for vkey, events in sdata.get('voices', {}).items():
            for ev in events:
                if ev['type'] == 'Chord':
                    all_chords.append((sid, vkey, ev))
                    staff_has_chords = True
        has_chords_staff[sid] = staff_has_chords

    # --- D. Rest detection (grand staff) ---
    # Skip only if BOTH staves have no chords
    staff_ids = list(mdata.get('staves', {}).keys())
    if len(staff_ids) >= 2:
        both_rest = all(not has_chords_staff.get(s, False) for s in staff_ids)
    elif len(staff_ids) == 1:
        both_rest = not has_chords_staff.get(staff_ids[0], False)
    else:
        both_rest = True

    if both_rest:
        result['flags'].append('all-rest')
        return result

    # --- Unique pitch classes and note count ---
    all_pcs = set()
    note_count = 0
    for sid, vkey, ev in all_chords:
        all_pcs.update(ev.get('pcs', []))
        note_count += len(ev.get('pitches', []))

    result['unique_pcs'] = len(all_pcs)
    result['note_count'] = note_count

    # --- A. Harmony change detection ---
    # Find bass voice: prefer Voice 2 of Staff 2, then Voice 1 of Staff 2, then Staff 1
    bass_events = _find_bass_events(mdata)

    if bass_events:
        # Find pitch class at tick 0 (or first chord)
        start_pc = None
        mid_pc = None

        for ev in bass_events:
            if ev['type'] != 'Chord':
                continue
            tick = ev['tick']
            lowest_pc = min(ev['pcs']) if ev['pcs'] else None

            if tick == 0 or (start_pc is None and tick < half_tick):
                start_pc = lowest_pc
            if tick >= half_tick and mid_pc is None:
                mid_pc = lowest_pc
            # Also check if a chord spans into the half-tick region
            if tick < half_tick and tick + ev['dur'] > half_tick and mid_pc is None:
                # Same chord still sounding at half-bar → same pc
                mid_pc = lowest_pc

        result['bass_start_pc'] = start_pc
        result['bass_mid_pc'] = mid_pc

        if start_pc is not None and mid_pc is not None and start_pc != mid_pc:
            result['flags'].append('harm_change')
            # 3/4 and 3/8 have no natural half-bar split — keep single by
            # default and let the user opt into a split via REVIEW.
            if time_sig in _HALF_BAR_OK:
                result['recommendation'] = 'split'
                result['split_tick'] = half_tick
            else:
                result['flags'].append('prefer_single_3beat')

        # --- Sustained bass detection (informational flag) ---
        # Very low bass notes (below C3) held for half note or longer already
        # sustain acoustically. Flag for user awareness but don't override the
        # recommendation.
        for ev in bass_events:
            if ev['type'] != 'Chord':
                continue
            if ev['dur'] >= 960 and min(ev['pitches']) < 48:
                result['flags'].append('sustained_bass')
                break

    # --- E. Irregular meter flag ---
    sig_parts = time_sig.split('/')
    sig_n = int(sig_parts[0])
    if sig_n in (5, 7, 11, 13):
        result['flags'].append('irregular_meter')

    # --- B. Density analysis ---
    if len(all_pcs) > 8:
        result['flags'].append('dense')
        if result['recommendation'] == 'single':
            result['recommendation'] = 'review'

    # Check for fast passages (16th notes or faster taking > half the measure)
    fast_ticks = 0
    for sid, vkey, ev in all_chords:
        if ev['dur'] <= 120:  # 16th or faster
            fast_ticks += ev['dur']
    if fast_ticks > ticks // 2:
        result['flags'].append('fast_passage')
        if result['recommendation'] == 'single':
            result['recommendation'] = 'review'

    # --- C. Articulation conflicts ---
    staccato_count = 0
    chord_count = len(all_chords)
    for sid, vkey, ev in all_chords:
        for art in ev.get('articulations', []):
            if 'staccato' in art.lower() or 'marcato' in art.lower():
                staccato_count += 1
                break
    if chord_count > 0 and staccato_count > chord_count // 2:
        result['flags'].append('staccato')
        if result['recommendation'] == 'single':
            result['recommendation'] = 'review'

    # --- Check for half-rest start in both staves ---
    if len(staff_ids) >= 2:
        both_start_rest = True
        for sid in staff_ids:
            sdata = mdata['staves'].get(sid, {})
            staff_starts_rest = True
            for vkey, events in sdata.get('voices', {}).items():
                if events and events[0]['type'] == 'Chord':
                    staff_starts_rest = False
                    break
                if events and events[0]['type'] == 'Rest' and events[0]['dur'] < half_tick:
                    staff_starts_rest = False
                    break
            if not staff_starts_rest:
                both_start_rest = False
                break
        if both_start_rest and not both_rest:
            result['flags'].append('late_entry')

    return result


def _find_bass_events(mdata):
    """Find the bass voice events for harmony analysis.

    Priority: Voice 2 of Staff 2 > Voice 1 of Staff 2 > lowest voice of Staff 1.
    """
    staves = mdata.get('staves', {})

    # Try Staff 2
    if '2' in staves:
        voices = staves['2'].get('voices', {})
        # Prefer voice 2 (bass voice)
        if '2' in voices and _has_chords(voices['2']):
            return voices['2']
        if '1' in voices and _has_chords(voices['1']):
            return voices['1']

    # Fall back to Staff 1 lowest voice
    if '1' in staves:
        voices = staves['1'].get('voices', {})
        # Try highest numbered voice (typically lowest pitch)
        for vkey in sorted(voices.keys(), reverse=True):
            if _has_chords(voices[vkey]):
                return voices[vkey]

    return []


def _has_chords(events):
    """Check if event list contains any Chord events."""
    return any(ev['type'] == 'Chord' for ev in events)


def format_pc(pc):
    """Format pitch class as note name, or '—' if None."""
    if pc is None:
        return '—'
    return PC_NAMES[pc % 12]


def print_table(results):
    """Print human-readable analysis table."""
    print(f"{'m':>3} | {'sig':>5} | {'bass_start':>10} | {'bass_mid':>8} | "
          f"{'uniq_pc':>7} | {'notes':>5} | {'flags':<20} | {'rec':<8}")
    print('-' * 85)

    for r in results:
        flags_str = ','.join(r['flags']) if r['flags'] else ''
        print(f"{r['number']:>3} | {r['time_sig']:>5} | "
              f"{format_pc(r['bass_start_pc']):>10} | {format_pc(r['bass_mid_pc']):>8} | "
              f"{r['unique_pcs']:>7} | {r['note_count']:>5} | "
              f"{flags_str:<20} | {r['recommendation']:<8}")


def print_summary(results):
    """Print copy-pasteable Python sets."""
    split = sorted(r['number'] for r in results if r['recommendation'] == 'split')
    review = sorted(r['number'] for r in results if r['recommendation'] == 'review')

    print(f"\nSPLIT_MEASURES = {{{', '.join(map(str, split))}}}")
    print(f"REVIEW_MEASURES = {{{', '.join(map(str, review))}}}  # dense or flagged — human should decide")
    print(f"\nTotal measures: {len(results)}")
    print(f"  single: {sum(1 for r in results if r['recommendation'] == 'single')}")
    print(f"  split:  {len(split)}")
    print(f"  review: {len(review)}")


def main():
    parser = argparse.ArgumentParser(description='Analyze pedal placement for a MuseScore file')
    parser.add_argument('mscz', help='Path to .mscz file')
    parser.add_argument('--staff', default='2', help='Staff ID to add pedals to (default: 2)')
    parser.add_argument('--json', action='store_true', help='Output as JSON')
    parser.add_argument('--dump', action='store_true',
                        help='Dump full per-measure note data as JSON (for programmatic use)')
    args = parser.parse_args()

    if not os.path.exists(args.mscz):
        print(f"ERROR: File not found: {args.mscz}", file=sys.stderr)
        sys.exit(1)

    # Extract
    extract_dir = '/tmp/mscz_analyze_extract'
    mscx_path = extract_mscz(args.mscz, extract_dir)

    # Determine staff IDs to analyze (always include both staves for grand staff analysis)
    staff_ids = ('1', '2')

    # Extract measure data
    measure_data = extract_measure_data(mscx_path, staff_ids=staff_ids)

    if args.dump:
        # Output full note data as JSON
        print(json.dumps(measure_data, indent=2))
        return

    # Analyze each measure
    results = [analyze_measure(m) for m in measure_data]

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        print(f"\nAnalysis of: {os.path.basename(args.mscz)}")
        print(f"Staves analyzed: {', '.join(staff_ids)}\n")
        print_table(results)
        print_summary(results)


if __name__ == '__main__':
    main()
