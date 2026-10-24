# judgekeeper on JailbreakBench's judge-comparison set

This check asks one question: when judgekeeper estimates how often an LLM-as-a-judge agrees with experts, does the real value fall inside the range it prints?

That needs a set where the real value is known. JailbreakBench published one: 300 answers, each graded by GPT-4 and by three experts. judgekeeper got the GPT-4 grades and the experts' marks and ran its normal steps; its estimates were then compared with the real values on all 300 answers.

No AI calls were made. The GPT-4 grades come from the paper's own run.

## The result

- **In 20 of 20 draws, judgekeeper's ranges held the real value for GPT-4 against experts:** TPR, TNR and kappa, all three in the same draw. Each draw marked the answers in two batches, on judgekeeper 1.0.0b2, commit `6437d85` (the code that ships as 1.0). See "Two batches, 20 draws" below.
- **One more single draw on the same code missed the real TNR.** Its TNR range was 92% to 100%; the real TNR is 90.9%. The 50 answers GPT-4 passed that this draw happened to show held none of the 10 the experts failed (about 3 to 4 draws in 100 go like this). TPR and kappa held. See "One round on the final code" below.
- **An earlier run of 20 single draws** (commit `e3052c7`) held all three real values in 20 of 20.

## What was checked

- **The data:** the Hugging Face dataset `JailbreakBench/JBB-Behaviors`, config `judge_comparison`, file `data/judge-comparison.csv`, revision `886acc352a31533ffbcf4ef22c744658688086fc`. SHA-256 `dacaf76a1057785f11b0fc6aa07b9a73cdab588319ddfc5e8cef2909e5b112a5`, 300 rows, MIT license. `load.py` downloads it; the data is not in this repository.
- **The paper:** Chao et al., "JailbreakBench: An Open Robustness Benchmark for Jailbreaking Large Language Models", NeurIPS 2024 Datasets and Benchmarks Track, arXiv 2404.01318 (v5), Table 1. The paper names the judge as GPT-4-0613, and the ground truth as the majority vote of three expert annotators.
- **The judge:** the dataset's `gpt4_cf` column.
- **The marks:** its `human_majority` column.

## The mapping (fixed before the run)

| | Pass | Fail |
|---|---|---|
| Judge (`gpt4_cf`) | 0, not jailbroken | 1, jailbroken |
| Marks (`human_majority`) | 0, not jailbroken | 1, jailbroken |

Each row became one line of an own-format JSONL file: `id`, `input` (the prompt), `output` (the response), `verdict` (pass or fail). The judge model was given as `--judge-model openai:gpt-4-0613`.

## How it ran

1. **Find.** `judgekeeper` read the file: 300 answers, 181 Pass and 119 Fail from the judge.
2. **Mark.** The marking page offered 100 answers: 50 the judge passed and 50 it failed. A script entered the experts' majority for each one, through the page's own calls (the same calls a click makes). It never saw the judge's grade while marking.
3. **Measure.** `judgekeeper` was run again and printed its result.

## The real values, on all 300 answers

Every answer has both grades, so these are counted, not estimated. The range in brackets is what you would get if the 300 were a sample of more answers like them (Wilson, 95%).

| | Real value | Count |
|---|---|---|
| TPR: experts say Pass, GPT-4 also says Pass | 90.0% (84.9% to 93.5%) | 171 of 190 |
| TNR: experts say Fail, GPT-4 also says Fail | 90.9% (84.1% to 95.0%) | 100 of 110 |
| Kappa | 0.795 | from the four counts below |
| Agreement, both kinds together | 90.3% (86.5% to 93.2%) | 271 of 300 |

The four counts:
- experts Pass and GPT-4 Pass: 171;
- experts Pass and GPT-4 Fail: 19;
- experts Fail and GPT-4 Pass: 10;
- experts Fail and GPT-4 Fail: 100.

These match the paper's Table 1 for GPT-4. The paper counts "jailbroken" as positive, so its FPR is 1 minus the TPR here and its FNR is 1 minus the TNR here:

| Paper (Table 1, GPT-4) | Paper | From the dataset |
|---|---|---|
| Agreement | 90.3% | 90.3% (86.5% to 93.2%), 271 of 300 |
| FPR | 10.0% | 10.0% (6.5% to 15.1%), 19 of 190 |
| FNR | 9.1% | 9.1% (5.0% to 15.9%), 10 of 110 |

