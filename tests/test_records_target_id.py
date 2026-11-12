"""Labels in a records file matched by `target_id`: a HUMAN line with no input or output takes
the text of the LLM line with the same `target_id` (same name first), as tools such as
mcp-server-tester write them. Answer ids stay made from the text, so marks saved before keep
matching. A label left with no graded answer says so. Records format v2 is a public
interface: its schema and the columns `fix` hands back are pinned.

The fixture `fixtures/records/target-id-only-labels.jsonl` is written by hand in that tool's
shape: 20 cases x 2 trials, ids like `case-3/trial-1/judge`, `run` the trial, `metadata.mst`.
Two trials have no LLM line (the judge said "unknown") and two have no HUMAN line: 38 LLM
lines and 38 HUMAN lines, so 36 labels find their answer and 2 have no grade.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import shutil
from pathlib import Path

import pytest

from judgekeeper import labels, start
from judgekeeper.cli import main
from judgekeeper.normalise import Normaliser
from judgekeeper.records import DEFAULT_NAME, derive_record_id, read_records
from tests.start_projects import records_project, split

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = Path(__file__).parent / "fixtures" / "records" / "target-id-only-labels.jsonl"
EXAMPLE = ROOT / "docs" / "examples" / "records" / "with-human-labels.jsonl"
SCHEMA = ROOT / "src" / "judgekeeper" / "schemas" / "records.schema.json"
SCHEMA_SHA256 = "a3b8050029c7e9c95d9fb2e10b496b946e566c4bbc257ab6fb8bee352a3fb832"
PAGE = ("--no-browser", "--port", "0", "--yes")


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def flat(text: str) -> str:
    return " ".join(text.split())


def mst_lines(cases: int, unknown=(), unlabelled=()) -> list[dict]:
    """Lines in mcp-server-tester's shape: per trial an LLM line with the text, then a HUMAN
    line with only the `target_id`. `unknown`: (case, trial) with no LLM line; `unlabelled`:
    with no HUMAN line."""
    out = []
    for c in range(1, cases + 1):
        for t in (1, 2):
            common = {"schema_version": 2, "target_id": f"case-{c}/trial-{t}/judge",
                      "name": "judge"}
            says = "fail" if (c + t) % 3 == 0 else "pass"
            if (c, t) not in unknown:
                out.append({**common, "annotator_kind": "LLM", "label": says, "run": t,
                            "input": f"Question {c}?", "output": f"Answer {c}, try {t}.",
                            "evaluator": {"model": "claude-sonnet-5-5"},
                            "metadata": {"mst": {"caseId": f"case-{c}", "trial": t}}})
            if (c, t) not in unlabelled:
                out.append({**common, "annotator_kind": "HUMAN", "label": says,
                            "metadata": {"mst": {"caseId": f"case-{c}", "trial": t}}})
    return out


def write(path: Path, lines: list[dict]) -> Path:
    path.write_text("".join(json.dumps(x) + "\n" for x in lines), encoding="utf-8")
    return path


def plan_of(path: Path, metric: str = DEFAULT_NAME) -> labels.Plan:
    """What `--labels` (the labels in the results) makes of a records file, one level below
    the command: the pool, its human labels, and the match. A name "judge" reads as
    DEFAULT_NAME."""
    records = read_records(path, cut_end_ok=True, bad_lines_ok=True)
    pool = start.build_pool([(path.name, records)], metric, Normaliser())
    found = labels.in_results(pool, metric)
    rows = {a.id: {"input": a.input, "output": a.output} for a in pool.answers}
    return labels.match(found, rows, [{"id": a.id} for a in pool.answers], pool.left)


# The fix ------------------------------------------------------------------------------------

def test_a_human_line_with_only_a_target_id_takes_the_text_of_its_llm_line(tmp_path):
    records = read_records(write(tmp_path / "r.jsonl", mst_lines(2)))
    llm = {r.target_id: r for r in records if r.annotator_kind == "LLM"}
    humans = [r for r in records if r.annotator_kind == "HUMAN"]
    assert len(humans) == 4
    for h in humans:
        assert (h.input, h.output) == (llm[h.target_id].input, llm[h.target_id].output)
        assert h.target_id.endswith("/judge")  # its own id, as written


def test_the_fixture_imports_its_labels_by_target_id(here, capsys):
    shutil.copy(FIXTURE, here / "results.jsonl")
    code = main(["--labels", *PAGE])
    out = flat("".join(capsys.readouterr()))
    assert "Answers: 38 answers" in out, out
    assert ("Added 36 marks from your results (21 Pass, 15 Fail). Skipped 2 labels: "
            "2 labels have no LLM-as-a-judge grade") in out, out
    assert "the answer text must be the same" not in out
    assert "Step 3 of 5: Measure" in out  # the 36 imported marks give a first result
    assert code in (0, 3), out


def test_the_ten_cases_shape_adds_16_and_skips_2(tmp_path):
    path = write(tmp_path / "r.jsonl",
                 mst_lines(10, unknown={(4, 2), (8, 1)}, unlabelled={(6, 1), (10, 2)}))
    plan = plan_of(path)
    assert len(plan.marks) == 16
    assert labels.skipped_lines(plan) == ["Skipped 2 labels:",
                                          "  2 labels have no LLM-as-a-judge grade"]


def test_one_label_with_no_grade_is_said_in_the_singular(tmp_path):
    plan = plan_of(write(tmp_path / "r.jsonl", mst_lines(3, unknown={(2, 1)})))
    assert labels.skipped_lines(plan) == ["Skipped 1 label:",
                                          "  1 label has no LLM-as-a-judge grade"]


def test_the_example_file_imports_its_labels():
    plan = plan_of(EXAMPLE, "Safe wording")
    assert sorted(plan.marks.values()) == ["fail", "pass", "pass", "pass"]
    assert plan.skipped == {}


def test_a_human_line_with_text_still_matches_by_its_text(tmp_path):
    lines = mst_lines(2)
    lines = [x for x in lines if x["annotator_kind"] == "LLM"]
    lines.append({"target_id": "someone-else", "name": "judge", "annotator_kind": "HUMAN",
                  "label": "fail", "input": "Question 2?", "output": "Answer 2, try 1."})
    plan = plan_of(write(tmp_path / "r.jsonl", lines))
    assert list(plan.marks.values()) == ["fail"] and plan.skipped == {}
    assert list(plan.marks) == [derive_record_id("Question 2?", "Answer 2, try 1.")]


def test_two_llm_lines_with_one_target_id_and_different_text_are_not_guessed(tmp_path):
    lines = mst_lines(2)
    twin = next(x for x in lines if x["annotator_kind"] == "LLM")
    lines.append({**twin, "output": "Another answer with the same id."})
    records = read_records(write(tmp_path / "r.jsonl", lines))
    human = next(r for r in records
                 if r.annotator_kind == "HUMAN" and r.target_id == twin["target_id"])
    assert human.input is None and human.output is None  # left as written
    plan = plan_of(tmp_path / "r.jsonl")
    assert len(plan.marks) == 3
    assert labels.skipped_lines(plan) == ["Skipped 1 label:",
                                          "  1 label has no LLM-as-a-judge grade"]


def test_the_llm_line_with_the_same_name_is_taken_first(tmp_path):
    lines = [
        {"target_id": "t1", "name": "tone", "annotator_kind": "LLM", "label": "pass",
         "input": "Q?", "output": "Tone answer."},
        {"target_id": "t1", "name": "facts", "annotator_kind": "LLM", "label": "fail",
         "input": "Q?", "output": "Facts answer."},
        {"target_id": "t1", "name": "facts", "annotator_kind": "HUMAN", "label": "fail"},
        {"target_id": "t1", "name": "other", "annotator_kind": "HUMAN", "label": "pass"},
        {"target_id": "t2", "name": "tone", "annotator_kind": "LLM", "label": "pass",
         "input": "Q2?", "output": "Only one."},
        {"target_id": "t2", "name": "other", "annotator_kind": "HUMAN", "label": "pass"}]
    records = read_records(write(tmp_path / "r.jsonl", lines))
    humans = [r for r in records if r.annotator_kind == "HUMAN"]
    assert humans[0].output == "Facts answer."  # its own name
    assert humans[1].output is None  # no line with its name, and two others that differ
    assert humans[2].output == "Only one."  # no line with its name: the one with its id


def test_a_human_line_with_no_target_id_and_no_text_is_left_alone(tmp_path):
    lines = [x for x in mst_lines(1) if x["annotator_kind"] == "LLM"]
    lines.append({"name": "judge", "annotator_kind": "HUMAN", "label": "pass"})
    records = read_records(write(tmp_path / "r.jsonl", lines))
    assert records[-1].output is None and records.ids_derived


def test_answer_ids_stay_made_from_the_text_so_earlier_marks_match(tmp_path):
    """Marks saved by 1.1.x and 1.2.0 name answers by an id made from their text; the fix
    fills a label's text only, so those ids do not change."""
    path = write(tmp_path / "r.jsonl", mst_lines(3))
    pool = start.build_pool([(path.name, read_records(path))], DEFAULT_NAME, Normaliser())
    llm = [x for x in mst_lines(3) if x["annotator_kind"] == "LLM"]
    assert sorted(a.id for a in pool.answers) == sorted(
        derive_record_id(x["input"], x["output"]) for x in llm)
    assert {key for key, _, _ in pool.humans} == {a.id for a in pool.answers}


