# Eval tools

How judgekeeper finds and reads the results each eval tool saves. Commands, flags, files and exit codes are in the [reference](reference.md). judgekeeper only reads these files and never changes them. Most of this page, it also says in the terminal when it happens.

## How it looks

- Inside your project folder, four folders deep (a CSV or JSONL table: two). A results file outside it is read only when you name it.
- It skips `.git`, `node_modules`, virtual environments (any folder holding `pyvenv.cfg`) and hidden folders, except `.deepeval` and `.judgekeeper/records/`. It does not follow symbolic links. It stops after 5,000 files or 2 seconds, and says so.
- A results file over 200 MB is listed, not read, unless you name it and say yes.
- When it finds nothing, it names the results-like files it left out (too deep, links, not UTF-8, Excel workbooks) with the command that reads each.

## Grading answers again

judgekeeper never runs your eval tool and never asks your LLM-as-a-judge itself. To test a new rule, `judgekeeper fix` writes every answer you marked in `.judgekeeper/fix/marked-answers.csv`. You grade those answers again with your new rule in your eval tool, save the results, and run `judgekeeper fix <new results file>`. Each tool's part below says how. To re-check, `judgekeeper check` reads the results your eval saves next, and finds the answers you marked in them by their exact text.

## How failed calls are spotted

Before you mark anything, judgekeeper checks the grades with no AI call.

| Eval tool | The call failed | The reply could not be read |
|---|---|---|
| promptfoo | `graderError`, or in older files a reason such as "API error:" | "Could not extract JSON" or "Error parsing output" |
| DeepEval | `error`, or no score with `success` false | |
| Inspect AI | `grader_failed`, or a sample that errored before it was scored | "Grade not found in model output" |
| MLflow | `feedback.error` | |

A DeepEval metric with nothing to check (an empty `Verdicts:` list) scores 1.0 and is left out too. **The reason says the opposite** when it starts with PASS, PASSED, FAIL or FAILED, when its last `verdict:`, `grade:`, `result:`, `decision:`, `final verdict:` or `final answer:` says pass, fail, correct or incorrect, or with Inspect AI's `GRADE: C` or `GRADE: I`. No other words count. This check is skipped for scores with a pass mark.

## promptfoo

```
promptfoo eval -o results.json
judgekeeper
```

Tested with promptfoo 0.123 and 0.124, the versions in tests/fixtures. It reads JSON files from `promptfoo eval -o` or `promptfoo export eval`. When results are only in promptfoo's database, it prints how to save them: `promptfoo eval -o promptfoo-results.json`, or `promptfoo list evals` and `promptfoo export eval <id> -o promptfoo-results.json`. It runs neither. `--metric` is an assertion's `metric:`, else its type (`llm-rubric`, `g-eval`, `factuality` and the other model-graded types); code assertions are left out. The rule `fix` shows is the assertion's `value`, unless it differs per test. Ids are the test's `description` when each is unique, else a hash of its vars.

To grade the same answers again, use `marked-answers.csv` as your tests with the `echo` provider and your new rule, and save with `-o`.

**Traps.**

- **A human rating overrides the row's `success` and `pass`.** So the grade is read from the model-graded part itself.
- **`--repeat` rows carry no repeat index.** Repeats are numbered in file order; repeats with the same grade count once.
- **The default grader is not recorded.** With no `provider` set, the model is unknown. Set `defaultTest.options.provider` (with `config.temperature`, or the temperature is unknown too). A grader set with `--grader` has an unknown provider.
- **Cached grades** may be old replies; it says how many.
- **No grading details.** With an empty `gradingResult` and one llm-rubric per test, each row's `success` is the grade, with a note. Otherwise turn `PROMPTFOO_STRIP_GRADING_RESULT` off.
- **The model you test failed.** The row has no answer; it is left out, not counted as a fail.

## DeepEval

```
export DEEPEVAL_RESULTS_FOLDER=deepeval-results
deepeval test run test_judge.py
judgekeeper --metric "Correctness [GEval]"
```

