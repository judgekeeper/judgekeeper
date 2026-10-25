"""The Inspect AI reader: an Inspect AI log in, ScoreRecords out.

Fixture (tests/fixtures/inspect/, made by make_framework_fixtures.py): one `.json` log with 6
samples (ids 1-6) and epochs=3, scorers model_graded_qa and match. Sample 3 has a score edit in
epoch 1 (the judge said I, a reviewer changed it to C), the one human label in the log.
model_graded_qa values:

  epoch 1: 1 C, 2 C, 3 I (the original, before the edit), 4 I, 5 I, 6 C
  epoch 2: 1 C, 2 C, 3 C, 4 I, 5 I, 6 I
  epoch 3: 1 C, 2 C, 3 C, 4 I, 5 P, 6 I     (P, partial credit, has no default meaning)
"""

import hashlib
import json
import sys
from types import ModuleType, SimpleNamespace

import pytest

from judgekeeper.anchors import canonical_json
from judgekeeper.readers import read_inspect
from judgekeeper.records import HUMAN, LLM, RecordsError, fingerprint_known
from judgekeeper.table import make_fingerprint
from tests.conftest import FIXTURES

DIR = FIXTURES / "inspect"
LOG = DIR / "logs" / "2026-09-30T10-00-00+00-00_qa_fixture.json"
OPTIONS = {"instructions": "Grade the answer as C (correct) or I (incorrect).",
           "partial_credit": True}


def test_the_fixture_is_a_log_inspect_ai_accepts():
    log = pytest.importorskip("inspect_ai.log")
    assert len(log.read_eval_log(str(LOG)).samples) == 18


def test_the_log_reads_as_judge_records_with_its_label_map():
    records = read_inspect(LOG)
    assert records.version == 2
    assert not records.ids_derived
    assert records.label_map == {"C": "pass", "I": "fail"}
    llm = [r for r in records if r.annotator_kind == LLM and r.name == "model_graded_qa"]
    assert len(llm) == 18  # 6 samples x 3 epochs
    assert {r.target_id for r in llm} == {str(i) for i in range(1, 7)}
    assert [r.label for r in llm if r.target_id == "5"] == ["I", "I", "P"]


def test_epochs_become_runs():
    records = read_inspect(LOG)
    llm = [r for r in records if r.annotator_kind == "LLM" and r.name == "model_graded_qa"]
    assert sorted({r.run for r in llm}) == [1, 2, 3]
    assert [r.label for r in llm if r.target_id == "6"] == ["C", "I", "I"]


def test_an_edited_score_gives_judge_and_human_from_one_sample():
    records = read_inspect(LOG)
    s3 = [r for r in records if r.target_id == "3" and r.name == "model_graded_qa"]
    human = [r for r in s3 if r.annotator_kind == "HUMAN"]
    judge_epoch1 = next(r for r in s3 if r.annotator_kind == "LLM" and r.run == 1)
    assert len(human) == 1 and human[0].label == "C"
    assert human[0].explanation == "the answer is right"
    assert judge_epoch1.label == "I"
    assert judge_epoch1.explanation == "epoch 1: GRADE: I"


def test_only_the_edited_sample_has_a_human_label_in_the_log():
    human = [r for r in read_inspect(LOG) if r.annotator_kind == HUMAN]
    assert [(r.target_id, r.name, r.label) for r in human] == [("3", "model_graded_qa", "C")]


def test_fingerprint_from_model_roles_and_scorer_options():
    rec = next(r for r in read_inspect(LOG)
               if r.annotator_kind == LLM and r.name == "model_graded_qa")
    fp = make_fingerprint(fingerprint_known(rec.evaluator))
    assert fp.model == "anthropic/claude-haiku-4-5"
    assert fp.provider == "anthropic"
    assert fp.temperature == 0.0
    # the scorer's template (Inspect's default here) and instructions; with instructions set,
    # partial_credit no longer changes the prompt
    prompt = {"template": "inspect_ai default for model_graded_qa",
              "instructions": OPTIONS["instructions"]}
    assert fp.prompt_hash == hashlib.sha256(canonical_json(prompt).encode()).hexdigest()


def _no_grader(tmp_path, rename=None, metadata=None):
    data = json.loads(LOG.read_text(encoding="utf-8"))
    data["eval"].pop("model_roles", None)
    for sample in data["samples"]:
        scores = sample["scores"]
        score = scores.pop("model_graded_qa")
        score["metadata"] = metadata or {}
        scores[rename or "model_graded_qa"] = score
    path = tmp_path / "log.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return [r for r in read_inspect(path) if r.annotator_kind == LLM and r.name != "match"]


def test_a_model_in_the_scores_name_is_the_judges_model(tmp_path):
    # as R's vitals package writes it: the grader's model after the scorer's name
    name = "model_graded_qa(partial_credit = TRUE) (claude-sonnet-4-5)"
    recs = _no_grader(tmp_path, rename=name)
    assert recs and {r.evaluator.get("model") for r in recs} == {"claude-sonnet-4-5"}
    assert {r.name for r in recs} == {name}


