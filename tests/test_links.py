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
from judgekeeper.start_again import move_to_previous
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
