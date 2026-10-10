---
name: judgekeeper
description: Check whether a project's LLM-as-judge agrees with human labels (TPR, TNR, kappa, run-to-run noise, position bias) using judgekeeper, and gate CI on it. Use when a project grades outputs with an LLM judge, eval framework or rubric model and the user asks if the judge can be trusted, wants human labels, or wants a judge check in CI.
---

# judgekeeper: check an LLM judge against human labels

judgekeeper checks the project's LLM-as-a-judge: how often it agrees with the person's own
labels. It reads the verdicts the judge already saved; the person labels some of the same
answers; it reports how often the judge agrees. You do the typing; the person does the
labeling. They may write little code, so say what you are doing in plain words. Full flags:
`judgekeeper <command> --help` or `docs/reference.md`.

## Rules

- Never invent, guess or generate human labels, and never let a model fill one in, not even
  as a draft. The labels are the only part of the check that is not a model's opinion: the
  person does the labeling, and you never label.
- API keys come only from environment variables (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`,
  `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, or the variable named with `--api-key-env`).
  Never write a key into a file, a command line, a config, a commit or the chat.
- Report TPR, TNR and kappa together. Never report raw agreement on its own.
- Judge calls cost money; labeling and the result make none. Ask before spending.
- Stop and ask whenever a step needs the human: labels, a key, money, what the rule means,
  and any change to their code: add a `judgekeeper.record()` line only after their yes on the diff.
- Labeling needs the person, and so does a review: start the page for them (step 2), never
  label yourself. Run `--review` only with them. Never answer a spending question or pass
  `--allow-calls`: for `--ask-again` and `--try-new-judge`, the person answers
  `Go ahead? [y/N]` themselves.

## Install

Install it into the project's own environment, never for the whole computer: with the
project's virtual environment active, `pip install judgekeeper` (or `uv add --dev judgekeeper`,
`poetry add --group dev judgekeeper`). Then `judgekeeper --version` confirms it runs.

## 1. See what judgekeeper finds

Run `judgekeeper start` in the project folder and tell the person what it found: the eval
tool (promptfoo, DeepEval, Inspect AI, MLflow, a table), the judge, and how many answers it
graded. Without a terminal it never asks: it stops and prints the flag that answers its
question (`--metric`, `--tool`, `--experiment`). If it found several tools, judges or MLflow
stores, ask the person which one.

The judge saves its results its own way, so `judgekeeper start` finds nothing? Three doors, in this order:
(1) `judgekeeper setup` maps the file with no code change (the person answers its few questions and the one yes);
(2) one `judgekeeper.record()` line where the judge runs (www.judgekeeper.com/assistant.html#add-the-record-line has the prompt that adds it; show the diff, wait for the yes; after one eval run, `judgekeeper import records .judgekeeper/records --check` shows what it saved);
(3) a table written by a converter (`judgekeeper start --agent-prompt`), checked with `judgekeeper start <table>`.

If the project has no judge at all, say so and stop. If it has no rule file (nothing says
what pass and fail mean), offer `judgekeeper init`: it writes `prompts/judge.md` with
`[FILL IN: ...]` markers, and the person decides the answers.

## 2. The person decides what pass means, then labels

Ask the human to say in one sentence what pass means before they label: the labels must
follow the human's rule, not the judge's.

Then start the labeling page for them: `judgekeeper start --yes --no-browser`. It is a
local page (127.0.0.1); the command keeps running and prints a link that includes a token.
The page opens only with that full link, and the link changes each time the command starts.
So ask them to run `judgekeeper start` in their own terminal, or start it in the background
and give them the exact link it printed. Keys: ← Fail, → Pass, S skip, U undo.

Stop. Tell the person to mark the answers and to come back when done. Do not continue
without their marks (labeling needs the person).

## 3. Tell the result in plain words

- First the two plain sentences judgekeeper prints ("When you said Pass, your judge also
  said Pass 83% of the time.", and the same for Fail), then its one coloured line.
- TPR: of the answers people passed, how many the judge passed.
- TNR: of the answers people failed, how many the judge failed. A judge that passes
  everything has TPR 1.0 and TNR 0.0.
- Kappa: agreement with the person beyond chance (1 perfect, 0 chance).
- Each flag, in plain words, and the ranges. Point them to `.judgekeeper/result.html`.
- Quote the numbers judgekeeper printed. Do not round them into a different claim.

## 4. What next: the person chooses

- Review the disagreements with them: `judgekeeper start --review` (free; they do the marking).
- Ask the judge again on the labeled answers, to see how steady it is: `judgekeeper start --ask-again`.
- After they change their judge, try the new one on the same labels: `judgekeeper start --try-new-judge`.

The last two make judge calls. judgekeeper shows the plan (calls, a cost range, the key's
name), and the person answers `Go ahead? [y/N]` themselves: never pass `--allow-calls`.

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

Advanced, only if the person asks: the older commands (judge, validate, check, import) build
the same check by hand when nothing was saved; www.judgekeeper.com/tutorial.html shows each
one.
