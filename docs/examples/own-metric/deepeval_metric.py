"""Worked example B: the same refund rule as a DeepEval GEval metric, judged by a live model.

The metric's criteria text is the rule part of rule.md (what is checked, pass, fail, examples,
edge cases) without the placeholders and the `Verdict:` line. The same 60 items and labels as
example A (synthetic data; labels by construction; an illustration, not a benchmark).

Needs DeepEval and the Anthropic SDK, which are not judgekeeper dependencies:

    pip install deepeval anthropic

The key comes from JUDGEKEEPER_ANTHROPIC_KEY and the endpoint is https://api.anthropic.com;
both are passed to DeepEval's model class explicitly, so ANTHROPIC_API_KEY and
ANTHROPIC_BASE_URL in the environment are not used. The key is never written to a file or
printed. Run from this folder:

    python deepeval_metric.py

It judges the 60 items 3 times with claude-haiku-4-5-20251001 at temperature 0, writes one
`deepeval/results/test_run_*.json` per run (DeepEval's own format), then runs

    judgekeeper import deepeval deepeval/results/ --metric "Refund policy [GEval]" \\
      --labels labels.csv --out deepeval/

which writes deepeval/report.json and deepeval/report.html.
"""

from __future__ import annotations

import csv
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "deepeval" / "results"
MODEL = "claude-haiku-4-5-20251001"
ENDPOINT = "https://api.anthropic.com"
KEY_VAR = "JUDGEKEEPER_ANTHROPIC_KEY"
METRIC_NAME = "Refund policy"
RUNS = 3

os.environ.setdefault("DEEPEVAL_TELEMETRY_OPT_OUT", "YES")


def criteria() -> str:
    """The rule part of rule.md: everything before the `# Instruction` placeholder section."""
    sys.path.insert(0, str(HERE.parent.parent.parent / "src"))
    from judgekeeper.prompts import load_prompt

    template = load_prompt(HERE / "rule.md").template
    return template.split("\n# Instruction\n", 1)[0].strip()


def items() -> list[dict]:
    with (HERE / "items.csv").open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def main() -> int:
    rows = items()
    print(f"{len(rows) * RUNS} judge calls ({len(rows)} items x {RUNS} runs), plus one call "
          f"to generate the evaluation steps; model {MODEL} at temperature 0 via {ENDPOINT}")
    key = os.environ.get(KEY_VAR)
    if not key:
        print(f"error: {KEY_VAR} is not set; nothing was run", file=sys.stderr)
        return 2
    try:
        from deepeval import evaluate
        from deepeval.evaluate.configs import AsyncConfig, DisplayConfig
        from deepeval.metrics import GEval
        from deepeval.models import AnthropicModel
        from deepeval.test_case import LLMTestCase
    except ImportError as e:
        print(f"error: {e}; run: pip install deepeval anthropic", file=sys.stderr)
        return 2
    try:
        from deepeval.test_case import SingleTurnParams as Params
    except ImportError:  # DeepEval before 4.2
        from deepeval.test_case import LLMTestCaseParams as Params

    # The Anthropic SDK dropped the `temperature` keyword in 1.x; the API still takes it in
    # the request body, and `extra_body` works on every SDK version.
    model = AnthropicModel(model=MODEL, api_key=key, base_url=ENDPOINT,
                           generation_kwargs={"extra_body": {"temperature": 0.0}})
    metric = GEval(name=METRIC_NAME, criteria=criteria(), threshold=0.5, model=model,
                   evaluation_params=[Params.INPUT, Params.ACTUAL_OUTPUT],
                   async_mode=False)
    cases = [LLMTestCase(name=r["id"], input=r["input"], actual_output=r["output"])
             for r in rows]

    shutil.rmtree(RESULTS, ignore_errors=True)
    RESULTS.mkdir(parents=True)
    os.chdir(HERE)  # DeepEval also writes .deepeval/ in the working directory; removed below
    for run in range(1, RUNS + 1):
        if run > 1:
            time.sleep(1.1)  # the file name's timestamp has one-second resolution
        print(f"run {run} of {RUNS}")
        evaluate(cases, [metric], async_config=AsyncConfig(run_async=False),
                 display_config=DisplayConfig(show_indicator=False, print_results=False,
                                              results_folder=str(RESULTS)))
    shutil.rmtree(HERE / ".deepeval", ignore_errors=True)
    (RESULTS / ".test_run.lock").unlink(missing_ok=True)
    written = sorted(RESULTS.glob("test_run_*.json"))
    print(f"wrote {len(written)} run files under {RESULTS.relative_to(HERE)}")
    if len(written) != RUNS:
        print(f"error: expected {RUNS} run files", file=sys.stderr)
        return 1

    command = [sys.executable, "-m", "judgekeeper.cli", "import", "deepeval",
               str(RESULTS.relative_to(HERE)) + "/", "--metric", f"{METRIC_NAME} [GEval]",
               "--labels", "labels.csv", "--out", "deepeval/"]
    print("judgekeeper " + " ".join(command[3:]))
    env = {k: v for k, v in os.environ.items() if k != KEY_VAR}
    return subprocess.run(command, cwd=HERE, env=env, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
