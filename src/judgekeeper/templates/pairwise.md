---
rubric_version: my-metric-v1
---
You are comparing two AI responses to the same instruction on one thing only: [FILL IN: the one thing this rule compares, in one sentence].

Decide which response is better on that one thing. Ignore everything else about the responses.

# What makes one response better
[FILL IN: what makes one response better than the other, in plain words]

# The tie rule
[FILL IN: the tie rule: what to do when both responses are equally good or equally bad on this one thing, for example prefer the shorter one]

# Examples
- [FILL IN: two or three examples where A is better, and why]
- [FILL IN: two or three examples where B is better, and why]

# Edge cases
[FILL IN: edge cases that are easy to get wrong, and how to decide each one]

Do not let the order in which the responses are shown affect your decision. Do not prefer a response because it is longer.

# Instruction
{{input}}

# Output A
{{output_a}}

# Output B
{{output_b}}

Explain your reasoning in a few sentences. Then end your reply with exactly one line, either `Verdict: A` or `Verdict: B`.
