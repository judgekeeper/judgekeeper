"""Build a real MLflow store for tests/test_import_mlflow.py: no API call, no network.

    python tests/fixtures/mlflow/make_store.py /tmp/mlflow-fixture

writes `mlflow.db` (SQLite tracking store) and `artifacts/` there and prints the tracking URI.
tests/test_import_mlflow.py calls `build()` once per test session (about ten seconds).

What MLflow is asked to do, through its public API only:
- Experiment "qa-judge". `app(qid, question)` is a plain traced Python function; it tags its
  trace with `row_id`.
- Three `mlflow.genai.evaluate` runs over the same 8 rows (Q0-Q7) with `predict_fn=app`, so
  every run logs 8 new traces with new trace ids.
- Scorers are local Python functions (no model call):
  `correctness` returns `Feedback(value=<bool>, source=LLM_JUDGE "fake:/judge-model-1")`;
  `concise` returns "yes"/"no" from the same source with the scorer name and version metadata
  keys, and a `Feedback(error=...)` for Q7 in run 1;
  `has_answer` returns a bare bool, which MLflow records as a CODE assessment.
- Humans label `correctness` on run 1's traces with `mlflow.log_feedback` (source HUMAN), except
  Q4, where `mlflow.override_feedback` overrides the judge's assessment.

`build(root, note=...)` appends `note` to every judge rationale (tests/test_leak.py puts keys
there). Human labels: Q0-Q3 pass, Q4-Q7 fail. `correctness` passes:
  run 1: Q0 Q1 Q2 Q4      run 2: Q0 Q1 Q2 Q3      run 3: Q0 Q1 Q3 Q5
"""

from __future__ import annotations

import inspect
import os
import sys
from pathlib import Path

EXPERIMENT = "qa-judge"
JUDGE_MODEL = "fake:/judge-model-1"
ITEMS = [f"Q{i}" for i in range(8)]
HUMAN = {q: i < 4 for i, q in enumerate(ITEMS)}
CORRECTNESS = {
    1: {"Q0", "Q1", "Q2", "Q4"},
    2: {"Q0", "Q1", "Q2", "Q3"},
    3: {"Q0", "Q1", "Q3", "Q5"},
}
OVERRIDDEN = "Q4"
CONCISE_ERROR = (1, "Q7")
SCORER_VERSION = "2"


def build(root: str | Path, note: str = "") -> str:
    """Create the store under `root`; return its tracking URI."""
    os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")
    os.environ["MLFLOW_GENAI_EVAL_SKIP_TRACE_VALIDATION"] = "true"
    import mlflow
    from mlflow.entities import AssessmentError, AssessmentSource, Feedback
    from mlflow.genai.scorers import scorer

    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    uri = f"sqlite:///{root / 'mlflow.db'}"
    mlflow.set_tracking_uri(uri)
    exp_id = mlflow.create_experiment(EXPERIMENT, artifact_location=(root / "artifacts").as_uri())
    mlflow.set_experiment(experiment_id=exp_id)
    judge = AssessmentSource(source_type="LLM_JUDGE", source_id=JUDGE_MODEL)
    state = {"run": 0}

    @mlflow.trace
    def app(qid: str, question: str) -> str:
        mlflow.update_current_trace(tags={"row_id": qid})
        return f"Answer to {question.lower()}"

    @scorer
    def correctness(inputs, outputs):
        ok = inputs["qid"] in CORRECTNESS[state["run"]]
        return Feedback(value=ok, source=judge,
                        rationale=f"run {state['run']}: {'correct' if ok else 'wrong'}{note}")

    @scorer
    def concise(inputs, outputs):
        metadata = {"mlflow.assessment.scorerName": "concise",
                    "mlflow.assessment.scorerVersion": SCORER_VERSION}
        if (state["run"], inputs["qid"]) == CONCISE_ERROR:
            return Feedback(error=AssessmentError(error_code="TIMEOUT",
                                                  error_message="judge timed out"),
                            source=judge, metadata=metadata)
        return Feedback(value="yes", rationale="short", source=judge, metadata=metadata)

    @scorer
    def has_answer(outputs):
        return bool(outputs)

    data = [{"inputs": {"qid": q, "question": f"Question {q[1:]}?"}} for q in ITEMS]
    run_ids = []
    for run in (1, 2, 3):
        state["run"] = run
        with mlflow.start_run(run_name=f"eval-{run}") as r:
            mlflow.genai.evaluate(data=data, predict_fn=app,
                                  scorers=[correctness, concise, has_answer])
        run_ids.append(r.info.run_id)
    mlflow.flush_trace_async_logging()

    human = AssessmentSource(source_type="HUMAN", source_id="reviewer@example.com")
    # MLflow 3.16 deprecates experiment_ids for locations; older 3.x has only experiment_ids.
    scope = ("locations" if "locations" in inspect.signature(mlflow.search_traces).parameters
             else "experiment_ids")
    for trace in mlflow.search_traces(**{scope: [exp_id]}, run_id=run_ids[0],
                                      return_type="list"):
        qid = trace.info.tags["row_id"]
        if qid == OVERRIDDEN:
            judged = next(a for a in trace.info.assessments
                          if a.name == "correctness" and a.source.source_type == "LLM_JUDGE")
            mlflow.override_feedback(trace_id=trace.info.trace_id,
                                     assessment_id=judged.assessment_id, value=HUMAN[qid],
                                     rationale="the answer is wrong", source=human)
        else:
            mlflow.log_feedback(trace_id=trace.info.trace_id, name="correctness",
                                value=HUMAN[qid], rationale="reviewed", source=human)
    return uri


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    print(build(sys.argv[1]))
