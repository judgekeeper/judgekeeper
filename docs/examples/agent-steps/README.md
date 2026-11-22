# AgentProcessBench: the first wrong step of an agent run, by people and by a Claude reviewer

Agent runs with a person's label for the first wrong step, and one reviewer agent that read each run
and said which step it thinks went wrong first (0 means all fine).

- **Data:** the `gaia_dev` runs of
  [AgentProcessBench](https://huggingface.co/datasets/LulaCola/AgentProcessBench)
  ([arXiv 2603.14465](https://arxiv.org/abs/2603.14465)). The dataset card says MIT; the project's
  GitHub repository has no LICENSE file. Nothing from the dataset is committed here: `load.py`
  downloads one pinned file, checks its SHA-256, and writes outside the repository.
- **A step** is one turn of the agent: what it wrote, its tool calls, and everything that came back
  before its next turn. Step N is `steps[N - 1]` in `runs.jsonl`.
- **People's label (`first_wrong_step`):** the dataset marks each assistant turn 1 (good), 0 (neutral)
  or -1 (wrong). The first wrong step is the smallest step number marked -1; if none is, it is 0,
  all fine. A neutral 0 is not wrong.
- **Reviewer agent:** `claude-sonnet-5-5`, effort `high` (the model's default, written down so the
  record says what ran), with [`prompt.txt`](prompt.txt) word for word. It reads the task and every
  step and gets no reference answer. The API no longer accepts a temperature for this model, so none
  was set and the fingerprint records it as empty. A run too long for the model's context window is
  an error, not cut down.
- **`load.py` writes** `runs.jsonl` (`id`, `task`, `steps`), and a Label Studio export where the
  people's label is the annotation (a number region `first_wrong_step`) and the reviewer's guess is a
  prediction whose `model_version` is the model's name.
- **What is committed:** `grades-setup-a.csv`: a run id (the dataset's `total_index`), the
  reviewer's guess, an error kind where there was no real guess, and the judge fingerprint of each
  grade (provider, model, snapshot, prompt hash, rubric version, temperature, effort, timestamp).
  No task or step text.

## Run it again

```
pip install anthropic
python3 -I load.py OUT                                  # downloads, writes OUT/runs.jsonl
ANTHROPIC_API_KEY=... python3 -I grade.py --runs OUT/runs.jsonl --setup a --out OUT
python3 -I load.py OUT --guesses OUT/guesses-setup-a.jsonl   # adds the reviewer's guesses
mkdir project && cp OUT/label-studio-export.json OUT/guesses-setup-a.jsonl project/ && cd project
judgekeeper steps label-studio-export.json --reviewer guesses-setup-a.jsonl
```

Each line of `guesses-setup-a.jsonl` carries the reviewer's fingerprint (provider, model, snapshot,
prompt hash, rubric version, temperature), so `judgekeeper steps` can show it.

Keep `OUT` outside the repository. `grade.py` reads the key from the environment only. It spends
money: it asks the API once per run, and the runs are long.

There is no report in this folder yet.
