# How much 123 people agree on DICES-350, and one Claude LLM-as-a-judge beside them

This check reads a Label Studio export where many people labelled the same answers, and shows two things: how much the people agree with each other, and how often an LLM-as-a-judge agrees with the experts' label. For each conversation the question is whether the chatbot's last reply is safe (Pass) or unsafe (Fail).

judgekeeper's result: **needs work**. Against the experts' label, the LLM-as-a-judge agreed on 143 of the 175 conversations they passed (82%) and on 94 of the 174 they failed (54%); kappa 0.36. The people agree with each other at Krippendorff's alpha 0.20 (between 0.17 and 0.22), so on this set even people often disagree.

## The setup

- **The conversations:** DICES-350 ([github.com/google-research-datasets/dices-dataset](https://github.com/google-research-datasets/dices-dataset), CC BY 4.0, Copyright Google LLC; Aroyo et al., NeurIPS 2023, [arXiv 2306.11247](https://arxiv.org/abs/2306.11247)): 350 conversations, each rated by all 123 raters. Some are offensive on purpose, so nothing from the dataset is committed. `load.py` downloads one pinned file, checks its SHA-256, and writes outside the repository.
- **The people's labels:** each rater's `Q_overall` answer is one annotation (Yes is Fail, No is Pass); "Unsure" is left out. Raters are numbered 1 to 123. The file also holds each rater's gender, race, age and education; `load.py` never reads those columns.
- **The experts' label:** the dataset's `safety_gold`, one per conversation, added as one more annotation (`completed_by` 124, flagged `ground_truth`). It is the mark the LLM-as-a-judge is measured against, and it counts as one of the 124 people in the agreement number.
- **The LLM-as-a-judge:** `claude-sonnet-5-5`, effort high, with `prompt.txt` word for word, through the Anthropic API (`grade.py`). The API does not accept a temperature for this model, so none was set. Grades and fingerprints are in `grades-setup-a.csv`.
- **When and with what:** graded 2026-11-22, one run. judgekeeper was a development build after 1.3.0 with the Label Studio reader and the people numbers; it prints version 1.3.0.

## What judgekeeper printed

`outputs/run-setup-a.txt` is `judgekeeper results-setup-a.jsonl --labels label-studio-export.json --no-browser --port 0`; `outputs/stop.txt` is `judgekeeper --stop`. `outputs/result-setup-a.json` holds only numbers, keyed by rater number; no rater details and no text.

| Against the experts' label | |
|---|---|
| When the experts said Pass, it also said Pass | 143 of 175 (82%) |
| When the experts said Fail, it also said Fail | 94 of 174 (54%) |
| Disagreed | 112 of 349 |
| Kappa | 0.36 |

Every graded conversation has the experts' label, so these are counted, not sampled.

**How much the people agree with each other:** Krippendorff's alpha 0.20 (between 0.17 and 0.22), on 349 conversations, 124 people. judgekeeper printed: "A check can't be expected to agree with your people more than they agree with each other."

**The LLM-as-a-judge against single people:** judgekeeper printed this for the 10 people with the most labels (each labelled all 349). Kappa ranged from 0.01 (rater 7) to 0.34 (rater 24). The other 114 people are in `result.json`.

## Answers with no grade

The API refused to grade 1 of the 350 conversations (id 217, `refusal` in the CSV); it was not asked again. judgekeeper printed "Skipped 1 label: 1 doesn't match any answer in your results".

## Limits

- One run of one setup.
- The experts' label is one label per conversation; the paper discusses how raters from different groups see safety differently, which this check does not show.
- The agreement number includes the experts' label as one of 124 people.
- The dataset is public (since 2023), so the model may have seen it.
- A development build, not a release. No conversation text and no rater details are in the repository.

## Run it again

```
pip install anthropic
python3 -I load.py OUT
ANTHROPIC_API_KEY=... python3 -I grade.py --export OUT/label-studio-export.json --setup a --out OUT
mkdir project && cp OUT/label-studio-export.json OUT/results-setup-a.jsonl project/ && cd project
judgekeeper results-setup-a.jsonl --labels label-studio-export.json --no-browser --port 0
judgekeeper --stop
```

The grading calls cost money and the model may answer differently the second time.
