# judgekeeper reference

Check your LLM-as-a-judge in 5 steps: Find. Mark. Measure. Fix. Re-check. The [README](../README.md) walks through them; this page has every command, flag, file and exit code. How each eval tool's results are read is in [eval-tools.md](eval-tools.md).

An LLM-as-a-judge is a model that grades your eval's answers by a rule you wrote. Each run ends with one `Next:` line that says what to do.

## judgekeeper: find, mark, measure

```
judgekeeper [PATH] [--tool NAME] [--metric NAME] [--experiment NAME_OR_ID]
            [--tracking-uri URI] [--pass-if RULE] [--label-map MAP] [--judge-model NAME]
            [--fields LIST] [--yes] [--port PORT] [--no-browser] [--new | --wait | --stop]
            [--version] [--debug]
```

Each run does the next step. A result needs at least 15 answers you mark Pass and 15 you mark Fail. If almost every answer passes, that can take many answers.

| What is there | What `judgekeeper` does |
|---|---|
| Nothing marked yet | Find: names your eval tool, the answers, your LLM-as-a-judge and its rule, and checks its grades with no AI call. Mark: opens the marking page. |
| Not enough marks yet | Opens the marking page again. |
| Every answer marked, too few of one kind | Says so (a result needs 15 of each). Run your eval on more questions, then `judgekeeper mark`. |
| Enough marks of each kind | Measure: how often your LLM-as-a-judge agrees with you, saved as `.judgekeeper/report.html`. |
| Marks for another LLM-as-a-judge or eval tool | Asks before it starts over. |
| Something to choose, and no terminal | Prints the flag that answers and exits 3. |

