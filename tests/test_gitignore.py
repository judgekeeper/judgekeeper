""".judgekeeper/.gitignore keeps everything out of Git except judge.json, history.jsonl and
itself. One the person wrote is never overwritten; the exact text 0.2 wrote is replaced."""

from __future__ import annotations

import shutil
import subprocess

import pytest

from judgekeeper import start, start_label
from tests.start_projects import promptfoo_project, split

OLD = ("# judgekeeper's files hold your app's answers. Commit them only if your data may live "
       "here.\n*\n!.gitignore\n!baseline.json\n!migrations/\n!migrations/*\n")


def _prepare(root):
    promptfoo_project(root, split(16, 16))
    return start_label.prepare(start.find_judge(root), say=lambda line: None)


def test_the_new_text(tmp_path):
    ws = _prepare(tmp_path)
    text = (ws.dir / ".gitignore").read_text(encoding="utf-8")
    assert text == start_label.GITIGNORE
    assert text.splitlines()[1:] == ["*", "!.gitignore", "!judge.json", "!history.jsonl"]


def test_the_exact_old_text_is_replaced(tmp_path):
    (tmp_path / ".judgekeeper").mkdir()
    (tmp_path / ".judgekeeper" / ".gitignore").write_text(OLD, encoding="utf-8")
    assert start_label.OLD_GITIGNORE == OLD
    ws = _prepare(tmp_path)
    assert (ws.dir / ".gitignore").read_text(encoding="utf-8") == start_label.GITIGNORE


def test_an_edited_one_is_left_alone(tmp_path):
    (tmp_path / ".judgekeeper").mkdir()
    edited = OLD + "!notes.md\n"
    (tmp_path / ".judgekeeper" / ".gitignore").write_text(edited, encoding="utf-8")
    ws = _prepare(tmp_path)
    assert (ws.dir / ".gitignore").read_text(encoding="utf-8") == edited


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
def test_git_keeps_only_the_judge_and_the_history(tmp_path):
    ws = _prepare(tmp_path)
    for name in ("judge.json", "history.jsonl"):
        (ws.dir / name).write_text("{}\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)

    def ignored(name):
        return subprocess.run(["git", "check-ignore", "-q", f".judgekeeper/{name}"],
                              cwd=tmp_path, check=False).returncode == 0

    assert not ignored("judge.json") and not ignored("history.jsonl")
    assert not ignored(".gitignore")
    for name in ("marks.jsonl", "pool.jsonl", "start.json", "server.json", "report.html",
                 "page.log"):
        assert ignored(name), name