The paper gives no ranges and no kappa. Kappa 0.795 is computed from the dataset.

## Two batches, 20 draws (commit `6437d85`)

New answers can join the marking as a second batch. This repeat checks that the ranges still hold when they do. Each draw used a fresh project folder, so judgekeeper picked a new random seed and showed different answers.

1. **Batch 1.** The results file held rows 0 to 149. The script marked every answer the page offered with the experts' majority, and Measure ran.
2. **Batch 2 joins.** The results file was written again with all 300 rows, the same judge's grades. `judgekeeper mark` added the 150 new answers as batch 2 (rows 150 to 299), and the script marked the batch-2 answers the page offered.
3. **Measure on both batches**, then the real TPR, TNR and kappa on all 300 rows were compared with judgekeeper's ranges.

The bar was 19 of 20 draws with all three real values inside in the same draw. Result (`two-batches/summary.json`):

- all three inside: **20 of 20 draws**;
- TPR inside 20 of 20, TNR inside 20 of 20, kappa inside 20 of 20;
- every draw counted the marks from both batches, put batch 2 exactly on rows 150 to 299, and showed no dataset text on any screen.

Draw 1's Measure after both batches (`two-batches/measure-batches-1-2.txt`, copied exactly):

```
Result: your judge is good enough to use.
You and your judge disagreed on 24 of 250 answers.

  You passed 168 answers. Of those, your judge passed 151 and failed 17.
  You failed 82 answers. Of those, your judge passed 7 and failed 75.

How often your judge agrees with you (estimates):
  When you say Pass, it also says Pass: about 89% (between 84% and 93%)
  When you say Fail, it also says Fail: about 91% (between 83% and 95%)
```

Every draw's estimates and ranges are in `two-batches/draws.csv`.

## One round on the final code (commit `6437d85`)

The first round of the check (100 marks, one batch) was run once more on `6437d85`. Measure printed (`measure-round-1.txt`, the result lines copied exactly):

```
Result: your judge is good enough to use.
You and your judge disagreed on 7 of 100 answers.

  You passed 57 answers. Of those, your judge passed 50 and failed 7.
  You failed 43 answers. Of those, your judge passed 0 and failed 43.

How often your judge agrees with you (estimates):
  When you say Pass, it also says Pass: about 92% (between 85% and 96%)
  When you say Fail, it also says Fail: about 100% (between 92% and 100%)
```

| | Real value | This draw | Inside? |
|---|---|---|---|
| TPR | 90.0% (84.9% to 93.5%) | about 92% (85% to 96%) | Yes |
| TNR | 90.9% (84.1% to 95.0%) | about 100% (92% to 100%) | **No** |
| Kappa | 0.795 | 0.88 (0.76 to 0.94) | Yes |

**Why TNR missed.** The page showed 50 answers GPT-4 passed. In all 300, GPT-4 passed 10 answers the experts failed; this draw's 50 held none of them. So in this draw, GPT-4 never passed an answer the experts failed, and judgekeeper's TNR range sat above the real value. A draw like this comes up about 3 to 4 times in 100: a range holds the real value most of the time, not every time. It is reported as it came out; it was not drawn again.

## The first run (commit `e3052c7`)

The check was first run on judgekeeper 1.0.0b2, commit `e3052c7` (2026-10-17). These are that run's results; the files are in `first-run/`.

### After 100 marks

Measure said "Result: too early to tell. Mark more answers to get a result." with 10 disagreements in 100 (`first-run/measure-round-1.txt`). "Too early to tell" means the Fail range still reaches below 80%, so judgekeeper does not give a verdict yet. At this point the terminal shows only the counts. The estimates are in the report page, under "More details" (`first-run/report-round-1.html`):

| How often the judge agrees with the experts | Estimate | Range (middle 96%) |
|---|---|---|
| When the experts say Pass, GPT-4 also says Pass (TPR) | about 91% | 84% to 96% |
| When the experts say Fail, GPT-4 also says Fail (TNR) | about 90% | 78% to 97% |
| Kappa (agreement beyond coincidence) | 0.81 | 0.65 to 0.90 |

