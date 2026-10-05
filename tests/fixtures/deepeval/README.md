# DeepEval fixture

`results/test_run_<timestamp>.json` are shaped like the files DeepEval writes to a
`results_folder` (or `DEEPEVAL_RESULTS_FOLDER`), one per run. `labels.csv` holds the human
labels, since DeepEval stores none. Made by `../make_framework_fixtures.py`; no DeepEval run
and no API call.

Where the shape comes from (DeepEval source, checked on 2026-10-01):

- `deepeval/test_run/test_run.py` (`TestRun`, aliases `testCases`, `conversationalTestCases`)
  and `deepeval/evaluate/local_store.py` (`test_run_<YYYYMMDD_HHMMSS>.json`, written with
  `model_dump(by_alias=True, exclude_none=True)`; `.deepeval/.latest_run_full.json` is the
  rolling snapshot).
- `deepeval/test_run/api.py` (`LLMApiTestCase`: `name`, `input`, `actualOutput`, ...) and
  `deepeval/tracing/api.py` (`MetricData`: `name`, `threshold`, `success`, `score`, `reason`,
  `evaluationModel`, `verboseLogs`, ...).
- `deepeval/test_case/api.py`: `name` defaults to `test_case_{order}`.
- `deepeval/metrics/g_eval/g_eval.py` and `deepeval/metrics/utils/verbose.py`: GEval's
  `verboseLogs` is "Criteria:", "Evaluation Steps:", "Rubric:" and "Score:" joined by
  `" \n \n"` (the "Reason:" step is printed, not stored).

Traps it exercises: positional default names; three runs as three files; two metrics.
