"""`judgekeeper import mlflow`: a real MLflow store in, a report out.

The store is built at test time by tests/fixtures/mlflow/make_store.py through MLflow's own
API (three `mlflow.genai.evaluate` runs, local scorers, no model call; see its docstring).
8 rows Q0-Q7; every run logs new traces, so trace ids differ per run and item ids are derived
from each trace's request input. Human labels (on run 1's traces): Q0-Q3 pass, Q4-Q7 fail; Q4's
label is a human override of the judge's run 1 assessment. `correctness` passes:

  run 1: Q0 Q1 Q2 Q4   TP 3, FN 1 (Q3), TN 3, FP 1 (Q4) -> TPR 3/4, TNR 3/4,
                       po 6/8, judge passes 4 of 8, pe (4*4 + 4*4)/64 = 1/2, kappa 1/2
  run 2: Q0 Q1 Q2 Q3   every verdict matches -> TPR 1, TNR 1, kappa 1
  run 3: Q0 Q1 Q3 Q5   TP 3, FN 1 (Q2), TN 3, FP 1 (Q5) -> TPR 3/4, TNR 3/4, kappa 1/2
  means: TPR (3/4 + 1 + 3/4)/3 = 5/6, TNR 5/6, kappa (1/2 + 1 + 1/2)/3 = 2/3
  noise floor: Q2 (P P F), Q3 (F P P), Q4 (P F F), Q5 (F F P) flip -> 4/8 = 1/2
"""

import json
import sys

import pytest

from judgekeeper import import_results
from judgekeeper.cli import main
from judgekeeper.records import RecordsError, derive_record_id

ITEMS = [f"Q{i}" for i in range(8)]
HUMAN = {q: "pass" if i < 4 else "fail" for i, q in enumerate(ITEMS)}


def _import(store, out, *extra):
    return main(["import", "mlflow", "--experiment", "qa-judge", "--tracking-uri", store,
                 "--out", str(out), *extra])


def _report(out):
    return json.loads((out / "report.json").read_text())


def _qid_input(qid):
    return {"qid": qid, "question": f"Question {qid[1:]}?"}


def test_one_command_turns_the_store_into_a_report(mlflow_store, tmp_path, capsys):
    out = tmp_path / "rep"
    assert _import(mlflow_store, out, "--metric", "correctness") == 0
    r = _report(out)
    assert r["n_runs"] == 3
    assert r["anchors"]["n_items"] == 8
    assert [x["kappa"] for x in r["runs"]] == pytest.approx([1 / 2, 1, 1 / 2])
    assert [x["tpr"] for x in r["runs"]] == pytest.approx([3 / 4, 1, 3 / 4])
    assert [x["tnr"] for x in r["runs"]] == pytest.approx([3 / 4, 1, 3 / 4])
    h = r["headline"]
    assert (h["tpr_mean"], h["tnr_mean"], h["kappa_mean"]) == pytest.approx((5 / 6, 5 / 6, 2 / 3))
    assert r["noise_floor"]["items_flipped_fraction"] == pytest.approx(1 / 2)
    src = r["source"]
    assert src["kind"] == "mlflow"
    assert src["metric"] == "correctness"
    assert src["ids_derived"] is True
    fp = r["fingerprint"]
    assert fp["model"] == "fake:/judge-model-1"
    assert fp["provider"] == "fake"
    # MLflow does not record the judge's prompt or temperature on the assessment
    assert "prompt_hash" in r["fingerprint_unknown"]
    assert "temperature" in r["fingerprint_unknown"]
    printed = capsys.readouterr().out
    assert "CODE" in printed  # the has_answer code check is ignored, with a note


def test_runs_are_mlflow_runs_in_start_order(mlflow_store, tmp_path):
    import mlflow

    client = mlflow.MlflowClient(mlflow_store)
    exp = client.get_experiment_by_name("qa-judge")
    runs = sorted(client.search_runs([exp.experiment_id]), key=lambda x: x.info.start_time)
    assert [x.info.run_name for x in runs] == ["eval-1", "eval-2", "eval-3"]
    out = tmp_path / "rep"
    assert _import(mlflow_store, out, "--metric", "correctness") == 0
    headers = [json.loads((out / "runs" / f"run-0{n}.jsonl").read_text().splitlines()[0])
               for n in (1, 2, 3)]
    assert [h["source"]["file"] for h in headers] == [x.info.run_id for x in runs]


