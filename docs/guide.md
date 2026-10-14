# judgekeeper guide

Check your LLM-as-a-judge. See how often it agrees with human labels, in one command. The [README](../README.md) is the short version. This page holds the rest, in the order you are likely to need it.

On this page: [Start here](#start-here), [Why](#why), [Install](#install), [Your tools](#your-tools), [First results](#first-results), [Why this and not X](#why-this-and-not-x) and [The website](#the-website). Every command, flag, exit code and config key is in [`docs/reference.md`](reference.md).

## Start here

```
cd your-project
judgekeeper start
```

`judgekeeper start` finds the results your eval tool already saved (promptfoo, DeepEval, Inspect AI, MLflow, or a CSV or JSONL file with `input`, `output` and a verdict column) and names your judge. It opens a page in your browser with one answer at a time, half from the judge's passes and half from its fails, without what the judge said; you mark each one Pass or Fail by your judge's rule (keys `←` Fail and `→` Pass). Then it shows how often your judge agrees with you, corrected for that picking: "When you said Pass, your judge also said Pass 83% of the time." You see a result after 15 Pass and 15 Fail; 25 of each with both ranges no wider than 0.30 makes it reliable. Everything is saved in `.judgekeeper/`, so you can stop, carry on, and check again after your next eval run.

What it prints first:

```text
judgekeeper found your LLM-as-a-judge:

  Eval tool       promptfoo
  Results file    evals/results.json (saved 3 Oct 2026, 10:00)
  What it checks  "Is polite and correct."
  Judge model     openai:gpt-4.1-mini
  Its decisions   50 answers: 30 passed, 20 failed

Next: in your browser, mark each answer Pass or Fail.
This shows how often your judge agrees with you.
Open it now? [Y/n]
```
 No AI calls unless you say yes. Then your own judge runs through your own tool; judgekeeper never sees your key, it only checks its name. It never runs your app. Every flag and saved file: [`reference.md`](reference.md#start-find-your-results-label-see-the-result).

Your judge saves its results in a format of its own? Turn them into a table with `id`, `input`, `output`, `verdict` (pass or fail) and `reason` columns, plus `judge_model` when you know the model, and run `judgekeeper start your-table.csv`; it prints the counts, the pass/fail split and the first 3 rows, so a wrong table shows. `judgekeeper start --agent-prompt` prints a prompt that asks your coding agent to write that table for you.

### After your first result

Run `judgekeeper start` again and it asks what next:

- **See where you disagree** (`--review`, free, no AI call). First you look again at each answer where you and your judge disagree, mixed with answers you agreed on, with what the judge said still hidden. Then you see what the judge said, with its reason, and say whether your judge was wrong, you were wrong, or the rule is unclear, with an optional line of why. The judge's mistakes go to `.judgekeeper/judge-mistakes.csv`. Your first marks stay the main result.
- **Fix your judge** (`--fix`, free, no AI call), once the review found something. First it keeps about 30% of your marked answers aside, to test a change fairly. From the rest it shows what your judge gets wrong: the two kinds of mistakes, with your why, and plain patterns in them. For a judge that gives a score, it finds the pass mark that fits your marks best and tests it on the answers kept aside in one click. To change the rule, "Let your coding agent do it" gives you one prompt for Claude Code, Cursor or Codex: the agent writes the new rule, puts it in the right file, runs your eval and Try your new judge, and tells you the numbers, asking you before anything that costs money. Or copy a prompt for any AI assistant, or write the rule yourself; judgekeeper says where the new rule goes, and Try your new judge tests it on the answers kept aside. A small local model can grade answers, but it usually can't rewrite a rule well. Use a capable assistant for this step: judgekeeper's fair test shows whether the new rule helped either way.
- **Ask your judge again** (`--ask-again`). Your own eval tool grades the answers you marked again, with your own judge; your app is not run. First a plan: whether this is exactly your judge or a close copy, which key it uses (by name only), how many calls and a dated cost range. Then `Go ahead? [y/N]`, No unless you type y. It shows how often the judge changes its verdict, and how well it agrees with you today.
- **Try your new judge** (`--try-new-judge`). After you change your judge's rule or model and run your eval once, the new judge grades the answers you already marked, shown side by side with the old one. A judge fixed while looking at these answers looks better on them, so it then offers a quick check on 10 Pass and 10 Fail new answers.
- **Mark more answers** (`--label-more`), or nothing for now.

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
3. Install: `pip install judgekeeper`. A line near the end starts with `Successfully installed`. Your project uses uv or Poetry? Run `uv add --dev judgekeeper` or `poetry add --group dev judgekeeper` instead, then put `uv run` or `poetry run` in front of each command: `uv run judgekeeper start`.
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

`judgekeeper start` reads the files your eval tool already writes: promptfoo, DeepEval, Inspect AI and MLflow. Your eval code does not change. How to get each file and each tool's traps: [`docs/integrations/`](integrations/). Any other tool (or your own code) can write judgekeeper's records format (one JSON line per verdict: `name, input, output, label` or `score`, plus optional fields such as `evaluator` and `metadata`; see the [records format](reference.md#records-format)), or call [`judgekeeper.record()`](reference.md#record-save-your-own-judges-verdicts-with-one-line).

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
