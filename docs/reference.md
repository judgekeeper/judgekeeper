# judgekeeper reference

Every command, file format, flag, exit code and config key. The README has the short version.

- [start: find your results, label, see the result](#start-find-your-results-label-see-the-result)
- [init: a starter rule file](#init-a-starter-rule-file)
- [Anchor sets, judging and the report](#anchor-sets-judging-and-the-report)
- [check: a table in, a report out](#check-a-table-in-a-report-out)
- [How verdicts are read](#how-verdicts-are-read)
- [Bring your own judge](#bring-your-own-judge)
- [Labels from a spreadsheet](#labels-from-a-spreadsheet)
- [label: a local labeling page](#label-a-local-labeling-page)
- [import: promptfoo, DeepEval and Inspect AI results](#import-promptfoo-deepeval-and-inspect-ai-results)
- [import mlflow and import langfuse](#import-mlflow-and-import-langfuse)
- [ScoreRecords: import records and export records](#scorerecords-import-records-and-export-records)
- [Unknown judge fields](#unknown-judge-fields)
- [Your API keys](#your-api-keys)
- [Gate CI on the judge](#gate-ci-on-the-judge)
- [pytest plugin](#pytest-plugin)
- [Migrate to a new judge](#migrate-to-a-new-judge)
- [Attribute a score change](#attribute-a-score-change)
- [Exit codes](#exit-codes)
- [GitHub Action](#github-action)

## start: find your results, label, see the result

```
judgekeeper start [PATH] [--tool NAME] [--metric NAME] [--experiment NAME_OR_ID]
                  [--pass-if RULE] [--label-map MAP] [--judge-model NAME]
                  [--yes] [--new | --review | --ask-again | --try-new-judge | --label-more]
                  [--times N] [--allow-calls N] [--python PATH] [--fields LIST]
                  [--judge-command CMD] [--agent-prompt] [--no-browser] [--port N]
```

Finds the results your eval tool already saved, names your eval tool and your judge, opens a local page where you mark answers Correct or Wrong without seeing the judge's verdict, and shows how often the judge agrees with you. No AI calls unless you say yes. Then your own judge runs through your own tool; judgekeeper never sees your key, it only checks its name: it opens `.env` files only to say which key your judge will use, and keeps only the variable names. It never runs your app. It runs your eval tool only to grade saved answers again, after you say yes.

| Flag | What it does |
|---|---|
| `PATH` | Your project folder (default: this folder), or one results file, which skips the search |
| `--tool NAME` | Which eval tool's results to use when several are found: `promptfoo`, `deepeval`, `inspect`, `mlflow` or `table` |
| `--metric NAME` | The judge (metric, assertion or scorer) to check when the results hold several, as in `import` |
| `--experiment NAME_OR_ID` | MLflow: the experiment to read when several have judge results |
| `--pass-if RULE` | A rule for numeric verdicts, e.g. `score>=0.5`, as in `import` |
| `--label-map MAP` | Extra verdict spellings, e.g. `good=pass,bad=fail`, as in `import` |
| `--judge-model NAME` | The judge's model, when the results do not record it. Saved with `"model_source": "given by you"`. A usage error when the results already name a model |
| `--yes` | Without a terminal, answer every yes/no question with its default (open the page, continue, label anyway). It never picks between tools or judges |
| `--new` | Start a new check: everything in `.judgekeeper/` except `baseline.json` moves to `.judgekeeper/previous-<date>/`. Nothing is deleted |
| `--review` | After a result: review the answers where you and your judge disagree (below). Answers the menu |
| `--ask-again` | After a result: ask your judge again about your labeled answers (below). It shows the plan and asks before any call. Answers the menu |
| `--try-new-judge` | After a result: try the new version of your judge (found in your newest results) on the answers you already marked; it asks before any call (below). Answers the menu |
| `--label-more` | After a result: open the labeling page to label more. Answers the menu |
| `--times N` | How many times each answer is asked about, 1 to 5: default 2 for `--ask-again`, 1 for `--try-new-judge` |
| `--allow-calls N` | Asking again: approve up to N judge calls without the question. Needed without a terminal, and above 1,000 calls at a terminal too; below the planned calls it refuses. `--yes` never approves spending |
| `--python PATH` | Asking again: the Python you run your evals with, for DeepEval, Inspect AI and MLflow (default: the active virtual environment, else the project's `.venv` or `venv`, else the Python running judgekeeper) |
| `--fields LIST` | Asking a DeepEval GEval judge again: the parts it reads, e.g. `input,actual_output` (DeepEval does not save them) |
| `--judge-command CMD` | Asking again: your own judge as a command, with the `--exec` contract (one answer as JSON on stdin, the verdict on stdout). Also for a judge that can't be asked again otherwise |
| `--agent-prompt` | Print a prompt for your coding agent that turns judge results saved in your own format into judgekeeper's table, then exit (below) |
| `--no-browser` | Print the labeling page's link instead of opening a browser |
| `--port N` | Port on 127.0.0.1 for the labeling page (default 8765) |

**What it reads.** It looks only inside the folder, to a depth of four folders, skipping `.git`, `node_modules`, virtual environments and hidden folders (except `.deepeval`). It stops after 5,000 files or 2 seconds and says so. It does not follow symbolic links, and results files over 200 MB are listed, not read.

| Tool | How it is found | What is read |
|---|---|---|
| promptfoo | `promptfooconfig.yaml`, `.yml` or `.json` | JSON results files (`promptfoo eval -o` or `promptfoo export eval`). With a config and no results file, it offers to run `promptfoo export` for you (below), or prints the commands |
| DeepEval | `.deepeval/`, or `deepeval` in `pyproject.toml` or `requirements*.txt` | `.deepeval/.latest_run_full.json`, `test_run_*.json`, and `DEEPEVAL_RESULTS_FOLDER` when it points inside the folder |
| Inspect AI | `logs/`, or `inspect-ai` in the dependencies | `.json` logs; `.eval` logs need `pip install "judgekeeper[inspect]"` in your project's environment. Also `INSPECT_LOG_DIR` inside the folder |
| MLflow | `mlruns/` or `mlflow.db` | The local store, opened read-only. Needs `pip install "judgekeeper[mlflow]"` in your project's environment |
| A plain table | A CSV, TSV or JSONL file at most two folders deep with `input`, `output` and `verdict` (or `judge_verdict`, `judge`) columns | That file; a `model` or `judge_model` column names the judge's model. It prints the counts, the pass/fail split and the first 3 rows, so a wrong table shows |

**No results it can read.** It says so, and does not tell you to run your eval again unless your tool's normal run writes files it reads. It looks for a recent JSON, JSONL or CSV file (changed in the last 90 days, at most four folders deep) that holds, at any depth, a score-like key (`score`, `scores`, `verdict`, `pass`, `passed`, `success`, `label`) next to an input-like and an output-like key, and names it: your judge's results in a format of its own. To use them, turn them into a table with the columns `id`, `input`, `output`, `verdict` (pass or fail) and `reason`, plus `judge_model` when you know the model, one CSV per judge or criterion, and run `judgekeeper start <file>`. It also prints a prompt for your coding agent that writes that table for you (`--agent-prompt` prints it alone). With DeepEval it adds that results are saved only when tests run through `deepeval test run` or `evaluate()`: calling a metric's `measure()` directly saves nothing.

From the newest results it builds the pool: every answer with a clear pass or fail, counted once (the same input and output; the newest file wins, then the majority of its verdicts, a tie counting as fail). With fewer than 30 answers it adds older results from the same judge. Unclear verdicts are left out and counted. A/B comparisons are refused (exit 2). Human labels already in the results are not used. Under 30 answers, or under 5 in either group, it prints the command that makes more with your own tool and asks whether to label anyway.

**The page.** One answer at a time, half from the judge's passes and half from its fails, in blocks of 10 in a seeded order. Keys: `1` Correct, `2` Wrong, `S` skip, `U` undo. The judge's verdict, reason and score never reach the page. Every click is saved at once. "See my result" works at any time. When every answer is labeled or skipped, the result is shown.

**The result.** TPR, TNR and the real pass rate are corrected for showing far more of the judge's fails than the pool holds: worked out per group and weighted by the group's size. Each group's rate has a Wilson interval at 97.5%, so the two hold together at 95% or more. Kappa is Cohen's kappa on the weighted table. A rough check needs 15 Correct and 15 Wrong, a reliable result 25 of each; below the rough check there is no verdict.

**Saved in `.judgekeeper/`.** Every string from a results file is scrubbed of credentials before it is written. Your `.gitignore` is never changed: the folder holds your answers' text, so commit it only if your data may live in your repository.

| File | What | When it is written |
|---|---|---|
| `start.json` | The tool, the results files used, the judge and its fingerprint, the pool counts, what was left out and why, the seed and the queue | When labeling starts |
| `pool-judge.jsonl` | The judge's verdict on every pool answer, as a run file with the full fingerprint on every line | When labeling starts |
| `pool.jsonl` | Each pool answer's id, input and output | When labeling starts |
| `labels.csv` | Your labels, in the `template` shape (a skipped answer has the note `skipped`) | On every click |
| `anchors.jsonl` and `anchors.manifest.json` | The answers you labeled, as a frozen anchor set for `judge`, `baseline` and `gate` | With each result |
| `result.json`, `result.html` | The result: every number, the label counts, the fingerprint and the date; the page opens without a server | With each result |
| `history/` | Earlier results (`result-<date>.json`) and, before a re-check, the check it replaced (`check-<date>/`) | With each result |
| `previous-<date>/` | Everything that was here before `--new`, or before you labeled new answers | On `--new` |
| `again/<date>/` | Asking your judge again: `judge-again-<n>.jsonl` (one run file per time asked, every line with the full fingerprint, plus the tool and its version, the names of setting variables that were set, and `exact` or `close copy` with the reasons), `again.json` (the numbers), and for promptfoo its own `promptfoo.json`, for DeepEval, Inspect AI and MLflow the script's output (`deepeval.jsonl`, `inspect.jsonl`, `mlflow.jsonl`). `result.json` gains an `again` block; an earlier one moves to `history/again-<date>.json` | When you ask your judge again |
| `new-judge-<date>/` | Trying your new judge: `new-judge.json` (the numbers), `new-judge-<n>.jsonl` (one run file per time asked, every line with the full fingerprint and `exact` or `close copy`), the tool's own output (`promptfoo.json`, `deepeval.jsonl`, `inspect.jsonl` or `mlflow.jsonl`), and `confirm/` (the quick check: `start.json`, `pool.jsonl`, `pool-judge.jsonl`, `labels.csv`, `result.json`, `result.html`). `result.json` gains a `new_judge` block | When you try your new judge |
| `review.json` | The review of the disagreements: the answers shown, the seed, your second looks and your choices | On every click of the review |
| `judge-mistakes.csv`, `rule-unclear.csv` | The disagreements you marked "The judge was wrong" or "The rule is unclear": id, input, output, your label, your second-look label, the judge's verdict and reason | On every click after the judge is shown |

**Running it again.**

| What is saved | What `start` does |
|---|---|
| Nothing | Everything above |
| Labeling not finished | "Continue?": the page opens at the next answer |
| A result, and the same results | A menu: review the disagreements, ask your judge again, label more (a new result replaces the old one, which goes to `history/`), or nothing. `--review`, `--ask-again` and `--label-more` answer it |
| A result, and newest results from a new version of the judge (same tool; its model, prompt or temperature changed, or its name changed and you confirm it is the new version; `--metric` names it) | The same menu, with "Try your new judge on your N marked answers" first. `--try-new-judge` answers it |
| A result, and new results from the same tool and judge | A re-check: your saved labels against the judge's new verdicts, shown next to the last result, after saying whether the judge's model, prompt or temperature changed. When fewer than 15 Correct or 15 Wrong of your labeled answers are in the new results unchanged, it offers to label the new results instead |

**Reviewing the disagreements** (no AI call). First you look again at every answer where you and your judge disagree, mixed with as many answers you agreed on (at least 3), with the judge's verdict still hidden: Correct, Wrong or Not sure. Then you see what the judge said on each disagreement, with its reason, and mark it: the judge was wrong, I slipped, or the rule is unclear. Your labels in `labels.csv` never change and stay the main result; the result adds a few lines with the numbers your second-look labels would give and what you called after seeing the judge.

**Asking your judge again.** judgekeeper can have your own eval tool grade the answers you labeled again, with your own judge; your app is not run. Before anything runs it shows a plan, with no API call: the judge, and whether it is exactly your judge, a close copy (and what differs) or can't be asked again (and why); which key your tool will read, by name only (judgekeeper reads the names in `.env` files, never their values); setting variables that change the judge (`OPENAI_TEMPERATURE`, `*_MAX_TOKENS`, `*_BASE_URL`, ...); the judge calls (labeled answers × times × calls per answer for that judge type); a cost range at prices dated in judgekeeper (`prices.py`; never fetched); and what the run touches. For DeepEval, Inspect AI and MLflow, a small script judgekeeper ships runs with your Python to build your judge and check it, with no call. Then it asks "Go ahead? [y/N]" (default No; without a terminal, `--allow-calls N` answers it). After No it says "Your judge was not called; nothing was spent."

promptfoo re-grades your saved answers itself: judgekeeper writes two temporary files next to your promptfoo config (`.judgekeeper-regrade.promptfoo.json` and `.judgekeeper-regrade.tests.json`: each labeled answer as a fixed `providerOutput` with its own model-graded assertions and grader copied unchanged) and removes them afterwards, also after an error or Ctrl-C. promptfoo runs with `--no-cache --no-write --no-share` and its telemetry, update check, sharing and logs off; `--grader` is never passed. It uses your project's promptfoo when its version is the one that made your results, else `npx promptfoo@<that version>` after asking. For llm-rubric, an answer whose new grading prompt is not byte for byte the saved one is not counted.

For DeepEval, Inspect AI and MLflow, the same small script runs your judge with your Python, in your project folder, and writes nothing into your tool's files. DeepEval: each answer's metric is built again (a GEval answer with its own saved steps, so no steps call) and `metric.measure()` is called directly, never `deepeval.evaluate()`; DeepEval's telemetry is off and `CONFIDENT_API_KEY` is not passed on, so nothing is uploaded; DeepEval's own cost of the calls is shown when it reports one. Your results do not say how your code chose the judge's model, so DeepEval's own settings pick it first; when they pick another model, the judge is built from the model name in your results (a plain OpenAI name, or a name DeepEval marks `(Anthropic)`, `(Gemini)`, `(Deepseek)`, `(Grok)` or `(KIMI)`) and used only when DeepEval reports exactly that name. A judge that needs more than its name, such as Azure, a local server or AWS Bedrock, can't be asked again this way. Inspect AI: your log is read and never written; a copy of it is re-scored in memory with the same scorer and grader, with the grader's cache off, and when a grader is set, the model under test is Inspect's `mockllm/model` stand-in, so it can't be called; an answer whose new grading prompt is not the saved one is not counted, and when every prompt matched, a judge from another Inspect version counts as exactly your judge. MLflow: your judge is got back (a registered judge by name and version, a built-in judge, `Guidelines`, or `make_judge` with its saved instructions) and called directly on each answer's saved inputs and outputs, with the expectations saved on its trace, never `mlflow.genai.evaluate()`; your store is only read. An answer is counted only when every time asked came back with a clear verdict; the others are listed.

How close the judge you ask again is to yours, by tool:

| Your judge | Exactly your judge when | A close copy when | Can't be asked again when |
|---|---|---|---|
| promptfoo | The grader is named in your results and the same promptfoo version runs. For llm-rubric, each new grading prompt must match the saved one byte for byte | Your results record no promptfoo version, or the grader is promptfoo's default, which results never name | The grader was set with `--grader`, its settings hold a secret promptfoo hid, or the judge runs your own code (a `file://`, `exec:` or `python:` grader, rubric or transform). An answer whose saved prompt or input holds template text (`{{`, `{%`, `{#`) is left out on its own |
| DeepEval GEval | You confirm which fields the judge reads (or give `--fields`) and the DeepEval version, and DeepEval builds the model your results name | The fields or the DeepEval version were not confirmed | The saved steps can't be read back exactly, or the model needs more than its name |
| DeepEval built-in metrics | Never | Always: they keep settings the results do not save, and their prompts change between DeepEval versions | Hallucination, Bias or Toxicity scores saved by a DeepEval on the other side of 4.2.0 from yours |
| Other DeepEval metrics | | | DAG metrics, your own metric classes, conversational metrics, and results that do not say which model judged |
| Inspect AI | Its own `model_graded_qa` or `model_graded_fact`, with the Inspect version that made your log, or with every new grading prompt matching the saved one | Another Inspect version, and the prompts could not be compared | Your own `@scorer` (Inspect would import your task file), a template file that is not here, `include_history` given as a function. Rule scorers (`match`, `includes`, ...) are not judges |
| MLflow | A registered judge with its version saved, a built-in judge, or `Guidelines` with one guideline, and you confirm the MLflow version | A registered judge with no version saved (the latest is used), a `make_judge` that was not registered (MLflow 3.14 or later: its output type and temperature are not saved), or the MLflow version not confirmed | Your own `@scorer`, `make_judge` before MLflow 3.14, `Guidelines` with several guidelines, and Databricks judges |
| Your own command | Always your judge: `--judge-command` runs it with the `--exec` contract, and the plan says how many times | | |

After asking: steadiness (how often the judge changed its verdict on the same answer, weighted by the pool's groups, with Wilson intervals), agreement today (your labels against the first new verdicts, weighted by the saved groups, with intervals from a stratified bootstrap of 2,000 resamples and a fixed seed; when that gives a range of one point, such as 100% when every answer agrees, the Wilson range per group joined at the corners is used instead, so a range always keeps its width) next to your last result, and how often the first new verdict matched the saved one (below 90% it asks whether the judge's model or prompt changed). For a close copy, the reason is said once, first, and every number line ends "(close copy)". Your labels and your main result do not change.

**Trying your new judge.** You changed your judge's rule or model and ran your eval once. When the newest results hold a new version of your judge, the menu offers to try it on the answers you already marked (`--try-new-judge`). judgekeeper rebuilds the new judge from the newest results and has it grade your marked answers, once by default (`--times`), never your new outputs. The plan, the key-name check and the default-No question are the same as for asking again. By tool: promptfoo uses the model-graded assertion and grader of the newest results (matched to each answer by the test's vars when they differ by test; an answer with no matching test is left out and listed); DeepEval GEval uses the newest criteria, rubric, threshold and steps (the steps of the newest row with the same input, else the steps most rows share; a close copy when the steps differ by answer); Inspect AI uses the newest scorer and grader, exactly your judge only for its own scorers with the same Inspect version, since no saved prompt can be compared, else a close copy; MLflow uses the newest registered version, or the built-in judge with the newest model; for your own command, give the new one with `--judge-command`.

The result shows both judges against your same marks, side by side, weighted by the old judge's groups, with ranges. The old numbers are your last result, or your judge asked again, when you did that (it says so). It always adds that a judge changed after you saw its mistakes on these answers will look better on them, and offers "Mark 10 Correct and 10 Wrong new answers to confirm? [Y/n]": a quick check on answers from the newest results you never marked, half from the new judge's passes and half from its fails. Its result always shows the wide ranges. Your main result stays the old judge's until you run `judgekeeper start --new`, which makes the new judge the one being checked: everything, the old marks and the quick check included, moves to `previous-<date>/`, and nothing is deleted.

**When promptfoo's results are only in its database**, at a terminal `start` offers to run `promptfoo export eval latest` for you (no AI call; promptfoo's telemetry, update check and logs off). The file is checked against this project's promptfoo config (its description, else its prompts): a run from another project is deleted with a note on how to find yours; otherwise it is saved as `promptfoo-results.json` and `start` carries on.

**Without a terminal** (a script, CI, a coding agent) it never asks. It prints what it found and the flag that answers the question, and exits 2; `--yes` takes the defaults. Labeling needs a person: in CI, `start` can only find and report. Exit codes: 0 done (also when you stop early, and after No to a spending question), 1 a runtime failure (for asking again: the tool failed), 2 a usage error or a question that needs an answer, 130 asking again stopped with Ctrl-C.

**Installed in your project?** judgekeeper belongs in your project's own Python environment, like pytest. In a terminal, `judgekeeper --version` says judgekeeper is ready and what to run next; when Python is not running in a virtual environment, or judgekeeper was installed as a tool for the whole computer (in the folder where a tool installer keeps its tools, not in a project), it adds: "judgekeeper is installed outside a project. Install it inside your project's environment instead (see www.judgekeeper.com/start.html#install)." Piped or in a script it prints only `judgekeeper <version>`.

## init: a starter rule file

```
judgekeeper init [--out prompts/judge.md] [--pairwise] [--force]
```

Writes one rule file, the prompt your judge runs with, from a template that ships in the package (`src/judgekeeper/templates/single.md`, or `pairwise.md` with `--pairwise`). The file loads with the Anthropic and OpenAI runners as it is: frontmatter `rubric_version: my-metric-v1`, the placeholders `{{input}}` and `{{output}}` (pairwise: `{{output_a}}` and `{{output_b}}`) and the final `Verdict:` line. The parts you write are marked `[FILL IN: ...]`: the one thing being checked, what counts as pass, what counts as fail, two or three examples of each, and edge cases (pairwise: what makes one output better, and the tie rule). Parent folders are created; an existing file is not overwritten without `--force` (usage error, exit 2). It prints the next commands: label, `judge --prompt`, `validate`. No model is called and nothing else is written.

`judge --prompt` refuses a file that still contains a `[FILL IN` marker, naming the first marker and its line number (usage error, exit 2). Change `rubric_version` whenever you change the rule: a changed rule is a changed judge, and `gate` reports `JUDGE_CHANGED`. How to write the rule, with two worked examples: [`own-metric.md`](own-metric.md).

## Anchor sets, judging and the report

```
pip install "judgekeeper[anthropic]"      # for --runner openai: pip install "judgekeeper[openai]"
judgekeeper init                          # writes prompts/judge.md; fill in its [FILL IN: ...] parts
judgekeeper freeze anchors.jsonl          # writes anchors.manifest.json (counts + sha256)
judgekeeper judge anchors.jsonl --runner anthropic --model claude-haiku-4-5-20251001 \
  --prompt prompts/judge.md --runs 3 --out runs/my-judge/
judgekeeper validate anchors.jsonl runs/my-judge/ --out reports/my-judge/
```

`--runner anthropic` and `--runner openai` call the model for you and need the provider's client library, which the first line installs in your project's environment (switch it on first); plain `pip install judgekeeper` does not include it. `--callable`, `--exec`, `check` and `import` do not need it. `prompts/judge.md` in the examples on this page is the rule file `judgekeeper init` writes (`judgekeeper init --pairwise` for an anchor set that compares two outputs).

An anchor set is JSONL with `id`, `input` and `human_label` on every line. Pairwise items add `output_a` and `output_b` with labels `A`/`B`; single-output items add `output` with labels `pass`/`fail`. `slice` and `notes` are optional. After `freeze`, every command checks the anchor set against its manifest and exits with code 3 if it changed.

`judge` writes one `run-NN.jsonl` per run. Line 1 is a header with the judge fingerprint and a `source` object (`{kind: judgekeeper | table | callable | exec | promptfoo | deepeval | inspect | records | mlflow | langfuse, file, metric}`, plus `version`, `notes` and `warnings` for imports; imported and custom judges also record the `--pass-if` rule and label map used). Every judgment line carries the judge fingerprint (provider, model, served snapshot, endpoint, prompt hash, rubric version, temperature, timestamp). Pairwise items are judged in both AB and BA order.

`validate` writes `report.json` and a self-contained `report.html`. The headline is TPR, TNR (each with a 95% Wilson interval) and Cohen's kappa, mean over runs. Kappa is chance-corrected agreement with the human labels; TPR and TNR are the numbers to act on. The interval's n is the number of human-positive (or negative) items, not items × runs, because runs re-judge the same items. The report also has: the fingerprint and source, per-run numbers, a confusion matrix on majority verdicts, the noise floor across runs (per-item flip rate, run-vs-run kappa, majority verdict; with one run it reads "unknown: one run supplied", never zero), AB/BA position bias, a per-slice table, and every disagreement with the judge's rationale.

The verdict:

| condition | says |
|---|---|
| TPR or TNR below 0.80, or kappa below 0.6 | "not trustworthy as a gate" |
| otherwise, TPR or TNR below 0.90 | "usable with care" |
| otherwise | "usable as a gate" |

The lower of the two rates decides: TPR 0.95 with TNR 0.85 is "usable with care". A rate that could not be measured (no human labels of that class) also gives "not trustworthy as a gate".

Flags: position bias above 0.10, more than 10% of items flipping between runs ("noisy, use majority of runs"), one run only (noise floor unknown), judge errors above 2% of judgments, an incomplete judge fingerprint ("judge identity incomplete: <fields>"), fewer than 60 labeled items ("error bars are wide; aim for about 100") and a class split more lopsided than 80/20. `report.json` keys read by `gate` are stable; later versions added `source`, `normaliser`, `errors`, `label_quality`, `notes`, `fingerprint_unknown`, `verdict.level`, `headline.tpr_ci`/`tnr_ci` and `noise_floor.status`.

## check: a table in, a report out

```
judgekeeper check results.csv --judge verdict --human label [--id id] [--run run] \
  [--input input --output output --reason reason] [--pass-if RULE] [--label-map MAP] --out reports/x/
```

- CSV, TSV or JSONL, one row per judgment. Column flags default to columns of those names when present (`--judge verdict`, `--human label`, `--id id`, `--run run`, `--input input`, `--output output`, `--reason reason`). Columns `output_a` and `output_b` make the items pairwise (verdicts `A`/`B`).
- Several rows for one id with different `--run` values are repeat runs. With no run column, or one run, the noise floor is "unknown: one run supplied" and `gate` on the report returns `FLAKY` for that reason. An item missing from a run is a judge error in that run.
- Without an id column, an item's id is the sha256 of its canonical input and output (both outputs for pairwise items), first 16 hex characters, and the report says the ids were derived. Duplicate ids within a run are a usage error that lists them.
- A row with an empty human label is skipped and counted (`source.n_unlabeled`). Different human labels for one id are a usage error.
- `--out` (default `judgekeeper-report`) gets `anchors.jsonl` with its manifest, `runs/run-NN.jsonl` and `report.json` / `report.html`, built by the same pipeline as `validate`. Imported data rarely says which model judged: the fingerprint is recorded with unknown fields (see [Unknown judge fields](#unknown-judge-fields)).

In Python (pandas is optional; anything with `to_dict(orient="records")` works):

```python
import judgekeeper
report = judgekeeper.check_table(df_or_rows_or_path, judge="verdict", human="label",
                                 pass_if=None, label_map=None, fingerprint={"model": "my-judge"},
                                 out="reports/x")   # out=None writes to a temporary directory
```

## How verdicts are read

One normaliser serves `check`, `check_judge`, `--callable`, `--exec` and `import-labels`. It turns a raw judge output into `pass`/`fail` (or `A`/`B`) or `error`, plus a rationale:

- a bool: `True` is pass;
- a string, case-insensitively, through the label map. Defaults: `pass`/`fail`, `true`/`false`, `yes`/`no`, `correct`/`incorrect`, `1`/`0`, and a leading `PASS` or `FAIL` token (`PASS: looks right`). Pairwise: `A`/`B`. `--label-map "good=pass,bad=fail"` adds entries;
- a number, through a required `--pass-if` rule: `score>=0.5`, `>`, `<=`, `<`, `==`. The name is free text, except that for a dict it names the key to read (`relevance>=3`). Integers `1`/`0` follow the label map when no rule is given;
- a `(verdict, reason)` tuple or two-element list;
- a dict with the verdict under `verdict`, `pass`, `passed`, `label` or `score` (first found) and the reason under `reason`, `rationale`, `explanation` or `comment`.

A value that looks like a verdict but is not in the map (`good`), or a number with no rule, is a usage error that lists every such value seen. judgekeeper never guesses. A judge that raised, returned nothing (None, an empty string, NaN) or returned something unreadable (a dict with no verdict key, a list of three) is recorded as `error`, never as fail: errors are excluded from every agreement metric, counted in the report (`errors`) and flagged above 2% of judgments. Human labels use the same label map but never `--pass-if`.

## Bring your own judge

Python:

```python
judgekeeper.check_judge(judge, anchors, runs=3, pass_if=None, label_map=None, fingerprint=None,
                        out=None, yes=False)   # returns the report dict
```

`judge(item: dict)` returns a bool, str, float, tuple or dict; it may be `async def` (this also works inside a running event loop, as in a notebook). `item` is the anchor item without `human_label` and `notes`. Pairwise items are judged twice, with `output_a` and `output_b` swapped the second time; the second verdict is mapped back to the original labels. `anchors` is a frozen anchor JSONL path, or a list of items (written under `out` and frozen). `fingerprint` takes what you know: `provider`, `model`, `snapshot`, `endpoint`, `prompt` (text, hashed) or `prompt_hash`, `rubric_version`, `temperature`; everything else is recorded as unknown. Above 1,000 judge calls it needs `yes=True`.

Command line:

```
judgekeeper judge anchors.jsonl --callable mypkg.judges:my_judge --runs 3 --out runs/x/
judgekeeper judge anchors.jsonl --exec "node judge.js" --runs 3 --out runs/x/
```

Both print the number of judge calls (items × runs, × 2 for pairwise) before starting and need `--yes` above 1,000. `--pass-if` and `--label-map` work as above; `--model`, `--temperature` and `--prompt` (any file; hashed, with `rubric_version` taken from its frontmatter if it has one) fill in the fingerprint. `--callable` imports from the working directory and calls the function one item at a time. `--exec` runs the command once per item, `--workers` at a time (default 4), with `--timeout` seconds each (default 300).

The `--exec` contract: one item as JSON on stdin per invocation. Stdout is either a bare verdict (`pass`, `FAIL: wrong total`, `0.83`) or a JSON object the normaliser reads (`{"verdict": "pass", "reason": "..."}`). A non-zero exit, a timeout or empty stdout is an `error` judgment; the last lines of stderr go into its error text (scrubbed of keys).

Node (`judge.js`):

```js
// judge.js: run with --exec "node judge.js"
let data = "";
process.stdin.on("data", (chunk) => (data += chunk));
process.stdin.on("end", async () => {
  const item = JSON.parse(data); // { id, input, output } or { id, input, output_a, output_b }
  // Call your model here. This placeholder passes any non-empty output.
  const pass = item.output.trim().length > 0;
  const reason = pass ? "output is not empty" : "empty output";
  console.log(JSON.stringify({ verdict: pass ? "pass" : "fail", reason }));
});
```

Python (`judge.py`):

```python
# judge.py: run with --exec "python judge.py"
import json
import sys

item = json.load(sys.stdin)  # {"id", "input", "output"} or {"id", "input", "output_a", "output_b"}
# Call your model here. This placeholder passes any non-empty output.
ok = bool(item["output"].strip())
reason = "output is not empty" if ok else "empty output"
print(json.dumps({"verdict": "pass" if ok else "fail", "reason": reason}))
sys.exit(0)  # a non-zero exit is recorded as an error, not a fail
```

## Labels from a spreadsheet

```
judgekeeper template items.jsonl -o labels.csv      # or items.csv
judgekeeper import-labels labels.csv -o anchors.jsonl [--label-map "good=pass,bad=fail"]
```

`template` writes `id,input,output,human_label,notes` (pairwise: `output_a,output_b`) with `human_label` and `notes` empty, ready for Excel or Google Sheets. Ids come from an `id` column or are derived as in `check`. `import-labels` reads the sheet back, checks every label through the normaliser (an unmapped label is a usage error listing them), skips and lists unlabeled rows, keeps non-empty `notes` and `slice`, writes the anchor file and freezes it. It prints the label-quality warnings that also appear in every report.

## label: a local labeling page

```
judgekeeper label items.jsonl [--out labels.csv] [--port 8765] [--no-browser]   # or items.csv
```

Opens a page in your browser that shows one item at a time: the input and the output (pairwise: A and B side by side). Keys: `1` pass (pairwise: A, also `a`), `2` fail (pairwise: B, also `b`), `d` defer, `u` undo, `n` note, arrow keys to move; a button mirrors every key. A judge verdict in the items (a `judge_verdict`, `verdict` or `judge` column, with `judge_reason`, `reason` or `rationale`) sits behind a "Show judge" button, hidden by default so it does not anchor the labeler.

Every change is written to `--out` at once (to a temporary file, then renamed over it) as `id,input,output,human_label,notes` (pairwise `output_a,output_b`), the shape `template` writes, so `import-labels` and `import --labels` read it unchanged. Single items get `pass`/`fail`, pairwise items `A`/`B`; deferred items stay unlabeled (deferral is not saved to the file). Reopening with the same `--out` resumes where it left off; an `--out` with ids that are not in the items is refused. `items` may itself be a sheet from `template`, partly filled in. When every item is labeled or deferred, the page shows the counts, the split, the label-quality warnings (fewer than 60 labels, worse than 80/20) and the `import-labels` command to run next.

The server uses only the standard library and binds `127.0.0.1`, never `0.0.0.0`. The URL carries a random token that the page and every request must present; a request whose `Host` header is not `127.0.0.1:<port>` is refused (DNS rebinding); the page loads nothing from the network (a Content-Security-Policy enforces it) and shows every string as text. Ctrl-C stops it, and it stops by itself after 2 hours without a request. It keeps serving until then.

## import: promptfoo, DeepEval and Inspect AI results

```
judgekeeper import <tool> <path>... [--metric NAME] [--labels labels.csv] [--pass-if RULE] \
  [--label-map MAP] [--runs-by-order] [--id-var NAME] [--map MAP] --out reports/x/
```

`<tool>` is `promptfoo`, `deepeval`, `inspect` or `records`. A path is a file, a directory or a quoted glob; files are read in the order given (a directory or glob in name order). The output is what `check` writes: `anchors.jsonl` with its manifest, `runs/run-NN.jsonl` and `report.json` / `report.html`, with `source.kind` set to the tool and `source.version` to the tool's own format version when the file states one (promptfoo `results.version`, Inspect `version`). Exit 0 on success, 2 on a usage error. Per-tool pages: [promptfoo](integrations/promptfoo.md), [DeepEval](integrations/deepeval.md), [Inspect AI](integrations/inspect.md).

- `--metric NAME`: the judge to validate (promptfoo assertion `metric` or type, DeepEval metric `name`, Inspect scorer name). Optional when the files hold one; with several, leaving it out is a usage error that lists the names.
- `--labels TABLE`: human labels, CSV, TSV or JSONL with an `id` column and a `human_label` (or `label`) column, read through the same normaliser as `check`. It wins over human labels in the files (promptfoo web-UI ratings, Inspect score edits) and the report notes how many it replaced and how many differed. Rows with an empty label are skipped. A `slice` column is kept, as `import-labels` keeps it, so the report has per-slice numbers.
- `--pass-if`, `--label-map`: as in `check`. `--pass-if` is applied to the record's `score` (DeepEval `score`, promptfoo component `score`, numeric Inspect values); without it the verdict is the tool's own pass flag or label. Human labels never use `--pass-if`.
- `--runs-by-order`: number each item's verdicts in a file 1, 2, 3 in order of appearance, in place of any run index the file carries, instead of stopping when one run holds several verdicts for one item. Works with every tool. The promptfoo reader always numbers repeats this way, because promptfoo strips the repeat index.
- `--id-var NAME` (promptfoo only): the test var holding the item id.
- `--map MAP` (records only): see below.

How records become a report: human records become anchor labels, judge records become judgments and code records (promptfoo's `contains`, `javascript`, ...) are ignored with a note. Several files, or several run indices in one file (Inspect epochs, promptfoo repeats), become separate runs; an item a run does not judge is an error judgment in that run. With one run the noise floor is "unknown: one run supplied". An item with a verdict and no human label, or a label and no verdict, is dropped, counted in `source.n_judged_unlabeled` / `source.n_labeled_unjudged` and noted in the report. Ids that had to be derived (a hash of input and output, as in `check`) are noted too.

Fingerprint: each judgment keeps the judge identity its record carries (model, prompt hash, temperature, timestamp). The run header records the fields every judgment agrees on; a field they disagree on is unknown in the header, with a note. A raw prompt is hashed into `prompt_hash` and never written. Tool warnings (promptfoo's unrecorded default grader, DeepEval's positional names) are report flags.

In Python:

```python
import judgekeeper
report = judgekeeper.import_results("deepeval", ["deepeval-results/"], metric="Correctness [GEval]",
                                    labels="labels.csv", pass_if=None, label_map=None,
                                    runs_by_order=False, out="reports/x")
# also id_var="qid" (promptfoo) and column_map="target_id=trace_id,..." (records)
```

## import mlflow and import langfuse

```
judgekeeper import mlflow --experiment NAME_OR_ID [--run-id ID]... [--metric NAME] \
  [--tracking-uri URI] [--id-from KEY] [--temperature T] [--labels labels.csv] \
  [--pass-if RULE] [--label-map MAP] [--anchors-out anchors.jsonl] --out reports/x/

judgekeeper import langfuse --judge-score NAME --human-score NAME \
  (--from DATE [--to DATE] | --to DATE | --max-items N) [--rate PER_MINUTE] \
  [--labels labels.csv] [--pass-if RULE] [--label-map MAP] [--anchors-out anchors.jsonl] --out reports/x/
```

These read a platform instead of files: they take no paths, and their flags are usage errors with any other tool. The output, `--labels`, `--pass-if`, `--label-map` and `--runs-by-order` are as for the file readers above. Per-platform pages: [MLflow](integrations/mlflow.md), [Langfuse](integrations/langfuse.md).

MLflow (needs `pip install "judgekeeper[mlflow]"`; without it, a usage error saying so):

- `--experiment NAME_OR_ID`: required.
- `--metric NAME`: the assessment name. Optional with one judge assessment name; with several, leaving it out is a usage error that lists them.
- `--run-id ID` (repeatable): only those runs' judge assessments; an id not in the experiment is a usage error. Default: every run, one judgekeeper run each, in start order (`source.file` is the MLflow run id).
- `--tracking-uri URI`: default `MLFLOW_TRACKING_URI`, then MLflow's own default. Databricks reads `DATABRICKS_HOST` and `DATABRICKS_TOKEN` through MLflow.
- `--id-from KEY`: item ids from this trace tag or request input key; a trace without it is a usage error. Default: a hash of the trace's request input, noted in the report.
- `--temperature T`: recorded in the fingerprint; MLflow does not store it.
- `LLM_JUDGE` assessments are judgments, `HUMAN` assessments labels, `CODE` ignored. A human assessment that overrides a judge assessment is the label; the overridden value stays the judge's verdict. `feedback.error` is an `error` verdict. Fingerprint: `source.source_id` as model (provider before `:/`), `scorerName@scorerVersion` metadata as rubric version, prompt unknown.

Langfuse (standard library only):

- `--judge-score NAME`, `--human-score NAME`: required; the same name splits by source (`ANNOTATION` is human).
- `--from DATE`, `--to DATE`: a date (`2026-09-01`) or ISO time, UTC when no offset is given; `--from` inclusive, `--to` exclusive. `--max-items N`: stop after N scores. One of the three is required.
- `--rate PER_MINUTE`: request cap, default 30. HTTP 429 waits for `Retry-After` and retries up to 5 times, then exits 1.
- `--metric` defaults to `--judge-score`. Verdicts by `dataType`: `BOOLEAN`, `NUMERIC` (with `--pass-if`), `CATEGORICAL`; `TEXT` and `CORRECTION` are skipped with a note. Item id is `subject.id`; rationale is `comment`. One run.
- Fingerprint: one `GET /api/public/v2/evaluators` call, matched by score name, for `modelConfig.provider`, `modelConfig.model`, `version` and a hash of `prompt`; unknown with a note when no evaluator matches or `modelConfig` is null. Temperature is always unknown.
- A failed request (HTTP error, unreachable host, refused cross-host redirect) exits 1 with the status and path only.

`--anchors-out PATH` (both): also write every item with a human label as an anchor set (`id`, `input`, `output`, `human_label`; input and output only when the platform returned them, else `""`; no rationales, no annotator ids) and freeze it, ready for `judgekeeper judge`. Usage error with the file readers.

In Python:

```python
report = judgekeeper.import_results("mlflow", metric="correctness", out="reports/x",
                                    source={"experiment": "my-app-eval", "run_ids": None,
                                            "tracking_uri": None, "id_from": None,
                                            "temperature": None},
                                    anchors_out="anchors.jsonl")
report = judgekeeper.import_results("langfuse", pass_if="score>=0.5", out="reports/y",
                                    source={"judge_score": "helpfulness",
                                            "human_score": "helpfulness_human",
                                            "from_": "2026-09-01", "to": None,
                                            "max_items": None, "rate": 30})
```

## ScoreRecords: import records and export records

A ScoreRecord is one verdict. Field names follow OpenInference annotations, so other tools' exports map onto it by renaming:

| field | meaning |
|---|---|
| `target_id` | the item. Missing: derived from `input` and `output` as in `check`, and the report says so |
| `name` | the metric or scorer (default `judge`); choose one with `--metric` |
| `annotator_kind` | `LLM` (a judge verdict), `HUMAN` (a label) or `CODE` (ignored). Case-insensitive; `LLM_JUDGE` reads as `LLM`. Default `LLM` |
| `label` | the verdict or label: `pass`/`fail`, `true`/`false`, a bool, or anything `--label-map` maps |
| `score` | a number; read as the verdict with `--pass-if`, or when `label` is empty |
| `explanation` | the judge's rationale |
| `run` | repeat index, or empty. Without one, each file is one run (see `--runs-by-order`) |
| `input`, `output` | the item's text (or any JSON) |
| `evaluator` | `{provider, model, prompt, temperature, version}`; `version` is the rubric version, `prompt` is hashed. Also `prompt_hash`, `snapshot` and `endpoint`, which `export records` writes |
| `created_at` | when the verdict was made |

HUMAN records label the metric they are named after, or any metric when their name is not a judge metric in the file (promptfoo's ratings are named `human`).

```
judgekeeper import records records.jsonl --out reports/x/
judgekeeper import records export.csv --map "target_id=trace_id,name=metric,label=value,explanation=comment,annotator_kind=source" --out reports/x/
judgekeeper export records reports/x/ -o records.jsonl
```

`import records` reads JSONL, CSV or TSV. `--map` takes `field=column` pairs; evaluator fields are `evaluator.model=judge_model` and so on (a CSV can also have `evaluator.model` columns, or an `evaluator` column holding JSON). A mapped column that does not exist is a usage error listing the columns.

`export records <dir> -o records.jsonl [--anchors anchors.jsonl]` writes judgekeeper's runs and anchors as ScoreRecords: one HUMAN record per anchor item and one LLM record per judgment, with the judgment's fingerprint as `evaluator` (the prompt as `prompt_hash`) and error judgments as an empty `label`. `<dir>` is a directory `check` or `import` wrote (or its `report.json`), or a runs directory with `--anchors`. `import records` on the result gives the same report. Single-output anchor sets only; `slice` and `notes` are not carried.

## Unknown judge fields

Every fingerprint field except `created_at` may be unknown: provider, model, snapshot, prompt hash, rubric version and temperature are `null`, and an unknown endpoint is the string `"unknown"` (because `endpoint: null` already means the provider's default endpoint). Reports show such fields as "unknown" and flag "judge identity incomplete: <fields>". Files from earlier versions still load: a missing field reads as unknown, except a missing `endpoint`, which reads as the provider default.

`gate` compares the baseline and the report field by field. A field known on both sides that differs is `JUDGE_CHANGED`, as always. A field unknown on either side adds a warning and does not block, unless `--require-fingerprint` is passed, in which case the status is `JUDGE_CHANGED` with the reason "cannot prove same judge". The default is to warn because imported data rarely carries temperature or snapshot, and blocking on that would make the gate unusable for it; pass `--require-fingerprint` once your judge records its full identity.

## Your API keys

- judgekeeper has no server. Your key stays in your environment, and requests go from your machine (or your CI runner) straight to the provider or the endpoint you name.
- Nothing judgekeeper writes contains a key: judgment files, reports, gate, migration and attribution files are all scrubbed. Before any text reaches disk or your terminal, the value of `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `MLFLOW_TRACKING_PASSWORD`, the variable named with `--api-key-env` and any variable ending in `_API_KEY`, `_TOKEN` or `_SECRET` (`DATABRICKS_TOKEN`, `MLFLOW_TRACKING_TOKEN`) is replaced with `[REDACTED]`, as is anything shaped like a provider key (`sk-ant-…`, `sk-…`, `Bearer …`, `Basic …`) and the `user:password@` part of a URL.
- Platform readers take credentials from the environment only: `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` (host from `LANGFUSE_BASE_URL` or `LANGFUSE_HOST`, default `https://cloud.langfuse.com`) for Langfuse; whatever MLflow reads (`MLFLOW_TRACKING_URI`, `MLFLOW_TRACKING_TOKEN`, `DATABRICKS_HOST`, `DATABRICKS_TOKEN`, ...) for MLflow. The Langfuse reader only issues GET requests, sends the keys only to the configured host, refuses redirects to another host and never prints the Authorization header, a response body or the keys.
- Error text is scrubbed too. A failed provider call prints one line and exits 1; `--debug` adds the traceback, still scrubbed. A failed call is never scored.
- There is no flag that takes a key, and there never will be. `--api-key-env` takes the *name* of a variable.
- In CI, keep keys in repository secrets and pass them to the step as `env`, never as inputs.

A custom endpoint: any OpenAI-compatible server (Azure OpenAI's v1 endpoint, OpenRouter, Together, a LiteLLM proxy, Ollama, vLLM) with `--runner openai`, or a gateway in front of Anthropic with `--runner anthropic`. `OPENAI_BASE_URL` and `ANTHROPIC_BASE_URL` also work; the flag wins when both are set. With `--base-url` and no key set, judgekeeper sends a placeholder key, since local servers need none. A URL with `user:password@` in it is rejected.

```
judgekeeper judge anchors.jsonl --runner openai --model "$JUDGE_MODEL" \
  --base-url http://localhost:11434/v1 --prompt prompts/judge.md --runs 3 --out runs/local/
```

A custom key variable:

```
export OPENROUTER_API_KEY=...            # in your shell or CI secrets, never in a file
judgekeeper judge anchors.jsonl --runner openai --model "$JUDGE_MODEL" \
  --base-url https://openrouter.ai/api/v1 --api-key-env OPENROUTER_API_KEY \
  --prompt prompts/judge.md --runs 3 --out runs/openrouter/
```

The endpoint's host goes into the fingerprint as `endpoint` (`null` for the provider default): the same model name behind a different endpoint is a different judge, and `gate` treats a changed endpoint as `JUDGE_CHANGED`. AWS Bedrock and Google Vertex have no native client; put a gateway such as LiteLLM in front of them and use `--base-url`.

## Gate CI on the judge

```
judgekeeper baseline set reports/my-judge/report.json   # copies to .judgekeeper/baseline.json; commit it
judgekeeper baseline show                               # fingerprint, anchors hash, kappa / TPR / TNR
judgekeeper gate reports/my-judge/report.json           # writes gate.json and gate.md next to the report
```

`gate` compares a report with fixed thresholds and, if there is one, the baseline (`--baseline`, default `.judgekeeper/baseline.json` when it exists). It decides one status, checking in this order:

1. `ANCHORS_CHANGED`: the anchor set hash differs from the baseline's.
2. `JUDGE_CHANGED`: provider, model, snapshot, endpoint, prompt hash, rubric version or temperature differ from the baseline. Scores are not compared across judges. `--allow-judge-change` turns this into a warning and gates on absolute thresholds only. A field unknown on either side is a warning, or `JUDGE_CHANGED` ("cannot prove same judge") with `--require-fingerprint`; see [Unknown judge fields](#unknown-judge-fields).
3. `FLAKY`: fewer than 3 runs, so the noise floor is unknown (with one run: "noise floor unknown: one run supplied").
4. Absolute thresholds: kappa mean >= 0.6, TPR mean >= 0.8, TNR mean >= 0.8, AB/BA disagreement <= 0.10.
5. Against the baseline: kappa, TPR and TNR may not drop by more than the noise band, which is the larger of the baseline's and this report's run-to-run spread, and at least 0.02.
6. A check that fails on the mean but passes on the best run, or more than 10% of items flipping between runs, is `FLAKY` ("use the majority of more runs") instead of `FAIL`.
7. Otherwise `PASS`.

`JUDGE_CHANGED` points at `migrate`, below: compare the old and new judge, then `--rebase` to make the new one the baseline.

`--flaky-as pass` or `--flaky-as fail` maps `FLAKY` to exit 0 or 1; the status in `gate.json` and `gate.md` stays `FLAKY`. Without the flag `FLAKY` exits 4. `gate.md` is a short summary for a PR comment or `$GITHUB_STEP_SUMMARY`: the status, why, a metric / baseline / now / delta / noise band table and the judge fingerprint.

Thresholds live in an optional `judgekeeper.toml` (`--config`, default `./judgekeeper.toml` when it exists), one table per command: `[gate]` here, `[migrate]` and `[attribute]` below. Unknown tables and keys are a usage error.

```toml
[gate]
kappa_min = 0.6
tpr_min = 0.8
tnr_min = 0.8
ab_ba_disagreement_max = 0.10
min_band = 0.02        # smallest noise band, for judges that never vary between runs
flip_rate_max = 0.10   # share of items that may flip between runs before a failure is FLAKY
```

## pytest plugin

Installed with judgekeeper (`pytest11` entry point `judgekeeper.pytest_plugin`); `pip install pytest-judgekeeper` installs the same thing under the name the pytest plugin list uses. It runs the `gate` logic on a `report.json` your pipeline already wrote. It never calls a judge or an API and writes nothing.

```python
def test_judge_still_agrees_with_humans(judgekeeper_gate):
    judgekeeper_gate("reports/my-judge/report.json")   # baseline=None, config=None, allow=("PASS",), flaky_as=None

@pytest.mark.judgekeeper(report="reports/my-judge/report.json", flaky_as="pass")
def test_with_the_marker():
    ...   # runs only if the gate allows the report
```

```
pytest --judgekeeper-report reports/my-judge/report.json [--judgekeeper-baseline B] \
  [--judgekeeper-config judgekeeper.toml] [--judgekeeper-flaky-as pass|fail]
```

- A status not in `allow` fails the test with the `gate.md` summary as the message. `flaky_as="pass"` adds `FLAKY` to `allow`; `"fail"` removes it. A missing or unreadable report fails the test with the reason.
- The marker checks the report before the test body runs; a marked test whose gate fails never runs its body.
- `--judgekeeper-report` adds one test, `judgekeeper-gate`, so a CI job can gate without writing a test.
- Fixture and marker paths are relative to the pytest rootdir; command-line paths to the directory pytest was started in. With no baseline or config, `.judgekeeper/baseline.json` and `judgekeeper.toml` under the rootdir are used when they exist, as `judgekeeper gate` does.

## Migrate to a new judge

When a judge model is deprecated, or you want a cheaper or better one, judge the same frozen anchor set with both and compare:

```
judgekeeper judge anchors.jsonl --runner anthropic --model "$OLD_MODEL" --prompt prompts/judge.md --runs 3 --out runs/old/
judgekeeper judge anchors.jsonl --runner anthropic --model "$NEW_MODEL" --prompt prompts/judge.md --runs 3 --out runs/new/
judgekeeper migrate anchors.jsonl runs/old/ runs/new/ --out reports/migration/ [--rebase] [--fail-on worse|different]
```

Both run directories must have been judged against the same frozen anchor set (exit 3 otherwise). `migrate` writes `migration.json` and a self-contained `migration.html` with:

1. **Who changed**: both fingerprints side by side, changed fields highlighted, served snapshots.
2. **Each judge against humans**: kappa, TPR and TNR, mean and range over runs.
3. **Old judge against new judge**: kappa between the two judges' majority verdicts, the share of items whose verdict changed, and for each change whether both judges were stable on it (unanimous across their own runs) or either was flipping anyway ("within noise"). Changed-and-stable items are *fixed* (the new judge now agrees with the human label) or *broken*, with the net.
4. **Per slice**: old kappa, new kappa, delta, changed-and-stable count.
5. **Changed items**: id, slice, human label, old and new verdict, fixed or broken, both rationales.
6. **Pass-rate bridge**: a = P(new says pass | old said pass) and b = P(new says pass | old said fail) on the anchor set, with Wilson 95% intervals, overall and per slice, so that `new_rate ≈ old_rate × a + (1 − old_rate) × b`. It assumes your production traffic resembles the anchor set. Pairwise sets use "prefers A" for "pass".
7. **Status**, with a sentence on what to do. The noise band is the larger of each judge's run-to-run kappa spread and `min_band`.

| status | meaning | what to do |
|---|---|---|
| `EQUIVALENT` | kappa vs humans moved within the noise band, and at most 2% of items changed while both judges were stable | keep comparing scores across the switch; rebase |
| `BETTER` | kappa vs humans rose by more than the noise band | switch and rebase; scores move because the judge improved |
| `WORSE` | kappa vs humans fell by more than the noise band | do not migrate yet |
| `DIFFERENT` | kappa within the band, but more than 2% of items changed while both judges were stable | as good, on different items: old and new scores are not comparable item by item; rebase if you switch |

`migrate` exits 0 when the analysis completes, whatever the status. `--fail-on worse` exits 1 on `WORSE`; `--fail-on different` exits 1 on `WORSE` or `DIFFERENT`. `--rebase` copies the new judge's report to the baseline (`--baseline`, default `.judgekeeper/baseline.json`) and keeps `migration.json` as `.judgekeeper/migrations/<UTC date>-<old model>-to-<new model>.json`, the audit trail. Commit both; after a rebase `gate` no longer reports `JUDGE_CHANGED`.

```toml
[migrate]
min_band = 0.02            # smallest kappa noise band
max_changed_share = 0.02   # changed-and-stable share above which equal kappa is DIFFERENT
```

`scripts/migration_demo.sh` runs this on LLMBar: `RUNNER`, `OLD_MODEL` and `NEW_MODEL` come from the environment, and it has no default model ids. Take them from the provider's current models and deprecations pages.

No example migration report is published yet, so this page quotes no migration numbers.

## Attribute a score change

Your app's eval score moved. Did your system change, or did the judge? The anchor set is frozen, so the outputs being judged are identical every time: any movement in verdicts on it comes from the judge. Re-judge the anchor set, validate, and compare with the baseline:

```
judgekeeper attribute reports/now/report.json [--baseline .judgekeeper/baseline.json] \
  [--app-score-before X --app-score-after Y]
```

It compares per-item majority verdicts between the baseline and the current report. An item counts as moved only if it was stable (unanimous across runs) in both. Judge drift is declared when more than 2% of items moved, or kappa vs humans moved outside the noise band. This works when the declared fingerprint is identical, which is what a silent provider-side update looks like, and it reports whether the served snapshot changed.

- `STABLE`: the judge did not move on the anchor set.
- `JUDGE_DRIFT`: it did. Re-validate the judge; to keep the new behaviour, `migrate` and rebase.
- `SYSTEM_CHANGE`: the judge is stable on the anchor set and the app scores you supplied (pass rates between 0 and 1) differ by more than the judge's own run-to-run pass-rate spread on the anchor set (at least `min_band`). The score change comes from your system.

Both reports need per-item verdicts (`items`, written by `validate` from this version on); an older baseline is a usage error that tells you to regenerate it. `attribute` writes `attribution.json` and `attribution.md` (for `$GITHUB_STEP_SUMMARY`) next to the report, or under `--out`. The example workflow in `docs/examples/workflows/judge-gate.yml` runs it weekly after the gate job re-judges the anchor set.

```toml
[attribute]
min_band = 0.02          # smallest noise band, for kappa and for app scores
max_moved_share = 0.02   # share of stable items that may move before it is JUDGE_DRIFT
```

## Exit codes

| exit code | meaning | commands |
|---|---|---|
| 0 | success; `PASS`; `STABLE`; `migrate` finished | all |
| 1 | `FAIL`; a judge call failed, or the judge failed on every item; `migrate --fail-on` matched; a Langfuse request failed | `gate`, `judge`, `migrate`, `import langfuse` |
| 2 | usage error (bad arguments, report, baseline or config; unmapped verdicts or labels; duplicate ids; several metrics without `--metric`; more than 1,000 judge calls without `--yes`; a missing extra or platform key; a Langfuse import with no time window or `--max-items`; an input file that is not UTF-8 text; an output location that cannot be written) | all |
| 3 | anchor set changed: hash mismatch, `ANCHORS_CHANGED`, runs or reports from a different anchor set | all that read anchors or reports |
| 4 | `FLAKY` (`--flaky-as` maps it to 0 or 1) | `gate` |
| 5 | `JUDGE_CHANGED` | `gate` |
| 6 | `JUDGE_DRIFT` | `attribute` |
| 7 | `SYSTEM_CHANGE` | `attribute` |

## GitHub Action

`action.yml` at the repo root runs `judge`, `validate` and `gate`, appends `gate.md` to the job summary, uploads `report.html`, `report.json` and `gate.json` as an artifact, and exits with the gate's exit code. API keys come from the caller's `env`, never from inputs; `api-key-env` names the variable when it is not the provider's standard one. A copy-paste workflow that runs weekly and on PRs touching the judge prompt is in `docs/examples/workflows/judge-gate.yml`:

```yaml
name: judge gate
on:
  schedule:
    - cron: "17 6 * * 1"   # weekly: catches provider-side judge drift between PRs
  pull_request:
    paths: ["prompts/judge.md", "evals/anchors.jsonl", ".judgekeeper/baseline.json", "judgekeeper.toml"]
jobs:
  gate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: judgekeeper/judgekeeper@v0.2.0   # a release tag; a commit sha is stricter
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
        with:
          anchors: evals/anchors.jsonl
          runner: anthropic
          model: claude-haiku-4-5-20251001
          prompt: prompts/judge.md
          runs: 3
          flaky-as: pass
```

| input | default | |
|---|---|---|
| `anchors` | required | frozen anchor set JSONL, manifest next to it |
| `runner` | required | `anthropic`, `openai` or `replay` |
| `model`, `prompt` | | judge model id and prompt (anthropic, openai) |
| `fixture` | | recorded judgments JSONL for `replay` (no API key) |
| `base-url` | | endpoint instead of the provider default (anthropic, openai) |
| `api-key-env` | | name of the variable holding the key, never the key itself |
| `runs` | `3` | judge runs; the gate needs at least 3 |
| `baseline` | `.judgekeeper/baseline.json` if present | baseline report |
| `config` | `judgekeeper.toml` if present | gate thresholds |
| `flaky-as` | `pass` | `pass`, `fail`, or empty to keep exit code 4 |
| `out-dir` | `judgekeeper-out` | where runs, report and gate files go |
| `artifact-name` | `judgekeeper-gate` | uploaded artifact name |
| `python-version` | `3.12` | Python used to run judgekeeper |

Outputs: `status` and `exit-code`. This repo's own CI runs the action on replay fixtures on every push.
