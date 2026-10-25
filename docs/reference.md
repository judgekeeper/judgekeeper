# judgekeeper reference

Check your LLM-as-a-judge in 5 steps: Find. Mark. Measure. Fix. Re-check. The [README](../README.md) walks through them. This page has every command, flag, file and exit code.

An LLM-as-a-judge is a model that grades your eval's answers by a rule you wrote. judgekeeper shows how often its grades agree with yours. How it reads each eval tool's results is in [eval-tools.md](eval-tools.md).

`judgekeeper --help` lists the commands, and `judgekeeper <command> --help` lists one command's flags. Each run ends with one `Next:` line that says what to do.

## judgekeeper: find, mark, measure

```
judgekeeper [PATH] [--tool NAME] [--metric NAME] [--experiment NAME_OR_ID]
            [--tracking-uri URI] [--pass-if RULE] [--label-map MAP] [--judge-model NAME]
            [--fields LIST] [--yes] [--port PORT] [--no-browser] [--new | --wait | --stop]
            [--version] [--debug]
```

Each run does the next step.

| What is there | What `judgekeeper` does |
|---|---|
| Nothing marked yet | Find: names your eval tool, the answers, your LLM-as-a-judge and its rule, and checks its grades with no AI call. Mark: opens the marking page. |
| Some marks, not enough yet | Says how many you marked. The marking page stays open, or opens again. |
| Every answer marked, too few of one kind | Says so ("A result needs at least 15 of each.") and opens no page. Next: run your eval on more questions, then `judgekeeper mark`. |
| Enough marks of each kind | Measure: how often your LLM-as-a-judge agrees with you, and where it goes wrong. Saved as `.judgekeeper/report.html`. |
| Marks for another LLM-as-a-judge or eval tool | Says why, and asks before it starts over. |
| Something to choose | Asks at a terminal. Without one, it prints the flag that answers and exits 3. |
| No results found | Names the eval tool it found with no saved results yet, or says what it can read. |

