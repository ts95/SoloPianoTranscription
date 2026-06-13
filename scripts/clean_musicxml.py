#!/usr/bin/env python3
"""MusicXML cleaner.

Originally written for Audiveris OMR output; adapted for this project, whose
MusicXML comes from the quantize/post pipeline (not OCR). Use `--source generated`
(the default) for our pipeline output — it applies the source-agnostic cleanups
(duplicate/contradictory dynamics, unpaired pedals, non-piano articulations) and
skips the OCR-only rules that would damage a clean score (stripping a short title,
removing intentional ornaments, deleting real subito dynamics as "outliers").
Use `--source omr` for raw Audiveris output to get the full original cleanup.

Usage:
    python3 clean_musicxml.py input.xml [-o out.musicxml] [--source generated|omr] [-v]
"""

import argparse
import os
import sys
import xml.etree.ElementTree as ET


# Dynamic priority (higher = louder)
DYNAMIC_PRIORITY = {
    'ppp': 1, 'pp': 2, 'p': 3, 'mp': 4, 'mf': 5, 'f': 6, 'ff': 7, 'fff': 8,
    'sfz': 9, 'sfp': 5, 'fp': 5, 'sf': 7, 'fz': 7,
}

# String/guitar articulations impossible on piano
NON_PIANO_ARTICULATIONS = {'up-bow', 'down-bow', 'snap-pizzicato', 'harmonic'}


def _get_dynamic_type(dynamics_elem):
    """Extract the dynamic marking name from a <dynamics> element."""
    for child in dynamics_elem:
        if child.tag in DYNAMIC_PRIORITY:
            return child.tag
    return None


def _cleanup_empty_containers(note, notations, container):
    """Remove empty articulations/ornaments → notations → note chain."""
    if container is not None and len(container) == 0:
        notations.remove(container)
    if len(notations) == 0:
        note.remove(notations)


# ── Rule 8: Credit text garbage ──────────────────────────────────────────

def clean_credit_garbage(root, log):
    """Remove <credit> elements with short garbage text (OCR fragments)."""
    removed = 0
    to_remove = []
    for credit in root.findall('credit'):
        # Keep credits that have an explicit type (composer, etc.)
        if credit.find('credit-type') is not None:
            continue
        words = credit.find('credit-words')
        if words is not None and words.text:
            text = words.text.strip()
            if len(text) <= 3 or text.isdigit():
                to_remove.append((credit, text))
    for credit, text in to_remove:
        root.remove(credit)
        log.append(f'Removed credit garbage: "{text}"')
        removed += 1
    return removed


# ── Rule 9: Metadata cleanup ────────────────────────────────────────────

def clean_metadata(root, log):
    """Remove garbage metadata values (e.g., lyricist "%")."""
    removed = 0
    identification = root.find('identification')
    if identification is not None:
        for creator in identification.findall('creator'):
            if creator.get('type') == 'lyricist':
                text = (creator.text or '').strip()
                if len(text) <= 1:
                    identification.remove(creator)
                    log.append(f'Removed garbage lyricist: "{text}"')
                    removed += 1
    # Also clean credit-type=lyricist with garbage text
    for credit in root.findall('credit'):
        ctype = credit.find('credit-type')
        if ctype is not None and ctype.text == 'lyricist':
            words = credit.find('credit-words')
            if words is not None and len((words.text or '').strip()) <= 1:
                root.remove(credit)
                log.append(f'Removed garbage lyricist credit: "{(words.text or "").strip()}"')
                removed += 1
    return removed


# ── Rule 1: Orphan volta brackets ───────────────────────────────────────

