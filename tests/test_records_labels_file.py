"""Labels kept in a records file of their own (a HUMAN line with only a `target_id`, as
`judgekeeper.record()` writes one file per process), and labels under another criterion name.

A records file with only HUMAN lines is still a records file: found in the project folder and
in `.judgekeeper/records/`, its labels join the grades of the other records files by
`target_id`. `--labels FILE` on a records JSONL reads it as records labels, not as a table.
HUMAN lines with no `name` label the one criterion the grades have; labels for another name
are said so. No test calls an LLM.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from judgekeeper import labels, start
from judgekeeper.cli import main
from judgekeeper.normalise import Normaliser
from judgekeeper.records import read_records

PAGE = ("--no-browser", "--port", "0", "--yes")
EXIT_QUESTION = 3
CRITERION = "Safe wording"


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def flat(text: str) -> str:
    return " ".join(text.split())


def says(i: int) -> str:
    return "fail" if i % 3 == 0 else "pass"


def grades(n: int = 40, name: str = CRITERION) -> list[dict]:
    return [{"schema_version": 2, "target_id": f"c{i}", "name": name, "annotator_kind": "LLM",
             "label": says(i), "input": f"Question {i}?", "output": f"Answer {i}.",
             "evaluator": {"model": "claude-sonnet-5-5"}} for i in range(n)]


def human(i: int, name: str | None = CRITERION, target: str | None = None) -> dict:
    line = {"schema_version": 2, "target_id": target or f"c{i}", "annotator_kind": "HUMAN",
            "label": says(i)}
    if name is not None:
        line["name"] = name
    return line


def write(path: Path, lines: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(x) + "\n" for x in lines), encoding="utf-8")
    return path


def run(capsys, *argv) -> tuple[int, str]:
    code = main([*argv, *PAGE])
    return code, flat("".join(capsys.readouterr()))


def split_project(root: Path, where: str = ".", labels_lines: list[dict] | None = None,
                  grade_lines: list[dict] | None = None) -> tuple[Path, Path]:
    """grades in one file, labels in another, both in the folder `where` of the project."""
    folder = root / where
    lines = labels_lines if labels_lines is not None else [human(i) for i in range(40)]
    return (write(folder / "evals.jsonl", grade_lines or grades()),
            write(folder / "evals-human.jsonl", lines))


LOCATIONS = [".", ".judgekeeper/records"]


# M2: the labels are in a file of their own ---------------------------------------------------

@pytest.mark.parametrize("where", LOCATIONS)
def test_labels_in_their_own_file_are_read_with_labels_alone(here, capsys, where):
    split_project(here, where)
    code, out = run(capsys, "--labels")
    assert "Added 40 marks from your results (26 Pass, 14 Fail)." in out, out
    assert "No Pass/Fail labels found" not in out
    assert code in (0, 3), out


@pytest.mark.parametrize("where", LOCATIONS)
def test_the_find_step_counts_the_file_of_labels_as_read(here, capsys, where):
    split_project(here, where)
    _, out = run(capsys)
    files = "evals.jsonl" if where == "." else ".judgekeeper/records/"
    assert f"Files: {files}, 2 files" in out, out
    assert "Found 40 labels in your results" in out, out


@pytest.mark.parametrize("where", LOCATIONS)
def test_labels_file_given_with_labels_is_read_as_records(here, capsys, where):
    _, labels_file = split_project(here, where)
    given = labels_file.relative_to(here).as_posix()
    code, out = run(capsys, "--labels", given)
    assert "needs an answer column" not in out, out
    assert "Added 40 marks from evals-human.jsonl (26 Pass, 14 Fail)." in out, out
    assert code in (0, 3), out


def test_a_labels_file_outside_the_project_is_read_as_records(here, capsys, tmp_path_factory):
    project = here / "project"
    split_project(project, labels_lines=[])
    elsewhere = write(tmp_path_factory.mktemp("elsewhere") / "labels.jsonl",
                      [human(i) for i in range(40)])
    code, out = run(capsys, str(project), "--labels", str(elsewhere))
    assert "Added 40 marks from labels.jsonl (26 Pass, 14 Fail)." in out, out
    assert code in (0, 3), out


@pytest.mark.parametrize("where", LOCATIONS)
def test_a_label_for_a_missing_target_is_skipped_and_said_plainly(here, capsys, where):
    lines = [human(i) for i in range(39)] + [human(0, target="nobody")]
    split_project(here, where, labels_lines=lines)
    _, out = run(capsys, "--labels")
    assert "Added 39 marks from your results" in out, out
    assert ("Skipped 1 label: 1 label is for an answer that is not in your results") in out, out
    assert "no LLM-as-a-judge grade" not in out


def test_a_label_for_a_missing_target_in_a_given_file_is_skipped_the_same_way(here, capsys):
    _, labels_file = split_project(here, labels_lines=[human(i) for i in range(39)]
                                   + [human(0, target="nobody")])
    _, out = run(capsys, "--labels", labels_file.name)
    assert "Added 39 marks from evals-human.jsonl" in out, out
    assert "Skipped 1 label: 1 label is for an answer that is not in your results" in out, out


def test_several_labels_for_missing_targets_are_said_in_the_plural(here, capsys):
    lines = [human(i) for i in range(38)] + [human(1, target="x"), human(2, target="y")]
    split_project(here, labels_lines=lines)
    _, out = run(capsys, "--labels")
    assert "Skipped 2 labels: 2 labels are for answers that are not in your results" in out, out


def test_the_pool_joins_a_label_file_to_the_grades_by_target_id(here):
    grade_path, label_path = split_project(here)
    files = [(p.name, read_records(p)) for p in (grade_path, label_path)]
    pool = start.build_pool(files, CRITERION, Normaliser())
    assert len(pool.answers) == 40
    assert {key for key, _, _ in pool.humans} == {a.id for a in pool.answers}


def test_a_target_with_two_different_answers_is_not_guessed(here):
    lines = grades(3) + [{**grades(1)[0], "output": "A second answer for c0."}]
    grade_path = write(here / "evals.jsonl", lines)
    label_path = write(here / "evals-human.jsonl", [human(0)])
    files = [(p.name, read_records(p)) for p in (grade_path, label_path)]
    pool = start.build_pool(files, CRITERION, Normaliser())
    found = labels.in_results(pool, CRITERION)
    plan = labels.match(found, {a.id: {"input": a.input, "output": a.output}
                                for a in pool.answers},
                        [{"id": a.id} for a in pool.answers], pool.left)
    assert plan.marks == {} and plan.skipped == {labels.NO_GRADE: 1}


# M3: the labels have no name, or another one -------------------------------------------------

@pytest.mark.parametrize("where", LOCATIONS)
def test_labels_with_no_name_label_the_one_criterion_graded(here, capsys, where):
    split_project(here, where, labels_lines=[human(i, name=None) for i in range(40)])
    code, out = run(capsys, "--labels")
    assert "Added 40 marks from your results (26 Pass, 14 Fail)." in out, out
    assert code in (0, 3), out


def test_labels_with_no_name_in_the_grades_file_itself_are_read(here, capsys):
    write(here / "evals.jsonl", grades() + [human(i, name=None) for i in range(40)])
    _, out = run(capsys, "--labels")
    assert "Added 40 marks from your results (26 Pass, 14 Fail)." in out, out


def test_labels_with_no_name_in_a_given_file_label_the_one_criterion(here, capsys):
    _, labels_file = split_project(here, labels_lines=[human(i, name=None)
                                                       for i in range(40)])
    _, out = run(capsys, "--labels", labels_file.name)
    assert "Added 40 marks from evals-human.jsonl (26 Pass, 14 Fail)." in out, out


NO_NAME = ('Your 40 labels have no name, and your LLM-as-a-judge grades "Safe wording" and '
           '"Tone", so judgekeeper can\'t tell which one they are for. Give each label line the '
           "name of the grade it labels.")


def test_labels_with_no_name_next_to_two_criteria_say_they_cannot_tell(here, capsys):
    both = grades() + grades(name="Tone")
    split_project(here, grade_lines=both, labels_lines=[human(i, name=None)
                                                         for i in range(40)])
    code, out = run(capsys, "--labels", "--metric", CRITERION)
    assert code == EXIT_QUESTION, out
    assert NO_NAME in out, out
    assert "Added" not in out and "No Pass/Fail labels found" not in out
    assert '"LLM-as-a-judge"' not in out.replace("your LLM-as-a-judge grades", "")


def test_labels_with_no_name_in_a_given_file_say_it_the_same_way(here, capsys):
    both = grades() + grades(name="Tone")
    _, labels_file = split_project(here, grade_lines=both,
                                   labels_lines=[human(i, name=None) for i in range(40)])
    code, out = run(capsys, "--labels", labels_file.name, "--metric", CRITERION)
    assert code == EXIT_QUESTION, out
    assert NO_NAME in out, out


def test_one_label_with_no_name_is_said_in_the_singular(here, capsys):
    both = grades() + grades(name="Tone")
    split_project(here, grade_lines=both, labels_lines=[human(1, name=None)])
    code, out = run(capsys, "--labels", "--metric", CRITERION)
    assert code == EXIT_QUESTION, out
    assert ('Your 1 label has no name, and your LLM-as-a-judge grades "Safe wording" and '
            '"Tone", so judgekeeper can\'t tell which one it is for. Give each label line the '
            "name of the grade it labels.") in out, out


def test_more_than_five_grade_names_are_cut_to_five_and_a_count(here, capsys):
    names = [f"Criterion {c}" for c in "ABCDEFG"]
    many = [line for n in names for line in grades(name=n)]
    split_project(here, grade_lines=many, labels_lines=[human(1, name=None)])
    code, out = run(capsys, "--labels", "--metric", "Criterion A")
    assert code == EXIT_QUESTION, out
    assert ('grades "Criterion A", "Criterion B", "Criterion C", "Criterion D", "Criterion E" '
            "and 2 more, so") in out, out


LINE = ('Your 40 labels are for "Tone", but your LLM-as-a-judge grades "Safe wording", so none '
        "of them were added.")


@pytest.mark.parametrize("where", LOCATIONS)
def test_labels_for_another_criterion_say_so(here, capsys, where):
    split_project(here, where, labels_lines=[human(i, name="Tone") for i in range(40)])
    code, out = run(capsys, "--labels")
    assert code == EXIT_QUESTION, out
    assert LINE in out, out
    assert "No Pass/Fail labels found" not in out


def test_labels_for_another_criterion_in_a_given_file_say_so(here, capsys):
    _, labels_file = split_project(here, labels_lines=[human(i, name="Tone")
                                                       for i in range(40)])
    code, out = run(capsys, "--labels", labels_file.name)
    assert code == EXIT_QUESTION, out
    assert LINE in out, out


def test_one_label_for_another_criterion_is_said_in_the_singular(here, capsys):
    split_project(here, labels_lines=[human(1, name="Tone")])
    code, out = run(capsys, "--labels")
    assert code == EXIT_QUESTION, out
    assert ('Your 1 label is for "Tone", but your LLM-as-a-judge grades "Safe wording", so it '
            "was not added.") in out, out


def test_labels_with_no_labels_anywhere_still_say_none_found(here, capsys):
    write(here / "evals.jsonl", grades())
    code, out = run(capsys, "--labels")
    assert code == EXIT_QUESTION, out
    assert "No Pass/Fail labels found in your results." in out, out
