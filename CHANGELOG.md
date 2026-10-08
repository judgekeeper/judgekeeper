# Changelog

## 0.2.0 (unreleased)

`judgekeeper start`: one command, in your project folder, from your eval tool's saved results
to how often your judge agrees with you. Then review where you and your judge disagree, ask
your judge again, and try your new judge on the answers you already marked. AI calls only
after you say yes, your own judge through your own tool, and key names only.

- New: `judgekeeper start`. It finds the results your eval tool already saved (promptfoo,
  DeepEval, Inspect AI, MLflow, or a CSV or JSONL file with input, output and verdict
  columns) and names your eval tool and your judge. It opens a page in your browser that
  shows one answer at a time, half from the judge's passes and half from its fails, without
  what the judge said, and you mark each one Correct or Wrong. Then it shows how often your
  judge agrees with you, corrected for that picking, in the terminal and on a page. Your
  labels and the result are saved in `.judgekeeper/` in your project, so you can stop, carry
  on, label more, and check again after your next eval run.
- The labeling and result pages use the whole screen: a side panel with your progress, your
  judge's rule and the keys; a result coloured by what it means.
- `judgekeeper start` never runs your app. Finding, labeling, the result and the review make
  no AI calls and need no API key. When there are too few answers, it prints the command that
  makes more with your own tool, and you run it.
- After a result, `start` shows a short menu: review the disagreements, ask your judge again,
  label more, or nothing. When your newest results hold a new version of your judge, it also
  offers to try the new judge. `--review`, `--ask-again`, `--try-new-judge` and
  `--label-more` answer the menu without asking.
- New: review the disagreements (free, no AI call). First you look again at each answer where
  you and your judge disagree, mixed with answers you agreed on, with the judge's verdict still
  hidden. Then you see what the judge said, with its reason, and say whether the judge was
  wrong, you slipped, or the rule is unclear. The judge's mistakes go to
  `.judgekeeper/judge-mistakes.csv`, unclear cases to `rule-unclear.csv`. Your first labels
  stay the main result.
- New: ask your judge again. Your own eval tool grades the answers you labeled again, with
  your own judge: promptfoo, DeepEval, Inspect AI, MLflow, or your own command
  (`--judge-command`). Your app is not run. First a plan, with no AI call: whether this is
  exactly your judge, a close copy (and what differs) or a judge that can't be asked again
  (and why); which key it will use, by name only (judgekeeper reads the names in `.env`
  files, never their values); how many calls, and a cost range at prices dated in
  judgekeeper. AI calls only after you say yes: the question defaults to No, `--yes` never
  answers it, and without a terminal only `--allow-calls N` does. Then it shows how often the
  judge changes its verdict on the same answer and how well it agrees with you today. Saved
  in `.judgekeeper/again/`.
- New: try your new judge on your old marks. After you change your judge's rule or model and
  run your eval once, the new judge grades the answers you already marked, shown side by side
  with the old one, after the same plan and question. A judge fixed while looking at these
  answers looks better on them, so it then offers a quick check: mark 10 Correct and 10 Wrong
  new answers. The main result stays the old judge's until `judgekeeper start --new`. Saved
  in `.judgekeeper/new-judge-<date>/`.
- When promptfoo kept its results only in its own database, `start` offers, at a terminal, to
  run `promptfoo export` for you. It asks first, and never runs it without a terminal.
- When your judge saves results in a format of its own, `start` no longer tells you to run
  your eval again when that would not help. It names a file that looks like your judge's
  results, says how to turn it into a table, and prints a prompt for your coding agent that
  writes the table (`judgekeeper start --agent-prompt` prints it alone). For DeepEval it says
  that calling a metric's `measure()` directly saves nothing. A table may name the judge's
  model in a `judge_model` column, and `start` prints its first 3 rows so a wrong table shows.
