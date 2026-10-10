# Real-data check of judgekeeper's ranges

Made by `scripts/real_data_check.py`; do not edit by hand.

Each judge below decided on every answer in a public dataset, and people labeled the same answers. So how often the judge agrees with the people is known: it is worked out from all of the dataset's human labels. Each check pretends a person labeled only a few answers, picked as `judgekeeper start` picks them (as many from the judge's passes as from its fails), and works out TPR (how often the judge passed answers people passed), TNR (how often it failed answers people failed) and the real pass rate with judgekeeper's own maths, each with a range. A range should hold the value from all labels about 96% of the time. No judge was called.

## The result

With 50 labels per check (25 from each group), on 5 judges from 3 public datasets, the TPR and TNR ranges held the value from all of the dataset's human labels in 96.0 checks in 100 on average (lowest 94.6, highest 98.4), over 1,000 checks per judge.

| Design | Labels per check | TPR and TNR: held in 100 (average) | Lowest | Highest |
|---|---|---|---|---|
| 25+25 labels | 50 | 96.0 | 94.6 (LLMBar × Claude Haiku 4.5, TNR) | 98.4 (LLMBar × Claude Haiku 4.5, TPR) |
| 30+30 labels | 60 | 96.6 | 95.0 (LLMJudge × RMITIR-GPT4o, TPR) | 99.0 (LLMBar × Claude Haiku 4.5, TPR) |
| start's rule (25 Pass + 25 Fail) | 59 to 79 on average | 96.5 | 95.0 (MT-Bench × GPT-4, TNR) | 99.0 (LLMBar × Claude Haiku 4.5, TPR) |

A 96% range is expected to miss about 4 times in 100. With 1,000 checks, chance alone moves the share it holds by up to about 1.2 either way (95 times in 100).

## The judges

The values from all of each dataset's human labels.

| Judge | Answers | Judge passed | TPR | TNR | Real pass rate | Kappa |
|---|---|---|---|---|---|---|
| LLMBar × Claude Haiku 4.5 | 419 | 53.5% | 0.95 | 0.87 | 0.49 | 0.82 |
| MT-Bench × GPT-4 | 1,814 | 67.3% | 0.85 | 0.56 | 0.57 | 0.42 |
| LLMJudge × RMITIR-GPT4o | 4,423 | 23.0% | 0.51 | 0.87 | 0.27 | 0.40 |
| LLMJudge × willia-umbrela1 | 4,423 | 19.4% | 0.46 | 0.90 | 0.27 | 0.40 |
| LLMJudge × NISTRetrieval-instruct0 | 4,423 | 27.5% | 0.50 | 0.81 | 0.27 | 0.30 |

## How often each range held, per judge

Held in 100 checks, TPR / TNR / real pass rate, 1,000 checks each.

| Judge | 25+25 labels | 30+30 labels | start's rule (25 Pass + 25 Fail) |
|---|---|---|---|
| LLMBar × Claude Haiku 4.5 | 98.4 / 94.6 / 96.4 | 99.0 / 97.4 / 96.8 | 99.0 / 97.5 / 97.3 |
| MT-Bench × GPT-4 | 96.0 / 95.7 / 96.5 | 95.9 / 97.0 / 97.4 | 95.7 / 95.0 / 95.5 |
| LLMJudge × RMITIR-GPT4o | 95.6 / 96.1 / 95.3 | 95.0 / 96.5 / 96.5 | 95.6 / 96.4 / 95.5 |
| LLMJudge × willia-umbrela1 | 94.8 / 96.6 / 95.8 | 95.9 / 96.4 / 94.7 | 95.9 / 97.3 / 96.1 |
| LLMJudge × NISTRetrieval-instruct0 | 95.0 / 96.7 / 95.2 | 96.3 / 97.0 / 95.3 | 95.9 / 96.4 / 96.4 |

Checks where a number could not be worked out: 0.

## Range width and error

Average width of the range (high end minus low end) and the median distance from the number to the value from all labels, TPR / TNR.

