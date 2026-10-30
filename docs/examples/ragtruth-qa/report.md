# Two LLM-as-a-judge setups on RAGTruth's question answers

This check runs judgekeeper's normal steps on the second kind of task in RAGTruth: short answers to questions, written from three passages (MS MARCO questions). Two LLM-as-a-judge setups, **setup A** (Claude Haiku 5.5, `claude-haiku-5-5`) and **setup B** (Claude Sonnet 5.5, `claude-sonnet-5-5`), graded 200 answers with one rule, and RAGTruth's human labels were the marks. It is the same check as [the news-summary one](../ragtruth/report.md), with one run per setup instead of three.

judgekeeper's result, in both runs: **needs work**. For setups A and B, the share of answers people failed that the setup also failed was 95% and 97%, and the share of answers people passed that it also passed was 61% and 58%.

## The setup

- **The answers:** 200 answers from RAGTruth's test split, 100 that people labelled Pass and 100 Fail, picked by a fixed seed (`sample-ids.json`: the ids, the seed, the counts). The pool is the test split's answers, 872 in all after 28 answers whose exact text appears more than once were left out (the marks are matched to answers by their text): 712 Pass and 160 Fail. `load.py` downloads the data and draws the sample; the data is not in this repository.
- **The LLM-as-a-judge setups:** A is Claude Haiku 5.5 (`claude-haiku-5-5`) and B is Claude Sonnet 5.5 (`claude-sonnet-5-5`), through promptfoo 0.124.0 `llm-rubric`, at the models' default temperature 1 (`promptfooconfig.yaml`). Effort was not set, so each ran at its API default, as in the news-summary check: medium for A, high for B.
- **The rule:** frozen on 2026-10-30, before any result (`rule.txt`): "Every claim in the answer is supported by the passages. Pass if every claim is supported by the passages. Fail if any claim is not supported by the passages or contradicts them." It is the news-summary rule with "answer" and "passages" in place of "summary" and "article". The question is shown to the LLM-as-a-judge above the passages, because a short answer cannot be read without it; nothing else was added.
- **The marks:** RAGTruth's own response-level labels (Fail when the annotators marked at least one hallucinated part), entered through the marking page's calls.
- **Runs:** 1 per LLM-as-a-judge, on 2026-10-30, with judgekeeper 1.0.0 (commit `bfc3606`). Token counts and cost are in `notes.txt`.

## How often each LLM-as-a-judge agrees with people

| LLM-as-a-judge, run | When people said Pass, the LLM-as-a-judge also said Pass | When people said Fail, the LLM-as-a-judge also said Fail | Disagreed | judgekeeper's result |
|---|---|---|---|---|
| A (Haiku 5.5), run 1 | about 61% (54% to 68%) | about 95% (90% to 98%) | 44 of 200 | needs work |
| B (Sonnet 5.5), run 1 | about 58% (51% to 65%) | about 97% (92% to 99%) | 45 of 200 | needs work |

The first two columns are TPR and TNR, copied from judgekeeper's Measure screens (`measure/`).

## Does the news-summary pattern hold?

The news-summary check found two things: the setups failed most of what people failed, and they also failed about one in three of what people passed. Run 1 of each check, side by side:

| Task | A: Pass also Pass | A: Fail also Fail | B: Pass also Pass | B: Fail also Fail |
|---|---|---|---|---|
| News summaries ([report](../ragtruth/report.md)) | about 66% (59% to 73%) | about 89% (83% to 94%) | about 68% (61% to 75%) | about 90% (84% to 95%) |
| This task | about 61% (54% to 68%) | about 95% (90% to 98%) | about 58% (51% to 65%) | about 97% (92% to 99%) |

- **Failing what people failed holds.** On question answers the setups failed 95% and 97% of the answers people failed, a little more than on summaries.
- **"About one in three good ones failed" does not hold exactly.** On question answers the setups failed about four in ten of the answers people passed (the Pass column is 61% and 58%), more than the roughly one in three on summaries. The ranges overlap with the summary ones (for Haiku, 54% to 68% against 59% to 73%), so with one run each this is a lean, not a difference we can state.
- **Same result, same advice:** "needs work" in both runs, because many good answers were failed.

## Limits

- **One run each,** at temperature 1. In the news-summary check, the same setup's TPR moved by up to 3 points between runs, so small differences here mean little.
- **The answers are old:** from 2023 models, in a public dataset since 2024, so the two LLM-as-a-judge models may have seen them.
- **One kind of task and one rule.** Question answers here are short, and the passages are web text from MS MARCO.
- **Not the people's rule:** RAGTruth's people labeled with a different rule from the one the LLM-as-a-judge was given, so part of the disagreement is the rule, not the LLM-as-a-judge.
- **The labels are people's,** and people disagree with each other too.
- **Pass and Fail answers come mostly from different models:** the Fails are mostly Llama-2 and Mistral-7B answers, while 39 of the 100 Passes come from the two GPT models and only 5 of the 100 Fails do (`sample-ids.json`).
- **The answers aren't fully independent:** the 200 come from 104 questions.
- **Temperature 1,** because these models refuse 0.
- **Never publish the passages, the questions, the answers or the LLM-as-a-judge reasons (the reasons quote them):** publish only ids, grades, counts and ranges.

## Files

- **`load.py`:** downloads RAGTruth from the authors' GitHub repository at a pinned commit, checks the files' SHA-256, keeps the test split's question-answering rows, draws the sample and checks it against `sample-ids.json` (`python3 -I load.py`). Its `cache/` folder holds the text and is never committed.
- **`sample-ids.json`:** the 200 sampled ids, the seed and the counts. No text.
- **`rule.txt`, `promptfooconfig.yaml`:** the rule and the LLM-as-a-judge's promptfoo setup, as frozen before the run.
- **`measure/`:** the Measure screen of each of the 2 runs.
- **`notes.txt`:** dates, effort, token counts and cost.

Each Measure screen in `measure/` starts with a header: the dataset, its commit, the subset and split, and where the grades come from.

Data: RAGTruth, Niu et al., ACL 2024 (github.com/ParticleMedia/RAGTruth), MIT license, Copyright (c) 2023 Particle Media. The license and the full citation are in [THIRD_PARTY_NOTICES.md](../../../THIRD_PARTY_NOTICES.md).
