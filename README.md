<p align="center"><img src="https://raw.githubusercontent.com/judgekeeper/judgekeeper/main/docs/assets/logo.png" alt="judgekeeper logo" width="96"></p>

# judgekeeper

<p><a href="https://pypi.org/project/judgekeeper/"><img src="https://img.shields.io/pypi/v/judgekeeper" alt="PyPI version"></a> <a href="https://pypi.org/project/judgekeeper/"><img src="https://img.shields.io/pypi/pyversions/judgekeeper" alt="Python 3.11 to 3.14"></a> <a href="https://github.com/judgekeeper/judgekeeper/actions/workflows/ci.yml"><img src="https://github.com/judgekeeper/judgekeeper/actions/workflows/ci.yml/badge.svg?branch=main" alt="Tests on main"></a> <a href="https://github.com/judgekeeper/judgekeeper/blob/main/LICENSE"><img src="https://img.shields.io/github/license/judgekeeper/judgekeeper" alt="MIT license"></a> <a href="https://github.com/judgekeeper/judgekeeper/blob/main/CHANGELOG.md"><img src="https://img.shields.io/pypi/status/judgekeeper" alt="Status: alpha"></a><br><a href="https://www.judgekeeper.com/">Website</a> · <a href="https://www.judgekeeper.com/start.html">Guide</a> · <a href="https://www.judgekeeper.com/docs.html">Docs</a> · <a href="https://www.judgekeeper.com/learn.html">How it works</a> · <a href="https://www.judgekeeper.com/reference.html">Reference</a> · <a href="https://pypi.org/project/judgekeeper/">PyPI</a></p>

**Check your LLM-as-a-judge.**

See how often it agrees with human labels, in one command.

An LLM-as-a-judge is an AI model that grades the answers of another AI model. Teams use one because reading every answer by hand is slow.

<p align="center"><img src="https://raw.githubusercontent.com/judgekeeper/judgekeeper/main/docs/assets/readme-label.png" width="720" alt="The marking page: a question, your app's answer, and equal Fail and Pass buttons. What your judge decided stays hidden."></p>

## Install

You need Python 3.11 or newer.
```
source .venv/bin/activate
pip install judgekeeper
judgekeeper --version
```

Run these in your project folder: judgekeeper is a tool for developers, like pytest, and goes inside your project's own Python environment. On Windows the first line is `.venv\Scripts\activate`. No `.venv` yet? Run `python3 -m venv .venv` first. With uv or Poetry: `uv add --dev judgekeeper` or `poetry add --group dev judgekeeper`, then `uv run judgekeeper start` or `poetry run judgekeeper start`. More help: [Install](https://www.judgekeeper.com/start.html#install).

## Use it on your own judge
```
cd your-project
judgekeeper start
```

It reads the results your eval tool already saved (promptfoo, DeepEval, Inspect AI, MLflow, or a CSV with input, output and verdict columns), opens a page where you mark answers Pass or Fail without seeing what the judge said, and shows how often your judge agrees with you. Then it can review the disagreements with you, have your coding agent fix your judge's rule, ask your judge again, or try your new judge on the answers you already marked. No AI calls unless you say yes. Then your own judge runs through your own tool; judgekeeper never sees your key, it only checks its name. It never runs your app. No judge yet, or want your own rule? See [Your own metric](https://www.judgekeeper.com/own-metric.html).

Already have a table with one row per answer, the judge's verdict and your own label?
```
judgekeeper check results.csv --judge verdict --human label
```

## What you get

First a plain sentence: of the answers people passed, how many the judge passed, and of the answers people failed, how many it failed. Then whether the judge is usable as a gate, with every warning, and a report you can open in a browser. A report from a real judge on a public dataset: [LLMBar judged by Claude Haiku 4.5](https://www.judgekeeper.com/examples/llmbar-haiku/report.html). The numbers are estimates from the answers you marked: how often your judge agreed with you on those answers, not a promise about the next ones.

## Numbers

- **Its ranges hold on real data.** On 5 real judges from 3 public datasets (LLMBar, MT-Bench and LLMJudge), with 50 human labels per check, the ranges for how often the judge passed answers people passed (TPR) and how often it failed answers people failed (TNR) held the value worked out from all of the dataset's human labels in 96.0 checks in 100 on average (lowest 94.6, highest 98.4), over 1,000 checks per judge. [Real-data check](https://www.judgekeeper.com/examples/real-data-check/report.md)
- **One of those checks:** GPT-4 as the judge on MT-Bench, 50 labels: TPR 0.82 (range 0.71 to 0.91), and the value from all 1,814 human labels is 0.85; TNR 0.49 (range 0.36 to 0.65), and from all labels 0.56.
- **In simulation too:** the ranges held the true value at least 93.6 times in 100 in every tested case, and 96.2 on average. [Coverage check](https://www.judgekeeper.com/examples/coverage/coverage.md)
- **A real judge, checked:** Claude Haiku 4.5 on LLMBar, 419 items: TPR 0.95, TNR 0.88, kappa (agreement after taking away lucky guesses) 0.83. [Report](https://www.judgekeeper.com/examples/llmbar-haiku/report.html)
- Tested on Python 3.11 to 3.14 on Linux, and on Windows. [Test runs](https://github.com/judgekeeper/judgekeeper/actions/workflows/ci.yml)

## When you need more

| You need | Command | Read |
|---|---|---|
| Your own rule, or judgekeeper to run the judge | `judgekeeper init` | [Your own metric](https://www.judgekeeper.com/own-metric.html) |
| A warning when the judge changes | `judgekeeper gate report.json` | [Keep checking](https://www.judgekeeper.com/learn.html#keeps) |
| To use results from an eval framework, pytest or CI | `judgekeeper import promptfoo results.json` | [Your tools](https://www.judgekeeper.com/learn.html#works) |
| A coding agent to set it up for you | none: the agent reads one file, `skills/judgekeeper/SKILL.md` | [With a coding assistant](https://www.judgekeeper.com/assistant.html) |

## Status

Alpha (0.2.0): commands and report fields may still change. The [Guide](https://www.judgekeeper.com/start.html) explains `judgekeeper start`, [How it works](https://www.judgekeeper.com/learn.html) has the background, the [reference](https://www.judgekeeper.com/reference.html) has every command and flag, and the [changelog](https://github.com/judgekeeper/judgekeeper/blob/main/CHANGELOG.md) says what changed.

## Issues

This project is maintained by one person and does not accept pull requests. Bug reports and ideas are welcome as [issues](https://github.com/judgekeeper/judgekeeper/issues).

## License

MIT, for the code. The name judgekeeper and the logo are not covered: see [TRADEMARKS.md](https://github.com/judgekeeper/judgekeeper/blob/main/TRADEMARKS.md).