def clean_orphan_voltas(measures, log):
    """Remove <ending> elements in measures not within ±2 of any repeat barline."""
    repeat_indices = set()
    for i, m in enumerate(measures):
        for barline in m.findall('barline'):
            if barline.find('repeat') is not None:
                repeat_indices.add(i)

    removed = 0
    for i, m in enumerate(measures):
        near_repeat = any(j in repeat_indices
                          for j in range(max(0, i - 2), min(len(measures), i + 3)))
        if near_repeat:
            continue
        for barline in m.findall('barline'):
            for ending in barline.findall('ending'):
                barline.remove(ending)
                text = ending.text or ''
                log.append(f'Removed orphan volta in m.{m.get("number", "?")}'
                           + (f' ("{text}")' if text else ''))
                removed += 1
    return removed


# ── Rule 2: Volta on forward repeat ─────────────────────────────────────

def clean_volta_on_forward_repeat(measures, log):
    """Remove <ending> from barlines that also contain <repeat direction="forward">."""
    removed = 0
    for m in measures:
        for barline in m.findall('barline'):
            repeat = barline.find('repeat')
            if repeat is not None and repeat.get('direction') == 'forward':
                for ending in barline.findall('ending'):
                    barline.remove(ending)
                    text = ending.text or ''
                    log.append(f'Removed volta on forward repeat in m.{m.get("number", "?")}'
                               + (f' ("{text}")' if text else ''))
                    removed += 1
    return removed


# ── Rule 3: Unpaired pedals ─────────────────────────────────────────────

def clean_unpaired_pedals(measures, log):
    """Remove pedal-start directions that have no matching stop."""
    # Collect all pedal directions in score order
    pedal_dirs = []  # (measure_elem, direction_elem, pedal_type)
    for m in measures:
        for direction in m.findall('direction'):
            for dtype in direction.findall('direction-type'):
                pedal = dtype.find('pedal')
                if pedal is not None:
                    pedal_dirs.append((m, direction, pedal.get('type', '')))

    # Walk through tracking state, mark unpaired starts for removal
    to_remove = []
    pedal_on = False
    last_start = None  # (measure, direction)

    for m, direction, ptype in pedal_dirs:
        if ptype == 'start':
            if pedal_on and last_start is not None:
                to_remove.append(last_start)
            pedal_on = True
            last_start = (m, direction)
        elif ptype in ('stop', 'discontinue'):
            pedal_on = False
            last_start = None
        elif ptype == 'change':
            if not pedal_on:
                to_remove.append((m, direction))

    if pedal_on and last_start is not None:
        to_remove.append(last_start)

    removed = 0
    for m, direction in to_remove:
        m.remove(direction)
        log.append(f'Removed unpaired pedal in m.{m.get("number", "?")}')
        removed += 1
    return removed


# ── Rule 4: Non-piano articulations ─────────────────────────────────────

def clean_non_piano_articulations(measures, log):
    """Remove string/guitar articulations impossible on piano."""
    removed = 0
    for m in measures:
        for note in m.iter('note'):
            notations = note.find('notations')
            if notations is None:
                continue
            articulations = notations.find('articulations')
            if articulations is None:
                continue
            for art_name in NON_PIANO_ARTICULATIONS:
                for elem in articulations.findall(art_name):
                    articulations.remove(elem)
                    log.append(f'Removed {art_name} in m.{m.get("number", "?")}')
                    removed += 1
            _cleanup_empty_containers(note, notations, articulations)
    return removed


# ── Rule 5: Duplicate articulations ─────────────────────────────────────

def clean_duplicate_articulations(measures, log):
    """Remove staccatissimo when staccato also present on same note."""
    removed = 0
    for m in measures:
        for note in m.iter('note'):
            notations = note.find('notations')
            if notations is None:
                continue
            articulations = notations.find('articulations')
            if articulations is None:
                continue
            if articulations.find('staccato') is not None:
                for elem in articulations.findall('staccatissimo'):
                    articulations.remove(elem)
                    log.append(f'Removed duplicate staccatissimo in m.{m.get("number", "?")}')
                    removed += 1
                _cleanup_empty_containers(note, notations, articulations)
    return removed


# ── Rule 6: Suspicious ornaments ────────────────────────────────────────

# Ornament types that Audiveris frequently hallucinates from visual noise
SUSPECT_ORNAMENTS = {'inverted-mordent', 'turn', 'delayed-turn', 'inverted-turn',
                     'mordent', 'trill-mark'}


