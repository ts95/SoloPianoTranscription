"""Regression test: simplify_score's three playability rules.

Run: .venv/bin/python scripts/test_simplify_score.py
"""
from music21 import chord as m21chord
from music21 import meter, note as m21note, stream

from simplify_score import pitches_of, simplify


def two_staff_score(rh_events, lh_events):
    """events: [(offset, [midi,...], quarterLength)] per staff."""
    s = stream.Score()
    for events in (rh_events, lh_events):
        p = stream.Part()
        p.insert(0, meter.TimeSignature("4/4"))
        for off, midis, ql in events:
            el = m21note.Note(midis[0]) if len(midis) == 1 \
                else m21chord.Chord(midis)
            el.quarterLength = ql
            p.insert(off, el)
        s.insert(0, p.makeMeasures())
    return s


def staff_pitches(score, idx):
    part = list(score.parts)[idx]
    return [(float(e.getOffsetInHierarchy(part)), pitches_of(e))
            for e in part.recurse().notes]


def test_repeat_strikes_thinned():
    gm = [55, 58, 62, 67]  # G minor stack
    rh = [(o, gm, 0.5) for o in (0.0, 0.5, 1.0, 1.5)]
    lh = [(o, [43, 50], 0.5) for o in (0.0, 0.5, 1.0, 1.5)]
    s = two_staff_score(rh, lh)
    stats = simplify(s, 4.0)
    got = staff_pitches(s, 0)
    assert got[0][1] == gm, "downbeat anchor chord must keep the full stack"
    assert all(ps == [62, 67] for _, ps in got[1:]), (
        f"repeat strikes should thin to top two, got {got[1:]}")
    assert stats["repeat_strikes_thinned"] == 3
    print("ok: off-beat repeat strikes thin to the melody skeleton")


def test_lh_stack_reduced_when_rh_covers():
    rh = [(0.0, [62, 65, 69], 1.0)]           # RH holds the full triad
    lh = [(0.0, [38, 45, 50, 53], 1.0)]       # D A d f -> bass + fifth/octave
    s = two_staff_score(rh, lh)
    stats = simplify(s, 4.0)
    got = staff_pitches(s, 1)[0][1]
    assert got[0] == 38 and len(got) <= 2, f"LH not reduced: {got}"
    assert stats["lh_stacks_reduced"] == 1
    print("ok: LH stack reduces to bass+partner when RH voices the triad")


def test_span_capped_never_loses_harmony():
    # doubled low G an octave under the chord -> droppable (pc survives)
    rh = [(0.0, [55, 67, 70, 74], 1.0)]
    # NO doubling: the endpoint octave-folds inward instead of vanishing
    rh.append((1.0, [53, 60, 69], 1.0))
    s = two_staff_score(rh, [(0.0, [43], 2.0)])
    stats = simplify(s, 4.0)
    got = staff_pitches(s, 0)
    assert got[0][1] == [67, 70, 74], f"doubled-pc span not capped: {got[0]}"
    assert got[1][1] == [60, 65, 69], f"non-doubled endpoint not folded: {got[1]}"
    assert {m % 12 for m in got[1][1]} == {53 % 12, 60 % 12, 69 % 12}, (
        "octave fold changed the pitch-class content")
    assert stats["spans_capped"] == 2
    print("ok: spans cap by dropping doubled pcs or octave-folding, "
          "never losing harmony")


def test_beams_survive_thinning():
    gm = [55, 58, 62, 67]
    rh = [(o, gm, 0.5) for o in (0.0, 0.5, 1.0, 1.5)]
    s = two_staff_score(rh, [(0.0, [43], 2.0)])
    for p in s.parts:
        p.makeBeams(inPlace=True)
    part = list(s.parts)[0]
    before = [len(e.beams.beamsList) for e in part.recurse().notes]
    assert any(before), "test setup: no beams to preserve"
    simplify(s, 4.0)
    after = [len(e.beams.beamsList) for e in part.recurse().notes]
    assert after == before, (
        f"thinning changed beam groups: {before} -> {after}")
    print("ok: beam groups survive chord thinning")


if __name__ == "__main__":
    test_repeat_strikes_thinned()
    test_lh_stack_reduced_when_rh_covers()
    test_span_capped_never_loses_harmony()
    test_beams_survive_thinning()
