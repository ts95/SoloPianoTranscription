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
# 3. House layout for every new score. When a .musicxml is converted to a .mscz:
#    - system/page breaks in the MusicXML are ignored (a MuseScore export records
#      the layout it had; re-importing them pins old page turns in place and
#      strands near-empty pages once anything changes the spacing), and
#    - scripts/score_style.mss is applied (a constant gap between systems, rows
#      gravitating to the top of the page) unless the call passes its own -S.
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

clean=""
if [[ "$out" == *.mscz ]]; then
  has_style=0
  in_index=""
  for ((i = 0; i < ${#args[@]}; i++)); do
    case "${args[i]}" in
      -S|--style) has_style=1 ;;
      *.musicxml) [ "$i" -ne "$out_index" ] && in_index=$i ;;
    esac
  done
  if [ -n "$in_index" ]; then
    clean="${TMPDIR:-/tmp}/mscore-in.$$.musicxml"
    sed -E 's/ new-(system|page)="yes"//g' "${args[in_index]}" > "$clean"
    args[in_index]="$clean"
    if [ "$has_style" -eq 0 ]; then
      args=(-S "$(dirname "$0")/score_style.mss" "${args[@]}")
    fi
  fi
fi
code=1
for attempt in 1 2 3; do
  rm -f "$tmp"
  "$MSCORE_BIN" "${args[@]}"
  code=$?
  if [ -s "$tmp" ]; then
    mv -f "$tmp" "$out"
    rm -f "$clean"
    exit 0
  fi
  # image exports (png/svg) write one file per page: <name>-1.png, <name>-2.png, ...
  pages=("${tmp%.*}"-[0-9]*."${tmp##*.}")
  if [ -s "${pages[0]}" ]; then
    for page in "${pages[@]}"; do
      mv -f "$page" "${out%.*}${page#"${tmp%.*}"}"
    done
    rm -f "$clean"
    exit 0
  fi
done
rm -f "$tmp" "$clean"
[ "$code" -ne 0 ] || code=1
exit "$code"
