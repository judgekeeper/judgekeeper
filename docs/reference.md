# judgekeeper reference

Every command, file format, flag, exit code and config key. The README has the short version.

- [start: find your results, label, see the result](#start-find-your-results-label-see-the-result)
- [setup: set a project up in one step](#setup-set-a-project-up-in-one-step)
- [init: a starter rule file](#init-a-starter-rule-file)
- [Anchor sets, judging and the report](#anchor-sets-judging-and-the-report)
- [check: a table in, a report out](#check-a-table-in-a-report-out)
- [How verdicts are read](#how-verdicts-are-read)
- [Bring your own judge](#bring-your-own-judge)
- [import: promptfoo, DeepEval and Inspect AI results](#import-promptfoo-deepeval-and-inspect-ai-results)
- [import mlflow and import langfuse](#import-mlflow-and-import-langfuse)
- [Records format: import records](#records-format-import-records)
- [record(): save your own judge's verdicts with one line](#record-save-your-own-judges-verdicts-with-one-line)
- [Unknown judge fields](#unknown-judge-fields)
- [Your API keys](#your-api-keys)
- [Gate CI on the judge](#gate-ci-on-the-judge)
- [pytest plugin](#pytest-plugin)
- [Migrate to a new judge](#migrate-to-a-new-judge)
- [Exit codes](#exit-codes)
- [GitHub Action](#github-action)

## start: find your results, label, see the result

```
judgekeeper start [PATH] [--tool NAME] [--metric NAME] [--experiment NAME_OR_ID]
                  [--tracking-uri URI] [--pass-if RULE] [--label-map MAP] [--judge-model NAME]
                  [--yes] [--new | --review | --fix | --ask-again | --try-new-judge |
                  --label-more] [--test-pass-mark]
                  [--times N] [--allow-calls N] [--python PATH] [--fields LIST]
                  [--judge-command CMD] [--agent-prompt] [--no-browser] [--port N]
```

Finds the results your eval tool already saved, names your eval tool and your judge, opens a local page where you mark answers Correct or Wrong without seeing the judge's verdict, and shows how often the judge agrees with you. No AI calls unless you say yes. Then your own judge runs through your own tool; judgekeeper never sees your key, it only checks its name: it opens `.env` files only to say which key your judge will use, and keeps only the variable names. It never runs your app. It runs your eval tool only to grade saved answers again, after you say yes.

| Flag | What it does |
|---|---|
| `PATH` | Your project folder (default: this folder), or one results file or MLflow store (`mlflow.db` or an `mlruns/` folder), which skips the search. `.judgekeeper/` is made next to a file or store, never inside it |
| `--tool NAME` | Which eval tool's results to use when several are found: `records` (what `judgekeeper.record()` saved), `promptfoo`, `deepeval`, `inspect`, `mlflow` or `table` |
| `--metric NAME` | The judge (metric, assertion or scorer) to check when the results hold several, as in `import` |
| `--experiment NAME_OR_ID` | MLflow: the experiment to read when several have judge results. With two stores in the folder, the store that holds it is read. When no store has it, the error names each store searched and the experiments in it |
| `--tracking-uri URI` | MLflow: the store to read, when the folder has several: `mlflow.db`, `sqlite:///...`, an `mlruns/` folder or a `file:` address of one. Default: the store `MLFLOW_TRACKING_URI` names, when it is in the folder. A tracking server is read with `judgekeeper import mlflow` (its own `--tracking-uri`), not with `start` |
| `--pass-if RULE` | A rule for numeric verdicts, e.g. `score>=0.5`, as in `import` |
| `--label-map MAP` | Extra verdict spellings, e.g. `good=pass,bad=fail`, as in `import` |
| `--judge-model NAME` | The judge's model, when the results do not record it. Saved with `"model_source": "given by you"`. A usage error when the results already name a model |
| `--yes` | Without a terminal, answer every yes/no question with its default (open the page, continue, label anyway). It never picks between tools or judges |
| `--new` | Start a new check: everything in `.judgekeeper/` except `baseline.json` and `records/` moves to `.judgekeeper/previous-<date>/`. Nothing is deleted |
| `--review` | After a result: review the answers where you and your judge disagree (below). Answers the menu |
| `--fix` | After the review: what your judge gets wrong, and a fair test of a change on answers set aside (below). Free, no AI call. Answers the menu |
| `--test-pass-mark` | With `--fix`: test the pass mark that fits your marks best on the answers set aside, in the terminal. Free: the scores are saved, so no judge call |
| `--ask-again` | After a result: ask your judge again about your labeled answers (below). It shows the plan and asks before any call. Answers the menu |
| `--try-new-judge` | After a result: try the new version of your judge (found in your newest results) on the answers you already marked; it asks before any call (below). Answers the menu |
| `--label-more` | After a result: open the labeling page to label more. Answers the menu |
| `--times N` | How many times each answer is asked about, 1 to 5: default 2 for `--ask-again`, 1 for `--try-new-judge` |
| `--allow-calls N` | Asking again: approve up to N judge calls without the question. Needed without a terminal, and above 1,000 calls at a terminal too; below the planned calls it refuses. `--yes` never approves spending |
| `--python PATH` | Asking again: the Python you run your evals with, for DeepEval, Inspect AI and MLflow (default: the active virtual environment, else the project's `.venv` or `venv`, else the Python running judgekeeper) |
| `--fields LIST` | Asking a DeepEval GEval judge again: the parts it reads, e.g. `input,actual_output` (DeepEval does not save them) |
| `--judge-command CMD` | Asking again: your own judge as a command, with the `--exec` contract (one answer as JSON on stdin, the verdict on stdout). Also for a judge that can't be asked again otherwise |
| `--agent-prompt` | Print a prompt for your coding agent that turns judge results saved in your own format into judgekeeper's table, then exit (below) |
| `--no-browser` | Print the labeling page's link instead of opening a browser. With `--fix`, print what your judge gets wrong in the terminal instead of serving a page |
| `--port N` | Port on 127.0.0.1 for the labeling page (default 8765) |

**`judgekeeper.toml` first.** When the project's `judgekeeper.toml` has a `[start]` table ([written by `setup`](#setup-set-a-project-up-in-one-step)), `start` reads it before anything else: a mapped results file is read with its map and nothing is searched; a saved tool and judge are used without asking (`--tool` and `--metric` still win); a saved model names the judge when the results do not.

**What it reads.** It looks only inside the folder, to a depth of four folders, skipping `.git`, `node_modules`, virtual environments and hidden folders (except `.deepeval`, and `.judgekeeper/records/`, where `judgekeeper.record()` writes). It stops after 5,000 files or 2 seconds and says so. It does not follow symbolic links, and results files over 200 MB are listed, not read.

| Tool | How it is found | What is read |
|---|---|---|
| `judgekeeper.record()` | `.judgekeeper/records/*.jsonl` | Every file written by the newest file's judge (one eval run can be many processes, so many files; a newer file wins for a repeated answer). Several judge names: it asks which, `--metric` answers. A last line cut short is left out; a file it cannot read is left out, with the `--check` command that shows why ([below](#record-save-your-own-judges-verdicts-with-one-line)) |
| promptfoo | `promptfooconfig.yaml`, `.yml` or `.json` | JSON results files (`promptfoo eval -o` or `promptfoo export eval`). With a config and no results file, it offers to run `promptfoo export` for you (below), or prints the commands |
| DeepEval | `.deepeval/`, or `deepeval` in `pyproject.toml` or `requirements*.txt` | `test_run_*.json` (in `DEEPEVAL_RESULTS_FOLDER` when it points inside the folder, or any results folder), else DeepEval's hidden copy of its newest run, `.deepeval/.latest_run_full.json` or `.deepeval/.latest_test_run.json` (counted once). When the copy holds a different run than the newest `test_run_*.json`, it says so and how to read the copy. A GEval judge built with evaluation steps and no criteria is shown by its steps |
| Inspect AI | `logs/`, or `inspect-ai` in the dependencies | `.json` logs; `.eval` logs need `pip install "judgekeeper[inspect]"` in your project's environment. Also `INSPECT_LOG_DIR` inside the folder |
| MLflow | `mlruns/` or `mlflow.db` | The local store: `mlflow.db` through a temporary copy, never opened itself; an `mlruns/` folder where it is, with MLflow's folder-store setting (`MLFLOW_ALLOW_FILE_STORE`, which MLflow 3.16 and later need) switched on for that read only, unless you set it yourself. An `mlruns/` folder copied or cloned from another computer is read from its own folder (MLflow looks for each trace's files where they were made); answers whose trace files are missing are left out, and it says so. Both stores in one folder: it names both, asks which at a terminal, and without one reads `mlflow.db` and prints the command for the other (`PATH`, `--tracking-uri`, `--experiment` or `MLFLOW_TRACKING_URI` choose without asking). MLflow's own log lines (its hint for coding agents, a warning per trace) are kept out of the output while it reads. Needs `pip install "judgekeeper[mlflow]"` in your project's environment |
| A plain table | A CSV, TSV or JSONL file at most two folders deep with `input`, `output` and `verdict` (or `judge_verdict`, `judge`) columns | That file; a `model` or `judge_model` column names the judge's model. It prints the counts, the pass/fail split and the first 3 rows, so a wrong table shows |

**No results it can read.** It says so, and does not tell you to run your eval again unless your tool's normal run writes files it reads. It looks for a recent JSON, JSONL or CSV file (changed in the last 90 days, at most four folders deep) that holds, at any depth, a score-like key (`score`, `scores`, `verdict`, `pass`, `passed`, `success`, `label`) next to an input-like and an output-like key, and names it: your judge's results in a format of its own. To use them, turn them into a table with the columns `id`, `input`, `output`, `verdict` (pass or fail) and `reason`, plus `judge_model` when you know the model, one CSV per judge or criterion, and run `judgekeeper start <file>`. It also prints a prompt for your coding agent that writes that table for you (`--agent-prompt` prints it alone). With DeepEval it adds that results are saved only when tests run through `deepeval test run` or `evaluate()`: calling a metric's `measure()` directly saves nothing.

From the newest results it builds the pool: every answer with a clear pass or fail, counted once (the same input and output; the newest file wins, then the majority of its verdicts, a tie counting as fail). With fewer than 30 answers it adds older results from the same judge. Answers with no real decision from the judge are left out and counted (below). The newest file still wins: an answer the newest results left out stays out, even when older results have a decision for it. A/B comparisons are refused (exit 2). Human labels already in the results are not used. Under 30 answers it says how many you have, prints the command that makes more with your own tool (naming the config, test file or task it read, and saying that running your eval again costs model calls) and asks whether to label anyway; with `--yes` it says "Labeling anyway, as you asked (--yes)." and goes on. A judge that failed (or passed) only 1 to 14 answers is not a stop: it says so, since that may mean it passes too much (or fails too much), and goes on. Your labels decide Correct and Wrong; the judge's verdicts only decide how answers are picked.

**Did your judge actually judge?** Before you label, `start` checks the judge's own decisions: no labels, no AI call, no key. Right after the pass and fail counts it says what it found, one line each:

- **No real decision.** The judge's call failed (DeepEval's `error`, or no score with `success` false; promptfoo's `graderError`, or in older files its grader-failure reasons such as "API error:"; Inspect AI's `grader_failed`, or a sample that errored before it was scored; MLflow's `feedback.error`), its reply could not be read (promptfoo's "Could not extract JSON" or "Error parsing output"; Inspect AI's "Grade not found in model output"), or there is no decision at all (a blank cell). These answers are left out of the pool, and it says what your eval tool counted them as: promptfoo and DeepEval count them as fails.
- **Checked nothing.** A DeepEval metric whose judge returned no verdicts at all scores a full 1.0 and passes (its logs show an empty `Verdicts:` list). Left out too.
- **Passed an empty answer.** The app's answer is empty and the judge passed it. Kept: it is a real decision, and a good one for you to mark. (DeepEval refuses an empty answer and saves an error instead, so there it is a "no real decision": an empty answer it could not judge, `empty_answer_refused`.)
- **The same decision for every answer.** The judge passed (or failed) all of them.
- **The reason says the opposite.** The judge's reason starts with PASS, PASSED, FAIL or FAILED, or its last `verdict:`, `grade:`, `result:`, `decision:`, `final verdict:` or `final answer:` says pass, fail, correct or incorrect (or Inspect AI's `GRADE: C` or `GRADE: I`), and either of them is the other decision. No other words count, so "does not fail" or "partially correct" are never flagged. Skipped for a score with a pass mark (`--pass-if`; DeepEval, whose metrics pass by a score and a threshold; `judgekeeper.record()` with `pass_mark`; and a file set up with `setup` whose decisions are scores).

None of these stops `start`. When nothing is found it prints one line: "Your judge made a real decision on every answer." The answers found are listed in `.judgekeeper/judge-check.csv` and `judge-check.json`, and the result page shows a "Did your judge actually judge?" card. `import`, `report` and `check` read your files exactly as before.

**The page.** One answer at a time, in blocks of 10 in a seeded order: 5 from the judge's passes and 5 from its fails, the other group filling the blocks once one runs out (so with 2 fails you see both among the first 10). Keys: `1` Correct, `2` Wrong, `S` skip, `U` undo. The judge's verdict, reason and score never reach the page. Every click is saved at once. "See my result" works at any time. When every answer is labeled or skipped, the result is shown.

**The result.** TPR, TNR and the real pass rate are corrected for showing far more of the judge's fails than the pool holds: worked out per group and weighted by the group's size. Their ranges come from Jeffreys draws: each group's share of answers you marked Correct gets the distribution Beta(Correct + 0.5, labeled − Correct + 0.5); 20,000 pairs of draws, with a fixed seed so the same labels always give the same ranges, go through the same formulas, and a range is the middle 96% of what comes out (widened, if needed, to hold the number itself). The 96% was chosen by a coverage check, not assumed: [`docs/examples/coverage/coverage.md`](examples/coverage/coverage.md) simulates thousands of checks for judges that pass 50%, 70% and 90% of answers, agree weakly to strongly, and 10 to 40 labels per group. At 96% the ranges held the true value at least 93.6 times in 100 in every case and 96.2 on average; 95% fell to 91.6 in one case. The ranges before (Wilson at 97.5% per group, joined at the corners) held it 99.1 times in 100 on average: too cautious, so they were wider than needed; the ranges now are 27.1% narrower on average. On real data too: on 5 real judges from 3 public datasets, with 25 + 25 labels, the TPR and TNR ranges held the value worked out from all of the dataset's human labels in 96.0 checks in 100 on average (lowest 94.6, highest 98.4), over 1,000 checks per judge: [`docs/examples/real-data-check/report.md`](examples/real-data-check/report.md). Kappa is Cohen's kappa on the weighted table, with no range. A rough check needs 15 answers you mark Correct and 15 you mark Wrong; a reliable result 25 of each, and both the TPR and the TNR range no wider than 0.30. When the judge passes most answers, its TNR range narrows slowly: the result then says it is not reliable yet, which range is still too wide, and to label more, and the labeling page says the same under its meters. Below the rough check there is no verdict. With fewer answers than a target needs (30, or 50), `start` says so before you label.

**Saved in `.judgekeeper/`.** Every string from a results file is scrubbed of credentials before it is written. Your `.gitignore` is never changed: the folder holds your answers' text, so commit it only if your data may live in your repository.

| File | What | When it is written |
|---|---|---|
| `start.json` | The tool, the results files used, the judge and its fingerprint, its pass mark (for a judge that gives a score), the pool counts, what was left out and why, the seed and the queue | When labeling starts |
| `pool-judge.jsonl` | The judge's verdict on every pool answer, as a run file with the full fingerprint on every line | When labeling starts |
| `pool.jsonl` | Each pool answer's id, input and output | When labeling starts |
| `judge-check.json`, `judge-check.csv` | Did your judge actually judge? The counts, and each answer found: `id,problem,tool_counted_as,judge_decision,judge_reason,input,output` (the problem is `error`, `unreadable`, `empty_answer_refused`, `empty`, `nothing_checked`, `empty_answer_passed` or `reason_says_opposite`) | When labeling starts, or when `start` names the CSV |
| `labels.csv` | Your labels: `id,input,output,human_label,notes` (a skipped answer has the note `skipped`) | On every click |
| `anchors.jsonl` and `anchors.manifest.json` | The answers you labeled, as a frozen anchor set for `judge`, `baseline` and `gate` | With each result |
| `result.json`, `result.html` | The result: every number, the label counts, the fingerprint and the date; the page opens without a server. After `--fix` it also holds a `fix` block (the two counts and every test), shown as a "Fix your judge" card; the main result never changes | With each result |
| `history/` | Earlier results (`result-<date>.json`) and, before a re-check, the check it replaced (`check-<date>/`, with its judge check files) | With each result |
| `previous-<date>/` | Everything that was here before `--new`, or before you labeled new answers | On `--new` |
| `records/` | Your judge's verdicts, saved by `judgekeeper.record()` (not by `start`); `--new` leaves them in place | By your eval |
| `again/<date>/` | Asking your judge again: `judge-again-<n>.jsonl` (one run file per time asked, every line with the full fingerprint, plus the tool and its version, the names of setting variables that were set, and `exact` or `close copy` with the reasons), `again.json` (the numbers), and for promptfoo its own `promptfoo.json`, for DeepEval, Inspect AI and MLflow the script's output (`deepeval.jsonl`, `inspect.jsonl`, `mlflow.jsonl`). `result.json` gains an `again` block; an earlier one moves to `history/again-<date>.json` | When you ask your judge again |
| `new-judge-<date>/` | Trying your new judge: `new-judge.json` (the numbers), `new-judge-<n>.jsonl` (one run file per time asked, every line with the full fingerprint and `exact` or `close copy`), the tool's own output (`promptfoo.json`, `deepeval.jsonl`, `inspect.jsonl` or `mlflow.jsonl`), and `confirm/` (the quick check: `start.json`, `pool.jsonl`, `pool-judge.jsonl`, `labels.csv`, `result.json`, `result.html`). `result.json` gains a `new_judge` block | When you try your new judge |
| `review.json` | The review of the disagreements: the answers shown, the seed, your second looks and your choices | On every click of the review |
| `judge-mistakes.csv`, `rule-unclear.csv` | The disagreements you marked "The judge was wrong" or "The rule is unclear": id, input, output, your label, your second-look label, the judge's verdict and reason, and your why | On every click after the judge is shown |
| `fix.json` | Fixing your judge: the result it is of, the seed, the answers used and the answers set aside, and every test done on them | On the first `--fix` for a result |
| `fix/` | `patterns.json` (the counts and the pattern lines, from the answers used only), `pass-mark.json` (the pass-mark test), `prompt.txt` (the prompt for an AI assistant, scrubbed), `rule.txt` (your new rule) and `rule.json` (its checks, whether you pasted it or wrote it yourself, and where it goes) | With `--fix` |

**Running it again.**

| What is saved | What `start` does |
|---|---|
| Nothing | Everything above |
| Labeling not finished | The results it uses and the judge's pass and fail counts, then "Continue?": the page opens at the next answer |
| A result, and the same results | A menu: review the disagreements, fix your judge (once the review found a mistake or an unclear rule), ask your judge again, label more (a new result replaces the old one, which goes to `history/`), or nothing. `--review`, `--fix`, `--ask-again` and `--label-more` answer it |
| A result, and newest results from a new version of the judge (same tool; its model, prompt or temperature changed, or its name changed and you confirm it is the new version; `--metric` names it) | The same menu, with "Try your new judge on your N marked answers" first. `--try-new-judge` answers it |
| A result, and new results from the same tool and judge | A re-check: your saved labels against the judge's new verdicts, shown next to the last result, after saying whether the judge's model, prompt or temperature changed. Labeled answers your judge made no real decision on this time are left out, and it says how many. When fewer than 15 Correct or 15 Wrong of your labeled answers are in the new results unchanged, it offers to label the new results instead (it says your app gives different answers only when some answers are gone, not just left out) |

**Reviewing the disagreements** (no AI call). First you look again at every answer where you and your judge disagree, mixed with as many answers you agreed on (at least 3), with the judge's verdict still hidden: Correct, Wrong or Not sure. Then you see what the judge said on each disagreement, with its reason, and mark it: the judge was wrong, I was wrong, or the rule is unclear. After "The judge was wrong" or "The rule is unclear", one optional line asks why (at most 300 characters; it helps fix your judge). Your labels in `labels.csv` never change and stay the main result; the result adds a few lines with the numbers your second-look labels would give and what you called after seeing the judge.

**Fixing your judge** (`--fix`, no AI call), once the review is done and found at least one mistake or unclear rule. Your final mark for an answer is your second look when you gave one, else your first label; "I was wrong" makes it the judge's verdict, and an answer you were not sure about is left out. The first time, about 30% of the answers with a final mark are set aside (30% rounded up of each of four groups: the judge's passes and fails, each split by whether it agrees with you; a group of one answer stays on the page), in a seeded order, and it says how many. They are used only to test a change, so the test is fair: nothing from them is shown on the page or counted in a pattern. The page, "What your judge gets wrong", shows from the rest: your judge's rule; "Passed, but you said Fail" and "Failed, but you said Pass", each a list that opens to the question, the answer, the judge's reason and your why; plain patterns, only when they are strong (most mistakes on one side, from 3 mistakes; most mistakes within 0.1 of the pass mark; the wrong passes or wrong fails, at least 4, half again as long as the answers it got right; words in 3 or more mistakes that the right answers rarely hold, at most 5); and the answers whose rule is unclear. The main result never changes.

**Moving the pass mark** (on the same page, free). For a judge that gives a score and passes it at a pass mark: DeepEval's `threshold` (not in strict mode; whether a lower score passes is read from the saved verdicts), the `pass_mark` of `judgekeeper.record()` or of a file `setup` mapped, or `--pass-if`. When every saved verdict follows its score, it tries a point between each two neighbouring scores of the answers it used and picks the one with the best (TPR + TNR) / 2; a tie goes to the mark nearest yours. Rounding up sets aside more of the few disagreements than of the many agreed answers, so here each answer is weighted by its group's size in the pool and its share of that group's marks (agreeing with you or not), which keeps the numbers on either part those of all your marks. One click (or `--fix --test-pass-mark`) tests it on the answers set aside: how many it fixed and broke (an exact sign test decides "it did better", "it did worse" or "Can't tell yet"), and, folded away, how often your judge agreed with you before and after (weighted the same way, with no range). It needs 5 answers you marked Pass and 5 you marked Fail among those set aside, and after 3 tests on the same answers it says they no longer give a fair test. Then it says where the pass mark is set (and the file and line where it probably is: it searches your project's text files, never your `.venv`, `venv`, `node_modules`, `.git` or `.judgekeeper/`, and imports or runs nothing). judgekeeper never changes your files.

**Changing the rule** (on the same page, no AI call from judgekeeper). When your judge has one rule for every answer (not a rule per test, as with promptfoo rubrics written per test), "Copy a prompt for your AI assistant" gives a prompt to paste into any AI assistant: your rule (a DeepEval GEval's evaluation steps, numbered), the template parts to keep (such as `{{output}}`, and Inspect's `GRADE:` line), and, from the answers judgekeeper used only, never the ones set aside, up to 20 mistakes (those with your why first), 6 answers whose rule is unclear and 6 it got right (half passes, half fails), each text cut to 1,500 characters, with short labels instead of ids. It asks for the smallest change, in general words, between the lines `NEW RULE START` and `NEW RULE END`. "I'll write it myself" opens the same box with your rule in it. On save, judgekeeper takes the text between those lines (or the whole paste) and checks it: an empty rule, or one that dropped a template part, is not saved; a rule more than 1.5 times as long as the old one plus 400 characters is "a big change", and one that copies 8 words in a row from your answers "may only fix these answers" (both said, not blocking). It shows the change word by word, then where the rule probably is in your files (a read-only search of your project's text files for the start of your rule, skipping `.venv`, `venv`, `node_modules`, `.git` and `.judgekeeper/`, importing or running nothing), what to change by tool (promptfoo: the `value:` of the llm-rubric assert; DeepEval: `evaluation_steps=[...]` in `GEval(...)`; Inspect AI: `instructions=` in `model_graded_qa(...)`; MLflow: `instructions=` in `make_judge(...)` or the text of `Guidelines(...)`), and a prompt for your coding agent. judgekeeper never changes your files. Then run your eval and `judgekeeper start`: for promptfoo, DeepEval, Inspect AI and MLflow it offers Try your new judge, which also tests the new rule on the answers set aside (below); for your own code or a table, `start` checks the new judge on new answers.

**Asking your judge again.** judgekeeper can have your own eval tool grade the answers you labeled again, with your own judge; your app is not run. Before anything runs it shows a plan, with no API call: the judge, and whether it is exactly your judge, a close copy (and what differs) or can't be asked again (and why); which key your tool will read, by name only (judgekeeper reads the names in `.env` files, never their values); setting variables that change the judge (`OPENAI_TEMPERATURE`, `*_MAX_TOKENS`, `*_BASE_URL`, ...); the judge calls (labeled answers × times × calls per answer for that judge type); a cost range at prices dated in judgekeeper (`prices.py`; never fetched); and what the run touches. For DeepEval, Inspect AI and MLflow, a small script judgekeeper ships runs with your Python to build your judge and check it, with no call. Then it asks "Go ahead? [y/N]" (default No; without a terminal, `--allow-calls N` answers it). After No it says "Your judge was not called; nothing was spent." Before your first result there is nothing to ask about: `--ask-again` says it needs your labels, with the command that labels, and, for a judge in your own code (`judgekeeper.record()`, a file mapped by `setup`, or a table), that asking it again needs `--judge-command`.

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

After asking: steadiness (how often the judge changed its verdict on the same answer, weighted by the pool's groups, with Wilson intervals), agreement today (your labels against the first new verdicts, weighted by the saved groups, with Jeffreys ranges as above: in each saved group, the share you marked Correct is drawn as for your result, and the shares the judge got right again are drawn from Beta(k, m − k), exact when every one or none agreed, so a judge that gives the same verdicts again gets your result's ranges; when that would leave a range of one point, such as 0% when the judge now fails every answer you marked Correct, those shares get Jeffreys draws too, so a range always keeps its width. In the coverage check, the stratified bootstrap used before held the true value as rarely as 53.8 times in 100; these ranges hold TPR and TNR at least 93.6 times in 100 in every case; kappa is given without a range, as in your result) next to your last result, and how often the first new verdict matched the saved one (below 90% it asks whether the judge's model or prompt changed). For a close copy, the reason is said once, first, and every number line ends "(close copy)". Your labels and your main result do not change.

**Trying your new judge.** You changed your judge's rule or model and ran your eval once. When the newest results hold a new version of your judge, the menu offers to try it on the answers you already marked (`--try-new-judge`). judgekeeper rebuilds the new judge from the newest results and has it grade your marked answers, once by default (`--times`), never your new outputs. The plan, the key-name check and the default-No question are the same as for asking again. By tool: promptfoo uses the model-graded assertion and grader of the newest results (matched to each answer by the test's vars when they differ by test; an answer with no matching test is left out and listed); DeepEval GEval uses the newest criteria, rubric, threshold and steps (the steps of the newest row with the same input, else the steps most rows share; a close copy when the steps differ by answer); Inspect AI uses the newest scorer and grader, exactly your judge only for its own scorers with the same Inspect version, since no saved prompt can be compared, else a close copy; MLflow uses the newest registered version, or the built-in judge with the newest model; for your own command, give the new one with `--judge-command`.

The result shows both judges against your same marks, side by side, weighted by the old judge's groups, with ranges. The old numbers are your last result, or your judge asked again, when you did that (it says so). It always adds that a judge changed after you saw its mistakes on these answers will look better on them, and offers "Mark 10 Correct and 10 Wrong new answers to confirm? [Y/n]": a quick check on answers from the newest results you never marked, half from the new judge's passes and half from its fails. Its result always shows the wide ranges. When you set answers aside with `--fix` for this result, the new judge is first tested on those, as a change is on the fix page: how many it fixed and broke, against your old judge asked again when you did that, else its saved verdicts; it counts toward the 3 tests on those answers, and when you wrote the rule yourself it adds that the test may look better than it is. Your main result stays the old judge's until you run `judgekeeper start --new`, which makes the new judge the one being checked: everything, the old marks and the quick check included, moves to `previous-<date>/`, and nothing is deleted.

**When promptfoo's results are only in its database**, at a terminal `start` offers to run `promptfoo export eval latest` for you (no AI call; promptfoo's telemetry, update check and logs off). The file is checked against this project's promptfoo config (its description, else its prompts): a run from another project is deleted with a note on how to find yours; otherwise it is saved as `promptfoo-results.json` and `start` carries on.

**Without a terminal** (a script, CI, a coding agent) it never asks. It prints what it found and the flag or command that answers the question, and exits 8; `--yes` takes the defaults. A printed command repeats the flags you gave (the path, `--metric`, `--experiment`, `--no-browser`, ...), so it works as printed. With `--no-browser` the question is "Start the labeling page? It will print a link."; after No at a terminal it says the command to run when you're ready. After you pick a tool, an experiment, a judge or an MLflow store at a terminal, it prints what picks it next time, such as `(Next time: --metric safe_wording)` or `(Next time: judgekeeper start mlruns)`. Labeling needs a person: in CI, `start` can only find and report. Exit codes: 0 done (also when you stop early, after No, and after No to a spending question), 1 a runtime failure (for asking again: the tool failed), 2 a usage error, nothing it can use found, or `--review`, `--ask-again` or `--try-new-judge` before a result (it prints the command that labels first, with `--yes` when there is no terminal, and what the flag does after), 8 stopped at a question that needs an answer (nothing went wrong), 130 stopped with Ctrl-C (asking again saves nothing from that run).

**Installed in your project?** judgekeeper belongs in your project's own Python environment, like pytest. In a terminal, `judgekeeper --version` says judgekeeper is ready and what to run next; when Python is not running in a virtual environment, or judgekeeper was installed as a tool for the whole computer (in the folder where a tool installer keeps its tools, not in a project), it adds: "judgekeeper is installed outside a project. Install it inside your project's environment instead (see www.judgekeeper.com/start.html#install)." Piped or in a script it prints only `judgekeeper <version>`.

## setup: set a project up in one step

```
judgekeeper setup [PATH] [--metric NAME] [--judge-model NAME] [--yes]
```

For a project whose judge saves its results its own way, and to set any project up in one step. Run it in your project folder (or give `PATH`: the folder, or your judge's results file). It never edits your code, and it writes nothing before the one question that lists every file change.

1. **It finds what there is.** Results `start` reads as they are (promptfoo, DeepEval, Inspect AI, MLflow, a table, `judgekeeper.record()` files): it names the tool and the judge, and saves them. Else a results file in a format of its own: a recent JSON, JSONL or CSV file whose items hold a score-like key with an input-like and an output-like key, at any depth.
2. **It maps that file.** It lists every nested path with an example value (cut to 60 characters), such as `cases[].A.output` and `cases[].A.scores.<criterion>.score`, and says how it reads it: what one answer is (the list that holds the answers), the input, the answer, the score or verdict, the reason, the id and the judge's model, from key names (`input`, `question`, `prompt`; `output`, `answer`, `response`, `actual_output`; `score`, `verdict`, `label`, `grade`; `reason`, `explanation`) and value types. Every criterion under the scores is a judge (`judges: safe_wording, helpful`). A pass mark and a judge's model that the file states, for each answer or for the whole run (`pass_mark`, `threshold`; `judge_model`, `judge.model`), are read, and it says where they came from (`0.7 (judge.pass_mark in the file)`); a run's own pass mark is used for its answers. Otherwise scores between 0 and 1 get the pass mark 0.5.
3. **It asks only what it cannot tell.** Several answers per item (A and B): "Count each as its own answer?" (No: which one). Several criteria: "Which judge do you want to check?" (or all, one at a time; `--metric` answers, `--metric all` for every judge). Scores outside 0 to 1, with no pass mark in the file: the pass mark. Answers with an error or a score made by a rule (a reason starting "Rule"): "Leave them out?". First, at a terminal, "Is this right?" (without a terminal only when a guess was made from value types alone). After No: "Which part is wrong?", a numbered list (what one answer is, the input, the answer, the score, the reason, the id, the judge's model, the pass mark, none of these fit); you choose that part from the file's paths, or type the pass mark, and it shows how it reads the file again. Then it shows 3 answers as it will read them.
4. **One question for every file change:**
   ```
   Set up judgekeeper in this project?
     • save judgekeeper.toml (where your judge's results are and how to read them)
     • add .judgekeeper/ to .gitignore (your answers stay off Git)
     • add judgekeeper to requirements-dev.txt
   [Y/n]
   ```
   - `judgekeeper.toml`: a `[start]` table (below). An existing file keeps every other table and line; only `[start]` is added or replaced.
   - `.gitignore`: only in a Git repository, and only when no `.judgekeeper` line is there. The lines are `.judgekeeper/*`, `!.judgekeeper/baseline.json` and `!.judgekeeper/migrations/`, so your answers and labels stay off Git while a [gate baseline](#gate-ci-on-the-judge) can still be committed.
   - The requirements line goes to the first that exists: `pyproject.toml`'s `[dependency-groups] dev` or `[project.optional-dependencies] dev`, then `requirements-dev.txt`, then `requirements-dev.in`; only when judgekeeper is not listed anywhere; never into the main requirements. With none of them, the list says "judgekeeper is not listed in your project's requirements; add it so teammates get it" and changes nothing. A `pyproject.toml` list in a shape judgekeeper does not edit is left alone, with a message.

When a file cannot be mapped (no answers or no scores in it), or you say none of the parts fit, it prints the prompt for your coding agent that writes a table instead, and the `judgekeeper.record()` way. Nothing found at all: it says the three ways in (`setup` with a file, one [`record()` line](#record-save-your-own-judges-verdicts-with-one-line), or the coding-agent prompt). Run again, it says what `judgekeeper.toml` holds and asks before changing it (default No).

| Flag | What it does |
|---|---|
| `PATH` | Your project folder (default: this folder), or your judge's results file |
| `--metric NAME` | The judge to check when the results hold several; `all` for every judge, one at a time. Needed without a terminal when there are several |
| `--judge-model NAME` | The judge's model, when the results do not say it; saved in `judgekeeper.toml` |
| `--yes` | Without a terminal, answer every yes/no question with its default, including the one before the file changes. Without a terminal and without `--yes`, it prints the list and exits 8 |

Exit 0 when a source is set up (or you kept the one set up before), 2 when none was found, 8 when a question needs an answer.

**The `[start]` table of `judgekeeper.toml`.** Nothing secret; `start` reads it first. The same file holds `[gate]` and `[migrate]` (below).

```toml
[start]
source = "map"                  # or the tool start reads as it is: records, promptfoo, deepeval, inspect, mlflow, table
file = "history/evals.jsonl"    # map: the results file, inside the project
judge = "Safe wording"          # the judge to check; "*": every judge, one at a time
pass_mark = 0.5                 # map: pass when the score is at least this
model = "claude-opus-5"         # only when the results do not say which model judged

[start.map]                     # how to read the file
each = "cases[]"                # the items: every element of the list cases
id = "id"
input = "prompt"
output = "{side}.output"
sides = ["A", "B"]              # one answer per side
score = "{side}.scores.{judge}.score"
reason = "{side}.scores.{judge}.reason"
kind = "score"                  # or "verdict": pass/fail values, no pass mark
judges = ["Safe wording", "Plain language"]
model_key = "judge_model"       # the path that names the judge's model, in the item or around it
pass_mark_key = "judge.pass_mark"  # where the file states its pass mark: each run's own is used
leave_out = true                # leave out answers with an error or a score made by a rule
```

Paths are keys joined by dots; `[]` after a key means every element of that list; a key with other characters than letters, digits, `_` and `-` is written in double quotes (`"User Question"`). Each line of a JSONL file whose items are inside it (often one eval run) is its own set of results, newest first, as for any other tool; in a flat file each line is one answer. When the file no longer fits the map, `start` says "Your results file changed shape. Run judgekeeper setup again."

## init: a starter rule file

```
judgekeeper init [--out prompts/judge.md] [--pairwise] [--force]
```

Writes one rule file, the prompt your judge runs with, from a template that ships in the package (`src/judgekeeper/templates/single.md`, or `pairwise.md` with `--pairwise`). The file loads with the Anthropic and OpenAI runners as it is: frontmatter `rubric_version: my-metric-v1`, the placeholders `{{input}}` and `{{output}}` (pairwise: `{{output_a}}` and `{{output_b}}`) and the final `Verdict:` line. The parts you write are marked `[FILL IN: ...]`: the one thing being checked, what counts as pass, what counts as fail, two or three examples of each, and edge cases (pairwise: what makes one output better, and the tie rule). Parent folders are created; an existing file is not overwritten without `--force` (usage error, exit 2). It prints the next steps: label real items in `anchors.jsonl`, `judge --prompt`, `validate`. No model is called and nothing else is written.

`judge --prompt` refuses a file that still contains a `[FILL IN` marker, naming the first marker and its line number (usage error, exit 2). Change `rubric_version` whenever you change the rule: a changed rule is a changed judge, and `gate` reports `JUDGE_CHANGED`. How to write the rule, with two worked examples: [`own-metric.md`](own-metric.md).

## Anchor sets, judging and the report

```
pip install "judgekeeper[anthropic]"      # for --runner openai: pip install "judgekeeper[openai]"
judgekeeper init                          # writes prompts/judge.md; fill in its [FILL IN: ...] parts
judgekeeper judge anchors.jsonl --runner anthropic --model claude-haiku-4-5-20251001 \
  --prompt prompts/judge.md --runs 3 --out runs/my-judge/
judgekeeper validate anchors.jsonl runs/my-judge/ --out reports/my-judge/
```

`--runner anthropic` and `--runner openai` call the model for you and need the provider's client library, which the first line installs in your project's environment (switch it on first); plain `pip install judgekeeper` does not include it. `--callable`, `--exec`, `check` and `import` do not need it. `prompts/judge.md` in the examples on this page is the rule file `judgekeeper init` writes (`judgekeeper init --pairwise` for an anchor set that compares two outputs).

An anchor set is JSONL with `id`, `input` and `human_label` on every line. Pairwise items add `output_a` and `output_b` with labels `A`/`B`; single-output items add `output` with labels `pass`/`fail`. `slice` and `notes` are optional. Label with `judgekeeper start` (it writes `.judgekeeper/anchors.jsonl`), or write the file yourself. The first `judge` or `validate` on an anchor set with no manifest seals it: it writes `anchors.manifest.json` (counts and sha256) and says so in one line, `Sealed anchors.jsonl: <n> items (sha256 <first 12 characters>...). Commit anchors.manifest.json with it.` After that, every command checks the anchor set against its manifest and exits with code 3 if it changed.

`judge` writes one `run-NN.jsonl` per run. Line 1 is a header with the judge fingerprint and a `source` object (`{kind: judgekeeper | table | callable | exec | promptfoo | deepeval | inspect | records | mlflow | langfuse, file, metric}`, plus `version`, `notes` and `warnings` for imports; imported and custom judges also record the `--pass-if` rule and label map used). Every judgment line carries the judge fingerprint (provider, model, served snapshot, endpoint, prompt hash, rubric version, temperature, timestamp). Pairwise items are judged in both AB and BA order.

`validate` writes `report.json` and a self-contained `report.html`. The headline is TPR, TNR (each with a 95% Wilson interval) and Cohen's kappa, mean over runs. Kappa is chance-corrected agreement with the human labels; TPR and TNR are the numbers to act on. The interval's n is the number of human-positive (or negative) items, not items × runs, because runs re-judge the same items. The report also has: the fingerprint and source, per-run numbers, a confusion matrix on majority verdicts, the noise floor across runs (per-item flip rate, run-vs-run kappa, majority verdict; with one run it reads "unknown: one run supplied", never zero), AB/BA position bias, a per-slice table, and every disagreement with the judge's rationale.

The verdict:

| condition | says |
|---|---|
| TPR or TNR below 0.80, or kappa below 0.6 | "not trustworthy as a gate" |
| otherwise, TPR or TNR below 0.90 | "usable with care" |
| otherwise | "usable as a gate" |

The lower of the two rates decides: TPR 0.95 with TNR 0.85 is "usable with care". A rate that could not be measured (no human labels of that class) also gives "not trustworthy as a gate".

Flags: position bias above 0.10, more than 10% of items flipping between runs ("noisy, use majority of runs"), one run only (noise floor unknown), judge errors above 2% of judgments, an incomplete judge fingerprint ("judge identity incomplete: <fields>"), and the label targets every command shares: `too_few_labels` (fewer than 15 labeled pass or 15 labeled fail, or A and B), `rough_check` (fewer than 25 of either) or `not_reliable_yet` (25 of each, but the 95% Wilson range of TPR or TNR still wider than 0.30, naming which). `label_quality` in `report.json` holds `n_labeled`, `per_class` (the count of each label), `check` (`too_few`, `rough` or `reliable`) and `wide` (the range, `tpr` or `tnr`, that keeps it from reliable, with its width). `report.json` keys read by `gate` are stable; later versions added `source`, `normaliser`, `errors`, `label_quality`, `notes`, `fingerprint_unknown`, `verdict.level`, `headline.tpr_ci`/`tnr_ci` and `noise_floor.status`.

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

One normaliser serves `check`, `check_judge`, `--callable` and `--exec`. It turns a raw judge output into `pass`/`fail` (or `A`/`B`) or `error`, plus a rationale:

- a bool: `True` is pass;
- a string, case-insensitively, through the label map. Defaults: `pass`/`fail`, `true`/`false`, `yes`/`no`, `correct`/`incorrect`, `right`/`wrong`, `1`/`0`, and a leading `PASS` or `FAIL` token (`PASS: looks right`). Pairwise: `A`/`B`. `--label-map "good=pass,bad=fail"` adds entries;
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

`judge(item: dict)` returns a bool, str, float, tuple or dict; it may be `async def` (this also works inside a running event loop, as in a notebook). `item` is the anchor item without `human_label` and `notes`. Pairwise items are judged twice, with `output_a` and `output_b` swapped the second time; the second verdict is mapped back to the original labels. `anchors` is an anchor JSONL path (sealed on first use, as `judge` does), or a list of items (written under `out` and frozen). `fingerprint` takes what you know: `provider`, `model`, `snapshot`, `endpoint`, `prompt` (text, hashed) or `prompt_hash`, `rubric_version`, `temperature`; everything else is recorded as unknown. Above 1,000 judge calls it needs `yes=True`.

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

## import: promptfoo, DeepEval and Inspect AI results

```
judgekeeper import <tool> <path>... [--metric NAME] [--labels labels.csv] [--pass-if RULE] \
  [--label-map MAP] [--runs-by-order] [--id-var NAME] [--map MAP] --out reports/x/
judgekeeper import records <path>... --check [--map MAP] [--pass-if RULE] [--label-map MAP]
```

`<tool>` is `promptfoo`, `deepeval`, `inspect` or `records`. A path is a file, a directory or a quoted glob; files are read in the order given (a directory or glob in name order). The output is what `check` writes: `anchors.jsonl` with its manifest, `runs/run-NN.jsonl` and `report.json` / `report.html`, with `source.kind` set to the tool and `source.version` to the tool's own format version when the file states one (promptfoo `results.version`, Inspect `version`). Exit 0 on success, 2 on a usage error. Per-tool pages: [promptfoo](integrations/promptfoo.md), [DeepEval](integrations/deepeval.md), [Inspect AI](integrations/inspect.md).

- `--metric NAME`: the judge to validate (promptfoo assertion `metric` or type, DeepEval metric `name`, Inspect scorer name). Optional when the files hold one; with several, leaving it out is a usage error that lists the names.
- `--labels TABLE`: human labels, CSV, TSV or JSONL with an `id` column and a `human_label` (or `label`) column, read through the same normaliser as `check`. It wins over human labels in the files (promptfoo web-UI ratings, Inspect score edits) and the report notes how many it replaced and how many differed. Rows with an empty label are skipped. A `slice` column is kept, so the report has per-slice numbers.
- `--pass-if`, `--label-map`: as in `check`. `--pass-if` is applied to the record's `score` (DeepEval `score`, promptfoo component `score`, numeric Inspect values); without it the verdict is the tool's own pass flag or label. Human labels never use `--pass-if`.
- `--runs-by-order`: number each item's verdicts in a file 1, 2, 3 in order of appearance, in place of any run index the file carries, instead of stopping when one run holds several verdicts for one item. Works with every tool. The promptfoo reader always numbers repeats this way, because promptfoo strips the repeat index.
- `--id-var NAME` (promptfoo only): the test var holding the item id.
- `--map MAP` (records only): see below.
- `--check` (records only): check the files and say what judgekeeper reads in them, without writing a report. See [Records format](#records-format-import-records).

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

## Records format: import records

judgekeeper's own format for judge results: one judged answer per line of a JSONL file (CSV and TSV work too). Use it when your judge saves its results in a way judgekeeper does not read: write these lines, check them with `--check`, then `import records`. Field names follow OpenInference annotations, so other tools' exports map onto it by renaming. Only a verdict is needed in practice; every field is optional. The smallest useful line:

```
{"name": "Safe wording", "input": "Do you ship to Canada?", "output": "Yes, in 5 to 8 working days.", "label": "pass"}
```

| field | meaning |
|---|---|
| `schema_version` | the format version: `2` now. A line without one is version 1, which has the same fields minus `metadata`, `rule`, `trajectory`, `outcome` and `app_version` |
| `target_id` | the item. Missing: derived from `input` and `output` (and `trajectory`, when there is one) as in `check`, and the report says so |
| `name` | the judge, metric or criterion (default `judge`); choose one with `--metric` |
| `annotator_kind` | `LLM` (a judge verdict), `HUMAN` (a label) or `CODE` (ignored). Case-insensitive; `LLM_JUDGE` reads as `LLM`. Default `LLM` |
| `label` | the verdict or label: `pass`/`fail`, `true`/`false`, a bool, or anything `--label-map` maps |
| `score` | a number; read as the verdict with `--pass-if`, or when `label` is empty |
| `explanation` | the judge's rationale |
| `run` | repeat index, or empty. Without one, each file is one run (see `--runs-by-order`) |
| `input`, `output` | the item's text (or any JSON) |
| `evaluator` | the judge's identity: `{provider, model, prompt, temperature, version, rule}`; `version` is the rubric version, `prompt` is hashed. `rule` is the judge's rule in words (GEval criteria and steps, an llm-rubric value): `start` shows it as "Your judge's rule", and it is hashed into the prompt hash when there is no `prompt` or `prompt_hash`. Also `prompt_hash`, `snapshot` and `endpoint` |
| `created_at` | when the verdict was made |
| `metadata` | an open object for anything else: a criterion name, a run id, an A/B version. Kept; never part of the judge's identity |
| `trajectory` | for agents: the steps that led to the output, as OpenAI-style messages (`role`, `content`, `tool_calls` with `id`, `name` and `arguments`, `tool_call_id`). Kept in the frozen anchor set, because hosted traces expire; not shown on any page yet |
| `outcome` | for agents: an automatic check of the result, `{passed, score, source, detail}`, e.g. `{"passed": true, "source": "unit tests"}` |
| `app_version` | the version of the app or agent that gave the answer. When `start` re-checks and it changed, it says so, as it does for a changed judge |

Fields judgekeeper does not know are kept, at the top level and inside `evaluator`; a file of a newer version is read as far as this version understands it, with one warning. A line over 1 MB is kept, with a warning. The rules are published as a JSON Schema (draft 2020-12): [records.schema.json](records.schema.json), also inside the package as `judgekeeper/schemas/records.schema.json`. Example files: [minimal.jsonl](examples/records/minimal.jsonl) (four fields per line), [full.jsonl](examples/records/full.jsonl) (every field) and [with-human-labels.jsonl](examples/records/with-human-labels.jsonl).

HUMAN records label the metric they are named after, or any metric when their name is not a judge metric in the file (promptfoo's ratings are named `human`).

```
judgekeeper import records records.jsonl --check
judgekeeper import records records.jsonl --out reports/x/
judgekeeper import records export.csv --map "target_id=trace_id,name=metric,label=value,explanation=comment,annotator_kind=source" --out reports/x/
```

`import records --check` writes nothing. For each file it prints the number of records and the format version, the pass/fail split per judge (with the `--pass-if` and `--label-map` you give) and, for each judge, the pass mark used, the judge's model and how many unique ids, the human labels, the first 3 records in plain words (each with its id), the fields it kept without knowing them, and every problem with its line number. Exit 0 when the file is usable (no problems, and at least one judge verdict reads as pass or fail), 2 when not. Given several files (a folder), it ends with how `judgekeeper start` reads them: the files of the same judge together, as one set, where an answer saved in more than one file counts once, with the verdict from the newest file. An import stops at the first problem, with its line number.

`import records` reads JSONL, CSV or TSV. `--map` takes `field=column` pairs; evaluator fields are `evaluator.model=judge_model` and so on (a CSV can also have `evaluator.model` columns, or an `evaluator` column holding JSON; `metadata`, `trajectory` and `outcome` cells hold JSON too). A mapped column that does not exist is a usage error listing the columns.

## record(): save your own judge's verdicts with one line

When your judge runs in your own code and saves nothing judgekeeper reads, add one line right after it gives each verdict, in your eval code:

```python
import judgekeeper
judgekeeper.record(input=question, output=answer, score=0.82, pass_mark=0.5,
                   reason=reason, judge="claude-opus-5", rule=criteria, name="Safe wording")
```

Then run your eval once and `judgekeeper start`: it finds the records. Install judgekeeper inside your project's environment, as for `start`.

| Argument | What |
|---|---|
| `input`, `output` | The question and the answer the judge looked at: text or any JSON value (anything else is written as text) |
| `verdict` | `pass` or `fail`, or `True` or `False` |
| `score`, `pass_mark` | Instead of `verdict`: a number, and the mark it must reach to pass (pass when `score >= pass_mark`). The pass mark is kept in `metadata`. A score with no pass mark is kept without a verdict (then `start --pass-if` reads it) |
| `reason` | The judge's reason |
| `judge` | The judge's model, e.g. `claude-opus-5` |
| `rule` | The judge's rule or criteria, shown as "Your judge's rule" |
| `name` | Which judge or criterion (default `judge`); with several names, `start` asks which to check |
| `temperature`, `id`, `metadata` | The judge's temperature, the answer's id (else one is made from the input and output), and a dict of anything else |

Each call writes one line in the [records format](#records-format-import-records) (version 2, `annotator_kind` `LLM`) to `.judgekeeper/records/<name>-<date>-<process id>.jsonl` under your project root: the nearest folder upward from where your eval runs that has `judgekeeper.toml`, `pyproject.toml`, `setup.py`, `.git` or a `requirements*.txt` (never your home folder), else the current folder. One file per process, so evals that run in several processes never write to the same file. `judgekeeper start` reads the files of the same judge together, as one set: an answer saved in more than one file (a second run, or the same day again) counts once, with the verdict from the newest file. Each line is written whole and the file closed at once; a lock keeps threads' lines apart.

It never breaks your program: any error inside it is caught, it logs one warning to the `judgekeeper` logger (once per process) and returns nothing. It uses only Python's standard library, and `import judgekeeper` loads nothing else until you call it. The file holds your inputs and outputs: use it in your eval code, not in code that serves real users. `JUDGEKEEPER_RECORD=0` (or `false`, `off`, `no`) turns it off.

**Without the import, or in another language.** Copy one of these into your eval code. The Python function, `jk_record`, takes the same arguments as `judgekeeper.record()` and writes the same lines, with nothing to install; the TypeScript one does the same for Node.js (`jkRecord(input, output, { score, pass_mark, ... })`, the same names in its options). Run them from your project folder: unlike `record()`, they do not look upward for the project root.

```python
# Saves each judge verdict for judgekeeper; run it from your project folder. Standard library only.
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
// Saves each judge verdict for judgekeeper; run it from your project folder. Node.js only.
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

**Let your coding agent add the line.** judgekeeper never edits your code. [A prompt for Claude Code, Cursor or Codex](assistant.md#add-the-record-line) asks it to find where your judge gives each score or verdict, add one `judgekeeper.record(...)` call right after it, touch nothing else, show you the diff and wait for your yes, then run the eval once and `judgekeeper import records .judgekeeper/records --check`.

## Unknown judge fields

Every fingerprint field except `created_at` may be unknown: provider, model, snapshot, prompt hash, rubric version and temperature are `null`, and an unknown endpoint is the string `"unknown"` (because `endpoint: null` already means the provider's default endpoint). Reports show such fields as "unknown" and flag "judge identity incomplete: <fields>". Files from earlier versions still load: a missing field reads as unknown, except a missing `endpoint`, which reads as the provider default.

`gate` compares the baseline and the report field by field. A field known on both sides that differs is `JUDGE_CHANGED`, as always. A field unknown on either side adds a warning and does not block, unless `--require-fingerprint` is passed, in which case the status is `JUDGE_CHANGED` with the reason "cannot prove same judge". The default is to warn because imported data rarely carries temperature or snapshot, and blocking on that would make the gate unusable for it; pass `--require-fingerprint` once your judge records its full identity.

## Your API keys

- judgekeeper has no server. Your key stays in your environment, and requests go from your machine (or your CI runner) straight to the provider or the endpoint you name.
- Nothing judgekeeper writes contains a key: judgment files, reports, gate and migration files are all scrubbed. Before any text reaches disk or your terminal, the value of `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `MLFLOW_TRACKING_PASSWORD`, the variable named with `--api-key-env` and any variable ending in `_API_KEY`, `_TOKEN` or `_SECRET` (`DATABRICKS_TOKEN`, `MLFLOW_TRACKING_TOKEN`) is replaced with `[REDACTED]`, as is anything shaped like a provider key (`sk-ant-…`, `sk-…`, `Bearer …`, `Basic …`) and the `user:password@` part of a URL.
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

Thresholds live in an optional `judgekeeper.toml` (`--config`, default `./judgekeeper.toml` when it exists), one table per command: `[gate]` here, `[migrate]` below, and `[start]`, which [`setup`](#setup-set-a-project-up-in-one-step) writes. Unknown tables and keys are a usage error.

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

## Exit codes

| exit code | meaning | commands |
|---|---|---|
| 0 | success; `PASS`; `migrate` finished | all |
| 1 | `FAIL`; a judge call failed, or the judge failed on every item; `migrate --fail-on` matched; a Langfuse request failed | `gate`, `judge`, `migrate`, `import langfuse` |
| 2 | usage error (bad arguments, report, baseline or config; unmapped verdicts or labels; duplicate ids; several metrics without `--metric`; more than 1,000 judge calls without `--yes`; a missing extra or platform key; a Langfuse import with no time window or `--max-items`; an input file that is not UTF-8 text; an output location that cannot be written) | all |
| 3 | anchor set changed: hash mismatch, `ANCHORS_CHANGED`, runs or reports from a different anchor set | all that read anchors or reports |
| 4 | `FLAKY` (`--flaky-as` maps it to 0 or 1) | `gate` |
| 5 | `JUDGE_CHANGED` | `gate` |
| 8 | stopped at a question it cannot ask (no terminal): the line before says the flag or command that answers it; nothing went wrong | `start`, `setup` |
| 130 | stopped with Ctrl-C: it prints "Stopped."; what was saved before stays saved | all |

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
