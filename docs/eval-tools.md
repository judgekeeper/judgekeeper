# Eval tools

How judgekeeper finds and reads the results each eval tool saves. Commands, flags, files and exit codes are in the [reference](reference.md). judgekeeper only reads these files and never changes them. Most of this page, it also says in the terminal when it happens.

## How it looks

- Inside your project folder, four folders deep (a CSV or JSONL table: two). A results file outside it is read only when you name it.
- It skips `.git`, `node_modules`, virtual environments (any folder holding `pyvenv.cfg`) and hidden folders, except `.deepeval` and `.judgekeeper/records/`. It does not follow symbolic links. It stops after 5,000 files or 2 seconds, and says so.
- A results file over 200 MB is listed, not read, unless you name it and say yes.
- When it finds nothing, it names the results-like files it left out (too deep, links, not UTF-8, Excel workbooks) with the command that reads each.

## Asking again

To ask your LLM-as-a-judge again, `fix` and `check` run your project's own eval tool and Python. Use them only in projects you trust, as you would run their tests. This starts while the plan is made, before the `Go ahead?` question: judgekeeper runs the project's `node_modules/.bin/promptfoo` (or promptfoo on your PATH) to read its version, and for DeepEval, Inspect AI and MLflow a small script with your Python (the active virtual environment, else the project's `.venv` or `venv`). Which promptfoo graders it asks again is under [promptfoo](#promptfoo).

When it asks again, the project's `.env` and `.npmrc` are not read. promptfoo and `npx` run from a new empty folder outside the project, and DeepEval and Inspect AI load no `.env`. From the `.env` files the tool would read, judgekeeper passes on only API key names (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY` and the like, and a promptfoo grader's `apiKeyEnvar`). For promptfoo it also passes on a temperature, max tokens or top p setting of the grader's provider (`OPENAI_TEMPERATURE` and the like) when its value is a plain number. Any other name there, such as `OPENAI_BASE_URL`, `HTTPS_PROXY`, `NODE_OPTIONS` or `AWS_CONFIG_FILE`, is not used. When it changes your LLM-as-a-judge, the plan names it and says to set it in your shell to use it, and the re-check is a close copy, not exactly your LLM-as-a-judge. Your shell's own variables are used as they are, and win over `.env`.

