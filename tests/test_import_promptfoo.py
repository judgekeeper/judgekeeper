"""`judgekeeper import promptfoo`: a promptfoo `-o results.json` in, a report out.

Fixture (tests/fixtures/promptfoo/results.json, made by make_framework_fixtures.py): 7 tests
t0..t6, one prompt, --repeat 3, so 21 rows with no repeat index, each with its own testIdx
(as real files have; see tests/fixtures/promptfoo/real/). Each row has a `contains`
component (code), an llm-rubric component with metric "helpfulness" and a factuality
component. Humans rated repeat 1 of t0-t5 in the web UI: t0-t2 pass, t3-t5 fail. t6 has no
rating, so it is dropped with a count.

The helpfulness judge passes:
  repeat 1: t0 t1 t5 (t6)    repeat 2: t0 t1 t2 t5 (t6)    repeat 3: as repeat 1

On t2 and t5 in repeat 1 the human rating overrides the row's `success` (t2 true, t5 false);
the judge's own verdict is the llm-rubric component (t2 fail, t5 pass). Reading `success`
would make repeat 1 perfect.

Six labeled items, human pass t0-t2 (positive), fail t3-t5:
  repeats 1, 3: TP t0 t1 = 2, FN t2 = 1, TN t3 t4 = 2, FP t5 = 1 -> TPR 2/3, TNR 2/3,
                po 4/6, judge passes 3 of 6, pe (3*3 + 3*3)/36 = 1/2, kappa (2/3-1/2)/(1/2) = 1/3
  repeat 2:     TP 3, FN 0, TN 2, FP 1 -> TPR 1, TNR 2/3,
                po 5/6, judge passes 4, pe (3*4 + 3*2)/36 = 1/2, kappa (5/6-1/2)/(1/2) = 2/3
  means:        TPR (2/3 + 1 + 2/3)/3 = 7/9, TNR 2/3, kappa (1/3 + 2/3 + 1/3)/3 = 4/9
  noise floor:  t2 is the only item whose verdict changes between repeats -> 1/6 flipped.

t2 has no grader provider anywhere (assertion, test options, defaultTest), so promptfoo used
its built-in default grader; the others name openai:gpt-4.1-mini at temperature 0.
"""

import copy
import hashlib
import json

import pytest

from judgekeeper import import_results
from judgekeeper.cli import main
from judgekeeper.readers import read_promptfoo
from judgekeeper.records import RecordsError
from tests.conftest import FIXTURES

RESULTS = FIXTURES / "promptfoo" / "results.json"
RUBRIC = "The answer is helpful and correct."


def _report(out):
    return json.loads((out / "report.json").read_text())


def test_one_command_turns_the_fixture_into_a_report(tmp_path):
    out = tmp_path / "rep"
    assert main(["import", "promptfoo", str(RESULTS), "--metric", "helpfulness",
                 "--out", str(out)]) == 0
    r = _report(out)
    assert (out / "report.html").is_file()
    assert r["n_runs"] == 3
    assert r["anchors"]["n_items"] == 6
    assert [x["kappa"] for x in r["runs"]] == pytest.approx([1 / 3, 2 / 3, 1 / 3])
    assert [x["tpr"] for x in r["runs"]] == pytest.approx([2 / 3, 1, 2 / 3])
    assert [x["tnr"] for x in r["runs"]] == pytest.approx([2 / 3, 2 / 3, 2 / 3])
    h = r["headline"]
    assert h["tpr_mean"] == pytest.approx(7 / 9)
    assert h["tnr_mean"] == pytest.approx(2 / 3)
    assert h["kappa_mean"] == pytest.approx(4 / 9)
    assert r["noise_floor"]["items_flipped_fraction"] == pytest.approx(1 / 6)
    assert r["source"]["kind"] == "promptfoo"
    assert r["source"]["version"] == 3
    assert r["source"]["metric"] == "helpfulness"
    assert r["source"]["file"] == "results.json"
    # t6 was judged but nobody rated it: dropped and counted
    assert r["source"]["n_judged_unlabeled"] == 1
    assert any("1 judged item has no human label" in n for n in r["notes"])
    # the contains components are code, not a judge
    assert any("code" in n.lower() and "ignored" in n for n in r["notes"])


def test_human_override_is_not_taken_as_the_judge_verdict():
    records = read_promptfoo(RESULTS)
    judge = {(r.target_id, r.run): r.label for r in records
             if r.annotator_kind == "LLM" and r.name == "helpfulness"}
    human = {r.target_id: r.label for r in records if r.annotator_kind == "HUMAN"}
    # row success is true for t2 repeat 1 and false for t5 repeat 1; the judge said otherwise
    assert judge[("t2", 1)] == "fail" and human["t2"] == "pass"
    assert judge[("t5", 1)] == "pass" and human["t5"] == "fail"
    human_rec = next(r for r in records if r.annotator_kind == "HUMAN" and r.target_id == "t2")
    assert human_rec.explanation == "reviewer on t2"


