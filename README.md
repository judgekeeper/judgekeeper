<div align="center">
  <img src="https://raw.githubusercontent.com/judgekeeper/judgekeeper/main/docs/assets/logo.png" alt="judgekeeper logo" width="80">
  <h1>judgekeeper</h1>
  <p><strong>Check your LLM-as-a-judge in 5 steps.</strong><br>Find. Mark. Measure. Fix. Re-check.</p>
  <p>
    <a href="https://pypi.org/project/judgekeeper/"><img src="https://img.shields.io/pypi/v/judgekeeper" alt="PyPI version"></a>
    <a href="https://github.com/judgekeeper/judgekeeper/actions/workflows/ci.yml"><img src="https://github.com/judgekeeper/judgekeeper/actions/workflows/ci.yml/badge.svg?branch=main" alt="Tests"></a>
    <a href="https://github.com/judgekeeper/judgekeeper/blob/main/LICENSE"><img src="https://img.shields.io/github/license/judgekeeper/judgekeeper" alt="MIT license"></a>
  </p>
  <p>
    <a href="https://www.judgekeeper.com">Website</a> ·
    <a href="https://www.judgekeeper.com/start.html">Guide</a> ·
    <a href="https://github.com/judgekeeper/judgekeeper/blob/main/docs/reference.md">Reference</a> ·
    <a href="https://github.com/judgekeeper/judgekeeper/blob/main/CHANGELOG.md">Changelog</a>
  </p>
</div>

An LLM-as-a-judge is an AI model that grades the answers of another AI model. judgekeeper shows how often your LLM-as-a-judge agrees with you, and where it goes wrong.

![judgekeeper finds the results, opens the marking page, and shows how often the LLM-as-a-judge agrees with you.](https://raw.githubusercontent.com/judgekeeper/judgekeeper/main/docs/assets/demo.webp)

## Install

In your project folder, with pip:
```
pip install judgekeeper
```
Then run:
```
judgekeeper
```
Or with [uv](https://docs.astral.sh/uv/):
```
uvx judgekeeper
```
Works with Python 3.11 to 3.14, and with promptfoo, DeepEval, Inspect AI, MLflow or your own file (such as a CSV, TSV or JSONL file). With uv, type `uvx judgekeeper` wherever this page says `judgekeeper`.

## The 5 steps

1. **Find** (`judgekeeper`). Find your eval results and the LLM-as-a-judge that graded them.
2. **Mark** (the page opens by itself). Mark your answers Pass or Fail in your browser.
3. **Measure** (`judgekeeper` again). See how often your LLM-as-a-judge agrees with you. A result needs at least 15 answers you mark Pass and 15 you mark Fail. If almost every answer passes, that can take many answers.
4. **Fix** (`judgekeeper fix`). Write a better rule and test it on marks kept aside.
5. **Re-check** (`judgekeeper check`). Change your LLM-as-a-judge and see if it still agrees with you.

`fix` keeps half your marks aside, so a new rule is tested on answers it wasn't written from. Change your rule in your eval tool, grade `.judgekeeper/fix/marked-answers.csv` again, then run `judgekeeper fix <new results file>`. A rule that fixes about a quarter of its mistakes needs about 80 marks for a clear answer, and usually reads "safe to try" ([simulation](https://github.com/judgekeeper/judgekeeper/blob/main/docs/examples/kept-aside/report.md)).

judgekeeper only reads files. It never runs your eval tool, makes no AI call and needs no API key. When you grade answers again, your eval tool does it with your own key. Details are in [SECURITY.md](https://github.com/judgekeeper/judgekeeper/blob/main/SECURITY.md).

## What the numbers mean

- **TPR:** of the answers you passed, how many your LLM-as-a-judge passed too.
- **TNR:** of the answers you failed, how many it failed too.
- **Kappa:** how much you agree beyond what agreeing at random would give. It is in the report's details and never decides the result.

Each number comes with a range, for example "about 90% (between 84% and 93%)". The result says "good enough to use" only when the low end of both the TPR and TNR range is at least 80%. The numbers come from the answers you marked. They are not a promise about the next ones.

## Checked on public data

- **JailbreakBench.** GPT-4 graded 300 answers that three experts also marked. In 100 tests with 100 marks each, judgekeeper's ranges held the true TPR in 99, the true TNR in 94 and the true kappa in 100; all three at once in 93. [Report](https://github.com/judgekeeper/judgekeeper/blob/main/docs/examples/jailbreakbench/report.md)
- **RAGTruth.** Two models graded 200 news summaries with one rule. Both failed about one in three of the summaries people passed, and judgekeeper said "needs work" in all 6 runs. RAGTruth's people labeled with a different rule from the one the LLM-as-a-judge was given, so part of the disagreement is the rule, not the LLM-as-a-judge. [Report](https://github.com/judgekeeper/judgekeeper/blob/main/docs/examples/ragtruth/report.md)
- **Empty answers.** In a test we ran with promptfoo, two models graded empty summaries, which should fail. With one rule, one model failed 0 of 20 and the other failed 14 of 20. Marks on real answers don't show this. [Report](https://github.com/judgekeeper/judgekeeper/blob/main/docs/examples/probes/report.md)
- **Simulation.** In made-up checks, the ranges held the true value 96.2 times in 100 on average, and never fewer than 92.6. [Coverage check](https://github.com/judgekeeper/judgekeeper/blob/main/docs/examples/coverage/coverage.md)

## More

The website, [www.judgekeeper.com](https://www.judgekeeper.com), has a [guide](https://www.judgekeeper.com/start.html) that walks through the 5 steps. `judgekeeper --help` lists every command. The [reference](https://github.com/judgekeeper/judgekeeper/blob/main/docs/reference.md) explains each one, and the [changelog](https://github.com/judgekeeper/judgekeeper/blob/main/CHANGELOG.md) says what changed. The tests run on Linux, Windows and macOS. judgekeeper is made by one person and takes [issues](https://github.com/judgekeeper/judgekeeper/issues/new/choose), not pull requests.

## License

MIT, for the code. The name judgekeeper and the logo are not covered: see [TRADEMARKS.md](https://github.com/judgekeeper/judgekeeper/blob/main/TRADEMARKS.md).
