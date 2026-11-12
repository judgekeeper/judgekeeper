"""The marking page's footer says how to come back as a command run in the project folder,
with the program as typed: from the folder above (`mark p2`) too, as `mark` there."""
from __future__ import annotations

import os
import re
import signal
import urllib.request

import pytest

from judgekeeper import background, label, start
from judgekeeper.cli import main
from tests.start_projects import promptfoo_project, split, unwrapped
from tests.test_mark_background import alive


def _page(out: str) -> str:
    link = re.search(r"http://127\.0\.0\.1:\d+/\?token=[\w-]+", out)[0]
    with urllib.request.urlopen(link, timeout=10) as r:
        return unwrapped(r.read().decode("utf-8"))


@pytest.mark.parametrize(("start_in", "given", "said"), [
    ("parent", ["p2"], "judgekeeper mark --port 0 --no-browser"),
    ("project", [], "judgekeeper mark --port 0 --no-browser"),
])
def test_the_footer_is_the_command_in_the_project_folder(start_in, given, said, tmp_path,
                                                         monkeypatch, capsys):
    promptfoo_project(tmp_path / "p2", split(25, 25))
    monkeypatch.chdir(tmp_path if start_in == "parent" else tmp_path / "p2")
    code = main(["mark", *given, "--port", "0", "--no-browser"])
    out, err = capsys.readouterr()
    assert code == 0, out + err
    page = _page(out)
    assert f'<p class="foot">To come back: <code>{said}</code>' in page


def test_a_whole_path_typed_gives_the_project_folder_command(tmp_path, monkeypatch, capsys):
    promptfoo_project(tmp_path / "p2", split(25, 25))
    monkeypatch.chdir(tmp_path)
    assert main(["mark", str(tmp_path / "p2"), "--port", "0", "--no-browser"]) == 0
    page = _page(capsys.readouterr().out)
    assert '<code>judgekeeper mark --port 0 --no-browser</code>' in page
    assert str(tmp_path) not in page


@pytest.mark.parametrize("back", [None, "judgekeeper mark p2", {"path": "p2"},
                                  {"path": "p2\nrm -rf ~", "program": "judgekeeper"},
                                  {"path": "p2", "program": ""}, {"path": 2, "program": "x"}])
def test_junk_given_for_the_footer_leaves_the_project_folder_form(back):
    assert start.saved_back(back) is None
    assert start.come_back({"path": ".", "port": 0}, back) == "judgekeeper mark --port 0"


@pytest.mark.real_page
def test_the_page_process_says_the_same(tmp_path, monkeypatch, capsys):
    promptfoo_project(tmp_path / "p2", split(25, 25))
    monkeypatch.chdir(tmp_path)
    folder = tmp_path / "p2" / ".judgekeeper"
    try:
        assert main(["mark", "p2", "--port", "0", "--no-browser"]) == 0
        page = _page(capsys.readouterr().out)
    finally:
        lock = label.read_lock(folder)
        background.stop(folder)
        if lock and alive(lock["pid"]):  # never leave a page running after a failed test
            try:
                os.kill(lock["pid"], signal.SIGTERM)
            except (PermissionError, ProcessLookupError):  # it was closing already (Windows)
                pass
    assert '<code>judgekeeper mark --port 0 --no-browser</code>' in page
