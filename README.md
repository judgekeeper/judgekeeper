<div align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/judgekeeper/judgekeeper/main/docs/assets/readme-header-dark.svg">
    <img src="https://raw.githubusercontent.com/judgekeeper/judgekeeper/main/docs/assets/readme-header-light.svg" alt="judgekeeper™: Check agents and chatbots with human judgment. Read. Measure. Fix. Re-check." width="640">
  </picture>
  <p>
    <a href="https://pypi.org/project/judgekeeper/"><img src="https://img.shields.io/pypi/v/judgekeeper" alt="PyPI version"></a>
    <a href="https://github.com/judgekeeper/judgekeeper/actions/workflows/ci.yml"><img src="https://github.com/judgekeeper/judgekeeper/actions/workflows/ci.yml/badge.svg?branch=main" alt="Tests"></a>
    <a href="https://github.com/judgekeeper/judgekeeper/blob/main/LICENSE"><img src="https://img.shields.io/github/license/judgekeeper/judgekeeper" alt="Apache-2.0 license"></a>
  </p>
</div>

judgekeeper checks your AI agent or chatbot with human judgment. You mark what's right, and it shows how often an agent-as-a-judge or an LLM-as-a-judge (an AI model that grades another model's work) agrees with you, and where it goes wrong.

## Install

In your project folder, in its virtual environment:
```
pip install judgekeeper
judgekeeper
```
Or `uvx judgekeeper`. Python 3.11 to 3.14.

Using a coding agent? Give it this page and say: "Follow this to run judgekeeper on my project."

## What you can check

| You have | Run | You see |
|---|---|---|
| Agent runs | `judgekeeper steps runs.jsonl --reviewer picks.jsonl` | How often your agent-as-a-judge picks the same first wrong step as you |
| Your agent's or chatbot's answers, no grades | `judgekeeper` | How many pass, with a range |
| Grades from an LLM-as-a-judge | `judgekeeper` | How often it agrees with your marks |

It reads promptfoo, DeepEval, Inspect AI, MLflow, Label Studio exports, or your own CSV, TSV or JSONL file. [Formats](https://github.com/judgekeeper/judgekeeper/blob/main/docs/reference.md#what-it-reads) · [Agent runs and picks](https://github.com/judgekeeper/judgekeeper/blob/main/docs/reference.md#steps-mark-an-agent-runs-first-wrong-step-then-check-an-agent-as-a-judge)

## The 4 steps

1. **Read:** `judgekeeper` finds your results and opens a page. Mark each answer Pass or Fail.
2. **Measure:** run `judgekeeper` again to see how often the LLM-as-a-judge agrees with you.
3. **Fix:** `judgekeeper fix` shows where the LLM-as-a-judge goes wrong. Change its rule, grade `.judgekeeper/fix/marked-answers.csv` again, then `judgekeeper fix new-results.json` tests it on marks kept aside.
4. **Re-check:** `judgekeeper check new-results.json` re-checks it on all your marks.

A result needs at least 15 Pass and 15 Fail marks (10 marks with no grades); for agent runs, 15 that went wrong and 15 that were fine. [More](https://github.com/judgekeeper/judgekeeper/blob/main/docs/reference.md#judgekeeper-read-and-measure)

judgekeeper makes no AI call and needs no API key. In your project it writes only in `.judgekeeper/`, plus `judgekeeper.toml` after you say yes. [Security](https://github.com/judgekeeper/judgekeeper/blob/main/SECURITY.md)

## The numbers

- **TPR:** when you say Pass, how often the LLM-as-a-judge says Pass too.
- **TNR:** when you say Fail, how often it says Fail too.
- **Kappa:** how much you agree beyond what matching at random would give.

Each comes with a range. They are about the answers you marked, not a promise about new ones. [How they are worked out](https://github.com/judgekeeper/judgekeeper/blob/main/docs/reference.md#how-the-numbers-are-worked-out)

## Checked on public data

- [AgentProcessBench](https://github.com/judgekeeper/judgekeeper/blob/main/docs/examples/agent-steps/report.md): an agent-as-a-judge against people's labels on 249 agent runs: 175 of 182 that went wrong caught, 47 of 67 fine ones left alone, kappa 0.71.
- [JailbreakBench](https://github.com/judgekeeper/judgekeeper/blob/main/docs/examples/jailbreakbench/report.md): the ranges held the true values in 96 of 100 random tests.
- [RAGTruth](https://github.com/judgekeeper/judgekeeper/blob/main/docs/examples/ragtruth/report.md): three LLM-as-a-judge setups, "needs work" in all 12 runs.
- [All reports](https://github.com/judgekeeper/judgekeeper/blob/main/docs/examples/)

## More

[Website](https://www.judgekeeper.com) · [Guide](https://www.judgekeeper.com/start.html) · [Reference](https://github.com/judgekeeper/judgekeeper/blob/main/docs/reference.md) · [Changelog](https://github.com/judgekeeper/judgekeeper/blob/main/CHANGELOG.md) · `judgekeeper --help`. [Issues](https://github.com/judgekeeper/judgekeeper/issues/new/choose) are welcome; pull requests are not taken.

## License

judgekeeper and the judgekeeper logo are [trademarks](https://github.com/judgekeeper/judgekeeper/blob/main/TRADEMARKS.md) of Sathvik Thota. The Apache-2.0 license covers the code, not the name or logo.
