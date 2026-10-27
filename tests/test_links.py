"""A cloned project controls `.judgekeeper/`: a link there must never make judgekeeper write
to a file outside the project. And the folder keeps the answers off Git with its own
.gitignore."""

from __future__ import annotations

import os
import shutil
import subprocess

import pytest

from judgekeeper import start, start_label
from judgekeeper.cli import main
from judgekeeper.project import move_to_previous
from judgekeeper.start_label import GITIGNORE, Workspace
from judgekeeper.textio import link_in, write_replacing
from tests.start_projects import promptfoo_project, records_project, split

VICTIM = "a file outside the project\n"


def _quiet(line=""):
    pass


def _link(link, target, folder=False):
    try:
        link.symlink_to(target, target_is_directory=folder)
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links not allowed here")


def _victim(tmp_path):
    victim = tmp_path / "outside" / "victim.txt"
    victim.parent.mkdir()
    victim.write_text(VICTIM, encoding="utf-8")
    return victim


def _run(capsys, *argv):
    code = main([*map(str, argv), "--yes", "--no-browser"])
    out, err = capsys.readouterr()
    return code, out, err


@pytest.mark.parametrize("name", ["pool.jsonl", "result.html", "start.json"])
def test_a_link_in_the_folder_stops_it_and_changes_nothing(
        tmp_path, capsys, pages, name):
    project = tmp_path / "project"
    promptfoo_project(project, split(20, 16))
    victim = _victim(tmp_path)
    (project / ".judgekeeper").mkdir()
    _link(project / ".judgekeeper" / name, victim)
    code, _, err = _run(capsys, project)
    assert code == 2 and pages[0] == []
    assert (f".judgekeeper/{name} is a link to another file. judgekeeper does not write "
            "through links. Remove it, then run judgekeeper again.") in err
    assert victim.read_text(encoding="utf-8") == VICTIM
    assert sorted(p.name for p in (project / ".judgekeeper").iterdir()) == [name]


def test_judgekeeper_itself_as_a_link_stops_it(tmp_path, capsys, pages):
    project = tmp_path / "project"
    promptfoo_project(project, split(20, 16))
    outside = tmp_path / "outside"
    outside.mkdir()
    _link(project / ".judgekeeper", outside, folder=True)
    code, _, err = _run(capsys, project)
    assert code == 2 and pages[0] == []
    assert ".judgekeeper is a link to another folder. judgekeeper does not write" in err
    assert list(outside.iterdir()) == []


def test_writing_replaces_a_link_and_leaves_its_target(tmp_path):
    victim = _victim(tmp_path)
    path = tmp_path / "pool.jsonl"
    _link(path, victim)
    write_replacing(path, "new\n")
    assert not path.is_symlink() and path.read_text(encoding="utf-8") == "new\n"
    assert victim.read_text(encoding="utf-8") == VICTIM
    assert sorted(p.name for p in tmp_path.iterdir()) == ["outside", "pool.jsonl"]


def test_link_in_finds_none_in_a_plain_folder(tmp_path):
    (tmp_path / "a" / "b").mkdir(parents=True)
    (tmp_path / "a" / "b" / "c.txt").write_text("x", encoding="utf-8")
    assert link_in(tmp_path) is None
    assert link_in(tmp_path / "missing") is None


# The folder's own .gitignore ---------------------------------------------------------------

