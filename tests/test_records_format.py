"""The records format, version 2: a version marker, fields it does not know kept, `metadata`,
the judge's `rule`, and the fields ready for agents (`trajectory`, `outcome`, `app_version`).

Older files (no `schema_version`) still read; a newer version reads what it can, with one
warning. Ids derived for a record with a trajectory cover the trajectory, so two agent runs
that end in the same answer stay two answers.
"""

import hashlib
import json

import pytest

from judgekeeper import start
from judgekeeper.normalise import Normaliser
from judgekeeper.records import (
    SCHEMA_VERSION,
    RecordsError,
    ScoreRecord,
    derive_record_id,
    fingerprint_known,
    problems,
    read_records,
    records_to_report,
    write_records,
)
from judgekeeper.table import make_fingerprint

TRAJECTORY = [
    {"role": "user", "content": "Refund order 7"},
    {"role": "assistant", "content": None,
     "tool_calls": [{"id": "c1", "name": "lookup_order", "arguments": {"order": 7}}]},
    {"role": "tool", "tool_call_id": "c1", "content": "{\"status\": \"delivered\"}"},
    {"role": "assistant", "content": "Your refund is on its way."},
]
SHORT_RUN = [TRAJECTORY[0], TRAJECTORY[3]]
OUTCOME = {"passed": True, "score": 1.0, "source": "database check",
           "detail": "refund row written"}
FULL = {"schema_version": 2, "target_id": "t1", "name": "Safe wording", "annotator_kind": "LLM",
        "label": "pass", "score": 0.82, "explanation": "Polite and correct.", "run": 1,
        "input": "Refund order 7", "output": "Your refund is on its way.",
        "evaluator": {"provider": "anthropic", "model": "claude-opus-5", "temperature": 0,
                      "version": "v3", "rule": "Pass when the reply is polite and correct."},
        "created_at": "2026-10-01T09:00:00Z",
        "metadata": {"criterion": "tone", "run_id": "nightly-41", "ab": "B"},
        "trajectory": TRAJECTORY, "outcome": OUTCOME, "app_version": "support-agent 2.3"}


def write_jsonl(path, rows):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return path