Tested with DeepEval 4.2, the version in tests/fixtures. It reads the newest `test_run_<date>.json` in your results folder (`DEEPEVAL_RESULTS_FOLDER`, or `DisplayConfig(results_folder=...)` in `evaluate()`), else `.deepeval/.latest_run_full.json`, which every run overwrites. Results are saved only by `deepeval test run` or `evaluate()`: calling a metric's `measure()` directly saves nothing. `--metric` is the metric's `name` (GEval: `"<name> [GEval]"`). The grade is `success`, or `score` with `--pass-if`. The rule `fix` shows is a GEval's evaluation steps or criteria. To grade the same answers again, build test cases from `marked-answers.csv` and run the metric. The version comes from your project's pin (`uv.lock`, `poetry.lock`, `pyproject.toml` or `requirements*.txt`).

**Traps.**

- **Default test case names are positional.** Without `LLMTestCase(name=...)`, ids are made from the input and answer, with a warning.
- **The temperature is not written.** The provider comes from the model name's suffix (`(Anthropic)`); a bare name is OpenAI.
- **An empty answer** is saved as an error: no real decision.
- **`DEEPEVAL_LOCAL_STORE=sqlite`** writes no JSON. Leave it unset.

## Inspect AI

```
inspect eval task.py
judgekeeper --metric model_graded_qa
```

Tested with Inspect AI 0.3.273, the version in tests/fixtures. Logs from 0.3.2 and 0.3.204 are tested too. Logs are in `./logs` or `INSPECT_LOG_DIR`. `.eval` logs need `pip install "judgekeeper[inspect]"` in your project's environment; else use `--log-format json` or `inspect log dump`. Logs in several folders are never read as one: it asks which and keeps the answer in `judgekeeper.toml`. `--metric` is the scorer's name under `samples[].scores`. Ids are `samples[].id`, repeats `samples[].epoch`. The rule `fix` shows is the scorer's instructions. To grade the same answers again, `inspect score <log> --scorer <name> --action overwrite --output-file logs/new.eval` with your scorer's new rule grades the log again without new answers: `--action overwrite` keeps the new grades under your scorer's name, and `--output-file` writes them to a new log in your log folder (`logs/` here), so yours stays as it was and `check` finds the new one there. Then run `judgekeeper fix logs/new.eval`.

**Traps.**

- **Score values.** `C` is pass, `I` is fail. `P` (partial credit) has no default: use `--label-map P=fail` (or `P=pass`). Numbers need `--pass-if`.
- **A dict value** (`{"accuracy": "C", "tone": "I"}`) is one LLM-as-a-judge per key, like `rubric.tone`.
- **Code scorers** (`match`, `includes`, `exact`, `pattern`, `f1`, `answer`) are left out, and so is a sample that failed before scoring.
- **The grading template.** The prompt hash covers the `template` and `instructions` options, not Inspect's default template. Set `template` to track it.
- **`--no-log-samples`** logs cannot be read.
- **Very big parts.** A `.eval` log is too big for judgekeeper to read when its `header.json` would unpack to more than 50 MB, its summaries and reductions to more than 500 MB together, one sample to more than 200 MB, or all its samples to more than 4 GB together. So is one with a part holding more than 2,000,000 values (1,000 more per sample for the summaries and reductions), more than 200,000,000 values in all its parts, samples holding more than 10 values for each byte they pack to, a sample over 1 MB that unpacks to more than 200 times its packed size, or one text in a sample longer than 8 MB. The message says which limit it passed. A log with a part nested more than 500 levels deep is not read, nor one whose parts share bytes, give a part's size two ways or can be named two ways. judgekeeper counts what each part really unpacks to, how deep it nests, how many values it holds and how long its texts are, before Inspect AI reads the log, and keeps none of it. It then reads only the samples the log holds, each once, a few at a time.
- **Damaged zips.** A `.eval` log that is not one plain zip (data before its first part, or a second table of contents) is not read.

