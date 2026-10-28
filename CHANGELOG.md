# Changelog

## 1.0.0 (YYYY-MM-DD)

The 5 steps: Find. Mark. Measure. Fix. Re-check. In your project folder, in its virtual environment, run `pip install judgekeeper`, then `judgekeeper`; or run `uvx judgekeeper`, which needs no virtual environment.

- `judgekeeper` finds your eval results and their LLM-as-a-judge: promptfoo, DeepEval, Inspect AI, MLflow, a CSV or JSONL file, or `judgekeeper.record()`.
- You mark answers Pass or Fail in your browser, with the grade hidden. The page accepts marks only from itself, so other websites can't send marks. A program already running on your computer could, just as it can edit your files.
- Then see how often your LLM-as-a-judge agrees with you: TPR and TNR with ranges, and kappa.
- `judgekeeper mark` marks more answers.
- `judgekeeper fix` shows where your LLM-as-a-judge goes wrong and keeps half your marks aside. Grade the marked answers again with your new rule in your eval tool, then `judgekeeper fix <new results file>` tests it on the marks kept aside.
- `judgekeeper check` re-checks it on your marks, from your new results, when something changes: its model, rule, grading prompt, pass mark or temperature, your eval tool's version, and more (the reference lists them all).
- `fix` and `check` find the answers you marked by their text and question. An answer kept aside that a new rule leaves ungraded counts as its mistake.
- judgekeeper only reads files. It never runs your eval tool, makes no AI call and needs no API key.
- It hides keys in what it prints and writes: the key variables in your shell, your project's `.env` and `.env.*` files and promptfoo's `env:` block, and anything shaped like a key.
- Very large Inspect AI logs and MLflow stores are refused with the limit named; the reference lists the limits.
- Removed since 0.1.3: every 0.1 command, the built-in runners that called an AI, the pytest plugin, the GitHub Action and the agent skill.

## 1.0.0b1 (2026-10-12)

First beta of the new judgekeeper: one command, `judgekeeper`, does the next step each time you
run it. Fixing your judge and re-checking it on its own come in later betas.

- Run `uvx judgekeeper@1.0.0b1` in your project, or `pip install judgekeeper==1.0.0b1` and then
  `judgekeeper`. The version is needed: uv and pip skip betas unless you name one.
- It finds the results your eval tool saved and checks your judge's verdicts, with no AI call.
- It opens a page in your browser to mark answers Pass or Fail, with your judge's verdict hidden.
- Run it again for TPR, TNR and kappa with ranges, and the smallest drop your marks can see.
- `judgekeeper mark` opens the page to mark more; `judgekeeper --stop` closes it.
- A coding agent reads `skills/judgekeeper/SKILL.md`: it runs `judgekeeper`, and only you mark.
- Removed: `init`, `freeze`, `judge`, `validate`, `baseline`, `gate`, `migrate`, `check`,
  `template`, `import-labels`, `label`, `import`, `export`, `attribute` and `demo`, the pytest
  plugin and the GitHub Action.

## 0.1.3 (2026-10-04)

- New headline: "Check your LLM-as-a-judge." with "See how often it agrees with human labels, in
  one command." The old line promised more than a comparison with labels can.
- The README shows the logo.
- The Windows test job runs on demand instead of on every push.
- More search keywords, including both spellings: llm-as-a-judge and llm-as-judge.
- No change to any command, flag, metric, report field or printed result.

## 0.1.2 (2026-10-04)

A simple front door. Your AI judge grades your app. judgekeeper grades the judge.

- New message in the README, on the home page, in the package description and at the top of
  `judgekeeper --help`.
- The README is one screen: try it, use it on your own judge, what you get, and where to go
  when you need more.
- A guide page, `docs/guide.md`, holds everything that left the README, in the order you are
  likely to need it. The text and every figure are unchanged.
- `judgekeeper --help` shows three commands first (`demo`, `check`, `label`) and the other
  twelve in three groups.
- `demo`, `check`, `validate` and `import` print the result as a plain sentence before the
  numbers, for example "Of the answers people passed, the judge passed 97%. Of the answers
  people failed, the judge failed 86%. It is usable with care." The sentence is printed only;
  it is not written to `report.json` or `report.html`.
- Three worked examples from three fields, with answers by a real model and two recorded
  judges each: `judgekeeper demo support`, `judgekeeper demo coding` and
  `judgekeeper demo health` replay them with no key and write the example's files next to
  the report, so you can try `check` and `label` on them.
