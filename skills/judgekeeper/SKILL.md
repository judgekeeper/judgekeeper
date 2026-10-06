---
name: judgekeeper
description: Check whether a project's LLM-as-judge agrees with human labels (TPR, TNR, kappa, run-to-run noise, position bias) using judgekeeper, and gate CI on it. Use when a project grades outputs with an LLM judge, eval framework or rubric model and the user asks if the judge can be trusted, wants human labels, or wants a judge check in CI.
---

# judgekeeper: check an LLM judge against human labels

judgekeeper checks the project's LLM-as-a-judge: how often it agrees with a frozen set of
human labels. You do the wiring and the typing; the human supplies the labels. The human may
write little code, so say what you are doing in plain words. Full flags:
`judgekeeper <command> --help` or `docs/reference.md`.

## Rules

- Never invent, guess or generate human labels, and never let a model fill `human_label`,
  not even as a draft. The labels are the only part of the check that is not a model's
  opinion. If there are no human labels, stop at step 2 and hand over to the human.
- API keys come only from environment variables (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`,
  `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, or the variable named with `--api-key-env`).
  Never write a key into a file, a command line, a config, a commit or the chat.
- Report TPR, TNR and kappa together. Never report raw agreement on its own.
- Count judge calls before running: items x runs (x 2 for pairwise). Ask before spending.
- Stop and ask whenever a step needs the human: labels, a key, money, what the rule means,
  and any change to their code: add a `judgekeeper.record()` line only after their yes on the diff.
- Labeling needs the person, and so does a review. Run `judgekeeper start --yes --no-browser`
  only to show what it found; then tell the person to open the page or run `judgekeeper start`.
  Run `--review` only with them. Never answer a spending question or pass `--allow-calls`: for
  `--ask-again` and `--try-new-judge`, the person answers `Go ahead? [y/N]` themselves.

## Install

Install it into the project's own environment, never for the whole computer: with the
project's virtual environment active, `pip install judgekeeper` (or `uv add --dev judgekeeper`,
`poetry add --group dev judgekeeper`). Then `judgekeeper --version` confirms it runs.

## 1. Find the judge

Search the project for how it grades outputs today:

- a judge function (a prompt that returns pass/fail, a score, or A/B);
- eval framework results: promptfoo `results.json`, DeepEval `test_run_*.json`, Inspect AI
  logs, MLflow assessments on traces, Langfuse scores;
- a CSV or JSONL that already has judge verdicts and human labels side by side.

The judge saves its results its own way, so `judgekeeper start` finds nothing? Three doors, in this order:
(1) `judgekeeper setup` maps the file with no code change (the person answers its few questions and the one yes);
(2) one `judgekeeper.record()` line where the judge runs (`judgekeeper record --agent-prompt` says how; show the diff, wait for the yes);
(3) a table written by a converter (`judgekeeper start --agent-prompt`), checked with `judgekeeper start <table>`.

Tell the user what you found and which on-ramp in step 3 fits. If the project has no rule file yet (no judge prompt that says what pass and fail mean), say so and offer `judgekeeper init` (`--pairwise` for A/B rules): it writes `prompts/judge.md` with `[FILL IN: ...]` markers for the one thing checked, pass, fail, examples and edge cases.
The rule is the human's decision: ask them, type their answers in, show them the file (`judge --prompt` refuses it until every marker is gone). See `docs/own-metric.md`. If a judge already exists, ask the human to say in one sentence what pass means before they label: the labels must follow the human's rule, not the judge's.

## 2. Get human labels (if there are none)

1. Collect 30 to 60 real items for a first look, about 100 before gating CI (input and
   output, or input, output_a and output_b for pairwise), as JSONL with an `id` per item.
   Real outputs of the app, never ones you write. Mix ordinary and hard cases; aim for no
   more lopsided than 80/20 between pass and fail.
2. Start the labeling page for the human: `judgekeeper label items.jsonl --out labels.csv`
   (local only, 127.0.0.1; keys 1/2 to label, d to defer, u to undo). It keeps running and
   prints a link that includes a token: the page opens only with that full link, and the
   link changes each time the command starts. So ask them to run it in their own terminal,
   or start it in the background and give them the exact link it printed.
