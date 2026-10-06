"""`judgekeeper import inspect`: an Inspect AI log in, a report out.

Fixture (tests/fixtures/inspect/, made by make_framework_fixtures.py): one `.json` log with 6
samples (ids 1-6) and epochs=3, scorers model_graded_qa and match. Human labels: 1-3 pass,
4-6 fail. Sample 3's label comes from a score edit in epoch 1 (the judge said I, a reviewer
changed it to C), the rest from labels.csv. model_graded_qa values:

  epoch 1: 1 C, 2 C, 3 I (the original, before the edit), 4 I, 5 I, 6 C
  epoch 2: 1 C, 2 C, 3 C, 4 I, 5 I, 6 I
  epoch 3: 1 C, 2 C, 3 C, 4 I, 5 P, 6 I     (P needs --label-map P=fail)

  epoch 1: TP 2, FN 1 (3), TN 2, FP 1 (6) -> TPR 2/3, TNR 2/3,
           po 4/6, judge passes 3 of 6, pe (3*3 + 3*3)/36 = 1/2, kappa 1/3
  epochs 2, 3: every verdict matches -> TPR 1, TNR 1, kappa 1
  means:   TPR (2/3 + 1 + 1)/3 = 8/9, TNR 8/9, kappa (1/3 + 1 + 1)/3 = 7/9
  noise:   3 (I, C, C) and 6 (C, I, I) flip -> 2/6 = 1/3 of items flipped
"""

import hashlib
import json
import sys
from types import ModuleType, SimpleNamespace

import pytest

from judgekeeper import import_results
from judgekeeper.anchors import canonical_json
from judgekeeper.cli import main
from judgekeeper.readers import read_inspect
from judgekeeper.records import RecordsError
from tests.conftest import FIXTURES

DIR = FIXTURES / "inspect"
LOG = DIR / "logs" / "2026-09-30T10-00-00+00-00_qa_fixture.json"
LABELS = DIR / "labels.csv"
OPTIONS = {"instructions": "Grade the answer as C (correct) or I (incorrect).",
           "partial_credit": True}


def _run(tmp_path, *extra):
    out = tmp_path / "rep"
    code = main(["import", "inspect", str(LOG), "--metric", "model_graded_qa",
                 "--labels", str(LABELS), "--out", str(out), *extra])
    return code, out


def test_one_command_turns_the_fixture_into_a_report(tmp_path):
    code, out = _run(tmp_path, "--label-map", "P=fail")
    assert code == 0
    r = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert r["n_runs"] == 3
    assert r["anchors"]["n_items"] == 6
    assert [x["kappa"] for x in r["runs"]] == pytest.approx([1 / 3, 1, 1])
    h = r["headline"]
    assert h["tpr_mean"] == pytest.approx(8 / 9)
    assert h["tnr_mean"] == pytest.approx(8 / 9)
    assert h["kappa_mean"] == pytest.approx(7 / 9)
    assert r["noise_floor"]["items_flipped_fraction"] == pytest.approx(1 / 3)
    assert r["source"]["kind"] == "inspect"
    assert r["source"]["version"] == 2
    assert r["source"]["ids_derived"] is False
    assert r["normaliser"]["label_map"]["c"] == "pass"
    assert r["normaliser"]["label_map"]["p"] == "fail"


def test_partial_credit_needs_a_label_map(tmp_path, capsys):
    code, _ = _run(tmp_path)
    assert code == 2
    err = capsys.readouterr().err
    assert "'P'" in err and "--label-map" in err


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


def test_edited_label_without_a_labels_file(tmp_path):
    r = import_results("inspect", [LOG], metric="model_graded_qa", label_map="P=fail",
                       out=tmp_path)
    # only sample 3 has a human label in the log; the other five are dropped and counted
    assert r["anchors"]["n_items"] == 1
    assert r["source"]["n_judged_unlabeled"] == 5
    assert [row["verdicts"] for row in r["items"]] == [["fail", "pass", "pass"]]


def test_fingerprint_from_model_roles_and_scorer_options(tmp_path):
    r = import_results("inspect", [LOG], metric="model_graded_qa", labels=LABELS,
                       label_map="P=fail", out=tmp_path)
    fp = r["fingerprint"]
    assert fp["model"] == "anthropic/claude-haiku-4-5"
    assert fp["provider"] == "anthropic"
    assert fp["temperature"] == 0.0
    # the scorer's template (Inspect's default here) and instructions; with instructions set,
    # partial_credit no longer changes the prompt
    prompt = {"template": "inspect_ai default for model_graded_qa",
              "instructions": OPTIONS["instructions"]}
    assert fp["prompt_hash"] == hashlib.sha256(canonical_json(prompt).encode()).hexdigest()


def test_scorer_without_options_hashes_the_default_template_not_the_grading_prompt(tmp_path):
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


def test_two_scorers_without_metric_is_a_usage_error(tmp_path, capsys):
    assert main(["import", "inspect", str(LOG), "--labels", str(LABELS),
                 "--out", str(tmp_path)]) == 2
    err = capsys.readouterr().err
    assert "match" in err and "model_graded_qa" in err


def test_eval_without_the_extra_gives_the_documented_error(tmp_path, monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, "inspect_ai", None)  # import inspect_ai fails
    path = tmp_path / "2026-09-30_qa.eval"
    path.write_bytes(b"PK\x03\x04 not a real archive")
    with pytest.raises(RecordsError, match=r"judgekeeper\[inspect\].*inspect log dump"):
        read_inspect(path)
    assert main(["import", "inspect", str(path), "--out", str(tmp_path / "o")]) == 2
    assert "pip install" in capsys.readouterr().err


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