def clean_suspicious_ornaments(measures, log, remove_all=False):
    """Remove suspect ornament types from notes.

    Args:
        remove_all: If True (piano), remove ALL suspect ornaments unconditionally.
            Audiveris almost never detects these correctly on piano scores.
            If False, only remove when co-located with other OCR artifacts.
    """
    artifact_tags = NON_PIANO_ARTICULATIONS | {'staccatissimo'}
    removed = 0
    warnings = []

    for m in measures:
        for note in m.iter('note'):
            notations = note.find('notations')
            if notations is None:
                continue
            ornaments = notations.find('ornaments')
            if ornaments is None:
                continue
            ornament_elems = [o for o in ornaments if o.tag in SUSPECT_ORNAMENTS]
            if not ornament_elems:
                continue

            num = m.get('number', '?')

            if remove_all:
                for elem in ornament_elems:
                    ornaments.remove(elem)
                    log.append(f'Removed ornament {elem.tag} in m.{num}')
                    removed += 1
                _cleanup_empty_containers(note, notations, ornaments)
            else:
                # Conservative: only remove when co-located with other artifacts
                articulations = notations.find('articulations')
                has_artifacts = (articulations is not None and
                                any(articulations.find(a) is not None
                                    for a in artifact_tags))
                if has_artifacts:
                    for elem in ornament_elems:
                        ornaments.remove(elem)
                        log.append(f'Removed suspicious {elem.tag} in m.{num}')
                        removed += 1
                    _cleanup_empty_containers(note, notations, ornaments)
                else:
                    for elem in ornament_elems:
                        warnings.append(
                            f'WARNING: {elem.tag} in m.{num} — verify against source')

    log.extend(warnings)
    return removed


# ── Rule 7: Duplicate/contradictory dynamics ────────────────────────────

def clean_duplicate_dynamics(measures, log):
    """Deduplicate dynamics within a measure and across consecutive measures."""
    removed = 0
    last_dynamic = None
    last_dynamic_idx = -10

    for idx, m in enumerate(measures):
        dyn_info = []  # (direction_elem, dynamic_type)
        for direction in m.findall('direction'):
            for dtype in direction.findall('direction-type'):
                dyn = dtype.find('dynamics')
                if dyn is not None:
                    dyn_type = _get_dynamic_type(dyn)
                    if dyn_type:
                        dyn_info.append((direction, dyn_type))

        num = m.get('number', '?')

        if len(dyn_info) > 1:
            # Multiple dynamics in same measure — keep loudest
            dyn_info.sort(key=lambda x: DYNAMIC_PRIORITY.get(x[1], 0), reverse=True)
            keep_type = dyn_info[0][1]
            for direction, dyn_type in dyn_info[1:]:
                m.remove(direction)
                log.append(f'Removed contradictory {dyn_type} in m.{num} (keeping {keep_type})')
                removed += 1
            last_dynamic = keep_type
            last_dynamic_idx = idx
        elif len(dyn_info) == 1:
            direction, dyn_type = dyn_info[0]
            if dyn_type == last_dynamic and idx == last_dynamic_idx + 1:
                m.remove(direction)
                log.append(f'Removed consecutive duplicate {dyn_type} in m.{num}')
                removed += 1
            else:
                last_dynamic = dyn_type
                last_dynamic_idx = idx

    return removed


# ── Rule 11: Outlier dynamics ───────────────────────────────────────────

