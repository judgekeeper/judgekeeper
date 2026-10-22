"""Readers against files written by the real tools, not hand-built (tests/fixtures/<tool>/real/).

Each folder holds the script that ran the tool, with no API call, and the small result files it
wrote. No test here runs a tool; regenerate with the scripts (see each folder's README.md).

promptfoo (promptfoo 0.123.1, `eval --repeat 3`, `exec:` answerer and llm-rubric grader):
6 tests Q0-Q5, one prompt. Real files give every repeat its own testIdx, all promptIdx 0 with
identical vars, so the reader must group by item id. The grader passes Q0 Q1 Q5 on every call
and Q2 on its second call only.

Inspect AI (inspect_ai 0.3.273, model_graded_qa with a mockllm grader, epochs 3): samples 1-6.
The grader says
  epoch 1: 1 C, 2 C, 3 I, 4 I, 5 I, 6 C     epochs 2, 3: 1-3 C, 4-6 I
Older Inspect AI logs (old/, inspect_ai 0.3.2 .json and 0.3.204 .eval, model_graded_qa with a
fixed fake grader): samples 1 I, 2 C.

DeepEval (deepeval 4.2.7, a non-LLM BaseMetric "Listed Passes", DEEPEVAL_RESULTS_FOLDER, three
runs, one test_run_*.json each): cases c0-c5. The metric passes
  run 1: c0 c1 c3      run 2: c0 c1 c2 c3      run 3: c0 c1 c2
"""

import hashlib
import json

import pytest

from judgekeeper.anchors import canonical_json
from judgekeeper.readers import read_deepeval, read_inspect, read_promptfoo
from judgekeeper.readers.promptfoo import grading_template
from judgekeeper.records import derive_record_id, fingerprint_known
from judgekeeper.table import make_fingerprint
from tests.conftest import FIXTURES

PF = FIXTURES / "promptfoo" / "real"
INSPECT = FIXTURES / "inspect" / "real"
DEEPEVAL = FIXTURES / "deepeval" / "real"


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def by_item(records) -> dict[str, list[str]]:
    """Each judged item's verdicts, in run order."""
    out: dict[str, list] = {}
    for r in sorted((r for r in records if r.annotator_kind == "LLM"), key=lambda r: r.run):
        out.setdefault(r.target_id, []).append(r.label)
    return out


# promptfoo ----------------------------------------------------------------------------------

def test_real_promptfoo_repeats_have_their_own_test_index():
    # the shape this reader has to handle: one testIdx per repeat, identical vars
    rows = json.loads((PF / "results.json").read_text(encoding="utf-8"))["results"]["results"]
    assert len(rows) == 18
    assert sorted(r["testIdx"] for r in rows) == list(range(18))
    assert {r["promptIdx"] for r in rows} == {0}
    assert [r["vars"]["qid"] for r in rows[:3]] == ["Q0", "Q0", "Q0"]


def test_real_promptfoo_repeats_become_runs():
    records = read_promptfoo(PF / "results.json", id_var="qid")
    assert records.version == 3
    assert {r.name for r in records} == {"helpfulness"}
    assert by_item(records) == {
        "Q0": ["pass"] * 3, "Q1": ["pass"] * 3, "Q2": ["fail", "pass", "fail"],
        "Q3": ["fail"] * 3, "Q4": ["fail"] * 3, "Q5": ["pass"] * 3}
    fps = {make_fingerprint(fingerprint_known(r.evaluator)) for r in records}
    assert len({fp.identity() for fp in fps}) == 1
    fp = fps.pop()
    assert fp.model == "your own script (python3 grader.py)"
    assert fp.provider == "exec"
    # the prompt hash is promptfoo's grading template (the saved grading prompt with the answer
    # and vars put back as placeholders), the same on every row
    row = json.loads((PF / "results.json").read_text(encoding="utf-8"))["results"]["results"][0]
    (comp,) = [c for c in row["gradingResult"]["componentResults"]
               if "renderedGradingPrompt" in (c.get("metadata") or {})]
    template = grading_template(comp["metadata"]["renderedGradingPrompt"],
                                row["response"]["output"], row["vars"])
    assert "<Rubric>\\nThe answer is helpful.\\n</Rubric>" in template
    assert fp.prompt_hash == sha(template)


def test_real_promptfoo_derived_ids_hash_vars_only():
    records = read_promptfoo(PF / "results.json")
    assert records.ids_derived
    rows = json.loads((PF / "results.json").read_text(encoding="utf-8"))["results"]["results"]
    expected = list(dict.fromkeys(derive_record_id(r["vars"], None) for r in rows))
    llm = [r for r in records if r.annotator_kind == "LLM"]
    assert list(dict.fromkeys(r.target_id for r in llm)) == expected
    assert len(expected) == 6
    runs = {}
    for r in llm:
        runs.setdefault(r.target_id, []).append(r.run)
    assert all(v == [1, 2, 3] for v in runs.values())


# Inspect AI ---------------------------------------------------------------------------------

DEFAULT_QA = canonical_json({"instructions": "inspect_ai default for model_graded_qa",
                             "template": "inspect_ai default for model_graded_qa"})


def test_real_inspect_epochs_become_runs():
    records = read_inspect(INSPECT / "logs" / "model_graded_qa.json")
    assert records.version == 2
    assert by_item(records) == {
        "1": ["C"] * 3, "2": ["C"] * 3, "3": ["I", "C", "C"],
        "4": ["I"] * 3, "5": ["I"] * 3, "6": ["C", "I", "I"]}
    fp = make_fingerprint(fingerprint_known(records[0].evaluator))
    assert fp.model == "mockllm/model"
    assert fp.provider == "mockllm"


def test_real_inspect_prompt_hash_is_the_default_template_identity():
    # the scorer sets no template or instructions; the rendered grading prompt differs per
    # sample and must not be hashed
    records = [r for r in read_inspect(INSPECT / "logs" / "model_graded_qa.json")
               if r.annotator_kind == "LLM"]
    assert {r.evaluator["prompt"] for r in records} == {DEFAULT_QA}
    assert make_fingerprint(fingerprint_known(records[0].evaluator)).prompt_hash == sha(DEFAULT_QA)


@pytest.mark.parametrize("name", ["inspect-0.3.2.json", "inspect-0.3.204.eval"])
def test_real_inspect_logs_from_older_versions_are_read(name):
    # written by the oldest inspect_ai the extra allows and by one six months older than 1.0
    if name.endswith(".eval"):
        pytest.importorskip("inspect_ai")
    records = read_inspect(INSPECT / "old" / name)
    assert by_item(records) == {"1": ["I"], "2": ["C"]}


# DeepEval -----------------------------------------------------------------------------------

def test_real_deepeval_files_become_runs():
    passed = []
    for f in sorted((DEEPEVAL / "results").glob("test_run_*.json")):
        records = read_deepeval(f)
        assert not records.ids_derived
        assert {r.name for r in records} == {"Listed Passes"}
        assert records.per_metric["Listed Passes"]["threshold"] == 0.5
        # a non-LLM metric records no evaluationModel
        assert all(make_fingerprint(fingerprint_known(r.evaluator)).model is None
                   for r in records)
        passed.append([r.target_id for r in records if r.label == "pass"])
    assert passed == [["c0", "c1", "c3"], ["c0", "c1", "c2", "c3"], ["c0", "c1", "c2"]]
