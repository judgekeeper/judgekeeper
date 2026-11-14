"""A file inside a project of its own below (a project file or its own .judgekeeper/) is never
the one a run reads in its place. A project whose session is on its own answers keeps reading
them when a project below holds newer results, and names that project. A plain run in a folder
that is no project counts only the files in no project below: its list of tools offers no tool
whose files are all in projects below, and with none left it names them and stops."""

from __future__ import annotations

import csv
import json
import os
import time

import pytest

from judgekeeper.start_label import StartSession, Workspace
from tests.start_projects import deepeval_project, inspect_project, promptfoo_project, split
from tests.test_answers_without_grades import _rows, write_answers
from tests.test_services_in_one_repo import _run, repo  # noqa: F401

OTHER_EVAL_TOO = ("The project in other-eval/ has results too: to check them, run "
                  "`judgekeeper other-eval --no-browser`.")
BELONG = "These results belong to the project in other-eval/."


def _newest(path) -> None:
    later = time.time() + 60
    os.utime(path, (later, later))


@pytest.fixture
def own(repo, capsys, monkeypatch):  # noqa: F811
    """A project with its own answers (no grade, 40), all marked, with a result."""
    write_answers(repo, 40)
    assert _run(capsys, monkeypatch, repo)[0] == 0
    session = StartSession(Workspace(repo))
    for k, item in enumerate(session.items):
        session.update({"id": item["id"], "label": "fail" if k % 5 == 0 else "pass",
                        "seconds": 5})
    assert _run(capsys, monkeypatch, repo)[0] == 0
    return repo


@pytest.fixture
def marked(own, capsys, monkeypatch):
    """`own`, with other-eval/ below it holding graded results and its own .judgekeeper/ from
    a run there; other-eval's file is the newest."""
    other = own / "other-eval"
    other.mkdir()
    write_answers(other, 20, grades=(["pass"] * 4 + ["fail"]) * 4)
    code, said = _run(capsys, monkeypatch, other)
    assert code == 3 and (other / ".judgekeeper" / "judge.json").is_file(), said
    _newest(other / "results.csv")
    return own


@pytest.mark.parametrize("argv", [(), (".",)])
def test_a_project_keeps_reading_its_own_answers_and_names_the_project_below(
        marked, capsys, monkeypatch, argv):
    code, said = _run(capsys, monkeypatch, marked, *argv)
    assert code == 0 and BELONG not in said, said
    assert "Full report: .judgekeeper/report.html" in said, said
    assert OTHER_EVAL_TOO in said, said
    assert not (marked / "other-eval" / ".judgekeeper" / "start.json").exists()


def test_its_own_answers_newest_are_read_as_before(marked, capsys, monkeypatch):
    _newest(marked / "results.csv")
    os.utime(marked / "other-eval" / "results.csv", (time.time(), time.time()))
    code, said = _run(capsys, monkeypatch, marked)
    assert code == 0 and BELONG not in said, said
    assert "Full report: .judgekeeper/report.html" in said, said


def test_its_own_answers_named_are_read_as_before(marked, capsys, monkeypatch):
    code, said = _run(capsys, monkeypatch, marked, "results.csv")
    assert code == 0 and BELONG not in said, said
    assert "Full report: .judgekeeper/report.html" in said, said


def test_answers_with_no_session_are_read_and_name_the_project_below(repo, capsys,  # noqa: F811
                                                                     monkeypatch):
    write_answers(repo, 40)
    other = repo / "other-eval"
    other.mkdir()
    write_answers(other, 20, grades=(["pass"] * 4 + ["fail"]) * 4)
    assert _run(capsys, monkeypatch, other)[0] == 3
    code, said = _run(capsys, monkeypatch, repo)
    assert code == 0 and BELONG not in said, said  # answers with no grade: the folder's own
    assert "File: results.csv" in said and OTHER_EVAL_TOO in said, said
    assert not (other / ".judgekeeper" / "start.json").exists()


# The plain run in a folder that is no project ------------------------------------------------

ONE_AT_A_TIME = ("de-bot/, insp-bot/ and pf-bot/ hold eval results: judgekeeper keeps a "
                 "project's marks in its own folder, so it checks one at a time.")
THREE_TOO = ("The projects in de-bot/, insp-bot/ and pf-bot/ have results too: to check them, "
             "run `judgekeeper de-bot --no-browser`, `judgekeeper insp-bot --no-browser` or "
             "`judgekeeper pf-bot --no-browser`.")


