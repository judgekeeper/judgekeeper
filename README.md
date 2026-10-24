<p align="center"><img src="https://raw.githubusercontent.com/judgekeeper/judgekeeper/main/docs/assets/logo.png" alt="judgekeeper logo" width="96"></p>

# judgekeeper

<p><a href="https://pypi.org/project/judgekeeper/"><img src="https://img.shields.io/pypi/v/judgekeeper" alt="PyPI version"></a> <a href="https://pypi.org/project/judgekeeper/"><img src="https://img.shields.io/pypi/pyversions/judgekeeper" alt="Python 3.11 to 3.14"></a> <a href="https://github.com/judgekeeper/judgekeeper/actions/workflows/ci.yml"><img src="https://github.com/judgekeeper/judgekeeper/actions/workflows/ci.yml/badge.svg?branch=main" alt="Tests on main"></a> <a href="https://github.com/judgekeeper/judgekeeper/blob/main/LICENSE"><img src="https://img.shields.io/github/license/judgekeeper/judgekeeper" alt="MIT license"></a> <a href="https://github.com/judgekeeper/judgekeeper/blob/main/CHANGELOG.md"><img src="https://img.shields.io/pypi/status/judgekeeper" alt="Status: beta"></a></p>

**Check your LLM-as-a-judge in 5 steps.**

Find. Mark. Measure. Fix. Re-check.

An LLM-as-a-judge is an AI model that grades the answers of another AI model. judgekeeper shows how often your LLM-as-a-judge agrees with you, where it goes wrong, and whether a new rule does better, in your own terminal.

<p align="center"><img src="https://raw.githubusercontent.com/judgekeeper/judgekeeper/main/docs/assets/readme-label.png" width="720" alt="The marking page: a question, the answer, and equal Fail and Pass buttons. What your LLM-as-a-judge decided is kept aside."></p>

## Install
```
cd your-project
uvx judgekeeper@1.0.0b2
```

You need Python 3.11 or newer and [uv](https://docs.astral.sh/uv/). The version is in the command because uv and pip skip betas unless you name one. Without uv, install it in your project's own Python environment, then run it:
```
pip install judgekeeper==1.0.0b2
judgekeeper
```

## The 5 steps

Run it in your own terminal. Each run does the next step and ends with one `Next:` line. (With uv, type `uvx judgekeeper@1.0.0b2` where it says `judgekeeper`; judgekeeper prints its commands that way too.)

1. **Find.** `judgekeeper` reads the results your eval tool already saved, names your LLM-as-a-judge and checks its grades with no AI call. It can read results from promptfoo, DeepEval, Inspect AI, MLflow, or a CSV, TSV or JSONL file (Inspect's `.eval` logs and MLflow need an extra: `pip install "judgekeeper[inspect]"` or `pip install "judgekeeper[mlflow]"`).
2. **Mark.** It opens a page in your browser. You mark answers Pass or Fail without seeing what your LLM-as-a-judge said; `judgekeeper mark` opens it again to mark more.
3. **Measure.** Run `judgekeeper` again: it shows how often your LLM-as-a-judge agrees with you.
4. **Fix.** `judgekeeper fix` shows where your LLM-as-a-judge goes wrong. You write a new rule; it tests it on marks kept aside, asking your own LLM-as-a-judge, and says whether it is better. It asks before any AI call.
5. **Re-check.** After you change your LLM-as-a-judge or update your eval tool, run `judgekeeper check`. It re-tests your LLM-as-a-judge on your marks. When that needs AI calls, it says how many and asks first.

Finding, marking and the result make no AI call and need no API key. judgekeeper never runs your eval's code, and it writes only inside `.judgekeeper/` in your project, plus `judgekeeper.toml` when you say yes. Every command, flag and file is in the [reference](https://github.com/judgekeeper/judgekeeper/blob/main/docs/reference.md).

## What you get

TPR: of the answers you passed, how many your LLM-as-a-judge passed. TNR: of the answers you failed, how many it failed. Kappa: how much you agree beyond coincidence, on your real mix of answers (it moves with how many answers pass, so it is in the report's details and never decides the result). Each comes with a range: "about 95% (between 92% and 98%)". The numbers are estimates from the answers you marked, not a promise about the next ones.

## Numbers

- **JailbreakBench, against experts.** On 300 answers that GPT-4-0613 graded and three experts marked, judgekeeper's ranges held the real value for GPT-4 against experts in 20 of 20 draws (TPR, TNR and kappa, with 250 marks in two batches). The first draw: TPR about 89% (between 84% and 93%), TNR about 91% (between 83% and 95%). One more single draw missed the real TNR; the report says why. [Report](https://github.com/judgekeeper/judgekeeper/blob/main/docs/examples/jailbreakbench/report.md)
- **RAGTruth, two Claude models as LLM-as-a-judge.** Claude Haiku 5.5 and Claude Sonnet 5.5 graded 200 news summaries with one rule, against people's labels. Both failed most summaries people failed, TNR about 91% (between 85% and 95%) in run 1, but also about one in three good ones: TPR about 62% (between 55% and 69%) for Haiku and about 69% (between 62% and 76%) for Sonnet. judgekeeper's result: needs work. [Report](https://github.com/judgekeeper/judgekeeper/blob/main/docs/examples/ragtruth/report.md)
- **Probes: a rule can let an empty answer pass.** With the same rule, Claude Sonnet 5.5 failed 0 of 20 empty summaries (0%, range 0% to 16%), and Claude Haiku 5.5 failed 15 of 20 (75%, range 53% to 89%). Marks on real answers don't show this. [Report](https://github.com/judgekeeper/judgekeeper/blob/main/docs/examples/probes/report.md)
- **In simulation:** the ranges held the true value at least 93.6 times in 100 in every tested case, and 96.2 on average; with new answers in two or three batches, at least 93.2 and 95.8 on average. [Coverage check](https://github.com/judgekeeper/judgekeeper/blob/main/docs/examples/coverage/coverage.md)
- Tested on Python 3.11 to 3.14 on Linux, macOS and Windows. [Test runs](https://github.com/judgekeeper/judgekeeper/actions/workflows/ci.yml)

## Status

Beta (1.0.0b2): commands and report fields may still change. `judgekeeper --help` lists every flag, the [reference](https://github.com/judgekeeper/judgekeeper/blob/main/docs/reference.md) explains each one, and the [changelog](https://github.com/judgekeeper/judgekeeper/blob/main/CHANGELOG.md) says what changed.

## Issues

This project is maintained by one person and accepts issues, not pull requests. Bug reports, results it could not find, ideas and designs are welcome as [issues](https://github.com/judgekeeper/judgekeeper/issues/new/choose).

## License

MIT, for the code. The name judgekeeper and the logo are not covered: see [TRADEMARKS.md](https://github.com/judgekeeper/judgekeeper/blob/main/TRADEMARKS.md).
