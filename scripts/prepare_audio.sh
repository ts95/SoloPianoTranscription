#!/bin/bash
# Prepare audio for Transkun: two-pass EBU R128 loudness normalization with
# LINEAR gain (a single static gain per file — dynamic-mode loudnorm would
# compress the dynamics and skew the velocities Transkun emits), resampled to
# the 44.1 kHz the model expects.
#
# Usage: prepare_audio.sh <input-audio> <output.wav>
set -euo pipefail

FFMPEG=/opt/homebrew/bin/ffmpeg
IN="$1"
OUT="$2"
TARGET="I=-16:TP=-1.5:LRA=11"

STATS=$("$FFMPEG" -hide_banner -nostats -i "$IN" \
  -af "loudnorm=$TARGET:print_format=json" -f null - 2>&1 | sed -n '/^{/,/^}/p')

get() { printf '%s' "$STATS" | python3 -c "import json,sys; print(json.load(sys.stdin)['$1'])"; }

"$FFMPEG" -y -hide_banner -nostats -i "$IN" \
  -af "loudnorm=$TARGET:measured_I=$(get input_i):measured_TP=$(get input_tp):measured_LRA=$(get input_lra):measured_thresh=$(get input_thresh):offset=$(get target_offset):linear=true" \
  -ar 44100 "$OUT"

echo "wrote $OUT (44.1 kHz, linear loudnorm from integrated $(get input_i) LUFS)"