def test_tracking_uri_from_the_environment(mlflow_store, tmp_path, monkeypatch):
    monkeypatch.setenv("MLFLOW_TRACKING_URI", mlflow_store)
    out = tmp_path / "rep"
    assert main(["import", "mlflow", "--experiment", "qa-judge", "--metric", "correctness",
                 "--out", str(out)]) == 0
    assert _report(out)["headline"]["kappa_mean"] == pytest.approx(2 / 3)


def test_derived_ids_are_stable_across_runs(mlflow_store):
    from judgekeeper.readers import read_mlflow

    files = read_mlflow("qa-judge", tracking_uri=mlflow_store)
    judge = [r for _, recs in files for r in recs
             if r.annotator_kind == "LLM" and r.name == "correctness"]
    assert len(judge) == 24
    expected = {derive_record_id(_qid_input(q), None): q for q in ITEMS}
    by_id = {}
    for r in judge:
        by_id.setdefault(r.target_id, []).append(r.run)
    assert set(by_id) == set(expected)
    assert all(sorted(v) == [1, 2, 3] for v in by_id.values())
    assert all(r.input == _qid_input(expected[r.target_id]) for r in judge)


def test_human_override_keeps_the_judge_verdict(mlflow_store):
    from judgekeeper.readers import read_mlflow

    q4 = derive_record_id(_qid_input("Q4"), None)
    recs = [r for _, rs in read_mlflow("qa-judge", tracking_uri=mlflow_store) for r in rs
            if r.target_id == q4 and r.name == "correctness"]
    judge = sorted((r.run, r.label) for r in recs if r.annotator_kind == "LLM")
    human = [r.label for r in recs if r.annotator_kind == "HUMAN"]
    # the overridden run 1 assessment (valid=false in MLflow) is still the judge's verdict
    assert judge == [(1, "pass"), (2, "fail"), (3, "fail")]
    assert human == ["fail"]


def test_id_from_reads_a_stable_id(mlflow_store, tmp_path):
    for key in ("qid", "row_id"):  # a request input key, then a trace tag
        out = tmp_path / key
        assert _import(mlflow_store, out, "--metric", "correctness", "--id-from", key) == 0
        anchors = [json.loads(x) for x in (out / "anchors.jsonl").read_text().splitlines()]
        assert {a["id"]: a["human_label"] for a in anchors} == HUMAN
        r = _report(out)
        assert r["source"]["ids_derived"] is False
        assert r["headline"]["kappa_mean"] == pytest.approx(2 / 3)


def test_id_from_a_missing_key_is_a_usage_error(mlflow_store, tmp_path, capsys):
    assert _import(mlflow_store, tmp_path / "x", "--metric", "correctness",
                   "--id-from", "nope") == 2
    assert "nope" in capsys.readouterr().err


def test_run_id_selects_runs(mlflow_store, tmp_path):
    import mlflow

    client = mlflow.MlflowClient(mlflow_store)
    exp = client.get_experiment_by_name("qa-judge")
    first = min(client.search_runs([exp.experiment_id]), key=lambda x: x.info.start_time)
    out = tmp_path / "rep"
    assert _import(mlflow_store, out, "--metric", "correctness",
                   "--run-id", first.info.run_id) == 0
    r = _report(out)
    assert r["n_runs"] == 1
    assert r["runs"][0]["kappa"] == pytest.approx(1 / 2)
    assert r["noise_floor"]["status"].startswith("unknown")


def test_unknown_run_id_is_a_usage_error(mlflow_store, tmp_path, capsys):
    assert _import(mlflow_store, tmp_path / "x", "--metric", "correctness",
                   "--run-id", "0" * 32) == 2
    assert "0" * 32 in capsys.readouterr().err


def test_unknown_experiment_is_a_usage_error(mlflow_store, tmp_path, capsys):
    assert main(["import", "mlflow", "--experiment", "nope", "--tracking-uri", mlflow_store,
                 "--metric", "correctness", "--out", str(tmp_path)]) == 2
    assert "nope" in capsys.readouterr().err


def test_several_assessment_names_without_metric_is_a_usage_error(mlflow_store, tmp_path,
                                                                    capsys):
    assert _import(mlflow_store, tmp_path / "x") == 2
    err = capsys.readouterr().err
    assert "concise" in err and "correctness" in err and "--metric" in err
    assert "has_answer" not in err  # a CODE assessment is not a judge