| Judge | 25+25 labels | 30+30 labels | start's rule (25 Pass + 25 Fail) |
|---|---|---|---|
| LLMBar × Claude Haiku 4.5 | width 0.15 / 0.22, error 0.02 / 0.04 | width 0.14 / 0.21, error 0.02 / 0.03 | width 0.14 / 0.21, error 0.02 / 0.04 |
| MT-Bench × GPT-4 | width 0.18 / 0.33, error 0.03 / 0.05 | width 0.17 / 0.30, error 0.03 / 0.05 | width 0.17 / 0.30, error 0.03 / 0.05 |
| LLMJudge × RMITIR-GPT4o | width 0.44 / 0.12, error 0.09 / 0.02 | width 0.41 / 0.11, error 0.07 / 0.02 | width 0.38 / 0.10, error 0.06 / 0.02 |
| LLMJudge × willia-umbrela1 | width 0.44 / 0.10, error 0.08 / 0.02 | width 0.40 / 0.09, error 0.07 / 0.02 | width 0.38 / 0.09, error 0.07 / 0.01 |
| LLMJudge × NISTRetrieval-instruct0 | width 0.45 / 0.14, error 0.08 / 0.02 | width 0.41 / 0.13, error 0.07 / 0.02 | width 0.36 / 0.11, error 0.06 / 0.02 |

## Without the correction

judgekeeper weighs each group by its size in the pool, because a check labels as many of the judge's passes as of its fails. Without that, the same labels give these rates (average over the 1,000 checks with 25 + 25 labels):

| Judge | TPR without / value from all labels | TNR without / value from all labels |
|---|---|---|
| LLMBar × Claude Haiku 4.5 | 0.95 / 0.95 | 0.89 / 0.87 |
| MT-Bench × GPT-4 | 0.73 / 0.85 | 0.73 / 0.56 |
| LLMJudge × RMITIR-GPT4o | 0.78 / 0.51 | 0.67 / 0.87 |
| LLMJudge × willia-umbrela1 | 0.79 / 0.46 | 0.70 / 0.90 |
| LLMJudge × NISTRetrieval-instruct0 | 0.73 / 0.50 | 0.62 / 0.81 |

## One check in full

The first of the 1,000 checks with 25 + 25 labels for each judge, not picked by hand. Kappa has no range.

| Judge | Marked Pass (of judge passes / fails) | TPR | TNR | Real pass rate | Kappa |
|---|---|---|---|---|---|
| LLMBar × Claude Haiku 4.5 | 21 of 25 / 0 of 25 | 1.00 (0.90 to 1.00), all labels 0.95 | 0.84 (0.71 to 0.94), all labels 0.87 | 0.45 (0.36 to 0.52), all labels 0.49 | 0.83, all labels 0.82 |
| MT-Bench × GPT-4 | 16 of 25 / 7 of 25 | 0.82 (0.71 to 0.91), all labels 0.85 | 0.49 (0.36 to 0.65), all labels 0.56 | 0.52 (0.38 to 0.66), all labels 0.57 | 0.32, all labels 0.42 |
| LLMJudge × RMITIR-GPT4o | 20 of 25 / 2 of 25 | 0.75 (0.49 to 0.94), all labels 0.51 | 0.94 (0.88 to 0.98), all labels 0.87 | 0.25 (0.18 to 0.37), all labels 0.27 | 0.70, all labels 0.40 |
| LLMJudge × willia-umbrela1 | 15 of 25 / 3 of 25 | 0.55 (0.30 to 0.82), all labels 0.46 | 0.90 (0.85 to 0.94), all labels 0.90 | 0.21 (0.13 to 0.36), all labels 0.27 | 0.46, all labels 0.40 |
| LLMJudge × NISTRetrieval-instruct0 | 13 of 25 / 5 of 25 | 0.50 (0.30 to 0.73), all labels 0.50 | 0.81 (0.74 to 0.88), all labels 0.81 | 0.29 (0.18 to 0.44), all labels 0.27 | 0.32, all labels 0.30 |

## The questions

Each item became one yes/no question, fixed before looking at the results. Nothing was dropped because of what the judge said.

