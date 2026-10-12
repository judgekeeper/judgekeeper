# MLflow

judgekeeper reads the judge and human assessments MLflow already stores on your traces, from the tracking store itself. No export step, and nothing in your setup changes.

Tested with MLflow 3.10 or newer. `judgekeeper[mlflow]` allows MLflow 3.1, but 3.10 is the oldest tested.

## How scores get there

`mlflow.genai.evaluate(data=..., predict_fn=..., scorers=[...])` runs your app and your scorers and logs one `Feedback` assessment per scorer per trace. An LLM judge's assessment has `source.source_type` `LLM_JUDGE` and `source.source_id` set to the model (`openai:/gpt-4.1-mini`).

## Read it

```
pip install "judgekeeper[mlflow]"                # in your project's environment
judgekeeper start --experiment my-app-eval --metric correctness
```

`judgekeeper start` reads the local store in your project folder: `mlflow.db` or an `mlruns/` folder (`--tracking-uri` picks one when there are both). A local `mlruns` folder needs MLflow's folder-store setting from MLflow 3.16 on: judgekeeper switches it on (`MLFLOW_ALLOW_FILE_STORE=true`) for its own read only, says so once, and leaves your own value alone when you set one.

- `--experiment` takes a name or an id.
- `--metric` is the assessment name (your scorer's name). With several judge assessment names and no `--metric`, judgekeeper asks which.

## Traps

- **Trace ids change every run.** `evaluate` with a `predict_fn` logs new traces each time, so a trace id is not an item id. judgekeeper derives the id from the trace's request input (a hash), so the same dataset row maps to the same item in every run. Two rows with the same input are one item.
- **Which run.** A judge assessment's run is its `mlflow.assessment.sourceRunId` metadata, which `evaluate` sets, also when it scores existing traces (then one trace carries the assessments of several runs). Assessments logged outside `evaluate` have none and form one extra run, listed last, with a note.
- **Prompt and temperature.** The fingerprint has the model from `source.source_id` (the provider is the part before `:/`) and, for registered scorers, `scorerName@scorerVersion` as the rubric version. A `make_judge` (MLflow 3.14 and later) saves its instructions with each assessment: they are the judge's rule, hashed into the prompt hash, so a changed rule is a new judge. Other judges' prompts are not saved with their assessments, and scorer tracing is off by default, so for them the prompt hash is unknown. Temperature is unknown.
- **Errors.** A `Feedback` with an `error` (a judge that timed out) is an `error` verdict, with the error code and message as its rationale.
- **CODE assessments** (a scorer that returns a bare bool or number) are not a judge and are ignored, with a note. Expectations (ground truth) are not verdicts and are not read.
- **Span-level assessments.** An assessment logged on one span inside a trace (`span_id`) judges a step, not the answer. Only trace-level assessments (and those on the root span, where `evaluate` puts them) are read as the judge's verdicts; span-level ones are left out with a note, unless `--metric` names a judge that is only on spans. A judge on both never mixes them. The span id is kept in each record's `metadata`.
- **A copied `mlruns/` folder.** A folder store saves where each trace's files are as a full path. Copied or cloned to another computer, MLflow looks for them at the old path and drops every trace it cannot find, with one warning each. judgekeeper reads them from the store's own folder instead, and says how many answers it left out when their files are not there either.
- **MLflow's own problems, not judgekeeper's.** Two that new users meet: `mlflow.genai.evaluate` on an `mlflow.db` store can drop traces when it runs out of database connections, while still saying the evaluation completed (fewer parallel workers, `MLFLOW_GENAI_EVAL_MAX_WORKERS=4`, avoids it); and an experiment made in `mlflow.db` keeps its artifacts in `./mlruns/` by default, inside a folder store if you also have one (give the experiment its own `artifact_location`). judgekeeper only counts the traces that were saved.
