#!/bin/sh
# Thin wrapper around the DuET CLI (the `duet` entry point of the duet-score
# package), which lives in a SEPARATE repo (~/Repos/DuET) with its own venv.
#
# Purpose: give the pipeline a stable, space-free command path
# (scripts/duet.sh ...) so a single permission rule — Bash(scripts/duet.sh *) —
# covers every DuET invocation. DuET is the MIDI -> MusicXML stage: it takes the
# cleaned Transkun .mid and produces a readable engraved score.musicxml (plus
# review.json, score.mid, notes.json, score.npz, frames.csv, report.json).
#
# All arguments pass through unchanged and the exit code is preserved.
# Override the CLI location with the DUET env var if DuET lives elsewhere, e.g.
#   DUET=/path/to/DuET/.venv/bin/duet scripts/duet.sh input.mid -o out/ --device cpu
exec "${DUET:-/Users/tonisucic/Repos/DuET/.venv/bin/duet}" "$@"
