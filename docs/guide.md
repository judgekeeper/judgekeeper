# judgekeeper guide

Check your LLM-as-a-judge. See how often it agrees with human labels, in one command. The [README](../README.md) is the short version. This page holds the rest, in the order you are likely to need it.

| Layer | When you need it | Commands |
|---|---|---|
| [0. The core](#0-the-core) | You have judge verdicts and human labels | `check` |
| [1. Labels](#1-labels) | You have no human labels yet | `label` |
| [2. Rule and judge](#2-rule-and-judge) | You want your own rule, or want judgekeeper to run the judge | `init`, `judge`, `validate`, `template`, `import-labels`, `freeze` |
| [3. Keep checking](#3-keep-checking) | You want a warning when the judge changes | `baseline`, `gate`, `migrate`, `attribute` |
| [4. Your tools](#4-your-tools) | You use an eval framework, pytest or CI | `import`, `export`, the pytest plugin, the GitHub Action |

Also on this page: [Why](#why), [First results](#first-results), [Why this and not X](#why-this-and-not-x) and [The website](#the-website). Every command, flag, exit code and config key is in [`docs/reference.md`](reference.md).

## Why

Teams grade AI outputs with another model, the "judge". Judges disagree with humans more than raw agreement suggests, flip verdicts between identical runs, and change silently when the provider updates the model. judgekeeper measures how often a judge agrees with a frozen set of human labels and shows you, later, whether it still agrees as often.

The report leads with TPR (how often the judge passes what humans passed) and TNR (how often it fails what humans failed), each with a 95% interval. Either below 0.80 is "not trustworthy as a gate"; 0.80 to 0.90 is "usable with care". It also shows kappa (agreement beyond chance; never raw agreement on its own), a confusion matrix, every disagreement with the judge's rationale, the noise floor across repeated runs ("unknown" with one run, never zero), AB/BA position bias for pairwise items, per-slice numbers, and warnings when there are fewer than 60 labels or the classes split worse than 80/20.

## 0. The core

```
pip install judgekeeper
judgekeeper --version
```

The second line prints the version, which shows judgekeeper is installed. On a Mac the command is `pip3`. If the install is refused, see [Install](#install) below.

### Install

Linux follows the Mac lines.

1. Check Python. Mac: `python3 --version`. Windows: `py --version` (`python --version` works too when Python is on the PATH). You should see `Python 3.11` or a higher number. If you see "command not found" or a lower number, install Python from https://www.python.org/downloads/ and open a new terminal.
2. Install. Mac: `pip3 install judgekeeper`. Windows: `pip install judgekeeper`. A line near the end starts with `Successfully installed`.
3. Run `judgekeeper --version`. It prints `judgekeeper` and the version number.

**If step 2 was refused** with `error: externally-managed-environment`: this Python is managed by Homebrew or by the system, and it refuses direct installs to protect itself. It is not about judgekeeper. The fix is a virtual environment: a folder that holds a Python program and what it needs, kept apart from the rest of your computer. Make one, switch it on, and install inside it.

Mac:

```
python3 -m venv ~/judgekeeper-env
source ~/judgekeeper-env/bin/activate
pip install judgekeeper
```

Windows, in PowerShell:

```
py -m venv "$HOME\judgekeeper-env"
& "$HOME\judgekeeper-env\Scripts\Activate.ps1"
pip install judgekeeper
```

After the second line, the start of the prompt reads `(judgekeeper-env)`. Each time you open a new terminal, run that second line again before you use judgekeeper. In Command Prompt the first two lines are `py -m venv "%USERPROFILE%\judgekeeper-env"` and `"%USERPROFILE%\judgekeeper-env\Scripts\activate.bat"`. If PowerShell refuses to run the script, run `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser` once and try again.

Three more notes:

- `pip: command not found` (a Mac may print `zsh: command not found: pip`): on a Mac the command is named `pip3`.
- `'pip' is not recognized as an internal or external command` on Windows (PowerShell words it as `The term 'pip' is not recognized`): Python was installed without being added to the PATH, the list of places Windows looks for commands. The `py` command is installed either way, so use `py -m pip install judgekeeper`.
- The `judgekeeper` command is not found after installing: `python3 -m judgekeeper --version` (Mac) or `py -m judgekeeper --version` (Windows) does the same thing; put `python3 -m` or `py -m` in front of every `judgekeeper` command.

See a real report without installing anything: [LLMBar judged by Claude Haiku 4.5](examples/llmbar-haiku/report.html), also published at https://www.judgekeeper.com/examples/llmbar-haiku/.

Already have judge verdicts and human labels in a CSV? One command:

```
judgekeeper check results.csv --judge verdict --human label --out reports/my-judge/
```

One row per judgment. `id`, `run`, `input`, `output` and `reason` columns are used when present. Verdicts can be `pass`/`fail`, `true`/`false`, `yes`/`no`, `correct`/`incorrect`, `1`/`0` or text starting with `PASS`/`FAIL`; scores need a rule (`--pass-if "score>=0.5"`); other spellings need `--label-map "good=pass,bad=fail"`. judgekeeper never guesses.

### I have a spreadsheet

Judge verdicts and human labels already in one table: `judgekeeper check` above. Give it a `run` column (or several rows per id with different runs) to measure run-to-run noise; with one run the noise floor is reported as unknown and `gate` returns `FLAKY`. Without an `id` column, ids are a hash of input and output and the report says so. In a notebook:

```python
import judgekeeper
report = judgekeeper.check_table(df, judge="verdict", human="label")   # a DataFrame, a list of dicts or a path
```

## 1. Labels

No labels yet? Label in the local page or in Excel or Google Sheets, then freeze the labels as an anchor set:

```
judgekeeper label items.jsonl --out labels.csv        # or: judgekeeper template items.jsonl -o labels.csv
judgekeeper import-labels labels.csv -o anchors.jsonl # checks every label, skips and lists unlabeled rows, freezes
```

`judgekeeper label items.jsonl` opens a local labeling page (keys 1/2, defer, undo, notes) that writes `labels.csv` as you go. [Details](reference.md#label-a-local-labeling-page).

## 2. Rule and judge

**Bring your own metric. judgekeeper checks it against your labels and tells you when that check is out of date.**

Your metric is a rule in plain words plus any judge model. The proof is a report of how often that judge agrees with your frozen human labels. "Expires" means `gate` returns `JUDGE_CHANGED` or `ANCHORS_CHANGED` when the model, the rule or the labels change, so a passing report never outlives the judge it measured.

Your own rule starts from a file:

```
judgekeeper init --out prompts/judge.md      # then fill in the [FILL IN: ...] parts
```

Label real outputs, run any judge with `--prompt prompts/judge.md`, read the report. [Your own metric](own-metric.md) walks through it with two worked examples on one company-style rule.

### I have a judge function

Run it 3 times over the anchor set (pairwise items in both AB and BA order) and get a report:

```python
import judgekeeper
def my_judge(item):          # item: id, input, output (never the human label)
    return call_my_model(item) # bool, "PASS: ...", 0.8, (verdict, reason) or {"verdict": ..., "reason": ...}
report = judgekeeper.check_judge(my_judge, "anchors.jsonl", runs=3, fingerprint={"model": "my-model"})
```

Async functions work too. A judge that raises or returns nothing is recorded as an error, excluded from the metrics and counted, never scored as a fail. From the command line, a Python function or a program in any language (one item as JSON on stdin, a verdict on stdout):

```
judgekeeper judge anchors.jsonl --callable mypkg.judges:my_judge --prompt prompts/judge.md --runs 3 --out runs/mine/
judgekeeper judge anchors.jsonl --exec "node judge.js" --runs 3 --out runs/mine/
judgekeeper validate anchors.jsonl runs/mine/ --out reports/mine/
```

judgekeeper prints the number of judge calls first and asks for `--yes` above 1,000. The `--exec` contract, with 10-line Node and Python judges, is in [`docs/reference.md`](reference.md). Keys stay in environment variables; nothing judgekeeper writes or prints contains one.

judgekeeper can also call the model for you, with its built-in Anthropic and OpenAI-compatible runners (`--runner anthropic|openai`, any OpenAI-compatible endpoint via `--base-url`). They need the provider's client library, which is an optional extra of the package:

```
pip install "judgekeeper[anthropic]"        # for --runner openai: pip install "judgekeeper[openai]"
judgekeeper judge anchors.jsonl --runner anthropic --model claude-haiku-4-5-20251001 --prompt prompts/judge.md --runs 3 --out runs/haiku/
```

The flags and the custom endpoints are in [`docs/reference.md`](reference.md).

### Your own metric, worked through

[`docs/own-metric.md`](own-metric.md) takes one company-style rule (a support reply must state the refund window the policy gives and must not promise a refund the policy does not allow) through `init`, labels, two judges and the report. The data is synthetic, the labels are by construction, and it is an illustration of the steps, not a benchmark. A keyword-matching Python function as the judge gets kappa 0.67, TPR 1.00, TNR 0.67: it passes every polite reply that states the right window and then promises a refund anyway ([report](examples/own-metric/function/report.html)). The same rule as a DeepEval `GEval` metric judged by `claude-haiku-4-5-20251001` gets kappa 0.97, TPR 0.97, TNR 1.00 ([report](examples/own-metric/deepeval/report.html)): it catches every wrong reply and fails one correct one.

## 3. Keep checking

```
judgekeeper baseline set reports/my-judge/report.json   # commit .judgekeeper/baseline.json
judgekeeper gate reports/my-judge/report.json           # PASS, FAIL, FLAKY, JUDGE_CHANGED, ANCHORS_CHANGED
judgekeeper migrate anchors.jsonl runs/old/ runs/new/ --out reports/migration/
judgekeeper attribute reports/now/report.json --app-score-before X --app-score-after Y
```

`gate` never fails on a change inside the noise band. In CI, the GitHub Action (`action.yml`) runs judge, validate and gate, and the pytest plugin gates a report your pipeline already wrote. A judge field that is unknown on either side (imported data rarely records temperature or snapshot) is a warning, not a block, unless you pass `--require-fingerprint`. `migrate` compares an old and a new judge item by item; `attribute` says whether a score moved because your system changed or the judge did. Details: [`docs/reference.md`](reference.md).

## 4. Your tools

- Gate from pytest: `pytest --judgekeeper-report reports/my-judge/report.json`, a `judgekeeper_gate` fixture or a `@pytest.mark.judgekeeper` marker. [Details](reference.md#pytest-plugin).
- Let a coding agent wire it in: [`skills/judgekeeper/SKILL.md`](../skills/judgekeeper/SKILL.md) tells Claude Code and other agents how, step by step.

### I use a framework

Point judgekeeper at the files your eval tool already writes and add human labels. Your eval code does not change.

promptfoo (human labels from web-UI ratings, or `--labels`; repeats from `--repeat 3`):

```
promptfoo eval -o results.json --repeat 3
judgekeeper import promptfoo results.json --metric helpfulness --out reports/helpfulness/
```

DeepEval (one `test_run_*.json` per run in a results folder; labels from `--labels`):

```
export DEEPEVAL_RESULTS_FOLDER=deepeval-results   # then run your DeepEval tests 3 times
judgekeeper import deepeval deepeval-results/ --metric "Correctness [GEval]" --labels labels.csv --out reports/correctness/
```

Inspect AI (epochs are runs; labels from score edits or `--labels`; `.eval` logs need the `judgekeeper[inspect]` extra):

```
inspect eval task.py --epochs 3 --log-format json
judgekeeper import inspect logs/ --metric model_graded_qa --labels labels.csv --out reports/qa/
```

MLflow (judge and human assessments on your traces; each evaluation run is a run; needs the `judgekeeper[mlflow]` extra):

```
judgekeeper import mlflow --experiment my-app-eval --metric correctness --out reports/correctness/
```

Langfuse (judge and human scores from the public API; keys from `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY`):

```
judgekeeper import langfuse --judge-score helpfulness --human-score helpfulness_human --from 2026-09-01 --pass-if "score>=0.5" --out reports/helpfulness/
```

Each writes the same `report.json` and `report.html` as `check`. With `--anchors-out anchors.jsonl`, the MLflow and Langfuse imports also freeze the labeled items as an anchor set, so you can re-judge them with `judgekeeper judge` for a real noise floor. How to get each file, how labels get in and each tool's traps: [`docs/integrations/`](integrations/). Any other tool can export ScoreRecords (`target_id, name, annotator_kind, label, score, explanation, run, input, output, evaluator, created_at`) and use `judgekeeper import records`, with `--map` for renamed columns; `judgekeeper export records` writes judgekeeper's runs in that format.

## First results

The judge is strong on ordinary items and weak on adversarial ones: `claude-haiku-4-5-20251001` reaches kappa 0.94 against human labels on LLMBar's Natural slice but 0.56 on Adversarial/GPTOut ([report](examples/llmbar-haiku/report.html), data in [`docs/examples/llmbar-haiku/`](examples/llmbar-haiku/)).

The run: LLMBar (Natural and Adversarial subsets, 419 human-labeled pairwise items) judged by `claude-haiku-4-5-20251001` at temperature 0, 3 runs, AB and BA, on 2026-10-01 against `api.anthropic.com`; `scripts/llmbar_haiku_demo.sh` runs it end to end and writes the report to `docs/examples/llmbar-haiku/`. Every number below is quoted from `docs/examples/llmbar-haiku/report.json` (human-readable version: `report.html` in the same folder). The report was written again by judgekeeper 0.1.2 on 2026-10-04 from the same judgments, with no new model call, so its verdict follows the current rules. TPR and TNR treat human label `A` as the positive class.

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

- Any model vendor, any eval tool, plain files in your repo. judgekeeper is owned by no model or platform vendor: the rule is a markdown file, the labels are a CSV, the report is JSON and HTML, and the judge is whatever you point it at.
- Several eval tools (LangSmith, Arize, MLflow, Ragas, Confident AI) help you line a judge up with human labels. judgekeeper adds what comes after that first check: checking again over time, checking again when the judge's model or prompt changes, and using the result as a gate in CI.
- RAND's Judge Reliability Harness generates bias probes; judgekeeper adds agreement with human labels (kappa, TPR, TNR), checks over time and a CI gate.

## The website

The website at https://www.judgekeeper.com (source in [`website/`](../website/)) explains judge evaluation step by step, with a key setup guide and a hands-on tutorial; preview it with `python3 -m http.server --directory website 8000`.
