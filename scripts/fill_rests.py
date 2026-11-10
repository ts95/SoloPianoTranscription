#!/usr/bin/env python3
"""Replace the rests that follow a note with a longer note.

A transcription is full of short rests where the player simply let go of a key;
under the pedal the note keeps sounding anyway. This lengthens each note (or
chord) to fill the bar up to the next note of its voice, so those rests go away.

    fill_rests.py <in.musicxml> <out.musicxml>

Works on a raw DuET score and on a MuseScore export alike. Rules:
  - only rests AFTER a note in the same bar and voice are filled; a rest that
    opens a bar (or a whole-bar rest) stays
  - a note never grows past its own bar
  - when the longer value is one note (plain or dotted) the note just becomes it;
    otherwise the rest turns into a tied continuation of the note
  - tuplets and grace notes are left alone
  - all <beam> elements, system/page breaks and a MuseScore export's <supports>
    declarations are dropped, so MuseScore re-beams and re-flows the new values
"""
import argparse
import copy
import json
import sys
import xml.etree.ElementTree as ET

TYPES = [("whole", 16), ("half", 8), ("quarter", 4), ("eighth", 2), ("16th", 1)]  # in 16ths


def notation(ticks, div):
    """(type, dots) of a single plain or dotted note lasting `ticks`, else None."""
    sixteenths = ticks * 4 / div
    for name, n in TYPES:
        if sixteenths == n:
            return name, 0
        if sixteenths == n * 1.5 and n >= 2:
            return name, 1
    return None


def set_value(note, ticks, div):
    name, dots = notation(ticks, div)
    note.find("duration").text = str(ticks)
    note.find("type").text = name
    for dot in note.findall("dot"):
        note.remove(dot)
    at = list(note).index(note.find("type")) + 1
    for _ in range(dots):
        note.insert(at, ET.Element("dot"))


def add_tie(note, kind):
    """Add a tie start/stop to a pitched note, in schema order."""
    tie = ET.Element("tie", type=kind)
    at = list(note).index(note.find("duration")) + 1
    while at < len(note) and note[at].tag == "tie":
        at += 1
    note.insert(at, tie)
    notations = note.find("notations")
    if notations is None:
        notations = ET.SubElement(note, "notations")
    notations.insert(0, ET.Element("tied", type=kind))


def continuation(event, rest, div):
    """Copies of the chord `event` that sound for the length of `rest`, tied from it."""
    out = []
    for src in event:
        new = ET.Element("note")
        for tag in ("chord", "pitch", "duration", "voice", "type", "staff"):
            el = src.find(tag)
            if el is not None:
                new.append(copy.deepcopy(el))
        set_value(new, int(rest.find("duration").text), div)
        add_tie(new, "stop")
        new.tail = rest.tail
        out.append(new)
    return out


def fill_measure(measure, div, stats):
    last = {}       # voice -> the chord (list of note elements) a following rest may extend
    adjacent = {}   # voice -> True while nothing but that voice's notes followed the chord
    for el in list(measure):
        if el.tag in ("backup", "forward"):
            if el.tag == "forward":
                last.clear()
            continue
        if el.tag != "note":
            for v in adjacent:
                adjacent[v] = False   # a direction sits here: merging would move it
            continue
        voice = el.findtext("voice", "1")
        plain = el.find("grace") is None and el.find("time-modification") is None \
            and el.find("duration") is not None and el.find("type") is not None
        if el.find("rest") is None:
            if not plain:
                last.pop(voice, None)
            elif el.find("chord") is not None and voice in last and adjacent.get(voice):
                last[voice].append(el)
            else:
                last[voice], adjacent[voice] = [el], True
            continue
        event = last.get(voice)
        if event is None or not plain:
            last.pop(voice, None)
            continue
        rest_ticks = int(el.find("duration").text)
        total = int(event[0].find("duration").text) + rest_ticks
        if adjacent.get(voice) and notation(total, div):
            for note in event:
                set_value(note, total, div)
            measure.remove(el)
            stats["merged"] += 1
        else:
            new = continuation(event, el, div)
            at = list(measure).index(el)
            measure.remove(el)
            for i, note in enumerate(new):
                measure.insert(at + i, note)
            for note in event:
                add_tie(note, "start")
            last[voice], adjacent[voice] = new, True
            stats["tied"] += 1


def fill_rests(root):
    stats = {"merged": 0, "tied": 0}
    div = 1
    for part in root.iter("part"):
        for measure in part.findall("measure"):
            d = measure.find("attributes/divisions")
            if d is not None:
                div = int(d.text)
            fill_measure(measure, div, stats)
    beams = 0
    for note in root.iter("note"):
        for beam in note.findall("beam"):
            note.remove(beam)
            beams += 1
    stats["beams_removed"] = beams
    # A MuseScore export declares <supports element="beam"/"print">, which makes the
    # next import trust the file's (now absent) beams and its old system/page breaks.
    # Dropping the declarations and the breaks lets MuseScore beam and lay out afresh.
    for encoding in root.iter("encoding"):
        for supports in encoding.findall("supports"):
            encoding.remove(supports)
    for pr in root.iter("print"):
        pr.attrib.pop("new-system", None)
        pr.attrib.pop("new-page", None)
    stats["rests_left"] = sum(1 for n in root.iter("note") if n.find("rest") is not None)
    return stats


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("output")
    args = ap.parse_args()

    with open(args.input, encoding="utf-8") as f:
        text = f.read()
    start = text.index("<score-partwise")
    root = ET.fromstring(text[start:])
    stats = fill_rests(root)
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(text[:start] + ET.tostring(root, encoding="unicode") + "\n")
    print(json.dumps({"input": args.input, "output": args.output, **stats}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
