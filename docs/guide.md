# judgekeeper guide

Check your LLM-as-a-judge in 5 steps. The [README](../README.md) is the short version. This page holds the rest, in the order you are likely to need it.

On this page: [Start here](#start-here), [Why](#why), [Install](#install), [Your tools](#your-tools), [First results](#first-results), [Why this and not X](#why-this-and-not-x) and [The website](#the-website). Every command, flag, exit code and config key is in [`docs/reference.md`](reference.md).

## Start here

Check your LLM-as-a-judge in 5 steps: Find. Mark. Measure. Fix. Re-check.

```
cd your-project
judgekeeper
```

Run it in your own terminal. Each run does the next step and ends with one `Next:` line that says what you do.

1. **Find.** `judgekeeper` finds the results your eval tool already saved (promptfoo, DeepEval, Inspect AI, MLflow, or a CSV or JSONL file with `input`, `output` and `verdict` columns), names your judge and its rule, and checks its grades for free (no AI call).
2. **Mark.** It opens the marking page in your browser: one answer at a time, half from your judge's passes and half from its fails, with your judge's grade hidden. You mark each one Pass or Fail, the way you want your judge to decide (keys `←` Fail and `→` Pass). On a remote machine, `--no-browser` prints the page's link for you to open. `judgekeeper mark` opens the page again to mark more; `judgekeeper --stop` closes it.
3. **Measure.** Run `judgekeeper` again. After 15 Pass and 15 Fail it shows how often your judge agrees with you: of the answers you passed, how many it passed (TPR), and of those you failed, how many it failed (TNR), each with a range, and kappa. 25 of each, with both ranges no wider than 0.30, makes the result reliable. The full report is `.judgekeeper/report.html`.
4. **Fix.** Run `judgekeeper fix`. It sets about a third of your marks aside, hidden, and shows where your judge goes wrong on the rest; `.judgekeeper/fix/mistakes.md` lists each mistake with your judge's own reason, and it says where your judge's rule is written. For a judge with a score, it also tests a better pass mark on the hidden marks, for free. Write your new rule in `.judgekeeper/fix/rule.txt` and run `judgekeeper fix` again: it asks your judge about the hidden answers with the old rule and the new one (it says how many AI calls and asks `Go ahead? [y/N]` first), then says whether the new rule is better, safe to try, or can't be told yet. judgekeeper never changes your files: you put the new rule in place.
5. **Re-check.** After you change your judge (its model, rule, pass mark and so on) or update your eval tool, run your eval, then `judgekeeper check`. It re-tests the new judge on your marks: for free when your new results already hold its grades for the answers you marked, else by asking your judge about them through your own eval tool, with your own key. Before any AI call it says how many and asks `Go ahead? [y/N]`; without a terminal it needs `--yes`. The report's History keeps each check.

What the first run prints:

```text
judgekeeper 1.0.0b2

Step 1 of 5: Find

Eval tool:   promptfoo
Answers:     40 answers from your app, each graded by your judge
             (read from results.json)
Judge:       openai:gpt-4.1-mini
Judge rule:  "The answer solves the customer's problem and is polite."

Your judge's grades: 23 Pass, 17 Fail.
Free check (no AI call): every answer got a clear Pass or Fail.

Step 2 of 5: Mark

The marking page is open in your browser. It shows the same
answers one at a time. Mark each one Pass or Fail, the way you
want your judge to decide. Your judge's grade stays hidden, so
you decide on your own.

Next: mark until the page says you have enough, then run
`judgekeeper` again.
```

judgekeeper never runs your app. It writes only inside `.judgekeeper/` in your project (and `judgekeeper.toml`, after you say yes to saving where your results are), so you can stop and carry on at any time. Every command, flag and saved file: [`reference.md`](reference.md).

Your judge saves its results in a format of its own? `judgekeeper` looks for a JSON, JSONL or CSV file that holds them, shows how it will read it, and asks before it saves that in `judgekeeper.toml`. Or turn them into a table with `id`, `input`, `output`, `verdict` (pass or fail) and `reason` columns, plus `judge_model` when you know the model, and run `judgekeeper your-table.csv`.

## Why

Teams grade AI outputs with another model, the "judge". Judges disagree with humans more than raw agreement suggests. They can flip verdicts between identical runs, and can change when the provider updates the model. judgekeeper measures how often a judge agrees with a frozen set of human labels and shows you, later, whether it still agrees as often.

The result shows:

- TPR (how often the judge passes what humans passed) and TNR (how often it fails what humans failed), each with a range.
- Kappa: agreement beyond chance. Never raw agreement on its own.
- How far the labels go: a rough check needs 15 labeled pass and 15 labeled fail. A reliable result needs 25 of each, and TPR and TNR ranges no wider than 0.30.

## Get it

You need Python 3.11 or newer.

```
source .venv/bin/activate
pip install judgekeeper
judgekeeper --version
```

Run these in your project folder. judgekeeper is a tool for developers, like pytest: it goes inside your project's own Python environment. The last line shows judgekeeper is installed. For Windows, uv, Poetry and a fix for each thing that can go wrong, see [Install](#install) below.

### Install

judgekeeper is a tool for developers, like pytest: install it inside your project, in the project's own Python environment, never on your computer as a whole. Linux follows the Mac lines.

1. Check Python. Mac: `python3 --version`. Windows: `py --version` (`python --version` works too when Python is on the PATH). You should see `Python 3.11` or a higher number. If you see "command not found" or a lower number: on a Mac or Windows, install Python from https://www.python.org/downloads/ and open a new terminal; on Linux, get Python 3.11 or newer from your package manager (Ubuntu 22.04 comes with Python 3.10, which is too old). A `.venv` you made before keeps its old Python: delete it and make it again.
2. Go to your project and switch on its environment. The start of the line then reads `(.venv)`.
3. Install: `pip install judgekeeper`. A line near the end starts with `Successfully installed`. Your project uses uv or Poetry? Run `uv add --dev judgekeeper` or `poetry add --group dev judgekeeper` instead, then put `uv run` or `poetry run` in front of each command: `uv run judgekeeper`.
4. Run `judgekeeper --version`. It says judgekeeper is ready.

Step 2 on a Mac:

```
cd your-project
source .venv/bin/activate
```

Step 2 on Windows, in PowerShell:

```
cd your-project
.venv\Scripts\activate
```

No `.venv` folder in your project yet? Make one first with `python3 -m venv .venv` (Windows: `py -m venv .venv`), then switch it on. If your project keeps its environment in another folder, such as `venv`, use that name. In Command Prompt the line is `.venv\Scripts\activate.bat`. If PowerShell refuses to run the script, run `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser` once and try again. Add judgekeeper to your project's dev requirements, so everyone who works on the project gets it.

If something goes wrong:

- `Could not find a version that satisfies the requirement judgekeeper (from versions: none)`: your Python is too old. judgekeeper needs Python 3.11 or newer. Install a newer Python, delete `.venv`, and make it again (`python3.12 -m venv .venv`; Windows: `py -3.12 -m venv .venv`).
- `ensurepip is not available` when you make `.venv` on Linux: on Debian and Ubuntu, the part of Python that makes environments is a package of its own. Install the one for your Python, such as `python3.12-venv` (`sudo apt install python3.12-venv`), delete the half-made `.venv`, and make it again.
- uv or Poetry refuses because your project also allows an older Python than judgekeeper needs: use `uv add --dev "judgekeeper; python_version >= '3.11'"` or `poetry add --group dev judgekeeper --python ">=3.11"`.
- `error: externally-managed-environment`: your project's environment is not switched on, so pip tried to install into the Python of your whole computer, which Homebrew or the system protects. It is not about judgekeeper. Run step 2, then install again.
- `pip: command not found` (a Mac may print `zsh: command not found: pip`): outside an environment, a Mac names the command `pip3`. Switch on your project's environment (step 2): inside it, `pip` works.
- `'pip' is not recognized as an internal or external command` on Windows (PowerShell words it as `The term 'pip' is not recognized`): Inside your project's environment `pip` is always found, so the environment is not switched on: switch it on again. Or use the environment's own Python, which always installs into your project: `.venv\Scripts\python -m pip install judgekeeper`.
- The `judgekeeper` command is not found after installing: with your project's environment switched on, `python -m judgekeeper --version` does the same thing; put `python -m` in front of every `judgekeeper` command. With uv or Poetry, put `uv run` or `poetry run` in front instead.

See a real report without installing anything: [LLMBar judged by Claude Haiku 4.5](examples/llmbar-haiku/report.html), also published at https://www.judgekeeper.com/examples/llmbar-haiku/.

## Your tools

### I use a framework

`judgekeeper` reads the files your eval tool already writes: promptfoo, DeepEval, Inspect AI and MLflow. Your eval code does not change. How to get each file and each tool's traps: [`docs/integrations/`](integrations/). Any other tool (or your own code) can write judgekeeper's records format (one JSON line per verdict: `name, input, output, label` or `score`, plus optional fields such as `evaluator` and `metadata`; see the [records format](reference.md#records-format)), or call [`judgekeeper.record()`](reference.md#record-save-your-own-judges-verdicts-with-one-line).

## First results

The judge is strong on ordinary items and weak on adversarial ones: `claude-haiku-4-5-20251001` reaches kappa 0.94 against human labels on LLMBar's Natural slice but 0.56 on Adversarial/GPTOut ([report](examples/llmbar-haiku/report.html), data in [`docs/examples/llmbar-haiku/`](examples/llmbar-haiku/)).

The run: LLMBar (Natural and Adversarial subsets, 419 human-labeled pairwise items) judged by `claude-haiku-4-5-20251001` at temperature 0, 3 runs, AB and BA, on 2026-10-01 against `api.anthropic.com`; the report and its judgments are in `docs/examples/llmbar-haiku/`. Every number below is quoted from `docs/examples/llmbar-haiku/report.json` (human-readable version: `report.html` in the same folder). The report was written again by judgekeeper 0.1.2 on 2026-10-04 from the same judgments, with no new model call, so its verdict follows the current rules. TPR and TNR treat human label `A` as the positive class.

Verdict: **Usable with care: TPR 0.95, TNR 0.88, kappa 0.83 against human labels.** The one flag: "TNR is 0.88 (between 0.80 and 0.90): usable with care."

| Run | Kappa | TPR | TNR |
|---|---|---|---|
| 1 | 0.82 | 0.95 | 0.87 |
| 2 | 0.85 | 0.96 | 0.89 |
| 3 | 0.82 | 0.95 | 0.87 |
| Mean | 0.83 | 0.95 | 0.88 |

| Slice (mean over runs) | Items | Kappa | TPR | TNR |
|---|---|---|---|---|
| Natural | 100 | 0.94 | 0.98 | 0.97 |
| Adversarial/GPTInst | 92 | 0.92 | 1.00 | 0.92 |
| Adversarial/Neighbor | 134 | 0.84 | 0.96 | 0.88 |
| Adversarial/Manual | 46 | 0.64 | 0.91 | 0.74 |
| Adversarial/GPTOut | 47 | 0.56 | 0.86 | 0.71 |

- Noise floor: mean pairwise kappa between runs 0.95. 3.6% of items changed verdict in at least one run.
- Position bias: 9.9% of judgments changed when the two outputs were swapped (AB vs BA). Kappa on the BA order alone was 0.80.
- The judge's TNR is lower than its TPR. Its errors cluster in the hardest adversarial slices (GPTOut, Manual), where kappa drops to 0.56 and 0.64.

## Why this and not X

- Any model vendor, any eval tool, plain files in your repo. judgekeeper is owned by no model or platform vendor: your marks are a CSV, the result is JSON and HTML, and the judge is whatever your eval tool runs.
- Several eval tools (LangSmith, Arize, MLflow, Ragas, Confident AI) help you line a judge up with human labels. judgekeeper adds what comes after that first check: checking again over time, and checking again when the judge's model or prompt changes.
- RAND's Judge Reliability Harness generates bias probes; judgekeeper adds agreement with human labels (kappa, TPR, TNR) and checks over time.

## The website

The website at https://www.judgekeeper.com (source in [`website/`](../website/)) explains judge evaluation step by step, with a setup guide; preview it with `python3 -m http.server --directory website 8000`.
