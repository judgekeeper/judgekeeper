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
Or, with no virtual environment: `uvx judgekeeper`. Python 3.11 to 3.14.
Reads promptfoo, DeepEval, Inspect AI, MLflow, or your own CSV, TSV or JSONL file. For Inspect AI logs or MLflow: `pip install "judgekeeper[inspect]"` or `pip install "judgekeeper[mlflow]"`.

Using a coding agent? Give it this page. It runs the steps and gives you the marking page link; you mark, then it explains the result.

## The 5 steps

1. **Find:** `judgekeeper` finds your eval results.
2. **Mark:** a page opens in your browser. Mark answers Pass or Fail; the LLM-as-a-judge's grade stays hidden. Already have Pass/Fail labels? Run `judgekeeper --labels your-labels.csv` (or `judgekeeper --labels` for labels already in your results), then mark more if needed.
3. **Measure:** run `judgekeeper` again to see how often it agrees with you. You need at least 15 Pass and 15 Fail marks.
4. **Fix:** `judgekeeper fix` helps you write a better rule and tests it on marks kept aside.
5. **Re-check:** after you change the model or the rule, grade your marked answers again (`.judgekeeper/fix/marked-answers.csv`). `judgekeeper check` shows if it still agrees with you.

judgekeeper only reads files. It makes no AI call and needs no API key. See [SECURITY.md](https://github.com/judgekeeper/judgekeeper/blob/main/SECURITY.md).

## The numbers

- **TPR:** of the answers you passed, how many it passed too.
- **TNR:** of the answers you failed, how many it failed too.
- **Kappa:** how much you agree beyond what matching at random would give.

TPR and TNR each come with a range, such as "about 90% (between 84% and 93%)". The result says "good enough to use" only when the low end of both TPR and TNR is at least 80%. The numbers are about the answers in your results, worked out from the ones you marked. They are not a promise about new answers.

How the numbers are worked out: [reference](https://github.com/judgekeeper/judgekeeper/blob/main/docs/reference.md#how-the-numbers-are-worked-out).

## Checked on public data

- [JailbreakBench](https://github.com/judgekeeper/judgekeeper/blob/main/docs/examples/jailbreakbench/report.md): the ranges held the true value in 93 of 100 tests (all three numbers at once).
- [RAGTruth](https://github.com/judgekeeper/judgekeeper/blob/main/docs/examples/ragtruth/report.md): three LLM-as-a-judge setups on news summaries: judgekeeper said "needs work" in all 12 runs. Changing the model did not close the gap.
- RAGTruth [question answers](https://github.com/judgekeeper/judgekeeper/blob/main/docs/examples/ragtruth-qa/report.md) and [data-to-text](https://github.com/judgekeeper/judgekeeper/blob/main/docs/examples/ragtruth-data2txt/report.md): "needs work" in all 4 runs.
- [JailbreakBench graded by two other setups](https://github.com/judgekeeper/judgekeeper/blob/main/docs/examples/jailbreakbench-setups/report.md): "needs work" for both; each passed more than half of the expert-failed answers it graded (setup B could not grade 61 of 300).
- [Empty answers](https://github.com/judgekeeper/judgekeeper/blob/main/docs/examples/probes/report.md): one model failed 0 of 20 empty summaries that should fail.
- [Simulation](https://github.com/judgekeeper/judgekeeper/blob/main/docs/examples/coverage/coverage.md): the ranges held the true value 96.2 times in 100 on average.

## More

A [guide](https://www.judgekeeper.com/start.html) on the [website](https://www.judgekeeper.com) walks through the 5 steps. `judgekeeper --help` lists every command, and the [reference](https://github.com/judgekeeper/judgekeeper/blob/main/docs/reference.md) explains each one. Made by one person; [issues](https://github.com/judgekeeper/judgekeeper/issues/new/choose) welcome, pull requests are not taken.

## License

Apache-2.0 for the code. The name and logo are not covered: see [TRADEMARKS.md](https://github.com/judgekeeper/judgekeeper/blob/main/TRADEMARKS.md).

judgekeeper and the judgekeeper logo are trademarks of Sathvik Thota. The Apache-2.0 license covers the code, not the name or logo.
