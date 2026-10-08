<p align="center"><img src="https://raw.githubusercontent.com/judgekeeper/judgekeeper/main/docs/assets/logo.png" alt="judgekeeper logo" width="96"></p>

# judgekeeper

**Check your LLM-as-a-judge.**

See how often it agrees with human labels, in one command.

An LLM-as-a-judge is an AI model that grades the answers of another AI model. Teams use one because reading every answer by hand is slow.

## Install

```
source .venv/bin/activate
pip install judgekeeper
judgekeeper --version
```

Run these in your project folder: judgekeeper is a tool for developers, like pytest, and goes inside your project's own Python environment. On Windows the first line is `.venv\Scripts\activate`. No `.venv` yet? Run `python3 -m venv .venv` first. With uv or Poetry: `uv add --dev judgekeeper` or `poetry add --group dev judgekeeper`. More help: [Install](https://www.judgekeeper.com/start.html#install).

## Use it on your own judge

```
cd your-project
judgekeeper start
```

It reads the results your eval tool already saved (promptfoo, DeepEval, Inspect AI, MLflow, or a CSV with input, output and verdict columns), opens a page where you mark answers Correct or Wrong without seeing what the judge said, and shows how often your judge agrees with you. Then it can review the disagreements with you, ask your judge again, or try your new judge on the answers you already marked. No AI calls unless you say yes. Then your own judge runs through your own tool; judgekeeper never sees your key, it only checks its name. It never runs your app. No judge yet, or want your own rule? See [Your own metric](https://www.judgekeeper.com/own-metric.html).

Already have a table with one row per answer, the judge's verdict and your own label?

```
judgekeeper check results.csv --judge verdict --human label
```

## What you get

First a plain sentence: of the answers people passed, how many the judge passed, and of the answers people failed, how many it failed. Then whether the judge is usable as a gate, with every warning, and a report you can open in a browser. A report from a real judge on a public dataset: [LLMBar judged by Claude Haiku 4.5](https://www.judgekeeper.com/examples/llmbar-haiku/report.html).

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

MIT.
