# MLflow fixture from a real store

No store is committed: `make_store.py` builds one in a few seconds, so
`tests/conftest.py` (`mlflow_store`) runs it once per test session in a temporary directory.
It needs the extra (`pip install -e ".[dev,mlflow]"`, as CI does); without mlflow the MLflow
tests skip. To look at the store yourself:

```
python tests/fixtures/mlflow/make_store.py /tmp/jk-mlflow
mlflow ui --backend-store-uri sqlite:////tmp/jk-mlflow/mlflow.db
```

Everything in it is written by MLflow's own API (mlflow 3.16.1 when this was written):
`mlflow.genai.evaluate` with local Python scorers that return `Feedback(source=LLM_JUDGE,
source_id="fake:/judge-model-1")`, `mlflow.log_feedback` and `mlflow.override_feedback` for the
human side. Nothing calls a model API. `make_store.py`'s docstring has the verdict table and
`tests/test_import_mlflow.py` the hand-derived numbers.

What the real store shows, and the reader relies on:
- `Assessment.to_dictionary()` spells the source as `source: {source_type, source_id}` and an
  error as `feedback: {value: null, error: {error_code, error_message}}`.
- Every evaluation run logs new traces with new trace ids; each judge assessment carries its run
  in `metadata["mlflow.assessment.sourceRunId"]`.
- `override_feedback` keeps the judge's assessment with `valid: false` and logs the human one
  with `overrides` set to its id. Both come back from `search_traces`.
- A scorer that returns a bare bool is stored as a `CODE` assessment named after the scorer.
- The `mlflow.assessment.scorerName`/`scorerVersion` metadata is written only for registered
  scorers, which MLflow allows for custom `@scorer` functions on Databricks only. The `concise`
  scorer sets the two keys in its own `Feedback.metadata`, so the store holds them as MLflow
  would; the reader reads them as the rubric version.
