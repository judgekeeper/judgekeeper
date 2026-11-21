#!/bin/bash
# Run judgekeeper itself on every pair the report counts.
#
#   bash run_judgekeeper.sh <rounds-folder> <scratch-folder>
#
# <rounds-folder> is $NOISE_WORK/rounds (math/, truthfulness/, multiple-choice/ with the graded
# CSV runs the run_*.py scripts write). judgekeeper must be installed (pip install judgekeeper).
# Each pair runs in its own empty folder, so no earlier baseline carries over, with
# `CI=true judgekeeper now.csv --before before.csv --no-browser`. CI=true makes judgekeeper open
# no marking page and leave no page running, so there is no link in the output. The output of each pair goes to
# judgekeeper-output/<set>/<before>__<now>.txt, with "exit N" on its last line, and
# judgekeeper-output/SUMMARY.txt lists them.
set -u
ROUNDS="$(cd "$1" && pwd)"; WORK="$2"
OUT="$(cd "$(dirname "$0")/.." && pwd)/judgekeeper-output"
mkdir -p "$OUT" "$WORK"
n=0

pair() {  # set before now
    mkdir -p "$OUT/$1"
    n=$((n + 1))
    dir="$WORK/pair-$n"; mkdir -p "$dir"
    cp "$ROUNDS/$1/$2.csv" "$dir/before.csv"
    cp "$ROUNDS/$1/$3.csv" "$dir/now.csv"
    f="$OUT/$1/$2__$3.txt"
    (cd "$dir" && CI=true judgekeeper now.csv --before before.csv --no-browser </dev/null > "$f" 2>&1
     echo "exit $?" >> "$f")
    # Safety: if a page was started anyway, stop it.
    [ -f "$dir/.judgekeeper/page.json" ] && (cd "$dir" && judgekeeper --stop >/dev/null 2>&1)
}

for set in math truthfulness multiple-choice; do
    for i in 1 2 3 4; do
        for j in $(seq $((i + 1)) 5); do pair "$set" "same-$i" "same-$j"; done
    done
done
for i in 1 2 3 4 5; do
    for c in worse small-a-1 older-ai-1; do pair math "same-$i" "$c"; done
    for c in worse-2 small-a-1 older-ai-1; do pair truthfulness "same-$i" "$c"; done
    for c in worse older-ai-1; do pair multiple-choice "same-$i" "$c"; done
done
pair truthfulness same-1 same-1-regrade

echo "pairs run: $n"
for f in "$OUT"/*/*.txt; do
    printf '%s | %s | %s | %s\n' "${f#$OUT/}" "$(grep -m1 '^On the ' "$f")" \
        "$(grep -m1 -E "^(Your change|Can't tell)" "$f")" "$(tail -1 "$f")"
done > "$OUT/SUMMARY.txt"
cat "$OUT/SUMMARY.txt"
