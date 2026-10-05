"""Readers against files written by the real tools, not hand-built (tests/fixtures/<tool>/real/).

Each folder holds the script that ran the tool, with no API call, and the small result files it
wrote. No test here runs a tool; regenerate with the scripts (see each folder's README.md).

promptfoo (promptfoo 0.123.1, `eval --repeat 3`, `exec:` answerer and llm-rubric grader):
6 tests Q0-Q5, one prompt. Real files give every repeat its own testIdx, all promptIdx 0 with
identical vars, so the reader must group by item id. Human (labels.csv): Q0-Q2 pass, Q3-Q5
fail. The grader passes Q0 Q1 Q5 on every call and Q2 on its second call only:
  repeats 1, 3: TP Q0 Q1 = 2, FN Q2 = 1, TN Q3 Q4 = 2, FP Q5 = 1 -> TPR 2/3, TNR 2/3,
                po 4/6, judge passes 3 of 6, pe (3*3 + 3*3)/36 = 1/2, kappa (2/3-1/2)/(1/2) = 1/3
  repeat 2:     TP 3, FN 0, TN 2, FP 1 -> TPR 1, TNR 2/3,
                po 5/6, judge passes 4, pe (3*4 + 3*2)/36 = 1/2, kappa (5/6-1/2)/(1/2) = 2/3
  means:        TPR (2/3 + 1 + 2/3)/3 = 7/9, TNR 2/3, kappa (1/3 + 2/3 + 1/3)/3 = 4/9
  noise floor:  Q2 is the only item whose verdict changes -> 1/6 flipped.

Inspect AI (inspect_ai 0.3.273, model_graded_qa with a mockllm grader, epochs 3): samples 1-6.
Human (labels.csv): 1-3 pass, 4-6 fail. The grader says
  epoch 1: 1 C, 2 C, 3 I, 4 I, 5 I, 6 C     epochs 2, 3: 1-3 C, 4-6 I
  epoch 1:     TP 2, FN 1 (3), TN 2, FP 1 (6) -> TPR 2/3, TNR 2/3, kappa 1/3 (as above)
  epochs 2, 3: every verdict matches -> TPR 1, TNR 1, kappa 1
  means:       TPR (2/3 + 1 + 1)/3 = 8/9, TNR 8/9, kappa (1/3 + 1 + 1)/3 = 7/9
  noise floor: 3 (I, C, C) and 6 (C, I, I) flip -> 2/6 = 1/3.

DeepEval (deepeval 4.2.7, a non-LLM BaseMetric "Listed Passes", DEEPEVAL_RESULTS_FOLDER, three
runs, one test_run_*.json each): cases c0-c5. Human (labels.csv): c0-c2 pass, c3-c5 fail.
The metric passes
  run 1: c0 c1 c3      run 2: c0 c1 c2 c3      run 3: c0 c1 c2
  run 1: TP 2, FN 1 (c2), TN 2, FP 1 (c3) -> TPR 2/3, TNR 2/3, kappa 1/3
  run 2: TP 3, FN 0, TN 2, FP 1 (c3) -> TPR 1, TNR 2/3, kappa 2/3 (as promptfoo repeat 2)
  run 3: every verdict matches -> TPR 1, TNR 1, kappa 1
  means: TPR (2/3 + 1 + 1)/3 = 8/9, TNR (2/3 + 2/3 + 1)/3 = 7/9, kappa (1/3 + 2/3 + 1)/3 = 2/3
  noise floor: c2 (fail, pass, pass) and c3 (pass, pass, fail) flip -> 2/6 = 1/3.
"""

import hashlib
import json

import pytest

from judgekeeper import import_results
from judgekeeper.anchors import canonical_json
from judgekeeper.cli import main
from judgekeeper.readers import read_inspect, read_promptfoo
from judgekeeper.readers.promptfoo import grading_template
from judgekeeper.records import derive_record_id
from tests.conftest import FIXTURES

PF = FIXTURES / "promptfoo" / "real"
INSPECT = FIXTURES / "inspect" / "real"
DEEPEVAL = FIXTURES / "deepeval" / "real"


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def check(r, kappa, tpr, tnr, means, flipped):
    assert r["n_runs"] == len(kappa)
    assert r["anchors"]["n_items"] == 6
    assert [x["kappa"] for x in r["runs"]] == pytest.approx(kappa)
    assert [x["tpr"] for x in r["runs"]] == pytest.approx(tpr)
    assert [x["tnr"] for x in r["runs"]] == pytest.approx(tnr)
    h = r["headline"]
    assert (h["tpr_mean"], h["tnr_mean"], h["kappa_mean"]) == pytest.approx(means)
    assert r["noise_floor"]["items_flipped_fraction"] == pytest.approx(flipped)


# promptfoo ----------------------------------------------------------------------------------

PF_EXPECTED = {"kappa": [1 / 3, 2 / 3, 1 / 3], "tpr": [2 / 3, 1, 2 / 3], "tnr": [2 / 3] * 3,
               "means": (7 / 9, 2 / 3, 4 / 9), "flipped": 1 / 6}


def test_real_promptfoo_repeats_have_their_own_test_index():
    # the shape this reader has to handle: one testIdx per repeat, identical vars
    rows = json.loads((PF / "results.json").read_text())["results"]["results"]
    assert len(rows) == 18
    assert sorted(r["testIdx"] for r in rows) == list(range(18))
    assert {r["promptIdx"] for r in rows} == {0}
    assert [r["vars"]["qid"] for r in rows[:3]] == ["Q0", "Q0", "Q0"]