def clean_outlier_dynamics(measures, log):
    """Remove dynamics that are implausible dips (OCR misdetections).

    Uses a window of ±3 positions in the dynamics sequence. If a dynamic
    is ≥3 priority levels softer than the STRONGEST dynamic on BOTH sides
    of the window, it's an outlier. This catches cases like:
        mf → p → pp → f  (the pp is 3 below the mf on the left, 4 below f on right)
    even when a cluster of wrong soft dynamics shields each other from
    immediate-neighbor detection.
    """
    THRESHOLD = 3
    WINDOW = 3  # look ±3 positions in dynamics sequence

    # Collect surviving dynamics in score order
    dyn_list = []  # (measure_elem, direction_elem, dyn_type)
    for m in measures:
        for direction in m.findall('direction'):
            for dtype in direction.findall('direction-type'):
                dyn = dtype.find('dynamics')
                if dyn is not None:
                    dyn_type = _get_dynamic_type(dyn)
                    if dyn_type:
                        dyn_list.append((m, direction, dyn_type))

    to_remove = []
    for i, (m, direction, dyn_type) in enumerate(dyn_list):
        pri = DYNAMIC_PRIORITY.get(dyn_type, 0)

        # Max dynamic in left window
        left_max = 0
        for j in range(max(0, i - WINDOW), i):
            left_max = max(left_max, DYNAMIC_PRIORITY.get(dyn_list[j][2], 0))

        # Max dynamic in right window
        right_max = 0
        for j in range(i + 1, min(len(dyn_list), i + WINDOW + 1)):
            right_max = max(right_max, DYNAMIC_PRIORITY.get(dyn_list[j][2], 0))

        if left_max > 0 and right_max > 0:
            if pri <= left_max - THRESHOLD and pri <= right_max - THRESHOLD:
                to_remove.append((m, direction, dyn_type))
        elif left_max > 0 and right_max == 0:
            # Last dynamic(s) in piece — flag if huge drop from context
            if pri <= left_max - THRESHOLD:
                to_remove.append((m, direction, dyn_type))

    removed = 0
    for m, direction, dyn_type in to_remove:
        m.remove(direction)
        log.append(f'Removed outlier dynamic {dyn_type} in m.{m.get("number", "?")}')
        removed += 1
    return removed


# ── Rule 12: Reconcile dynamics against ground truth ────────────────────

# Standard MIDI velocities for dynamics
DYNAMIC_VELOCITY = {
    'ppp': 16, 'pp': 33, 'p': 56, 'mp': 71,
    'mf': 89, 'f': 112, 'ff': 126, 'fff': 127,
}


def _make_dynamics_direction(dyn_type, staff='1'):
    """Create a <direction> element containing a dynamics marking."""
    direction = ET.Element('direction', {'placement': 'below'})
    dtype = ET.SubElement(direction, 'direction-type')
    dynamics = ET.SubElement(dtype, 'dynamics')
    ET.SubElement(dynamics, dyn_type)
    staff_elem = ET.SubElement(direction, 'staff')
    staff_elem.text = staff
    vel = DYNAMIC_VELOCITY.get(dyn_type, 89)
    ET.SubElement(direction, 'sound', {'dynamics': str(vel)})
    return direction


def reconcile_dynamics(measures, expected, log):
    """Enforce a ground-truth dynamics map from visual inspection.

    This is the authoritative step — after automated heuristic cleanup,
    this function makes the MusicXML match exactly what's in the source PDF.

    Args:
        measures: List of measure elements from a part.
        expected: Dict mapping measure number (str) to dynamic type (str).
            E.g. {'1': 'p', '9': 'mf', '17': 'f', '33': 'ff'}
        log: List to append log messages to.

    Returns:
        Number of changes made.
    """
    changes = 0

    for m in measures:
        num = m.get('number', '?')

        # Find existing dynamics directions in this measure
        dyn_dirs = []
        for direction in m.findall('direction'):
            for dtype in direction.findall('direction-type'):
                dyn = dtype.find('dynamics')
                if dyn is not None:
                    dyn_type = _get_dynamic_type(dyn)
                    if dyn_type:
                        dyn_dirs.append((direction, dyn_type))

        if num in expected:
            want = expected[num]
            if len(dyn_dirs) == 1 and dyn_dirs[0][1] == want:
                continue  # already correct

            # Remove all existing dynamics (wrong, extra, or duplicated)
            old_types = [d[1] for d in dyn_dirs]
            for direction, _ in dyn_dirs:
                m.remove(direction)
                changes += 1

            # Always insert the correct dynamic before first <note>
            new_dir = _make_dynamics_direction(want)
            insert_idx = 0
            for i, child in enumerate(m):
                if child.tag == 'note':
                    insert_idx = i
                    break
            m.insert(insert_idx, new_dir)
            changes += 1

            if not old_types:
                log.append(f'Added missing {want} in m.{num}')
            elif old_types != [want]:
                log.append(f'Replaced {"+".join(old_types)} with {want} in m.{num}')
        else:
            # No dynamic expected here — remove any that exist
            for direction, dyn_type in dyn_dirs:
                m.remove(direction)
                log.append(f'Removed spurious {dyn_type} in m.{num}')
                changes += 1

    return changes


