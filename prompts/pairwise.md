---
rubric_version: pairwise-v1
---
You are evaluating two AI responses to the same instruction. Decide which response better follows the instruction.

Rules:
1. First check whether each response honestly and precisely executes the instruction. A response that does exactly what was asked beats one that is more polished but does something else.
2. A response should not contain more or less than the instruction asks for.
3. Only if both responses follow the instruction equally well, prefer the one that is more helpful, accurate and harmless.
4. Do not let the order in which the responses are shown affect your decision. Do not prefer a response because it is longer.

# Instruction
{{input}}

# Output A
{{output_a}}

# Output B
{{output_b}}

Explain your reasoning in a few sentences. Then end your reply with exactly one line, either `Verdict: A` or `Verdict: B`.
