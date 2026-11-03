<div align="center">
  <img src="https://raw.githubusercontent.com/judgekeeper/judgekeeper/main/docs/assets/logo.png" alt="judgekeeper logo" width="80">
  <h1>judgekeeper <sup><sup><sub>™</sub></sup></sup></h1>
  <p><strong>Check your LLM-as-a-judge in 5 steps.</strong><br>Find. Mark. Measure. Fix. Re-check.</p>
  <p>
    <a href="https://pypi.org/project/judgekeeper/"><img src="https://img.shields.io/pypi/v/judgekeeper" alt="PyPI version"></a>
    <a href="https://github.com/judgekeeper/judgekeeper/actions/workflows/ci.yml"><img src="https://github.com/judgekeeper/judgekeeper/actions/workflows/ci.yml/badge.svg?branch=main" alt="Tests"></a>
    <a href="https://github.com/judgekeeper/judgekeeper/blob/main/LICENSE"><img src="https://img.shields.io/github/license/judgekeeper/judgekeeper" alt="Apache-2.0 license"></a>
  </p>
  <p>
    <a href="https://www.judgekeeper.com">Website</a> ·
    <a href="https://www.judgekeeper.com/start.html">Guide</a> ·
    <a href="https://github.com/judgekeeper/judgekeeper/blob/main/docs/reference.md">Reference</a> ·
    <a href="https://github.com/judgekeeper/judgekeeper/blob/main/CHANGELOG.md">Changelog</a>
  </p>
</div>

An LLM-as-a-judge is an AI model that grades another model's answers. judgekeeper shows how often your LLM-as-a-judge agrees with you, and where it goes wrong.

