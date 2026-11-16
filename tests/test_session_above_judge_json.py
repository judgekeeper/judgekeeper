"""A first run that stops before marking leaves a .judgekeeper/ holding judge.json: a run in a
folder below it uses that session, as it uses one with marks, and starts no second one, so the
repository's top names that project. A .judgekeeper/ holding nothing judgekeeper wrote makes no
project. A second session made below by an older version is read as before."""

from __future__ import annotations

import json
import shutil

import pytest

from judgekeeper import find, project
from tests.start_projects import promptfoo_project, split, table_project
from tests.test_answers_without_grades import write_answers
from tests.test_services_in_one_repo import _run, repo, support_bot  # noqa: F401

SAVED_ABOVE = ("judgekeeper saved your LLM-as-a-judge's setup in ../.judgekeeper/judge.json.")
SAVED_HERE = "judgekeeper saved your LLM-as-a-judge's setup in .judgekeeper/judge.json."


def _pf_svc(repo, answers: int = 20):  # noqa: F811
    """services/pf-svc: promptfooconfig.yaml (no project file) and evals/out.json."""
    folder = repo / "services" / "pf-svc"
    promptfoo_project(folder, split(answers * 7 // 10, answers - answers * 7 // 10),
                      name="evals/out.json")
    return folder


def _stopped_in(capsys, monkeypatch, folder) -> None:
    """A first run there with too few answers: judge.json only."""
    code, said = _run(capsys, monkeypatch, folder)
    assert code == 3 and SAVED_HERE in said, said
    assert sorted(p.name for p in (folder / ".judgekeeper").iterdir()) == [".gitignore",
                                                                          "judge.json"]


def test_a_run_below_uses_the_judge_json_above(repo, capsys, monkeypatch):  # noqa: F811
    pf = _pf_svc(repo)
    _stopped_in(capsys, monkeypatch, pf)
    code, said = _run(capsys, monkeypatch, pf / "evals")
    assert code == 3 and SAVED_ABOVE in said, said
    assert not (pf / "evals" / ".judgekeeper").exists()


def test_the_repository_top_then_names_that_project(repo, capsys, monkeypatch):  # noqa: F811
    pf = _pf_svc(repo)
    _stopped_in(capsys, monkeypatch, pf)
    _run(capsys, monkeypatch, pf / "evals")
    support_bot(repo, graded=40)
    assert _run(capsys, monkeypatch, repo / "services" / "support-bot")[0] == 0
    code, said = _run(capsys, monkeypatch, repo)
    assert code == 3, said
    assert "services/pf-svc/ and services/support-bot/" in said, said



def test_the_project_then_reads_its_own_results_and_names_the_session_below(
        repo, capsys, monkeypatch):  # noqa: F811
    bot = support_bot(repo)
    for folder in (bot, bot / "src", bot / "evals"):
        _run(capsys, monkeypatch, folder)
    assert not (bot / "evals" / ".judgekeeper").exists()
    for argv in ((), (".",)):
        code, said = _run(capsys, monkeypatch, bot, *argv)
        assert code == 3 and "File: evals/results.csv" in said, said  # 20 answers: too few
        assert ("The project in src/ has results too: to check them, run `judgekeeper src --no-browser`."
                in said), said
        assert "already hold" not in said, said


def test_a_session_with_marks_above_is_used_as_before(repo, capsys, monkeypatch):  # noqa: F811
    pf = _pf_svc(repo, answers=40)
    assert _run(capsys, monkeypatch, pf)[0] == 0
    assert _run(capsys, monkeypatch, pf / "evals")[0] == 0
    assert not (pf / "evals" / ".judgekeeper").exists()


def test_a_project_file_between_keeps_its_own_session(repo, capsys, monkeypatch):  # noqa: F811
    pf = _pf_svc(repo)
    _stopped_in(capsys, monkeypatch, pf)
    (pf / "evals" / "pyproject.toml").write_text("[project]\nname = 'x'\n", encoding="utf-8")
    code, said = _run(capsys, monkeypatch, pf / "evals")
    assert code == 3 and SAVED_HERE in said, said
    assert (pf / "evals" / ".judgekeeper" / "judge.json").is_file()


def test_an_older_second_session_below_is_read_as_before(repo, capsys, monkeypatch):  # noqa: F811
    pf = _pf_svc(repo)
    _stopped_in(capsys, monkeypatch, pf)
    shutil.copytree(pf / ".judgekeeper", pf / "evals" / ".judgekeeper")  # made by 1.2.0
    code, said = _run(capsys, monkeypatch, pf / "evals")
    assert code == 3 and SAVED_HERE in said, said
    assert (pf / ".judgekeeper" / "judge.json").is_file()  # both left as they are
    assert (pf / "evals" / ".judgekeeper" / "judge.json").is_file()


def test_a_judge_json_of_another_tool_does_not_take_the_results_below(repo, capsys,  # noqa: F811
                                                                      monkeypatch):
    pf = _pf_svc(repo)
    _stopped_in(capsys, monkeypatch, pf)
    path = pf / ".judgekeeper" / "judge.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["setup"]["tool"] = "table"
    path.write_text(json.dumps(data), encoding="utf-8")
    code, said = _run(capsys, monkeypatch, pf / "evals")
    assert code == 3 and SAVED_HERE in said, said  # its own, as before
    assert (pf / "evals" / ".judgekeeper" / "judge.json").is_file()


@pytest.mark.parametrize("judge", ['{"setup": {}}', "not json", '{"setup": {"tool": 3}}'])
def test_a_judge_json_with_no_tool_read_is_passed_over_as_before(repo, capsys, monkeypatch,  # noqa: F811
                                                                 judge):
    pf = _pf_svc(repo)
    (pf / ".judgekeeper").mkdir()
    (pf / ".judgekeeper" / "judge.json").write_text(judge, encoding="utf-8")
    code, said = _run(capsys, monkeypatch, pf / "evals")
    assert code == 3 and SAVED_HERE in said, said
    assert (pf / "evals" / ".judgekeeper" / "judge.json").is_file()
    assert (pf / ".judgekeeper" / "judge.json").read_text(encoding="utf-8") == judge


def test_start_json_names_the_tool_before_judge_json(repo, capsys, monkeypatch):  # noqa: F811
    pf = _pf_svc(repo, answers=40)
    assert _run(capsys, monkeypatch, pf)[0] == 0  # start.json and judge.json
    path = pf / ".judgekeeper" / "judge.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["setup"]["tool"] = "table"
    path.write_text(json.dumps(data), encoding="utf-8")
    assert project.session_tool(pf) == "promptfoo"
    assert _run(capsys, monkeypatch, pf / "evals")[0] == 0
    assert not (pf / "evals" / ".judgekeeper").exists()


# What makes a folder a project of its own (find.is_project) ----------------------------------

@pytest.mark.parametrize(("inside", "is_one"), [
    ([], False),
    ([".gitignore"], False),
    ([".gitignore", "judge.json"], True),
    (["start.json"], True),
    (["records/run.jsonl"], True),  # judgekeeper.record()'s
])
def test_a_judgekeeper_folder_makes_a_project_when_it_holds_what_judgekeeper_wrote(
        tmp_path, inside, is_one):
    store = tmp_path / ".judgekeeper"
    store.mkdir()
    for name in inside:
        (store / name).parent.mkdir(parents=True, exist_ok=True)
        (store / name).write_text("{}", encoding="utf-8")
    assert find.is_project(tmp_path) is is_one


def test_an_empty_judgekeeper_folder_below_hides_no_results(repo, capsys, monkeypatch):  # noqa: F811
    folder = repo / "evals"
    table_project(folder, split(24, 16))
    (folder / ".judgekeeper").mkdir()
    (folder / ".judgekeeper" / ".gitignore").write_text("*\n", encoding="utf-8")
    code, said = _run(capsys, monkeypatch, repo)
    assert code == 0 and "File: evals/results.csv" in said, said


def test_results_of_another_tool_below_get_no_line_on_marks_above(repo, capsys,  # noqa: F811
                                                                  monkeypatch):
    pf = _pf_svc(repo, answers=40)
    (pf / ".judgekeeper").mkdir()
    (pf / ".judgekeeper" / "judge.json").write_text(
        json.dumps({"setup": {"tool": "table"}}), encoding="utf-8")
    code, said = _run(capsys, monkeypatch, pf / "evals")
    assert code == 0 and "get their own marks here" not in said, said
    assert (pf / "evals" / ".judgekeeper" / "start.json").is_file()


def test_answers_beside_a_judge_json_are_read_and_name_the_project_below(
        repo, capsys, monkeypatch):  # noqa: F811
    table_project(repo, split(8, 4), tag="p")
    _stopped_in(capsys, monkeypatch, repo)
    (repo / "results.csv").unlink()
    write_answers(repo, 40)  # answers with no grade now, beside the judge.json of the first run
    other = repo / "other-eval"
    other.mkdir()
    (other / "pyproject.toml").write_text("", encoding="utf-8")
    write_answers(other, 20, grades=(["pass"] * 4 + ["fail"]) * 4)
    code, said = _run(capsys, monkeypatch, repo)
    assert code == 0 and "File: results.csv" in said, said
    assert ("The project in other-eval/ has results too: to check them, run "
            "`judgekeeper other-eval --no-browser`.") in said, said
    assert not (other / ".judgekeeper").exists()
