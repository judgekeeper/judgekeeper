#!/bin/sh
# Regenerate results.json with the real promptfoo CLI. No API call: the answerer and the
# llm-rubric grader are local `exec:` Python scripts.
#   cd tests/fixtures/promptfoo/real && sh make.sh
set -e
rm -f grader-state.json results.json
# promptfoo exits 100 when any test fails, as some do here by design.
PROMPTFOO_DISABLE_TELEMETRY=1 PROMPTFOO_DISABLE_UPDATE=1 \
  npx --yes promptfoo@0.123.1 eval -c promptfooconfig.yaml --repeat 3 -j 1 --no-cache \
  --no-table --no-write -o results.json || test $? -eq 100
rm -f grader-state.json