@pytest.fixture
def services(repo, capsys, monkeypatch):  # noqa: F811
    """services/: pf-bot/ (promptfoo), de-bot/ (DeepEval) and insp-bot/ (Inspect AI), each
    with its own .judgekeeper/, and loose/results.csv in no project."""
    top = repo / "services"
    promptfoo_project(top / "pf-bot", split(14, 6))
    deepeval_project(top / "de-bot", split(11, 5), tag="de")
    inspect_project(top / "insp-bot", split(8, 4), tag="insp")
    for name in ("pf-bot", "de-bot", "insp-bot"):
        code, said = _run(capsys, monkeypatch, top / name)
        assert code == 3 and (top / name / ".judgekeeper" / "judge.json").is_file(), said
    (top / "loose").mkdir()
    write_answers(top / "loose", 15, grades=(["pass"] * 4 + ["fail"]) * 3)
    return top


def test_the_plain_run_reads_the_only_tool_left_and_names_the_projects(services, capsys,
                                                                        monkeypatch):
    code, said = _run(capsys, monkeypatch, services)
    assert code == 3, said  # 15 answers: too few
    assert "Saved results from more than one eval tool" not in said, said
    assert "File: loose/results.csv" in said and "Answers: 15 answers" in said, said
    assert THREE_TOO in said, said


def test_with_no_file_left_the_plain_run_names_the_projects_and_stops(services, capsys,
                                                                      monkeypatch):
    (services / "loose" / "results.csv").unlink()
    code, said = _run(capsys, monkeypatch, services)
    assert code == 3, said
    assert ONE_AT_A_TIME in said and "Saved results" not in said, said
    assert not (services / ".judgekeeper").exists()


def test_two_folders_left_stop_as_with_no_project_below_and_name_the_projects(
        services, capsys, monkeypatch):  # the projects' DeepEval and Inspect AI results never
    # decide how this folder is read: only that they are named
    promptfoo_project(services / "pf-loose", split(10, 5), name="evals/out.json")  # no project
    code, said = _run(capsys, monkeypatch, services)
    assert code == 3, said
    assert "de-bot/, insp-bot/, loose/, pf-bot/ and pf-loose/ hold eval results" in said, said
    assert "Saved results" not in said, said
    assert not (services / ".judgekeeper").exists()


# Another eval beside the answers marked with no grade ---------------------------------------

ANOTHER = ("zzz-other.jsonl shares few questions with the results you marked (results.csv), so "
           "it looks like another eval.")
FOUND_3 = "Found 3 new answers since your last results."


def _unrelated(folder) -> None:
    """zzz-other.jsonl: 6 answers with no grade, no question shared, the newest file."""
    path = folder / "zzz-other.jsonl"
    path.write_text("".join(json.dumps({"input": f"Name a colour of the rainbow, #{i}.",
                                        "output": f"Red, {i}."}) + "\n" for i in range(6)),
                    encoding="utf-8")
    _newest(path)


def _round(folder, name: str = "results") -> None:
    """The same 40 questions, 3 of them with a new answer, in `name`.csv: the newest file."""
    rows = _rows(40)
    for row in rows[:3]:
        row["output"] += " Asked again."
    with (folder / f"{name}.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["input", "output"])
        w.writeheader()
        w.writerows(rows)
    _newest(folder / f"{name}.csv")


def test_another_eval_beside_the_answers_marked_is_not_read(own, capsys, monkeypatch):
    _unrelated(own)
    code, said = _run(capsys, monkeypatch, own)
    assert code == 0 and "new answers" not in said, said
    assert ANOTHER in said and "Full report: .judgekeeper/report.html" in said, said
    assert len(StartSession(Workspace(own)).raw) == 40


def test_another_eval_named_says_so_and_stops(own, capsys, monkeypatch):
    _unrelated(own)
    code, said = _run(capsys, monkeypatch, own, "zzz-other.jsonl")
    assert code == 3 and ANOTHER in said, said
    assert len(StartSession(Workspace(own)).raw) == 40


@pytest.mark.parametrize("name", ["results", "round-2"])
def test_a_new_round_of_the_same_questions_is_new_answers(own, capsys, monkeypatch, name):
    _round(own, name)
    said = _run(capsys, monkeypatch, own)[1]
    assert FOUND_3 in said and "another eval" not in said, said


def test_after_a_newer_round_another_eval_names_the_file_now_marked(own, capsys, monkeypatch):
    _round(own, "results-3")
    assert FOUND_3 in _run(capsys, monkeypatch, own)[1]
    _unrelated(own)
    code, said = _run(capsys, monkeypatch, own)
    assert code == 0, said
    assert ("zzz-other.jsonl shares few questions with the results you marked (results-3.csv), "
            "so it looks like another eval.") in said, said