- `demo` prints the report's flags, as `check` already did.
- `label` prints its link at once when started in the background, and no longer names a
  labels file when nothing was labeled.
- A path for coding assistants: a prompt to paste (`docs/assistant-prompt.md`), the page that
  explains it (`docs/assistant.md`) and an updated skill file.
- Security hardening: labeling sheets guard the id column against spreadsheet formulas, as
  they already did every other cell; the credential scrubber no longer slows to a crawl on
  long dotted text; one silent connection can no longer freeze the `label` page; the
  Anthropic and OpenAI runners do not follow redirects, so the key goes only to the endpoint
  you name; the judge fingerprint (the model id a gateway reports) is scrubbed of keys like
  any other text; `gate.md` and `attribution.md` escape links, images and the anchor hash;
  and text from input files is printed without terminal control characters.
- `judgekeeper --version`. `python -m judgekeeper` works where the `judgekeeper` command is not
  on the PATH.
- Plain one-line messages, with exit code 2, for a file that is not saved as UTF-8 (the usual
  result of Excel's default "CSV" option) and for an output location that cannot be written.
  Semicolon- and tab-separated tables are read as they are.
- `judge` says how many judgments were errors, and exits 1 when the judge failed on every item,
  instead of reporting success.
- The source distribution holds only the package, the README, the licence and the changelog.
- First steps for Windows: commands printed for you to paste use double quotes, output never
  fails on characters the terminal cannot show, and `--exec` keeps backslash paths. Windows is
  not yet tested as thoroughly as macOS and Linux.
- Nothing was removed or renamed: no existing command, flag, metric or report field changed.

## 0.1.1 (2026-10-03)

Bring your own metric: judgekeeper proves it works and tells you when the proof expires.

- `judgekeeper init [--out prompts/judge.md] [--pairwise] [--force]` writes a starter rule
  file with `[FILL IN: ...]` markers for the one thing checked, pass, fail, examples and edge
  cases. The templates ship in the wheel. `judge --prompt` refuses a file that still has a
  marker and names its line.
- A docs page, "Your own metric" (`docs/own-metric.md`, rendered to the website): how to write
  a rule, two worked examples on one company-style rule (a plain Python function, offline and
  reproducible; a DeepEval GEval metric judged by `claude-haiku-4-5-20251001`), and three
  short rules from other kinds of work. Reports under `docs/examples/own-metric/`.
- The DeepEval reader fills in the judge's provider when the model id leaves no doubt
  (`claude-...`, `gpt-...`); it was always unknown before.
- `import --labels` keeps a `slice` column from the labels table, as `import-labels` does, so
  an imported report has per-slice numbers.
- The README, the home page and the package description lead with the new message.

## 0.1.0 (2026-10-02)

The first release: alpha, so commands, flags and `report.json` keys may still change.

- Validate an LLM judge against a frozen human-labeled anchor set: TPR and TNR with 95%
  intervals, Cohen's kappa, the noise floor across repeated runs, AB/BA position bias, per-slice
  numbers and label-quality warnings, in `report.json` and a self-contained `report.html`.
- Judges: built-in Anthropic and OpenAI-compatible runners, your own Python function
  (`check_judge`, `--callable`), any program (`--exec`), and a replay runner for tests. Every
  judgment carries a judge fingerprint; API keys are read from environment variables only and
  scrubbed from everything judgekeeper prints or writes.
- No framework needed: `check` for a CSV or JSONL of verdicts and labels, `demo` with bundled
  synthetic data, `template` and `import-labels` for spreadsheet labels, and `label`, a local
  labeling page.
- Readers for promptfoo, DeepEval, Inspect AI, MLflow and Langfuse results, and the ScoreRecord
  import and export format.
- Keep checking: `baseline`, `gate` (PASS, FAIL, FLAKY, JUDGE_CHANGED, ANCHORS_CHANGED, never
  failing inside the noise band), a GitHub Action, a pytest plugin (also published as
  `pytest-judgekeeper`), `migrate` to compare an old and a new judge, and `attribute` to tell
  judge drift from a change in your system.
- A skill file for coding agents: `skills/judgekeeper/SKILL.md`.
- A static website in `website/`: what judgekeeper does, step by step, with an interactive
  confusion matrix, a setup guide for API keys, a hands-on tutorial and the reference.
  Published at https://www.judgekeeper.com; preview with
  `python3 -m http.server --directory website`.

Measured so far: one live run, LLMBar judged by `claude-haiku-4-5-20251001`
(`docs/examples/llmbar-haiku/`).
