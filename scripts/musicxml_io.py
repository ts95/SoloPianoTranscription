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
