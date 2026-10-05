"""Write results/test_run_*.json with three real `deepeval.evaluate` runs. No API call.

Run from this folder with deepeval installed: python make_runs.py

The metric is a plain BaseMetric (no model): it passes a test case when the case's name is in
PASSES for the current run. DEEPEVAL_RESULTS_FOLDER makes DeepEval keep one
test_run_<timestamp>.json per run; the runs are a second apart because the timestamp has
one-second resolution.
"""

import os
import shutil
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"
os.environ["DEEPEVAL_RESULTS_FOLDER"] = str(RESULTS)
os.environ["DEEPEVAL_TELEMETRY_OPT_OUT"] = "YES"
os.chdir(HERE)  # DeepEval also writes .deepeval/ in the working directory; removed below

from deepeval import evaluate
from deepeval.evaluate.configs import AsyncConfig, DisplayConfig
from deepeval.metrics import BaseMetric
from deepeval.test_case import LLMTestCase

# Test cases the metric passes, per run.
PASSES = {1: {"c0", "c1", "c3"}, 2: {"c0", "c1", "c2", "c3"}, 3: {"c0", "c1", "c2"}}


class ListedPasses(BaseMetric):
    """Passes the test cases named in PASSES[run]."""

    def __init__(self, run: int):
        self.run = run
        self.threshold = 0.5
        self.async_mode = False

    def measure(self, test_case: LLMTestCase, *args, **kwargs) -> float:
        passed = test_case.name in PASSES[self.run]
        self.score = 1.0 if passed else 0.0
        self.success = passed
        self.reason = f"run {self.run}: {'listed' if passed else 'not listed'}"
        return self.score

    async def a_measure(self, test_case: LLMTestCase, *args, **kwargs) -> float:
        return self.measure(test_case)

    def is_successful(self) -> bool:
        return bool(self.success)

    @property
    def __name__(self):
        return "Listed Passes"


def main() -> None:
    shutil.rmtree(RESULTS, ignore_errors=True)
    cases = [LLMTestCase(name=f"c{i}", input=f"What is {i} + {i}?", actual_output=f"{2 * i}")
             for i in range(6)]
    for run in (1, 2, 3):
        if run > 1:
            time.sleep(1.1)
        evaluate(cases, [ListedPasses(run)], async_config=AsyncConfig(run_async=False),
                 display_config=DisplayConfig(show_indicator=False, print_results=False))
    shutil.rmtree(HERE / ".deepeval", ignore_errors=True)
    (RESULTS / ".test_run.lock").unlink(missing_ok=True)


if __name__ == "__main__":
    main()
