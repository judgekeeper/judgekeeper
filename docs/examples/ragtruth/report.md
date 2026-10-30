# Three Claude LLM-as-a-judge setups on RAGTruth's news summaries

This check runs judgekeeper's normal steps on a real LLM-as-a-judge task: does a news summary say only what the article says? Three LLM-as-a-judge setups, Claude Haiku 5.5, Claude Sonnet 5.5 and (added 2026-10-30) Claude Opus 5.5, graded 200 summaries with one rule, and RAGTruth's human labels were the marks.

judgekeeper's result, in all 12 runs: **needs work**. All three LLM-as-a-judge setups fail most of the summaries people failed, but also a good share of the summaries people passed: about one in three for Haiku and Sonnet, about two in five for Opus.

## The setup

- **The answers:** 200 news summaries from RAGTruth's test split, 100 that people labelled Pass and 100 Fail, picked by a fixed seed (`sample-ids.json`: the ids, the seed, the counts). `load.py` downloads the data; it is not in this repository.
- **The LLM-as-a-judge setups:** Claude Haiku 5.5, Claude Sonnet 5.5 and Claude Opus 5.5 (aliases `claude-haiku-5-5`, `claude-sonnet-5-5`, `claude-opus-5-5`), through promptfoo 0.124.0 `llm-rubric`, at the models' default temperature 1 (`promptfooconfig.yaml`).
- **The rule:** frozen before any result (`rule.txt`): "Every claim in the summary is supported by the article. Pass if every claim is supported by the article. Fail if any claim is not supported by the article or contradicts it."
- **The marks:** RAGTruth's own response-level labels (Fail when the annotators marked at least one hallucinated part), entered through the marking page's calls.
- **Effort:** how hard the model thinks is a setting of its own. promptfoo sends it only when the config sets it, and the Haiku and Sonnet runs did not, so each ran at its API default: medium for Haiku 5.5, high for Sonnet 5.5. Opus 5.5's default is medium, so it first ran at medium (extra table below), which is not a like-for-like comparison with Sonnet. The Opus rows in the main table were run again with `effort: high` set in the config, to match Sonnet. The effort is the only difference in the config.
- **Runs:** 3 per LLM-as-a-judge. Haiku and Sonnet on 2026-10-25, with judgekeeper 1.0.0 (commit `bc0d099`); Opus on 2026-10-30, with judgekeeper 1.0.0 (commit `bfc3606`), the same sample, rule and config. Opus's token counts and cost are in `opus-notes.txt`.

## How often each LLM-as-a-judge agrees with people

| LLM-as-a-judge, run | When people said Pass, the LLM-as-a-judge also said Pass | When people said Fail, the LLM-as-a-judge also said Fail | Disagreed | judgekeeper's result |
|---|---|---|---|---|
| Haiku 5.5, run 1 | about 66% (59% to 73%) | about 89% (83% to 94%) | 45 of 200 | needs work |
| Haiku 5.5, run 2 | about 66% (59% to 73%) | about 89% (83% to 94%) | 45 of 200 | needs work |
| Haiku 5.5, run 3 | about 67% (60% to 74%) | about 87% (80% to 92%) | 46 of 200 | needs work |
| Sonnet 5.5, run 1 | about 68% (61% to 75%) | about 90% (84% to 95%) | 42 of 200 | needs work |
| Sonnet 5.5, run 2 | about 70% (63% to 77%) | about 91% (85% to 95%) | 39 of 200 | needs work |
| Sonnet 5.5, run 3 | about 71% (64% to 78%) | about 91% (85% to 95%) | 38 of 200 | needs work |
| Opus 5.5 (effort high), run 1 | about 58% (51% to 65%) | about 94% (88% to 98%) | 48 of 200 | needs work |
| Opus 5.5 (effort high), run 2 | about 61% (54% to 68%) | about 94% (88% to 98%) | 45 of 200 | needs work |
| Opus 5.5 (effort high), run 3 | about 62% (55% to 69%) | about 94% (88% to 97%) | 44 of 200 | needs work |

The first two columns are TPR and TNR, copied from judgekeeper's Measure screens (`measure/`). Opus's rows were added on 2026-10-30; the first six rows are unchanged. Opus at its default effort is in a second table below.

**Asked again:** Haiku changed its grade on 19 of the 200 answers in at least one of its 3 runs. Sonnet changed it on 13. Opus (effort high) changed it on 6 (`opus-high-runs.json`).

**Extra: Opus 5.5 at its default effort (medium)**, run first, before the like-for-like runs above:

| LLM-as-a-judge, run | When people said Pass, the LLM-as-a-judge also said Pass | When people said Fail, the LLM-as-a-judge also said Fail | Disagreed | judgekeeper's result |
|---|---|---|---|---|
| Opus 5.5 (effort medium), run 1 | about 61% (54% to 68%) | about 94% (88% to 98%) | 45 of 200 | needs work |
| Opus 5.5 (effort medium), run 2 | about 58% (51% to 65%) | about 93% (87% to 97%) | 49 of 200 | needs work |
| Opus 5.5 (effort medium), run 3 | about 58% (51% to 65%) | about 92% (86% to 96%) | 50 of 200 | needs work |

At medium effort Opus changed its grade on 11 of the 200 answers (`opus-medium-runs.json`).

## What it shows, in plain words

- **All three LLM-as-a-judge setups catch made-up claims well.** When people said a summary had something unsupported, each also failed it about 9 times in 10.
- **Haiku and Sonnet fail about one in three good summaries; Opus about two in five.** When people said a summary was fully supported, they still failed that many of them. With this rule, they are too strict. A single "accuracy" number would hide this, because the two directions are far apart.
- **Sonnet agrees with people about as often as Haiku here,** with its ranges overlapping Haiku's, but steadier when asked again: 13 changed answers against 19.
- **A larger model did not agree with people more often here.** Claude Opus 5.5 (effort high) disagreed with people on 44 to 48 of 200 answers, against 45 to 46 for Haiku and 38 to 42 for Sonnet. Of the summaries people passed, Opus also passed 58% to 62%, against 66% to 67% for Haiku and 68% to 71% for Sonnet; of the ones people failed, it also failed 94%, against 87% to 89% and 90% to 91%. Every range overlaps one from another setup, so three runs cannot say the three setups differ on agreement. The result did not change: "needs work" in all 3 Opus runs, for the same reason (good summaries failed).
- **Thinking less or more changed little.** At its default effort (medium) Opus gave nearly the same numbers (second table). Opus at high effort used about 12% more output tokens than at medium (299,389 against 266,973 over 3 runs).
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
- **`rule.txt`, `promptfooconfig.yaml`:** the rule and the LLM-as-a-judge's promptfoo setup, as frozen before the first run and used unchanged for Opus.
- **`measure/`:** the Measure screen of each run: Haiku and Sonnet on `bc0d099`, Opus (effort high, and the extra medium runs) on `bfc3606`.
- **`opus-high-runs.json`, `opus-medium-runs.json`, `opus-notes.txt`:** for Opus, each answer's grade in the 3 runs (ids and grades only), and the dates, effort, token counts and cost.

Each Measure screen in `measure/` starts with a header: the dataset, its commit, the subset and split, and where the grades come from. `sample-ids.json` holds the same in its own fields, unchanged, because the probes record its hash.

Data: RAGTruth, Niu et al., ACL 2024 (github.com/ParticleMedia/RAGTruth), MIT license, Copyright (c) 2023 Particle Media. The license and the full citation are in [THIRD_PARTY_NOTICES.md](../../../THIRD_PARTY_NOTICES.md).
