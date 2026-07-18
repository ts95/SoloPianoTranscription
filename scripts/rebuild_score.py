#!/usr/bin/env python3
"""One-command rebuild of a piece's score from its piece.json manifest.

Chain: quantize -> post -> clean_musicxml -> edits.py (if present) ->
mscore import -> finish_score (anacrusis, pedaling, hygiene) -> export
.musicxml/.pdf -> verify. Every stage summary is persisted under
<piece-dir>/reports/ and one compact digest is printed at the end.
The .mscz is a build product: sources are cleaned.mid + beats.json +
piece.json + edits.py. Never edit outputs in place — change a source and
rerun this.
"""
import argparse
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
TC = os.path.join(HERE, "transcription_cleanup.py")
CLEAN_XML = os.path.join(HERE, "clean_musicxml.py")
FINISH = os.path.join(HERE, "finish_score.py")


def run(cmd, report_path=None, quiet_ok=True):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if report_path and r.stdout:
        with open(report_path, "w") as f:
            f.write(r.stdout)
            if r.stderr:
                f.write("\n--- stderr ---\n" + r.stderr)
    if r.returncode != 0:
        sys.stderr.write(r.stdout + r.stderr)
        raise SystemExit(f"stage failed: {' '.join(map(str, cmd))}")
    return r.stdout


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("piece_dir")
    ap.add_argument("--mscore",
                    default="/Applications/MuseScore 4.app/Contents/MacOS/mscore")
    ap.add_argument("--skip-verify", action="store_true")
    args = ap.parse_args()

    d = os.path.abspath(args.piece_dir)
    man = json.load(open(os.path.join(d, "piece.json")))
    slug = man["slug"]
    S = os.path.join(d, slug)
    reports = os.path.join(d, "reports")
    os.makedirs(reports, exist_ok=True)
    digest = {}

    q = [PY, TC, "quantize", S + ".cleaned.mid", S + ".tmp.musicxml",
         "--beats", os.path.join(d, man["beats"]),
         "--beats-shift", str(man["beats_shift"]),
         "--key", man["key"], "--time-sig", man["time_sig"],
         "--title", man["title"], "--composer", man["composer"]]
    for role in ("performer", "arranger"):
        if man.get(role):
            q += [f"--{role}", man[role]]
    q += man.get("quantize_flags", [])
    out = run(q, os.path.join(reports, "quantize.json"))
    js = json.loads(out)
    digest["fit"] = js.get("onset_grid_fit")
    digest["lint"] = js.get("lint", {}).get("verdict")

    p = [PY, TC, "post", S + ".tmp.musicxml", S + ".musicxml",
         "--key", man["key"], "--time-sig", man["time_sig"]]
    if man.get("dynamics_from_cleaned_midi"):
        p += ["--dynamics-from", S + ".cleaned.mid"]
    p += ["--beats", os.path.join(d, man["beats"]),
          "--beats-shift", str(man["beats_shift"])]
    if js.get("offset_shift_beats"):
        p += ["--offset-shift", str(js["offset_shift_beats"])]
    p += man.get("post_flags", [])
    out = run(p, os.path.join(reports, "post.json"))
    digest["post_lint"] = json.loads(out).get("lint", {}).get("verdict")
    os.remove(S + ".tmp.musicxml")

    run([PY, CLEAN_XML, S + ".musicxml", "-o", S + ".musicxml",
         "--source", "generated"], os.path.join(reports, "clean_musicxml.txt"))

    edits = os.path.join(d, "edits.py")
    if os.path.exists(edits):
        print(run([PY, edits, S + ".musicxml"],
                  os.path.join(reports, "edits.txt")), end="")
        digest["edits"] = "applied"

    run([args.mscore, S + ".musicxml", "-o", S + ".mscz"])
    f = [PY, FINISH, S + ".mscz"]
    if man.get("anacrusis"):
        f += ["--anacrusis", str(man["anacrusis"])]
    run(f, os.path.join(reports, "finish.txt"))
    run([args.mscore, S + ".mscz", "-o", S + ".musicxml"])
    run([args.mscore, S + ".mscz", "-o", S + ".pdf"])

    if not args.skip_verify:
        v = [PY, TC, "verify", S + ".musicxml", S + ".wav",
             "--output", os.path.join(d, "verify.json")]
        if man.get("audio_window"):
            v += ["--audio-window", man["audio_window"]]
        run(v, os.path.join(reports, "verify.txt"))
        digest["verify_median"] = json.load(
            open(os.path.join(d, "verify.json"))).get("median_similarity")

    print("rebuild digest: " + json.dumps(digest))


if __name__ == "__main__":
    main()
