# Two Claude LLM-as-a-judge setups on RAGTruth's data-to-text overviews

This check runs judgekeeper's normal steps on the second kind of task in RAGTruth: overviews of local businesses (from Yelp), written from a block of structured JSON data. Two LLM-as-a-judge setups, Claude Haiku 5.5 and Claude Sonnet 5.5, graded 200 overviews with one rule, and RAGTruth's human labels were the marks. It is the same check as [the news-summary one](../ragtruth/report.md), with one run per setup instead of three.

judgekeeper's result, in both runs: **needs work**. Both setups fail almost every overview people failed (98% and 97%). On the overviews people passed they differ: Haiku passed 39% of them, Sonnet 65%.

## The setup

- **The overviews:** 200 overviews from RAGTruth's test split, 100 that people labelled Pass and 100 Fail, picked by a fixed seed (`sample-ids.json`: the ids, the seed, the counts). The pool is the test split's overviews: 321 Pass and 579 Fail (no overview text appears twice). `load.py` downloads the data and draws the sample; the data is not in this repository.
- **The LLM-as-a-judge setups:** Claude Haiku 5.5 and Claude Sonnet 5.5 (aliases `claude-haiku-5-5`, `claude-sonnet-5-5`), through promptfoo 0.124.0 `llm-rubric`, at the models' default temperature 1 (`promptfooconfig.yaml`). Effort was not set, so each ran at its API default, as in the news-summary check: medium for Haiku, high for Sonnet.
- **The rule:** frozen on 2026-10-30, before any result (`rule.txt`): "Every claim in the overview is supported by the data. Pass if every claim is supported by the data. Fail if any claim is not supported by the data or contradicts it." It is the news-summary rule with "overview" and "data" in place of "summary" and "article". The data is shown to the LLM-as-a-judge as the JSON the writing model was given; nothing else was added.
- **The marks:** RAGTruth's own response-level labels (Fail when the annotators marked at least one hallucinated part), entered through the marking page's calls.
- **Runs:** 1 per LLM-as-a-judge, on 2026-10-30, with judgekeeper 1.0.0 (commit `bfc3606`). Token counts and cost are in `notes.txt`.

## How often each LLM-as-a-judge agrees with people

| LLM-as-a-judge, run | When people said Pass, the LLM-as-a-judge also said Pass | When people said Fail, the LLM-as-a-judge also said Fail | Disagreed | judgekeeper's result |
|---|---|---|---|---|
| Haiku 5.5, run 1 | about 39% (34% to 44%) | about 98% (94% to 100%) | 63 of 200 | needs work |
| Sonnet 5.5, run 1 | about 65% (58% to 72%) | about 97% (92% to 99%) | 38 of 200 | needs work |

The first two columns are TPR and TNR, copied from judgekeeper's Measure screens (`measure/`).

## Does the news-summary pattern hold?

The news-summary check found two things: both setups fail most of what people failed, and they also fail about one in three of what people passed. Run 1 of each check, side by side:

| Task | Haiku: Pass also Pass | Haiku: Fail also Fail | Sonnet: Pass also Pass | Sonnet: Fail also Fail |
|---|---|---|---|---|
| News summaries ([report](../ragtruth/report.md)) | about 66% (59% to 73%) | about 89% (83% to 94%) | about 68% (61% to 75%) | about 90% (84% to 95%) |
| This task | about 39% (34% to 44%) | about 98% (94% to 100%) | about 65% (58% to 72%) | about 97% (92% to 99%) |

- **Failing what people failed holds.** On data-to-text both setups failed 97% to 98% of the overviews people failed.
- **"About one in three good ones failed" holds for Sonnet, not for Haiku.** Sonnet's Pass column (65%) is close to its summary one (68%). Haiku passed only 39% of the overviews people passed, so it failed about six in ten. The ranges do not overlap (34% to 44% against 59% to 73% on summaries), so this is a real gap in this sample. We did not look into why; a strict reading of "supported by the data" is one guess.
- **Same result, same advice:** "needs work" in both runs. For Haiku, the first step would be the same as before: most mistakes are good overviews failed, so the rule may be too strict for it.

## Limits

- **One run each,** at temperature 1. In the news-summary check, the same setup's TPR moved by up to 3 points between runs, so small differences here mean little.
- **The answers are old:** from 2023 models, in a public dataset since 2024, so the two LLM-as-a-judge models may have seen them.
- **One kind of task and one rule.** The data is Yelp business records.
- **Not the people's rule:** RAGTruth's people labeled with a different rule from the one the LLM-as-a-judge was given, so part of the disagreement is the rule, not the LLM-as-a-judge.
- **The labels are people's,** and people disagree with each other too.
- **Pass and Fail answers come mostly from different models:** the Fails are mostly Llama-2 and Mistral-7B overviews, while 72 of the 100 Passes come from the two GPT models and only 9 of the 100 Fails do (`sample-ids.json`). A strong lean toward one family of writers.
- **The answers aren't fully independent:** the 200 come from 113 businesses.
- **Temperature 1,** because these models refuse 0.
- **Never publish the data, the overviews or the LLM-as-a-judge reasons (the reasons quote them):** publish only ids, grades, counts and ranges.

## Files

- **`load.py`:** downloads RAGTruth from the authors' GitHub repository at a pinned commit, checks the files' SHA-256, keeps the test split's data-to-text rows, draws the sample and checks it against `sample-ids.json` (`python3 -I load.py`). Its `cache/` folder holds the text and is never committed.
- **`sample-ids.json`:** the 200 sampled ids, the seed and the counts. No text.
- **`rule.txt`, `promptfooconfig.yaml`:** the rule and the LLM-as-a-judge's promptfoo setup, as frozen before the run.
- **`measure/`:** the Measure screen of each of the 2 runs.
- **`notes.txt`:** dates, effort, token counts and cost.

Each Measure screen in `measure/` starts with a header: the dataset, its commit, the subset and split, and where the grades come from.

Data: RAGTruth, Niu et al., ACL 2024 (github.com/ParticleMedia/RAGTruth), MIT license, Copyright (c) 2023 Particle Media. The license and the full citation are in [THIRD_PARTY_NOTICES.md](../../../THIRD_PARTY_NOTICES.md).
