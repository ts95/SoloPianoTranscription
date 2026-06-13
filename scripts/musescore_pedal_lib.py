#!/usr/bin/env python3
"""Shared library for MuseScore pedal modification scripts.

Provides utilities for parsing .mscz files, manipulating pedal Spanner elements,
and extracting per-measure note data for analysis.

Division = 480 ticks per quarter note, so whole note = 1920 ticks.
"""

import xml.etree.ElementTree as ET
from fractions import Fraction
import random
import string
import os
import zipfile
import shutil
import sys

# Duration type → ticks (Division=480, so quarter=480)
DURATION_TICKS = {
    'whole': 1920, 'half': 960, 'quarter': 480, 'eighth': 240,
    '16th': 120, '32nd': 60, '64th': 30, '128th': 15,
}

# Pitch class names (0=C, 1=C#, ... 11=B)
PC_NAMES = ['C', 'Db', 'D', 'Eb', 'E', 'F', 'F#', 'G', 'Ab', 'A', 'Bb', 'B']


# ---------------------------------------------------------------------------
# Tick / fraction conversion
# ---------------------------------------------------------------------------

def get_duration_ticks(elem):
    """Get duration in ticks for a Chord or Rest element."""
    dur_elem = elem.find('durationType')
    if dur_elem is None:
        return 0
    if dur_elem.text == 'measure':
        # Whole-measure rest: actual duration is in <duration> child (e.g. "4/4")
        dur_frac = elem.find('duration')
        return frac_to_ticks(dur_frac.text) if dur_frac is not None else 0
    ticks = DURATION_TICKS.get(dur_elem.text, 0)
    dots_elem = elem.find('dots')
    if dots_elem is not None:
        n_dots = int(dots_elem.text)
        dot_extra = sum(ticks // (2 ** i) for i in range(1, n_dots + 1))
        ticks += dot_extra
    # Check for explicit duration override (irregular-length rests in irregular measures)
    dur_frac = elem.find('duration')
    if dur_frac is not None:
        ticks = frac_to_ticks(dur_frac.text)
    # Check for explicit ticks override (tuplets etc.)
    actual = elem.find('ticks')
    if actual is not None:
        ticks = frac_to_ticks(actual.text)
    return ticks


def frac_to_ticks(frac_str):
    """Convert fraction string like '3/8' to ticks. 1/1 = 1920 ticks."""
    f = Fraction(frac_str)
    return int(f * 1920)


def ticks_to_frac(ticks):
    """Convert ticks to simplified fraction string."""
    f = Fraction(ticks, 1920)
    return f'{f.numerator}/{f.denominator}'


# ---------------------------------------------------------------------------
# Element helpers
# ---------------------------------------------------------------------------

def generate_eid():
    """Generate a random eid string."""
    chars = string.ascii_letters + string.digits + '+/'
    p1 = ''.join(random.choice(chars) for _ in range(20))
    p2 = ''.join(random.choice(chars) for _ in range(15))
    return f'{p1}_{p2}'


def is_duration_elem(elem):
    return elem.tag in ('Chord', 'Rest')


def is_pedal_spanner(elem):
    return elem.tag == 'Spanner' and elem.get('type') == 'Pedal'


# ---------------------------------------------------------------------------
# Pedal element construction
# ---------------------------------------------------------------------------

def make_pedal_start(span_frac):
    """Create a Pedal Spanner start element."""
    sp = ET.Element('Spanner', type='Pedal')
    ped = ET.SubElement(sp, 'Pedal')
    ET.SubElement(ped, 'endHookType').text = '1'
    ET.SubElement(ped, 'eid').text = generate_eid()
    seg = ET.SubElement(ped, 'Segment')
    ET.SubElement(seg, 'subtype').text = '0'
    ET.SubElement(seg, 'offset', x='0', y='0')
    ET.SubElement(seg, 'off2', x='0', y='0')
    ET.SubElement(seg, 'eid').text = generate_eid()
    nxt = ET.SubElement(sp, 'next')
    loc = ET.SubElement(nxt, 'location')
    ET.SubElement(loc, 'fractions').text = span_frac
    return sp


def make_pedal_end(span_frac):
    """Create a Pedal Spanner end element."""
    sp = ET.Element('Spanner', type='Pedal')
    prv = ET.SubElement(sp, 'prev')
    loc = ET.SubElement(prv, 'location')
    ET.SubElement(loc, 'fractions').text = f'-{span_frac}'
    return sp


def make_location(frac_str, time_tick=False):
    """Create a location element for tick position adjustment."""
    loc = ET.Element('location')
    ET.SubElement(loc, 'fractions').text = frac_str
    if time_tick:
        ET.SubElement(loc, 'timeTick').text = '1'
    return loc


# ---------------------------------------------------------------------------
# Voice processing
# ---------------------------------------------------------------------------

def remove_pedals_from_voice(voice):
    """Remove all Pedal Spanner elements and their associated location adjustments.
    Returns list of clean child elements."""
    children = list(voice)
    to_remove = set()

    for i, child in enumerate(children):
        if is_pedal_spanner(child):
            to_remove.add(i)
            if i > 0 and children[i - 1].tag == 'location':
                to_remove.add(i - 1)
            if i + 1 < len(children) and children[i + 1].tag == 'location':
                to_remove.add(i + 1)

    return [child for i, child in enumerate(children) if i not in to_remove]


def assign_ticks(elements):
    """Assign tick positions to each element. Returns [(tick, element), ...]."""
    result = []
    current_tick = 0
    for elem in elements:
        result.append((current_tick, elem))
        if elem.tag == 'location':
            frac = elem.find('fractions')
            if frac is not None:
                current_tick += frac_to_ticks(frac.text)
        elif is_duration_elem(elem):
            current_tick += get_duration_ticks(elem)
    return result


def process_measure(voice, measure_num, get_pedals_fn):
    """Remove old pedals and insert new ones in a single measure's voice.

    Args:
        voice: XML voice element
        measure_num: 1-indexed measure number
        get_pedals_fn: callable(measure_num) -> list of (start_tick, end_tick, span_frac_str)
    """
    # Step 1: Remove existing pedal elements
    clean = remove_pedals_from_voice(voice)

    # Step 2: Assign tick positions
    ticked = assign_ticks(clean)

    # Step 3: Get new pedal definitions
    pedals = get_pedals_fn(measure_num)
    if not pedals:
        return

    # Step 4: Collect pedal events by tick
    events_at = {}  # tick -> [(type, span_str)]
    for start_tick, end_tick, span_str in pedals:
        events_at.setdefault(start_tick, []).append(('start', span_str))
        events_at.setdefault(end_tick, []).append(('end', span_str))
    # Sort: ends before starts at same tick
    for tick in events_at:
        events_at[tick].sort(key=lambda x: 0 if x[0] == 'end' else 1)

    # Step 5: Find which ticks have duration elements
    elem_start_ticks = set()
    for tick, elem in ticked:
        if is_duration_elem(elem):
            elem_start_ticks.add(tick)

    # Step 6: Find first element index at each tick
    first_idx_at = {}
    for i, (tick, elem) in enumerate(ticked):
        if tick not in first_idx_at:
            first_idx_at[tick] = i

    def find_containing(target_tick):
        """Find (index, elem_tick, elem_end_tick) for the element containing target_tick."""
        for i, (tick, elem) in enumerate(ticked):
            if is_duration_elem(elem):
                dur = get_duration_ticks(elem)
                if tick <= target_tick < tick + dur:
                    return (i, tick, tick + dur)
        # If past all elements, return last element
        for i in range(len(ticked) - 1, -1, -1):
            tick, elem = ticked[i]
            if is_duration_elem(elem):
                dur = get_duration_ticks(elem)
                return (i, tick, tick + dur)
        return None

    # Build insertions
    insertions = []

    for event_tick, evts in events_at.items():
        pedal_elems = []
        for etype, span_str in evts:
            if etype == 'end':
                pedal_elems.append(make_pedal_end(span_str))
            else:
                pedal_elems.append(make_pedal_start(span_str))

        if event_tick in elem_start_ticks:
            idx = first_idx_at[event_tick]
            insertions.append((idx, pedal_elems, 'before', event_tick))
        else:
            containing = find_containing(event_tick)
            if containing is None:
                print(f"  WARNING: No containing element for tick {event_tick} in m{measure_num}")
                continue
            idx, _, elem_end = containing
            offset_back = event_tick - elem_end  # negative
            offset_fwd = elem_end - event_tick   # positive

            wrapped = [make_location(ticks_to_frac(offset_back), time_tick=True)]
            wrapped.extend(pedal_elems)
            wrapped.append(make_location(ticks_to_frac(offset_fwd)))
            insertions.append((idx, wrapped, 'after', event_tick))

    # Apply insertions in reverse order to preserve indices.
    # Secondary sort by -tick ensures that same-index insertions (which get
    # reversed by repeated list.insert) end up in chronological order.
    abs_insertions = []
    for idx, elems, pos, tick in insertions:
        if pos == 'before':
            abs_insertions.append((idx, elems, tick))
        else:
            abs_insertions.append((idx + 1, elems, tick))

    abs_insertions.sort(key=lambda x: (-x[0], -x[2]))

    result = [elem for _, elem in ticked]
    for idx, elems, _tick in abs_insertions:
        for elem in reversed(elems):
            result.insert(idx, elem)

    # Replace voice children
    for child in list(voice):
        voice.remove(child)
    for elem in result:
        voice.append(elem)


# ---------------------------------------------------------------------------
# XML formatting
# ---------------------------------------------------------------------------

def indent_xml(elem, level=0):
    """Add pretty-print indentation to XML tree."""
    indent = "\n" + "  " * level
    if len(elem):
        if not elem.text or not elem.text.strip():
            elem.text = indent + "  "
        if not elem.tail or not elem.tail.strip():
            elem.tail = indent
        for i, child in enumerate(elem):
            indent_xml(child, level + 1)
        if not child.tail or not child.tail.strip():
            child.tail = indent
    else:
        if level and (not elem.tail or not elem.tail.strip()):
            elem.tail = indent
        if not elem.text:
            elem.text = None


# ---------------------------------------------------------------------------
# Score-level Staff lookup (MS3/MS4 compatible)
# ---------------------------------------------------------------------------

def _find_score_staves(root):
    """Return the Staff elements under <Score> that contain actual measures.

    MS4 format: Part-definition staves have no 'id' attribute.
    MS3 format: Part-definition staves have 'id' but live under <Part>, not <Score>.

    In both formats, the staves with measure data are direct children of <Score>.
    """
    score = root.find('Score')
    if score is None:
        # Flat structure (shouldn't happen but fall back to root.iter)
        return [s for s in root.iter('Staff') if s.find('Measure') is not None]
    return [s for s in score if s.tag == 'Staff']


# ---------------------------------------------------------------------------
# .mscz extraction helpers
# ---------------------------------------------------------------------------

def find_mscx_in_dir(extract_dir):
    """Find the .mscx file inside an extracted .mscz directory."""
    for fname in os.listdir(extract_dir):
        if fname.endswith('.mscx'):
            return fname
    raise FileNotFoundError(f"No .mscx file found in {extract_dir}")


def extract_mscz(mscz_path, extract_dir):
    """Extract .mscz archive and return path to the .mscx file inside."""
    if os.path.exists(extract_dir):
        shutil.rmtree(extract_dir)
    os.makedirs(extract_dir)
    with zipfile.ZipFile(mscz_path, 'r') as zf:
        zf.extractall(extract_dir)
    mscx_filename = find_mscx_in_dir(extract_dir)
    return os.path.join(extract_dir, mscx_filename)


def repackage_mscz(mscz_path, extract_dir):
    """Repackage extracted directory back into .mscz archive."""
    files_to_zip = []
    for dirpath, dirnames, filenames in os.walk(extract_dir):
        for fname in filenames:
            full = os.path.join(dirpath, fname)
            rel = os.path.relpath(full, extract_dir)
            files_to_zip.append((full, rel))

    with zipfile.ZipFile(mscz_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for full, rel in files_to_zip:
            zf.write(full, rel)


# ---------------------------------------------------------------------------
# High-level pedal workflow
# ---------------------------------------------------------------------------

def add_pedals(mscz_path, get_pedals_fn, staff_id='2',
               extract_dir='/tmp/mscz_pedal_extract',
               post_process=None):
    """Full workflow: extract → backup → parse → add pedals → repackage.

    Args:
        mscz_path: path to .mscz file
        get_pedals_fn: callable(measure_num) -> list of (start_tick, end_tick, span_frac_str)
                       Return [] to skip a measure.
        staff_id: which staff to add pedals to (default '2')
        extract_dir: temp directory for extraction
        post_process: optional callable(root) for extra XML modifications
                      (e.g., changing dynamics). Called after pedals are inserted,
                      before indent/write.
    """
    # Extract
    print(f"Extracting {mscz_path}...")
    mscx_path = extract_mscz(mscz_path, extract_dir)

    # Backup
    bak_path = mscz_path + '.bak'
    if not os.path.exists(bak_path):
        shutil.copy2(mscz_path, bak_path)
        print(f"Backed up to {bak_path}")

    # Parse
    print(f"Reading {mscx_path}...")
    tree = ET.parse(mscx_path)
    root = tree.getroot()

    # Find target staff (Score-level staves only, works for both MS3 and MS4)
    target_staff = None
    for staff in _find_score_staves(root):
        if staff.get('id') == staff_id:
            target_staff = staff
            break

    if target_staff is None:
        print(f"ERROR: Staff {staff_id} not found!")
        sys.exit(1)

    measures = list(target_staff.findall('Measure'))
    print(f"Found {len(measures)} measures in Staff {staff_id}")

    # Process each measure
    for i, measure in enumerate(measures):
        mnum = i + 1
        voice = measure.find('voice')
        if voice is None:
            print(f"  m{mnum}: no voice element, skipping")
            continue

        pedals = get_pedals_fn(mnum)
        if not pedals:
            # Remove any existing pedals from skipped measures
            clean = remove_pedals_from_voice(voice)
            for child in list(voice):
                voice.remove(child)
            for elem in clean:
                voice.append(elem)
            print(f"  m{mnum}: skipped")
            continue

        process_measure(voice, mnum, get_pedals_fn)
        pedal_count = len(pedals)
        label = "SPLIT" if pedal_count > 1 else "single"
        print(f"  m{mnum}: {label}")

    # Post-processing hook
    if post_process is not None:
        post_process(root)

    # Indent and write
    indent_xml(root)
    print(f"\nWriting {mscx_path}...")
    tree.write(mscx_path, encoding='UTF-8', xml_declaration=True)

    # Repackage
    print(f"Repackaging {mscz_path}...")
    repackage_mscz(mscz_path, extract_dir)
    print("Done!")


def make_pedal_config(measure_ticks_fn, split_measures, skip_measures=None, gap=60):
    """Build a get_pedals_fn (legacy, non-syncopated).

    Pedal starts at the downbeat (tick 0). New pieces should use
    make_syncopated_pedal_config() instead, which engages the pedal
    just after the beat — the standard legato-pedal pattern.

    Args:
        measure_ticks_fn: callable(measure_num) -> ticks, OR int for constant.
                          Supports mid-piece time sig changes.
        split_measures: set of measure numbers to split at half-bar
        skip_measures: deprecated — kept for backward compat with older piece
                       scripts. Prefer not passing it (new pieces don't skip).
        gap: ticks gap before pedal end (default 60 = 1/32)

    Returns a callable(measure_num) -> pedal list.
    Single: (0, measure_ticks-gap, span_frac)
    Split: two pedals at half-measure, each with gap.
    """
    if isinstance(measure_ticks_fn, int):
        _const = measure_ticks_fn
        measure_ticks_fn = lambda m: _const
    skip_measures = skip_measures or set()

    def get_pedals(measure_num):
        if measure_num in skip_measures:
            return []
        mt = measure_ticks_fn(measure_num)
        if measure_num in split_measures:
            half = mt // 2
            span1 = half - gap
            span2 = half - gap
            return [
                (0, span1, ticks_to_frac(span1)),
                (half, half + span2, ticks_to_frac(span2)),
            ]
        else:
            span = mt - gap
            return [
                (0, span, ticks_to_frac(span)),
            ]
        return []

    return get_pedals


# Time signatures whose half-bar is a beat boundary. For 3/4 and 3/8 the
# mathematical midpoint lands mid-beat, so callers must supply split_points.
_HALF_BAR_OK = {'4/4', '2/4', '6/8'}


def _default_split_tick(time_sig, mt):
    """Return the natural split tick for a time signature, or None."""
    if time_sig in _HALF_BAR_OK:
        return mt // 2
    return None


def make_syncopated_pedal_config(measure_ticks_fn, split_measures=None,
                                  split_points=None, time_sig_fn=None, gap=60):
    """Build a syncopated get_pedals_fn (legato-pedal pattern).

    Each pedal starts `gap` ticks after its segment's downbeat and ends `gap`
    ticks before the next downbeat (or before the split point). Visually the
    pedal mark sits just after the bar line, producing the standard legato-
    pedal notation.

    Args:
        measure_ticks_fn: callable(mnum) -> ticks, OR int for constant.
        split_measures: set of mnums to split (default: empty).
        split_points: optional dict {mnum: tick} for custom split positions.
                      Required for measures in split_measures whose time
                      signature is 3/4 or 3/8 (no musical default exists).
        time_sig_fn: optional callable(mnum) -> time signature string
                     (e.g., '4/4'). Used to pick default split tick. If
                     omitted, defaults to mt//2 for all split measures.
        gap: ticks gap at each pedal boundary (default 60 = 1/32).

    Returns callable(mnum) -> pedal list.
    Single: [(gap, mt-gap, span)]
    Split:  [(gap, split-gap, span1), (split+gap, mt-gap, span2)]
    """
    if isinstance(measure_ticks_fn, int):
        _const_mt = measure_ticks_fn
        measure_ticks_fn = lambda m: _const_mt
    split_measures = split_measures or set()
    split_points = split_points or {}

    def get_pedals(mnum):
        mt = measure_ticks_fn(mnum)
        if mnum in split_measures:
            split = split_points.get(mnum)
            if split is None and time_sig_fn is not None:
                split = _default_split_tick(time_sig_fn(mnum), mt)
            if split is None:
                split = mt // 2
            span1 = (split - gap) - gap
            span2 = (mt - gap) - (split + gap)
            return [
                (gap, split - gap, ticks_to_frac(span1)),
                (split + gap, mt - gap, ticks_to_frac(span2)),
            ]
        span = mt - 2 * gap
        return [(gap, mt - gap, ticks_to_frac(span))]

    return get_pedals


# ---------------------------------------------------------------------------
# Note data extraction (for analysis)
# ---------------------------------------------------------------------------

def get_time_sig_ticks(sig_n, sig_d):
    """Compute ticks per measure from time signature numerator/denominator."""
    return sig_n * (1920 // sig_d)


def extract_measure_data(mscx_path, staff_ids=('1', '2')):
    """Extract structured per-measure note data from an .mscx file.

    Returns list of dicts:
    [
      {
        "number": 1, "time_sig": "4/4", "ticks": 1920,
        "staves": {
          "1": {"voices": {"1": [{"tick": 0, "dur": 480, "pitches": [60,64,67],
                                   "pcs": [0,4,7], "type": "Chord"}, ...]}},
          "2": {"voices": {"1": [...], "2": [...]}}
        }
      },
      ...
    ]
    """
    tree = ET.parse(mscx_path)
    root = tree.getroot()

    # First pass: determine number of measures and time signatures per measure
    # Use first matching staff as reference for measure count and time sigs
    # _find_score_staves returns only Score-level staves (works for MS3 and MS4)
    score_staves = _find_score_staves(root)
    ref_staff = None
    for staff in score_staves:
        if staff.get('id') in staff_ids:
            ref_staff = staff
            break

    if ref_staff is None:
        raise ValueError(f"No staff with id in {staff_ids} found")

    ref_measures = list(ref_staff.findall('Measure'))
    num_measures = len(ref_measures)

    # Track time signatures (from any staff, they're the same)
    current_sig_n, current_sig_d = 4, 4  # default 4/4
    measure_info = []

    for i, meas in enumerate(ref_measures):
        # Check for time sig change in this measure (could be in any voice)
        for voice in meas.findall('voice'):
            for elem in voice:
                if elem.tag == 'TimeSig':
                    sn = elem.find('sigN')
                    sd = elem.find('sigD')
                    if sn is not None and sd is not None:
                        current_sig_n = int(sn.text)
                        current_sig_d = int(sd.text)

        ticks = get_time_sig_ticks(current_sig_n, current_sig_d)
        measure_info.append({
            'number': i + 1,
            'time_sig': f'{current_sig_n}/{current_sig_d}',
            'ticks': ticks,
            'staves': {},
        })

    # Second pass: extract note data per staff per voice per measure
    for staff in score_staves:
        sid = staff.get('id')
        if sid not in staff_ids:
            continue

        staff_measures = list(staff.findall('Measure'))
        for i, meas in enumerate(staff_measures):
            if i >= num_measures:
                break

            voices_data = {}
            for voice_idx, voice in enumerate(meas.findall('voice'), start=1):
                voice_key = str(voice_idx)
                events = []
                current_tick = 0

                for elem in voice:
                    if elem.tag == 'Chord':
                        dur = get_duration_ticks(elem)
                        pitches = []
                        pcs = []
                        for note in elem.findall('Note'):
                            pitch_elem = note.find('pitch')
                            if pitch_elem is not None:
                                p = int(pitch_elem.text)
                                pitches.append(p)
                                pcs.append(p % 12)
                        # Check for articulations
                        artics = []
                        for art in elem.findall('Articulation'):
                            sub = art.find('subtype')
                            if sub is not None:
                                artics.append(sub.text)
                        event = {
                            'tick': current_tick,
                            'dur': dur,
                            'pitches': sorted(pitches),
                            'pcs': sorted(set(pcs)),
                            'type': 'Chord',
                        }
                        if artics:
                            event['articulations'] = artics
                        events.append(event)
                        current_tick += dur

                    elif elem.tag == 'Rest':
                        dur = get_duration_ticks(elem)
                        events.append({
                            'tick': current_tick,
                            'dur': dur,
                            'type': 'Rest',
                        })
                        current_tick += dur

                    elif elem.tag == 'location':
                        frac = elem.find('fractions')
                        if frac is not None:
                            current_tick += frac_to_ticks(frac.text)

                voices_data[voice_key] = events

            measure_info[i]['staves'][sid] = {'voices': voices_data}

    return measure_info
