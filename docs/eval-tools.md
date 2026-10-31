# Eval tools

How judgekeeper finds and reads the results each eval tool saves. Commands, flags, files and exit codes are in the [reference](reference.md). judgekeeper only reads these files and never changes them. judgekeeper also says most of this in the terminal.

## How it looks

- Inside your project folder, four folders deep (a CSV, TSV or JSONL table: two). A results file outside it is read only when you name it.
- It skips `.git`, `node_modules`, virtual environments (any folder holding `pyvenv.cfg`) and hidden folders, except `.deepeval` and `.judgekeeper/records/`. It does not follow symbolic links. It stops after 5,000 files or 2 seconds, and says so.
- A results file over 200 MB is listed, not read, unless you name it and say yes.
- When it finds nothing, it names the results-like files it left out (too deep, links, not UTF-8, Excel workbooks) with the command that reads each.

## Grading answers again

judgekeeper never runs your eval tool and never asks your LLM-as-a-judge itself. To test a new rule, `judgekeeper fix` writes every answer you marked in `.judgekeeper/fix/marked-answers.csv`, with two columns, `question` and `answer`. You grade those answers again with your new rule in your eval tool, keeping your LLM-as-a-judge's name the same, save the results, and run `judgekeeper fix <new results file>`. Each tool's part below says how. `fix` and `check` read the new results with the choices you made at the start (`--metric`, `--experiment`), so you don't give them again.

To re-check after you change your LLM-as-a-judge, grade your marked answers again (`.judgekeeper/fix/marked-answers.csv`) the same way, then run `judgekeeper check <new results file>`. It finds the answers you marked by their exact text and question, and running your eval again usually makes new answers, which it can't compare.

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

Tested with promptfoo 0.123 and 0.124, the versions in tests/fixtures. It reads JSON files from `promptfoo eval -o` or `promptfoo export eval`. When results are only in promptfoo's database, it prints how to save them: `promptfoo eval -o promptfoo-results.json`, or `promptfoo list evals` and `promptfoo export eval <id> -o promptfoo-results.json`. It runs neither. `--metric` is an assertion's `metric:`, else its type (`llm-rubric`, `g-eval`, `factuality` and the other model-graded types); code assertions are left out. The rule `fix` shows is the assertion's `value`, unless it differs per test. An assertion's `threshold` is its pass mark: `check` notices when it changes, and `fix` may test a better one. The question is the test's vars; a test with no vars (questions written in `prompts:`) is asked by its prompt. Ids are the test's `description` when each is unique, else a hash of its vars.

To grade the same answers again, `judgekeeper fix` writes `.judgekeeper/fix/regrade.yaml` for you: `marked-answers.csv` as its tests and the `echo` provider, which returns each answer as it is. It looks like this (change the rule in it, and run it with `promptfoo eval -c .judgekeeper/fix/regrade.yaml -o .judgekeeper/fix/new.json`):

```yaml
prompts: ['{{answer}}']
providers: [echo]
tests: file://.judgekeeper/fix/marked-answers.csv
defaultTest:
  options:
    provider: <your grader model>  # your grader, as before
  assert:
    - type: llm-rubric
      metric: correctness  # the same metric: as before, if yours has one
      value: Your new rule. The question was {{question}}.
```

The rule's variables must be the CSV's column names, `{{question}}` and `{{answer}}`. Run `promptfoo eval -c regrade.yaml -o new.json`, then `judgekeeper fix new.json`.

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

Tested with DeepEval 4.2, the version in tests/fixtures. It reads the newest `test_run_<date>.json` in your results folder (`DEEPEVAL_RESULTS_FOLDER`, or `DisplayConfig(results_folder=...)` in `evaluate()`), else `.deepeval/.latest_run_full.json`, which every run overwrites. Results are saved only by `deepeval test run` or `evaluate()`: calling a metric's `measure()` directly saves nothing. `--metric` is the metric's `name` (GEval: `"<name> [GEval]"`). The grade is `success`, or `score` with `--pass-if`. The rule `fix` shows is a GEval's evaluation steps or criteria. To grade the same answers again, make one `LLMTestCase(input=row["question"], actual_output=row["answer"])` for each row of `marked-answers.csv`, with any field your metric also reads, such as `expected_output`, added back by its question, and run your metric with its new rule and the same `name` through `deepeval test run` or `evaluate()`. The run is saved as a new `test_run_<date>.json` in your results folder: run `judgekeeper fix deepeval-results/test_run_<date>.json` (your `DEEPEVAL_RESULTS_FOLDER`). `fix` and `check` keep the `--metric` you chose at the start. The version comes from your project's pin (`uv.lock`, `poetry.lock`, `pyproject.toml` or `requirements*.txt`).

