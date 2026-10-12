# Inspect AI

judgekeeper reads Inspect AI eval logs. Your task does not change.

Tested with Inspect AI 0.3.242 to 0.3.278. Asking your judge again and trying a new judge need Inspect AI 0.3.242 or newer.

## Produce the log

```
inspect eval task.py
```

Logs land in `./logs` (or `INSPECT_LOG_DIR`).

## Read it

```
judgekeeper start --metric model_graded_qa
```

`.json` logs are read directly. `.eval` logs (Inspect's default, a zip archive) need the optional extra, which reads any log with `inspect_ai.log.read_eval_log`. Install it in your project's environment:

```
pip install "judgekeeper[inspect]"
```

Without it, convert first: `inspect log dump logs/x.eval > log.json`, or write JSON logs with `--log-format json`. To read one log, give its path: `judgekeeper start logs/log.json`.

`--metric` is the scorer's name, the key under `samples[].scores` (`model_graded_qa`, `model_graded_fact`, your `@scorer` name). Item ids are `samples[].id`; runs are `samples[].epoch`.

## Traps

- **Score values.** `C` reads as pass and `I` as fail. `P` (partial credit) has no default: map it with `--label-map P=fail` (or `P=pass`), otherwise judgekeeper stops and lists the values it cannot read. Numeric values need `--pass-if`, e.g. `--pass-if "score>=0.5"`.
- **Several values at once.** A scorer whose value is a dict (rubric and checklist graders report this way, e.g. `{"accuracy": "C", "tone": "I"}`) is read as one judge per key, named `<scorer>.<key>` (`rubric.tone`); choose one with `--metric`.
- **Agent runs.** Each sample's `messages` are kept as the records' `trajectory` (OpenAI-style steps), so two runs that end in the same answer by different steps stay two answers in `judgekeeper start`.
- **Fingerprint.** The grader model and temperature come from `eval.model_roles.grader` when the task uses the grader role; otherwise from the scorer's `model` option, with temperature unknown. The prompt hash covers the scorer's `template` and `instructions` options from `eval.scorers[]`; one left unset stands for Inspect's default for that scorer (with default instructions, `partial_credit` is included because it changes them). A scorer that sets neither, such as plain `model_graded_qa()`, gets a hash of that default identity, the same for every sample. The rendered prompt in `score.metadata.grading` is never hashed: it holds each sample's text. If you upgrade Inspect and its default template changes, the hash does not; set `template` explicitly to track it.
- **`--no-log-samples`** logs have no samples and cannot be read.
