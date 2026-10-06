# MLflow

judgekeeper reads the judge and human assessments MLflow already stores on your traces, from the tracking store itself. No export step, and nothing in your setup changes.

## How scores get there

`mlflow.genai.evaluate(data=..., predict_fn=..., scorers=[...])` runs your app and your scorers and logs one `Feedback` assessment per scorer per trace. An LLM judge's assessment has `source.source_type` `LLM_JUDGE` and `source.source_id` set to the model (`openai:/gpt-4.1-mini`). Run the evaluation three times to measure the judge's run-to-run noise: each MLflow run is one judgekeeper run.

## Import it

```
pip install "judgekeeper[mlflow]"                # in your project's environment
judgekeeper import mlflow --experiment my-app-eval --metric correctness --out reports/correctness/
```

The tracking URI is `MLFLOW_TRACKING_URI` (or `--tracking-uri`), resolved exactly as MLflow resolves it: a local `mlruns` folder, a SQL store (`sqlite:///mlflow.db`), a tracking server or Databricks (`databricks`, with `DATABRICKS_HOST` and `DATABRICKS_TOKEN`). MLflow handles the credentials; judgekeeper never writes them anywhere. A local `mlruns` folder needs MLflow's folder-store setting from MLflow 3.16 on: judgekeeper switches it on (`MLFLOW_ALLOW_FILE_STORE=true`) for its own read only, says so once, and leaves your own value alone when you set one.

- `--experiment` takes a name or an id.
- `--metric` is the assessment name (your scorer's name). With several judge assessment names and no `--metric`, judgekeeper stops and lists them.
- `--run-id ID` (repeatable) keeps only those runs' judge assessments. By default every run with judge assessments is read, in start order.
- `--id-from KEY` reads a stable item id from a trace tag or a key of the request input.
- `--temperature T` records the judge's temperature, which MLflow does not store.
- `--labels`, `--pass-if` and `--label-map` work as for every `import`.

## Human labels

Three ways, which combine:

- **Human feedback.** `mlflow.log_feedback(trace_id=..., name="correctness", value=False, source=AssessmentSource(source_type="HUMAN", source_id="you@example.com"))`, or the MLflow UI's assessment panel. A human assessment named like the judge's (or named after no judge) is the label for that item.
- **Override.** `mlflow.override_feedback(trace_id=..., assessment_id=<the judge's>, value=...)` marks the judge's assessment `valid: false` and logs yours with `overrides` set. judgekeeper reads the overridden value as the judge's verdict and the override as the human label: an explicit disagreement.
- **A labels table:** `--labels labels.csv` with `id` and `human_label` columns. It wins where both exist, with a note. Use `--id-from` so the ids are ones you can write down.

Label one evaluation run's traces: ids come from the request input, so a label applies to the same row in every run.

## Traps

- **Trace ids change every run.** `evaluate` with a `predict_fn` logs new traces each time, so a trace id is not an item id. judgekeeper derives the id from the trace's request input (a hash, as in `check`), so the same dataset row maps to the same item in every run, and says so in the report. Two rows with the same input are one item; give them a tag or input key and pass `--id-from`.
- **Which run.** A judge assessment's run is its `mlflow.assessment.sourceRunId` metadata, which `evaluate` sets, also when it scores existing traces (then one trace carries the assessments of several runs). Assessments logged outside `evaluate` have none and form one extra run, listed last, with a note.
- **Prompt and temperature.** The fingerprint has the model from `source.source_id` (the provider is the part before `:/`) and, for registered scorers, `scorerName@scorerVersion` as the rubric version. MLflow does not save the judge's prompt with its assessments, and scorer tracing is off by default, so the prompt hash is unknown and the report flags it. Temperature is unknown unless you pass `--temperature`.
- **Errors.** A `Feedback` with an `error` (a judge that timed out) is an `error` verdict, with the error code and message as its rationale.
- **CODE assessments** (a scorer that returns a bare bool or number) are not a judge and are ignored, with a note. Expectations (ground truth) are not verdicts and are not read.
- **Span-level assessments.** An assessment logged on one span inside a trace (`span_id`) judges a step, not the answer. Only trace-level assessments (and those on the root span, where `evaluate` puts them) are read as the judge's verdicts; span-level ones are left out with a note, unless `--metric` names a judge that is only on spans. A judge on both never mixes them. The span id is kept in each record's `metadata`.
- **One run.** With a single evaluation run the noise floor is "unknown". Re-run `evaluate`, or use the re-judge path below.

## Re-judge the labeled items

The import measures the judgments MLflow already holds. For a noise floor you control, freeze the labeled items as an anchor set and judge them again:

```
judgekeeper import mlflow --experiment my-app-eval --metric correctness \
  --anchors-out anchors/correctness.jsonl --out reports/correctness/
judgekeeper judge anchors/correctness.jsonl --callable myjudges:correctness --runs 3 --out runs/correctness/
judgekeeper validate anchors/correctness.jsonl runs/correctness/ --out reports/correctness-rejudged/
```

`--anchors-out` writes every item with a human label (id, the trace's request input and response, the label) and freezes it. Rationales and annotator ids are never written. Any judge works: `--runner`, `--callable` or `--exec`. This is the recommended path for platform data: the anchor set is frozen and versioned in your repo, and `gate` and `migrate` work on it from then on.
