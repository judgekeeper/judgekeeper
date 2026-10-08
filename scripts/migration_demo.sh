#!/usr/bin/env bash
# Judge migration demo on LLMBar (Natural + Adversarial): judge the anchor set with an old and
# a new model (3 runs each, AB and BA, temperature 0), then run `judgekeeper migrate`.
#
#   RUNNER=anthropic OLD_MODEL=<old model id> NEW_MODEL=<new model id> scripts/migration_demo.sh
#
# There are no default model ids on purpose: take both from the provider's current models and
# deprecations pages. Needs the runner's key (ANTHROPIC_API_KEY or OPENAI_API_KEY, or the
# variable named in API_KEY_ENV) and `pip install -e ".[anthropic]"` or `".[openai]"`.
# Optional: PROMPT (default prompts/pairwise.md), OUT (default
# docs/examples/migration-<old>-to-<new>/), BASE_URL, API_KEY_ENV.
set -euo pipefail

: "${RUNNER:?set RUNNER to anthropic or openai}"
: "${OLD_MODEL:?set OLD_MODEL to the judge model id you are migrating from}"
: "${NEW_MODEL:?set NEW_MODEL to the judge model id you are migrating to}"
case "$RUNNER" in
  anthropic) default_key=ANTHROPIC_API_KEY ;;
  openai) default_key=OPENAI_API_KEY ;;
  *) echo "RUNNER must be anthropic or openai, got $RUNNER" >&2; exit 2 ;;
esac
key_env="${API_KEY_ENV:-$default_key}"
if [ -z "${BASE_URL:-}" ] && [ -z "${!key_env:-}" ]; then
  echo "$key_env must be set" >&2
  exit 2
fi

PROMPT="${PROMPT:-prompts/pairwise.md}"
safe() { printf '%s' "$1" | tr -c 'A-Za-z0-9._-' '-'; }
OUT="${OUT:-docs/examples/migration-$(safe "$OLD_MODEL")-to-$(safe "$NEW_MODEL")}"

extra=()
if [ -n "${BASE_URL:-}" ]; then extra+=(--base-url "$BASE_URL"); fi
if [ -n "${API_KEY_ENV:-}" ]; then extra+=(--api-key-env "$API_KEY_ENV"); fi

python -m judgekeeper.datasets.llmbar --out anchors/llmbar.jsonl
rm -f anchors/llmbar.manifest.json  # a fresh download: the first judge call seals it again
for model in "$OLD_MODEL" "$NEW_MODEL"; do
  runs="runs/llmbar-$(safe "$model")"
  rm -rf "$runs"
  judgekeeper judge anchors/llmbar.jsonl --runner "$RUNNER" --model "$model" \
    --prompt "$PROMPT" --temperature 0 --runs 3 --out "$runs/" "${extra[@]}"
done
judgekeeper migrate anchors/llmbar.jsonl "runs/llmbar-$(safe "$OLD_MODEL")/" \
  "runs/llmbar-$(safe "$NEW_MODEL")/" --out "$OUT/"
