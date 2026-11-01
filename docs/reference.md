# judgekeeper reference

Check your LLM-as-a-judge in 5 steps: Find. Mark. Measure. Fix. Re-check. The [README](../README.md) walks through them; this page has every command, flag, file and exit code. How each eval tool's results are read is in [eval-tools.md](eval-tools.md).

An LLM-as-a-judge is a model that grades your eval's answers by a rule you wrote. Each run ends with one `Next:` line that says what to do.

## Install

In your project folder, in its virtual environment, `pip install judgekeeper`, then `judgekeeper`. Or with [uv](https://docs.astral.sh/uv/), which needs no virtual environment: `uvx judgekeeper`. Python 3.11 to 3.14 is supported. Inspect AI `.eval` logs and MLflow need an extra: `pip install "judgekeeper[inspect]"` or `pip install "judgekeeper[mlflow]"` (with uv: `uvx --from "judgekeeper[mlflow]" judgekeeper`). With uv, type `uvx judgekeeper` wherever these pages say `judgekeeper`.

## judgekeeper: find, mark, measure

```
judgekeeper [PATH] [--tool NAME] [--metric NAME] [--experiment NAME_OR_ID]
            [--tracking-uri URI] [--pass-if RULE] [--label-map MAP] [--labels [FILE]]
            [--judge-model NAME] [--yes] [--port PORT] [--no-browser]
            [--new | --wait | --stop] [--version] [--debug]
```

Each run does the next step. A result needs at least 15 answers you mark Pass and 15 you mark Fail, and 20 marks on answers your LLM-as-a-judge passed and 20 on answers it failed. If your LLM-as-a-judge fails under 10% of the answers, finding 15 answers you mark Fail can take many marks.

| What is there | What `judgekeeper` does |
|---|---|
| Nothing marked yet | Find: names your eval tool, the answers, your LLM-as-a-judge and its rule, and checks its grades with no AI call. Mark: opens the marking page. |
| Not enough marks yet | Opens the marking page again. |
| Every answer marked, too few of one kind | Says so (a result needs 15 of each). Run your eval on more questions, then `judgekeeper mark`. |
| Enough marks of each kind | Measure: how often your LLM-as-a-judge agrees with you, saved as `.judgekeeper/report.html`. |
| Marks for another LLM-as-a-judge or eval tool | Asks before it starts over. |
| Something to choose, and no terminal | Prints the flag that answers and exits 3. |

New answers from the same LLM-as-a-judge join as a new batch. Every command uses the nearest `.judgekeeper/` that holds your marks, up to the project folder (the one with `pyproject.toml`, `package.json`, `.git`, `setup.py` or `judgekeeper.toml`). With none, it starts one in the folder you run it in. Run in a folder with a project right below it where you already ran judgekeeper, it names that project and stops (exit 3) instead of starting a second set of marks there. It stops the same way when results are in two or more folders right below it and none are in it: it names them, and you check one at a time from its own folder (DeepEval and Inspect AI results in several folders are asked about instead). judgekeeper can read results from promptfoo, DeepEval, Inspect AI, MLflow, or a CSV, TSV or JSONL file ([What it reads](#what-it-reads)).

| Flag | What it does |
|---|---|
| `PATH` | Your project folder (default: this folder), one results file, or an MLflow store (`mlflow.db` or an `mlruns/` folder). Later runs remember a file you name |
| `--tool NAME` | Which eval tool's results to read when several are found: `records`, `promptfoo`, `deepeval`, `inspect`, `mlflow` or `table` |
| `--metric NAME` | The LLM-as-a-judge to look at when the results hold several |
| `--experiment NAME_OR_ID` | MLflow: the experiment to read, when several have LLM-as-a-judge results. Kept with your marks: later runs read it without the flag |
| `--tracking-uri URI` | MLflow: the local store to read (`mlflow.db`, `sqlite:///...`, an `mlruns/` folder or `file:...`) |
| `--pass-if RULE` | When your LLM-as-a-judge's grades are scores: which pass, e.g. `'score>=0.5'` |
| `--label-map MAP` | More spellings of your LLM-as-a-judge's grades, e.g. `'good=pass,bad=fail'` (added to pass/fail, true/false, yes/no, correct/incorrect, right/wrong, 1/0); `=error` for a value that is no decision. Kept with your marks: later runs read the same way without it |
| `--labels [FILE]` | Use Pass/Fail labels you already have as your marks: from FILE (CSV, TSV or JSONL with an answer and a label column), or with no FILE the human labels already in your results. See [Bring labels you already have](#bring-labels-you-already-have). Not kept: give it each time you want labels brought in |
| `--judge-model NAME` | The LLM-as-a-judge's model, when the results do not record it. Given after marking started, it is written down with your marks, not a change |
| `--yes` | Without a terminal: yes to the questions judgekeeper printed. Never to a choice of tool, LLM-as-a-judge or pass mark |
| `--port PORT` | Port on 127.0.0.1 for the page (default 8765). `0` means any open port |
| `--no-browser` | Print the page's link without opening a browser |
| `--new` | Start over: your marks move to `.judgekeeper/previous-<date>/` (asked first; nothing is deleted). `history.jsonl`, `verdicts/`, `records/` and `.gitignore` stay where they are |
| `--wait` | Serve the page in this terminal until Ctrl-C, instead of in the background |
| `--stop` | Close the open page |
| `--version` | Show the version and exit. At a terminal it prints "✓ judgekeeper 1.0.0 is ready" and a `Next:` line; piped, only "judgekeeper 1.0.0" |
| `--debug` | On an unexpected error, also print where it went wrong (files, lines and the error's type, never its text) |

**The marking page** shows one answer at a time, with your LLM-as-a-judge's grade hidden. Above the answer is the metric's name (the name of the LLM-as-a-judge in your results; promptfoo: the assertion's `metric:` or its type), and "Show the rule" shows your LLM-as-a-judge's rule when your results hold one. Mark each Pass or Fail, as you want your LLM-as-a-judge to decide: `←` Fail, `→` Pass, `S` skip, `Z` undo. Every click is saved at once. "See your result" appears once there are enough marks of each kind. The page stops after 30 minutes with no use.

The page runs on 127.0.0.1 with a random token in its link. The page accepts marks only from itself, so other websites can't send marks. A program already running on your computer could, just as it can edit your files. The page does not listen on the network. It checks the Host header and the token before reading a request's body, and every change needs the page's own `Origin` (and `Sec-Fetch-Site`, when sent). It takes 32 connections at most, each sending within 5 seconds. Without the token, a request gets only the icon. While the page is open, its token is in `.judgekeeper/server.json`, so a second run uses the same page after checking it is judgekeeper's, for this project. It opens no new tab: at your terminal it prints the link; with no terminal it prints no link and says to run with `--no-browser` to print it. It keeps the open page whatever its `--port` and `--no-browser`; with other flags it starts the page again, and says so (the link stays the same unless you ask for another port). Marks made through the program in `BROWSER`, or from a link printed with no terminal (another program, such as a coding agent, read the output), are stamped so, and the result counts them. A link printed at your terminal is not stamped.

On your result page, say why you disagree on an answer. `fix` counts your reasons and suggests rule lines in `.judgekeeper/fix/suggestions.md`. The parts of your rule are buttons too: at most 6, the first five and the last; for a part with no button, use “Other…”.

## mark: mark more answers

```
judgekeeper mark [PATH] [--tool NAME] [--metric NAME] [--experiment NAME_OR_ID]
                 [--tracking-uri URI] [--pass-if RULE] [--label-map MAP] [--labels [FILE]]
                 [--judge-model NAME] [--yes] [--port PORT] [--no-browser] [--new | --wait | --stop]
```

Opens the marking page again. It takes the same flags as `judgekeeper`, without `--version`. When every answer is marked, it opens your result page if you and your LLM-as-a-judge disagree on some.

After your first 10 marks, about 1 in 20 answers comes back a second time, so judgekeeper can see how often your own marks change. Only your first mark counts. It adds about 5% more marks.

## Bring labels you already have

If you already have Pass/Fail labels, judgekeeper can use them as your marks, so you don't mark those answers again. Then mark more on the page if you need to.

- `judgekeeper --labels your-labels.csv` reads them from a CSV, TSV or JSONL file.
- `judgekeeper --labels` uses the labels people gave that are already in your results: promptfoo `human` ratings, MLflow assessments from a HUMAN source, a `human_label` or `label` column in your results table, and `record()` lines with `annotator_kind` `HUMAN`. Without the flag, judgekeeper says how many it found and never uses them. Scores edited in Inspect AI are not used: Inspect keeps a person's label only when they change a score, so those labels would be mostly disagreements and make your LLM-as-a-judge look worse than it is. Labels for another question (for example a Tone rating when your LLM-as-a-judge checks something else) are not used.

`judgekeeper mark` takes the flag too. Put your project folder first: `judgekeeper evals --labels your-labels.csv`.

**The file's columns** (any case): the answer, `output` or `answer`; the label, `label` or `human_label`; and, if you have them, the question, `input` or `question`, and an `id`. Other columns are ignored. Your results table and the template judgekeeper writes both work. Excel files are not read: save the sheet as CSV first.

**How a label finds its answer:** by `id` when the answer text (if given) is the same too, else by the same answer text, word for word. Line endings, spaces at both ends and a spreadsheet's `'` before `=` don't matter; anything else must be the same (no fuzzy matching). Two answers with the same text and different questions need a question column to tell them apart. A label counts for every repeat of its answer.

**The words** are read like grades ([How grades are read](#how-grades-are-read)), with your `--label-map`. A blank label is skipped. A number (other than 1 or 0), or a word judgekeeper can't read, stops it before anything is written (exit 3).

**What is left out, and said:** a label for an answer not in your results, for one your LLM-as-a-judge didn't grade Pass or Fail, for an answer that matches more than one answer, or for an answer labelled both Pass and Fail. When none match, it stops (exit 3).

**Running it again** adds only what is new. An answer you already marked keeps your mark, from the page or an earlier import; judgekeeper says how many it kept. You can change an imported mark on the page.

**In your result** each imported mark counts like a page mark, and the result says once how many came from where: "{k} of your marks came from {name}. The numbers assume those answers were picked at random and labelled without looking at your LLM-as-a-judge's grade."

Imported marks count toward the numbers. A result of good enough or needs work also needs 15 answers marked on the page among those your LLM-as-a-judge passed and 15 among those it failed, so judgekeeper can check the imported marks against yours.

Once you have 15 page marks among the answers your LLM-as-a-judge passed and 15 among those it failed, judgekeeper compares them with the imported marks in each group. When they differ too much to be a coincidence (Fisher's exact test, p under 0.025 in either group), the result warns that the numbers may be off. It is a warning, never a stop.

## fix: see where your LLM-as-a-judge goes wrong, then test a better rule

```
judgekeeper fix [PATH] [--new]
```

| What is there | What `judgekeeper fix` does |
|---|---|
| No results file given | Keeps half your marks aside, and writes where your LLM-as-a-judge goes wrong on the others in `fix/mistakes.md`. Writes every marked answer in `fix/marked-answers.csv`, says where your rule lives, and prints how to grade the answers again with your eval tool. With scores, it also tests the best pass mark on the saved scores, once, and says so: that counts as one test on the marks kept aside. |
| A results file | Reads it as step 1 reads results, finds the answers kept aside in it, and tests the new grades against the old ones. Results already tested show their saved result. |

| Flag | What it does |
|---|---|
| `PATH` | The results of grading your marked answers again with a new rule (for MLflow, the store: `mlflow.db` or an `mlruns/` folder, read at its newest run), or your project folder (default: this folder) |
| `--new` | Start a new set of marks kept aside, made of the next marks you make: every mark you have made counts as seen, and the marks you make next (at least 10; [about 40 for a clear answer](examples/kept-aside/report.md), as many as `fix` keeps aside from about 80 marks) become the new set. A mark you have seen is never kept aside again |

**Marks kept aside:** half of each group, rounded up, at least 5 Pass and 5 Fail. Only `fix/split.json` names them, so a new rule is never written from them. A `split.json` that is damaged or changed by hand stops `fix` (exit 2); it is never replaced. **`mistakes.md`** holds the clues (your reasons, which way the mistakes go, words found in many), the rule, and each mistake with both reasons. After `check` found a new LLM-as-a-judge worse, the mistakes are that one's, and the file names the results its grades are in. Write a better rule from it, or hand it to a coding agent.

**`marked-answers.csv`** holds every answer you marked, shuffled, with two columns, `question` and `answer`: no marks, no grades and no judgekeeper ids, so the file does not say which are kept aside. Your own question fields (such as a promptfoo `description`) stay as they are, because the regrade matches on them. Change the rule where your eval keeps it, grade these answers again, save the results, then run `judgekeeper fix <new results file>`. judgekeeper prints the line for your eval tool:

| Eval tool | How to grade the same answers again |
|---|---|
| promptfoo | Use `marked-answers.csv` as your tests with the `echo` provider and your new rule; save with `-o`. |
| Inspect AI | `inspect score <log> --scorer <name> --action overwrite --output-file logs/new.eval` with your scorer's new rule grades the log again without new answers. The new grades keep your scorer's name, your log stays as it was, and the new one is in your log folder, where `check` finds it. Then run `judgekeeper fix logs/new.eval`. |
| MLflow | `mlflow.genai.evaluate()` on the existing traces with the new scorer. |
| DeepEval | Build test cases from `marked-answers.csv`, add back by question any field your metric also reads (such as `expected_output`), and run the metric. |
| A CSV, TSV or JSONL file | Grade `marked-answers.csv` with your own code. |
| Your own code, with `record()` | Grade `marked-answers.csv` with your own code, call `judgekeeper.record()` again on the new grades, then run `judgekeeper fix .judgekeeper/records/<new file>`. |
| A format of its own | Grade `marked-answers.csv` with your own code, and save the new grades in the same shape as your results file. |

**The new results** must come from the same eval tool as your marks and hold an LLM-as-a-judge of the same name (its metric or scorer); results from another eval tool, or with no LLM-as-a-judge of that name, stop it (exit 2). Its model and rule may differ, as may the model that gave the answers (promptfoo's `echo` provider, for one): that is the change you test. judgekeeper reads them as step 1 read your results, with the same options. An answer kept aside is found by the same text, word for word, and its question; a row in the results with no question is never an answer you marked with one. If some aren't there, it gives no result: it says how many and asks you to grade the same answers again (exit 3). One there with no decision from the new rule (`error`, empty or `NaN`) counts as its mistake, and it says how many: a rule can't look better by leaving the hard ones ungraded. With more than half of the answers kept aside ungraded, it gives no result and asks you to grade them again (exit 3). This holds for a rule tested before too. Otherwise a rule tested before gets its saved result, with the file and day it came from and how many answers this file leaves ungraded. A grade word it doesn't know stops it, as in step 1 (exit 3). An answer graded twice with different grades counts against your LLM-as-a-judge, and repeats with the same grade count once; it says how many of each. The grades you marked, given again, are not a test: give the results from after your change (exit 3). Nor is a new rule that changes no grade kept aside (exit 3). On the answers kept aside it found, it counts the answers the new rule fixed and those it broke:

| Result | When |
|---|---|
| Better / Worse | The exact two-sided sign test on fixed against broke, at 5% |
| Safe to try | Else, a non-inferiority test (Tango's score test for paired proportions, one-sided 2.5%) rules out the new rule being more than 10 points worse |
| Can't tell yet | Else. It says whether it leans toward better, looks the same, or leans toward worse. Unless it leans toward worse, it also says how many of your LLM-as-a-judge's mistakes are kept aside, and about how many fixed (and none broken) "better" needs |

The fixed and broke counts are weighted to your whole set of answers: the marks kept aside hold more of your LLM-as-a-judge's fails than your results do, so each kept-aside mark counts for its share of its group.

After "Worse", copy your old rule back (`mistakes.md` keeps a copy). After "Better" or "Safe to try", keep the new rule and run `judgekeeper check <new results file>` on the same new results: they grade every answer you marked. Running your eval again would make new answers, which judgekeeper can't compare. Each extra test on the same marks is stricter (the levels divided by the number of tests): "Better" or "Worse" needs the 5% level for the first rule, 2.5% for the second and about 1.7% for the third. So over 3 rules, a coincidence says "Better" or "Worse" at least once in at most about 9 cases in 100 (5 + 2.5 + 1.7), not 5. After 3 rules, or once `check` takes on a rule tested on them (for results without a rule, only after 3 rules), your next marks become a new set kept aside. Mark [about 40 more answers for a clear answer](examples/kept-aside/report.md) (at least 10; with fewer than about 40, the result will often be "can't tell yet"). All of them are kept aside: as many as `fix` keeps aside from about 80 marks. Each rule tested is saved in `rules/`.

**How many marks:** it depends on how big the change is. In a simulation through `fix`'s own split and test ([report](examples/kept-aside/report.md)), a new rule that fixes about a quarter of the mistakes and breaks few right answers gets a clear answer most of the time from about 80 marks, mostly "Safe to try"; one that fixes almost all of them, also from about 80; one that fixes 1 in 10 and breaks 5 in 100 right answers, from about 160. These figures are for the first rule tested on a set; the second and third are tested more strictly, so they need more marks. Calling a rule "Better" or "Worse" by mistake is rare but not zero, and happens only for rules close to no change. A worse rule often reads "Can't tell yet", and now and then "Safe to try" (not more than 10 points worse), so with few marks "Can't tell yet" does not mean the new rule is as good.

## check: re-check your LLM-as-a-judge after a change

```
judgekeeper check [PATH]
```

Run it after you change your LLM-as-a-judge or eval tool and grade the answers you marked again the same way as for `fix` (see [Grading answers again](eval-tools.md#grading-answers-again)). It notices a new model, rule, grading prompt, pass mark or temperature, a panel's voting rule, an agent's settings, the eval tool's version, and the endpoint when the results record one. It can't compare two different eval tools.

| Flag | What it does |
|---|---|
| `PATH` | A new results file or MLflow store (`mlflow.db` or an `mlruns/` folder), or your project folder (default: this folder, with its newest results). A folder is read as step 1 reads it |

**Which results it reads.** It names the file first ("New results: ..."). With a saved choice in `judgekeeper.toml`, check reads only there; name a file to check another. When newer results of the same eval are somewhere else, it says where and the command that checks them.

**Which answers count.** Your marks are tests for the LLM-as-a-judge, so it finds the answers you marked in the new results by the same text, word for word, and the same question (a row with no question is never one you marked with a question), and takes the new grades from there. A marked answer that isn't there, such as one your eval answered differently, or that is there with no decision (`error`), is counted, said once and left out. A grade word it doesn't know stops it, as in step 1 (exit 3). An answer graded twice with different grades counts against your LLM-as-a-judge, and repeats with the same grade count once; it says how many of each. With fewer than 15 of the answers you marked Pass, or 15 you marked Fail, it says "can't tell yet" and why (exit 3), also when nothing changed: "has not changed" needs them too. Its Next line says to grade every answer you marked again (Inspect AI: score the whole log again; MLflow: evaluate all the same traces again).

**How it decides.** It checks the answers you passed and failed as two groups. "Worse": the whole range of the change is a drop. "Better": the whole range of the change is a rise of more than 20 points. "No big drop": the low end is above a 20-point drop. "Not sure": anything else. The new grades come from one run of your eval, so a small change, or a small drop in one group, may be a coincidence. Each group's range is a 90% range, so even when nothing changed, one of the two groups can say "Worse" by coincidence, in up to about 1 check in 10 ([coverage check](examples/coverage/coverage.md)). Mark more answers before acting on one. It exits 1 only when the drop's middle estimate is over 20 points, whichever word it says. Unless it is "Worse" (or "Not sure" when the drop's middle estimate is over 20 points), your marks now test the new LLM-as-a-judge. Results from the LLM-as-a-judge you marked with, after a check of another one, say "back to the one you marked with" on every check (exit 0), and your marks test it again.

## How the numbers are worked out

**What it checks first, with no AI call.** Before you mark anything, it looks at the LLM-as-a-judge's own grades. Each finding is a line starting with "Checked:", and none stops it. The answers found are in `judge-check.csv` ([signs per tool](eval-tools.md#how-failed-calls-are-spotted)).

- **No real decision:** the call failed, its reply could not be read, or the grade is blank. Left out (promptfoo and DeepEval count these as fails).
- **Checked nothing:** a DeepEval metric with nothing to check scored 1.0. Left out.
- **Passed an empty answer:** kept, for you to mark.
- **The same grade for every answer.**
- **The reason says the opposite** of the grade.

**Which answers you mark:** every answer in the newest results with a clear Pass or Fail, counted once, in blocks of 5 your LLM-as-a-judge passed and 5 it failed. **Batches:** new answers join as the next batch, offered first. A later batch counts once each of its groups has marks in proportion to its size: 5 for a group as big as the first batch's, at least 1 and at most 15, or every answer of a smaller group.

**The result** has three numbers: **TPR** (of the answers you passed, how many your LLM-as-a-judge passed), **TNR** (of the answers you failed, how many it failed) and **the real pass rate** of your answers. Each is weighted back by group size, since the page shows more of the LLM-as-a-judge's fails than your results hold. Each has a range, the middle 96% of draws from your marks, a level chosen by a [coverage check](examples/coverage/coverage.md) and checked on [public data](examples/real-data-check/report.md). Kappa (Cohen's kappa) is how much you agree beyond what your mix of Pass and Fail alone would give; it moves with that mix, so it is only in the report's More details and never decides the result. When your LLM-as-a-judge gave every answer one grade, its TPR and TNR on your answers are 1 and 0, or 0 and 1, with no range; kappa is `null` in result.json and the page shows n/a.

**Labels you brought** with `--labels` count like marks made on the page, in the same groups with the same weights. The result then says once: "{k} of your marks came from {name}. The numbers assume those answers were picked at random and labelled without looking at your LLM-as-a-judge's grade."

### The maths (you can skip this)

**The formulas.** The pool (the answers you mark from, kept in `pool.jsonl`) holds N_pass answers your LLM-as-a-judge passed and N_fail it failed; pi = N_pass / (N_pass + N_fail). Of the n_p answers you marked in its pass group, c_p are the answers you marked Pass, so a = c_p / n_p. In its fail group, c_f of the n_f you marked are the answers you marked Pass, so b = c_f / n_f. Skipped answers don't count.

```
TPR             = pi a / (pi a + (1 - pi) b)
TNR             = (1 - pi)(1 - b) / ((1 - pi)(1 - b) + pi (1 - a))
real pass rate  = pi a + (1 - pi) b          (your LLM-as-a-judge's own is pi)
```

This is the Begg-Greenes correction; kappa uses the same weighted table. For the ranges, each group's share Correct is drawn 20,000 times from Beta(c + 0.5, n - c + 0.5) with a fixed seed. With every answer of a group marked, its share is known, so it has no range. A group with no marks makes a number that needs it unknown, never an error.

- **`fix`:** each kept-aside mark weighs N_s / h_s (its group's answers over its kept-aside marks), and the fixed and broke counts are scaled to the effective number of marks, (sum of weights)² / (sum of squared weights) (Kish's), before the sign test and Tango's test.
- **Batches:** the groups become (batch, grade) strata, each marked answer weighs N_s / n_s, and the draws are per stratum.
- **After `check`:** TPR and TNR use the new grades. The shares passed or failed again are drawn one time in three from Beta(k, m - k), which is 0 or 1 when every answer agrees, and two times in three from Beta(k + 0.5, m - k + 0.5), which keeps a range open then. The first suits an LLM-as-a-judge that gives the same grade when asked again; the second, one that turns some grades round. With none of a kind marked, the old grade stands; with every answer of a group marked, the shares have no range.

**What it says.** One result line, from the ranges:

- "Your LLM-as-a-judge is good enough to use." when the low end of both wider ranges (99%) is at least 80%;
- "Your LLM-as-a-judge needs work." when a wider range stays below 80%;
- "Too early to tell. Mark more answers to get a result." otherwise.

The ranges on screen are the middle 96%. The result line uses 99%, because you can look after every mark, and a run of good marks should not decide it.

## What it reads

It looks only inside your project folder, four folders deep; a results file outside it is read only when you name it. Your eval tool's files are never changed. It finds:

- promptfoo by `promptfooconfig.yaml`, `.yml` or `.json`, and reads its JSON results files;
- DeepEval by `.deepeval/` or `deepeval` in your dependencies, and reads `test_run_*.json`, else `.deepeval/.latest_run_full.json`;
- Inspect AI by `logs/` or `inspect-ai` in your dependencies, and reads `.json` logs, and `.eval` logs with the `inspect` extra;
- MLflow's local store, `mlruns/` or `mlflow.db`, with the `mlflow` extra;
- A CSV, TSV or JSONL file at most two folders deep, with `input`, `output` and `verdict` columns, and at most 200 columns. A table it can't read is left out, with one line saying how many;
- the lines `judgekeeper.record()` saved in `.judgekeeper/records/`.

It reads the first 100,000 answers of a results file, and the newest 100,000 records in `.judgekeeper/records/` in all, and says so when there are more.

**Very large `.eval` logs.** A `.eval` log is too big for judgekeeper to read when its `header.json` would unpack to more than 50 MB, its summaries and reductions to more than 500 MB together, one sample to more than 200 MB, or all its samples to more than 4 GB together. So is one with a part holding more than 2,000,000 values (1,000 more per sample for the summaries and reductions), more than 200,000,000 values in all its parts, samples holding more than 10 values for each byte they pack to, a sample over 1 MB that unpacks to more than 200 times its packed size, one text in a sample longer than 32 MB, or texts over 8 MB adding up to more than 64 MB. A text over 8 MB, such as a screenshot or a long tool output, is read only when at most one in 32 of its characters is a special character such as `\n` or `\"` (Inspect AI is very slow to read texts full of them). Texts over 1 MB may hold 11,000,000 of these special characters together in one log (JSON kept as a text holds about one in 7). The message says which limit it passed. A log with a part nested more than 500 levels deep is not read, nor one whose parts share bytes, give a part's size two ways or can be named two ways. judgekeeper counts what each part really unpacks to, how deep it nests, how many values it holds and how long its texts are, before Inspect AI reads the log, and keeps none of it. It then reads only the samples the log holds, each once, a few at a time.

**Very large MLflow stores.** From an MLflow store it reads at most 1,000 experiments and 1 GB of trace files in one go, and the newest 30,000 traces of an experiment. When the trace files of several experiments pass 1 GB together, it asks you to name one with `--experiment`. It doesn't let MLflow open an `mlruns/` folder holding a link, a pipe or a device, or a tag, setting or assessment file over 1 MB, such files over 200 MB together, or run metric and dataset files over 100 MB together, nor copy an `mlflow.db` that is a link or a pipe, or an `mlflow.db` over 10 GB with its `-wal` and `-shm` files. The message names the file or the limit.

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
| `annotator_kind` | `LLM` (a grade, the default; `LLM_JUDGE` too), `HUMAN` (a label, used as a mark with `--labels`) or `CODE` (ignored) |
| `label` | the grade, as in [How grades are read](#how-grades-are-read) |
| `score` | a number; the grade with `--pass-if`, or when `label` is empty |
| `explanation` | the LLM-as-a-judge's reason |
| `run` | repeat index, or empty |
| `input`, `output` | the question and answer (text or any JSON) |
| `evaluator` | the fingerprint (what tells one LLM-as-a-judge setup from another): `provider`, `model`, `prompt` (hashed), `temperature`, `version` (rubric), `rule`, `prompt_hash`, `snapshot`, `endpoint` |
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
                   reason=reason, judge="my-judge-v1", rule=criteria, name="Safe wording")
```

| Argument | What |
|---|---|
| `input`, `output` | The question and the answer the LLM-as-a-judge looked at: text or any JSON value |
| `verdict` | `pass` or `fail`, or `True` or `False` |
| `score`, `pass_mark` | Instead of `verdict`: it passes when `score >= pass_mark`. A score with no pass mark waits for `--pass-if` |
| `reason` | The LLM-as-a-judge's reason |
| `judge` | The LLM-as-a-judge's model |
| `rule` | The LLM-as-a-judge's rule, for `fix`; the marking page shows it behind "Show the rule" |
| `name` | Which LLM-as-a-judge or criterion (default `judge`) |
| `temperature`, `id`, `metadata` | The temperature, the answer's id (else one is made), and a dict of anything else |

Each call adds a line to `.judgekeeper/records/<name>-<date>-<process id>.jsonl` in your project root (the nearest folder up with `judgekeeper.toml`, `pyproject.toml`, `setup.py`, `.git` or `requirements*.txt`). It never writes in your home folder: there it saves nothing and logs that once. An answer saved twice counts once, with the newest grade. Errors inside it are logged to the `judgekeeper` logger, never raised. The file holds your inputs and outputs, so use it in eval code, not in code that serves users. `JUDGEKEEPER_RECORD=0` turns it off.

Without the import, or in another language, copy [jk_record.py](examples/records/jk_record.py) (Python) or [jk_record.ts](examples/records/jk_record.ts) (Node.js) into your eval code. They take the same arguments; run them from your project folder.

## The .judgekeeper/ folder

In your project, judgekeeper writes only inside `.judgekeeper/`, plus `judgekeeper.toml` after you say yes. Outside your project it writes only a copy of an `mlflow.db` it reads (with its `-wal` and `-shm` files) in your temporary folder (`judgekeeper-mlflow-*`), removed when judgekeeper ends. MLflow makes `mlruns/.trash` when it opens a folder store without one: judgekeeper removes `mlruns/.trash` again. It never changes other tools' settings: no editor or agent hooks, no git hooks, no `.pre-commit-config.yaml`, no requirements files, no `.gitignore` but its own. The folder holds your answers' text, so commit it only if your data may live in your repository.

- On macOS and Linux, only your user can read its files (0600) and folders (0700). Each file is written whole, replacing the old one.
- It does not write through links: if `.judgekeeper/` or anything in it is a symlink (a cloned repository can hold one) or a hard link, it stops before writing and says which.
- Text from results files is cleaned of keys before it is written. Pages escape every value, spreadsheets stop cells from running as formulas (the id column too), and the terminal gets no control or invisible characters (bidirectional controls, zero-width and tag characters). Pages drop the same characters but keep the two zero-width joiners (U+200C, U+200D), which joined emoji and scripts such as Hindi and Persian need, plus emoji variation selectors and the tag characters of the England, Scotland and Wales flags. A key split by one is still replaced.
- `mistakes.md` and `suggestions.md` start with a warning that what follows is data, with your notes and own reasons, the rule, and each question, answer, part you marked and LLM-as-a-judge's reason fenced below it.
- A `judgekeeper.toml` that names a results file outside the project is refused.

| File | What it holds |
|---|---|
| `.gitignore` | `*`, `!.gitignore`, `!judge.json`, `!history.jsonl`: your answers stay off Git. Never overwritten |
| `judge.json` | Your LLM-as-a-judge's setup: eval tool and version, models, rule and prompt (as hashes), temperature, pass mark, endpoint |
| `judge-check.json`, `judge-check.csv` | What the first check found, with each answer and its problem |
| `start.json` | The results files, the LLM-as-a-judge's fingerprint, counts, the seed, the answers' order and batches |
| `pool.jsonl` | Each answer to mark: id, input, output, batch |
| `pool-judge.jsonl` | Your LLM-as-a-judge's grade on every answer, with the fingerprint |
| `marks.jsonl` | One line per click on the page, or per label brought with `--labels` (id, mark, time, and for a label the file's name; no answer text), and your reasons |
| `reasons.json` | Your own reason buttons (at most 8) |
| `server.json`, `page.json` | The open page: port, process, token, and a secret that only closes it. Removed when it stops |
| `page.log` | What the page wrote in the background |
| `opening` | Empty: a run is opening the page |
| `ready-seen.json` | When the marking page first showed a result, so the "Your result is ready." box opens only once |
| `result.json`, `report.html` | The result: every number, your counts, the fingerprint and the date. In `result.json`, `labels.correct` and `labels.wrong` count the answers you marked Pass and Fail (not what your LLM-as-a-judge got right or wrong), and `groups.pass.correct` and `groups.fail.correct` count the answers you marked Pass among those it passed and failed |
| `history/` | Earlier results, with the same fields as `result.json` |
| `history.jsonl` | One line per result, fix test, check and new set of marks kept aside: counts and numbers, no answer text |
| `anchors.jsonl`, `anchors.manifest.json` | The answers you marked, as a fixed set with its sha256 |
| `fix/split.json` | Which marks are kept aside, the seed, and every test on them, with its sha256 |
| `fix/mistakes.md` | The clues, the rule, and each mistake on the marks you can see |
| `fix/marked-answers.csv` | Every marked answer, question and answer only, shuffled, to grade again |
| `fix/suggestions.md` | Rule lines suggested from your reasons |
| `rules/` | Each rule tested, as `<hash>.txt` |
| `results-seen.json` | The setup last read, so a check with nothing new reads nothing again |
| `verdicts/` | Each setup's grades on your marked answers (ids and grades only) |
| `records/` | What `judgekeeper.record()` saved; `--new` leaves it |
| `previous-<date>/` | Everything here before you started over, except `history.jsonl`, `verdicts/`, `records/` and `.gitignore`, which stay |

## Your API keys

- judgekeeper makes no AI call and needs no API key. It never runs your eval tool or your project's code; the only programs it starts are its own marking page and your browser (the program in `BROWSER`, when you set it). When you grade answers again, your eval tool uses your key, from your machine straight to the provider.
- judgekeeper never prints a key or writes one to a file. Before text reaches disk or your terminal, `[REDACTED]` replaces the values of `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `MLFLOW_TRACKING_PASSWORD` and any variable ending in `_API_KEY`, `_TOKEN`, `_SECRET` or `_PASSWORD`, when 8 characters or longer, even split by a hidden character. The same names set in your project's `.env` and `.env.*` files (`.env.local`, `.env.production` and the others) or in promptfoo's config `env:` block are hidden from the moment judgekeeper finds the project. A `.env` file or config that is a link, or over 1 MB, is not read, nor are the `.env` files past the first 50 in a folder, and judgekeeper says their keys are not hidden.
- It also hides anything shaped like a key: `sk-ant-…`, `sk-…`, `AKIA…`, `ASIA…`, a 40-character secret after `aws_secret_access_key` or next to an AWS key, `ghp_…`, `gho_…`, `ghs_…`, `ghu_…`, `github_pat_…`, `AIza…`, `xoxb-…`, `xoxp-…`, `gsk_…`, `hf_…`, `xai-…`, a JWT, `Bearer …`, `Basic …`, and the login part of a URL: `user:password@`, `:password@`, or a long token alone.
- An unexpected error prints one line, never its own text (it can hold an answer), and exits 2.
- There is no flag that takes a key, and there never will be.

## When something goes wrong

- **Port 8765 is taken:** judgekeeper tries 8766 to 8785 and uses the first free one. If those are taken too, it says so, and its `Next:` line gives the command that opens the page on any free port.
- **The browser didn't open:** open the link judgekeeper printed.
- **"This link no longer works":** each time judgekeeper opens its page, it makes a new link, and older links stop working. Your marks are saved. Run `judgekeeper mark` to open the page again.
- **To remove judgekeeper:** run `pip uninstall judgekeeper`, then delete `.judgekeeper/` and `judgekeeper.toml` from your project.

## Checked on public data

- **JailbreakBench.** The dataset's own LLM-as-a-judge graded 300 answers that three experts also marked. In 100 tests with 100 marks each, judgekeeper's ranges held the true TPR in 99, the true TNR in 98 and the true kappa in 99; all three at once in 97. [Report](examples/jailbreakbench/report.md)
- **RAGTruth.** Three LLM-as-a-judge setups (A, B and C; the report names the models) graded 200 news summaries with one rule, 3 runs each. judgekeeper said "needs work" in all 12 runs. These numbers are about the answers in each sample, all of which were marked. In run 1 of each, of the summaries people passed the setup also passed 66% for A, 68% for B and 58% for C; of the summaries people failed it also failed 89%, 90% and 94%. Changing the model did not close the gap. RAGTruth's people labeled with a different rule from the one the LLM-as-a-judge was given, so part of the disagreement is the rule, not the LLM-as-a-judge. [Report](examples/ragtruth/report.md)
- **RAGTruth, two more tasks.** Two of those setups (A and B) graded 200 question answers and 200 data-to-text overviews, 1 run each. judgekeeper said "needs work" in all 4 runs. Of the answers people passed, the setup also passed 61% for A and 58% for B on question answers, and 39% and 65% on data-to-text; of the answers people failed, it also failed 95% and 97%, and 98% and 97%. [Question answers](examples/ragtruth-qa/report.md), [data-to-text](examples/ragtruth-data2txt/report.md)
- **JailbreakBench, graded by two other setups.** The same 300 answers were graded by two LLM-as-a-judge setups (A and B), with the three experts' majority as the marks. judgekeeper said "needs work" for both. Of the answers the experts passed, the setup also passed 98% for A and 99% for B; of the answers the experts failed, it also failed 43% and 32%. The model provider declined to grade 6 answers for A and 61 for B, and judgekeeper leaves those out. For the dataset's own LLM-as-a-judge the same two figures are 90.0% and 90.9%. [Report](examples/jailbreakbench-setups/report.md)
- **Empty answers.** In a test we ran with promptfoo, two models graded empty summaries, which should fail. With one rule, one model failed 0 of 20 and the other failed 14 of 20. Marks on real answers don't show this. [Report](examples/probes/report.md)
- **Simulation.** In made-up checks, the ranges held the true value as often as the level asks. The average is the chosen level's Average, in the report's first table. The lowest, 91.6, is after grading again with 10 marks in each group, in batches (table "Batches"). Before grading again, the lowest is 93.2, when marking stops as early as it can: 15 of your Passes, 15 of your Fails, and 20 marks on answers your LLM-as-a-judge passed and 20 on answers it failed (table "The real stopping rule"). [Coverage check](examples/coverage/coverage.md)

The tests run on Linux, Windows and macOS.

## Exit codes

| exit code | meaning | commands |
|---|---|---|
| 0 | success: the step is done | all |
| 1 | the drop's middle estimate is over 20 points, whichever word it says (Worse or Not sure): the new LLM-as-a-judge agrees with you over 20 points less on the answers you passed or failed | `check` |
| 2 | usage error: bad arguments, a file it can't read, a place it can't write, a removed command, an error it didn't expect, or a results file given to `fix` or `check` from another eval tool or LLM-as-a-judge | all |
| 3 | you are needed: the `Next:` line says what to do. For example: no eval results found, too few of one kind, a rule to change, a grade it doesn't know, or stopped at a question it cannot ask (no terminal) | all |
| 130 | stopped with Ctrl-C: it prints "Stopped." and what was saved stays saved | all |