def sha256(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# The version marker ---------------------------------------------------------------------

def test_this_is_version_two_and_a_missing_version_means_one():
    assert SCHEMA_VERSION == 2
    assert ScoreRecord.from_dict({"label": "pass"}).schema_version == 1
    assert ScoreRecord.from_dict({"schema_version": 2, "label": "pass"}).schema_version == 2
    assert ScoreRecord(target_id="a", name="j", annotator_kind="LLM").schema_version == 2


def test_records_are_written_as_version_two():
    d = ScoreRecord.from_dict({"label": "pass"}).to_dict()
    assert d["schema_version"] == 2
    assert list(d)[:12] == ["schema_version", "target_id", "name", "annotator_kind", "label",
                            "score", "explanation", "run", "input", "output", "evaluator",
                            "created_at"]


def test_optional_fields_are_left_out_when_empty():
    d = ScoreRecord.from_dict({"label": "pass"}).to_dict()
    for name in ("metadata", "trajectory", "outcome", "app_version"):
        assert name not in d


# Fields it does not know ----------------------------------------------------------------

def test_unknown_fields_are_kept_not_rejected():
    r = ScoreRecord.from_dict({"label": "pass", "colour": "blue",
                               "evaluator": {"model": "m", "region": "eu"}})
    assert r.extra == {"colour": "blue"}
    assert r.evaluator == {"model": "m", "region": "eu"}
    d = r.to_dict()
    assert d["colour"] == "blue"
    assert d["evaluator"]["region"] == "eu"


def test_unknown_evaluator_keys_stay_out_of_the_fingerprint():
    fp = make_fingerprint(fingerprint_known({"model": "m", "version": "v2", "region": "eu"}))
    assert fp.model == "m"
    assert fp.rubric_version == "v2"


# metadata and the rule ------------------------------------------------------------------

def test_metadata_is_an_open_object():
    meta = {"criterion": "tone", "ab": "B", "n": 3, "tags": ["a", "b"]}
    assert ScoreRecord.from_dict({"label": "pass", "metadata": meta}).metadata == meta
    with pytest.raises(RecordsError, match="metadata"):
        ScoreRecord.from_dict({"label": "pass", "metadata": "tone"})


def test_the_rule_is_kept_in_the_evaluator():
    r = ScoreRecord.from_dict({"label": "pass", "evaluator": {"rule": "Be kind."}})
    assert r.evaluator == {"rule": "Be kind."}


def test_the_rule_is_hashed_into_the_prompt_hash_when_none_is_given():
    assert make_fingerprint(fingerprint_known({"rule": "Be kind."})).prompt_hash == \
        sha256("Be kind.")
    assert make_fingerprint(fingerprint_known({"prompt": "P", "rule": "R"})).prompt_hash == \
        sha256("P")
    assert make_fingerprint(fingerprint_known({"prompt_hash": "abc", "rule": "R"})
                            ).prompt_hash == "abc"


def test_start_shows_the_rule_from_the_evaluator_first():
    with_rule = [ScoreRecord(target_id="a", name="j", annotator_kind="LLM",
                             evaluator={"prompt": "Criteria: old words", "rule": "Be kind."})]
    assert start.rule_of(with_rule) == "Be kind."
    only_prompt = [ScoreRecord(target_id="a", name="j", annotator_kind="LLM",
                               evaluator={"prompt": "Criteria: Be brief."})]
    assert start.rule_of(only_prompt) == "Be brief."
    assert start.rule_of([ScoreRecord(target_id="a", name="j", annotator_kind="LLM")]) is None


# Ready for agents -----------------------------------------------------------------------

def test_the_agent_fields_are_stored_and_written_again():
    r = ScoreRecord.from_dict({"label": "pass", "trajectory": TRAJECTORY, "outcome": OUTCOME,
                               "app_version": "support-agent 2.3"})
    assert r.trajectory == TRAJECTORY
    assert r.outcome == OUTCOME
    assert r.app_version == "support-agent 2.3"
    d = r.to_dict()
    assert (d["trajectory"], d["outcome"], d["app_version"]) == (
        TRAJECTORY, OUTCOME, "support-agent 2.3")


def test_a_full_record_has_no_problems():
    assert problems(FULL) == []
    assert problems({"label": "pass"}) == []


BAD = [
    ({"trajectory": "steps"}, "trajectory"),
    ({"trajectory": ["hello"]}, "trajectory"),
    ({"trajectory": [{"content": "hi"}]}, "role"),
    ({"trajectory": [{"role": "assistant", "tool_calls": [{"id": "c1"}]}]}, "name"),
    ({"trajectory": [{"role": "assistant", "tool_calls": "lookup"}]}, "tool_calls"),
    ({"trajectory": [{"role": "tool", "tool_call_id": 5, "content": "x"}]}, "tool_call_id"),
    ({"trajectory": [{"role": "user", "content": 5}]}, "content"),
    ({"outcome": {"source": "unit tests"}}, "passed or score"),
    ({"outcome": {"passed": "yes"}}, "passed"),
    ({"outcome": {"score": "high"}}, "score"),
    ({"outcome": True}, "outcome"),
    ({"app_version": ["1", "2"]}, "app_version"),
    ({"schema_version": "two"}, "schema_version"),
    ({"schema_version": 0}, "schema_version"),
    ({"schema_version": True}, "schema_version"),
    ({"score": "high"}, "score"),
    ({"evaluator": {"temperature": "hot"}}, "temperature"),
    ({"evaluator": ["m"]}, "evaluator"),
    ({"annotator_kind": "robot"}, "annotator_kind"),
    ({"run": 1.5}, "run"),
    ({"name": True}, "name"),
]


@pytest.mark.parametrize("bad, words", BAD)
def test_a_bad_value_is_named(bad, words):
    found = problems({"label": "pass", **bad})
    assert found and any(words in p for p in found), found
    with pytest.raises(RecordsError, match=words):
        ScoreRecord.from_dict({"label": "pass", **bad})


# Reading and writing files --------------------------------------------------------------

def test_read_write_read_gives_the_same_records(tmp_path):
    rows = [{**FULL, "colour": "blue", "evaluator": {**FULL["evaluator"], "region": "eu"}},
            {"schema_version": 2, "target_id": "t1", "name": "Safe wording",
             "annotator_kind": "HUMAN", "label": "pass", "input": FULL["input"],
             "output": FULL["output"], "metadata": {"labeler": "support lead"}}]
    first = read_records(write_jsonl(tmp_path / "a.jsonl", rows))
    write_records(tmp_path / "b.jsonl", first)
    second = read_records(tmp_path / "b.jsonl")
    assert [r.to_dict() for r in second] == [r.to_dict() for r in first]
    assert second[0].extra == {"colour": "blue"}
    assert second[0].evaluator["region"] == "eu"
    assert second[1].metadata == {"labeler": "support lead"}
    assert second[0].trajectory == TRAJECTORY


def test_version_one_files_still_read(tmp_path):
    rows = [{"target_id": "a", "name": "q", "annotator_kind": "LLM", "label": "pass",
             "score": None, "explanation": "ok", "run": None, "input": "in", "output": "out",
             "evaluator": {"model": "m"}, "created_at": None}]
    records = read_records(write_jsonl(tmp_path / "v1.jsonl", rows))
    assert records[0].schema_version == 1
    assert records[0].label == "pass"
    assert records.warnings == []


def test_a_newer_version_reads_what_it_can_with_one_warning(tmp_path):
    rows = [{"schema_version": 3, "label": "pass", "input": f"q{i}", "output": "a",
             "judge_cost": {"usd": 0.01}} for i in range(3)]
    records = read_records(write_jsonl(tmp_path / "v3.jsonl", rows))
    assert len(records) == 3
    assert len(records.warnings) == 1
    assert "version 3" in records.warnings[0] and "version 2" in records.warnings[0]
    assert records[0].extra == {"judge_cost": {"usd": 0.01}}
    write_records(tmp_path / "again.jsonl", records)
    line = json.loads((tmp_path / "again.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert line["schema_version"] == 3  # it holds version 3's fields, so it stays version 3
    assert line["judge_cost"] == {"usd": 0.01}


def test_a_record_over_one_megabyte_is_kept_with_a_warning(tmp_path):
    big = "x" * 1_100_000
    rows = [{"label": "pass", "input": "q", "output": "a",
             "trajectory": [{"role": "tool", "content": big}]},
            {"label": "fail", "input": "q2", "output": "b"}]
    records = read_records(write_jsonl(tmp_path / "big.jsonl", rows))
    assert len(records) == 2
    assert records[0].trajectory[0]["content"] == big
    assert len(records.warnings) == 1 and "1 MB" in records.warnings[0]


def test_csv_cells_can_hold_json_for_the_open_fields(tmp_path):
    path = tmp_path / "r.csv"
    path.write_text('input,output,label,metadata,outcome,app_version\n'
                    'q,a,pass,"{""criterion"": ""tone""}","{""passed"": true}",2.0\n',
                    encoding="utf-8")
    (r,) = read_records(path)
    assert r.metadata == {"criterion": "tone"}
    assert r.outcome == {"passed": True}
    assert r.app_version == "2.0"


def test_a_csv_cell_that_is_not_json_is_named(tmp_path):
    path = tmp_path / "r.csv"
    path.write_text("input,output,label,metadata\nq,a,pass,tone\n", encoding="utf-8")
    with pytest.raises(RecordsError, match="metadata"):
        read_records(path)


# Ids and the trajectory -----------------------------------------------------------------

def test_a_derived_id_covers_the_trajectory_only_when_there_is_one():
    plain = derive_record_id("q", "a")
    assert derive_record_id("q", "a", None) == plain
    assert derive_record_id("q", "a", []) == plain
    with_steps = derive_record_id("q", "a", TRAJECTORY)
    shorter = derive_record_id("q", "a", SHORT_RUN)
    assert len({plain, with_steps, shorter}) == 3


def test_two_agent_runs_with_the_same_answer_do_not_merge(tmp_path):
    rows = [{"input": "Refund order 7", "output": "Done.", "label": "pass",
             "trajectory": TRAJECTORY},
            {"input": "Refund order 7", "output": "Done.", "label": "fail",
             "trajectory": SHORT_RUN}]
    records = read_records(write_jsonl(tmp_path / "runs.jsonl", rows))
    assert records[0].target_id != records[1].target_id
    pool = start.build_pool([("runs.jsonl", records)], "judge", Normaliser())
    assert len(pool.answers) == 2 and pool.n_merged == 0
    assert {a.agent["trajectory"] == TRAJECTORY for a in pool.answers} == {True, False}


def test_without_a_trajectory_the_same_answer_still_merges(tmp_path):
    rows = [{"input": "q", "output": "a", "label": "pass"},
            {"input": "q", "output": "a", "label": "pass"}]
    records = read_records(write_jsonl(tmp_path / "same.jsonl", rows))
    assert records[0].target_id == records[1].target_id == derive_record_id("q", "a")
    pool = start.build_pool([("same.jsonl", records)], "judge", Normaliser())
    assert len(pool.answers) == 1 and pool.n_merged == 1


# The anchor set -------------------------------------------------------------------------

def _labeled(tmp_path, trajectory=TRAJECTORY):
    rows = []
    for item, label in (("a", "pass"), ("b", "fail")):
        common = {"target_id": item, "name": "Safe wording", "input": f"q {item}",
                  "output": f"out {item}"}
        rows.append({**common, "annotator_kind": "LLM", "label": label,
                     "trajectory": trajectory, "outcome": OUTCOME,
                     "app_version": "support-agent 2.3", "metadata": {"criterion": "tone"}})
        rows.append({**common, "annotator_kind": "HUMAN", "label": label})
    return read_records(write_jsonl(tmp_path / "labeled.jsonl", rows))


def test_the_agent_fields_go_into_the_anchor_set(tmp_path):
    records_to_report([("labeled.jsonl", _labeled(tmp_path))], kind="records",
                      out=tmp_path / "rep")
    anchors = [json.loads(line) for line in
               (tmp_path / "rep" / "anchors.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(anchors) == 2
    for a in anchors:
        assert a["trajectory"] == TRAJECTORY
        assert a["outcome"] == OUTCOME
        assert a["app_version"] == "support-agent 2.3"
        assert "metadata" not in a


def test_the_agent_fields_are_scrubbed_in_the_anchor_set(tmp_path):
    secret = "sk-" + "a1b2c3d4" * 4
    steps = [{"role": "assistant", "content": None, "tool_calls": [
        {"id": "c1", "name": "call_api", "arguments": {"key": secret}}]}]
    records_to_report([("labeled.jsonl", _labeled(tmp_path, steps))], kind="records",
                      out=tmp_path / "rep")
    text = (tmp_path / "rep" / "anchors.jsonl").read_text(encoding="utf-8")
    assert secret not in text
    assert "[REDACTED]" in text