def test_feedback_error_becomes_an_error_verdict(mlflow_store, tmp_path):
    labels = tmp_path / "labels.csv"
    labels.write_text("id,human_label\n" + "".join(f"{q},{HUMAN[q]}\n" for q in ITEMS))
    out = tmp_path / "rep"
    assert _import(mlflow_store, out, "--metric", "concise", "--id-from", "qid",
                   "--labels", str(labels)) == 0
    run1 = [json.loads(x) for x in (out / "runs" / "run-01.jsonl").read_text().splitlines()]
    q7 = next(x for x in run1 if x.get("id") == "Q7")
    assert q7["verdict"] == "error"
    assert "judge timed out" in (q7["rationale"] + (q7.get("error") or ""))
    r = _report(out)
    assert [x["n"] for x in r["errors"]["per_run"]] == [1, 0, 0]
    # scorer name and version metadata become the rubric version
    assert r["fingerprint"]["rubric_version"] == "concise@2"


def test_temperature_is_recorded_when_given(mlflow_store, tmp_path):
    out = tmp_path / "rep"
    assert _import(mlflow_store, out, "--metric", "correctness", "--temperature", "0") == 0
    assert _report(out)["fingerprint"]["temperature"] == 0.0


def test_anchors_out_hands_off_to_judge(mlflow_store, tmp_path):
    out, anchors = tmp_path / "rep", tmp_path / "labels" / "anchors.jsonl"
    assert _import(mlflow_store, out, "--metric", "correctness",
                   "--anchors-out", str(anchors)) == 0
    items = [json.loads(x) for x in anchors.read_text().splitlines()]
    assert len(items) == 8
    assert all(set(i) == {"id", "input", "output", "human_label"} for i in items)
    by_q = {i["input"]["qid"]: i for i in items}
    assert {q: i["human_label"] for q, i in by_q.items()} == HUMAN
    assert by_q["Q0"]["output"] == "Answer to question 0?"
    assert "reviewed" not in anchors.read_text()  # no rationales
    assert "reviewer@example.com" not in anchors.read_text()  # no user ids
    assert main(["freeze", str(anchors)]) == 0
    # replay the imported run 1 as a judge over the new anchor set, three times
    assert main(["judge", str(anchors), "--runner", "replay", "--fixture",
                 str(out / "runs" / "run-01.jsonl"), "--runs", "3",
                 "--out", str(tmp_path / "rejudged")]) == 0
    assert main(["validate", str(anchors), str(tmp_path / "rejudged"),
                 "--out", str(tmp_path / "rep2")]) == 0
    r = _report(tmp_path / "rep2")
    assert r["n_runs"] == 3
    assert r["headline"]["kappa_mean"] == pytest.approx(1 / 2)
    assert r["noise_floor"]["items_flipped_fraction"] == 0


def test_anchors_out_applies_to_platform_readers_only(tmp_path, capsys):
    from tests.conftest import FIXTURES

    assert main(["import", "promptfoo", str(FIXTURES / "promptfoo" / "results.json"),
                 "--metric", "helpfulness", "--anchors-out", str(tmp_path / "a.jsonl"),
                 "--out", str(tmp_path / "rep")]) == 2
    assert "--anchors-out" in capsys.readouterr().err


def test_missing_extra_says_how_to_install(monkeypatch):
    from judgekeeper.readers import read_mlflow

    monkeypatch.setitem(sys.modules, "mlflow", None)
    with pytest.raises(RecordsError, match=r"judgekeeper\[mlflow\]"):
        read_mlflow("qa-judge")


def test_missing_extra_is_a_usage_error_on_the_command_line(monkeypatch, tmp_path, capsys):
    monkeypatch.setitem(sys.modules, "mlflow", None)
    assert main(["import", "mlflow", "--experiment", "x", "--out", str(tmp_path)]) == 2
    assert 'pip install "judgekeeper[mlflow]"' in capsys.readouterr().err


def test_mlflow_options_need_mlflow(tmp_path, capsys):
    assert main(["import", "promptfoo", "x.json", "--experiment", "e",
                 "--out", str(tmp_path)]) == 2
    assert "--experiment" in capsys.readouterr().err


def test_mlflow_takes_no_paths(tmp_path, capsys):
    assert main(["import", "mlflow", "some.json", "--experiment", "e",
                 "--out", str(tmp_path)]) == 2
    assert "path" in capsys.readouterr().err


def test_import_results_api(mlflow_store, tmp_path):
    r = import_results("mlflow", metric="correctness", out=tmp_path,
                       source={"experiment": "qa-judge", "tracking_uri": mlflow_store})
    assert r["headline"]["kappa_mean"] == pytest.approx(2 / 3)
