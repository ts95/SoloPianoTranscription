#!/bin/bash
# Prepare audio for Transkun: ONE static gain per file (never a compressor —
# compression would skew the velocities Transkun emits), resampled to the
# 44.1 kHz the model expects.
#
# The gain moves the file toward -16 LUFS integrated, capped so the true peak
# stays <= -1.5 dBTP. A peaky recording therefore ends up quieter than -16 LUFS
# rather than being limited. (ffmpeg's two-pass loudnorm is NOT used for the
# gain: with linear=true it silently falls back to dynamic mode whenever the
# peak or loudness range exceeds its targets.)
#
# Usage: prepare_audio.sh <input-audio> <output.wav>
set -euo pipefail

FFMPEG=/opt/homebrew/bin/ffmpeg
IN="$1"
OUT="$2"
TARGET_I=-16
TARGET_TP=-1.5

STATS=$("$FFMPEG" -hide_banner -nostats -i "$IN" \
  -af "loudnorm=I=$TARGET_I:TP=$TARGET_TP:LRA=11:print_format=json" -f null - 2>&1 | sed -n '/^{/,/^}/p')

GAIN=$(printf '%s' "$STATS" | python3 -c "
import json, math, sys
d = json.load(sys.stdin)
g = min($TARGET_I - float(d['input_i']), $TARGET_TP - float(d['input_tp']))
if not math.isfinite(g):
    sys.exit('prepare_audio: input is silent')
print(round(g, 2))")

"$FFMPEG" -y -hide_banner -nostats -i "$IN" -af "volume=${GAIN}dB" -ar 44100 "$OUT"

echo "wrote $OUT (44.1 kHz, static gain ${GAIN} dB)"
