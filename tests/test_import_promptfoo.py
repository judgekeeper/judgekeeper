"""The promptfoo reader: a promptfoo `-o results.json` in, ScoreRecords out.

Fixture (tests/fixtures/promptfoo/results.json, made by make_framework_fixtures.py): 7 tests
t0..t6, one prompt, --repeat 3, so 21 rows with no repeat index, each with its own testIdx
(as real files have; see tests/fixtures/promptfoo/real/). Each row has a `contains`
component (code), an llm-rubric component with metric "helpfulness" and a factuality
component. Humans rated repeat 1 of t0-t5 in the web UI: t0-t2 pass, t3-t5 fail. t6 has no
rating.

On t2 and t5 in repeat 1 the human rating overrides the row's `success` (t2 true, t5 false);
the judge's own verdict is the llm-rubric component (t2 fail, t5 pass).

t2 has no grader provider anywhere (assertion, test options, defaultTest), so promptfoo used
its built-in default grader; the others name openai:gpt-4.1-mini at temperature 0.
"""

import copy
import hashlib
import json

import pytest

from judgekeeper.readers import read_promptfoo
from judgekeeper.records import CODE, HUMAN, LLM, RecordsError, fingerprint_known
from judgekeeper.table import make_fingerprint
from tests.conftest import FIXTURES

RESULTS = FIXTURES / "promptfoo" / "results.json"
RUBRIC = "The answer is helpful and correct."


def test_the_fixture_reads_as_judge_human_and_code_records():
    records = read_promptfoo(RESULTS)
    assert records.version == 3
    assert {(r.annotator_kind, r.name) for r in records} == {
        (LLM, "helpfulness"), (LLM, "factuality"), (CODE, "contains"), (HUMAN, "human")}
    judge = [r for r in records if r.annotator_kind == LLM and r.name == "helpfulness"]
    assert len(judge) == 21
    assert {r.target_id for r in judge} == {f"t{i}" for i in range(7)}
    # humans rated t0-t5; t6 has no rating
    human = {r.target_id: r.label for r in records if r.annotator_kind == HUMAN}
    assert human == {"t0": "pass", "t1": "pass", "t2": "pass",
                     "t3": "fail", "t4": "fail", "t5": "fail"}


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


def test_default_grader_is_flagged_and_its_model_unknown():
    records = read_promptfoo(RESULTS)
    [warning] = records.per_metric["helpfulness"]["warnings"]
    assert "default grader model not recorded by promptfoo" in warning
    # each judgment keeps its own grader: t2's model is unknown, the others are known
    models = {r.target_id: r.evaluator.get("model") for r in records
              if r.annotator_kind == LLM and r.name == "helpfulness" and r.run == 1}
    assert models["t2"] is None
    assert models["t0"] == "openai:gpt-4.1-mini"


def test_fingerprint_when_every_row_names_its_grader(tmp_path):
    data = json.loads(RESULTS.read_text(encoding="utf-8"))
    data["config"]["defaultTest"]["options"]["provider"] = {
        "id": "openai:gpt-4.1-mini", "config": {"temperature": 0}}
    path = tmp_path / "results.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    records = read_promptfoo(path)
    assert not records.per_metric.get("helpfulness", {}).get("warnings")
    fps = [make_fingerprint(fingerprint_known(r.evaluator)) for r in records
           if r.annotator_kind == LLM and r.name == "helpfulness"]
    assert len({fp.identity() for fp in fps}) == 1  # one judge on every row
    fp = fps[0]
    assert fp.model == "openai:gpt-4.1-mini"
    assert fp.provider == "openai"
    assert fp.temperature == 0.0
    assert fp.prompt_hash == hashlib.sha256(RUBRIC.encode()).hexdigest()


def test_assertion_provider_wins_over_test_and_default_options(tmp_path):
    data = json.loads(RESULTS.read_text(encoding="utf-8"))
    data["config"]["defaultTest"]["options"]["provider"] = "anthropic:messages:default-model"
    for row in data["results"]["results"]:
        for c in row["gradingResult"]["componentResults"]:
            if c["assertion"].get("metric") == "helpfulness":
                c["assertion"]["provider"] = "openai:gpt-4.1"
                c["assertion"]["rubricPrompt"] = "Grade strictly."
    path = tmp_path / "results.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    rec = next(r for r in read_promptfoo(path) if r.name == "helpfulness")
    assert rec.evaluator["model"] == "openai:gpt-4.1"
    assert "temperature" not in rec.evaluator  # a bare id carries no config
    assert rec.evaluator["prompt"] == RUBRIC + "\n\nGrade strictly."


def test_id_var_reads_ids_from_vars():
    records = read_promptfoo(RESULTS, id_var="qid")
    assert not records.ids_derived
    assert {r.target_id for r in records} == {f"Q{i}" for i in range(7)}
    human = {r.target_id for r in records if r.annotator_kind == HUMAN}
    assert human == {"Q0", "Q1", "Q2", "Q3", "Q4", "Q5"}


def test_duplicate_descriptions_fall_back_to_derived_ids(tmp_path):
    data = json.loads(RESULTS.read_text(encoding="utf-8"))
    for row in data["results"]["results"]:
        row["testCase"]["description"] = "same for every test"
    path = tmp_path / "results.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    records = read_promptfoo(path)
    assert records.ids_derived
    judge = [r for r in records if r.annotator_kind == LLM and r.name == "helpfulness"]
    assert len({r.target_id for r in judge}) == 7  # one id per test, not one for all


def test_two_llm_rubric_components_with_the_same_name_are_an_error(tmp_path):
    data = json.loads(RESULTS.read_text(encoding="utf-8"))
    row = data["results"]["results"][0]
    comps = row["gradingResult"]["componentResults"]
    comps.append(copy.deepcopy(next(c for c in comps
                                    if c["assertion"].get("metric") == "helpfulness")))
    path = tmp_path / "results.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(RecordsError, match="a name with metric: in its assertion"):
        read_promptfoo(path)
