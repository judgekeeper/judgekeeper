"""ScoreRecords: the common format every reader produces, and `import records`.

export.csv (tests/fixtures/records/) maps onto ScoreRecords with --map. Five items, one run.
Human: r1 r2 r5 pass, r3 r4 fail. Judge (yes/no): r1 yes, r2 no, r3 no, r4 no, r5 yes.
  TP r1 r5 = 2, FN r2 = 1, TN r3 r4 = 2, FP 0 -> TPR 2/3, TNR 1,
  po 4/5, judge passes 2 of 5, human passes 3: pe (3*2 + 2*3)/25 = 12/25,
  kappa (4/5 - 12/25)/(1 - 12/25) = (8/25)/(13/25) = 8/13.

The round trip uses tests/fixtures/check/results.csv, whose numbers test_check.py derives.
"""

import json

import pytest

from judgekeeper import import_results
from judgekeeper.cli import main
from judgekeeper.records import RecordsError, ScoreRecord, read_records
from tests.conftest import FIXTURES

CSV = FIXTURES / "records" / "export.csv"
MAP = ("target_id=trace_id,name=metric,label=value,explanation=comment,annotator_kind=source,"
       "input=question,output=answer,evaluator.model=judge_model")


def write_jsonl(path, rows):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return path


def rec(target_id, label, kind="LLM", run=None, name="quality", **extra):
    return {"target_id": target_id, "name": name, "annotator_kind": kind, "label": label,
            "run": run, "input": f"in {target_id}", "output": f"out {target_id}", **extra}


# Four items, human pass a b, fail c d. Two runs.
#   run 1: judge a pass, b fail, c fail, d fail -> TP 1, FN 1, TN 2, FP 0
#          po 3/4, judge passes 1, pe (2*1 + 2*3)/16 = 1/2, kappa (3/4-1/2)/(1/2) = 1/2
#   run 2: every verdict matches -> kappa 1
SMALL = [rec("a", "pass", "HUMAN"), rec("b", "pass", "HUMAN"), rec("c", "fail", "HUMAN"),
         rec("d", "fail", "HUMAN"),
         rec("a", "pass", run=1), rec("b", "fail", run=1), rec("c", "fail", run=1),
         rec("d", "fail", run=1),
         rec("a", "pass", run=2), rec("b", "pass", run=2), rec("c", "fail", run=2),
         rec("d", "fail", run=2)]


def test_score_record_fields_and_kinds():
    r = ScoreRecord.from_dict({"target_id": 7, "name": "q", "annotator_kind": "human",
                               "label": "pass", "evaluator": {"model": "m", "version": "v2"}})
    assert r.target_id == "7" and r.annotator_kind == "HUMAN"
    assert r.evaluator == {"model": "m", "version": "v2"}
    d = r.to_dict()
    assert list(d) == ["schema_version", "target_id", "name", "annotator_kind", "label",
                       "score", "explanation", "run", "input", "output", "evaluator",
                       "created_at"]
    with pytest.raises(RecordsError, match="annotator_kind"):
        ScoreRecord.from_dict({"target_id": "x", "name": "q", "annotator_kind": "robot"})
    with pytest.raises(RecordsError, match="evaluator"):
        ScoreRecord.from_dict({"target_id": "x", "name": "q", "annotator_kind": "LLM",
                               "evaluator": ["nope"]})


def test_import_records_jsonl(tmp_path):
    path = write_jsonl(tmp_path / "records.jsonl", SMALL)
    assert main(["import", "records", str(path), "--out", str(tmp_path / "rep")]) == 0
    r = json.loads((tmp_path / "rep" / "report.json").read_text(encoding="utf-8"))
    assert r["n_runs"] == 2
    assert [x["kappa"] for x in r["runs"]] == pytest.approx([0.5, 1.0])
    assert r["source"]["kind"] == "records"
    assert r["source"]["metric"] == "quality"