# ── Rule 13: Section labels ──────────────────────────────────────────────

def _make_rehearsal_direction(text):
    """Create a <direction> with a <rehearsal> element for a section label."""
    direction = ET.Element('direction', {'placement': 'above'})
    dtype = ET.SubElement(direction, 'direction-type')
    rehearsal = ET.SubElement(dtype, 'rehearsal', {
        'font-size': '12',
        'font-weight': 'bold',
    })
    rehearsal.text = text
    return direction


def reconcile_sections(measures, expected, log):
    """Ensure section labels exist as <rehearsal> elements at the right measures.

    Audiveris frequently misses section labels (VERSE, CHORUS, etc.) or
    encodes them only as page-level <credit-words> not attached to measures.

    Args:
        measures: List of measure elements from a part.
        expected: Dict mapping measure number (str) to section label (str).
            E.g. {'1': 'VERSE', '13': 'PRE-CHORUS', '17': 'CHORUS'}
        log: List to append log messages to.

    Returns:
        Number of changes made.
    """
    changes = 0

    for m in measures:
        num = m.get('number', '?')

        # Find existing rehearsal directions in this measure
        rehearsal_dirs = []
        for direction in m.findall('direction'):
            for dtype in direction.findall('direction-type'):
                rehearsal = dtype.find('rehearsal')
                if rehearsal is not None:
                    rehearsal_dirs.append((direction, (rehearsal.text or '').strip()))

        if num in expected:
            want = expected[num]
            # Check if correct rehearsal already exists
            if any(text.upper() == want.upper() for _, text in rehearsal_dirs):
                continue

            # Remove any wrong rehearsal marks
            for direction, text in rehearsal_dirs:
                m.remove(direction)
                log.append(f'Removed wrong section label "{text}" in m.{num}')
                changes += 1

            # Insert the correct rehearsal mark before first note
            new_dir = _make_rehearsal_direction(want)
            insert_idx = 0
            for i, child in enumerate(m):
                if child.tag == 'note':
                    insert_idx = i
                    break
            m.insert(insert_idx, new_dir)
            log.append(f'Added section label "{want}" in m.{num}')
            changes += 1
        else:
            # No section label expected — remove any spurious ones
            for direction, text in rehearsal_dirs:
                m.remove(direction)
                log.append(f'Removed spurious section label "{text}" in m.{num}')
                changes += 1

    return changes


def clean_section_label_credits(root, section_labels, log):
    """Remove <credit-words> that duplicate section labels added as <rehearsal>.

    Audiveris often puts section labels as page-level credits rather than
    measure-attached rehearsal marks. Once we've added proper <rehearsal>
    elements, these credits are redundant.
    """
    if not section_labels:
        return 0
    label_set = {v.upper() for v in section_labels.values()}
    removed = 0
    to_remove = []
    for credit in root.findall('credit'):
        words = credit.find('credit-words')
        if words is not None and words.text:
            text = words.text.strip().upper()
            if text in label_set:
                to_remove.append((credit, words.text.strip()))
    for credit, text in to_remove:
        root.remove(credit)
        log.append(f'Removed redundant section credit: "{text}"')
        removed += 1
    return removed


# ── Rule 10: Breath marks ───────────────────────────────────────────────