## MLflow

```
pip install "judgekeeper[mlflow]"
judgekeeper --experiment my-app-eval --metric correctness
```

Tested with MLflow 3.16, the version in tests/fixtures. The extra allows MLflow 3.1 or newer. It reads the assessments on your traces from the local store: `mlflow.db` (through a temporary copy) or `mlruns/` (`--tracking-uri` picks one). `--experiment` takes a name or id, `--metric` the assessment name. It reads the newest 30,000 traces. MLflow's usage tracking is off while judgekeeper reads a store (`MLFLOW_DISABLE_TELEMETRY=true`, and `DO_NOT_TRACK=1` unless your shell sets it). The rule `fix` shows is a `make_judge`'s instructions or a `Guidelines` text, not a registered or built-in scorer's. To grade the same answers again, run `mlflow.genai.evaluate()` on the existing traces with the new scorer.

**Traps.**

- **Trace ids change every run.** So ids are made from the trace's request input.
- **Assessments logged outside `evaluate`** form one extra run, listed last.
- **The rule.** Only `make_judge` (MLflow 3.14+) saves its instructions; for other scorers the prompt hash and temperature are unknown.
- **Errors** are no decision; the reason is the error's code, never its message.
- **Code scorers** (a bare bool or number) and assessments on spans are left out, unless `--metric` names a span-only one.
- **Traces kept elsewhere.** In `mlflow.db`, a trace whose full data is kept outside the folder that holds `mlflow.db` (on a server, in a cloud bucket or in another folder) is read from its short preview in the store, and the count is said once. So is one that names no place for its data. The copy's triggers are removed before MLflow opens it, and its locations are checked again once MLflow has. judgekeeper never fetches that data.
- **A copied `mlruns/` folder.** Its traces point at full paths, so judgekeeper reads them from the store's own folder, never from where they point. A trace whose files are not there is left out, and said.
- **MLflow's own problems, not judgekeeper's.** `mlflow.genai.evaluate` on `mlflow.db` can drop traces and still say it completed; `MLFLOW_GENAI_EVAL_MAX_WORKERS=4` avoids it.

## A CSV or JSONL file

A CSV, TSV or JSONL file with `input`, `output` and `verdict` columns, one file per LLM-as-a-judge. `judge_verdict` or `judge` also work as the grade column; with several, it asks which. A `model` or `judge_model` column names the model. `id` (when unique) and `reason` are read. With `--pass-if`, a `score` column is read instead. It prints the columns it read, one row each, so a wrong table shows at once. A `;` file reads `0,42` as 0.42. Save Excel files as CSV UTF-8. To grade the same answers again, grade `marked-answers.csv` with your own code.

## Results in a format of its own

With no eval tool found, it looks for a JSON, JSONL or CSV file changed in the last 90 days with a score-like key (`score`, `scores`, `verdict`, `pass`, `passed`, `success`, `label`) next to an input-like and an output-like key. It shows how it would read the file (paths, never values) and asks whether that is right, then asks only what the file cannot tell. A blank, `NaN`, `error`, `N/A` or `null` score is no decision. `--yes` never accepts a reading it is unsure of. With your yes, it saves the reading in `judgekeeper.toml` (`[start]`), for files inside the project only. Otherwise turn the file into a CSV, or use [`judgekeeper.record()`](reference.md#record-save-your-own-llm-as-a-judges-verdicts-with-one-line).

## judgekeeper.record()

`judgekeeper` reads every file in `.judgekeeper/records/` written by the newest file's LLM-as-a-judge as one set; a newer file wins for a repeated answer. With several names, `--metric` picks one. A cut-short last line, or a file it cannot read, is left out with a note. To grade the same answers again, grade `marked-answers.csv` with your own code. How to write them: [record()](reference.md#record-save-your-own-llm-as-a-judges-verdicts-with-one-line).