def test_map_on_a_csv_with_renamed_columns(tmp_path):
    out = tmp_path / "rep"
    assert main(["import", "records", str(CSV), "--map", MAP, "--out", str(out)]) == 0
    r = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert r["n_runs"] == 1
    assert r["headline"]["tpr_mean"] == pytest.approx(2 / 3)
    assert r["headline"]["tnr_mean"] == pytest.approx(1.0)
    assert r["headline"]["kappa_mean"] == pytest.approx(8 / 13)
    assert r["fingerprint"]["model"] == "gpt-4.1"
    assert {row["id"] for row in r["items"]} == {"r1", "r2", "r3", "r4", "r5"}
    r2 = next(d for d in r["disagreements"] if d["id"] == "r2")
    assert r2["rationale"] == "drifts off topic"
    anchors = [json.loads(x) for x in (out / "anchors.jsonl").read_text(
        encoding="utf-8").splitlines()]
    assert anchors[0]["input"] == "Question 1" and anchors[0]["output"] == "Answer 1"


def test_bad_map_is_a_usage_error(tmp_path, capsys):
    assert main(["import", "records", str(CSV), "--map", "target_id=nope",
                 "--out", str(tmp_path)]) == 2
    assert "nope" in capsys.readouterr().err
    assert main(["import", "records", str(CSV), "--map", "colour=metric",
                 "--out", str(tmp_path)]) == 2
    assert "colour" in capsys.readouterr().err


def test_map_only_applies_to_records(tmp_path, capsys):
    assert main(["import", "promptfoo", str(FIXTURES / "promptfoo" / "results.json"),
                 "--map", "label=value", "--out", str(tmp_path)]) == 2
    assert "--map" in capsys.readouterr().err


def test_duplicate_without_run_is_an_error_unless_runs_by_order(tmp_path, capsys):
    rows = [rec(i, lab, "HUMAN") for i, lab in zip("abcd", ["pass", "pass", "fail", "fail"])]
    rows += [rec("a", "pass"), rec("b", "fail"), rec("c", "fail"), rec("d", "fail"),
             rec("a", "pass"), rec("b", "pass"), rec("c", "fail"), rec("d", "fail")]
    path = write_jsonl(tmp_path / "r.jsonl", rows)
    assert main(["import", "records", str(path), "--out", str(tmp_path / "x")]) == 2
    err = capsys.readouterr().err
    assert "--runs-by-order" in err and "'a'" in err
    r = import_results("records", [path], runs_by_order=True, out=tmp_path / "y")
    assert r["n_runs"] == 2
    assert [x["kappa"] for x in r["runs"]] == pytest.approx([0.5, 1.0])


def test_runs_by_order_replaces_a_run_index_that_repeats(tmp_path, capsys):
    # A source that stamps every verdict with the same run index: --runs-by-order still
    # numbers each item's verdicts in order of appearance, whatever the reader set.
    rows = [rec(i, lab, "HUMAN") for i, lab in zip("abcd", ["pass", "pass", "fail", "fail"])]
    rows += [rec("a", "pass", run=1), rec("b", "fail", run=1), rec("c", "fail", run=1),
             rec("d", "fail", run=1), rec("a", "pass", run=1), rec("b", "pass", run=1),
             rec("c", "fail", run=1), rec("d", "fail", run=1)]
    path = write_jsonl(tmp_path / "r.jsonl", rows)
    assert main(["import", "records", str(path), "--out", str(tmp_path / "x")]) == 2
    assert "--runs-by-order" in capsys.readouterr().err
    r = import_results("records", [path], runs_by_order=True, out=tmp_path / "y")
    assert r["n_runs"] == 2
    assert [x["kappa"] for x in r["runs"]] == pytest.approx([0.5, 1.0])


def test_several_files_are_separate_runs(tmp_path):
    humans = [r for r in SMALL if r["annotator_kind"] == "HUMAN"]
    one = write_jsonl(tmp_path / "1.jsonl",
                      humans + [{**r, "run": None} for r in SMALL if r["run"] == 1])
    two = write_jsonl(tmp_path / "2.jsonl", [{**r, "run": None} for r in SMALL if r["run"] == 2])
    r = import_results("records", [one, two], out=tmp_path / "rep")
    assert r["n_runs"] == 2
    assert [x["kappa"] for x in r["runs"]] == pytest.approx([0.5, 1.0])
    # an item a file does not judge is an error judgment in that run
    three = write_jsonl(tmp_path / "3.jsonl", [rec("a", "pass")])
    r = import_results("records", [one, three], out=tmp_path / "rep2")
    assert r["errors"]["per_run"] == [{"run": 1, "n": 0}, {"run": 2, "n": 3}]


