# DeepEval

judgekeeper reads the JSON files DeepEval already writes. Your test code does not change.

Tested with DeepEval 3.9.9 to 4.2.8. With an older DeepEval, reading, marking and the review work; asking your judge again and trying a new judge need DeepEval 3.9.9 or newer.

## Produce the files

DeepEval has no `--output-file` flag. It writes results in two places:

- `.deepeval/.latest_run_full.json`, overwritten by every run;
- one `test_run_<YYYYMMDD_HHMMSS>.json` per run in a results folder, when you set one:

  ```
  export DEEPEVAL_RESULTS_FOLDER=deepeval-results
  deepeval test run test_judge.py
  ```

  or in Python, `evaluate(..., display_config=DisplayConfig(results_folder="deepeval-results"))`.

`.latest_run_full.json` only ever holds the last run.

## Read them

```
judgekeeper start --metric "Correctness [GEval]"
```

`judgekeeper start` reads the newest `test_run_*.json`, else `.latest_run_full.json`. `--metric` is the metric's `name` as it appears in `metricsData` (GEval metrics are named `"<name> [GEval]"`). The verdict is the metric's `success`; with `--pass-if "score>=0.7"` judgekeeper applies that rule to `score` instead.

## Traps

- **Default test case names are positional.** Without `LLMTestCase(name=...)`, DeepEval names cases `test_case_0`, `test_case_1`, ... by order, which is not an id. judgekeeper then derives each id from the case's `input` and `actual_output` and warns. Derived ids only line up across runs if the outputs are the same in every run; name your test cases for stable ids.
- **The rubric lives in `verboseLogs`.** For GEval, the prompt hash covers the `Criteria:`, `Evaluation Steps:` and `Rubric:` parts of `verboseLogs`, not the per-item `Score:` line. Metrics without those parts get an unknown prompt hash.
- **Temperature is not written.** The judge model comes from `evaluationModel`; DeepEval does not store the temperature, so it is recorded as unknown. The provider comes from the suffix DeepEval adds to the model's name (`claude-sonnet-4-6 (Anthropic)`, `my-deployment (Azure)`, `gemini-... (Gemini)`); a bare name is OpenAI, since DeepEval builds an OpenAI model for any plain string.
- **`DEEPEVAL_LOCAL_STORE=sqlite`** writes `deepeval.db` and no JSON. Leave it unset.