@pytest.mark.parametrize("extra", [[], ["--runs-by-order"]])
def test_real_promptfoo_repeats_become_runs(tmp_path, extra):
    out = tmp_path / "rep"
    assert main(["import", "promptfoo", str(PF / "results.json"), "--id-var", "qid",
                 "--labels", str(PF / "labels.csv"), "--out", str(out), *extra]) == 0
    r = json.loads((out / "report.json").read_text())
    check(r, **PF_EXPECTED)
    assert r["source"]["version"] == 3
    assert r["source"]["metric"] == "helpfulness"
    fp = r["fingerprint"]
    assert fp["model"] == "exec: python3 grader.py"
    assert fp["provider"] == "exec"
    # the prompt hash is promptfoo's grading template (the saved grading prompt with the answer
    # and vars put back as placeholders), the same on every row
    row = json.loads((PF / "results.json").read_text())["results"]["results"][0]
    (comp,) = [c for c in row["gradingResult"]["componentResults"]
               if "renderedGradingPrompt" in (c.get("metadata") or {})]
    template = grading_template(comp["metadata"]["renderedGradingPrompt"],
                                row["response"]["output"], row["vars"])
    assert "<Rubric>\\nThe answer is helpful.\\n</Rubric>" in template
    assert fp["prompt_hash"] == sha(template)


def test_real_promptfoo_derived_ids_hash_vars_only():
    records = read_promptfoo(PF / "results.json")
    assert records.ids_derived
    rows = json.loads((PF / "results.json").read_text())["results"]["results"]
    expected = list(dict.fromkeys(derive_record_id(r["vars"], None) for r in rows))
    llm = [r for r in records if r.annotator_kind == "LLM"]
    assert list(dict.fromkeys(r.target_id for r in llm)) == expected
    assert len(expected) == 6
    runs = {}
    for r in llm:
        runs.setdefault(r.target_id, []).append(r.run)
    assert all(v == [1, 2, 3] for v in runs.values())


def test_real_promptfoo_with_derived_ids_gives_the_same_report(tmp_path):
    # labels keyed by derived id: the same human labels as labels.csv
    rows = json.loads((PF / "results.json").read_text())["results"]["results"]
    human = {"Q0": "pass", "Q1": "pass", "Q2": "pass", "Q3": "fail", "Q4": "fail", "Q5": "fail"}
    labels = tmp_path / "labels.csv"
    ids = dict.fromkeys((derive_record_id(r["vars"], None), r["vars"]["qid"]) for r in rows)
    labels.write_text("id,human_label\n" + "".join(f"{i},{human[q]}\n" for i, q in ids))
    r = import_results("promptfoo", [PF / "results.json"], labels=labels, out=tmp_path / "rep")
    check(r, **PF_EXPECTED)
    assert r["source"]["ids_derived"] is True


# Inspect AI ---------------------------------------------------------------------------------

INSPECT_EXPECTED = {"kappa": [1 / 3, 1, 1], "tpr": [2 / 3, 1, 1], "tnr": [2 / 3, 1, 1],
                    "means": (8 / 9, 8 / 9, 7 / 9), "flipped": 1 / 3}
DEFAULT_QA = canonical_json({"instructions": "inspect_ai default for model_graded_qa",
                             "template": "inspect_ai default for model_graded_qa"})


@pytest.mark.parametrize("extra", [[], ["--runs-by-order"]])
def test_real_inspect_epochs_become_runs(tmp_path, extra):
    out = tmp_path / "rep"
    assert main(["import", "inspect", str(INSPECT / "logs"), "--labels",
                 str(INSPECT / "labels.csv"), "--out", str(out), *extra]) == 0
    r = json.loads((out / "report.json").read_text())
    check(r, **INSPECT_EXPECTED)
    assert r["source"]["version"] == 2
    fp = r["fingerprint"]
    assert fp["model"] == "mockllm/model"
    assert fp["provider"] == "mockllm"


def test_real_inspect_prompt_hash_is_the_default_template_identity(tmp_path):
    # the scorer sets no template or instructions; the rendered grading prompt differs per
    # sample and must not be hashed
    records = [r for r in read_inspect(INSPECT / "logs" / "model_graded_qa.json")
               if r.annotator_kind == "LLM"]
    assert {r.evaluator["prompt"] for r in records} == {DEFAULT_QA}
    r = import_results("inspect", [INSPECT / "logs"], labels=INSPECT / "labels.csv",
                       out=tmp_path)
    assert r["fingerprint"]["prompt_hash"] == sha(DEFAULT_QA)
    assert "prompt_hash" not in r["fingerprint_unknown"]


# DeepEval -----------------------------------------------------------------------------------

DEEPEVAL_EXPECTED = {"kappa": [1 / 3, 2 / 3, 1], "tpr": [2 / 3, 1, 1], "tnr": [2 / 3, 2 / 3, 1],
                     "means": (8 / 9, 7 / 9, 2 / 3), "flipped": 1 / 3}


@pytest.mark.parametrize("extra", [[], ["--runs-by-order"]])
def test_real_deepeval_files_become_runs(tmp_path, extra):
    out = tmp_path / "rep"
    assert main(["import", "deepeval", str(DEEPEVAL / "results"), "--labels",
                 str(DEEPEVAL / "labels.csv"), "--out", str(out), *extra]) == 0
    r = json.loads((out / "report.json").read_text())
    check(r, **DEEPEVAL_EXPECTED)
    assert r["source"]["metric"] == "Listed Passes"
    assert r["source"]["ids_derived"] is False
    assert r["source"]["threshold"] == 0.5
    # a non-LLM metric records no evaluationModel
    assert r["fingerprint"]["model"] is None
