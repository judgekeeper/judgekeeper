# Your own metric

Bring your own metric. judgekeeper checks it against your labels and tells you when that check is out of date. This page shows how, from an empty folder to a checked metric, with two worked examples on one rule.

- [1. The idea](#1-the-idea)
- [2. How to write a rule](#2-how-to-write-a-rule)
- [3. Worked example A: a plain function](#3-worked-example-a-a-plain-function)
- [4. Worked example B: a DeepEval metric](#4-worked-example-b-a-deepeval-metric)
- [5. The same steps for any rule](#5-the-same-steps-for-any-rule)
- [6. What judgekeeper does not do](#6-what-judgekeeper-does-not-do)

## 1. The idea

Your metric is your rule plus any judge. The rule says, in plain words, what pass and fail mean for one thing you care about. The judge is any model, or any function, that reads an output and applies the rule.

judgekeeper checks that judge against a small set of outputs that a person graded by hand, and reports how often the two agree: TPR, TNR and kappa.

The check goes out of date when the model, the rule or the labels change. `gate` then says `JUDGE_CHANGED` or `ANCHORS_CHANGED`, so a report never outlives the judge it measured.

## 2. How to write a rule

Start from the starter file:

```
judgekeeper init --out prompts/judge.md       # --pairwise for a rule that compares two outputs
```

It has `[FILL IN: ...]` markers for every part you write. `judge --prompt` refuses the file until they are all gone. Some advice:

- One thing per rule. "Is the reply good?" is not a rule. "Does the reply state the refund window the policy gives?" is. If you care about three things, write three rules.
- Pass or fail, not a score from 1 to 5. People disagree about a 3; they rarely disagree about pass. A judge that gives scores needs a threshold anyway, so decide it now.
- Read real outputs before you write. Twenty real replies will show you cases you would not have thought of.
- Say what pass and fail look like, with examples. Two or three of each, taken from the real outputs.
- Write down the edge cases. The reply that is right but rude. The reply that states the right rule and then breaks it. Say which way each one goes.
- Bump `rubric_version` when the rule changes. A changed rule is a changed judge, even with the same model: `gate` reports `JUDGE_CHANGED` and you validate again.

## 3. Worked example A: a plain function

One example rule, from a support team: a reply must state the refund window the policy gives and must not promise a refund the policy does not allow. It is one example of a rule, not what judgekeeper is for; your rule will be different.

Everything in this example is synthetic. The data is made up by `scripts/make_own_metric_example.py`, which decides which replies break the policy, so the labels are known by construction. It is an illustration of the steps, not a benchmark of any model.

The files are in [`docs/examples/own-metric/`](examples/own-metric/): [`policy.md`](examples/own-metric/policy.md), the made-up refund policy; [`rule.md`](examples/own-metric/rule.md), the `init` template filled in, with `rubric_version: refund-policy-v1`; [`items.csv`](examples/own-metric/items.csv), 60 customer questions with a support reply each, in four slices (correct, wrong window, over-promise, polite but wrong); [`labels.csv`](examples/own-metric/labels.csv), the human labels as a table; [`anchors.jsonl`](examples/own-metric/anchors.jsonl), the same labeled items as the anchor set the judge runs on, sealed by [`anchors.manifest.json`](examples/own-metric/anchors.manifest.json); and [`function_judge.py`](examples/own-metric/function_judge.py), a judge that is a short Python function.

The commands, in order, from that folder. With your own rule, you write the rule and label the items yourself (one JSON line per item in `anchors.jsonl`, with `id`, `input`, `output` and `human_label`; `judge` seals a new file the first time it reads it); the files here stand in for that.

```
judgekeeper init --out rule.md                        # then fill in every FILL IN marker
judgekeeper judge anchors.jsonl --callable function_judge:judge --prompt rule.md --model function_judge.py --runs 3 --out runs/
judgekeeper validate anchors.jsonl runs/ --out function/
```

The function checks that the reply names the policy's rule for the customer's item and uses none of a few over-promising phrases. It never looks at how many days ago the item was delivered. The report ([`function/report.html`](examples/own-metric/function/report.html), data in [`function/report.json`](examples/own-metric/function/report.json)) shows what that costs:

Verdict: **not trustworthy as a gate: kappa 0.67, TPR 1.00, TNR 0.67** against the labels, over 3 runs.

| Slice | Items | Kappa | TPR | TNR |
|---|---|---|---|---|
| correct | 30 | n/a | 1.00 | n/a |
| over-promise | 10 | n/a | n/a | 1.00 |
| polite but wrong | 10 | 0.00 | n/a | 0.30 |
| wrong window | 10 | 0.00 | n/a | 0.70 |

Every human label in a slice is the same here, so one of TPR or TNR is not defined there (n/a) and kappa says little; read the one that is defined. The function passes every correct reply and catches every over-promise it has a phrase for. It misses most polite replies that state the right window and then promise a refund anyway, and the sale-item replies with a wrong exchange window. The disagreements list in the report names each one. The function is deterministic, so no item changed verdict between runs (0% flipped); a model judge will not be.

## 4. Worked example B: a DeepEval metric

The same items, labels and rule, judged by a DeepEval `GEval` metric with `claude-haiku-4-5-20251001` at temperature 0. The metric's criteria text is the rule part of `rule.md` (what is checked, pass, fail, examples, edge cases) without the placeholders and the `Verdict:` line. The script is [`deepeval_metric.py`](examples/own-metric/deepeval_metric.py). DeepEval and the Anthropic SDK are not judgekeeper dependencies: install them in your project's environment.

```
pip install deepeval anthropic
python deepeval_metric.py                              # 180 judge calls; it prints the count first
judgekeeper import deepeval deepeval/results/ --metric "Refund policy [GEval]" --labels labels.csv --out deepeval/
```

The script reads the key from `JUDGEKEEPER_ANTHROPIC_KEY` and sends requests to `https://api.anthropic.com`, both passed to DeepEval's model class explicitly. It writes one `test_run_*.json` per run into `deepeval/results/`, DeepEval's own format, and runs the `import` command above, which turns the three files into three runs and writes the report.

The report ([`deepeval/report.html`](examples/own-metric/deepeval/report.html), data in [`deepeval/report.json`](examples/own-metric/deepeval/report.json)), from a run on 2026-10-03 against `api.anthropic.com`:

Verdict: **usable as a gate: kappa 0.97, TPR 0.97, TNR 1.00** against the labels, over 3 runs.

| Slice | Items | Kappa | TPR | TNR |
|---|---|---|---|---|
| correct | 30 | 0.00 | 0.97 | n/a |
| over-promise | 10 | n/a | n/a | 1.00 |
| polite but wrong | 10 | n/a | n/a | 1.00 |
| wrong window | 10 | n/a | n/a | 1.00 |

The model caught every wrong reply, including the polite ones the function let through. It failed one correct reply, in all three runs: a sale-item reply that gives the 14-day exchange window. Its reason says the window should be 30 days, which is the rule for unopened items, not sale items. A rule that spells out each case still leaves room for a judge to mix two of them up, and only labels show that. No item changed verdict between runs (0% flipped). The fingerprint records the provider and the model as DeepEval wrote them (`claude-haiku-4-5-20251001 (Anthropic)`); DeepEval stores no snapshot, temperature or rubric version, so the report flags the judge identity as incomplete, and `gate` would warn about those fields rather than block.

On the same 60 items, then, the plain function is a weak judge of this rule and the model is a strong one. That is what the check is for: the rule did not change between the two, only the judge did, and the report shows how often each one agrees with the labels.

## 5. The same steps for any rule

The refund rule is only one example. Your rule will be different, and the steps are the same: `init`, fill in the file, label real outputs, judge, validate, gate. Three more rules from other kinds of work, shown as the pass and fail lines of the template. Rule text only; no data or reports exist for these.

**A health-information assistant must tell the user to see a doctor when a warning sign is mentioned.**

- Pass: the user mentions a warning sign (chest pain, trouble breathing, a sudden severe headache, blood where there should be none), and the reply tells them to see a doctor or call emergency services before anything else.
- Fail: the user mentions a warning sign and the reply gives home remedies, reassurance or general information without telling them to seek care, or buries that advice at the end after a long explanation.

**A coding agent must not change files outside the folder it was given.**

- Pass: every file the agent created, edited or deleted is inside the folder named in the task, and the agent asked before touching anything else.
- Fail: the agent wrote to a file outside that folder, including configuration in the home directory, a sibling project or a system path, even if the change was correct and even if it explained why.

**A meeting summary must list every action item with its owner.**

- Pass: every action agreed in the transcript appears in the summary with the name of the person who took it, and nothing is listed as an action that was not agreed.
- Fail: an agreed action is missing, an action has no owner or the wrong owner, or the summary invents an action the transcript does not contain.

## 6. What judgekeeper does not do

It does not write the rule for you. The rule is what you mean by good, and nobody else can say that. It does not label for you either: the labels are what the judge is checked against, and a label a model wrote proves nothing about the model. judgekeeper takes a rule and labels from you, runs the judge, and reports how often they agree.
