#!/bin/bash
# Regression test: prepare_audio.sh must apply ONE static gain (no compression).
# Run: bash scripts/test_prepare_audio.sh
set -euo pipefail
FFMPEG=/opt/homebrew/bin/ffmpeg
FFPROBE=/opt/homebrew/bin/ffprobe
T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT

# crest factor (max_volume - mean_volume, dB) of a file
crest() {
  "$FFMPEG" -hide_banner -nostats -i "$1" -af volumedetect -f null - 2>&1 |
    awk '/mean_volume/{m=$5}/max_volume/{x=$5}END{printf "%.1f %.1f\n", x-m, x}'
}

# Peaky signal: quiet tone with 5 ms near-full-scale bursts (crest ~30 dB).
"$FFMPEG" -y -hide_banner -loglevel error -f lavfi \
  -i "aevalsrc='sin(2*PI*440*t)*if(lt(mod(t,3),0.005),0.9,0.02)':d=30:s=48000" "$T/in.wav"
scripts/prepare_audio.sh "$T/in.wav" "$T/out.wav" >/dev/null 2>&1

read -r CIN _ < <(crest "$T/in.wav")
read -r COUT MAXOUT < <(crest "$T/out.wav")
python3 -c "import sys; d=abs($COUT-$CIN); sys.exit(0 if d < 1.0 else 'FAIL: crest changed by %.1f dB (compression)' % d)"
python3 -c "import sys; sys.exit(0 if $MAXOUT <= -1.0 else 'FAIL: peak $MAXOUT dB above -1.0')"
echo "ok: static gain preserves crest factor and keeps peak <= -1.0 dB"

RATE=$("$FFPROBE" -v error -show_entries stream=sample_rate -of csv=p=0 "$T/out.wav")
[ "$RATE" = "44100" ] || { echo "FAIL: sample rate $RATE"; exit 1; }
echo "ok: output is 44.1 kHz"

"$FFMPEG" -y -hide_banner -loglevel error -f lavfi -i "anullsrc=r=48000:cl=mono" -t 2 "$T/silent.wav"
if scripts/prepare_audio.sh "$T/silent.wav" "$T/silent.out.wav" >"$T/log" 2>&1; then
  echo "FAIL: silent input accepted"; exit 1
fi
grep -q "prepare_audio: input is silent" "$T/log" || { echo "FAIL: no silent-input message"; cat "$T/log"; exit 1; }
echo "ok: silent input is rejected"
