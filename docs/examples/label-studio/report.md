# Two Claude LLM-as-a-judge setups on XSTest, read from a Label Studio export

This check starts from a Label Studio export with two people's labels on 450 answers, and asks how often an LLM-as-a-judge agrees with them. Nobody marked anything new: judgekeeper read the labels from the export with `--labels`. For each answer the question is whether the AI model complied with the request (Pass) or refused, fully or in part (Fail).

judgekeeper's result for setup A: **good enough to use**. On the 447 answers it graded, it agreed with the people on all 230 they passed and on 190 of the 217 they failed (88%); kappa 0.88. Setup B, a different model, then agreed on 230 of 230 and 211 of 217, and judgekeeper's `check` said it now agrees with the people more than before.

## The setup

- **The answers:** the GPT-4 completions of XSTest (Röttger et al., NAACL 2024, [arXiv 2308.01263](https://arxiv.org/abs/2308.01263)). The prompts are CC-BY-4.0; the completions follow their model's terms, so nothing from the dataset is committed here. `load.py` downloads one pinned file, checks its SHA-256, and writes outside the repository.
- **The people's labels:** the dataset's two annotators, as two annotations per task (`completed_by` 1 and 2) in a Label Studio export. The one that matches the dataset's final label is flagged `ground_truth`; that is the mark. A partial refusal is Fail.
- **Setup A:** `claude-sonnet-5-5`, effort high. **Setup B:** `claude-haiku-5-5`, effort medium. Both use `prompt.txt` word for word, through the Anthropic API (`grade.py`). The API does not accept a temperature for these models, so none was set. The grades and fingerprints are in `grades-setup-a.csv` and `grades-setup-b.csv`.
- **When and with what:** graded 2026-11-22, one run per setup. judgekeeper was a development build after 1.3.0 with the Label Studio reader and the people numbers; it prints version 1.3.0.

## What judgekeeper printed

`outputs/run-setup-a.txt` is `judgekeeper results-setup-a.jsonl --labels label-studio-export.json --no-browser --port 0`. `outputs/check-setup-b.txt` is `judgekeeper check results-setup-b.jsonl`. `outputs/stop.txt` is `judgekeeper --stop`. The `result-*.json` files hold only numbers and fingerprints.

| | When the people said Pass, it also said Pass | When the people said Fail, it also said Fail | Disagreed | Kappa |
|---|---|---|---|---|
| Setup A (Sonnet 5.5) | 230 of 230 (100%) | 190 of 217 (88%) | 27 of 447 | 0.88 |
| Setup B (Haiku 5.5) | 230 of 230 (100%) | 211 of 217 (97%) | 6 of 447 | 0.97 |

Every graded answer has a label, so these are counted, not sampled, and have no range. Setup B's row is from `result-check-setup-b.json`.

**How much the two people agree with each other:** kappa 0.99 (between 0.98 and 1.00), on all 447 answers. Setup A against each person: kappa 0.88. judgekeeper also printed: "A check can't be expected to agree with your people more than they agree with each other."

**What `check` said about setup B:** no drop bigger than 20 points in either group, and "Your LLM-as-a-judge now agrees with your people more than before, on the 447 answers they labelled." It also said: "One run, so a small change may be a coincidence."

## Answers with no grade

Setup A did not grade 3 of the 450 answers (ids 431, 442 and 443): the API refused them (`refusal` in the CSV). They were not asked again. judgekeeper printed "Skipped 3 labels: 3 are for questions that are not in your results". Setup B graded all 450; `check` compares the 447 both graded.

## Limits

- One run per setup. A second run of the same setup may move a few answers.
- Two people, who agree almost always on this set; most real projects will see lower agreement between people.
- The dataset is public (since 2023), so the models may have seen it.
- A development build, not a release. No request or reply text is in the repository.

## Run it again

```
pip install anthropic
python3 -I load.py OUT
ANTHROPIC_API_KEY=... python3 -I grade.py --export OUT/label-studio-export.json --setup a --out OUT
ANTHROPIC_API_KEY=... python3 -I grade.py --export OUT/label-studio-export.json --setup b --out OUT
mkdir project && cp OUT/label-studio-export.json OUT/results-setup-*.jsonl project/ && cd project
judgekeeper results-setup-a.jsonl --labels label-studio-export.json --no-browser --port 0
judgekeeper --stop
judgekeeper check results-setup-b.jsonl
```

The grading calls cost money and the models may answer differently the second time.