3. Stop. Tell the human to label and to come back when done. Do not continue without labels.
   If they prefer a spreadsheet, `judgekeeper template items.jsonl -o labels.csv` writes
   one; they fill `human_label`.
4. Freeze the labels: `judgekeeper import-labels labels.csv -o anchors.jsonl`

## 3. Wire the right on-ramp

A table with judge verdicts and human labels:
```
judgekeeper check results.csv --judge verdict --human label --out reports/judge/
```

A judge function in Python (or a program in any language):
```
judgekeeper judge anchors.jsonl --callable mypkg.judges:my_judge --runs 3 --out runs/judge/
judgekeeper judge anchors.jsonl --exec "node judge.js" --runs 3 --out runs/judge/
judgekeeper validate anchors.jsonl runs/judge/ --out reports/judge/
```

or from Python: `judgekeeper.check_judge(my_judge, "anchors.jsonl", runs=3)`. The function
gets one item as a dict with `id`, `input` and `output` and returns True or False (if the project's judge takes something else, add a small wrapper file in the project folder).

An eval framework (human labels from the tool, or `--labels labels.csv`), or results saved in judgekeeper's records format (one JSON line per verdict; run `--check` first, it lists every problem with its line):
```
judgekeeper import records records.jsonl --check
judgekeeper import promptfoo results.json --metric helpfulness --out reports/judge/
judgekeeper import deepeval deepeval-results/ --labels labels.csv --out reports/judge/
judgekeeper import inspect logs/ --labels labels.csv --out reports/judge/
judgekeeper import mlflow --experiment my-eval --metric correctness --out reports/judge/
judgekeeper import langfuse --judge-score helpfulness --human-score helpfulness_human --from 2026-09-01 --out reports/judge/
```

Numeric scores need a rule (`--pass-if "score>=0.5"`); other spellings need
`--label-map "good=pass,bad=fail"`. judgekeeper never guesses; neither should you.

## 4. Run, read, explain

- Use three judge runs where possible (`--runs 3`, `promptfoo --repeat 3`, Inspect
  `--epochs 3`). One run leaves the noise floor unknown and the gate returns FLAKY.
- Read `reports/judge/report.json` (`headline`, `verdict.flags`) and point the user to
  `report.html`.
- Tell the human the result in this order:
  - First the plain sentence the command prints (of the answers people passed, how many the
    judge passed; of the answers people failed, how many it failed), then its verdict.
  - TPR: of the outputs humans passed, how many the judge passed.
  - TNR: of the outputs humans failed, how many the judge failed. A judge that passes
    everything has TPR 1.0 and TNR 0.0.
  - Kappa: agreement with humans beyond chance (1 perfect, 0 chance).
  - Below 0.80 TPR or TNR, or kappa below 0.6: not trustworthy as a gate. 0.80 to 0.90:
    usable with care.
  - Each flag in `verdict.flags`, in plain words: few labels, lopsided labels, noise between
    runs, position bias (pairwise AB vs BA), judge errors, unknown judge fields.
- Quote the numbers from the report. Do not round them into a different claim.

## 5. Gate CI

Only when the human asks for it. Record the baseline once and commit it:
```
judgekeeper baseline set reports/judge/report.json
judgekeeper gate reports/judge/report.json
```

`gate` returns PASS, FAIL, FLAKY, JUDGE_CHANGED or ANCHORS_CHANGED and never fails on a
change inside the noise band. Then pick one:

- The GitHub Action re-judges the anchor set and gates (key from repository secrets, via
  `env`, never an input):

  ```
  - uses: judgekeeper/judgekeeper@v0.2.0
    env:
      ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
    with:
      anchors: evals/anchors.jsonl
      runner: anthropic
      model: claude-haiku-4-5-20251001
      prompt: prompts/judge.md
  ```

- The pytest plugin gates a report your pipeline already wrote (it only reads files):
  `pytest --judgekeeper-report reports/judge/report.json`, or in a test
  `@pytest.mark.judgekeeper(report="reports/judge/report.json")` or the
  `judgekeeper_gate` fixture.

Tell the user what was added, where the report is, and what they must do by hand (label,
add the secret, commit the baseline).
