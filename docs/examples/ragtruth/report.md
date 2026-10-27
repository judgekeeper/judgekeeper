# Two Claude LLM-as-a-judge setups on RAGTruth's news summaries

This check runs judgekeeper's normal steps on a real LLM-as-a-judge task: does a news summary say only what the article says? Two LLM-as-a-judge setups, Claude Haiku 5.5 and Claude Sonnet 5.5, graded 200 summaries with one rule, and RAGTruth's human labels were the marks.

judgekeeper's result, in all 6 runs: **needs work**. Both LLM-as-a-judge setups fail most of the summaries people failed, but also about one in three of the summaries people passed.

## The setup

- **The answers:** 200 news summaries from RAGTruth's test split, 100 that people labelled Pass and 100 Fail, picked by a fixed seed (`sample-ids.json`: the ids, the seed, the counts). `load.py` downloads the data; it is not in this repository.
- **The LLM-as-a-judge setups:** Claude Haiku 5.5 and Claude Sonnet 5.5 (aliases `claude-haiku-5-5`, `claude-sonnet-5-5`), through promptfoo 0.124.0 `llm-rubric`, at the models' default temperature 1 (`promptfooconfig.yaml`).
- **The rule:** frozen before any result (`rule.txt`): "Every claim in the summary is supported by the article. Pass if every claim is supported by the article. Fail if any claim is not supported by the article or contradicts it."
- **The marks:** RAGTruth's own response-level labels (Fail when the annotators marked at least one hallucinated part), entered through the marking page's calls.
- **Runs:** 3 per LLM-as-a-judge, on 2026-10-25, with judgekeeper 1.0.0 (commit `bc0d099`).

## How often each LLM-as-a-judge agrees with people

| LLM-as-a-judge, run | When people said Pass, the LLM-as-a-judge also said Pass | When people said Fail, the LLM-as-a-judge also said Fail | Disagreed | judgekeeper's result |
|---|---|---|---|---|
| Haiku 5.5, run 1 | about 66% (59% to 73%) | about 89% (83% to 94%) | 45 of 200 | needs work |
| Haiku 5.5, run 2 | about 66% (59% to 73%) | about 89% (83% to 94%) | 45 of 200 | needs work |
| Haiku 5.5, run 3 | about 67% (60% to 74%) | about 87% (80% to 92%) | 46 of 200 | needs work |
| Sonnet 5.5, run 1 | about 68% (61% to 75%) | about 90% (84% to 95%) | 42 of 200 | needs work |
| Sonnet 5.5, run 2 | about 70% (63% to 77%) | about 91% (85% to 95%) | 39 of 200 | needs work |
| Sonnet 5.5, run 3 | about 71% (64% to 78%) | about 91% (85% to 95%) | 38 of 200 | needs work |

The first two columns are TPR and TNR, copied from judgekeeper's Measure screens (`measure/`).

**Asked again:** Haiku changed its grade on 19 of the 200 answers in at least one of its 3 runs. Sonnet changed it on 13.

## What it shows, in plain words

- **Both LLM-as-a-judge setups catch made-up claims well.** When people said a summary had something unsupported, both also failed it about 9 times in 10.
- **Both fail about one in three good summaries.** When people said a summary was fully supported, both still failed about a third of them. With this rule, they are too strict. A single "accuracy" number would hide this, because the two directions are far apart.
- **Sonnet agrees with people about as often as Haiku here,** with its ranges overlapping Haiku's, but steadier when asked again: 13 changed answers against 19.
- **What a user would do next:** judgekeeper says "needs work" and points to `fix`. Most mistakes are good summaries failed, so the clue would be that the rule may be too strict.

## Limits

- **The answers are old:** from 2023 models, in a public dataset since 2024, so the two LLM-as-a-judge models may have seen them.
- **News summaries only,** and one rule.
- **Not the people's rule:** RAGTruth's people labeled with a different rule from the one the LLM-as-a-judge was given, so part of the disagreement is the rule, not the LLM-as-a-judge.
- **The labels have a ceiling:** two annotators agreed on 91.8% of answers (the RAGTruth paper, arXiv:2401.00396, section 3.3, page 4).
- **Pass and Fail answers come mostly from different models:** the Fails are mostly Mistral-7B and Llama-2.
- **The answers aren't fully independent:** the 200 come from 113 articles.
- **Temperature 1,** because these models refuse 0.
- **Never publish article text, the summaries or the LLM-as-a-judge reasons:** the reasons quote the articles. Publish only ids, grades, counts and ranges.

## Files

- **`load.py`:** downloads RAGTruth from the authors' GitHub repository at a pinned commit, checks the files' SHA-256, and keeps the test split's news summaries (`python3 -I load.py`). Its `cache/` folder holds the articles and summaries and is never committed.
- **`sample-ids.json`:** the 200 sampled ids, the seed and the counts. No text.
- **`rule.txt`, `promptfooconfig.yaml`:** the rule and the LLM-as-a-judge's promptfoo setup, as frozen before the run.
- **`measure/`:** the Measure screen of each of the 6 runs, on `bc0d099`.

Each Measure screen in `measure/` starts with a header: the dataset, its commit, the subset and split, and where the grades come from. `sample-ids.json` holds the same in its own fields, unchanged, because the probes record its hash.

Data: RAGTruth, Niu et al., ACL 2024 (github.com/ParticleMedia/RAGTruth), MIT license, Copyright (c) 2023 Particle Media. The license and the full citation are in [THIRD_PARTY_NOTICES.md](../../../THIRD_PARTY_NOTICES.md).
