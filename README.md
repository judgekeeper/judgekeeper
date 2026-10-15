<p align="center"><img src="https://raw.githubusercontent.com/judgekeeper/judgekeeper/main/docs/assets/logo.png" alt="judgekeeper logo" width="96"></p>

# judgekeeper

<p><a href="https://pypi.org/project/judgekeeper/"><img src="https://img.shields.io/pypi/v/judgekeeper" alt="PyPI version"></a> <a href="https://pypi.org/project/judgekeeper/"><img src="https://img.shields.io/pypi/pyversions/judgekeeper" alt="Python 3.11 to 3.14"></a> <a href="https://github.com/judgekeeper/judgekeeper/actions/workflows/ci.yml"><img src="https://github.com/judgekeeper/judgekeeper/actions/workflows/ci.yml/badge.svg?branch=main" alt="Tests on main"></a> <a href="https://github.com/judgekeeper/judgekeeper/blob/main/LICENSE"><img src="https://img.shields.io/github/license/judgekeeper/judgekeeper" alt="MIT license"></a> <a href="https://github.com/judgekeeper/judgekeeper/blob/main/CHANGELOG.md"><img src="https://img.shields.io/pypi/status/judgekeeper" alt="Status: beta"></a></p>

**Check your LLM-as-a-judge in 5 steps.**

Find. Mark. Measure. Fix. Re-check.

An LLM-as-a-judge is an AI model that grades the answers of another AI model. judgekeeper shows how often your judge agrees with you, where it goes wrong, and whether a new rule does better, in your own terminal.

<p align="center"><img src="https://raw.githubusercontent.com/judgekeeper/judgekeeper/main/docs/assets/readme-label.png" width="720" alt="The marking page: a question, your app's answer, and equal Fail and Pass buttons. What your judge decided stays hidden."></p>

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

1. **Find.** `judgekeeper` reads the results your eval tool already saved, names your judge and checks its grades for free. It can read results from promptfoo, DeepEval, Inspect AI, MLflow, or a CSV or JSONL file.
2. **Mark.** It opens a page in your browser. You mark answers Pass or Fail without seeing what your judge said; `judgekeeper mark` opens it again to mark more.
3. **Measure.** Run `judgekeeper` again: it shows how often your judge agrees with you.
4. **Fix.** `judgekeeper fix` shows where your judge goes wrong. You write a new rule; it tests it on marks kept hidden, asking your own judge, and says whether it is better. It asks before any AI call.
5. **Re-check.** After you change your judge or update your eval tool, run `judgekeeper check`. It re-tests your judge on your marks. When that needs AI calls, it says how many and asks first.

Finding, marking and the result make no AI call and need no API key. judgekeeper never runs your app, and it writes only inside `.judgekeeper/` in your project. Every command, flag and file is in the [reference](https://github.com/judgekeeper/judgekeeper/blob/main/docs/reference.md).

## What you get

TPR: of the answers you passed, how many your judge passed. TNR: of the answers you failed, how many it failed. Kappa: how much you agree beyond coincidence, on your real mix of answers (it moves with how many answers pass, so it is in the report's details and never decides the result). Each comes with a range: "about 95% (could be 92% to 98%)". The numbers are estimates from the answers you marked, not a promise about the next ones.

## Numbers

- **A real judge, checked.** Claude Haiku 4.5 as the judge on the LLMBar benchmark, against 419 answers labelled by people (206 Pass, 213 Fail), run 3 times. [Report](https://github.com/judgekeeper/judgekeeper/tree/main/docs/examples/llmbar-haiku)
- When people said Pass, the judge also said Pass about 95% (could be 92% to 98%). TPR.
- When people said Fail, the judge also said Fail about 88% (could be 83% to 91%). TNR.
- Agreement beyond coincidence: kappa 0.83 (0.82 to 0.85 across the 3 runs).
- **Its ranges hold on real data.** We tested the ranges for how often the judge passed answers people passed (TPR) and how often it failed answers people failed (TNR). We used 5 real judges from 3 public datasets (LLMBar, MT-Bench, LLMJudge), with 50 human labels per check, over 1,000 checks per judge. On average the value from all the human labels fell inside the range in 96.0 checks in 100 (lowest 94.6, highest 98.4). [Real-data check](https://github.com/judgekeeper/judgekeeper/blob/main/docs/examples/real-data-check/report.md)
- **One of those checks:** GPT-4 as the judge on MT-Bench, 50 labels: TPR 0.82 (range 0.71 to 0.91), and the value from all 1,814 human labels is 0.85; TNR 0.49 (range 0.36 to 0.65), and from all labels 0.56.
- **In simulation too:** the ranges held the true value at least 93.6 times in 100 in every tested case, and 96.2 on average. [Coverage check](https://github.com/judgekeeper/judgekeeper/blob/main/docs/examples/coverage/coverage.md)
- Tested on Python 3.11 to 3.14 on Linux, and on Windows. [Test runs](https://github.com/judgekeeper/judgekeeper/actions/workflows/ci.yml)

## Status

Beta (1.0.0b2): commands and report fields may still change. `judgekeeper --help` lists every flag, the [reference](https://github.com/judgekeeper/judgekeeper/blob/main/docs/reference.md) explains each one, and the [changelog](https://github.com/judgekeeper/judgekeeper/blob/main/CHANGELOG.md) says what changed.

## Issues

This project is maintained by one person and does not accept pull requests. Bug reports and ideas are welcome as [issues](https://github.com/judgekeeper/judgekeeper/issues).

## License

MIT, for the code. The name judgekeeper and the logo are not covered: see [TRADEMARKS.md](https://github.com/judgekeeper/judgekeeper/blob/main/TRADEMARKS.md).