def test_the_first_check_writes_the_folders_gitignore(tmp_path):
    promptfoo_project(tmp_path, split(20, 16))
    ws = start_label.prepare(start.find_judge(tmp_path), say=_quiet)
    assert (ws.dir / ".gitignore").read_text(encoding="utf-8") == GITIGNORE
    assert GITIGNORE.startswith("# judgekeeper's files hold your answers. Commit them "
                                "only if your data may live here.\n*\n!.gitignore\n"
                                "!judge.json\n!history.jsonl\n")


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
def test_git_keeps_the_answers_out_and_the_judge_in(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    promptfoo_project(tmp_path, split(20, 16))
    ws = start_label.prepare(start.find_judge(tmp_path), say=_quiet)
    (ws.dir / "judge.json").write_text("{}", encoding="utf-8")

    def ignored(rel):
        return subprocess.run(["git", "-C", str(tmp_path), "check-ignore", "-q", rel],
                              check=False).returncode == 0

    assert ignored(".judgekeeper/pool.jsonl") and ignored(".judgekeeper/start.json")
    assert ignored(".judgekeeper/records/x.jsonl") and ignored(".judgekeeper/marks.jsonl")
    assert not ignored(".judgekeeper/.gitignore")
    assert not ignored(".judgekeeper/judge.json")


def test_an_existing_gitignore_is_never_changed(tmp_path):
    promptfoo_project(tmp_path, split(20, 16))
    (tmp_path / ".judgekeeper").mkdir()
    (tmp_path / ".judgekeeper" / ".gitignore").write_text("mine\n", encoding="utf-8")
    ws = start_label.prepare(start.find_judge(tmp_path), say=_quiet)
    assert (ws.dir / ".gitignore").read_text(encoding="utf-8") == "mine\n"


def test_a_folder_record_made_gets_its_gitignore_at_the_first_check(tmp_path):
    records_project(tmp_path, split(20, 16))
    ws = start_label.prepare(start.find_judge(tmp_path), say=_quiet)
    assert (ws.dir / ".gitignore").read_text(encoding="utf-8") == GITIGNORE


def test_a_check_already_there_gets_no_gitignore(tmp_path):
    promptfoo_project(tmp_path, split(20, 16))
    ws = start_label.prepare(start.find_judge(tmp_path), say=_quiet)
    (ws.dir / ".gitignore").unlink()  # the user removed it
    start_label.prepare(start.find_judge(tmp_path), say=_quiet)
    assert not os.path.lexists(ws.dir / ".gitignore")


def test_new_leaves_the_gitignore_in_place(tmp_path):
    promptfoo_project(tmp_path, split(20, 16))
    ws = start_label.prepare(start.find_judge(tmp_path), say=_quiet)
    target = move_to_previous(Workspace(tmp_path), _quiet)
    assert (ws.dir / ".gitignore").read_text(encoding="utf-8") == GITIGNORE
    assert not (target / ".gitignore").exists() and (target / "start.json").is_file()


def test_a_hard_linked_page_log_is_said_as_the_symlink_case_is(tmp_path, capsys, pages):
    project = tmp_path / "project"
    promptfoo_project(project, split(20, 16))
    victim = _victim(tmp_path)
    (project / ".judgekeeper").mkdir()
    try:
        os.link(victim, project / ".judgekeeper" / "page.log")
    except (OSError, NotImplementedError):
        pytest.skip("hard links not allowed here")
    code, out, err = _run(capsys, project)
    assert code == 2 and pages[0] == []
    assert (".judgekeeper/page.log is linked to another file. judgekeeper does not write "
            "through links. Remove it, then run judgekeeper again.") in err
    assert "what went wrong is in" not in out + err
    assert victim.read_text(encoding="utf-8") == VICTIM


# Every command refuses a linked .judgekeeper/, before it does any work ---------------------------

def _snapshot(folder):
    return {p.relative_to(folder).as_posix(): p.read_bytes() if p.is_file() else None
            for p in sorted(folder.rglob("*"))}


@pytest.mark.parametrize("command", [[], ["mark"], ["check"], ["fix"], ["fix", "--new"]],
                         ids=lambda c: " ".join(c) or "judgekeeper")
def test_every_command_refuses_a_linked_judgekeeper_folder(tmp_path, monkeypatch, capsys,
                                                           pages, command):
    from tests import test_fix

    victim = tmp_path / "victim"  # another project, marked enough to fix its judge
    victim.mkdir()
    monkeypatch.chdir(victim)
    test_fix.project(victim)
    capsys.readouterr()
    project = tmp_path / "s1"
    project.mkdir()
    for name in ("results.json", "promptfooconfig.yaml"):
        shutil.copy(victim / name, project / name)
    _link(project / ".judgekeeper", victim / ".judgekeeper", folder=True)
    before = _snapshot(victim / ".judgekeeper")
    monkeypatch.chdir(project)
    code = main(command if command[:1] != ["mark"] else [*command, "--no-browser"])
    out, err = capsys.readouterr()
    assert code == 2, out + err
    assert ("error: .judgekeeper is a link to another folder. judgekeeper does not write "
            "through links. Remove it, then run judgekeeper again.") in err
    assert "Next:" not in out  # the command never started
    assert _snapshot(victim / ".judgekeeper") == before


def test_the_marks_writer_refuses_a_link_above_the_files_folder(tmp_path):
    from judgekeeper import marks

    folder = tmp_path / ".judgekeeper"
    folder.mkdir()
    outside = tmp_path / "outside"
    (outside / "x").mkdir(parents=True)
    _link(folder / "fix", outside, folder=True)
    with pytest.raises(marks.MarksError, match="is a link to another folder"):
        marks.append(folder / "fix" / "x" / "y.jsonl", {"a": 1})
    with pytest.raises(marks.MarksError, match="is a link to another folder"):
        marks.begin(folder / "fix" / "x" / "y.jsonl", {"a": 1})
    assert list((outside / "x").iterdir()) == []


@pytest.mark.parametrize("name", ["mistakes.md", "marked-answers.csv", "split.json"])
def test_a_hard_link_at_a_fix_file_is_refused_as_a_symlink_is(tmp_path, monkeypatch, capsys,
                                                               name):
    from tests import test_fix

    monkeypatch.chdir(tmp_path)
    ws = test_fix.project(tmp_path)
    assert main(["fix"]) == 0
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    try:
        os.link(ws.dir / "fix" / name, outside)
    except (OSError, NotImplementedError):
        pytest.skip("hard links not allowed here")
    before = outside.read_bytes()
    capsys.readouterr()
    code = main(["fix"])
    out, err = capsys.readouterr()
    assert code == 2, out + err
    assert (f"{name} is linked to another file. judgekeeper does not write through links."
            in " ".join(err.split()))
    assert outside.read_bytes() == before