| Judge | Question | Judge pass | Human pass |
|---|---|---|---|
| LLMBar × Claude Haiku 4.5 | Is output A the better of the two? | run 1 of the saved runs says A | LLMBar's gold label is A |
| MT-Bench × GPT-4 | Is model_b's answer better than model_a's? | GPT-4 says model_b; its ties are not a pass | more than half of the expert votes say model_b; ties and split votes are not a pass |
| LLMJudge × RMITIR-GPT4o | Is this passage relevant to the question (grade 2 or 3 of 0 to 3)? | the run's grade is 2 or 3 | the NIST assessor's grade is 2 or 3 |
| LLMJudge × willia-umbrela1 | Is this passage relevant to the question (grade 2 or 3 of 0 to 3)? | the run's grade is 2 or 3 | the NIST assessor's grade is 2 or 3 |
| LLMJudge × NISTRetrieval-instruct0 | Is this passage relevant to the question (grade 2 or 3 of 0 to 3)? | the run's grade is 2 or 3 | the NIST assessor's grade is 2 or 3 |

The human labels are what each dataset has: LLMBar's gold labels written by its authors, MT-Bench's expert votes (often one per item), and one NIST assessor per passage in LLMJudge. Each check draws from the dataset without putting answers back, as a person labels; the ranges assume an endless pool, which makes them a little cautious on the smallest pool.

## Data and licences

- **LLMBar** (MIT): <https://github.com/princeton-nlp/LLMBar>, revision `900616bff90b6c6c8e1681f7d079250637c55992`. Zeng et al. (2024), Evaluating Large Language Models at Evaluating Instruction Following, ICLR 2024. The judge verdicts are judgekeeper's own run of claude-haiku-4-5-20251001, kept in docs/examples/llmbar-haiku/report.json.
- **MT-Bench human judgments** (CC-BY-4.0): <https://huggingface.co/datasets/lmsys/mt_bench_human_judgments>, revision `f7d2896d2cc5d80f8b55c2bbc722613555233c25`. Zheng et al. (2023), Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena, NeurIPS 2023 Datasets and Benchmarks. Licensed CC-BY-4.0. Changed here: each item turned into one yes/no question as described in this report; no data is copied into this repository.
  - `mtbench/gpt4_pair.parquet`: sha256 `57068327ffb5f8fddb15fedbbfe40b26fe862da2326331e5cf64a42320a00e71`
  - `mtbench/human.parquet`: sha256 `4877bc46a40929f4082c3c79593700fb897b1d6c7f4c473032694a01322f5769`
- **LLMJudge benchmark** (MIT): <https://github.com/llm4eval/LLMJudge-benchmark>, revision `0e2024814e3192cfc662ecee56dbd16b2536a7de`. Rahmani et al. (2024), LLMJudge: LLMs for Relevance Judgments, LLM4Eval workshop at SIGIR 2024. Grades by NIST assessors for TREC Deep Learning 2023 and by the submitted runs; only grades and ids are read.
  - `llmjudge/qrels.txt`: sha256 `3a2169a62cecf8725acf402be3222f53399fd5b3467f9f734aa3b2bbd583426c`
  - `llmjudge/RMITIR-GPT4o.txt`: sha256 `7b2a67e6b6215f84377c5b9b3b622aeae6fff54e03806f7b90caec36379293d6`
  - `llmjudge/willia-umbrela1.txt`: sha256 `a7a40aca152a13313b7e39e5356d876f3f7b0d1d8f3ddadc3c4185bde350db01`
  - `llmjudge/NISTRetrieval-instruct0.txt`: sha256 `e4b1d4dc953bed2aa510a111bb221d4c70864778f665b3b26b879f9dae8d8658`

## Settings

Seed 20261009; 1,000 checks per judge and design; start's rule labels 5 from each group at a time. Ranges: `weighted.corrected` at level 0.96, 20,000 draws, seed 20261008. To run it again: `pip install pyarrow`, then `python scripts/real_data_check.py`. It downloads the files above into a cache folder outside the repository, checks each sha256, and writes this report and `report.json`.