**Traps.**

- **Default test case names are positional.** Without `LLMTestCase(name=...)`, ids are made from the input and answer, with a warning.
- **The temperature is not written.** The provider comes from the model name's suffix (`(Anthropic)`); a bare name is OpenAI.
- **The prompt hash is kept per answer.** A GEval given only `criteria=` writes its evaluation steps with its model for each answer, so the prompt differs per answer: each judgment keeps its own prompt hash, and the run and `judge.json` keep none. Give `evaluation_steps=[...]` for one prompt.
- **An empty answer** is saved as an error: no real decision.
- **`DEEPEVAL_LOCAL_STORE=sqlite`** writes no JSON. Leave it unset.

## Inspect AI

```
inspect eval task.py
judgekeeper --metric model_graded_qa
```

Tested with Inspect AI 0.3.273, the version in tests/fixtures. Logs from 0.3.2 and 0.3.204 are tested too. Logs are in `./logs` or `INSPECT_LOG_DIR`. `.eval` logs need `pip install "judgekeeper[inspect]"` in your project's environment; else use `--log-format json` or `inspect log dump`. Logs in several folders are never read as one: it asks which and keeps the answer in `judgekeeper.toml`. `--metric` is the scorer's name under `samples[].scores`. Ids are `samples[].id`, repeats `samples[].epoch`. The rule `fix` shows is the scorer's instructions. To grade the same answers again, grade your log again, with no new answers: `inspect score <log> --scorer model_graded_qa -S instructions="<new rule>" --action overwrite --output-file logs/new.eval`. `--scorer` takes the scorer's name: `model_graded_qa` (or `inspect_ai/model_graded_qa`) for Inspect's own, `task.py@<name>` for a scorer of your own. `-S` sets the scorer's options: give the ones you set before again, such as `-S model=...`. `--action overwrite` replaces the old grades in the new log, so your scorer's name holds the new ones (Inspect's default, `append`, keeps both). `--output-file` writes a new log in your log folder (`logs/` here), so yours stays as it was and `check` finds the new one there. Then run `judgekeeper fix logs/new.eval` (a `.eval` log needs `judgekeeper[inspect]`). A rule with a comma, or a colon followed by a space, needs Python: see the traps.

**Traps.**

- **Score values.** `C` is pass, `I` is fail. `P` (partial credit) has no default: use `--label-map P=fail` (or `P=pass`). Numbers need `--pass-if`.
- **A dict value** (`{"accuracy": "C", "tone": "I"}`) is one LLM-as-a-judge per key, like `rubric.tone`.
- **Code scorers** (`match`, `includes`, `exact`, `pattern`, `f1`, `answer`) are left out, and so is a sample that failed before scoring.
- **The grading template.** The prompt hash covers the `template` and `instructions` options, not Inspect's default template. Set `template` to track it.
- **Grades the grader skips.** A grader model that leaves out the `GRADE:` line ("Grade not found in model output") gives that answer no decision. In `judgekeeper fix <log>`, each one kept aside counts as the new rule's mistake, and it says how many; with more than half ungraded, grade the log again. `check` leaves them out and says how many.
- **A new rule with a comma, or a colon followed by a space.** `inspect score -S instructions="…"` breaks such a rule: Inspect reads `-S` values as YAML, so a colon followed by a space (`GRADE: C`) makes it something other than text, then splits text at commas. Grade the log again with Inspect's `score()` in Python instead, which keeps the whole rule under your scorer's name:

  ```python
  from pathlib import Path
  from inspect_ai import score
  from inspect_ai.log import read_eval_log, write_eval_log
  from inspect_ai.scorer import model_graded_qa

  log = read_eval_log("logs/<your log>.eval")
  rule = Path("rule.txt").read_text()  # your new rule
  scorer = model_graded_qa(instructions=rule, model="<the grader model you used>")
  write_eval_log(score(log, scorer, action="overwrite"), "logs/new.eval")
  ```

  `model=` writes your grader model into the new log, so `check` can name your LLM-as-a-judge. Then run `judgekeeper fix logs/new.eval`.
