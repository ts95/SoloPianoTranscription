#!/bin/sh
# Thin wrapper around the MuseScore 4 CLI.
#
# Purpose: give the pipeline a stable, space-free command path
# (scripts/mscore.sh ...) so a single permission rule — Bash(scripts/mscore.sh *)
# — covers every MuseScore invocation. The real binary path contains a space
# and was previously called via a "$MSCORE" shell variable, neither of which a
# static allowlist rule can match.
#
# All arguments pass through unchanged and the exit code is preserved.
# Override the binary location with the MSCORE env var if MuseScore lives
# elsewhere than the default /Applications install.
exec "${MSCORE:-/Applications/MuseScore 4.app/Contents/MacOS/mscore}" "$@"
