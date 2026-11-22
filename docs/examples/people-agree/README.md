# DICES-350: how much people agree, and one Claude setup beside them

Many people labelled the same answers in a Label Studio export, and one LLM-as-a-judge setup
graded them too. The question: is the chatbot's last reply safe? Pass is safe, Fail is unsafe.

- **Data:** [DICES-350](https://github.com/google-research-datasets/dices-dataset), CC BY 4.0,
  Copyright Google LLC (Aroyo et al., NeurIPS 2023,
  [arXiv 2306.11247](https://arxiv.org/abs/2306.11247)): 350 conversations between a person and a
  chatbot, each rated by all 123 raters. Some conversations are offensive on purpose, so nothing
  from the dataset is committed here: `load.py` downloads one pinned file, checks its SHA-256, and
  writes outside the repository.
- **People's labels:** each rater's `Q_overall` answer becomes one annotation (Yes is Fail, No is
  Pass). "Unsure" is left out: that rater has no annotation on that conversation. Raters are
  numbered with small integers in `completed_by`. The file also holds each rater's gender, race, age
  and education; `load.py` never reads those columns into its output, and nothing in this folder
  names a rater.
- **LLM-as-a-judge setup:** `claude-sonnet-5-5`, effort `high` (the model's default, written down so
  the record says what ran), with [`prompt.txt`](prompt.txt) word for word. The API no longer
  accepts a temperature for this model, so none was set and the fingerprint records it as empty.
- **What is committed:** `grades-setup-a.csv`: an id (the dataset's `item_id`), a grade, an error
  kind where there was no real decision, and the judge fingerprint of each grade (provider, model,
  snapshot, prompt hash, rubric version, temperature, effort, timestamp). No conversation text. If
  the API refused a conversation or its reply could not be read, the grade is `none` and the error
  kind says which; it was not asked again with another prompt.

## Run it again

```
pip install anthropic
python3 -I load.py OUT                                  # downloads, writes OUT/label-studio-export.json
ANTHROPIC_API_KEY=... python3 -I grade.py --export OUT/label-studio-export.json --setup a --out OUT
```

Keep `OUT` outside the repository. `grade.py` writes the raw replies, a records file for
judgekeeper (`results-setup-a.jsonl`, with the text) and the committed CSV. It reads the key from
the environment only. It spends money: it asks the API once per conversation.

There is no report in this folder yet.