- **`--no-log-samples`** logs cannot be read.
- **Very big parts.** Very large `.eval` logs are refused; the message says which limit ([reference](reference.md#what-it-reads)).
- **Damaged zips.** A `.eval` log that is not one plain zip (data before its first part, or a second table of contents) is not read.

## MLflow

```
pip install "judgekeeper[mlflow]"
judgekeeper --experiment my-app-eval --metric correctness
```

Tested with MLflow 3.16, the version in tests/fixtures. The extra allows MLflow 3.1 or newer. It reads the assessments on your traces from the local store: `mlflow.db` (through a temporary copy) or `mlruns/` (`--tracking-uri` picks one). `--experiment` takes a name or id, `--metric` the assessment name. It reads the newest 30,000 traces. MLflow's usage tracking is off while judgekeeper reads a store (`MLFLOW_DISABLE_TELEMETRY=true`, and `DO_NOT_TRACK=1` unless your shell sets it). The rule `fix` shows is a `make_judge`'s instructions or a `Guidelines` text, not a registered or built-in scorer's. To grade the same answers again, run `mlflow.genai.evaluate()` on the existing traces with the new scorer, under the same name, in the same experiment. Then run `judgekeeper fix mlflow.db` (or `judgekeeper fix mlruns`): it reads the newest run of the experiment you chose at the start.

**Traps.**

- **Trace ids change every run.** So ids are made from the trace's request input.
- **Assessments logged outside `evaluate`** form one extra run, listed last.
- **The rule.** Only `make_judge` (MLflow 3.14+) saves its instructions; for other scorers the prompt hash and temperature are unknown.
- **Errors** are no decision; the reason is the error's code, never its message.
- **Code scorers** (a bare bool or number) and assessments on spans are left out, unless `--metric` names a span-only one.
- **Traces kept elsewhere.** In `mlflow.db`, a trace whose full data is kept outside the folder that holds `mlflow.db` (on a server, in a cloud bucket or in another folder) is read from its short preview in the store, and the count is said once. So is one that names no place for its data. The copy's triggers are removed before MLflow opens it, and its locations are checked again once MLflow has. judgekeeper never fetches that data.
- **A copied `mlruns/` folder.** Its traces point at full paths, so judgekeeper reads them from the store's own folder, never from where they point. A trace whose files are not there is left out, and said.
- **MLflow's own problems, not judgekeeper's.** `mlflow.genai.evaluate` on `mlflow.db` can drop traces and still say it completed; `MLFLOW_GENAI_EVAL_MAX_WORKERS=4` avoids it.

## A CSV, TSV or JSONL file

A CSV, TSV or JSONL file with `input`, `output` and `verdict` columns, one file per LLM-as-a-judge. `judge_verdict` or `judge` also work as the grade column (a `judge` column of model names, such as my-judge-v1, is not one); with several, it asks which. A `model` or `judge_model` column names the model. `id` (when unique) and `reason` are read. With `--pass-if`, a `score` column is read instead. It prints the columns it read, one row each, so a wrong table shows at once. A `;` file reads `0,42` as 0.42. Save Excel files as CSV UTF-8. To grade the same answers again, grade `marked-answers.csv` with your own code, and save a file with the same column names as your first one: its `question` as `input`, its `answer` as `output`, and the new grade as `verdict`. Then run `judgekeeper fix <new file>`.

## Results in a format of its own

With no eval tool found, it looks for a JSON, JSONL or CSV file changed in the last 90 days with a score-like key (`score`, `scores`, `verdict`, `pass`, `passed`, `success`, `label`) next to an input-like and an output-like key. It shows how it would read the file (paths, never values) and asks whether that is right, then asks only what the file cannot tell. A blank, `NaN`, `error`, `N/A` or `null` score is no decision. `--yes` never accepts a reading it is unsure of. With your yes, it saves the reading in `judgekeeper.toml` (`[start]`), for files inside the project only. A key that names your LLM-as-a-judge's model, such as `judge_model` or a `model` or `grader` inside a `judge` object (`judge.grader`), is read as the model when its value looks like a model's name; `--judge-model` wins over it for that run only. To grade the same answers again, grade `marked-answers.csv` with your own code and save the new grades in the same shape as your results file. Otherwise turn the file into a CSV, or use [`judgekeeper.record()`](reference.md#record-save-your-own-llm-as-a-judges-verdicts-with-one-line).

## judgekeeper.record()

`judgekeeper` reads every file in `.judgekeeper/records/` written by the newest file's LLM-as-a-judge as one set; a newer file wins for a repeated answer. With several names, `--metric` picks one. A cut-short last line, or a file it cannot read, is left out with a note. To grade the same answers again, grade `marked-answers.csv` with your own code, call `judgekeeper.record()` again on the new grades, then run `judgekeeper fix .judgekeeper/records/<new file>`. How to write them: [record()](reference.md#record-save-your-own-llm-as-a-judges-verdicts-with-one-line).
