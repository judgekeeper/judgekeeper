# Eval tools

How judgekeeper finds and reads the results each eval tool saves. Commands, flags, files and exit codes are in the [reference](reference.md).

An eval tool runs your tests and saves the results, including your LLM-as-a-judge's grades. judgekeeper only reads those files. It never changes them. To ask your LLM-as-a-judge again, `fix` and `check` run your eval tool on your saved answers (see the [reference](reference.md#your-api-keys)).

Most of what follows, judgekeeper also says in the terminal when it happens. Read this page when something surprises you.

## How it looks

- It looks inside your project folder, four folders deep. A results file outside it is read only when you name it. A CSV or JSONL table is looked for two folders deep.
- It skips `.git`, `node_modules`, virtual environments (any folder holding `pyvenv.cfg`) and hidden folders. It does look in `.deepeval` and `.judgekeeper/records/`.
- It stops after 5,000 files or 2 seconds, and says so. It does not follow symbolic links.
- A results file over 200 MB is listed, not read. One you name (`judgekeeper results.csv`) is read after you say yes.
- A damaged file is named with what is wrong, such as "mlflow.db can't be read: it's damaged".
- A results file with no LLM-as-a-judge in it (checks written in code, or promptfoo's table output) is left out with one line.
- When it finds nothing, it says how deep it looked and names the results-like files it left out, with the command that reads each. That covers files further down, links, files not saved as UTF-8, and Excel workbooks (save them as CSV UTF-8).
- When it finds nothing in a folder inside a project, it reads the project folder instead.

## How failed calls are spotted

Before you mark anything, judgekeeper checks the grades with no AI call. These are the signs it looks for.

| Eval tool | The call failed | The reply could not be read |
|---|---|---|
| promptfoo | `graderError`, or in older files a reason such as "API error:" | "Could not extract JSON" or "Error parsing output" |
| DeepEval | `error`, or no score with `success` false | |
| Inspect AI | `grader_failed`, or a sample that errored before it was scored | "Grade not found in model output" |
| MLflow | `feedback.error` | |

A DeepEval metric that had nothing to check shows an empty `Verdicts:` list in its logs, scores 1.0 and passes. It is left out too.

**The reason says the opposite** when it names the other grade in one of these ways:

- it starts with PASS, PASSED, FAIL or FAILED;
- its last `verdict:`, `grade:`, `result:`, `decision:`, `final verdict:` or `final answer:` says pass, fail, correct or incorrect;
- Inspect AI's `GRADE: C` or `GRADE: I`.

No other words count, so "does not fail" is never flagged. This check is skipped when grades are scores with a pass mark.

## promptfoo

```
promptfoo eval -o results.json
judgekeeper
```

Tested with promptfoo 0.123 and 0.124, the versions in tests/fixtures. Your promptfoo config does not change. judgekeeper reads JSON results files from `promptfoo eval -o` or `promptfoo export eval`. When the results are only in promptfoo's database, it prints the `promptfoo export eval` commands that save them to a file. They run no test and make no AI call.

To ask your LLM-as-a-judge again (`fix`, or a `check` that makes AI calls), judgekeeper runs the promptfoo version your results were made with. That is the project's, or the one on your PATH, or else `npx promptfoo@<version>`. The download is part of the same `Go ahead? [y/N]` question. Without `npx`, it names the install command.

`--metric` names the LLM-as-a-judge: an assertion's `metric:` if it has one, otherwise its type (`llm-rubric`, `g-eval`, `factuality`, `model-graded-closedqa` and the other model-graded types). Other assertions (`contains`, `javascript`, ...) are code checks, so they are left out, with a note.

The rule `fix` swaps in is the assertion's `value`. An assertion whose `value` differs per test shows as "Rule: differs per test (12 rules)", and `fix` can't swap it.

Each answer's id is the test's `description` when every test has a unique one. Otherwise it is a hash of the test's vars. With several prompts, ids get `#prompt<n>`.

**Traps.**

- **A human rating overrides the row's `success` and `pass`.** So judgekeeper reads the LLM-as-a-judge's grade from the model-graded part itself, never from those two.
- **`--repeat` rows carry no repeat index.** judgekeeper numbers the repeats in file order. Repeats of one answer with the same grade count once. With different grades, each is its own answer, and it says so.
- **The default grader is not recorded.** With no `provider` set, promptfoo grades with its built-in default model and the file does not say which. Those grades get an unknown model. Set the grader yourself, as below. The temperature is recorded only when the provider config holds it.
- **A grader set with `--grader`** is saved by its model name only, so the provider is unknown.
- **Cached grades.** A grade promptfoo replayed from its cache may be an old reply. judgekeeper says how many there are.
- **No grading details.** When `gradingResult` is empty on every row and each test has one llm-rubric, each row's `success` is used as the grade, with a note. With more assertions per test, turn `PROMPTFOO_STRIP_GRADING_RESULT` off and run again.
- **The model you test failed.** Such a row has no answer and no grade. promptfoo counts it as a fail, but your LLM-as-a-judge never ran. judgekeeper leaves it out and says so.

```yaml
defaultTest:
  options:
    provider:
      id: openai:gpt-4.1-mini
      config:
        temperature: 0
```

## DeepEval

```
export DEEPEVAL_RESULTS_FOLDER=deepeval-results
deepeval test run test_judge.py
judgekeeper --metric "Correctness [GEval]"
```

Tested with DeepEval 4.2, the version in tests/fixtures. Your test code does not change.

DeepEval has no `--output-file` flag. It writes `.deepeval/.latest_run_full.json`, overwritten by every run. When you set a results folder (`DEEPEVAL_RESULTS_FOLDER`, or `display_config=DisplayConfig(results_folder=...)` in `evaluate()`), it also writes one `test_run_<date>.json` per run. judgekeeper reads the newest run by time.

Results are saved only when tests run through `deepeval test run` or `evaluate()`: calling a metric's `measure()` directly saves nothing.

`--metric` is the metric's `name` in `metricsData`. GEval metrics are named `"<name> [GEval]"`. The grade is the metric's `success`. With `--pass-if "score>=0.7"`, the rule is applied to `score` instead. The rule `fix` swaps in is a GEval's evaluation steps, or its criteria.

DeepEval's results don't hold its version. judgekeeper reads it from your project's pin (`uv.lock`, `poetry.lock`, `pyproject.toml` or `requirements*.txt`).

**Traps.**

- **Default test case names are positional.** Without `LLMTestCase(name=...)`, cases are named `test_case_0`, `test_case_1`, ... by order. judgekeeper then makes each id from the input and the answer, and warns. Name your test cases so ids stay the same across runs.
- **The temperature is not written.** It is recorded as unknown. The provider comes from the suffix DeepEval adds to the model's name, such as `claude-sonnet-4-6 (Anthropic)`. A bare name is OpenAI.
- **An empty answer.** DeepEval refuses it and saves an error, so it counts as no real decision.
- **`DEEPEVAL_LOCAL_STORE=sqlite`** writes `deepeval.db` and no JSON. Leave it unset.

## Inspect AI

```
inspect eval task.py
judgekeeper --metric model_graded_qa
```

Tested with Inspect AI 0.3.273, the version in tests/fixtures. Logs written by 0.3.2 and 0.3.204 are tested too. Your task does not change.

Logs land in `./logs`, or in `INSPECT_LOG_DIR`. `.json` logs are read directly. `.eval` logs (Inspect's default) need the optional extra, installed in your project's environment: `pip install "judgekeeper[inspect]"`. Without it, write JSON logs with `--log-format json`, or convert one with `inspect log dump logs/x.eval > log.json`.

To read one log, give its path: `judgekeeper logs/log.json`. Logs in more than one folder are never read as one: it asks which, and keeps your answer in `judgekeeper.toml`.

`--metric` is the scorer's name, the key under `samples[].scores` (`model_graded_qa`, `model_graded_fact`, or your `@scorer` name). Ids are `samples[].id`, and repeats are `samples[].epoch`. The rule `fix` swaps in is the scorer's instructions.

When `fix` or `check` asks again and one call fails, only that answer is left out. The error is shown by its type and count ("BadRequestError on 13 answers"), never its text, which can quote the grading prompt.

**Traps.**

- **Score values.** `C` is pass and `I` is fail. `P` (partial credit) has no default: map it with `--label-map P=fail` (or `P=pass`). Numbers need `--pass-if`, such as `--pass-if "score>=0.5"`.
- **Several values at once.** A scorer whose value is a dict (`{"accuracy": "C", "tone": "I"}`) is read as one LLM-as-a-judge per key, named like `rubric.tone`. Pick one with `--metric`.
- **Code scorers.** `match`, `includes`, `exact`, `pattern`, `f1` and `answer` check text in code, not with a model. They are left out.
- **A sample that failed before scoring** has no grade. It is left out, never counted as a failed LLM-as-a-judge call.
- **The grading template.** The prompt hash covers the scorer's `template` and `instructions` options. If you upgrade Inspect and its default template changes, the hash does not. Set `template` yourself to track it.
- **`--no-log-samples`** logs have no samples and cannot be read.

## MLflow

```
pip install "judgekeeper[mlflow]"
judgekeeper --experiment my-app-eval --metric correctness
```

Tested with MLflow 3.16, the version in tests/fixtures. The extra allows MLflow 3.1 or newer. Install it in your project's environment.

judgekeeper reads the LLM-as-a-judge's assessments MLflow already stores on your traces. It reads the local store in your project: `mlflow.db` (through a temporary copy) or an `mlruns/` folder. `--tracking-uri` picks one when there are both. For an `mlruns/` folder it turns on MLflow's folder-store setting for its own read only, unless you set it yourself.

`--experiment` takes a name or an id. `--metric` is the assessment name (your scorer's name). It reads the newest 30,000 traces, and says so when there are more. The rule `fix` swaps in is a `make_judge`'s instructions or a `Guidelines` text. It can't swap a registered or built-in scorer's rule.

**Traps.**

- **Trace ids change every run.** So judgekeeper makes each id from the trace's request input. The same dataset row is the same answer in every run.
- **Which run.** An assessment logged outside `evaluate` has no run. Such assessments form one extra run, listed last, with a note.
- **The rule.** A `make_judge` (MLflow 3.14 and later) saves its instructions with each assessment, so a changed rule shows. Other scorers don't save their prompt with their assessments, so for them the prompt hash is unknown. The temperature is unknown.
- **Errors.** An assessment with an `error` (a timeout, say) is no decision. Its reason is the error's code, never its message.
- **Code scorers.** A scorer that returns a bare bool or number is not an LLM-as-a-judge. It is left out, with a note.
- **Steps, not answers.** An assessment on one span inside a trace grades a step. Only trace-level assessments are read, unless `--metric` names one that is only on spans.
- **A copied `mlruns/` folder.** It saves each trace's files as a full path. On another computer, MLflow drops every trace it can't find there. judgekeeper reads them from the store's own folder instead.
- **MLflow's own problems, not judgekeeper's.** `mlflow.genai.evaluate` on `mlflow.db` can drop traces when it runs out of database connections, and still say it completed. `MLFLOW_GENAI_EVAL_MAX_WORKERS=4` avoids it. judgekeeper only counts the traces that were saved.

## A CSV or JSONL file

A CSV, TSV or JSONL file with `input`, `output` and `verdict` columns, one file per LLM-as-a-judge. `judge_verdict` or `judge` also work as the grade column. With more than one of them, each is an LLM-as-a-judge, and judgekeeper asks which to check.

- A `model` or `judge_model` column names the LLM-as-a-judge's model, when its values are model names.
- `id` and `reason` are read when they are there. The `id` column is used when every row has a unique one.
- With `--pass-if`, a `score` column next to the grade column is read instead, and it says so.

It prints the file, the count of answers, and the columns it read, one row each, so a wrong table shows at once. Then it prints how many answers your LLM-as-a-judge passed and failed.

Blank rows at the end are skipped. In a file separated by `;`, a score like `0,42` is 0.42. A title row above the header is named, and so is an Excel file: save it as CSV UTF-8. A file deeper than two folders needs its path: `judgekeeper results/judge.csv`.

## Results in a format of its own

When it finds no eval tool's results, it looks for a recent JSON, JSONL or CSV file (changed in the last 90 days). The file must hold a score-like key next to an input-like and an output-like key. Score-like keys are `score`, `scores`, `verdict`, `pass`, `passed`, `success` and `label`. You can also give it such a file.

It shows the file's paths, never their values, and how it would read them: what one answer is, the input, the answer, the score, the reason, the id and the model. It asks whether that is right. Then it asks only what the file cannot tell, such as which metric, or the pass mark when scores are not between 0 and 1.

- A part is a grade only when its name says so and most of its values are grades.
- Ids, free text and settings (a pass mark, the criteria's text, a run id) never are.
- A blank or `NaN` score, or `error`, `N/A` or `null`, is no decision.
- `--pass-if` sets the pass mark with any sign (`score>4`, `score<=2`, `score==5`).
- A reading it is not sure of is never accepted by `--yes`. Run it in a terminal to check.

With your yes, it saves how to read the file in `judgekeeper.toml` (its `[start]` table), and reads that first next time. Only a file inside the project can be saved this way.

When the file cannot be read this way, it says so. Turn it into a CSV with the columns `id`, `input`, `output`, `verdict` and `reason`, or save the grades with [`judgekeeper.record()`](reference.md#record-save-your-own-llm-as-a-judges-verdicts-with-one-line).

## judgekeeper.record()

When your LLM-as-a-judge runs in your own code, one `judgekeeper.record()` line saves each grade in `.judgekeeper/records/` ([how](reference.md#record-save-your-own-llm-as-a-judges-verdicts-with-one-line)).

`judgekeeper` reads every file written by the newest file's LLM-as-a-judge, as one set. One eval run can be many processes, so many files. A newer file wins for a repeated answer. With several LLM-as-a-judge names, it asks which, and `--metric` answers. A last line cut short is left out, and so is a file it cannot read, with a note.
