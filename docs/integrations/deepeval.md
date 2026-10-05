# DeepEval

judgekeeper reads the JSON files DeepEval already writes. Your test code does not change.

## Produce the files

DeepEval has no `--output-file` flag. It writes results in two places:

- `.deepeval/.latest_run_full.json`, overwritten by every run;
- one `test_run_<YYYYMMDD_HHMMSS>.json` per run in a results folder, when you set one:

  ```
  export DEEPEVAL_RESULTS_FOLDER=deepeval-results
  deepeval test run test_judge.py      # run it three times, or call evaluate() three times
  ```

  or in Python, `evaluate(..., display_config=DisplayConfig(results_folder="deepeval-results"))`.

Use the results folder: every file is one run, so three runs measure the judge's run-to-run noise. `.latest_run_full.json` only ever holds the last run.

## Import them

```
judgekeeper import deepeval deepeval-results/ --metric "Correctness [GEval]" --labels labels.csv --out reports/correctness/
```

A path can be the folder, a glob (`"deepeval-results/test_run_*.json"`) or files; a folder with no `test_run_*.json` falls back to `.latest_run_full.json`. `--metric` is the metric's `name` as it appears in `metricsData` (GEval metrics are named `"<name> [GEval]"`). The verdict is the metric's `success`; with `--pass-if "score>=0.7"` judgekeeper applies that rule to `score` instead. The threshold DeepEval used is kept in the report's `source.threshold`.

## Human labels

DeepEval stores no human verdict (`expectedOutput` is a reference answer, not a pass/fail label), so labels come from `--labels`: a CSV or JSONL with an `id` column and a `human_label` column. To get the ids right, make the sheet with `judgekeeper template items.jsonl -o labels.csv` from your test cases' `input` and `output`, or name your test cases (below) and use those names.

## Traps

- **Default test case names are positional.** Without `LLMTestCase(name=...)`, DeepEval names cases `test_case_0`, `test_case_1`, ... by order, which is not an id. judgekeeper then derives each id from the case's `input` and `actual_output` and warns. Derived ids only line up across runs if the outputs are the same in every run; name your test cases for stable ids.
- **The rubric lives in `verboseLogs`.** For GEval, the prompt hash covers the `Criteria:`, `Evaluation Steps:` and `Rubric:` parts of `verboseLogs`, not the per-item `Score:` line. Metrics without those parts get an unknown prompt hash.
- **Temperature is not written.** The judge model comes from `evaluationModel`; DeepEval does not store the temperature, so it is recorded as unknown. The provider comes from the suffix DeepEval adds to the model's name (`claude-sonnet-4-6 (Anthropic)`, `my-deployment (Azure)`, `gemini-... (Gemini)`); a bare name is OpenAI, since DeepEval builds an OpenAI model for any plain string.
- **`DEEPEVAL_LOCAL_STORE=sqlite`** writes `deepeval.db` and no JSON. Leave it unset.
