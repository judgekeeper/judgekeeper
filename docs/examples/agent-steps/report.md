# A Claude reviewer's first wrong step, against people's, on AgentProcessBench runs

This check starts from agent runs where people labelled the first wrong step, and asks how often a reviewer agent finds the same one. A Claude reviewer read each run with no reference answer and said the number of the first wrong step (0 means all fine).

What `judgekeeper steps` printed, on the 249 runs both labelled: when the people said a run went wrong, the reviewer also said so for 96% (175 of 182; between 92% and 98%). When the people said a run was fine, it also said so for 70% (47 of 67; between 58% and 80%). Kappa 0.71 (between 0.58 and 0.80). On the 175 runs both say went wrong, it named the same first wrong step for 57% (100 of 175; between 50% and 64%) and was within one step for 70% (123 of 175; between 63% and 77%).

## The setup

- **The runs:** the `gaia_dev` runs of AgentProcessBench ([arXiv 2603.14465](https://arxiv.org/abs/2603.14465)); the dataset card says MIT, the GitHub repository has no LICENSE file. `load.py` downloads one pinned file, checks its SHA-256, and writes outside the repository. The dataset is not in this repository.
- **A step** is one agent turn with its tool calls and results. Step N is `steps[N - 1]` in `runs.jsonl`.
- **The people's label:** the smallest step number the dataset marks wrong (-1); 0 if none. A neutral 0 label is not wrong. In the Label Studio export it is a number region `first_wrong_step`.
- **The reviewer:** `claude-sonnet-5-5`, effort high, with `prompt.txt` word for word, through the Anthropic API (`grade.py`). The API does not accept a temperature for this model, so none was set. Its guesses are in `guesses-setup-a.jsonl`, read with `--reviewer`; the grades and fingerprints are in `grades-setup-a.csv`.
- **When and with what:** 2026-11-22, a development build of judgekeeper after 1.3.0 with `judgekeeper steps`. It prints version 1.3.0.

## What judgekeeper printed

`outputs/steps.txt`, from `judgekeeper steps label-studio-export.json --reviewer guesses-setup-a.jsonl`, and `outputs/result.json`, which holds only numbers and the reviewer's fingerprint.

| | Reviewer agrees with the people | Range |
|---|---|---|
| Runs the people say went wrong | 175 of 182 (96%) | 92% to 98% |
| Runs the people say were fine | 47 of 67 (70%) | 58% to 80% |
| Kappa | 0.71 | 0.58 to 0.80 |
| Same first wrong step (on 175 runs both say went wrong) | 100 of 175 (57%) | 50% to 64% |
| Within one step | 123 of 175 (70%) | 63% to 77% |

## What it shows

- The reviewer finds most runs that went wrong, but it also says 20 of the 67 runs the people called fine went wrong.
- When both agree a run went wrong, the reviewer points at the same first wrong step a little more than half the time.
- One run, one reviewer: how much a second run of the same reviewer would change its guesses is not measured here.

## Errors

- 250 runs asked, 249 graded. One run (id 349) was too long for the model's context window; it is recorded as an error (`too_long`) and was not cut down or asked again. judgekeeper printed "Left out: 1 with no guess from this reviewer".
- No refusals and no unreadable replies.

## Limits

- One reviewer, one run, and a prompt written by us; the reviewer is not told the correct answer, which the people may have seen.
- The people's labels are the dataset's; how many people labelled each run, and how often they disagreed, is not in this file.
- The fingerprint in `result.json` is full except temperature (the API takes none).
- A development build, not a release. No task or step text is in the repository.

## Run it again

```
pip install anthropic
python3 -I load.py OUT
ANTHROPIC_API_KEY=... python3 -I grade.py --runs OUT/runs.jsonl --setup a --out OUT
python3 -I load.py OUT --guesses OUT/guesses-setup-a.jsonl
mkdir project && cp OUT/label-studio-export.json OUT/guesses-setup-a.jsonl project/ && cd project
judgekeeper steps label-studio-export.json --reviewer guesses-setup-a.jsonl
```

The grading calls cost money and the reviewer may answer differently the second time.