- Install inside your project: the docs, the website, the README and the agent skill show
  only an install into your project's own Python environment, like pytest
  (`pip install judgekeeper` with the project's environment switched on, `uv add --dev
  judgekeeper` or `poetry add --group dev judgekeeper`). In a terminal,
  `judgekeeper --version` says when judgekeeper is installed outside a project, including
  installs made with pipx or `uv tool install`.
- `judgekeeper --version` in a terminal now says the install is ready and what to run next.
  Piped or in a script it prints `judgekeeper <version>` as before.
- `import promptfoo` warns when promptfoo's PROMPTFOO_STRIP_* settings removed the answers or
  the inputs from a results file, and stops when they removed the judge's verdicts.
- Reading results, in `start` and in `import`: a promptfoo grader set with `--grader` is no
  longer taken for promptfoo's default grader; `defaultTest.provider` counts as the grader
  when nothing else names one; the prompt hash of an llm-rubric judge comes from its grading
  prompt when every answer shows the same one, so a baseline made from promptfoo results with
  an earlier version can report `JUDGE_CHANGED` once; a warning when the saved verdicts came
  from promptfoo's cache. DeepEval: the judge's provider is read from the end of its model
  name, such as `(Anthropic)`.
- The records format (what `import records` reads) now has a version (`schema_version`, now 2)
  and keeps fields it does not know instead of stopping. New optional fields: `metadata` for
  anything else, the judge's `rule`, and, ready for agents, `trajectory` (the agent's steps),
  `outcome` (an automatic check such as unit tests) and `app_version`. New: `judgekeeper
  import records FILE --check` says what judgekeeper reads in a file and lists every problem
  with its line, and writes nothing. The format is published as a JSON Schema
  (`docs/records.schema.json`), with three example files.
- Reading results: Inspect AI keeps each sample's steps, so two agent runs that end in the
  same answer stay two answers in `start`; a score whose value is a dict is read as one judge
  per key. MLflow: an assessment on one span inside a trace is left out unless `--metric`
  names a judge that is only on spans.
- New: `judgekeeper setup`, to set any project up in one step. When your judge saves its
  results in a format of its own (a JSON, JSONL or CSV file, nested or flat), it shows what
  one line holds and how it will read it, asks only what it cannot tell (for example whether
  answers A and B each count, and which judge to check), and shows 3 answers as it reads
  them. Then one question lists every file change: `judgekeeper.toml` (where your results
  are and how to read them; `judgekeeper start` reads it first), the `.gitignore` lines and
  judgekeeper in your dev requirements. It never edits your code. The website's "Run it"
  step is now `judgekeeper setup`, then `judgekeeper start`.
- New: `judgekeeper.record()`. When your judge runs in your own code, one line right after
  it saves each verdict in `.judgekeeper/records/` (one file per process), and
  `judgekeeper start` finds them; `start --new` leaves them in place. It never stops your
  program (an error inside it only logs one warning), uses only Python's standard library,
  and `JUDGEKEEPER_RECORD=0` turns it off.
- `judgekeeper start` says when your app's version changed since your last check, from
  `app_version` in the results (or an `app_version` column in a table).
- The website's home page shows the install for Mac and Windows, with a check for Python, and
  then `judgekeeper start`. "Use it on your app" is about `judgekeeper start`; the earlier
  paths are under "Other ways".
- Removed: `judgekeeper demo`, with its bundled synthetic data. Running it now gives the usual
  "invalid choice" error. This includes `judgekeeper demo --try` (the five practice questions)
  and `judgekeeper demo support`, `coding` and `health` (the three worked examples).
- Removed: `label`, `template`, `import-labels`, `freeze`, `attribute`, `export` and the
  `record` command (the `judgekeeper.record()` function stays). Labeling is `judgekeeper
  start`; `judge` and `validate` seal a new anchor file themselves.
- Removed from the website: the "See it work" page and its menu entry, and the practice step
  with its screenshots. The home page now says what judgekeeper is, shows how to install it,
  and points to checking your own judge.
- Reads MLflow results kept in an mlruns/ folder with MLflow 3.16 and later.
- `judgekeeper start` goes on to labeling when your judge failed (or passed) only a few
  answers, and says so: that may mean it passes too much, and your labels will show it. It
  stops only when there are fewer than 30 answers, and then says how many you have and how to
  make more with your own tool, naming the config, test file or task it read. The targets
  say they are about your labels ("15 you mark Correct and 15 you mark Wrong").
- Every command `start` prints for you to run next repeats the flags you gave, so it works as
  printed. With `--no-browser` it asks "Start the labeling page? It will print a link.", and
  after No it says what to run when you're ready.
- New exit code 8: `start` and `setup` stopped at a question they cannot ask without a
  terminal. Nothing went wrong; the line before says what answers it. Exit code 2 stays for
  usage errors.
- `--review`, `--ask-again` and `--try-new-judge` before a result name the exact command that
  labels first (with `--yes` when there is no terminal) and what the flag does after.
- DeepEval: `start` reads the `test_run_*.json` files in your results folder before
  DeepEval's hidden copy of its newest run, says so when that copy holds a different run, and
  shows the DEEPEVAL_RESULTS_FOLDER tip only when no results folder is kept. A GEval judge
  built with evaluation steps and no criteria is shown by its first step, never "None".
- MLflow: `start` keeps MLflow's own log lines out of what it says. With both `mlflow.db` and
  an `mlruns/` folder, it names both and lets you choose (at a terminal, or with the store's
  path, `--tracking-uri`, `--experiment` or `MLFLOW_TRACKING_URI`). `judgekeeper start
  mlruns` reads that store. An `mlruns/` folder copied from another computer is read from its
  own folder. An unknown `--experiment` names each store searched and its experiments.
- `judgekeeper setup` reads a pass mark and a judge's model that your file states, for each
  answer or for the whole run, and says where they came from; it lists every criterion as a
  judge; at a terminal it asks whether its guess is right, and after No you correct only the
  part that is wrong.
- `import records --check` shows each judge's pass mark, model and ids, and how `start`
  reads several record files of one judge.
- The agent skill follows `judgekeeper start`: find, set up, the person labels, the result,
  then review, ask again or try a new judge, where the person answers the spending question.
- Works on Windows: reading an MLflow store, and every test, now pass on Windows too.
  judgekeeper reads an `mlflow.db` store through a temporary copy (removed afterwards), so
  it never opens your store file itself; `judgekeeper setup` keeps your files' own line
  endings.
- `start` says only what can happen next: no "label more" once every saved answer is
  labeled (run your evals again for more answers), and no "ask your judge again" for a judge
  it cannot run (verdicts saved by your own code or in a table). Below a rough check (15
  Correct and 15 Wrong) the result shows no numbers, and the labeling page shows "See my
  result" only from then on. A records file is found anywhere `start` looks, not only in
  `.judgekeeper/records/`. When verdicts cannot be read, `start` stops and says what to map,
  or `--pass-if` for scores, instead of leaving those answers out.
- The labeling page: the answer box fits the answer, the buttons sit under it, and your
  judge's rule is shown open. The result page leads each number with its plain name.
- Ctrl-C at any question stops with "Stopped." (exit code 130) instead of a traceback.
- `--label-map` advice never guesses which side a word is on, and `right`/`wrong` are read
  like `correct`/`incorrect` by default.
- The project does not accept pull requests. Bug reports and ideas are welcome as issues.
- No change to any metric or report field.

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
