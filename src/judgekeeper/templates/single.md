---
rubric_version: my-metric-v1
---
You are checking one thing about an AI response to an instruction: [FILL IN: the one thing this rule checks, in one sentence].

Decide whether the response passes or fails on that one thing only. Ignore everything else about the response.

# What counts as pass
[FILL IN: what a response must do to pass, in plain words]

# What counts as fail
[FILL IN: what makes a response fail, in plain words]

# Examples
Pass:
- [FILL IN: two or three examples of a passing response, one per line]

Fail:
- [FILL IN: two or three examples of a failing response, one per line]

# Edge cases
[FILL IN: edge cases that are easy to get wrong, and how to decide each one]

# Instruction
{{input}}

# Response
{{output}}

Explain your reasoning in a few sentences. Then end your reply with exactly one line, either `Verdict: pass` or `Verdict: fail`.
