"""ScoreRecords: the common format every reader produces.

export.csv (tests/fixtures/records/) maps onto ScoreRecords with a column map. Five items, one
run. Human: r1 r2 r5 pass, r3 r4 fail. Judge (yes/no): r1 yes, r2 no, r3 no, r4 no, r5 yes.
"""

import json

import pytest

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


def test_read_records_jsonl(tmp_path):
    records = read_records(write_jsonl(tmp_path / "records.jsonl", SMALL))
    assert len(records) == 12
    assert [r.annotator_kind for r in records[:4]] == ["HUMAN"] * 4
    judge = {(r.target_id, r.run): r.label for r in records if r.annotator_kind == "LLM"}
    assert judge[("b", 1)] == "fail" and judge[("b", 2)] == "pass"
    assert not records.ids_derived


def test_map_on_a_csv_with_renamed_columns():
    records = read_records(CSV, column_map=MAP)
    judge = {r.target_id: r for r in records if r.annotator_kind == "LLM"}
    human = {r.target_id: r.label for r in records if r.annotator_kind == "HUMAN"}
    assert set(judge) == {"r1", "r2", "r3", "r4", "r5"}
    assert [judge[i].label for i in sorted(judge)] == ["yes", "no", "no", "no", "yes"]
    assert human == {"r1": "pass", "r2": "pass", "r3": "fail", "r4": "fail", "r5": "pass"}
    assert judge["r2"].explanation == "drifts off topic"
    assert judge["r1"].evaluator == {"model": "gpt-4.1"}
    assert (judge["r1"].input, judge["r1"].output) == ("Question 1", "Answer 1")
    assert {r.name for r in records} == {"relevance"}


def test_bad_map_is_an_error():
    with pytest.raises(RecordsError, match="nope"):
        read_records(CSV, column_map="target_id=nope")
    with pytest.raises(RecordsError, match="colour"):
        read_records(CSV, column_map="colour=metric")


def test_evaluator_is_kept_as_written(tmp_path):
    ev = {"provider": "openai", "model": "gpt-4.1", "prompt": "Is it good?",
          "temperature": 0, "version": "rubric-3"}
    rows = [r if r["annotator_kind"] == "HUMAN" else {**r, "evaluator": ev} for r in SMALL]
    records = read_records(write_jsonl(tmp_path / "r.jsonl", rows))
    assert all(r.evaluator == ev for r in records if r.annotator_kind == "LLM")
    assert all(r.evaluator == {} for r in records if r.annotator_kind == "HUMAN")


def test_read_records_derives_missing_ids(tmp_path):
    path = write_jsonl(tmp_path / "r.jsonl", [{**r, "target_id": None} for r in SMALL])
    records = read_records(path)
    assert records.ids_derived
    # the same input and output give the same id, whoever wrote the record
    ids = {}
    for r in records:
        ids.setdefault(r.input, set()).add(r.target_id)
    assert all(len(v) == 1 for v in ids.values())
    assert len({next(iter(v)) for v in ids.values()}) == 4
