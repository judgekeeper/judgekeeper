<p align="center"><img src="https://raw.githubusercontent.com/judgekeeper/judgekeeper/main/docs/assets/logo.png" alt="judgekeeper logo" width="96"></p>

# judgekeeper

<p><a href="https://pypi.org/project/judgekeeper/"><img src="https://img.shields.io/pypi/v/judgekeeper" alt="PyPI version"></a> <a href="https://pypi.org/project/judgekeeper/"><img src="https://img.shields.io/pypi/pyversions/judgekeeper" alt="Python 3.11 to 3.14"></a> <a href="https://github.com/judgekeeper/judgekeeper/actions/workflows/ci.yml"><img src="https://github.com/judgekeeper/judgekeeper/actions/workflows/ci.yml/badge.svg?branch=main" alt="Tests on main"></a> <a href="https://github.com/judgekeeper/judgekeeper/blob/main/LICENSE"><img src="https://img.shields.io/github/license/judgekeeper/judgekeeper" alt="MIT license"></a> <a href="https://github.com/judgekeeper/judgekeeper/blob/main/CHANGELOG.md"><img src="https://img.shields.io/pypi/status/judgekeeper" alt="Status: beta"></a></p>

**Check your LLM-as-a-judge.**

See how often it agrees with human labels, in one command.

An LLM-as-a-judge is an AI model that grades the answers of another AI model. Teams use one because reading every answer by hand is slow.

<p align="center"><img src="https://raw.githubusercontent.com/judgekeeper/judgekeeper/main/docs/assets/readme-label.png" width="720" alt="The marking page: a question, your app's answer, and equal Fail and Pass buttons. What your judge decided stays hidden."></p>

## Use it on your own judge
```
cd your-project
uvx judgekeeper@1.0.0b2
```

You need Python 3.11 or newer and [uv](https://docs.astral.sh/uv/). The version is in the command because uv and pip skip betas unless you name one. Without uv, install it in your project's own Python environment, then run it:
```
pip install judgekeeper==1.0.0b2
judgekeeper
```

- It reads the results your eval tool already saved (promptfoo, DeepEval, Inspect AI, MLflow, or a CSV) and checks your judge's verdicts for free.
- It opens a page in your browser. You mark answers Pass or Fail without seeing what your judge said.
- Run it again the same way when you are done: it shows how often your judge agrees with you.
- Marking and the result make no AI call and need no API key. judgekeeper never runs your app.

This is a beta: fixing your judge is coming.

## Then it keeps checking by itself

Once you have marked 25 Pass and 25 Fail, judgekeeper asks on the page whether it should keep checking your judge. Only your click turns this on. Then, when your judge's model, rule, pass mark or eval tool changes, judgekeeper re-tests it on your marks and says if it got worse.

- Turning on adds a hook for Claude Code and Cursor (in `.claude/settings.local.json`), a check before each git commit (no AI call), judgekeeper to your dev requirements when it is installed in your project, and asks your judge once about your marked answers, to learn how steady it is.
- A re-check first uses the verdicts your newest results already hold, for free. It asks your own judge only about the rest, with the key your evals already use.
- To turn it off: `uvx judgekeeper@1.0.0b2 check --off`. It takes out exactly what it added; your marks stay.
- In GitHub Actions: `uses: judgekeeper/judgekeeper@v1.0.0b2`, after the step that runs your eval. See [action.yml](https://github.com/judgekeeper/judgekeeper/blob/main/action.yml).

## What you get

TPR: of the answers you passed, how many your judge passed. TNR: of the answers you failed, how many it failed. Kappa: how much you agree beyond chance. Each comes with a range, and judgekeeper says the smallest drop your marks can see. The numbers are estimates from the answers you marked, not a promise about the next ones.

## Numbers

- **Its ranges hold on real data.** We tested the ranges for how often the judge passed answers people passed (TPR) and how often it failed answers people failed (TNR). We used 5 real judges from 3 public datasets (LLMBar, MT-Bench, LLMJudge), with 50 human labels per check, over 1,000 checks per judge. On average the value from all the human labels fell inside the range in 96.0 checks in 100 (lowest 94.6, highest 98.4). [Real-data check](https://github.com/judgekeeper/judgekeeper/blob/main/docs/examples/real-data-check/report.md)
- **One of those checks:** GPT-4 as the judge on MT-Bench, 50 labels: TPR 0.82 (range 0.71 to 0.91), and the value from all 1,814 human labels is 0.85; TNR 0.49 (range 0.36 to 0.65), and from all labels 0.56.
- **In simulation too:** the ranges held the true value at least 93.6 times in 100 in every tested case, and 96.2 on average. [Coverage check](https://github.com/judgekeeper/judgekeeper/blob/main/docs/examples/coverage/coverage.md)
- **A real judge, checked:** Claude Haiku 4.5 on LLMBar, 419 items: TPR 0.95, TNR 0.88, kappa (agreement after taking away lucky guesses) 0.83. [Report](https://github.com/judgekeeper/judgekeeper/tree/main/docs/examples/llmbar-haiku)
- Tested on Python 3.11 to 3.14 on Linux, and on Windows. [Test runs](https://github.com/judgekeeper/judgekeeper/actions/workflows/ci.yml)

## Status

Beta (1.0.0b2): commands and report fields may still change. `judgekeeper --help` lists every flag, and the [changelog](https://github.com/judgekeeper/judgekeeper/blob/main/CHANGELOG.md) says what changed.

## Issues

This project is maintained by one person and does not accept pull requests. Bug reports and ideas are welcome as [issues](https://github.com/judgekeeper/judgekeeper/issues).

## License

MIT, for the code. The name judgekeeper and the logo are not covered: see [TRADEMARKS.md](https://github.com/judgekeeper/judgekeeper/blob/main/TRADEMARKS.md).