def clean_breath_marks(measures, log):
    """Remove breath marks on piano (unusual, likely OCR artifact)."""
    removed = 0
    for m in measures:
        for note in m.iter('note'):
            notations = note.find('notations')
            if notations is None:
                continue
            articulations = notations.find('articulations')
            if articulations is None:
                continue
            for breath in articulations.findall('breath-mark'):
                articulations.remove(breath)
                log.append(f'Removed breath mark in m.{m.get("number", "?")}')
                removed += 1
            _cleanup_empty_containers(note, notations, articulations)
    return removed


# ── Main entry point ────────────────────────────────────────────────────

def clean_musicxml(input_path, instrument='piano', dynamics=None, sections=None,
                   verbose=False, source='generated'):
    """Clean a MusicXML file of artifacts.

    Args:
        input_path: Path to input MusicXML file.
        instrument: Instrument type (enables instrument-specific rules).
        dynamics: Optional ground-truth dynamics map from visual inspection.
            Dict mapping measure number (str) to dynamic type (str).
            When provided, this is the authoritative source — all dynamics
            not in the map are removed, all missing ones are added.
        sections: Optional ground-truth section labels from visual inspection.
            Dict mapping measure number (str) to section label (str).
            E.g. {'1': 'VERSE', '13': 'PRE-CHORUS', '17': 'CHORUS'}
            When provided, adds <rehearsal> marks and removes redundant credits.
        verbose: Print per-rule counts during processing.
        source: 'generated' (default) for MusicXML produced by this project's
            quantize/post pipeline, or 'omr' for raw Audiveris OCR output.
            The OCR-only rules (garbage-credit stripping, metadata-garbage,
            volta/breath-mark repair, remove-all ornaments, outlier-dynamics)
            only make sense on OCR output — on clean generated scores they
            misfire: they would delete a legitimate short title (e.g. a cover
            titled "U"), strip intentional ornaments, and remove *real*
            velocity-derived subito dynamics as if they were OCR noise. In
            'generated' mode those are skipped; the source-agnostic cleanups
            (unpaired pedals, non-piano articulations, duplicate articulations,
            duplicate/contradictory dynamics) still run.

    Returns:
        Tuple of (ElementTree, log_lines).
    """
    tree = ET.parse(input_path)
    root = tree.getroot()
    log = []
    is_piano = instrument == 'piano'
    omr = source == 'omr'

    def _report(label, n):
        if verbose and n:
            print(f'  {label}: {n}')

    # Global rules (not per-part). OCR-garbage stripping would delete a
    # legitimate short title on generated scores, so it is OMR-only.
    if omr:
        _report('Credit garbage', clean_credit_garbage(root, log))
        _report('Metadata cleanup', clean_metadata(root, log))
    if sections:
        _report('Section label credits', clean_section_label_credits(root, sections, log))

    # Per-part rules
    for part in root.findall('.//part'):
        part_measures = list(part.findall('measure'))

        if omr:  # volta/repeat OCR artifacts do not occur in generated output
            _report('Orphan voltas', clean_orphan_voltas(part_measures, log))
            _report('Volta on forward repeat',
                    clean_volta_on_forward_repeat(part_measures, log))

        # Source-agnostic safety: pedal pairing matters once we insert pedals.
        _report('Unpaired pedals', clean_unpaired_pedals(part_measures, log))

        if is_piano:
            _report('Non-piano articulations',
                    clean_non_piano_articulations(part_measures, log))
            if omr:
                _report('Breath marks', clean_breath_marks(part_measures, log))

        _report('Duplicate articulations',
                clean_duplicate_articulations(part_measures, log))
        if omr:
            # remove_all strips every ornament — right for OCR hallucinations,
            # wrong for our intentional marks.
            _report('Ornaments', clean_suspicious_ornaments(
                part_measures, log, remove_all=is_piano))

        if dynamics:
            # Ground truth provided — reconcile is authoritative, skip heuristics
            _report('Dynamics reconciled', reconcile_dynamics(
                part_measures, dynamics, log))
        else:
            # Contradictory/duplicate dynamics are noise in any source.
            _report('Dynamics dedup', clean_duplicate_dynamics(part_measures, log))
            if omr:
                # Outlier removal assumes a soft dip is an OCR misread; our
                # dynamics are measured from velocity, so a dip may be a real
                # subito — do not strip it on generated scores.
                _report('Dynamics outliers', clean_outlier_dynamics(part_measures, log))
            if verbose:
                print('  WARNING: No --dynamics ground truth provided.')
                print('           Dynamics cleaned by heuristics only — verify against PDF!')

        if sections:
            _report('Section labels', reconcile_sections(
                part_measures, sections, log))
        elif verbose:
            print('  NOTE: No --sections provided. Section labels not added.')
            print('        Visually inspect PDF for section labels (VERSE, CHORUS, etc.)')

    return tree, log