# Records format v2 is a public interface ------------------------------------------------------

def _newest_changelog_section() -> str:
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    return re.split(r"^## ", text, flags=re.MULTILINE)[1]


def test_the_records_schema_changes_only_with_a_changelog_line():
    got = hashlib.sha256(SCHEMA.read_bytes()).hexdigest()
    if got != SCHEMA_SHA256:
        assert "records format" in _newest_changelog_section().lower(), (
            "records.schema.json changed. Records format v2 is a public interface: say what "
            "changed in the newest CHANGELOG section (with the words \"records format\"; a "
            "change that makes a v2 file read differently also bumps schema_version), then set "
            f"SCHEMA_SHA256 in this test to {got}.")


def _marked_answer_columns(root: Path, monkeypatch, capsys) -> list[str]:
    from judgekeeper.start_label import Workspace
    from tests.test_only_reads import closed, mark_all, only_reads

    with only_reads(monkeypatch):
        assert main(["--no-browser"]) == 0
    ws = Workspace(root)
    mark_all(ws)
    with only_reads(monkeypatch):
        closed(ws)
    capsys.readouterr()
    assert main(["fix"]) == 0
    with (ws.dir / "fix" / "marked-answers.csv").open(encoding="utf-8", newline="") as f:
        return next(csv.reader(f))


def test_fix_hands_back_question_and_answer_for_a_records_file(here, capsys, monkeypatch):
    records_project(here, split(20, 20))
    assert _marked_answer_columns(here, monkeypatch, capsys) == ["question", "answer"]


def test_fix_hands_back_question_and_answer_for_promptfoo(here, capsys, monkeypatch):
    from tests.test_only_reads import FIRST, judge, write_results

    (here / "promptfooconfig.yaml").write_text(
        "description: support bot\nprompts:\n  - 'Answer: {{question}}'\n", encoding="utf-8")
    write_results("promptfoo", here / FIRST["promptfoo"], {i: judge(i) for i in range(40)})
    assert _marked_answer_columns(here, monkeypatch, capsys) == ["question", "answer"]