def test_repeats_are_numbered_in_order_of_appearance():
    records = read_promptfoo(RESULTS)
    runs = sorted({r.run for r in records if r.annotator_kind == "LLM"})
    assert runs == [1, 2, 3]
    t2 = [r.label for r in records
          if r.annotator_kind == "LLM" and r.name == "helpfulness" and r.target_id == "t2"]
    assert t2 == ["fail", "pass", "fail"]


def test_default_grader_is_flagged_and_its_model_unknown(tmp_path):
    r = import_results("promptfoo", [RESULTS], metric="helpfulness", out=tmp_path)
    assert r["fingerprint"]["model"] is None
    assert "model" in r["fingerprint_unknown"]
    messages = [f["message"] for f in r["verdict"]["flags"]]
    assert any("default grader model not recorded by promptfoo" in m for m in messages)
    # each judgment keeps its own fingerprint: t2's model is unknown, the others are known
    lines = [json.loads(x) for x in (tmp_path / "runs" / "run-01.jsonl").read_text().splitlines()]
    models = {rec["id"]: rec["fingerprint"]["model"] for rec in lines[1:]}
    assert models["t2"] is None
    assert models["t0"] == "openai:gpt-4.1-mini"
    # the raw rubric is hashed, never written
    assert RUBRIC not in (tmp_path / "report.json").read_text()


def test_fingerprint_when_every_row_names_its_grader(tmp_path):
    data = json.loads(RESULTS.read_text())
    data["config"]["defaultTest"]["options"]["provider"] = {
        "id": "openai:gpt-4.1-mini", "config": {"temperature": 0}}
    path = tmp_path / "results.json"
    path.write_text(json.dumps(data))
    r = import_results("promptfoo", [path], metric="helpfulness", out=tmp_path / "rep")
    fp = r["fingerprint"]
    assert fp["model"] == "openai:gpt-4.1-mini"
    assert fp["provider"] == "openai"
    assert fp["temperature"] == 0.0
    assert fp["prompt_hash"] == hashlib.sha256(RUBRIC.encode()).hexdigest()
    flags = [f["message"] for f in r["verdict"]["flags"]]
    assert not any("default grader" in m for m in flags)


def test_assertion_provider_wins_over_test_and_default_options(tmp_path):
    data = json.loads(RESULTS.read_text())
    data["config"]["defaultTest"]["options"]["provider"] = "anthropic:messages:default-model"
    for row in data["results"]["results"]:
        for c in row["gradingResult"]["componentResults"]:
            if c["assertion"].get("metric") == "helpfulness":
                c["assertion"]["provider"] = "openai:gpt-4.1"
                c["assertion"]["rubricPrompt"] = "Grade strictly."
    path = tmp_path / "results.json"
    path.write_text(json.dumps(data))
    rec = next(r for r in read_promptfoo(path) if r.name == "helpfulness")
    assert rec.evaluator["model"] == "openai:gpt-4.1"
    assert "temperature" not in rec.evaluator  # a bare id carries no config
    assert rec.evaluator["prompt"] == RUBRIC + "\n\nGrade strictly."


def test_multiple_metrics_without_metric_is_a_usage_error(tmp_path, capsys):
    assert main(["import", "promptfoo", str(RESULTS), "--out", str(tmp_path / "o")]) == 2
    err = capsys.readouterr().err
    assert "--metric" in err and "factuality" in err and "helpfulness" in err
    with pytest.raises(RecordsError, match="factuality.*helpfulness"):
        import_results("promptfoo", [RESULTS], out=tmp_path / "p")


def test_id_var_reads_ids_from_vars(tmp_path):
    r = import_results("promptfoo", [RESULTS], metric="helpfulness", id_var="qid",
                       out=tmp_path)
    assert {row["id"] for row in r["items"]} == {"Q0", "Q1", "Q2", "Q3", "Q4", "Q5"}
    assert r["headline"]["kappa_mean"] == pytest.approx(4 / 9)


def test_duplicate_descriptions_fall_back_to_derived_ids(tmp_path):
    data = json.loads(RESULTS.read_text())
    for row in data["results"]["results"]:
        row["testCase"]["description"] = "same for every test"
    path = tmp_path / "results.json"
    path.write_text(json.dumps(data))
    records = read_promptfoo(path)
    assert records.ids_derived
    r = import_results("promptfoo", [path], metric="helpfulness", out=tmp_path / "rep")
    assert r["source"]["ids_derived"] is True
    assert r["headline"]["kappa_mean"] == pytest.approx(4 / 9)


def test_two_llm_rubric_components_with_the_same_name_are_an_error(tmp_path):
    data = json.loads(RESULTS.read_text())
    row = data["results"]["results"][0]
    comps = row["gradingResult"]["componentResults"]
    comps.append(copy.deepcopy(next(c for c in comps
                                    if c["assertion"].get("metric") == "helpfulness")))
    path = tmp_path / "results.json"
    path.write_text(json.dumps(data))
    with pytest.raises(RecordsError, match="name them with metric"):
        read_promptfoo(path)


def test_id_var_only_applies_to_promptfoo(tmp_path, capsys):
    assert main(["import", "deepeval", str(FIXTURES / "deepeval" / "results"),
                 "--id-var", "qid", "--out", str(tmp_path)]) == 2
    assert "--id-var" in capsys.readouterr().err
