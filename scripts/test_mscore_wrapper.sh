#!/bin/bash
# Regression test: scripts/mscore.sh retries, trusts the file not the exit code,
# and never destroys an existing output on failure.
# Run: bash scripts/test_mscore_wrapper.sh
set -uo pipefail
T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT

fake() { printf '#!/bin/sh\n%s\n' "$2" > "$T/$1"; chmod +x "$T/$1"; }
out_arg='while [ "$1" != "-o" ]; do shift; done; out="$2"'

# 1. writes the file, then crashes with 134 (MuseScore's shutdown abort)
fake crashy "$out_arg"'; printf x > "$out"; exit 134'
MSCORE="$T/crashy" scripts/mscore.sh in.mscz -o "$T/a.pdf"; code=$?
[ "$code" -eq 0 ] && [ -s "$T/a.pdf" ] || { echo "FAIL: exit 134 after a good write must succeed (got $code)"; exit 1; }
echo "ok: a write followed by exit 134 counts as success"

# 2. fails twice, succeeds on the third attempt
fake flaky "$out_arg"'; n=$(cat "'"$T"'/count" 2>/dev/null || echo 0); n=$((n+1)); echo $n > "'"$T"'/count"; [ "$n" -ge 3 ] && printf x > "$out"; exit 40'
MSCORE="$T/flaky" scripts/mscore.sh in.mscz -o "$T/b.pdf"; code=$?
[ "$code" -eq 0 ] && [ -s "$T/b.pdf" ] && [ "$(cat "$T/count")" = "3" ] || { echo "FAIL: third attempt should succeed (code $code, attempts $(cat "$T/count"))"; exit 1; }
echo "ok: retries up to three times"

# 3. never writes: non-zero exit, and the previous output survives
fake dead 'exit 0'
printf old > "$T/c.pdf"
MSCORE="$T/dead" scripts/mscore.sh in.mscz -o "$T/c.pdf"; code=$?
[ "$code" -ne 0 ] && [ "$(cat "$T/c.pdf")" = "old" ] || { echo "FAIL: no file written must fail and keep the old output (code $code)"; exit 1; }
[ -z "$(ls "$T" | grep mscore-tmp)" ] || { echo "FAIL: temp file left behind"; exit 1; }
echo "ok: exit 0 without a file is a failure, and the old output is kept"

# 4. without -o: plain pass-through of arguments and exit code
fake echoer 'echo "$@"; exit 7'
got=$(MSCORE="$T/echoer" scripts/mscore.sh --version "a b"); code=$?
[ "$code" -eq 7 ] && [ "$got" = "--version a b" ] || { echo "FAIL: pass-through (code $code, got '$got')"; exit 1; }
echo "ok: without -o the call passes straight through"

# 5. .musicxml -> .mscz: stale breaks are stripped from what MuseScore reads, the house
#    style is applied, and the source file is left alone
fake rec 'echo "$@" > "'"$T"'/args"; for a in "$@"; do case "$a" in *.musicxml) cp "$a" "'"$T"'/seen";; esac; done; '"$out_arg"'; printf x > "$out"; exit 0'
printf '<measure><print new-system="yes"/></measure><measure><print new-page="yes" x="1"/></measure>' > "$T/in.musicxml"
cp "$T/in.musicxml" "$T/in.orig"
MSCORE="$T/rec" scripts/mscore.sh "$T/in.musicxml" -o "$T/e.mscz"; code=$?
[ "$code" -eq 0 ] && grep -q -- "-S .*score_style.mss" "$T/args" || { echo "FAIL: house style not applied ($(cat "$T/args"))"; exit 1; }
! grep -q "new-system\|new-page" "$T/seen" && grep -q 'x="1"' "$T/seen" || { echo "FAIL: breaks not stripped: $(cat "$T/seen")"; exit 1; }
cmp -s "$T/in.musicxml" "$T/in.orig" || { echo "FAIL: source MusicXML was modified"; exit 1; }
echo "ok: importing MusicXML ignores its old breaks and applies the house style"

# 6. an explicit -S wins; other conversions get no style
MSCORE="$T/rec" scripts/mscore.sh -S mine.mss "$T/in.musicxml" -o "$T/f.mscz"
[ "$(grep -o -- "-S" "$T/args" | wc -l | tr -d ' ')" = "1" ] && grep -q "mine.mss" "$T/args" || { echo "FAIL: explicit -S not respected ($(cat "$T/args"))"; exit 1; }
MSCORE="$T/rec" scripts/mscore.sh "$T/e.mscz" -o "$T/g.pdf"
! grep -q -- "-S" "$T/args" || { echo "FAIL: style added to a non-import conversion"; exit 1; }
echo "ok: an explicit -S is respected, and exports are untouched"