def _parse_dynamics_arg(s):
    """Parse dynamics from CLI: JSON file path or inline 'measure:dynamic,...' pairs."""
    import json
    if os.path.isfile(s):
        with open(s) as f:
            return json.load(f)
    # Inline format: "1:p,9:mf,17:f,33:ff"
    result = {}
    for pair in s.split(','):
        pair = pair.strip()
        if ':' in pair:
            m, d = pair.split(':', 1)
            result[m.strip()] = d.strip()
    return result


def _parse_sections_arg(s):
    """Parse sections from CLI: JSON file path or inline 'measure:LABEL,...' pairs."""
    import json
    if os.path.isfile(s):
        with open(s) as f:
            return json.load(f)
    # Inline format: "1:VERSE,13:PRE-CHORUS,17:CHORUS"
    result = {}
    for pair in s.split(','):
        pair = pair.strip()
        if ':' in pair:
            m, label = pair.split(':', 1)
            result[m.strip()] = label.strip()
    return result


def main():
    parser = argparse.ArgumentParser(
        description='Clean MusicXML (this project\'s pipeline output, or Audiveris OMR)')
    parser.add_argument('input', help='Input MusicXML file')
    parser.add_argument('-o', '--output', help='Output file (default: input with -clean suffix)')
    parser.add_argument('--instrument', default='piano',
                        help='Instrument type (default: piano)')
    parser.add_argument('--source', default='generated', choices=['generated', 'omr'],
                        help='Input provenance (default: generated). "generated" skips '
                             'OCR-only rules that misfire on clean scores; "omr" runs '
                             'the full Audiveris cleanup.')
    parser.add_argument('--dynamics',
                        help='Ground-truth dynamics from visual PDF inspection. '
                             'Either a JSON file {"1":"p","9":"mf",...} or inline '
                             '"1:p,9:mf,17:f,33:ff"')
    parser.add_argument('--sections',
                        help='Ground-truth section labels from visual PDF inspection. '
                             'Either a JSON file {"1":"VERSE","17":"CHORUS",...} or inline '
                             '"1:VERSE,13:PRE-CHORUS,17:CHORUS"')
    parser.add_argument('--verbose', '-v', action='store_true', help='Print detailed log')
    args = parser.parse_args()

    if not args.output:
        base = args.input.rsplit('.', 1)
        args.output = base[0] + '-clean.' + (base[1] if len(base) > 1 else 'musicxml')

    dynamics = _parse_dynamics_arg(args.dynamics) if args.dynamics else None
    sections = _parse_sections_arg(args.sections) if args.sections else None

    tree, log = clean_musicxml(args.input, instrument=args.instrument,
                               dynamics=dynamics, sections=sections,
                               verbose=args.verbose, source=args.source)
    tree.write(args.output, xml_declaration=True, encoding='UTF-8')

    print(f'\nCleaned MusicXML written to: {args.output}')
    print(f'Changes made: {len(log)}')
    if log:
        print('\nChange log:')
        for entry in log:
            print(f'  {entry}')


if __name__ == '__main__':
    main()
