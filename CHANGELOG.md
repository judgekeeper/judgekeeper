# Changelog

## 1.0.1 (2026-10-31)
- ™ on the judgekeeper name and logo in the README, on the website and on the marking and report pages, with the trademark notice at the end of the README. The README title's ™ is shown small.
- The example model names are neutral (`my-judge-v1`, `my-judge-v2`), and the example with two LLM-as-a-judge setups on JailbreakBench is now in `docs/examples/jailbreakbench-setups/`.
- The demo is recorded again, with the new frame and the ™.
- Wording fixes in the docs and the examples, and a line for people who use a coding agent, in the README and the Guide.
- No change to what judgekeeper does.

## 1.0.0 (2026-10-30)

The 5 steps: Find. Mark. Measure. Fix. Re-check. In your project folder, in its virtual environment, run `pip install judgekeeper`, then `judgekeeper`; or run `uvx judgekeeper`, which needs no virtual environment.

- `judgekeeper` finds your eval results and their LLM-as-a-judge: promptfoo, DeepEval, Inspect AI, MLflow, a CSV, TSV or JSONL file, or `judgekeeper.record()`.
- You mark answers Pass or Fail in your browser, with the grade hidden. The page accepts marks only from itself, so other websites can't send marks. A program already running on your computer could, just as it can edit your files.
- Then see how often your LLM-as-a-judge agrees with you: TPR and TNR with ranges, and kappa.
- `judgekeeper mark` marks more answers.
- `judgekeeper fix` shows where your LLM-as-a-judge goes wrong and keeps half your marks aside. Grade the marked answers again with your new rule in your eval tool, then `judgekeeper fix <new results file>` tests it on the marks kept aside.
- `judgekeeper check` re-checks it on your marks, from your new results, when something changes: its model, rule, grading prompt, pass mark or temperature, your eval tool's version, and more (the reference lists them all).
- `fix` and `check` find the answers you marked by their text and question. An answer kept aside that a new rule leaves ungraded counts as its mistake.
- judgekeeper only reads files. It never runs your eval tool, makes no AI call and needs no API key.
- It hides keys in what it prints and writes: the key variables in your shell, your project's `.env` and `.env.*` files and promptfoo's `env:` block, and anything shaped like a key.
- Very large Inspect AI logs and MLflow stores are refused with the limit named; the reference lists the limits.
- Reading results: a table with a `score` column and no verdict column is read with `--pass-if`, or judgekeeper asks for a pass mark (exit 3), and the website's browser check says the same. A promptfoo assertion's `threshold` is its pass mark. In a file of your own format, the model field inside the judge object (`judge.grader`, ...) is offered as the model and written into every judgment's fingerprint, and a `response_time` column is not a second answer. A folder with results in two or more folders below it stops (exit 3) and names them. Long files no longer take time that grows with the square of their size. A score table reads answers that run over many lines, and a quote that never closes, or closes only on a later row, stops with its line named, in the tool and the browser check. In the browser check, plain 1 and 0 scores count no Pass or Fail until a pass mark is given.
- `fix` and `check`: a `fix/split.json` changed by hand stops `fix` (exit 2, Next: `fix --new`). `check` on the results your marks were made from says "back to the one you marked with" every time, not "Worse" from the second run on. A DeepEval GEval's rule leaves out the steps its model wrote for each answer, so a plain re-run no longer says "rule changed". A model given later with `--judge-model` is written into the marks and the history too, and a new results file with its own model column is read (`check` names a model change). "Worse" next to a group that rose says which group dropped. With a wrong MLflow scorer name, `fix` and `check` give the same next step. The README, the reference and SECURITY.md say what the code does.
- Marking page and exits: `--wait` keeps the page open until Ctrl-C (exit 130) and leaves no lock; a second run opens no new tab and says the page is already running; a plain run reuses the `--label-map` kept with your marks; keys pressed while a mark is saved act once it is saved; a save with no answer after 10 seconds says it wasn't saved; only `http://127.0.0.1:<port>` may send marks. A file judgekeeper guessed and can't read exits 2, and Ctrl-C, `--debug` and `--version` keep their exit codes when the output can't be printed.
- Removed since 0.1.3: every 0.1 command, the built-in runners that called an AI, the pytest plugin, the GitHub Action and the agent skill.
- The license is now Apache-2.0 (was MIT).

Earlier versions (0.1.0 to 1.0.0b1): see the PyPI release history.
