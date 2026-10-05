#!/usr/bin/env bash
# Reproduce docs/examples/llmbar-haiku/: LLMBar (Natural + Adversarial), claude-haiku-4-5-20251001,
# temperature 0, 3 runs, AB and BA. Needs ANTHROPIC_API_KEY and `pip install -e ".[anthropic]"`.
#
# Optional:
#   API_KEY_ENV  name of the variable holding the key (default ANTHROPIC_API_KEY); forwarded
#                to `judgekeeper judge --api-key-env`. The key itself is never passed or printed.
#   BASE_URL     endpoint forwarded to `judgekeeper judge --base-url` (overrides
#                ANTHROPIC_BASE_URL), e.g. https://api.anthropic.com when a proxy is configured.
set -euo pipefail

API_KEY_ENV="${API_KEY_ENV:-ANTHROPIC_API_KEY}"
: "${!API_KEY_ENV:?$API_KEY_ENV must be set}"

judge_flags=(--api-key-env "$API_KEY_ENV")
if [[ -n "${BASE_URL:-}" ]]; then
  judge_flags+=(--base-url "$BASE_URL")
fi

python -m judgekeeper.datasets.llmbar --out anchors/llmbar.jsonl
judgekeeper freeze anchors/llmbar.jsonl
judgekeeper judge anchors/llmbar.jsonl --runner anthropic --model claude-haiku-4-5-20251001 \
  --prompt prompts/pairwise.md --temperature 0 --runs 3 --out runs/llmbar-haiku/ \
  "${judge_flags[@]}"
judgekeeper validate anchors/llmbar.jsonl runs/llmbar-haiku/ --out docs/examples/llmbar-haiku/
