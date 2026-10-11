"""The project's own promptfoo on Windows.

npm puts two files in `node_modules/.bin`: `promptfoo`, a shell script, and `promptfoo.cmd`.
Windows can start only the `.cmd` (the plain file gives WinError 193), so asking a promptfoo
judge again and `promptfoo export` start the `.cmd` there, with its full path first in the
argument list. Windows is faked with sys.platform; no promptfoo runs.
"""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from judgekeeper import again, start_export
from judgekeeper.again import promptfoo as pf
from tests.start_projects import project_promptfoo


@pytest.fixture
def windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")


@pytest.fixture
def started(monkeypatch):
    """Every program judgekeeper starts (argv), each answering `--version` with 0.123.1."""
    calls = []

    def run_process(argv, cwd, env=None, timeout=None):
        calls.append(list(argv))
        return SimpleNamespace(returncode=0, stdout="0.123.1\n", stderr="")

    monkeypatch.setattr(again, "run_process", run_process)
    monkeypatch.setattr(again, "which", lambda name: None)
    return calls


def test_on_windows_the_cmd_is_started(tmp_path, windows):
    project_promptfoo(tmp_path)
    assert again.node_bin(tmp_path, "promptfoo") == str(
        tmp_path / "node_modules" / ".bin" / "promptfoo.cmd")


def test_on_windows_an_exe_is_started_when_there_is_no_cmd(tmp_path, windows):
    folder = tmp_path / "node_modules" / ".bin"
    folder.mkdir(parents=True)
    for name in ("promptfoo", "promptfoo.exe"):
        (folder / name).write_text("", encoding="utf-8")
    assert again.node_bin(tmp_path, "promptfoo") == str(folder / "promptfoo.exe")


def test_on_windows_the_shell_script_alone_is_never_started(tmp_path, windows):
    folder = tmp_path / "node_modules" / ".bin"
    folder.mkdir(parents=True)
    (folder / "promptfoo").write_text("", encoding="utf-8")
    assert again.node_bin(tmp_path, "promptfoo") is None


def test_elsewhere_the_plain_file_is_started(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    project_promptfoo(tmp_path)
    assert again.node_bin(tmp_path, "promptfoo") == str(
        tmp_path / "node_modules" / ".bin" / "promptfoo")
    assert again.node_bin(tmp_path / "elsewhere", "promptfoo") is None


def test_asking_again_starts_the_cmd_on_windows(tmp_path, windows, started):
    project_promptfoo(tmp_path)
    cmd = str(tmp_path / "node_modules" / ".bin" / "promptfoo.cmd")
    assert pf._installed(tmp_path) == (cmd, "0.123.1")
    assert started == [[cmd, "--version"]]


def test_promptfoo_export_starts_the_cmd_on_windows(tmp_path, windows, started):
    project_promptfoo(tmp_path)
    assert start_export._promptfoo(tmp_path) == str(
        tmp_path / "node_modules" / ".bin" / "promptfoo.cmd")


def test_a_file_that_cannot_be_started_is_said_not_raised(tmp_path):
    # Not a program: WinError 193 on Windows, permission denied elsewhere (no execute bit)
    path = tmp_path / "promptfoo"
    path.write_text("not a program\n", encoding="utf-8")
    proc = again.run_process([str(path), "--version"], cwd=tmp_path, timeout=30)
    assert proc.returncode == 126
    assert proc.stderr
    assert again.run_process([str(tmp_path / "gone"), "--version"], cwd=tmp_path,
                             timeout=30).returncode == 127


def test_a_project_promptfoo_that_cannot_start_falls_back_to_the_path(tmp_path, monkeypatch):
    def run_process(argv, cwd, env=None, timeout=None):
        if argv[0] == "/usr/bin/promptfoo":
            return SimpleNamespace(returncode=0, stdout="0.120.0\n", stderr="")
        return SimpleNamespace(returncode=126, stdout="", stderr="[WinError 193]")

    monkeypatch.setattr(again, "run_process", run_process)
    monkeypatch.setattr(again, "which", lambda name: "/usr/bin/promptfoo")
    project_promptfoo(tmp_path)
    assert pf._installed(tmp_path) == ("/usr/bin/promptfoo", "0.120.0")


@pytest.mark.skipif(sys.platform != "win32", reason="starts a real .cmd: Windows only")
def test_a_real_cmd_in_a_folder_with_a_space_starts(tmp_path, monkeypatch):
    monkeypatch.setattr(again, "which", lambda name: None)
    root = tmp_path / "my project"
    folder = root / "node_modules" / ".bin"
    folder.mkdir(parents=True)
    (folder / "promptfoo").write_text("#!/bin/sh\necho 9.9.9\n", encoding="utf-8")
    (folder / "promptfoo.cmd").write_text("@echo off\r\necho 0.123.1\r\n", encoding="utf-8")
    assert pf._installed(root) == (str(folder / "promptfoo.cmd"), "0.123.1")
