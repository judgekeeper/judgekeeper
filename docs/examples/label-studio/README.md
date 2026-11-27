# XSTest in Label Studio shape, graded by two Claude setups

People's labels in a Label Studio export, and two LLM-as-a-judge setups that graded the same
answers. The question: did the AI model comply with the request? Full compliance is Pass; a full
or partial refusal is Fail.

- **Data:** the GPT-4 completions of [XSTest](https://github.com/paul-rottger/xstest)
  (Röttger et al., NAACL 2024, [arXiv 2308.01263](https://arxiv.org/abs/2308.01263)). The prompts
  are CC-BY-4.0. The completions follow their model's terms, so nothing from the dataset is
  committed here: `load.py` downloads one pinned file, checks its SHA-256, and writes outside the
  repository.
- **People's labels:** the dataset's two annotators (`completed_by` 1 and 2) as annotations. The one
  that matches the final label is flagged `ground_truth`. The three-way labels are kept in each
  task's `meta`. A partial refusal is Fail.
- **LLM-as-a-judge setups:** both use [`prompt.txt`](prompt.txt) word for word.
  - Setup A: `claude-sonnet-5-5`, effort `high`.
  - Setup B: `claude-haiku-5-5`, effort `medium`.
  Effort is each model's default, written down so the record says what ran. The API no longer
  accepts a temperature for these models, so none was set and the fingerprint records it as empty.
- **What is committed:** `grades-setup-a.csv` and `grades-setup-b.csv`: an id, a grade, an error
  kind where there was no real decision, and the judge fingerprint of each grade (provider, model,
  snapshot, prompt hash, rubric version, temperature, effort, timestamp). No request or reply text.
  An item the model refused or answered unreadably has grade `none` and is not asked again.

## Run it again

```
pip install anthropic
python3 -I load.py OUT                                  # downloads, writes OUT/label-studio-export.json
ANTHROPIC_API_KEY=... python3 -I grade.py --export OUT/label-studio-export.json --setup a --out OUT
ANTHROPIC_API_KEY=... python3 -I grade.py --export OUT/label-studio-export.json --setup b --out OUT
```

Keep `OUT` outside the repository. `grade.py` writes the raw replies, a records file for
judgekeeper (`results-setup-a.jsonl`, with the text) and the committed CSV. It reads the key from
the environment only. It spends money: it asks the API once per answer.


The outputs here were made with judgekeeper 1.3.0. Newer versions word some lines differently.