def test_labels_file_wins_over_in_file_human_records_with_a_note(tmp_path, capsys):
    path = write_jsonl(tmp_path / "r.jsonl", SMALL)
    labels = tmp_path / "labels.csv"
    labels.write_text("id,human_label\na,pass\nb,fail\nc,fail\nd,fail\n")  # b flipped to fail
    out = tmp_path / "rep"
    assert main(["import", "records", str(path), "--labels", str(labels),
                 "--out", str(out)]) == 0
    r = json.loads((out / "report.json").read_text(encoding="utf-8"))
    # human now: a pass; b c d fail. run 1 matches every item; run 2 passes b.
    assert [x["kappa"] for x in r["runs"]] == pytest.approx([1.0, 0.5])
    note = next(n for n in r["notes"] if "--labels" in n)
    assert "4 items" in note and "1 differ" in note
    assert "--labels" in capsys.readouterr().out


def test_code_records_are_ignored_with_a_note(tmp_path):
    rows = SMALL + [rec("a", "pass", "CODE", run=1, name="quality")]
    r = import_results("records", [write_jsonl(tmp_path / "r.jsonl", rows)], out=tmp_path / "o")
    assert any("1 CODE record ignored" in n for n in r["notes"])


def test_unlabeled_and_unjudged_items_are_dropped_and_counted(tmp_path):
    rows = SMALL + [rec("e", "pass", run=1), rec("f", "fail", "HUMAN")]
    r = import_results("records", [write_jsonl(tmp_path / "r.jsonl", rows)], out=tmp_path / "o")
    assert r["anchors"]["n_items"] == 4
    assert r["source"]["n_judged_unlabeled"] == 1
    assert r["source"]["n_labeled_unjudged"] == 1


def test_several_metric_names_need_metric(tmp_path, capsys):
    # human records named after another judge metric label that metric, not this one
    rows = SMALL + [rec("a", "pass", run=1, name="tone"), rec("a", "pass", "HUMAN", name="tone")]
    path = write_jsonl(tmp_path / "r.jsonl", rows)
    assert main(["import", "records", str(path), "--out", str(tmp_path / "o")]) == 2
    err = capsys.readouterr().err
    assert "'quality'" in err and "'tone'" in err
    r = import_results("records", [path], metric="tone", out=tmp_path / "p")
    assert r["source"]["metric"] == "tone"
    assert r["anchors"]["n_items"] == 1
    with pytest.raises(RecordsError, match="no LLM records named 'nope'"):
        import_results("records", [path], metric="nope", out=tmp_path / "q")


def test_scores_need_pass_if(tmp_path, capsys):
    rows = [r if r["annotator_kind"] == "HUMAN"
            else {**r, "label": None, "score": 0.9 if r["label"] == "pass" else 0.1}
            for r in SMALL]
    path = write_jsonl(tmp_path / "r.jsonl", rows)
    assert main(["import", "records", str(path), "--out", str(tmp_path / "o")]) == 2
    assert "--pass-if" in capsys.readouterr().err
    r = import_results("records", [path], pass_if="score>=0.5", out=tmp_path / "p")
    assert [x["kappa"] for x in r["runs"]] == pytest.approx([0.5, 1.0])


def test_evaluator_becomes_the_fingerprint_and_the_prompt_is_hashed(tmp_path):
    ev = {"provider": "openai", "model": "gpt-4.1", "prompt": "Is it good? SECRET RUBRIC",
          "temperature": 0, "version": "rubric-3"}
    rows = [r if r["annotator_kind"] == "HUMAN" else {**r, "evaluator": ev} for r in SMALL]
    r = import_results("records", [write_jsonl(tmp_path / "r.jsonl", rows)], out=tmp_path / "o")
    fp = r["fingerprint"]
    assert (fp["provider"], fp["model"], fp["rubric_version"], fp["temperature"]) == (
        "openai", "gpt-4.1", "rubric-3", 0.0)
    assert fp["prompt_hash"]
    for p in (tmp_path / "o").rglob("*"):
        if p.is_file():
            assert "SECRET RUBRIC" not in p.read_text(encoding="utf-8")


def test_read_records_derives_missing_ids(tmp_path):
    path = write_jsonl(tmp_path / "r.jsonl", [{**r, "target_id": None} for r in SMALL])
    records = read_records(path)
    assert records.ids_derived
    r = import_results("records", [path], out=tmp_path / "o")
    assert r["source"]["ids_derived"] is True
    assert [x["kappa"] for x in r["runs"]] == pytest.approx([0.5, 1.0])