It won't ask again when a file in the project could start a program or send the calls to another server: for promptfoo, a name in the config's `env:` block that is not an API key; for Inspect AI, a log that gives the model that grades a server (`base_url`) or `args`, or a template Inspect could read from outside the project (an address such as `https://` or `s3://`, a path that starts with `~`, `/`, `\` or a drive, or `file:`), or a template file whose name holds anything but letters, digits, `_`, `.`, `/`, `\` and `-`; for MLflow, a registered custom `@scorer`.

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

Tested with promptfoo 0.123 and 0.124, the versions in tests/fixtures. It reads JSON files from `promptfoo eval -o` or `promptfoo export eval`; when results are only in promptfoo's database, it prints the export commands. At a terminal it also asks to run the export (Enter is No); a yes runs the project's promptfoo. `--metric` is an assertion's `metric:`, else its type (`llm-rubric`, `g-eval`, `factuality` and the other model-graded types); code assertions are left out. The rule `fix` swaps in is the assertion's `value`, unless it differs per test. Ids are the test's `description` when each is unique, else a hash of its vars.

To ask again, it runs the promptfoo version your results were made with (the project's, the one on your PATH, or `npx promptfoo@<version>`, part of the same `Go ahead?` question). It takes that version from a results file only when it reads as a plain version number. It asks again only when the grader is a model provider promptfoo calls over HTTP, from a fixed list (`openai:`, `anthropic:`, `azure:`, `bedrock:`, `vertex:`, `google:`, `mistral:`, `ollama:` and others like them, in any case). It won't when the grader runs an agent with tools (`anthropic:claude-agent-sdk`, `anthropic:claude-code`, `openai:codex-sdk`, `openai:agents:...`, an assistant) or is any other kind (`package:`, `exec:`, `python:`, `file://`, a URL, `webhook:`, a name it doesn't know), also inside a grader written by output type (`{"text": ...}`), or when the rule loads code (`package:`, `file://`, `exec:`) or there is a `transform`.

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

Tested with DeepEval 4.2, the version in tests/fixtures. It reads the newest `test_run_<date>.json` in your results folder (`DEEPEVAL_RESULTS_FOLDER`, or `DisplayConfig(results_folder=...)` in `evaluate()`), else `.deepeval/.latest_run_full.json`, which every run overwrites. Results are saved only by `deepeval test run` or `evaluate()`: calling a metric's `measure()` directly saves nothing. `--metric` is the metric's `name` (GEval: `"<name> [GEval]"`). The grade is `success`, or `score` with `--pass-if`. The rule `fix` swaps in is a GEval's evaluation steps or criteria. The version comes from your project's pin (`uv.lock`, `poetry.lock`, `pyproject.toml` or `requirements*.txt`).

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

Tested with Inspect AI 0.3.273, the version in tests/fixtures. Logs from 0.3.2 and 0.3.204 are tested too. Logs are in `./logs` or `INSPECT_LOG_DIR`. `.eval` logs need `pip install "judgekeeper[inspect]"` in your project's environment; else use `--log-format json` or `inspect log dump`. Logs in several folders are never read as one: it asks which and keeps the answer in `judgekeeper.toml`. `--metric` is the scorer's name under `samples[].scores`. Ids are `samples[].id`, repeats `samples[].epoch`. The rule `fix` swaps in is the scorer's instructions. When asking again, a failed call leaves out only that answer, and the error is shown by type and count, never its text.

**Traps.**

- **Score values.** `C` is pass, `I` is fail. `P` (partial credit) has no default: use `--label-map P=fail` (or `P=pass`). Numbers need `--pass-if`.
- **A dict value** (`{"accuracy": "C", "tone": "I"}`) is one LLM-as-a-judge per key, like `rubric.tone`.
- **Code scorers** (`match`, `includes`, `exact`, `pattern`, `f1`, `answer`) are left out, and so is a sample that failed before scoring.
- **The grading template.** The prompt hash covers the `template` and `instructions` options, not Inspect's default template. Set `template` to track it.
- **`--no-log-samples`** logs cannot be read.
- **Very big parts.** A `.eval` log whose header would unpack to more than 500 MB, or one sample to more than 200 MB, is not read. judgekeeper counts what each part really unpacks to before Inspect AI reads the log, and keeps none of it.

## MLflow

```
pip install "judgekeeper[mlflow]"
judgekeeper --experiment my-app-eval --metric correctness
```

Tested with MLflow 3.16, the version in tests/fixtures. The extra allows MLflow 3.1 or newer. It reads the assessments on your traces from the local store: `mlflow.db` (through a temporary copy) or `mlruns/` (`--tracking-uri` picks one). `--experiment` takes a name or id, `--metric` the assessment name. It reads the newest 30,000 traces. The rule `fix` swaps in is a `make_judge`'s instructions or a `Guidelines` text, not a registered or built-in scorer's.

**Traps.**

- **Trace ids change every run.** So ids are made from the trace's request input.
- **Assessments logged outside `evaluate`** form one extra run, listed last.
- **The rule.** Only `make_judge` (MLflow 3.14+) saves its instructions; for other scorers the prompt hash and temperature are unknown.
- **Errors** are no decision; the reason is the error's code, never its message.
- **Code scorers** (a bare bool or number) and assessments on spans are left out, unless `--metric` names a span-only one.
- **A copied `mlruns/` folder.** Its traces point at full paths, so judgekeeper reads them from the store's own folder, never from where they point. A trace whose files are not there is left out, and said.
- **MLflow's own problems, not judgekeeper's.** `mlflow.genai.evaluate` on `mlflow.db` can drop traces and still say it completed; `MLFLOW_GENAI_EVAL_MAX_WORKERS=4` avoids it.

## A CSV or JSONL file

A CSV, TSV or JSONL file with `input`, `output` and `verdict` columns, one file per LLM-as-a-judge. `judge_verdict` or `judge` also work as the grade column; with several, it asks which. A `model` or `judge_model` column names the model. `id` (when unique) and `reason` are read. With `--pass-if`, a `score` column is read instead. It prints the columns it read, one row each, so a wrong table shows at once. A `;` file reads `0,42` as 0.42. Save Excel files as CSV UTF-8.

## Results in a format of its own

With no eval tool found, it looks for a JSON, JSONL or CSV file changed in the last 90 days with a score-like key (`score`, `scores`, `verdict`, `pass`, `passed`, `success`, `label`) next to an input-like and an output-like key. It shows how it would read the file (paths, never values) and asks whether that is right, then asks only what the file cannot tell. A blank, `NaN`, `error`, `N/A` or `null` score is no decision. `--yes` never accepts a reading it is unsure of. With your yes, it saves the reading in `judgekeeper.toml` (`[start]`), for files inside the project only. Otherwise turn the file into a CSV, or use [`judgekeeper.record()`](reference.md#record-save-your-own-llm-as-a-judges-verdicts-with-one-line).

## judgekeeper.record()

`judgekeeper` reads every file in `.judgekeeper/records/` written by the newest file's LLM-as-a-judge as one set; a newer file wins for a repeated answer. With several names, `--metric` picks one. A cut-short last line, or a file it cannot read, is left out with a note. How to write them: [record()](reference.md#record-save-your-own-llm-as-a-judges-verdicts-with-one-line).
