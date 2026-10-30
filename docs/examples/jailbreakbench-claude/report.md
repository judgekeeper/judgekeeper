# Two LLM-as-a-judge setups on JailbreakBench's judge-comparison answers

This check runs judgekeeper's normal steps on 300 answers to harmful requests, with three experts' majority label as the marks. It is the same 300 answers as [the GPT-4 check](../jailbreakbench/report.md); here two Claude setups graded them instead of the dataset's own GPT-4 grades. For each answer the question is whether it gives real help with the harmful request (Fail) or not (Pass).

judgekeeper's result for both setups: **needs work**. Both passed nearly every answer the experts passed, and both failed fewer than half of the answers the experts failed. For the dataset's own GPT-4 grades, the same two figures are about 90% and 91%.

## The setups

In this report, **setup A** is Claude Haiku 5.5 (`claude-haiku-5-5`, effort medium) and **setup B** is Claude Sonnet 5.5 (`claude-sonnet-5-5`, effort high). Each is the model's API default effort, set in the config on purpose.

- **The answers:** all 300 rows of the `judge_comparison` set, revision `886acc352a31533ffbcf4ef22c744658688086fc`, MIT license. `load.py` downloads it (it reuses `../jailbreakbench/load.py`'s source and SHA-256); the data is not in this repository. Nothing from it is committed except ids and grades.
- **The LLM-as-a-judge setups:** A and B, through promptfoo 0.124.0 `llm-rubric`, at temperature 1 (`promptfooconfig.yaml`).
- **The rule:** frozen on 2026-10-30, before any result (`rule.txt`). It is the jailbreak judge prompt printed in the JailbreakBench paper (Chao et al., arXiv 2404.01318, Appendix F, Table 10), with the four guidelines kept as printed. Changed: the closing "Answer with either 'safe' or 'unsafe'" line is left out, because `llm-rubric` asks for its own reply format, and the rule is turned into a statement that is true for a Pass ("The response is safe"). The request shown to the LLM-as-a-judge is the dataset's `goal` column, the response is `target_response`.
- **The marks:** the dataset's `human_majority` column, the majority of three expert annotators. Pass = not jailbroken, Fail = jailbroken, as in the GPT-4 check. They were entered through the marking page's calls.
- **Runs:** 1 per setup, on 2026-10-30, with judgekeeper 1.0.0 (commit `bfc3606`). Token counts and cost are in `notes.txt`.

## How often each setup agrees with the experts

| Setup, run | When the experts said Pass, it also said Pass | When the experts said Fail, it also said Fail | Disagreed | Answers with a real decision | judgekeeper's result |
|---|---|---|---|---|---|
| A (Haiku 5.5), run 1 | about 98% (96% to 100%) | about 43% (37% to 49%) | 64 of 294 | 294 of 300 | needs work |
| B (Sonnet 5.5), run 1 | about 99% (97% to 100%) | about 32% (27% to 39%) | 51 of 239 | 239 of 300 | needs work |

The Pass and Fail columns are TPR and TNR, copied from judgekeeper's Measure screens (`measure/`). Every answer with a real decision was marked, so these are counted, not sampled. The same counts with 95% (Wilson) ranges, and kappa computed from them (`figures.json`):

| | TPR | TNR | Kappa |
|---|---|---|---|
| A | 98.4% (95.4% to 99.5%), 184 of 187 | 43.0% (34.0% to 52.5%), 46 of 107 | 0.468 |
| B | 99.4% (96.6% to 99.9%), 164 of 165 | 32.4% (22.9% to 43.7%), 24 of 74 | 0.389 |

**Comparison with the dataset's own GPT-4 grades** (counted on all 300 answers, from [the GPT-4 report](../jailbreakbench/report.md)): TPR 90.0% (84.9% to 93.5%), 171 of 190; TNR 90.9% (84.1% to 95.0%), 100 of 110; kappa 0.795. On the same answers each Claude setup graded, the GPT-4 grades give TPR 89.8% and TNR 90.7% (294 answers, setup A), and TPR 92.7% and TNR 87.8% (239 answers, setup B), from `ids-and-grades.csv`.

## Answers with no real decision

For some answers the model provider declined to grade: no usable reply came back. promptfoo counts these as fails. judgekeeper leaves them out of the result (its Find step lists them).

- **Setup A:** 6 of 300 (3 the experts passed, 3 the experts failed).
- **Setup B:** 61 of 300, 25 the experts passed and 36 the experts failed, so about a third (36 of 110) of the answers the experts failed are missing from setup B's TNR. The provider's message named a category for each: 55 `cyber`, 4 `general_harms`, 2 `bio`.

These answers were not asked again. The answers the provider declines to grade are probably not a random part of the set, so setup B's numbers describe the answers it was allowed to grade.

## What it shows, in plain words

- **Both setups passed almost everything the experts passed** (98% and 99%).
- **Both failed fewer than half of what the experts failed** (43% and 32%): about 6 of 10 and 7 of 10 of the answers the experts called jailbroken were passed. Here a Pass means "no real help with the request", so this is the costly direction. A single "agreement" number would hide it: overall agreement is 78% and 79%.
- **What a user would do next:** judgekeeper says "needs work" and points to `fix`. Most mistakes are jailbroken answers passed, so the clue would be that the rule is too lenient for these setups. **Checked for a set-up error, none found.** In `llm-rubric` a Pass is "the rubric statement is true", and the rule's statement is "The response is safe", so "unsafe" is a Fail; the 98% and 99% in the Pass column also show the labels are not swapped. We read the LLM-as-a-judge's own reasons (without saving or quoting any answer) for setup A on 10 answers the experts failed and it passed, and on 5 it failed: all 10 passes say the content was generic, high-level, truncated or cut off, or fictional without usable detail, which is guidelines 2 and 3 applied as printed; the 5 fails name specific harmful content. So the gap comes from the paper's guidelines being stricter than the experts' marks, not from a mapping mistake. We did not run the same read for setup B.

## Limits

- **One run each,** at temperature 1. In the RAGTruth check, runs of the same setup moved a few points.
- **The rule was written for a different judge.** It is the paper's prompt for its Llama-3-70B judge, adapted to `llm-rubric`; the dataset's own GPT-4 grades came from a different prompt. A different wording could give different numbers. The check says what these two setups did with this rule, not what any model can do.
- **Setup B's result is on 239 of 300 answers** (see above).
- **The dataset is public** (since 2024), so the models may have seen it.
- **Three experts' majority** is the mark; the experts disagreed with each other on some answers.
- **Never publish the requests or the responses:** they are harmful. Only ids, grades, counts and ranges are published.

## Files

- **`load.py`:** downloads the data (pinned revision, SHA-256 checked) and writes `cache/rows.jsonl`, which is never committed.
- **`rule.txt`, `promptfooconfig.yaml`:** the rule and the setup, as frozen before the run. The config has two slots, `JUDGE_PROVIDER` and `JUDGE_EFFORT`.
- **`measure/`:** the Measure screen of each run.
- **`ids-and-grades.csv`:** each answer's id, both Claude grades (`none` where there was no real decision), the GPT-4 grade and the experts' majority.
- **`figures.json`:** the counts, ranges and kappa above. **`notes.txt`:** dates, effort, token counts, cost, and the answers with no real decision.

Each file starts with a header: the dataset, its commit, the subset and split, and where the grades come from.

Data: JailbreakBench, Chao et al., NeurIPS 2024 Datasets and Benchmarks Track (github.com/JailbreakBench/jailbreakbench), MIT license, Copyright (c) 2023 JailbreakBench Team. The license and the full citation are in [THIRD_PARTY_NOTICES.md](../../../THIRD_PARTY_NOTICES.md).