def test_a_model_in_the_scores_metadata_is_the_judges_model(tmp_path):
    recs = _no_grader(tmp_path, metadata={"grader_model": "openai/gpt-4.1"})
    assert {r.evaluator.get("model") for r in recs} == {"openai/gpt-4.1"}
    assert {r.evaluator.get("provider") for r in recs} == {"openai"}


def test_no_model_anywhere_is_no_model(tmp_path):
    recs = _no_grader(tmp_path, rename="bluff_scorer (strict)", metadata={"grading": []})
    assert {r.evaluator.get("model") for r in recs} == {None}


def test_scorer_without_options_hashes_the_default_template(tmp_path):
    data = json.loads(LOG.read_text(encoding="utf-8"))
    data["eval"]["scorers"] = [s for s in data["eval"]["scorers"]
                               if s["name"] != "model_graded_qa"]
    path = tmp_path / "log.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    prompts = {r.evaluator["prompt"] for r in read_inspect(path)
               if r.name == "model_graded_qa" and r.annotator_kind == "LLM"}
    # one prompt for every sample: metadata.grading holds each sample's text and is not used
    assert prompts == {canonical_json({"template": "inspect_ai default for model_graded_qa",
                                       "instructions": "inspect_ai default for model_graded_qa"})}


def test_eval_without_the_extra_gives_the_documented_error(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "inspect_ai", None)  # import inspect_ai fails
    monkeypatch.setitem(sys.modules, "inspect_ai.log", None)
    path = tmp_path / "2026-09-30_qa.eval"
    path.write_bytes(b"PK\x03\x04 not a real archive")
    with pytest.raises(RecordsError, match=r"judgekeeper\[inspect\].*inspect log dump"):
        read_inspect(path)


def refusing_inspect_ai(monkeypatch):
    """An installed inspect_ai that refuses every log."""
    def read_eval_log(path, **kwargs):
        raise ValueError("not valid")

    pkg, log_mod = ModuleType("inspect_ai"), ModuleType("inspect_ai.log")
    log_mod.read_eval_log = read_eval_log
    pkg.log = log_mod
    monkeypatch.setitem(sys.modules, "inspect_ai", pkg)
    monkeypatch.setitem(sys.modules, "inspect_ai.log", log_mod)


def test_a_json_log_inspect_ai_refuses_is_read_as_json(tmp_path, monkeypatch):
    data = json.loads(LOG.read_text(encoding="utf-8"))
    data["samples"][0]["scores"] = "damaged"
    path = tmp_path / "log.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    expected = read_inspect(path, with_errors=True)
    refusing_inspect_ai(monkeypatch)
    assert read_inspect(path, with_errors=True) == expected


def test_a_cut_off_json_log_is_said_as_cut_off_with_inspect_ai(tmp_path, monkeypatch):
    refusing_inspect_ai(monkeypatch)
    path = tmp_path / "log.json"
    path.write_text(LOG.read_text(encoding="utf-8")[:500], encoding="utf-8")
    with pytest.raises(RecordsError, match="cut off or damaged"):
        read_inspect(path)


@pytest.mark.parametrize("data, said", [({"results": [{"text": "secret"}]}, "not an Inspect AI log"),
                                        ({"eval": {}, "samples": []}, "the log has no samples")])
def test_json_that_is_no_inspect_log_is_still_refused_with_inspect_ai(tmp_path, monkeypatch,
                                                                      data, said):
    refusing_inspect_ai(monkeypatch)
    path = tmp_path / "log.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(RecordsError, match=said) as e:
        read_inspect(path)
    assert "secret" not in str(e.value)


def test_an_eval_log_inspect_ai_refuses_is_said_in_plain_words(tmp_path, monkeypatch):
    refusing_inspect_ai(monkeypatch)
    path = tmp_path / "log.eval"
    path.write_bytes(b"PK\x03\x04 not a real archive")
    with pytest.raises(RecordsError, match="may be cut short, or not an Inspect AI log"):
        read_inspect(path)


def test_eval_is_read_with_read_eval_log_when_installed(tmp_path, monkeypatch):
    data = json.loads(LOG.read_text(encoding="utf-8"))
    seen = []

    def read_eval_log(path):
        seen.append(str(path))
        return SimpleNamespace(model_dump=lambda mode="json": data)

    pkg, log_mod = ModuleType("inspect_ai"), ModuleType("inspect_ai.log")
    log_mod.read_eval_log = read_eval_log
    pkg.log = log_mod
    monkeypatch.setitem(sys.modules, "inspect_ai", pkg)
    monkeypatch.setitem(sys.modules, "inspect_ai.log", log_mod)
    path = tmp_path / "2026-09-30_qa.eval"
    path.write_bytes(b"zip")
    records = read_inspect(path)
    assert seen == [str(path)]
    assert len([r for r in records if r.name == "model_graded_qa"]) == 18 + 1
