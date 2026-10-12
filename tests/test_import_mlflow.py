"""The MLflow reader: a real MLflow store in, ScoreRecords out.

The store is built at test time by tests/fixtures/mlflow/make_store.py through MLflow's own
API (three `mlflow.genai.evaluate` runs, local scorers, no model call; see its docstring).
8 rows Q0-Q7; every run logs new traces, so trace ids differ per run and item ids are derived
from each trace's request input. Human labels (on run 1's traces): Q0-Q3 pass, Q4-Q7 fail; Q4's
label is a human override of the judge's run 1 assessment. The `concise` judge timed out on
Q7 in run 1.
"""

import sys

import pytest

from judgekeeper.readers import read_mlflow
from judgekeeper.records import RecordsError, derive_record_id, fingerprint_known
from judgekeeper.table import make_fingerprint

ITEMS = [f"Q{i}" for i in range(8)]
HUMAN = {q: "pass" if i < 4 else "fail" for i, q in enumerate(ITEMS)}


def _qid_input(qid):
    return {"qid": qid, "question": f"Question {qid[1:]}?"}


def _read(store, **options):
    return read_mlflow("qa-judge", tracking_uri=store, **options)


def _records(files, kind, name):
    return [r for _, recs in files for r in recs if r.annotator_kind == kind and r.name == name]


def _runs_in_start_order(store):
    import mlflow

    client = mlflow.MlflowClient(store)
    exp = client.get_experiment_by_name("qa-judge")
    return sorted(client.search_runs([exp.experiment_id]), key=lambda x: x.info.start_time)


def test_each_mlflow_run_is_one_run_in_start_order(mlflow_store):
    runs = _runs_in_start_order(mlflow_store)
    assert [x.info.run_name for x in runs] == ["eval-1", "eval-2", "eval-3"]
    files = _read(mlflow_store)
    assert [label for label, _ in files] == [x.info.run_id for x in runs] + ["human assessments"]
    for label, recs in files[:3]:
        assert {(r.annotator_kind, r.name) for r in recs} == {("LLM", "concise"),
                                                              ("LLM", "correctness")}
        assert recs.ids_derived is True
    # the last file holds the human labels and the code check (a CODE record, not a judge)
    assert {(r.annotator_kind, r.name) for r in files[-1][1]} == {("HUMAN", "correctness"),
                                                                  ("CODE", "has_answer")}
    notes = files[-1][1].notes
    assert any(n.startswith("Runs are MLflow runs in start order: 1 = ") for n in notes)
    assert any("prompt hash unknown" in n for n in notes)


def test_the_judge_is_named_but_its_prompt_and_temperature_are_unknown(mlflow_store):
    rec = _records(_read(mlflow_store), "LLM", "correctness")[0]
    known = fingerprint_known(rec.evaluator)
    assert known == {"model": "fake:/judge-model-1", "provider": "fake"}
    fp = make_fingerprint(known)
    # MLflow does not record the judge's prompt or temperature on the assessment
    assert fp.prompt_hash is None and fp.temperature is None


def test_tracking_uri_from_the_environment(mlflow_store, monkeypatch):
    monkeypatch.setenv("MLFLOW_TRACKING_URI", mlflow_store)
    assert len(_records(read_mlflow("qa-judge"), "LLM", "correctness")) == 24


def test_derived_ids_are_stable_across_runs(mlflow_store):
    judge = _records(_read(mlflow_store), "LLM", "correctness")
    assert len(judge) == 24
    expected = {derive_record_id(_qid_input(q), None): q for q in ITEMS}
    by_id = {}
    for r in judge:
        by_id.setdefault(r.target_id, []).append(r.run)
    assert set(by_id) == set(expected)
    assert all(sorted(v) == [1, 2, 3] for v in by_id.values())
    assert all(r.input == _qid_input(expected[r.target_id]) for r in judge)


def test_human_override_keeps_the_judge_verdict(mlflow_store):
    q4 = derive_record_id(_qid_input("Q4"), None)
    recs = [r for _, rs in _read(mlflow_store) for r in rs
            if r.target_id == q4 and r.name == "correctness"]
    judge = sorted((r.run, r.label) for r in recs if r.annotator_kind == "LLM")
    human = [r.label for r in recs if r.annotator_kind == "HUMAN"]
    # the overridden run 1 assessment (valid=false in MLflow) is still the judge's verdict
    assert judge == [(1, "pass"), (2, "fail"), (3, "fail")]
    assert human == ["fail"]


@pytest.mark.parametrize("key", ["qid", "row_id"])  # a request input key, then a trace tag
def test_id_from_reads_a_stable_id(mlflow_store, key):
    files = _read(mlflow_store, id_from=key)
    assert all(recs.ids_derived is False for _, recs in files)
    assert {r.target_id: r.label for r in _records(files, "HUMAN", "correctness")} == HUMAN
    assert {r.target_id for r in _records(files, "LLM", "correctness")} == set(ITEMS)


def test_id_from_a_missing_key_is_an_error(mlflow_store):
    with pytest.raises(RecordsError, match="nope"):
        _read(mlflow_store, id_from="nope")


def test_run_id_selects_runs(mlflow_store):
    first = _runs_in_start_order(mlflow_store)[0]
    files = _read(mlflow_store, run_ids=[first.info.run_id])
    assert [label for label, _ in files] == [first.info.run_id, "human assessments"]
    assert {r.run for r in _records(files, "LLM", "correctness")} == {1}


def test_unknown_run_id_is_an_error(mlflow_store):
    with pytest.raises(RecordsError, match="0" * 32):
        _read(mlflow_store, run_ids=["0" * 32])


def test_unknown_experiment_is_an_error(mlflow_store):
    with pytest.raises(RecordsError, match="nope"):
        read_mlflow("nope", tracking_uri=mlflow_store)


def test_feedback_error_becomes_a_verdict_with_no_decision(mlflow_store):
    files = _read(mlflow_store, id_from="qid", metric="concise")
    q7 = {r.run: r for r in _records(files, "LLM", "concise") if r.target_id == "Q7"}
    assert q7[1].label is None and q7[1].score is None
    assert "judge timed out" in q7[1].explanation
    assert q7[2].label == "yes"
    # scorer name and version metadata become the rubric version
    assert fingerprint_known(q7[1].evaluator)["rubric_version"] == "concise@2"


def test_temperature_is_recorded_when_given(mlflow_store):
    rec = _records(_read(mlflow_store, temperature=0), "LLM", "correctness")[0]
    assert make_fingerprint(fingerprint_known(rec.evaluator)).temperature == 0.0


def test_missing_extra_says_how_to_install(monkeypatch):
    monkeypatch.setitem(sys.modules, "mlflow", None)
    with pytest.raises(RecordsError, match=r"judgekeeper\[mlflow\]"):
        read_mlflow("qa-judge")
