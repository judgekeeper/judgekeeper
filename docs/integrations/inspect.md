# Inspect AI

judgekeeper reads Inspect AI eval logs. Your task does not change.

## Produce the log

```
inspect eval task.py --epochs 3
```

`--epochs 3` (or `epochs=3` in the task) scores every sample three times; each epoch is one run, so the report can measure the judge's run-to-run noise. Logs land in `./logs` (or `INSPECT_LOG_DIR`).

## Import it

```
judgekeeper import inspect logs/2026-09-30T10-00-00_task.json --metric model_graded_qa --labels labels.csv --out reports/qa/
```

`.json` logs are read directly. `.eval` logs (Inspect's default, a zip archive) need the optional extra, which reads any log with `inspect_ai.log.read_eval_log`. Install it in your project's environment:

```
pip install "judgekeeper[inspect]"
```

Without it, convert first: `inspect log dump logs/x.eval > log.json`, or write JSON logs with `--log-format json`. A path can be a log, a folder of logs or a glob; several logs become separate runs.

`--metric` is the scorer's name, the key under `samples[].scores` (`model_graded_qa`, `model_graded_fact`, your `@scorer` name). Item ids are `samples[].id`; runs are `samples[].epoch`.

## Human labels

Two ways, which can be combined:

- **Edit the score.** With `from inspect_ai.log import edit_score, ScoreEdit, ProvenanceData`, `edit_score(log, sample_id, "model_graded_qa", ScoreEdit(value="C", provenance=ProvenanceData(author="you", reason="...")))` keeps the original score in `history`, then write the log back. judgekeeper reads the original value as the judge's verdict and the edited value as the human label for that sample. Edit one epoch per sample; edits that disagree across epochs are a usage error.
- **A labels table:** `--labels labels.csv` with an `id` column (the sample ids) and a `human_label` column. Where both exist for a sample, `--labels` wins, with a note.

## Traps

- **Score values.** `C` reads as pass and `I` as fail. `P` (partial credit) has no default: map it with `--label-map P=fail` (or `P=pass`), otherwise judgekeeper stops and lists the values it cannot read. Numeric values need `--pass-if`, e.g. `--pass-if "score>=0.5"`.
- **Several values at once.** A scorer whose value is a dict (rubric and checklist graders report this way, e.g. `{"accuracy": "C", "tone": "I"}`) is read as one judge per key, named `<scorer>.<key>` (`rubric.tone`); choose one with `--metric`.
- **Agent runs.** Each sample's `messages` are kept as the records' `trajectory` (OpenAI-style steps), so two runs that end in the same answer by different steps stay two answers in `judgekeeper start`.
- **Fingerprint.** The grader model and temperature come from `eval.model_roles.grader` when the task uses the grader role; otherwise from the scorer's `model` option, with temperature unknown. The prompt hash covers the scorer's `template` and `instructions` options from `eval.scorers[]`; one left unset stands for Inspect's default for that scorer (with default instructions, `partial_credit` is included because it changes them). A scorer that sets neither, such as plain `model_graded_qa()`, gets a hash of that default identity, the same for every sample. The rendered prompt in `score.metadata.grading` is never hashed: it holds each sample's text. If you upgrade Inspect and its default template changes, the hash does not; set `template` explicitly to track it.
- **`--no-log-samples`** logs have no samples and cannot be read.