**A new eval run does not start over.** Your marks and the answers you are marking stay in `.judgekeeper/`. New answers from the same LLM-as-a-judge join as a new batch ([below](#how-the-numbers-are-worked-out)). When your LLM-as-a-judge changed, it says what changed, and the `Next:` line becomes `judgekeeper check`.

**Your project folder.** Every command uses the nearest `.judgekeeper/` that holds your marks. It looks from where you run up to the project folder (the one with `pyproject.toml`, `package.json`, `.git`, `setup.py` or `judgekeeper.toml`). A results file given as `PATH` is read where it is, and later runs read it again.

judgekeeper can read results from promptfoo, DeepEval, Inspect AI, MLflow, or a CSV or JSONL file with `input`, `output` and `verdict` columns ([What it reads](#what-it-reads)).

| Flag | What it does |
|---|---|
| `PATH` | Your project folder (default: this folder), one results file, or an MLflow store (`mlflow.db` or an `mlruns/` folder). Later runs remember a file you name |
| `--tool NAME` | Which eval tool's results to read when several are found: `records`, `promptfoo`, `deepeval`, `inspect`, `mlflow` or `table` |
| `--metric NAME` | The LLM-as-a-judge to look at when the results hold several |
| `--experiment NAME_OR_ID` | MLflow: the experiment to read, when several have LLM-as-a-judge results |
| `--tracking-uri URI` | MLflow: the local store to read (`mlflow.db`, `sqlite:///...`, an `mlruns/` folder or `file:...`) |
| `--pass-if RULE` | When your LLM-as-a-judge's grades are scores: which pass, e.g. `'score>=0.5'` |
| `--label-map MAP` | More spellings of your LLM-as-a-judge's grades, e.g. `'good=pass,bad=fail'` (added to pass/fail, true/false, yes/no, correct/incorrect, right/wrong, 1/0); `=error` for a value that is no decision |
| `--judge-model NAME` | The LLM-as-a-judge's model, when the results do not record it. It is kept with your marks. With a file that already names the model, it is refused (exit 2) |
| `--fields LIST` | A DeepEval GEval LLM-as-a-judge: the parts it reads, e.g. `input,actual_output` |
| `--yes` | Without a terminal: yes to the questions judgekeeper printed. It never picks a tool, an LLM-as-a-judge or a pass mark for you |
| `--port PORT` | Port on 127.0.0.1 for the page (default 8765). If 8765 is taken, the next open one. A port you name that is taken stops with a message. `0` means any open port |
| `--no-browser` | Print the page's link without opening a browser. For a remote machine. The link is also printed when no browser opens within 10 seconds |
| `--new` | Start over: your marks move to `.judgekeeper/previous-<date>/` (asked first; nothing is deleted) |
| `--wait` | Serve the page in this terminal until Ctrl-C, instead of in the background |
| `--stop` | Close the open page. Your marks are saved |
| `--version` | Show the version and exit |
| `--debug` | On an unexpected error, also print where it went wrong (files, lines and the error's type, never its text). An error's text can quote an answer |

**The marking page** shows one answer at a time, with your LLM-as-a-judge's grade and rule hidden. Mark each answer Pass or Fail, the way you want your LLM-as-a-judge to decide. Keys: `←` Fail, `→` Pass, `S` skip, `Z` undo. Every click is saved at once. "See your result" appears once there are enough marks of each kind. The page closes with `--stop`, or after half an hour with no use.

The page runs on 127.0.0.1 with a random token in its link. The page accepts marks only from itself, so another website can't send marks. A program on your computer could, the same way it could edit your files.

On your result page, say why you disagree on an answer. Tap a reason or a part of your rule, type your own, or select words in the answer. `fix` counts your reasons and suggests rule lines in `.judgekeeper/fix/suggestions.md`.

## mark: mark more answers

```
judgekeeper mark [PATH] [--tool NAME] [--metric NAME] [--experiment NAME_OR_ID]
                 [--tracking-uri URI] [--pass-if RULE] [--label-map MAP] [--judge-model NAME]
                 [--fields LIST] [--yes] [--port PORT] [--no-browser] [--new | --wait | --stop]
```

Opens the marking page again. Run `judgekeeper` afterwards to see your updated result. It takes the same flags as `judgekeeper`, without `--version` and `--debug`.

When every answer is marked, it opens your result page if you and your LLM-as-a-judge disagree on some, so you can say why. Otherwise it opens no page: run your eval on more questions, then `judgekeeper mark` again.

## fix: see where your LLM-as-a-judge goes wrong, then test a better rule

```
judgekeeper fix [PATH] [--yes] [--new]
```

Each run does the next step.

| What is there | What `judgekeeper fix` does |
|---|---|
| No new rule in `.judgekeeper/fix/rule.txt` | Keeps some marks aside, then shows where your LLM-as-a-judge goes wrong on the others, and writes `.judgekeeper/fix/mistakes.md`. |
| An LLM-as-a-judge with a score and a pass mark | Also tests the pass mark that fits best, with the saved scores, with no AI call. Shown when it is better or safe to try. |
| A new rule in `rule.txt` | Checks the rule, says how many AI calls the test makes, and asks `Go ahead? [y/N]`. Then it tests old and new rule on the marks kept aside. |
| A rule already tested on these marks | Shows that test's saved result. No AI call. |
| A rule judgekeeper can't swap in (a table, `record()`, your own format, a rule per test) | Says "judgekeeper can't ask this LLM-as-a-judge itself." Change the rule in your eval, run it, then `judgekeeper check`. It lists every mistake. |

| Flag | What it does |
|---|---|
| `PATH` | Your project folder (default: this folder) |
| `--yes` | Without a terminal: go ahead and test the new rule (it makes AI calls, paid with your own key) |
| `--new` | Keep a new set of your marks aside to test rules on |

**Marks kept aside.** About 30% of each group of marks: your LLM-as-a-judge's passes and fails, where you agree with it and where not. At least 5 marked Pass and 5 marked Fail. Only `.judgekeeper/fix/split.json` names them, so a new rule is never written from them. They stay the same until `--new`.

**Where it goes wrong.** It looks at the marks you can see. It counts your reasons, which way its mistakes go (Pass where you said Fail, or the other way), and words found in many of them. `mistakes.md` holds these clues, the rule, and each mistake with both reasons. Use it to write a better rule, or hand it to a coding agent. `fix` also says in which file and line the rule is written, when it can tell.

**Testing a new rule.** Write it in `.judgekeeper/fix/rule.txt` and run `fix` again. A rule that is empty, over 64 KB, or drops or adds a template part is refused. judgekeeper swaps the new rule in only for its own test, for promptfoo, DeepEval, Inspect AI and MLflow ([what it swaps](eval-tools.md)). It never changes your files.

**The result.** It counts, on the marks kept aside, the answers the new rule fixed (old rule wrong, new right). It also counts those it broke (old right, new wrong).

| Result | When |
|---|---|
| Better / Worse | The exact two-sided sign test on fixed against broke, at 5% |
| Safe to try | Else, a non-inferiority test (Tango's score test for paired proportions, one-sided 2.5%) rules out the new rule being more than 10 points worse |
| Can't tell yet | Else. It says whether it leans toward better, looks the same, or leans toward worse (keep the old rule) |

Each extra test on the same marks is stricter (the levels divided by the number of tests). So trying rule after rule can't turn a coincidence into "better".

After a "can't tell yet" that leans toward better, it asks once for a few more marks and tests the same rule again. After 3 rules, 10 new marks become a new set kept aside. Each rule tested is saved in `.judgekeeper/rules/`.

## check: re-check your LLM-as-a-judge after a change

```
judgekeeper check [PATH] [--yes]
```

Run it after you change your LLM-as-a-judge or your eval tool, and run your eval again. It compares the LLM-as-a-judge in your newest results with the one you marked with.

| What changed | Noticed |
|---|---|
| The model or models, the rule, the grading prompt, the pass mark, the temperature | Yes |
| A panel of several and its voting rule, an agent's settings, the eval tool's version | Yes |
| The endpoint | Only when the results record one (judgekeeper's records, a table's `endpoint` column) |
| A table's grades on your marked answers | Yes: it says on how many, and re-checks with them (no AI call) |
| A switch to another eval tool | No: it says it can't compare across two eval tools. Run `judgekeeper` to start fresh |
| The answers themselves | No, on purpose: your marks are tests for the LLM-as-a-judge |

| Flag | What it does |
|---|---|
| `PATH` | Your project folder (default: this folder) |
| `--yes` | Without a terminal: go ahead and ask your LLM-as-a-judge (it makes AI calls, paid with your own key) |

**Before any AI call.** First, with no AI call: answers you marked whose exact text is in your newest results already have the new grade. For the rest it asks your own LLM-as-a-judge, through your own eval tool, with your own key. It says how many answers and AI calls that is, and asks `Go ahead? [y/N]` (Enter is No). Without a terminal it needs `--yes`, or it stops before any call (exit 3).

**How it decides.** It asks about each answer twice and compares the first grade. The second shows how often your LLM-as-a-judge changes its own grade, so a small difference can be told apart from that. It checks the answers you passed and the answers you failed as two groups, each on its own.

- "Worse": the whole range of the change is a drop.
- "No big drop": the low end of the range is above a 20-point drop.
- "Not sure": anything else.

Coincidence alone can flag a small drop in one group, so mark more answers before acting on a small one.

**After the check.** If it is not "Worse" (or "Not sure" with a drop over 20 points), your marks now test the new LLM-as-a-judge. If it is, every `check` says so until you go back to the old one or change it again. Going back needs no AI call.

**Exit codes:** 0 for no big drop, a small "not sure", or nothing changed. 1 for worse, or "not sure" with a drop over 20 points. 3 when you are needed. 2 for a usage error, or when an answer came from another model than your new LLM-as-a-judge's (nothing is saved).

## How the numbers are worked out

**What it checks first, with no AI call.** Before you mark anything, `judgekeeper` looks at the LLM-as-a-judge's own grades. It needs no marks and no key. Each finding is one line starting with "Checked:".

- **No real decision:** the call failed, its reply could not be read, or the grade is blank. Left out. promptfoo and DeepEval count these as fails.
- **Checked nothing:** a DeepEval metric with nothing to check scored 1.0. Left out.
- **Passed an empty answer:** kept, as a good one for you to mark.
- **The same grade for every answer.**
- **The reason says the opposite:** the reason starts with PASS or FAIL, or ends with a line like `verdict: fail`, and that is the other grade.

None of these stops it. The answers found are listed in `.judgekeeper/judge-check.csv`. The exact signs per tool are in [eval-tools.md](eval-tools.md).

**Which answers you mark.** Every answer from the newest results with a clear Pass or Fail, counted once (the same input and output; the newest file wins). The page shows them in blocks of 10: 5 your LLM-as-a-judge passed and 5 it failed, so you see both kinds early. Its grades only decide how answers are picked.

**New answers join as batches.** The answers you first mark are batch 1. New answers (by their exact question and answer text) from the same LLM-as-a-judge join as the next batch, offered first. A batch never removes or replaces an answer. A new batch counts toward the result once each of its groups has 5 marks, and the result says when one doesn't yet. Each batch's passes and fails are weighted by their size. On two and three batches, these ranges held the true value at least 93.2 times in 100 in every case. They held it 95.8 on average ([coverage check](examples/coverage/coverage.md), Batches).

**The result.** It gives three numbers:

- **TPR**: of the answers you passed, how many your LLM-as-a-judge passed.
- **TNR**: of the answers you failed, how many it failed.
- **The real pass rate** of your answers.

The page shows more of the LLM-as-a-judge's fails than your results hold, so each number is weighted back by group size.

Each number has a range: the middle 96% of 20,000 draws from your marks (drawn with a fixed seed, so the same marks give the same ranges). The 96% was chosen by a [coverage check](examples/coverage/coverage.md), not assumed. In simulated checks, the TPR, TNR and pass-rate ranges at 96% held the true value at least 93.6 times in 100 in every case of the test grid. They held it 96.2 on average. Ranges at 95% fell to 91.6 in one case.

On real data too, the TPR and TNR ranges were checked on 5 real LLM-as-a-judge setups from 3 public datasets, with 25 + 25 labels. They held the value from all the human labels in 96.0 checks in 100 on average (lowest 94.6, highest 98.4), over 1,000 checks per LLM-as-a-judge ([report](examples/real-data-check/report.md)).

Kappa (Cohen's kappa) is how much you and your LLM-as-a-judge agree beyond what your mix of Pass and Fail alone would give. It moves with how many answers pass, so it is only in the report's More details and never decides the result. The coverage figures above are not about kappa's range.

**The formulas.** The pool holds N_pass answers your LLM-as-a-judge passed and N_fail it failed; pi = N_pass / (N_pass + N_fail). Of the n_p answers you marked in its pass group, c_p are Correct, so a = c_p / n_p. In its fail group, b = c_f / n_f. Skipped answers don't count. Then:

```
TPR             = pi a / (pi a + (1 - pi) b)
TNR             = (1 - pi)(1 - b) / ((1 - pi)(1 - b) + pi (1 - a))
real pass rate  = pi a + (1 - pi) b          (your LLM-as-a-judge's own is pi)
```

This is the Begg-Greenes correction. Kappa is Cohen's kappa on the weighted table: a marked answer in the pass group counts N_pass / n_p, one in the fail group N_fail / n_f. For the ranges, each group's share Correct is drawn from Beta(c + 0.5, n - c + 0.5) with a fixed seed; each draw goes through the formulas above. A group with no marks makes every number that needs it unknown, never an error.

- **Batches.** The groups become strata: (batch, your LLM-as-a-judge's grade). Each marked answer weighs N_s / n_s and the draws are per stratum. With one batch this gives the same numbers to the last digit.
- **After asking again** (`check`, `fix`). The groups stay the saved grades, since that is how the answers were picked. TPR and TNR are worked out on the weighted table of the fresh grades. In each group, the share you marked Correct is drawn as above; of those, the share passed again, and of the Wrong ones the share failed again, are drawn from Beta(k, m - k). When none or all agree, that range draws from Beta(k + 0.5, m - k + 0.5) instead, so it never shrinks to one point.
- **Wobble.** When asking twice gives an answer two grades, a fresh grade may have turned by itself about e = (1 - sqrt(1 - 2 w)) / 2 of the time (w: the share of answers with two grades). The share that turned is then drawn from Beta(turned + 0.5 + s e, same + 0.5 + s (1 - e)), s = max(0, 5 - m), m the answers counted: few marks lean on the wobble, many on themselves. The numbers stay the same; only the ranges widen.
- **Steadiness** (the share of answers whose fresh grades differ) is weighted like the real pass rate, with Wilson ranges at 97.5% per group joined at the corners.

**What it says.** The terminal and the report say the same, in the same order.

1. One result line, from the ranges:
   - "Your LLM-as-a-judge is good enough to use." when the low end of both ranges is at least 80%;
   - "Your LLM-as-a-judge needs work." when a range stays below 80%;
   - "Too early to tell. Mark more answers to get a result." otherwise.
2. How many answers you and your LLM-as-a-judge disagreed on, and plain counts for the answers you passed and the ones you failed.
3. The estimates: "When you say Pass, it also says Pass: about N% (between A% and B%)", and the same for Fail. A range wider than 40 points says "too early to tell". While the result is too early to tell, the terminal shows counts only.
4. The next step: `judgekeeper mark` while it is too early to tell, `judgekeeper fix` when it needs work, nothing when it is good enough.

The report also lists the answers where you disagree, with your LLM-as-a-judge's own reason. Marks kept aside for `fix` are counted, not shown.

## What it reads

It looks for results only inside your project folder, four folders deep. A results file outside it is read only when you name it. It skips `.git`, `node_modules`, virtual environments and hidden folders (except `.deepeval` and `.judgekeeper/records/`). It stops after 5,000 files or 2 seconds. Your eval tool's files are only read, never changed.

| Tool | How it is found | What is read |
|---|---|---|
| promptfoo | `promptfooconfig.yaml`, `.yml` or `.json` | JSON results files |
| DeepEval | `.deepeval/`, or `deepeval` in `pyproject.toml` or `requirements*.txt` | `test_run_*.json`, else `.deepeval/.latest_run_full.json` |
| Inspect AI | `logs/`, or `inspect-ai` in the dependencies | `.json` logs, and `.eval` logs with the `inspect` extra |
| MLflow | `mlruns/` or `mlflow.db` | The local store, with the `mlflow` extra |
| A CSV or JSONL file | A CSV, TSV or JSONL file at most two folders deep (the folder and one below it), with `input`, `output` and `verdict` columns | That file |
| `judgekeeper.record()` | `.judgekeeper/records/*.jsonl` | The lines your eval code saved |

Each tool's details, and results in a format of their own, are in [eval-tools.md](eval-tools.md).

## How grades are read

Every grade from your LLM-as-a-judge, and every mark, becomes `pass`, `fail` or `error`, plus a reason.

- **True or false:** `True` is pass.
- **Words**, in any case: `pass`/`fail`, `true`/`false`, `yes`/`no`, `correct`/`incorrect`, `right`/`wrong`, `1`/`0`, and a leading `PASS` or `FAIL` (`PASS: looks right`). `error`, `N/A`, `null`, `none` and `nan` are no decision. Add your own with `--label-map "good=pass,bad=fail,maybe=error"`.
- **Scores** need a `--pass-if` rule: `score>=0.5`, or `>`, `<=`, `<`, `==`. For a dict, the name before the sign is the key to read (`relevance>=3`). Without a rule, `1` and `0` follow the words above.
- **A pair** `(grade, reason)`.
- **A dict** with the grade under `verdict`, `pass`, `passed`, `label` or `score` (the first found), and the reason under `reason`, `rationale`, `explanation` or `comment`.

judgekeeper never guesses. A value that looks like a grade but isn't known (`good`), or a score with no rule, stops it (exit 3). It lists every such value it saw.

A call that raised, returned nothing, or returned something unreadable is recorded as `error`, never as fail. Errors are left out of every agreement number.

## Records format

judgekeeper's own format: one judged answer per line of a JSONL file. Write these lines yourself, or let [`record()`](#record-save-your-own-llm-as-a-judges-verdicts-with-one-line) write them. Every `.jsonl` file in `.judgekeeper/records/` is read this way. Elsewhere, a `.jsonl` file is read this way when its lines hold `annotator_kind` or `schema_version`. Field names follow OpenInference annotations. Every field is optional. The smallest useful line:

```
{"name": "Safe wording", "input": "Do you ship to Canada?", "output": "Yes, in 5 to 8 working days.", "label": "pass"}
```

| field | meaning |
|---|---|
| `schema_version` | `2` now. A line without one is version 1, which lacks `metadata`, `rule`, `trajectory`, `outcome` and `app_version` |
| `target_id` | the answer's id. Missing: made from `input` and `output` (and `trajectory`) |
| `name` | the LLM-as-a-judge or criterion (default `judge`); pick one with `--metric` |
| `annotator_kind` | `LLM` (a grade), `HUMAN` (a label) or `CODE` (ignored). Default `LLM`; `LLM_JUDGE` reads as `LLM` |
| `label` | the grade: `pass`/`fail`, `true`/`false`, a bool, or anything `--label-map` maps |
| `score` | a number; read as the grade with `--pass-if`, or when `label` is empty |
| `explanation` | the LLM-as-a-judge's reason |
| `run` | repeat index, or empty |
| `input`, `output` | the question and answer (text or any JSON) |
| `evaluator` | the LLM-as-a-judge's fingerprint: `provider`, `model`, `prompt` (hashed), `temperature`, `version` (the rubric version), `rule` (shown as its rule), `prompt_hash`, `snapshot`, `endpoint` |
| `created_at` | when the grade was made |
| `metadata` | anything else: a criterion name, a run id. Kept, never part of the fingerprint |
| `trajectory` | for agents: the steps that led to the output, as OpenAI-style messages. Kept with the answers you marked |
| `outcome` | for agents: an automatic check of the result, e.g. `{"passed": true, "source": "unit tests"}` |
| `app_version` | the version of the program or agent that gave the answer |

A fingerprint is what identifies the LLM-as-a-judge behind a grade: provider, model, snapshot, prompt hash, rubric version, temperature, endpoint and `created_at`. Any of them but `created_at` may be unknown. An unknown one is `null`, except an unknown endpoint, which is `"unknown"` (`null` means the provider's default). Older files still load: a missing field reads as unknown, and a missing `endpoint` as the default.

Unknown fields are kept. The rules are a JSON Schema: [records.schema.json](../src/judgekeeper/schemas/records.schema.json), also in the package as `judgekeeper/schemas/records.schema.json`. Examples: [minimal.jsonl](examples/records/minimal.jsonl), [full.jsonl](examples/records/full.jsonl), [with-human-labels.jsonl](examples/records/with-human-labels.jsonl).

## record(): save your own LLM-as-a-judge's verdicts with one line

When your LLM-as-a-judge runs in your own code, add one line right after it gives each grade:

```python
import judgekeeper
judgekeeper.record(input=question, output=answer, score=0.82, pass_mark=0.5,
                   reason=reason, judge="claude-opus-5", rule=criteria, name="Safe wording")
```

Install judgekeeper in your project's environment (`pip install judgekeeper`). Run your eval once, then `judgekeeper`: it finds the records.

| Argument | What |
|---|---|
| `input`, `output` | The question and the answer the LLM-as-a-judge looked at: text or any JSON value |
| `verdict` | `pass` or `fail`, or `True` or `False` |
| `score`, `pass_mark` | Instead of `verdict`: a number, and the mark it must reach to pass (`score >= pass_mark`). A score with no pass mark is kept without a grade, for `--pass-if` |
| `reason` | The LLM-as-a-judge's reason |
| `judge` | The LLM-as-a-judge's model, e.g. `claude-opus-5` |
| `rule` | The LLM-as-a-judge's rule. `fix` shows it and tests a new one; the marking page hides it |
| `name` | Which LLM-as-a-judge or criterion (default `judge`) |
| `temperature`, `id`, `metadata` | The temperature, the answer's id (else one is made), and a dict of anything else |

Each call writes one line in the [records format](#records-format) to `.judgekeeper/records/<name>-<date>-<process id>.jsonl`. The folder is in your project root: the nearest folder up with `judgekeeper.toml`, `pyproject.toml`, `setup.py`, `.git` or a `requirements*.txt`, never your home folder. Each process writes its own file, so parallel evals never share one. An answer saved in two files counts once, with the grade from the newest file.

It never breaks your program: any error inside it is caught and logged to the `judgekeeper` logger. It uses only Python's standard library. The file holds your inputs and outputs, so use it in eval code, not in code that serves real users. `JUDGEKEEPER_RECORD=0` turns it off.

**Without the import, or in another language.** Copy [jk_record.py](examples/records/jk_record.py) (Python, nothing to install) or [jk_record.ts](examples/records/jk_record.ts) (Node.js) into your eval code. Each takes the same arguments as `record()` and writes the same lines. Run them from your project folder: unlike `record()`, they do not look upward for it.

## The .judgekeeper/ folder

judgekeeper writes only inside `.judgekeeper/` in your project, plus `judgekeeper.toml` when you say yes. While it asks a promptfoo LLM-as-a-judge again, it also writes two temporary files next to your promptfoo config, removed when promptfoo is done.

- On macOS and Linux, only your user can read its files (0600) and folders (0700).
- Every string from a results file is cleaned of keys before it is written.
- Each file is written whole, as a new file that replaces the old one.
- It does not write through links. If `.judgekeeper/` or a file in it is a symlink or a hard link, it stops and says which, before writing anything.
- Your `.gitignore` and your git hooks are never changed. The folder holds your answers' text, so commit it only if your data may live in your repository.

| File | What it holds |
|---|---|
| `.gitignore` | `*`, `!.gitignore`, `!judge.json`, `!history.jsonl`: your answers stay off Git. Written when marking first starts, never overwritten |
| `judge.json` | Your LLM-as-a-judge's setup: eval tool and version, models, rule, grading prompt, temperature, pass mark, endpoint. Rewritten only when the setup changes |
| `judge-check.json`, `judge-check.csv` | What the first check found: the counts, and each answer found with its problem |
| `start.json` | The eval tool, the results files, the LLM-as-a-judge and its fingerprint, the counts, what was left out, the seed, the order of the answers and their batches |
| `pool.jsonl` | Each answer to mark: its id, input, output and batch |
| `pool-judge.jsonl` | Your LLM-as-a-judge's grade on every answer, with the full fingerprint |
| `marks.jsonl` | One line per click (the answer's id, your mark, the time; no answer text), and your reasons |
| `reasons.json` | Your own reasons, as buttons (at most 8) |
| `server.json`, `page.json` | The open page: its port, its process, the token, and a secret that only closes it |
| `page.log` | What the page wrote while it ran in the background |
| `opening` | Empty: a run is opening the page, so a second run waits |
| `result.json`, `report.html` | The result: every number, your counts, the fingerprint and the date. The report opens without a server |
| `history/` | Earlier results |
| `history.jsonl` | One line per result, fix test and check: the counts and numbers, no answer text |
| `anchors.jsonl`, `anchors.manifest.json` | The answers you marked, kept as a fixed set, with a sha256 of the set |
| `fix/split.json` | Which marks are kept aside, the seed, and every test on them |
| `fix/mistakes.md` | The clues, the rule, and each mistake on the marks you can see |
| `fix/suggestions.md` | Rule lines suggested from your reasons |
| `fix/rule.txt` | Your new rule |
| `fix/runs/` | The grades from each rule test, with the full fingerprint |
| `rules/` | Each rule tested, as `<hash>.txt` |
| `results-seen.json` | The setup in the results read last, so a check with nothing new reads nothing again |
| `checks/` | The grades from each check, with the full fingerprint, and the eval tool's own output |
| `verdicts/` | Each setup's grades on your marked answers (ids and grades only) |
| `records/` | The grades `judgekeeper.record()` saved; `--new` leaves them |
| `previous-<date>/` | Everything that was here before you started over |

## Your API keys

- Your key is used only by your own eval tool, when it asks your LLM-as-a-judge. Requests go from your machine straight to the provider.
- Finding, marking and the result never run your eval's code. To ask again, `fix` and `check` run your eval tool, and for DeepEval, Inspect AI and MLflow a small script with your project's Python. [SECURITY.md](../SECURITY.md) says what runs. A key in promptfoo's config `env:` block counts too.
- Finding, marking and the result make no AI call and need no key. Before any AI call, judgekeeper says how many calls it makes and asks first (`Go ahead? [y/N]`, Enter is No). Without a terminal, only `--yes` says yes.
- judgekeeper never prints a key or writes one to a file. Before any text reaches disk or your terminal, key values are replaced with `[REDACTED]`. That covers `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `MLFLOW_TRACKING_PASSWORD`, and any variable ending in `_API_KEY`, `_TOKEN` or `_SECRET`, when the value has 8 characters or more.
- It also hides anything shaped like a key: `sk-ant-…`, `sk-…`, `AKIA…`, `ASIA…`, a 40-character secret after `aws_secret_access_key` or next to an AWS key, `ghp_…`, `gho_…`, `ghs_…`, `ghu_…`, `github_pat_…`, `AIza…`, `xoxb-…`, `xoxp-…`, `Bearer …`, `Basic …`, and the `user:password@` part of a URL.
- Error text is cleaned too. An unexpected error prints one line, never its own text (it can hold an answer), and exits 2.
- There is no flag that takes a key, and there never will be.

## Exit codes

| exit code | meaning | commands |
|---|---|---|
| 0 | success: the step is done | all |
| 1 | the new LLM-as-a-judge is Worse, or Not sure with a drop bigger than 20 points | `check` |
| 2 | usage error: bad arguments, marks or an input file it can't read, a place it can't write, a removed command, an error it didn't expect, or `check` answered by another model | all |
| 3 | you are needed: the `Next:` line says what to do. For example: no eval results found, every answer marked with too few of one kind, a rule to change, a grade it doesn't know, or stopped at a question it cannot ask (no terminal) | all |
| 130 | stopped with Ctrl-C: it prints "Stopped." and what was saved stays saved | all |