judgekeeper shows half Pass and half Fail answers from the judge, so it weights each half by its real share before it gives a number. Without that weighting, the 100 marks alone would say 87% (76% to 94%) and 93% (83% to 98%).

### After 200 marks

The script then followed the Next line: `judgekeeper mark`. The page offered 100 more answers, the script marked them the same way, and Measure printed (`first-run/measure-round-2.txt`, the result lines copied exactly):

```
Result: your judge is good enough to use.
You and your judge disagreed on 20 of 200 answers.

  You passed 108 answers. Of those, your judge passed 94 and failed 14.
  You failed 92 answers. Of those, your judge passed 6 and failed 86.

How often your judge agrees with you (estimates):
  When you say Pass, it also says Pass: about 91% (between 86% and 95%)
  When you say Fail, it also says Fail: about 90% (between 82% and 96%)
```

The report page (`report.html`) gives kappa 0.81, range 0.70 to 0.88.

The second 100 happened to split exactly like the first (47, 3, 7, 43). So the estimates did not move; only the ranges got narrower.

| | Real value | After 100 marks | Inside? | After 200 marks | Inside? |
|---|---|---|---|---|---|
| TPR | 90.0% (84.9% to 93.5%) | about 91% (84% to 96%) | Yes | about 91% (86% to 95%) | Yes |
| TNR | 90.9% (84.1% to 95.0%) | about 90% (78% to 97%) | Yes | about 90% (82% to 96%) | Yes |
| Kappa | 0.795 | 0.81 (0.65 to 0.90) | Yes | 0.81 (0.70 to 0.88) | Yes |

### The same first round, 20 more times

The marking page picks its 100 answers at random, so a new project folder gets a different 100. The first round ran again in 20 fresh folders (`first-run/repeat-draws.csv`).

- In all 20, the real TPR, TNR and kappa were each inside judgekeeper's range.
- After 100 marks, 7 of the 20 said "Your judge is good enough to use." The other 13 said "Too early to tell", because the Fail range still reached below 80%. None said the judge needs work.
- Disagreements in the 100 ranged from 7 to 16.

So with 100 marks, whether you get a verdict yet depends on which answers you were shown.

## Limits

- **One judge and one task:** GPT-4-0613, judging whether a response is a jailbreak. Other judges and tasks can behave differently.
- **Old grades:** the GPT-4 grades come from the paper's run. GPT-4 was not called again, so this checks judgekeeper's numbers, not today's GPT-4.
- **The answers:** 300 in all, 200 jailbreak attempts and 100 harmless prompts the paper took from XSTest.
- **The marks:** the experts' majority vote, entered by a script. A person marking by hand may mark differently. judgekeeper says so on every Measure screen here.
- **Harmful text:** the prompts and responses are harmful, so they are never published. The files here hold row ids and grades only. Row `jbb-NNN` is the dataset's `Index` NNN.

## Files

- **`load.py`:** downloads the dataset at the pinned revision, checks its SHA-256, and writes it as a results file judgekeeper reads (`python3 -I load.py`). Its `cache/` folder is never committed.
- **`ids-and-grades.csv`:** row id, GPT-4 grade, expert majority, and whether it was marked in the round on `6437d85`. No text.
- **`measure-round-1.txt`, `true-figures.json`:** the Measure screen and the figures of the round on `6437d85`.
- **`two-batches/`:** `draws.csv` (each draw's counts, ranges and inside yes/no), `summary.json` (the real values and the 20-draw result), and draw 1's Measure screens after batch 1 and after both batches.
- **`report.html`:** judgekeeper's report page after 200 marks in the first run, with each prompt and response replaced by its row id.
- **`first-run/`:** the first run's Measure screens, report page after 100 marks, ids and grades, figures, and the 20 repeat draws.

Every CSV, text and JSON file here starts with the same header: the dataset, its revision, the subset and split, and where the grades come from. The report pages carry it as a comment.

Both report pages use 1.0's colours, for easier reading; their numbers and contents are as the runs made them.

Data: JailbreakBench, Chao et al., NeurIPS 2024 Datasets and Benchmarks Track, MIT license, Copyright (c) 2023 JailbreakBench Team. The license and the full citation are in [THIRD_PARTY_NOTICES.md](../../../THIRD_PARTY_NOTICES.md).
