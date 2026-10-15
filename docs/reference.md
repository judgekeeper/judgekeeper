# judgekeeper reference

Every command, flag, exit code, file and format. The README has the short version.

Check your LLM-as-a-judge in 5 steps: Find. Mark. Measure. Fix. Re-check. `judgekeeper` does Find, Mark and Measure; `judgekeeper mark` marks more; `judgekeeper fix` shows where your judge goes wrong and tests a better rule; `judgekeeper check` re-checks your judge after a change. Run them in your own terminal: each run ends with one `Next:` line that says what you do. `judgekeeper --help` lists the commands, and `judgekeeper <command> --help` each command's flags.

- [judgekeeper: find, mark, measure](#judgekeeper-find-mark-measure)
- [mark: mark more answers](#mark-mark-more-answers)
- [fix: see where your judge goes wrong and test a better rule](#fix-see-where-your-judge-goes-wrong-and-test-a-better-rule)
- [check: re-check your judge after a change](#check-re-check-your-judge-after-a-change)
- [How the numbers are worked out](#how-the-numbers-are-worked-out)
- [What it reads](#what-it-reads)
- [How grades are read](#how-grades-are-read)
- [Records format](#records-format)
- [record(): save your own judge's verdicts with one line](#record-save-your-own-judges-verdicts-with-one-line)
- [Unknown judge fields](#unknown-judge-fields)
- [The .judgekeeper/ folder](#the-judgekeeper-folder)
- [Your API keys](#your-api-keys)
- [Exit codes](#exit-codes)

## judgekeeper: find, mark, measure

```
judgekeeper [PATH] [--tool NAME] [--metric NAME] [--experiment NAME_OR_ID]
            [--tracking-uri URI] [--pass-if RULE] [--label-map MAP] [--judge-model NAME]
            [--fields LIST] [--yes] [--port PORT] [--no-browser] [--new | --wait | --stop]
            [--version] [--debug]
```

Each run does the next step:

| What is there | What `judgekeeper` does |
|---|---|
| Nothing marked yet | Step 1, Find: names your eval tool, the answers, your judge and its rule, and checks its grades for free (no AI call). Step 2, Mark: opens the marking page in your browser |
| Some marks, not enough yet | Says how many you marked; the marking page stays open, or opens again when it was closed |
| Enough marks of each kind | Step 3, Measure: how often your judge agrees with you, and where it goes wrong. The full report is saved in `.judgekeeper/report.html` |
| Marks for another judge or eval tool | Says why, and asks before it starts over (your old marks move to `.judgekeeper/previous-<date>/`; nothing is deleted) |
| Something to choose (several eval tools, judges or MLflow stores, a pass mark) | Asks at a terminal. Without one, it prints the flag that answers the question and exits 3 |
| No results found | Names the eval tool it found with no saved results yet, or says what it can read |

A new eval run does not start over: the answers you are marking are kept in `.judgekeeper/pool.jsonl`, so marking goes on with them. When your judge changed since your marks, it says what changed, and once there are enough marks its `Next:` line is `judgekeeper check`.

judgekeeper can read results from promptfoo, DeepEval, Inspect AI, MLflow, or a CSV or JSONL file with `input`, `output` and `verdict` columns ([What it reads](#what-it-reads)).

| Flag | What it does |
|---|---|
| `PATH` | Your project folder (default: this folder), one results file, or an MLflow store (`mlflow.db` or an `mlruns/` folder) |
| `--tool NAME` | Which eval tool's results to read when several are found: `records`, `promptfoo`, `deepeval`, `inspect`, `mlflow` or `table` |
| `--metric NAME` | The judge to look at when the results hold several |
| `--experiment NAME_OR_ID` | MLflow: the experiment to read, when several have judge results |
| `--tracking-uri URI` | MLflow: the local store to read (`mlflow.db`, `sqlite:///...`, an `mlruns/` folder or `file:...`) |
| `--pass-if RULE` | When your judge's grades are scores: which pass, e.g. `'score>=0.5'` |
| `--label-map MAP` | More spellings of your judge's grades, e.g. `'good=pass,bad=fail'` (added to pass/fail, true/false, yes/no, correct/incorrect, right/wrong, 1/0) |
| `--judge-model NAME` | The judge's model, when the results do not record it |
| `--fields LIST` | A DeepEval GEval judge: the parts it reads, e.g. `input,actual_output` |
| `--yes` | Without a terminal: yes to the questions judgekeeper printed. It never picks a tool, a judge or a pass mark for you |
| `--port PORT` | Port on 127.0.0.1 for the page (default 8765). When it is taken, the next free one; `0` for any free port |
| `--no-browser` | Print the page's link without opening a browser. For a remote machine |
| `--new` | Start over: your marks move to `.judgekeeper/previous-<date>/` (asked first; nothing is deleted) |
| `--wait` | Serve the page in this terminal until Ctrl-C, instead of in the background |
| `--stop` | Close the open page. Your marks are saved |
| `--version` | Show the version and exit |
| `--debug` | On an unexpected error, also print the traceback (credentials are still scrubbed) |

**The marking page** shows one answer at a time, with your judge's grade hidden; you mark it Pass or Fail, the way you want your judge to decide (keys `←` Fail and `→` Pass). "See your result" appears once there are enough marks of each kind. The page runs on 127.0.0.1 with a random token in its link, and saves a mark only from the page itself (its own origin), so the marks are yours. Every click is saved at once.

**Exit codes:** 0 the next step is done, 3 you are needed (the `Next:` line says what to do), 2 a usage error, 130 Ctrl-C.

## mark: mark more answers

```
judgekeeper mark [PATH] [--tool NAME] [--metric NAME] [--experiment NAME_OR_ID]
                 [--tracking-uri URI] [--pass-if RULE] [--label-map MAP] [--judge-model NAME]
                 [--fields LIST] [--yes] [--port PORT] [--no-browser] [--new | --wait | --stop]
```

Opens the marking page again, to mark more answers; more marks make your numbers more precise. Run `judgekeeper` afterwards to see your updated result. When every answer is marked, it says so and opens no page: run your eval again to get new answers. It takes the same flags as `judgekeeper`, without `--version` and `--debug`.

## fix: see where your judge goes wrong and test a better rule

```
judgekeeper fix [PATH] [--yes] [--new]
```

It needs a result (enough marks of each kind). Each run does the next step:

| What is there | What `judgekeeper fix` does |
|---|---|
| No new rule in `.judgekeeper/fix/rule.txt` | Sets some of your marks aside, hidden (about 30% of each group: your judge's passes and fails, where you agree with it and where not; at least 5 marked Pass and 5 marked Fail). On the other marks: where your judge goes wrong (too easy or too strict, mistakes near the pass mark, long answers, words found in many of its mistakes) and `.judgekeeper/fix/mistakes.md`, each mistake with your mark, its grade, the question, the answer, your note and its own reason, fenced as data. Where your judge's rule is written (file and line) |
| A judge with a score and a pass mark | Also tests the pass mark that fits the other marks best on the hidden marks, with the saved scores: free, no AI call. Shown when it is better or safe to try |
| A new rule in `rule.txt` | Checks it (empty, a template part dropped or added: refused; a big change or text copied from an answer: said), says how many AI calls the test makes, and asks `Go ahead? [y/N]` (without a terminal, `--yes`). Then it asks your judge about the hidden answers, once with the old rule and once with the new one, in the same run, and gives the result |
| A judge whose rule judgekeeper can't swap in | Says so: change the rule yourself, run your eval and `judgekeeper check` |

| Flag | What it does |
|---|---|
| `PATH` | Your project folder (default: this folder) |
| `--yes` | Without a terminal: go ahead and test the new rule (it makes AI calls, paid with your own key) |
| `--new` | Hide a new set of your marks to test rules on |

The hidden marks stay hidden: nothing prints them or writes them anywhere but `.judgekeeper/fix/split.json`, so a new rule is never written from them. They stay the same until `--new`.

**The result**, from the hidden marks: fixed (the old rule was wrong, the new one right) and broke (the other way round).

| Result | When |
|---|---|
| Better / Worse | The exact two-sided sign test on fixed against broke, at 5% |
| Safe to try | Else, a non-inferiority test (Tango's score test for paired proportions, one-sided 2.5%) rules out the new rule being more than 10 points worse |
| Can't tell yet | Else; it says whether it leans toward better, looks the same, or looks worse |

Each extra test on the same hidden marks is stricter (the levels divided by the number of tests), so trying rule after rule can't turn a coincidence into "better". Over all tries on one set, a wrong "safe to try" stays under about 1 in 20. After a "can't tell yet" that leans toward better, it asks once for a few more marks (7 when about 10 are hidden, 9 when about 15): they join the hidden marks and the same rule is tested again. After 3 rules, 10 new marks become a new set of hidden marks.

Your judge's rule is swapped in by judgekeeper when it asks: promptfoo's assertion value, a DeepEval GEval's evaluation steps (or criteria), an Inspect scorer's instructions, an MLflow `make_judge`'s instructions or a `Guidelines` text. A judge whose rule can't be swapped (a table, your own code, a registered or built-in MLflow judge) is told to change the rule itself, run its eval and `judgekeeper check`. judgekeeper never changes your files. Each test is saved: the rule in `.judgekeeper/rules/<hash>.txt`, and a line in `history.jsonl` (the rule's hash, the counts and the result; no answer text). `report.html` has a Fix section and a History row for each test.

**Exit codes:** 0 the step is done, 3 you are needed (more marks, a rule to change, or the question needs your answer), 2 a usage error.

## check: re-check your judge after a change

```
judgekeeper check [PATH] [--yes]
```

Run it after you change your judge or update your eval tool, and run your eval. It needs a result (enough marks of each kind). It compares the judge in your newest results with the one your marks were made on:

| What changed | Noticed |
|---|---|
| The model, or models | Yes |
| The rule | Yes |
| The grading prompt | Yes |
| The pass mark | Yes |
| The temperature | Yes |
| The endpoint | Yes |
| One judge or several (a panel), and the voting rule | Yes |
| An agent judge's settings | Yes |
| The eval tool's version | Yes |
| A switch to another eval tool | No: it says your results now come from another eval tool and that it can't compare judges across two eval tools, and gives no result. Run `judgekeeper` to start fresh |
| Your app's answers | No, on purpose: marks are tests for the judge, so a re-check grades the answers you marked |

| Flag | What it does |
|---|---|
| `PATH` | Your project folder (default: this folder) |
| `--yes` | Without a terminal: go ahead and ask your judge (it makes AI calls, paid with your own key) |

When something changed, it re-checks the new judge on your marks. Free first: answers you marked whose exact text is in your newest results already have the new judge's grade. For the rest it asks your own judge, through your own eval tool and with your own key: it says how many answers and AI calls that is, and asks `Go ahead? [y/N]` (Enter is No). Without a terminal it needs `--yes`, else it stops before any call (exit 3). It asks about each answer twice and compares the first grade; the second shows how often your judge changes its own grade, so a small difference can be told from that. Then, for the answers you passed and those you failed, how many of your marks the old and the new judge got right, how many turned wrong and how many turned right, and a result from a range on that change: "Worse" (the whole range is a drop), "No drop bigger than 20 points" (its low end is above that), or "Not sure". It always says the worst drop the marks could hide. Each group is checked on its own. In about 1 check in 10 at most, coincidence alone flags a drop in one of the two groups; mark more answers before acting on a small one. The rates `history.jsonl` and the report keep are corrected for how the marks were picked, the same as the result's. Each check is a line in `.judgekeeper/history.jsonl` (no answer text) and a row in the report's History. After a "Worse", your marks keep testing the new judge against the old one: every `check` says it is worse until you go back to the old judge or change it again.

**Exit codes:** 0 no drop bigger than 20 points, not sure with a smaller drop, or nothing changed; 1 worse, or not sure with a drop bigger than 20 points; 3 you are needed (not enough marks, nothing could be re-checked, or the question needs your answer), 2 a usage error.

## How the numbers are worked out

**What it checks first, for free.** Before you mark anything, `judgekeeper` looks at the judge's own grades: no marks, no AI call, no key. It says what it found, one line each:

- **No real decision.** The judge's call failed (DeepEval's `error`, or no score with `success` false; promptfoo's `graderError`, or in older files its grader-failure reasons such as "API error:"; Inspect AI's `grader_failed`, or a sample that errored before it was scored; MLflow's `feedback.error`), its reply could not be read (promptfoo's "Could not extract JSON" or "Error parsing output"; Inspect AI's "Grade not found in model output"), or there is no decision at all (a blank cell). These answers are left out, and it says what your eval tool counted them as: promptfoo and DeepEval count them as fails.
- **Checked nothing.** A DeepEval metric whose judge returned nothing to check scores a full 1.0 and passes (its logs show an empty `Verdicts:` list). Left out too.
- **Passed an empty answer.** The app's answer is empty and the judge passed it. Kept: it is a real decision, and a good one for you to mark.
- **The same grade for every answer.** The judge passed (or failed) all of them.
- **The reason says the opposite.** The judge's reason starts with PASS, PASSED, FAIL or FAILED, or its last `verdict:`, `grade:`, `result:`, `decision:`, `final verdict:` or `final answer:` says pass, fail, correct or incorrect (or Inspect AI's `GRADE: C` or `GRADE: I`), and either of them is the other grade. No other words count, so "does not fail" or "partially correct" are never flagged. Skipped for a judge that grades with a score and a pass mark.

None of these stops it. When nothing is found it says every answer got a clear Pass or Fail. The answers found are listed in `.judgekeeper/judge-check.csv` and `judge-check.json`.

**Which answers you mark.** From the newest results it takes every answer with a clear Pass or Fail, counted once (the same input and output; the newest file wins). With too few answers for a first result, it says so and says how to make more with your own eval tool. The page shows the answers in blocks of 10 in a seeded order, 5 from the judge's passes and 5 from its fails, so you see both kinds early. Your marks decide Pass and Fail; the judge's grades only decide how answers are picked.

**The result.** TPR (of the answers you passed, how many your judge passed), TNR (of the answers you failed, how many it failed) and the real pass rate are corrected for showing far more of the judge's fails than the pool holds: worked out per group and weighted by the group's size. Their ranges come from Jeffreys draws: each group's share of answers you marked Pass gets the distribution Beta(passes + 0.5, marked − passes + 0.5); 20,000 pairs of draws, with a fixed seed so the same marks always give the same ranges, go through the same formulas, and a range is the middle 96% of what comes out (widened, if needed, to hold the number itself). The 96% was chosen by a coverage check, not assumed: [`docs/examples/coverage/coverage.md`](examples/coverage/coverage.md) simulates thousands of checks for judges that pass 50%, 70% and 90% of answers, agree weakly to strongly, and 10 to 40 labels per group. At 96% the ranges held the true value at least 93.6 times in 100 in every case and 96.2 on average; 95% fell to 91.6 in one case. The ranges before (Wilson at 97.5% per group, joined at the corners) held it 99.1 times in 100 on average: too cautious, so they were wider than needed; the ranges now are 27.1% narrower on average. On real data too: on 5 real judges from 3 public datasets, with 25 + 25 labels, the TPR and TNR ranges held the value worked out from all of the dataset's human labels in 96.0 checks in 100 on average (lowest 94.6, highest 98.4), over 1,000 checks per judge: [`docs/examples/real-data-check/report.md`](examples/real-data-check/report.md). Kappa is Cohen's kappa on the weighted table (your real mix of answers), with its range from the same draws. Kappa moves with how many answers pass, so it is in the report's details only and never decides the result.

**What it says.** The terminal and the report show "You passed: your judge also passed about N% (could be A% to B%)" and the same for Fail, then "These are estimates from N marked answers." A side whose range is more than 40 points wide says "too early to tell". One result line follows the ranges, never a number alone: "Your judge agrees with you often enough to use." when the low end of both ranges is at least 80%; "Your judge passes too many answers you would fail." (or "fails too many answers you would pass.") when a range stays below 80%; "Too early to tell: mark more answers." while a side is too early; else "Can't tell yet if your judge is good enough. Marking more answers will tell." Under the result, where it goes wrong: which side most of its mistakes are on, and words found in many of them.

## What it reads

It looks only inside the folder, to a depth of four folders, skipping `.git`, `node_modules`, virtual environments and hidden folders (except `.deepeval`, and `.judgekeeper/records/`, where `judgekeeper.record()` writes). It stops after 5,000 files or 2 seconds and, when it found nothing, says so. It does not follow symbolic links, and results files over 200 MB are listed, not read. A results file with no LLM-as-a-judge in it (checks written in code, DeepEval metrics with no model, promptfoo's table output) is left out with one line; an empty file or one it can't open is named. When it finds nothing, it says how deep it looked, names the results-like files it left out (further down, a link, or in the folder above) with the command that reads one, and, run from a subfolder of a project (a folder above with `pyproject.toml`, `package.json` or `.git`), reads the project folder instead. A big file says how far reading has got on stderr every few seconds after the first two. From an MLflow experiment it reads the newest 30,000 traces and says so when there are more (reading each trace takes about a millisecond). The marking page gets the answers up to the furthest one marked and the next 100, never the whole pool. Your eval tool's files are only read, never changed.

| Tool | How it is found | What is read |
|---|---|---|
| promptfoo | `promptfooconfig.yaml`, `.yml` or `.json` | JSON results files (`promptfoo eval -o` or `promptfoo export eval`) |
| DeepEval | `.deepeval/`, or `deepeval` in `pyproject.toml` or `requirements*.txt` | `test_run_*.json` (in `DEEPEVAL_RESULTS_FOLDER` when it points inside the folder, or any results folder), else DeepEval's copy of its newest run, `.deepeval/.latest_run_full.json` |
| Inspect AI | `logs/`, or `inspect-ai` in the dependencies | `.json` logs, and `.eval` logs with the `inspect` extra. Also `INSPECT_LOG_DIR` inside the folder |
| MLflow | `mlruns/` or `mlflow.db` | The local store, with the `mlflow` extra |
| A CSV or JSONL file | A CSV, TSV or JSONL file at most two folders deep with `input`, `output` and `verdict` columns | That file |
| `judgekeeper.record()` | `.judgekeeper/records/*.jsonl` | The lines your eval code saved ([below](#record-save-your-own-judges-verdicts-with-one-line)) |

### promptfoo

```
promptfoo eval -o results.json
judgekeeper
```

Tested with promptfoo 0.120 to 0.124. Your promptfoo config does not change. When promptfoo's results are only in its own database, `judgekeeper` prints the `promptfoo export eval` commands that save them to a file (they run no test and cost nothing).

`--metric` names the judge: an assertion's `metric:` if it has one, otherwise its type (`llm-rubric`, `g-eval`, `factuality`, `model-graded-closedqa`, `model-graded-factuality`, `answer-relevance`, `context-faithfulness`, `context-recall`, `context-relevance`, `conversation-relevance`, `search-rubric`). With only one such judge in the file you can leave it out; with several, judgekeeper asks which. Other assertions (`contains`, `javascript`, ...) are code checks: they are ignored, with a note. Item ids: each test's `description` when every test has a unique one, otherwise a hash of the test's vars (not its output, which can differ between repeats). With several prompts, ids get `#prompt<n>`.

**Traps.**

- **A human rating overrides the row's `success` and `pass`.** judgekeeper never reads the judge's grade from them: it reads the model-graded component itself.
- **`--repeat` rows carry no repeat index.** promptfoo removes `__repeatIndex` before saving and gives every repeat its own `testIdx` (with the same `promptIdx` and identical vars), so `testIdx` does not identify a test. judgekeeper groups rows by item id and `promptIdx` and numbers the repeats in the order they appear in the file. If your outputs differ between repeats (no provider cache), each item keeps the output of its first repeat.
- **The default grader is not recorded.** With no `provider` on the assertion, the test's `options`, `defaultTest.options` or `defaultTest.provider`, promptfoo grades with its built-in default model and the results file does not say which. Those grades get an unknown model, and judgekeeper says so. Set the grader explicitly (below); the temperature is recorded only when the provider config carries it.
- **A grader set with `--grader`** is saved without its provider, only its model name. judgekeeper records that model, leaves the provider unknown and says so.
- **The prompt hash** is the assertion's `value` (the rubric) plus `rubricPrompt` when set. For llm-rubric, promptfoo also saves the exact text it sent the grader (`renderedGradingPrompt`): with the answer and the test's vars put back as placeholders, that is the grading template, and when it is the same on every row its hash is the prompt hash, so a change in promptfoo's own grading prompt shows too. A different rubric per test gives a different hash per answer.
- **Cached grades.** A grade promptfoo replayed from its cache (`cachedResponse`) may be an old reply; judgekeeper says how many there are.

```yaml
defaultTest:
  options:
    provider:
      id: openai:gpt-4.1-mini
      config:
        temperature: 0
```

### DeepEval

```
export DEEPEVAL_RESULTS_FOLDER=deepeval-results
deepeval test run test_judge.py
judgekeeper --metric "Correctness [GEval]"
```

Tested with DeepEval 3.9.9 to 4.2.8. Your test code does not change. DeepEval has no `--output-file` flag. It writes `.deepeval/.latest_run_full.json`, overwritten by every run, and one `test_run_<YYYYMMDD_HHMMSS>.json` per run in a results folder when you set one (`DEEPEVAL_RESULTS_FOLDER`, or in Python `evaluate(..., display_config=DisplayConfig(results_folder="deepeval-results"))`). Results are saved only when tests run through `deepeval test run` or `evaluate()`: calling a metric's `measure()` directly saves nothing. `--metric` is the metric's `name` as it appears in `metricsData` (GEval metrics are named `"<name> [GEval]"`). The grade is the metric's `success`; with `--pass-if "score>=0.7"` judgekeeper applies that rule to `score` instead. A GEval judge built with evaluation steps and no criteria is shown by its steps.

**Traps.**

- **Default test case names are positional.** Without `LLMTestCase(name=...)`, DeepEval names cases `test_case_0`, `test_case_1`, ... by order, which is not an id. judgekeeper then makes each id from the case's `input` and `actual_output` and warns. Those ids only line up across runs if the outputs are the same in every run; name your test cases for stable ids.
- **The rubric lives in `verboseLogs`.** For GEval, the prompt hash covers the `Criteria:`, `Evaluation Steps:` and `Rubric:` parts of `verboseLogs`, not the per-item `Score:` line. Metrics without those parts get an unknown prompt hash.
- **Temperature is not written.** The judge's model comes from `evaluationModel`; DeepEval does not store the temperature, so it is recorded as unknown. The provider comes from the suffix DeepEval adds to the model's name (`claude-sonnet-4-6 (Anthropic)`, `my-deployment (Azure)`, `gemini-... (Gemini)`); a bare name is OpenAI, since DeepEval builds an OpenAI model for any plain string.
- **An empty answer.** DeepEval refuses an empty answer and saves an error instead, so it counts as no real decision.
- **`DEEPEVAL_LOCAL_STORE=sqlite`** writes `deepeval.db` and no JSON. Leave it unset.

### Inspect AI

```
inspect eval task.py
judgekeeper --metric model_graded_qa
```

Tested with Inspect AI 0.3.242 to 0.3.278. Your task does not change. Logs land in `./logs` (or `INSPECT_LOG_DIR`). `.json` logs are read directly. `.eval` logs (Inspect's default, a zip archive) need the optional extra, installed in your project's environment: `pip install "judgekeeper[inspect]"`. Without it, convert first (`inspect log dump logs/x.eval > log.json`), or write JSON logs with `--log-format json`. To read one log, give its path: `judgekeeper logs/log.json`. `--metric` is the scorer's name, the key under `samples[].scores` (`model_graded_qa`, `model_graded_fact`, your `@scorer` name). Item ids are `samples[].id`; runs are `samples[].epoch`.

**Traps.**

- **Score values.** `C` reads as pass and `I` as fail. `P` (partial credit) has no default: map it with `--label-map P=fail` (or `P=pass`), otherwise judgekeeper stops and lists the values it cannot read. Numeric values need `--pass-if`, e.g. `--pass-if "score>=0.5"`.
- **Several values at once.** A scorer whose value is a dict (rubric and checklist graders report this way, e.g. `{"accuracy": "C", "tone": "I"}`) is read as one judge per key, named `<scorer>.<key>` (`rubric.tone`); choose one with `--metric`.
- **Agent runs.** Each sample's `messages` are kept as the records' `trajectory` (OpenAI-style steps), so two runs that end in the same answer by different steps stay two answers.
- **Fingerprint.** The grader's model and temperature come from `eval.model_roles.grader` when the task uses the grader role; otherwise from the scorer's `model` option, with temperature unknown. The prompt hash covers the scorer's `template` and `instructions` options from `eval.scorers[]`; one left unset stands for Inspect's default for that scorer. The rendered prompt in `score.metadata.grading` is never hashed: it holds each sample's text. If you upgrade Inspect and its default template changes, the hash does not; set `template` explicitly to track it.
- **`--no-log-samples`** logs have no samples and cannot be read.

### MLflow

```
pip install "judgekeeper[mlflow]"
judgekeeper --experiment my-app-eval --metric correctness
```

Tested with MLflow 3.10 or newer: `judgekeeper[mlflow]` allows MLflow 3.1, but 3.10 is the oldest tested. Install the extra in your project's environment. judgekeeper reads the judge's assessments MLflow already stores on your traces, from the local store in your project folder: `mlflow.db` (through a temporary copy, never opened itself) or an `mlruns/` folder (`--tracking-uri` picks one when there are both; at a terminal it asks). A local `mlruns` folder needs MLflow's folder-store setting from MLflow 3.16 on: judgekeeper switches it on (`MLFLOW_ALLOW_FILE_STORE=true`) for its own read only, and leaves your own value alone when you set one. `--experiment` takes a name or an id. `--metric` is the assessment name (your scorer's name). An LLM judge's assessment has `source.source_type` `LLM_JUDGE` and `source.source_id` set to the model (`openai:/gpt-4.1-mini`).

**Traps.**

- **Trace ids change every run.** `evaluate` with a `predict_fn` logs new traces each time, so a trace id is not an item id. judgekeeper makes the id from the trace's request input (a hash), so the same dataset row maps to the same item in every run. Two rows with the same input are one item.
- **Which run.** A judge assessment's run is its `mlflow.assessment.sourceRunId` metadata, which `evaluate` sets. Assessments logged outside `evaluate` have none and form one extra run, listed last, with a note.
- **Prompt and temperature.** The fingerprint has the model from `source.source_id` (the provider is the part before `:/`) and, for registered scorers, `scorerName@scorerVersion` as the rubric version. A `make_judge` (MLflow 3.14 and later) saves its instructions with each assessment: they are the judge's rule, hashed into the prompt hash, so a changed rule is a new judge. Other judges' prompts are not saved with their assessments, so for them the prompt hash is unknown. Temperature is unknown.
- **Errors.** A `Feedback` with an `error` (a judge that timed out) is an `error` grade, with the error code and message as its reason.
- **CODE assessments** (a scorer that returns a bare bool or number) are not a judge and are ignored, with a note. Expectations (ground truth) are not grades and are not read.
- **Span-level assessments.** An assessment logged on one span inside a trace (`span_id`) judges a step, not the answer. Only trace-level assessments (and those on the root span, where `evaluate` puts them) are read; span-level ones are left out with a note, unless `--metric` names a judge that is only on spans.
- **A copied `mlruns/` folder.** A folder store saves where each trace's files are as a full path. Copied or cloned to another computer, MLflow looks for them at the old path and drops every trace it cannot find. judgekeeper reads them from the store's own folder instead, and says how many answers it left out when their files are not there either.
- **MLflow's own problems, not judgekeeper's.** `mlflow.genai.evaluate` on an `mlflow.db` store can drop traces when it runs out of database connections, while still saying the evaluation completed (fewer parallel workers, `MLFLOW_GENAI_EVAL_MAX_WORKERS=4`, avoids it); and an experiment made in `mlflow.db` keeps its artifacts in `./mlruns/` by default (give the experiment its own `artifact_location`). judgekeeper only counts the traces that were saved.

### A CSV or JSONL file

A CSV, TSV or JSONL file with `input`, `output` and `verdict` columns (`judge_verdict` or `judge` work as the grade column too); a `model` or `judge_model` column names the judge's model, and `id` and `reason` are read when they are there. One file per judge or criterion. It prints the counts, the pass/fail split and the first 3 rows, so a wrong table shows. Give its path when it is deeper than two folders: `judgekeeper results/judge.csv`.

**Results in a format of its own.** When it finds no eval tool's results but a recent JSON, JSONL or CSV file (changed in the last 90 days, at most four folders deep) that holds, at any depth, a score-like key (`score`, `scores`, `verdict`, `pass`, `passed`, `success`, `label`) next to an input-like and an output-like key, or when you give it such a file, it shows the file's paths (never their values) and how it would read them: what one answer is, the input, the answer, the score, the reason, the id and the judge's model. It asks whether that is right, and then only what the file cannot tell (which of several judges, the pass mark when the scores are not between 0 and 1, whether to leave out answers with an error). A part is the judge's grade only when its name says so (`score`, `verdict`, `grade`, `label` and the like, or a part inside a judge object) and most of its values are grades: pass or fail, true or false, yes or no, correct or incorrect, or numbers from 0 to 100. Ids, free text and a judge's settings (its pass mark, its criteria's text, a run id) never are. A reading it is not sure of (a part told by its values alone, or one answer from a file that holds a list of many) is never accepted by `--yes`: run it in a terminal to check it. With your yes it saves how to read the file in a `[start]` table of `judgekeeper.toml`, which it reads first next time. When the file cannot be read this way, it says so: turn it into a CSV with the columns `id`, `input`, `output`, `verdict` (pass or fail) and `reason`, one CSV per judge, and run `judgekeeper <the CSV>`; or save your judge's grades with [`judgekeeper.record()`](#record-save-your-own-judges-verdicts-with-one-line).

### judgekeeper.record()

When your judge runs in your own code, one `judgekeeper.record()` line saves each grade in `.judgekeeper/records/` ([below](#record-save-your-own-judges-verdicts-with-one-line)). `judgekeeper` reads every file written by the newest file's judge (one eval run can be many processes, so many files; a newer file wins for a repeated answer). Several judge names: it asks which, `--metric` answers. A last line cut short is left out; a file it cannot read is left out, and it says so.

## How grades are read

One normaliser reads every grade from your judge (with `--pass-if` and `--label-map`) and every mark. It turns a raw judge output into `pass`/`fail` or `error`, plus a reason:

- a bool: `True` is pass;
- a string, case-insensitively, through the label map. Defaults: `pass`/`fail`, `true`/`false`, `yes`/`no`, `correct`/`incorrect`, `right`/`wrong`, `1`/`0`, and a leading `PASS` or `FAIL` token (`PASS: looks right`). `--label-map "good=pass,bad=fail"` adds entries;
- a number, through a required `--pass-if` rule: `score>=0.5`, `>`, `<=`, `<`, `==`. The name is free text, except that for a dict it names the key to read (`relevance>=3`). Integers `1`/`0` follow the label map when no rule is given;
- a `(grade, reason)` tuple or two-element list;
- a dict with the grade under `verdict`, `pass`, `passed`, `label` or `score` (first found) and the reason under `reason`, `rationale`, `explanation` or `comment`.

A value that looks like a grade but is not in the map (`good`), or a number with no rule, is a usage error that lists every such value seen. judgekeeper never guesses. A judge that raised, returned nothing (None, an empty string, NaN) or returned something unreadable (a dict with no grade key, a list of three) is recorded as `error`, never as fail: errors are left out of every agreement number.

## Records format

judgekeeper's own format for judge results: one judged answer per line of a JSONL file (CSV and TSV work too). Use it when your judge saves its results in a way judgekeeper does not read: write these lines (or let [`record()`](#record-save-your-own-judges-verdicts-with-one-line) write them), then run `judgekeeper`. Field names follow OpenInference annotations, so other tools' exports map onto it by renaming. Only a grade is needed in practice; every field is optional. The smallest useful line:

```
{"name": "Safe wording", "input": "Do you ship to Canada?", "output": "Yes, in 5 to 8 working days.", "label": "pass"}
```

| field | meaning |
|---|---|
| `schema_version` | the format version: `2` now. A line without one is version 1, which has the same fields minus `metadata`, `rule`, `trajectory`, `outcome` and `app_version` |
| `target_id` | the item. Missing: derived from `input` and `output` (and `trajectory`, when there is one) |
| `name` | the judge, metric or criterion (default `judge`); choose one with `--metric` |
| `annotator_kind` | `LLM` (a judge's grade), `HUMAN` (a label) or `CODE` (ignored). Case-insensitive; `LLM_JUDGE` reads as `LLM`. Default `LLM` |
| `label` | the grade or mark: `pass`/`fail`, `true`/`false`, a bool, or anything `--label-map` maps |
| `score` | a number; read as the grade with `--pass-if`, or when `label` is empty |
| `explanation` | the judge's rationale |
| `run` | repeat index, or empty |
| `input`, `output` | the item's text (or any JSON) |
| `evaluator` | the judge's identity: `{provider, model, prompt, temperature, version, rule}`; `version` is the rubric version, `prompt` is hashed. `rule` is the judge's rule in words (GEval criteria and steps, an llm-rubric value): `judgekeeper` shows it as the judge's rule, and it is hashed into the prompt hash when there is no `prompt` or `prompt_hash`. Also `prompt_hash`, `snapshot` and `endpoint` |
| `created_at` | when the grade was made |
| `metadata` | an open object for anything else: a criterion name, a run id, an A/B version. Kept; never part of the judge's identity |
| `trajectory` | for agents: the steps that led to the output, as OpenAI-style messages (`role`, `content`, `tool_calls` with `id`, `name` and `arguments`, `tool_call_id`). Kept in the frozen anchor set, because hosted traces expire; not shown on any page yet |
| `outcome` | for agents: an automatic check of the result, `{passed, score, source, detail}`, e.g. `{"passed": true, "source": "unit tests"}` |
| `app_version` | the version of the app or agent that gave the answer |

Fields judgekeeper does not know are kept, at the top level and inside `evaluator`; a file of a newer version is read as far as this version understands it, with one warning. A line over 1 MB is kept, with a warning. The rules are published as a JSON Schema (draft 2020-12): [records.schema.json](records.schema.json), also inside the package as `judgekeeper/schemas/records.schema.json`. Example files: [minimal.jsonl](examples/records/minimal.jsonl) (four fields per line), [full.jsonl](examples/records/full.jsonl) (every field) and [with-human-labels.jsonl](examples/records/with-human-labels.jsonl).

## record(): save your own judge's verdicts with one line

When your judge runs in your own code and saves nothing judgekeeper reads, add one line right after it gives each grade, in your eval code:

```python
import judgekeeper
judgekeeper.record(input=question, output=answer, score=0.82, pass_mark=0.5,
                   reason=reason, judge="claude-opus-5", rule=criteria, name="Safe wording")
```

Then run your eval once and `judgekeeper`: it finds the records. Install judgekeeper inside your project's environment (`pip install judgekeeper`) for the import.

| Argument | What |
|---|---|
| `input`, `output` | The question and the answer the judge looked at: text or any JSON value (anything else is written as text) |
| `verdict` | `pass` or `fail`, or `True` or `False` |
| `score`, `pass_mark` | Instead of `verdict`: a number, and the mark it must reach to pass (pass when `score >= pass_mark`). The pass mark is kept in `metadata`. A score with no pass mark is kept without a grade (then `--pass-if` reads it) |
| `reason` | The judge's reason |
| `judge` | The judge's model, e.g. `claude-opus-5` |
| `rule` | The judge's rule or criteria, shown as "Your judge's rule" |
| `name` | Which judge or criterion (default `judge`); with several names, `judgekeeper` asks which to check |
| `temperature`, `id`, `metadata` | The judge's temperature, the answer's id (else one is made from the input and output), and a dict of anything else |

Each call writes one line in the [records format](#records-format) (version 2, `annotator_kind` `LLM`) to `.judgekeeper/records/<name>-<date>-<process id>.jsonl` under your project root: the nearest folder upward from where your eval runs that has `judgekeeper.toml`, `pyproject.toml`, `setup.py`, `.git` or a `requirements*.txt` (never your home folder), else the current folder. One file per process, so evals that run in several processes never write to the same file. `judgekeeper` reads the files of the same judge together, as one set: an answer saved in more than one file (a second run, or the same day again) counts once, with the grade from the newest file. Each line is written whole and the file closed at once; a lock keeps threads' lines apart.

A score or pass mark may be any real number: an int or float, a numpy number, a `Decimal`, or text such as `"0.8"`. It never breaks your program: any error inside it is caught and it returns nothing. The first grade it can't save is logged to the `judgekeeper` logger at once; any more are counted, and the count is logged when your program ends. It uses only Python's standard library, and `import judgekeeper` loads nothing else until you call it. The file holds your inputs and outputs: use it in your eval code, not in code that serves real users. `JUDGEKEEPER_RECORD=0` (or `false`, `off`, `no`) turns it off.

**Without the import, or in another language.** Copy one of these into your eval code. The Python function, `jk_record`, takes the same arguments as `judgekeeper.record()` and writes the same lines, with nothing to install; the TypeScript one does the same for Node.js (`jkRecord(input, output, { score, pass_mark, ... })`, the same names in its options). Run them from your project folder: unlike `record()`, they do not look upward for the project root.

```python
# Saves each judge grade for judgekeeper; run it from your project folder. Standard library only.
# It takes the arguments of judgekeeper.record() and writes the same line.
import json, os, re, time
def jk_record(input=None, output=None, *, verdict=None, score=None, pass_mark=None,
              reason=None, judge=None, rule=None, name=None, temperature=None, id=None,
              metadata=None):
    try:
        name, now = "judge" if name is None else str(name), time.gmtime()
        meta = dict(metadata or {})
        if pass_mark is not None:
            meta.setdefault("pass_mark", pass_mark)
        label = verdict
        if isinstance(verdict, bool):
            label = "pass" if verdict else "fail"
        elif isinstance(verdict, str) and verdict.strip().lower() in ("pass", "fail"):
            label = verdict.strip().lower()
        elif verdict is None and score is not None and pass_mark is not None:
            label = "pass" if score >= pass_mark else "fail"
        line = {"schema_version": 2, "target_id": None if id is None else str(id), "name": name,
                "annotator_kind": "LLM", "label": label, "score": score,
                "explanation": None if reason is None else str(reason), "run": None,
                "input": input, "output": output,
                "evaluator": {k: v for k, v in (("model", judge), ("temperature", temperature),
                                                ("rule", rule)) if v is not None},
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", now)}
        if meta:
            line["metadata"] = meta
        folder = os.path.join(".judgekeeper", "records")
        os.makedirs(folder, exist_ok=True)
        file = re.sub(r"[^A-Za-z0-9._]+", "-", name).strip("-.")[:60] or "judge"
        file += f"-{time.strftime('%Y-%m-%d', now)}-{os.getpid()}.jsonl"
        with open(os.path.join(folder, file), "a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(line, ensure_ascii=False, default=str) + "\n")
    except Exception:
        pass  # a record never stops your program
```

```typescript
// Saves each judge grade for judgekeeper; run it from your project folder. Node.js only.
// It takes the arguments of judgekeeper.record() and writes the same line.
import { appendFileSync, mkdirSync } from "node:fs";
import { join } from "node:path";

type JkFields = { verdict?: unknown; score?: number; pass_mark?: number; reason?: string;
  judge?: string; rule?: string; name?: string; temperature?: number; id?: string | number;
  metadata?: Record<string, unknown> };

export function jkRecord(input: unknown, output: unknown, f: JkFields = {}): void {
  try {
    const name = f.name ?? "judge", now = new Date().toISOString();
    const meta: Record<string, unknown> = { ...(f.metadata ?? {}) };
    if (f.pass_mark != null && !("pass_mark" in meta)) meta.pass_mark = f.pass_mark;
    const said = typeof f.verdict === "string" ? f.verdict.trim().toLowerCase() : "";
    let label: unknown = f.verdict ?? null;
    if (typeof f.verdict === "boolean") label = f.verdict ? "pass" : "fail";
    else if (said === "pass" || said === "fail") label = said;
    else if (f.verdict == null && f.score != null && f.pass_mark != null)
      label = f.score >= f.pass_mark ? "pass" : "fail";
    const evaluator = Object.fromEntries(Object.entries(
      { model: f.judge, temperature: f.temperature, rule: f.rule }).filter(([, v]) => v != null));
    const line: Record<string, unknown> = { schema_version: 2,
      target_id: f.id == null ? null : String(f.id), name, annotator_kind: "LLM", label,
      score: f.score ?? null, explanation: f.reason == null ? null : String(f.reason), run: null,
      input, output, evaluator, created_at: now.slice(0, 19) + "Z" };
    if (Object.keys(meta).length) line.metadata = meta;
    const folder = join(".judgekeeper", "records");
    mkdirSync(folder, { recursive: true });
    const file = name.replace(/[^A-Za-z0-9._]+/g, "-").replace(/^[-.]+|[-.]+$/g, "")
      .slice(0, 60) || "judge";
    appendFileSync(join(folder, `${file}-${now.slice(0, 10)}-${process.pid}.jsonl`),
      JSON.stringify(line) + "\n");
  } catch { /* a record never stops your program */ }
}
```

## Unknown judge fields

Every fingerprint field except `created_at` may be unknown: provider, model, snapshot, prompt hash, rubric version and temperature are `null`, and an unknown endpoint is the string `"unknown"` (because `endpoint: null` already means the provider's default endpoint). Files from earlier versions still load: a missing field reads as unknown, except a missing `endpoint`, which reads as the provider default.

## The .judgekeeper/ folder

judgekeeper writes only inside `.judgekeeper/` in your project. Every string from a results file is scrubbed of credentials before it is written. It does not write through links: if `.judgekeeper/`, or anything in it, is a link (a symlink, as a cloned repository can hold), it stops and says which, before writing anything. Every file is written as a new file that replaces the old one. Your own `.gitignore` is never changed: the folder holds your answers' text, so commit it only if your data may live in your repository.

| File | What it holds | When it is written |
|---|---|---|
| `.gitignore` | `*`, `!.gitignore`, `!judge.json`, `!history.jsonl`: your answers stay off Git. Never overwritten | When marking first starts, if there is none |
| `judge.json` | Your judge's setup, read from your results: the eval tool and its version, the kind of judge, its models, the rule, the grading prompt, the temperature, the pass mark and the endpoint. Before marking starts it follows your newest results; then it keeps the judge of your marks until `judgekeeper check` re-checks a new one | Only when the setup changes, so a committed `judge.json` changes only when your judge did |
| `judge-check.json`, `judge-check.csv` | What the free check found: the counts, and each answer found with its problem (`error`, `unreadable`, `empty_answer_refused`, `empty`, `nothing_checked`, `empty_answer_passed` or `reason_says_opposite`) | When `judgekeeper` finds your judge |
| `start.json` | The eval tool, the results files used, the judge and its fingerprint, its pass mark, the counts, what was left out and why, the seed and the order of the answers | When marking starts |
| `pool.jsonl` | Each answer to mark: its id, input and output | When marking starts |
| `pool-judge.jsonl` | Your judge's grade on every answer, each line with the full fingerprint | When marking starts |
| `marks.jsonl` | Your marks: a line about the judge first, then one line per click (the answer's id, your mark, the time; no answer text) | On every click |
| `server.json`, `page.json` | The open marking page: its port, its process and a secret that only closes it (never the page's token) | While the page is open |
| `result.json`, `report.html` | The result: every number, the counts of your marks, the fingerprint and the date. The report opens in your browser without a server, with a Fix section and a History | With each result |
| `history/` | Earlier results | When a new result replaces one |
| `history.jsonl` | One line per result, fix test and check: the judge, the counts and the numbers, no answer text | With each result, fix test and check |
| `anchors.jsonl`, `anchors.manifest.json` | The answers you marked, as a frozen set: the manifest holds the counts and a sha256 of the set | With each result |
| `fix/split.json` | Which marks are hidden, the seed, and every test done on them | On the first `judgekeeper fix` |
| `fix/mistakes.md` | Each mistake on the marks you can see, fenced as data | With `judgekeeper fix` |
| `fix/rule.txt` | Your new rule, written by you | By you |
| `fix/runs/` | The grades your judge gave when it was asked about the hidden answers, each line with the full fingerprint | When you say yes to a test |
| `rules/` | Each rule tested, as `<hash>.txt` | With each fix test |
| `results-seen.json` | The judge's setup in the results read last, so a check with nothing new reads nothing again | With `judgekeeper check` |
| `checks/` | The grades your judge gave when `check` asked it, each line with the full fingerprint | When you say yes to a check |
| `verdicts/` | Each judge setup's grades on your marked answers (ids and grades only) | With each check |
| `records/` | Your judge's grades, saved by `judgekeeper.record()` in your eval; `--new` leaves them in place | By your eval |
| `previous-<date>/` | Everything that was here before you started over | On `--new`, or a yes to start over |

## Your API keys

- Your key is used only by your own eval tool, when it asks your judge. judgekeeper has no server: your eval tool's requests go from your machine straight to the provider.
- judgekeeper never prints a key or writes one to a file. Before any text reaches disk or your terminal, the value of `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `MLFLOW_TRACKING_PASSWORD` and any variable ending in `_API_KEY`, `_TOKEN` or `_SECRET` (`DATABRICKS_TOKEN`, `MLFLOW_TRACKING_TOKEN`) is replaced with `[REDACTED]`, as is anything shaped like a provider key (`sk-ant-…`, `sk-…`, `Bearer …`, `Basic …`) and the `user:password@` part of a URL.
- Finding, marking and the result make no AI call and need no key. Before any AI call, judgekeeper says how many calls it makes and asks first (`Go ahead? [y/N]`, Enter is No). Without a terminal only `--yes` says yes.
- Error text is scrubbed too. An unexpected error prints one line, never its own text (it can hold an answer's text), and exits 2; `--debug` adds the traceback, still scrubbed.
- There is no flag that takes a key, and there never will be.

## Exit codes

| exit code | meaning | commands |
|---|---|---|
| 0 | success: the step is done | all |
| 1 | the new judge is Worse, or Not sure with a drop bigger than 20 points | `check` |
| 2 | usage error (bad arguments; grades or marks it can't read; nothing it can use found; an input file that is not UTF-8 text or is damaged; a place it cannot write; a command removed in this version, which says so in one line; a problem judgekeeper didn't expect) | all |
| 3 | you are needed: the `Next:` line says what to do. Also: stopped at a question it cannot ask (no terminal), and the line before says the flag that answers it; nothing went wrong | all |
| 130 | stopped with Ctrl-C: it prints "Stopped." and what was saved before stays saved | all |
