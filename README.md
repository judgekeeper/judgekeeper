<p align="center"><img src="https://raw.githubusercontent.com/judgekeeper/judgekeeper/main/docs/assets/logo.png" alt="judgekeeper logo" width="96"></p>

# judgekeeper

[![PyPI version](https://img.shields.io/pypi/v/judgekeeper)](https://pypi.org/project/judgekeeper/) [![Tests](https://github.com/judgekeeper/judgekeeper/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/judgekeeper/judgekeeper/actions/workflows/ci.yml) [![MIT license](https://img.shields.io/github/license/judgekeeper/judgekeeper)](https://github.com/judgekeeper/judgekeeper/blob/main/LICENSE)

**Check your LLM-as-a-judge in 5 steps.**\
Find. Mark. Measure. Fix. Re-check.

An LLM-as-a-judge is an AI model that grades the answers of another AI model. judgekeeper shows how often your LLM-as-a-judge agrees with you, and where it goes wrong.

![judgekeeper finds the results, opens the marking page, and shows how often the LLM-as-a-judge agrees with you.](https://raw.githubusercontent.com/judgekeeper/judgekeeper/main/docs/assets/demo.webp)

## Install

In your project folder, with pip:
```
pip install judgekeeper
```
```
judgekeeper
```
Or with [uv](https://docs.astral.sh/uv/):
```
uvx judgekeeper
```
Works with Python 3.11 to 3.14, and with promptfoo, DeepEval, Inspect AI, MLflow or your own file. With uv, type `uvx judgekeeper` wherever this page says `judgekeeper`.

## The 5 steps

1. **Find** (`judgekeeper`). Find your eval results and the LLM-as-a-judge that graded them.
2. **Mark** (the page opens by itself). Mark your answers Pass or Fail in your browser.
3. **Measure** (`judgekeeper` again). See how often your LLM-as-a-judge agrees with you.
4. **Fix** (`judgekeeper fix`). Write a better rule and test it on marks kept aside.
5. **Re-check** (`judgekeeper check`). Change your LLM-as-a-judge and see if it still agrees with you.

Marks kept aside are marks that `fix` doesn't show you, so a new rule is tested on answers it wasn't written from. Testing a rule works with promptfoo, DeepEval, Inspect AI and MLflow.

Finding, marking and the result need no API key and make no AI call. Fix and Re-check run your eval tool to grade answers again, and ask before any AI call. Details are in [SECURITY.md](https://github.com/judgekeeper/judgekeeper/blob/main/SECURITY.md).

## What the numbers mean

- **TPR:** of the answers you passed, how many your LLM-as-a-judge passed too.
- **TNR:** of the answers you failed, how many it failed too.
- **Kappa:** how much you agree beyond coincidence. It is in the report's details and never decides the result.

Each number comes with a range, for example "about 89% (between 84% and 93%)". The result says "good enough to use" only when the low end of both the TPR and TNR range is at least 80%. The numbers come from the answers you marked. They are not a promise about the next ones.

## Checked on public data

- **JailbreakBench.** GPT-4 graded 300 answers, and three experts marked them. In 20 of 20 draws, judgekeeper's ranges held the real TPR, TNR and kappa. Each draw marks 250 of the same 300 answers, so the draws overlap a lot. One separate draw missed the real TNR; the report says why. [Report](https://github.com/judgekeeper/judgekeeper/blob/main/docs/examples/jailbreakbench/report.md)
- **RAGTruth.** Two models graded 200 news summaries with one rule. Both failed about one in three of the summaries people passed, and judgekeeper said "needs work" in all 6 runs. [Report](https://github.com/judgekeeper/judgekeeper/blob/main/docs/examples/ragtruth/report.md)
- **Empty answers.** An empty summary should fail. With one rule, one model failed 0 of 20 empty summaries and another failed 14 of 20. Marks on real answers don't show this. [Report](https://github.com/judgekeeper/judgekeeper/blob/main/docs/examples/probes/report.md)
- **Simulation.** In simulated checks, the TPR and TNR ranges held the true value at least 92.6 times in 100 in every setting tested, and 96.2 times on average in the main test grid. [Coverage check](https://github.com/judgekeeper/judgekeeper/blob/main/docs/examples/coverage/coverage.md)

## More

The website, [www.judgekeeper.com](https://www.judgekeeper.com), has a [guide](https://www.judgekeeper.com/start.html) that walks through the 5 steps. `judgekeeper --help` lists every command. The [reference](https://github.com/judgekeeper/judgekeeper/blob/main/docs/reference.md) explains each one, and the [changelog](https://github.com/judgekeeper/judgekeeper/blob/main/CHANGELOG.md) says what changed. The tests run on Linux with Python 3.11 to 3.14, and on Windows and macOS. judgekeeper is made by one person and takes [issues](https://github.com/judgekeeper/judgekeeper/issues/new/choose), not pull requests.

## License

MIT, for the code. The name judgekeeper and the logo are not covered: see [TRADEMARKS.md](https://github.com/judgekeeper/judgekeeper/blob/main/TRADEMARKS.md).