New answers from the same LLM-as-a-judge join as a new batch. Every command uses the nearest `.judgekeeper/` that holds your marks, up to the project folder (the one with `pyproject.toml`, `package.json`, `.git`, `setup.py` or `judgekeeper.toml`). judgekeeper can read results from promptfoo, DeepEval, Inspect AI, MLflow, or a CSV or JSONL file ([What it reads](#what-it-reads)).

| Flag | What it does |
|---|---|
| `PATH` | Your project folder (default: this folder), one results file, or an MLflow store (`mlflow.db` or an `mlruns/` folder). Later runs remember a file you name |
| `--tool NAME` | Which eval tool's results to read when several are found: `records`, `promptfoo`, `deepeval`, `inspect`, `mlflow` or `table` |
| `--metric NAME` | The LLM-as-a-judge to look at when the results hold several |
| `--experiment NAME_OR_ID` | MLflow: the experiment to read, when several have LLM-as-a-judge results |
| `--tracking-uri URI` | MLflow: the local store to read (`mlflow.db`, `sqlite:///...`, an `mlruns/` folder or `file:...`) |
| `--pass-if RULE` | When your LLM-as-a-judge's grades are scores: which pass, e.g. `'score>=0.5'` |
| `--label-map MAP` | More spellings of your LLM-as-a-judge's grades, e.g. `'good=pass,bad=fail'` (added to pass/fail, true/false, yes/no, correct/incorrect, right/wrong, 1/0); `=error` for a value that is no decision |
| `--judge-model NAME` | The LLM-as-a-judge's model, when the results do not record it |
| `--fields LIST` | A DeepEval GEval LLM-as-a-judge: the parts it reads, e.g. `input,actual_output` |
| `--yes` | Without a terminal: yes to the questions judgekeeper printed. Never to a choice of tool, LLM-as-a-judge or pass mark |
| `--port PORT` | Port on 127.0.0.1 for the page (default 8765). `0` means any open port |
| `--no-browser` | Print the page's link without opening a browser |
| `--new` | Start over: your marks move to `.judgekeeper/previous-<date>/` (asked first; nothing is deleted) |
| `--wait` | Serve the page in this terminal until Ctrl-C, instead of in the background |
| `--stop` | Close the open page |
| `--version` | Show the version and exit |
| `--debug` | On an unexpected error, also print where it went wrong (files, lines and the error's type, never its text) |

**The marking page** shows one answer at a time, with your LLM-as-a-judge's grade hidden. Above the answer is the metric's name, and "Show the rule" shows your LLM-as-a-judge's rule when your results hold one. Mark each Pass or Fail, as you want your LLM-as-a-judge to decide: `←` Fail, `→` Pass, `S` skip, `Z` undo. Every click is saved at once. "See your result" appears once there are enough marks of each kind. The page stops after 30 minutes with no use.

The page runs on 127.0.0.1 with a random token in its link. The page accepts marks only from itself, so another website can't send marks. A program on your computer could, the same way it could edit your files. The page does not listen on the network. It checks the Host header and the token before reading a request's body, and every change needs the page's own `Origin` (and `Sec-Fetch-Site`, when sent). It takes 32 connections at most, each sending within 5 seconds. Without the token, a request gets only the icon and the project folder's name (`GET /project`). While the page is open, its token is in `.judgekeeper/server.json`, so a second run can print the same link after checking the page is judgekeeper's, for this project. Marks made through the program in `BROWSER`, or from a link printed with no terminal, are stamped so, and the result counts them.

On your result page, say why you disagree on an answer. `fix` counts your reasons and suggests rule lines in `.judgekeeper/fix/suggestions.md`.

## mark: mark more answers

```
judgekeeper mark [PATH] [--tool NAME] [--metric NAME] [--experiment NAME_OR_ID]
                 [--tracking-uri URI] [--pass-if RULE] [--label-map MAP] [--judge-model NAME]
                 [--fields LIST] [--yes] [--port PORT] [--no-browser] [--new | --wait | --stop]
```

Opens the marking page again. It takes the same flags as `judgekeeper`, without `--version` and `--debug`. When every answer is marked, it opens your result page if you and your LLM-as-a-judge disagree on some.

## fix: see where your LLM-as-a-judge goes wrong, then test a better rule

```
judgekeeper fix [PATH] [--yes] [--new]
```

| What is there | What `judgekeeper fix` does |
|---|---|
| No rule in `.judgekeeper/fix/rule.txt` | Keeps some marks aside, and writes where your LLM-as-a-judge goes wrong on the others in `fix/mistakes.md`. With scores, it also tests the best pass mark, with the saved scores, with no AI call. |
| A new rule in `rule.txt` | Asks before the AI calls, then tests old and new rule on the marks kept aside. A rule already tested shows its saved result. |
| A rule judgekeeper can't swap in (a table, `record()`, your own format, a rule per test) | Lists every mistake. Change the rule in your eval, run it, then `judgekeeper check`. |

| Flag | What it does |
|---|---|
| `PATH` | Your project folder (default: this folder) |
| `--yes` | Without a terminal: go ahead and test the new rule (it makes AI calls, paid with your own key) |
| `--new` | Keep a new set of your marks aside to test rules on |

**Marks kept aside:** about 30% of each group, at least 5 Pass and 5 Fail. Only `fix/split.json` names them, so a new rule is never written from them. **`mistakes.md`** holds the clues (your reasons, which way the mistakes go, words found in many), the rule, and each mistake with both reasons. Write a better rule from it, or hand it to a coding agent.

**A new rule** that is empty, over 64 KB, or drops or adds a template part is refused. judgekeeper swaps it in only for its own test, for promptfoo, DeepEval, Inspect AI and MLflow ([what it swaps](eval-tools.md)), and never changes your files. On the marks kept aside, it counts the answers the new rule fixed and those it broke:

| Result | When |
|---|---|
| Better / Worse | The exact two-sided sign test on fixed against broke, at 5% |
| Safe to try | Else, a non-inferiority test (Tango's score test for paired proportions, one-sided 2.5%) rules out the new rule being more than 10 points worse |
| Can't tell yet | Else. It says whether it leans toward better, looks the same, or leans toward worse (keep the old rule) |

Each extra test on the same marks is stricter (the levels divided by the number of tests), so trying rule after rule can't turn a coincidence into "better". After 3 rules, 10 new marks become a new set kept aside. Each rule tested is saved in `rules/`.

## check: re-check your LLM-as-a-judge after a change

```
judgekeeper check [PATH] [--yes]
```

Run it after you change your LLM-as-a-judge or eval tool and run your eval again. It notices a new model, rule, grading prompt, pass mark or temperature, a panel's voting rule, an agent's settings, the eval tool's version, and the endpoint when the results record one. It can't compare two different eval tools. Changed answers don't count: your marks are tests for the LLM-as-a-judge.

| Flag | What it does |
|---|---|
| `PATH` | Your project folder (default: this folder) |
| `--yes` | Without a terminal: go ahead and ask your LLM-as-a-judge (it makes AI calls, paid with your own key) |

**Before any AI call.** First, with no AI call: answers you marked whose exact text is in your newest results already have the new grade. For the rest it asks your LLM-as-a-judge through your eval tool and key, after saying how many AI calls that is.

**How it decides.** It asks about each answer twice, to see how often your LLM-as-a-judge changes its own grade, and checks the answers you passed and failed as two groups. "Worse": the whole range of the change is a drop. "No big drop": the low end is above a 20-point drop. "Not sure": anything else. Coincidence alone can flag a small drop in one group, so mark more answers before acting on one. Unless it is "Worse" (or "Not sure" with a drop over 20 points), your marks now test the new LLM-as-a-judge. Going back to the old one needs no AI call.

## How the numbers are worked out

**What it checks first, with no AI call.** Before you mark anything, it looks at the LLM-as-a-judge's own grades. Each finding is a line starting with "Checked:", and none stops it. The answers found are in `judge-check.csv` ([signs per tool](eval-tools.md#how-failed-calls-are-spotted)).

- **No real decision:** the call failed, its reply could not be read, or the grade is blank. Left out (promptfoo and DeepEval count these as fails).
- **Checked nothing:** a DeepEval metric with nothing to check scored 1.0. Left out.
- **Passed an empty answer:** kept, for you to mark.
- **The same grade for every answer.**
- **The reason says the opposite** of the grade.

**Which answers you mark:** every answer in the newest results with a clear Pass or Fail, counted once, in blocks of 5 your LLM-as-a-judge passed and 5 it failed. **Batches:** new answers join as the next batch, offered first. A batch counts once each of its groups has 5 marks.

**The result** has three numbers: **TPR** (of the answers you passed, how many your LLM-as-a-judge passed), **TNR** (of the answers you failed, how many it failed) and **the real pass rate** of your answers. Each is weighted back by group size, since the page shows more of the LLM-as-a-judge's fails than your results hold. Each has a range, the middle 96% of draws from your marks, a level chosen by a [coverage check](examples/coverage/coverage.md) and checked on [public data](examples/real-data-check/report.md). Kappa (Cohen's kappa) is how much you agree beyond what your mix of Pass and Fail alone would give; it moves with that mix, so it is only in the report's More details and never decides the result.

**The formulas.** The pool holds N_pass answers your LLM-as-a-judge passed and N_fail it failed; pi = N_pass / (N_pass + N_fail). Of the n_p answers you marked in its pass group, c_p are Correct, so a = c_p / n_p. In its fail group, b = c_f / n_f. Skipped answers don't count.

```
TPR             = pi a / (pi a + (1 - pi) b)
TNR             = (1 - pi)(1 - b) / ((1 - pi)(1 - b) + pi (1 - a))
real pass rate  = pi a + (1 - pi) b          (your LLM-as-a-judge's own is pi)
```

This is the Begg-Greenes correction; kappa uses the same weighted table. For the ranges, each group's share Correct is drawn 20,000 times from Beta(c + 0.5, n - c + 0.5) with a fixed seed. A group with no marks makes a number that needs it unknown, never an error.

- **Batches:** the groups become (batch, grade) strata, each marked answer weighs N_s / n_s, and the draws are per stratum.
- **After asking again:** TPR and TNR use the fresh grades, with the shares passed or failed again drawn from Beta(k, m - k), or Beta(k + 0.5, m - k + 0.5) when none or all agree.
- **Wobble:** when an answer gets two grades, the share that turned is drawn from Beta(turned + 0.5 + s e, same + 0.5 + s (1 - e)), e = (1 - sqrt(1 - 2 w)) / 2, w the share with two grades, s = max(0, 5 - m), m the answers counted; only the ranges widen.
- **Steadiness** (the share whose fresh grades differ) is weighted like the real pass rate, with Wilson ranges at 97.5% per group.

**What it says.** One result line, from the ranges:

- "Your LLM-as-a-judge is good enough to use." when the low end of both ranges is at least 80%;
- "Your LLM-as-a-judge needs work." when a range stays below 80%;
- "Too early to tell. Mark more answers to get a result." otherwise.

## What it reads

It looks only inside your project folder, four folders deep; a results file outside it is read only when you name it. Your eval tool's files are never changed. It finds:

- promptfoo by `promptfooconfig.yaml`, `.yml` or `.json`, and reads its JSON results files;
- DeepEval by `.deepeval/` or `deepeval` in your dependencies, and reads `test_run_*.json`, else `.deepeval/.latest_run_full.json`;
- Inspect AI by `logs/` or `inspect-ai` in your dependencies, and reads `.json` logs, and `.eval` logs with the `inspect` extra;
- MLflow's local store, `mlruns/` or `mlflow.db`, with the `mlflow` extra;
- A CSV, TSV or JSONL file at most two folders deep, with `input`, `output` and `verdict` columns;
- the lines `judgekeeper.record()` saved in `.judgekeeper/records/`.

## How grades are read

Every grade, and every mark, becomes `pass`, `fail` or `error`, plus a reason.

- **True or false:** `True` is pass.
- **Words**, in any case: `pass`/`fail`, `true`/`false`, `yes`/`no`, `correct`/`incorrect`, `right`/`wrong`, `1`/`0`, and a leading `PASS` or `FAIL`. `error`, `N/A`, `null`, `none` and `nan` are no decision. Add your own with `--label-map`.
- **Scores** need a `--pass-if` rule: `score>=0.5`, or `>`, `<=`, `<`, `==`. For a dict, the name before the sign is the key (`relevance>=3`).
- **A pair** `(grade, reason)`, or **a dict** with the grade under `verdict`, `pass`, `passed`, `label` or `score` and the reason under `reason`, `rationale`, `explanation` or `comment`.

judgekeeper never guesses: an unknown grade (`good`), or a score with no rule, stops it (exit 3). A call that raised, returned nothing, or returned something unreadable is `error`, never fail, and errors are left out of every number.

## Records format

judgekeeper's own format: one judged answer per JSONL line, written by you or by [`record()`](#record-save-your-own-llm-as-a-judges-verdicts-with-one-line). Every `.jsonl` file in `.judgekeeper/records/` is read this way, and any other whose lines hold `annotator_kind` or `schema_version`. Field names follow OpenInference annotations. Every field is optional:

```
{"name": "Safe wording", "input": "Do you ship to Canada?", "output": "Yes, in 5 to 8 working days.", "label": "pass"}
```

| field | meaning |
|---|---|
| `schema_version` | `2` now. Without it, version 1 (no `metadata`, `rule`, `trajectory`, `outcome`, `app_version`) |
| `target_id` | the answer's id; else made from `input` and `output` (and `trajectory`) |
| `name` | the LLM-as-a-judge or criterion (default `judge`) |
| `annotator_kind` | `LLM` (a grade, the default; `LLM_JUDGE` too), `HUMAN` (a label) or `CODE` (ignored) |
| `label` | the grade, as in [How grades are read](#how-grades-are-read) |
| `score` | a number; the grade with `--pass-if`, or when `label` is empty |
| `explanation` | the LLM-as-a-judge's reason |
| `run` | repeat index, or empty |
| `input`, `output` | the question and answer (text or any JSON) |
| `evaluator` | the fingerprint: `provider`, `model`, `prompt` (hashed), `temperature`, `version` (rubric), `rule`, `prompt_hash`, `snapshot`, `endpoint` |
| `created_at` | when the grade was made |
| `metadata` | anything else; never part of the fingerprint |
| `trajectory` | for agents: the steps to the output, as OpenAI-style messages |
| `outcome` | for agents: an automatic check, e.g. `{"passed": true, "source": "unit tests"}` |
| `app_version` | the version of the program or agent that answered |

An unknown fingerprint part is `null`, except an unknown endpoint: `"unknown"` (`null` is the provider's default). Unknown fields are kept. The JSON Schema is [records.schema.json](../src/judgekeeper/schemas/records.schema.json), also in the package. Examples: [minimal.jsonl](examples/records/minimal.jsonl), [full.jsonl](examples/records/full.jsonl), [with-human-labels.jsonl](examples/records/with-human-labels.jsonl).

## record(): save your own LLM-as-a-judge's verdicts with one line

When your LLM-as-a-judge runs in your own code, install judgekeeper in your project's environment and add one line after each grade. Run your eval once, then `judgekeeper`:

```python
import judgekeeper
judgekeeper.record(input=question, output=answer, score=0.82, pass_mark=0.5,
                   reason=reason, judge="claude-opus-5", rule=criteria, name="Safe wording")
```

| Argument | What |
|---|---|
| `input`, `output` | The question and the answer the LLM-as-a-judge looked at: text or any JSON value |
| `verdict` | `pass` or `fail`, or `True` or `False` |
| `score`, `pass_mark` | Instead of `verdict`: it passes when `score >= pass_mark`. A score with no pass mark waits for `--pass-if` |
| `reason` | The LLM-as-a-judge's reason |
| `judge` | The LLM-as-a-judge's model |
| `rule` | The LLM-as-a-judge's rule, for `fix`; the marking page hides it |
| `name` | Which LLM-as-a-judge or criterion (default `judge`) |
| `temperature`, `id`, `metadata` | The temperature, the answer's id (else one is made), and a dict of anything else |

Each call adds a line to `.judgekeeper/records/<name>-<date>-<process id>.jsonl` in your project root (the nearest folder up with `judgekeeper.toml`, `pyproject.toml`, `setup.py`, `.git` or `requirements*.txt`, never your home folder). An answer saved twice counts once, with the newest grade. Errors inside it are logged to the `judgekeeper` logger, never raised. The file holds your inputs and outputs, so use it in eval code, not in code that serves users. `JUDGEKEEPER_RECORD=0` turns it off.

Without the import, or in another language, copy [jk_record.py](examples/records/jk_record.py) (Python) or [jk_record.ts](examples/records/jk_record.ts) (Node.js) into your eval code. They take the same arguments; run them from your project folder.

## The .judgekeeper/ folder

judgekeeper writes only inside `.judgekeeper/`, plus `judgekeeper.toml` after you say yes, and two temporary files next to your promptfoo config while it asks a promptfoo LLM-as-a-judge again. It never changes other tools' settings: no editor or agent hooks, no git hooks, no `.pre-commit-config.yaml`, no requirements files, no `.gitignore` but its own. The folder holds your answers' text, so commit it only if your data may live in your repository.

- On macOS and Linux, only your user can read its files (0600) and folders (0700). Each file is written whole, replacing the old one.
- It does not write through links: if `.judgekeeper/` or anything in it is a symlink (a cloned repository can hold one) or a hard link, it stops before writing and says which.
- Text from results files is cleaned of keys before it is written. Pages escape every value, spreadsheets stop cells from running as formulas (the id column too), and the terminal gets no control or invisible characters (bidirectional controls, zero-width and tag characters). Pages drop the same characters but keep the two zero-width joiners (U+200C, U+200D), which joined emoji and scripts such as Hindi and Persian need. A key split by one is still replaced.
- `mistakes.md` and `suggestions.md` start with a warning that what follows is data, with your notes and the answers fenced below it.
- A `judgekeeper.toml` that names a results file outside the project is refused.

| File | What it holds |
|---|---|
| `.gitignore` | `*`, `!.gitignore`, `!judge.json`, `!history.jsonl`: your answers stay off Git. Never overwritten |
| `judge.json` | Your LLM-as-a-judge's setup: eval tool and version, models, rule, prompt, temperature, pass mark, endpoint |
| `judge-check.json`, `judge-check.csv` | What the first check found, with each answer and its problem |
| `start.json` | The results files, the LLM-as-a-judge's fingerprint, counts, the seed, the answers' order and batches |
| `pool.jsonl` | Each answer to mark: id, input, output, batch |
| `pool-judge.jsonl` | Your LLM-as-a-judge's grade on every answer, with the fingerprint |
| `marks.jsonl` | One line per click (id, mark, time; no answer text), and your reasons |
| `reasons.json` | Your own reason buttons (at most 8) |
| `server.json`, `page.json` | The open page: port, process, token, and a secret that only closes it. Removed when it stops |
| `page.log` | What the page wrote in the background |
| `opening` | Empty: a run is opening the page |
| `result.json`, `report.html` | The result: every number, your counts, the fingerprint and the date |
| `history/` | Earlier results |
| `history.jsonl` | One line per result, fix test and check: counts and numbers, no answer text |
| `anchors.jsonl`, `anchors.manifest.json` | The answers you marked, as a fixed set with its sha256 |
| `fix/split.json` | Which marks are kept aside, the seed, and every test on them |
| `fix/mistakes.md` | The clues, the rule, and each mistake on the marks you can see |
| `fix/suggestions.md` | Rule lines suggested from your reasons |
| `fix/rule.txt` | Your new rule |
| `fix/runs/` | The grades from each rule test, with the fingerprint |
| `rules/` | Each rule tested, as `<hash>.txt` |
| `results-seen.json` | The setup last read, so a check with nothing new reads nothing again |
| `checks/` | Each check's grades, with the fingerprint, and the eval tool's output |
| `verdicts/` | Each setup's grades on your marked answers (ids and grades only) |
| `records/` | What `judgekeeper.record()` saved; `--new` leaves it |
| `previous-<date>/` | Everything here before you started over |

## Your API keys

- Your key is used only by your own eval tool, when it asks your LLM-as-a-judge, from your machine straight to the provider. A key in promptfoo's config `env:` block counts too.
- Finding, marking and the result never run your eval's code, unless you say yes to the export question, which runs the project's promptfoo. They make no AI call and need no key. To ask again, `fix` and `check` run your eval tool ([what runs](eval-tools.md#asking-again)). Before any AI call, judgekeeper says how many calls it makes and asks first (`Go ahead? [y/N]`, Enter is No). Without a terminal, only `--yes` says yes.
- judgekeeper never prints a key or writes one to a file. Before text reaches disk or your terminal, `[REDACTED]` replaces the values of `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `MLFLOW_TRACKING_PASSWORD` and any variable ending in `_API_KEY`, `_TOKEN` or `_SECRET`, when 8 characters or longer, even split by a hidden character.
- It also hides anything shaped like a key: `sk-ant-…`, `sk-…`, `AKIA…`, `ASIA…`, a 40-character secret after `aws_secret_access_key` or next to an AWS key, `ghp_…`, `gho_…`, `ghs_…`, `ghu_…`, `github_pat_…`, `AIza…`, `xoxb-…`, `xoxp-…`, `Bearer …`, `Basic …`, and the `user:password@` part of a URL.
- An unexpected error prints one line, never its own text (it can hold an answer), and exits 2.
- There is no flag that takes a key, and there never will be.

## Exit codes

| exit code | meaning | commands |
|---|---|---|
| 0 | success: the step is done | all |
| 1 | the new LLM-as-a-judge is Worse, or Not sure with a drop bigger than 20 points | `check` |
| 2 | usage error: bad arguments, a file it can't read, a place it can't write, a removed command, an error it didn't expect, or `check` answered by another model (nothing is saved) | all |
| 3 | you are needed: the `Next:` line says what to do. For example: no eval results found, too few of one kind, a rule to change, a grade it doesn't know, or stopped at a question it cannot ask (no terminal) | all |
| 130 | stopped with Ctrl-C: it prints "Stopped." and what was saved stays saved | all |
