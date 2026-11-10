"""Regression tests for transcription_cleanup helpers.

Run: .venv/bin/python scripts/test_transcription_cleanup.py
"""
import os
import stat
import tempfile

import mido

from transcription_cleanup import bar_times_from_midi, render_ok, scale_for_clean


def test_bar_times_follow_tempo_and_meter_changes():
    # 2 bars of 4/4 at 120 BPM (2 s each), then 2 bars of 3/4 at 60 BPM (3 s each)
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "t.mid")
        m = mido.MidiFile(ticks_per_beat=480)
        t = mido.MidiTrack()
        m.tracks.append(t)
        t.append(mido.MetaMessage("set_tempo", tempo=500000, time=0))
        t.append(mido.MetaMessage("time_signature", numerator=4, denominator=4, time=0))
        t.append(mido.Message("note_on", note=60, velocity=80, time=0))
        t.append(mido.MetaMessage("set_tempo", tempo=1000000, time=3840))
        t.append(mido.MetaMessage("time_signature", numerator=3, denominator=4, time=0))
        t.append(mido.Message("note_off", note=60, velocity=0, time=2880))
        m.save(path)
        times = [round(x, 6) for x in bar_times_from_midi(path)]
    assert times == [0.0, 2.0, 4.0, 7.0, 10.0], times
    print("ok: bar times follow tempo and time-signature changes")


def _fake_mscore(td, name, body):
    path = os.path.join(td, name)
    with open(path, "w") as f:
        f.write("#!/bin/sh\n" + body + "\n")
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)
    return path


def test_render_judged_by_output_file_not_exit_code():
    with tempfile.TemporaryDirectory() as td:
        crashy = _fake_mscore(td, "crashy.sh", 'printf x > "$3"\nexit 134')
        silent = _fake_mscore(td, "silent.sh", "exit 0")
        assert render_ok(crashy, "score.musicxml", os.path.join(td, "a.mid")) is True
        assert render_ok(silent, "score.musicxml", os.path.join(td, "b.mid")) is False
    print("ok: a render counts when the file was written (exit 134 tolerated), not when exit is 0 with no file")


def test_clean_uses_the_given_key():
    assert scale_for_clean([], "D Major") == {2, 4, 6, 7, 9, 11, 1}
    assert scale_for_clean([], "C# minor") == {1, 3, 4, 6, 8, 9, 11}
    assert scale_for_clean([], "Eb Major") == {3, 5, 7, 8, 10, 0, 2}
    print("ok: the artifact music-prior uses --key when given")


if __name__ == "__main__":
    test_bar_times_follow_tempo_and_meter_changes()
    test_render_judged_by_output_file_not_exit_code()
    test_clean_uses_the_given_key()
