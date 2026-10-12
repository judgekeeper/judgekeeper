# Changelog

## 0.2.0 (2026-10-12)

`judgekeeper start`: one command from your eval tool's saved results to how often your judge agrees
with you. AI calls only after you say yes, your own judge through your own tool, and key names only.

### New

- `judgekeeper start` reads the results your eval tool saved and shows how often your judge agrees
  with your marks. See the [Guide](https://www.judgekeeper.com/start.html).
- Finding answers, marking them and the result make no AI calls and need no API key.
- `start` never runs your app. Before you mark, it checks whether your judge actually judged.
- After a result: review the disagreements, ask your judge again, or try your new judge.
- `judgekeeper start --fix` finds a better pass mark for scores and helps you change the rule.
- "Let your coding agent do it": Claude Code, Cursor or Codex writes the new rule (`--rule-file`).
- `judgekeeper setup` sets up a project whose judge saves results in a format of its own.
- `start --agent-prompt` prints a prompt for your coding agent to turn those results into a table.
- `judgekeeper.record()` saves each verdict when your judge runs in your own code.
- `start` offers to run `promptfoo export` when promptfoo kept its results only in its database.
- `judgekeeper import records FILE --check` lists every problem in a records file.
- TRADEMARKS.md: the MIT license covers the code, not the name judgekeeper or its logo.

### Changed

- A new look for the pages, made for a laptop screen. Nothing is loaded from outside.
- The pages and terminal say Pass and Fail instead of Correct and Wrong.
- Install inside your project, like pytest. `judgekeeper --version` says when judgekeeper is
  installed outside a project.
- Narrower ranges: in simulation they held the true value at least 93.6 times in 100 in every case,
  and are 27.1% narrower on average.
- Checked on 5 real judges from 3 public datasets. The ranges held the value from all human labels
  in 96.0 checks in 100 on average (lowest 94.6, highest 98.4), over 1,000 checks per judge.
- After you ask your judge again, its TPR and TNR ranges use the same method. The old bootstrap
  held the true value as rarely as 53.8 times in 100.
- Label targets: 15 of each mark for a rough check, 25 of each for a reliable result. Report fields
  changed: see the [Reference](https://www.judgekeeper.com/reference.html).
- Removed: `judgekeeper demo` (with `judgekeeper demo --try`) and the website's "See it work" page.
- Removed: `label`, `template`, `import-labels`, `freeze`, `attribute`, `export` and the `record`
  command. Marking is now part of `judgekeeper start`.
- The project does not accept pull requests. Bug reports and ideas are welcome as issues.
- No change to any metric.

### Fixed

- Works on Windows, including reading an MLflow store.
- Reads MLflow `mlruns/` folders from MLflow 3.16 and later.
- Reads more of what promptfoo, DeepEval, Inspect AI and MLflow save.
- Every command `start` prints for you to run next works as printed.
- Ctrl-C at any question stops with "Stopped." instead of a traceback.

### Security

- `start` stops when `.judgekeeper/` or anything in it is a link, instead of writing through it.
- `.judgekeeper/` gets its own `.gitignore`, so your answers stay off Git.
- Asking your judge again runs your project's own code: do it only in a project you trust.

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
(`docs/examples/llmbar-haiku/`). The live judge-migration demo has not been run yet.
