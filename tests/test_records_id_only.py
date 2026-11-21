"""Records lines with a `target_id` and no `input`, `output` or `trajectory`: each id is its own
answer, found again by its id (the pool, labels by `target_id`, `--labels FILE`, marks kept,
and the same answer in new results). Lines with text are keyed by their text, as before.
No test calls an LLM.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from judgekeeper import labels, start
from judgekeeper.cli import main
from judgekeeper.normalise import Normaliser
from judgekeeper.records import read_records

PAGE = ("--no-browser", "--port", "0", "--yes")
CRITERION = "Safe wording"


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def flat(text: str) -> str:
    return " ".join(text.split())


def says(i: int) -> str:
    return "fail" if i % 4 == 0 else "pass"


def grade(target, label, **more) -> dict:
    return {"target_id": target, "name": CRITERION, "annotator_kind": "LLM", "label": label,
            **more}


def human(target, label) -> dict:
    return {"target_id": target, "name": CRITERION, "annotator_kind": "HUMAN", "label": label}


def grades(n: int = 40, label=says) -> list[dict]:
    return [grade(f"case-{i}", label(i)) for i in range(n)]


def write(path: Path, lines: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(x) + "\n" for x in lines), encoding="utf-8")
    return path


def run(capsys, *argv) -> tuple[int, str]:
    code = main([*argv, *PAGE])
    return code, flat("".join(capsys.readouterr()))


def pool_of(lines: list[dict], tmp: Path, name: str = "evals.jsonl") -> start.Pool:
    records = read_records(write(tmp / name, lines))
    return start.build_pool([(name, records)], CRITERION, Normaliser())


# Repro A and B --------------------------------------------------------------------------------

def test_labels_by_id_for_id_only_grades_are_added(here, capsys):
    write(here / "evals.jsonl", grades())
    write(here / "human.jsonl", [human(f"case-{i}", says(i)) for i in range(40)])
    _, out = run(capsys, ".", "--labels", "human.jsonl")
    assert "Added 40 marks from human.jsonl (30 Pass, 10 Fail)" in out, out
    assert "Nothing added" not in out and "both Pass and Fail" not in out, out
    assert "Answers: 40 answers" in out, out
    assert "1 answer" not in out, out


def test_labels_by_id_reach_a_result(here, capsys):
    def label(i):
        return "fail" if i % 8 < 3 else "pass"  # 15 Fail, 25 Pass

    write(here / "evals.jsonl", grades(label=label))
    write(here / "human.jsonl", [human(f"case-{i}", label(i)) for i in range(40)])
    code, out = run(capsys, ".", "--labels", "human.jsonl")
    assert "Added 40 marks from human.jsonl (25 Pass, 15 Fail)" in out, out
    assert "A result needs at least" not in out, out
    assert code in (0, 3), out


def test_forty_id_only_grades_are_forty_answers(here, capsys):
    write(here / "evals.jsonl", grades(label=lambda i: "pass"))
    _, out = run(capsys, ".")
    assert "Answers: 40" in out, out
    assert "1 answer" not in out, out


# The pool -------------------------------------------------------------------------------------

def test_each_id_is_one_answer_keyed_by_its_id(tmp_path):
    pool = pool_of(grades(5), tmp_path)
    assert sorted(a.id for a in pool.answers) == [f"case-{i}" for i in range(5)]
    assert not pool.split


def test_a_file_with_text_and_id_only_lines(tmp_path):
    lines = [grade("a", "pass", input="Q1?", output="A1."),
             grade("b", "fail", input="Q2?", output="A2."),
             grade("x", "pass"), grade("y", "fail"), grade("z", "pass")]
    pool = pool_of(lines, tmp_path)
    ids = {a.id for a in pool.answers}
    assert len(ids) == 5
    assert {"x", "y", "z"} <= ids
    assert len(ids - {"x", "y", "z"}) == 2  # the two with text: keyed by their text
    assert pool.by_target["x"] == {"x"}


def test_a_line_with_no_id_and_no_text_is_not_keyed_by_a_made_up_id(tmp_path):
    pool = pool_of([grade("x", "pass"), {k: v for k, v in grade("w", "pass").items()
                                         if k != "target_id"}], tmp_path)
    assert "x" in {a.id for a in pool.answers}


def test_repeats_of_an_id_with_the_same_grade_count_once(tmp_path):
    pool = pool_of([grade("x", "pass"), grade("x", "pass"), grade("y", "fail")], tmp_path)
    assert sorted(a.id for a in pool.answers) == ["x", "y"]
    assert pool.n_repeats == 1 and not pool.split


def test_repeats_of_an_id_with_different_grades_split(tmp_path):
    pool = pool_of([grade("x", "pass"), grade("x", "fail"), grade("y", "fail")], tmp_path)
    assert pool.split == {"x": (2, 1, 1)}
    assert sorted(a.id for a in pool.answers) == ["x", "x#2", "y"]


def test_labels_join_id_only_grades_by_target_id(tmp_path):
    lines = [*grades(6), *[human(f"case-{i}", says(i)) for i in range(6)]]
    pool = pool_of(lines, tmp_path)
    assert sorted(k for k, _, _ in pool.humans) == [f"case-{i}" for i in range(6)]
    assert start.NO_TEXT_ID not in {k for k, _, _ in pool.humans}


def test_the_same_ids_in_new_results_are_the_same_answers(tmp_path):
    old = pool_of(grades(6), tmp_path, "old.jsonl")
    new = pool_of(list(reversed(grades(6, label=lambda i: "pass"))), tmp_path, "new.jsonl")
    assert {a.id for a in old.answers} == {a.id for a in new.answers}


def test_a_labels_file_reads_by_id(tmp_path):
    pool = pool_of(grades(6), tmp_path)
    file = write(tmp_path / "human.jsonl", [human(f"case-{i}", says(i)) for i in range(6)])
    found = labels.read_records_file(file, pool, CRITERION)
    assert sorted(x.key for x in found) == [f"case-{i}" for i in range(6)]


def test_a_mixed_file_names_its_id_only_answers_by_id(tmp_path):
    lines = [grade("a", "pass", input="Q1?", output="A1."), grade("x", "pass"),
             grade("y", "fail"), {k: v for k, v in grade("q", "pass", input="Q9?").items()
                                  if k != "target_id"}]
    pool = pool_of(lines, tmp_path)
    by_id = {a.id: a for a in pool.answers}
    assert by_id["x"].case == "x" and by_id["y"].case == "y"
    assert len(pool.answers) == 4


# Found again in new results ---------------------------------------------------------------------

def test_marks_on_id_only_answers_are_found_again_in_new_results(here, capsys):
    def label(i):
        return "fail" if i % 8 < 3 else "pass"

    write(here / "evals.jsonl", grades(label=label))
    write(here / "human.jsonl", [human(f"case-{i}", label(i)) for i in range(40)])
    run(capsys, ".", "--labels", "human.jsonl")
    marked = [json.loads(x).get("id") for x in
              (here / ".judgekeeper" / "marks.jsonl").read_text(encoding="utf-8").splitlines()]
    assert "case-7" in marked
    write(here / "evals.jsonl", grades(label=lambda i: "fail" if label(i) == "fail" or
                                       10 < i < 16 else "pass"))
    _, out = run(capsys, ".")
    assert "Your answers were graded again" in out, out
    assert "On the 40 questions in both results: fixed 0, broke 5, same 35." in out, out


# Shown ------------------------------------------------------------------------------------------

def prepared(root: Path):
    from judgekeeper import start_label

    found = start.find_judge(root)
    return start_label.prepare(found, say=lambda line: None)


def test_an_id_only_answer_shows_its_id_where_its_text_would_be(here):
    from judgekeeper.start_label import StartSession

    write(here / "evals.jsonl", grades())
    items = StartSession(prepared(here)).state()["items"]
    assert items
    assert all(i["output"] == f"id: {i['id']}" for i in items)


def test_an_answer_with_text_is_shown_as_it_is(here):
    from judgekeeper.start_label import StartSession

    write(here / "evals.jsonl", [grade(f"c{i}", says(i), input=f"Q{i}?", output=f"Answer {i}.")
                                 for i in range(40)])
    items = StartSession(prepared(here)).state()["items"]
    assert items and all(i["output"].startswith("Answer ") for i in items)


def test_the_result_page_lists_a_failed_id_only_answer_by_its_id(here, capsys):
    def label(i):
        return "fail" if i % 8 < 3 else "pass"

    write(here / "evals.jsonl", grades(80, label=label))
    # the person fails 20 answers the LLM-as-a-judge passed
    write(here / "human.jsonl", [human(f"case-{i}", "fail" if i % 8 in (3, 4) or
                                       label(i) == "fail" else "pass") for i in range(80)])
    run(capsys, ".", "--labels", "human.jsonl")
    page = (here / ".judgekeeper" / "report.html").read_text(encoding="utf-8")
    assert len(re.findall(r"id: case-\d+", page)) == 10, page[:200]
