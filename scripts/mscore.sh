#!/bin/bash
# Wrapper around the MuseScore 4 CLI.
#
# 1. A stable, space-free command path (scripts/mscore.sh ...) so a single
#    permission rule — Bash(scripts/mscore.sh *) — covers every MuseScore call.
#    The real binary path contains a space. Override it with the MSCORE env var.
#
# 2. Reliable conversions. MuseScore often aborts (exit 134) on shutdown AFTER
#    writing its output, and occasionally fails outright and works on a retry.
#    So for a conversion (-o <out>) the wrapper judges by the file, not the exit
#    code: MuseScore writes to a temporary sibling of <out>, up to 3 attempts;
#    a non-empty result is moved onto <out> and the wrapper exits 0. If no
#    attempt produced a file, <out> is left untouched and the wrapper exits
#    non-zero.
#
# Without -o, arguments and exit code pass through unchanged.
MSCORE_BIN="${MSCORE:-/Applications/MuseScore 4.app/Contents/MacOS/mscore}"

out=""
args=("$@")
for ((i = 0; i < ${#args[@]}; i++)); do
  if [ "${args[i]}" = "-o" ] && [ $((i + 1)) -lt ${#args[@]} ]; then
    out="${args[i + 1]}"
    out_index=$((i + 1))
  fi
done

if [ -z "$out" ]; then
  exec "$MSCORE_BIN" "$@"
fi

# same directory and extension as <out>: MuseScore picks the format by extension
tmp="${out%.*}.mscore-tmp.$$.${out##*.}"
args[out_index]="$tmp"
code=1
for attempt in 1 2 3; do
  rm -f "$tmp"
  "$MSCORE_BIN" "${args[@]}"
  code=$?
  if [ -s "$tmp" ]; then
    mv -f "$tmp" "$out"
    exit 0
  fi
done
rm -f "$tmp"
[ "$code" -ne 0 ] || code=1
exit "$code"