![judgekeeper finds the results, opens the marking page, and shows how often the LLM-as-a-judge agrees with you.](https://raw.githubusercontent.com/judgekeeper/judgekeeper/main/docs/assets/demo.webp)

## Install

In your project folder, in its virtual environment:
```
pip install judgekeeper
judgekeeper
```
In a uv virtual environment, install it with `uv pip install judgekeeper` instead.

With no virtual environment, run `uvx judgekeeper`. judgekeeper runs on Python 3.11 to 3.14.

Reads promptfoo, DeepEval, Inspect AI, MLflow, or your own CSV, TSV or JSONL file. In your own file, judgekeeper looks for three columns: `input` (the question), `output` (the answer) and `verdict` (Pass or Fail from your LLM-as-a-judge). For Inspect AI logs or MLflow: `pip install "judgekeeper[inspect]"` or `pip install "judgekeeper[mlflow]"` (with uv: `uvx --from "judgekeeper[inspect]" judgekeeper` or `uvx --from "judgekeeper[mlflow]" judgekeeper`).

Using a coding agent? Give it this page. It runs the steps and gives you the marking page link. You mark, then it explains the result. The result also notes that your marks came through a link judgekeeper printed.

## The 5 steps

1. **Find:** `judgekeeper` finds your eval results.
2. **Mark:** a page opens in your browser. Mark answers Pass or Fail; the LLM-as-a-judge's grade stays hidden. "See the numbers so far" appears with your first numbers, and "See your result" once there is a result.
   - Now and then an answer you marked comes back once, to see how steady your marks are. Mark it as you see it.
   - No browser here, or a coding agent runs it? `judgekeeper --no-browser` prints the link to open instead.
   - Already have Pass/Fail labels? Run `judgekeeper --labels your-labels.csv` (or `judgekeeper --labels` for labels already in your results), then mark more if needed.
3. **Measure:** run `judgekeeper` again to see how often it agrees with you.
   - A result needs at least 15 Pass and 15 Fail marks from you. It also needs 20 marks on answers your LLM-as-a-judge passed and 20 on answers it failed (or all of them, if there are fewer).
   - If your LLM-as-a-judge gives scores, a plain `judgekeeper` asks for the pass mark again, with the one you gave as the default. With no terminal, it prints the `--pass-if` to give.
4. **Fix:** `judgekeeper fix` shows where your LLM-as-a-judge goes wrong, helps you write a better rule and tests it on marks kept aside.
   - It is a loop: change the rule, grade again, then run `judgekeeper fix <new results file>`.
   - With promptfoo, the rule to change is usually in `.judgekeeper/fix/regrade.yaml`. When `fix` can't write that file, it says how to grade again.
   - With few marks, "can't tell yet" is a normal answer.
5. **Re-check:** after you change the model or the rule, grade your marked answers again, then run `judgekeeper check <new results file>`.
   - Your marked answers are in `.judgekeeper/fix/marked-answers.csv`. With promptfoo, `fix` usually writes `.judgekeeper/fix/regrade.yaml` to grade them.
   - Grading only your marked answers is enough to compare the two. To count new marks, grade all your answers with your new LLM-as-a-judge.
   - If you switched to a new pass mark with `judgekeeper check --pass-if`, a plain `judgekeeper` and `judgekeeper mark` ask for the pass mark again, with the new one as the default.

judgekeeper only reads files. It makes no AI call and needs no API key. See [SECURITY.md](https://github.com/judgekeeper/judgekeeper/blob/main/SECURITY.md).

## The numbers

- **TPR:** of the answers you passed, how many it passed too. The result page calls it "When you say Pass, your LLM-as-a-judge also says Pass".
- **TNR:** of the answers you failed, how many it failed too. The result page calls it "When you say Fail, your LLM-as-a-judge also says Fail".
- **Kappa:** how much you agree beyond what matching at random would give; it is under "More details" on the result page and in report.html, and never decides the result (TPR and TNR do).

TPR and TNR each come with a range, such as "about 90% (between 85% and 93%)" (when you mark every answer, the numbers are exact and have no range). The result says "good enough to use" only when a wider range (99%) starts at 80% or more for both. That way you can look at the result after every mark, and a few marks that agree by coincidence can't decide it. The numbers are about the answers in your results, worked out from the ones you marked. They are not a promise about new answers.

How the numbers are worked out: [reference](https://github.com/judgekeeper/judgekeeper/blob/main/docs/reference.md#how-the-numbers-are-worked-out).

## Checked on public data

These runs use public datasets that people already labelled, made-up empty answers that should fail, and one simulation, so the true numbers are known. They test whether judgekeeper's ranges hold those numbers, and show what it says about real LLM-as-a-judge setups. Each line links its report.

- [JailbreakBench](https://github.com/judgekeeper/judgekeeper/blob/main/docs/examples/jailbreakbench/report.md): the ranges held the true values in 96 of 100 random tests with 100 marks each (TPR, TNR and kappa at once; another 100 tests give a slightly different count).
- [RAGTruth](https://github.com/judgekeeper/judgekeeper/blob/main/docs/examples/ragtruth/report.md): news summaries. Three LLM-as-a-judge setups, 3 runs each, and 3 more runs at a lower effort setting: needs work in all 12. Changing the model did not close the gap.
- RAGTruth [question answers](https://github.com/judgekeeper/judgekeeper/blob/main/docs/examples/ragtruth-qa/report.md) and [data-to-text](https://github.com/judgekeeper/judgekeeper/blob/main/docs/examples/ragtruth-data2txt/report.md): "needs work" in all 4 runs.
- [JailbreakBench graded by two other setups](https://github.com/judgekeeper/judgekeeper/blob/main/docs/examples/jailbreakbench-setups/report.md): "needs work" for both; each passed more than half of the expert-failed answers it graded (setup B could not grade 61 of 300).
- [Empty answers](https://github.com/judgekeeper/judgekeeper/blob/main/docs/examples/probes/report.md): one model failed 0 of 20 empty summaries that should fail.
- [Simulation](https://github.com/judgekeeper/judgekeeper/blob/main/docs/examples/coverage/coverage.md): the ranges held the true value 96.7 times in 100 on average.

## More

A [guide](https://www.judgekeeper.com/start.html) on the [website](https://www.judgekeeper.com) walks through the 5 steps. `judgekeeper --help` lists every command, and the [reference](https://github.com/judgekeeper/judgekeeper/blob/main/docs/reference.md) explains each one. Made by one person; [issues](https://github.com/judgekeeper/judgekeeper/issues/new/choose) welcome, pull requests are not taken.

## License

The Apache-2.0 license covers the code, not the name or logo. judgekeeper and the judgekeeper logo are trademarks of Sathvik Thota: see [TRADEMARKS.md](https://github.com/judgekeeper/judgekeeper/blob/main/TRADEMARKS.md).
