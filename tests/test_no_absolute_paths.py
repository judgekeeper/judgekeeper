"""No file judgekeeper writes in .judgekeeper/ holds an absolute path: the folder may be
committed, and a path from the root names the user's own folders. Paths are kept relative to
the project folder (`..` allowed); files an older judgekeeper wrote with absolute paths
still read."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from judgekeeper import background, check, start
from judgekeeper.cli import main
from tests.start_projects import promptfoo_project, split
from tests.test_check import _marked, _results

PAGE = ("--no-browser", "--port", "0", "--yes")


@pytest.fixture
def here(tmp_path, monkeypatch):
    project = tmp_path / "shop"
    project.mkdir()
    monkeypatch.chdir(project)
    yield project
    background.stop(project / ".judgekeeper")


def _whole_paths(folder: Path, *paths: Path) -> dict[str, list[str]]:
    """{file: [absolute paths in it]}, for every file under `folder`."""
    shown = {str(p) for p in paths} | {os.path.realpath(p) for p in paths}
    shown |= {s.replace("\\", "\\\\") for s in shown}  # as JSON writes a Windows path
    out = {}
    for f in sorted(folder.rglob("*")):
        if f.is_file():
            text = f.read_bytes().decode("utf-8", "replace")
            found = sorted(s for s in shown if s in text)
            if found:
                out[str(f.relative_to(folder))] = found
    return out


def test_the_whole_loop_writes_no_absolute_path(here, capsys, tmp_path):
    _marked(here)
    said = []

    def step(*argv):
        code = main(list(argv))
        said.append((argv, code, capsys.readouterr().out))
        return code

    step(*PAGE)  # Measure
    step("fix")
    (here / "new").mkdir()
    _results(here / "new", [True] * 25 + [False] * 25, version="0.125.0")
    step("check", "new/results.json")
    step("check")
    step("check", str(here / "new" / "results.json"))  # a whole path typed
    step(str(here), *PAGE)
    step("mark", *PAGE)
    folder = here / ".judgekeeper"
    for name in ("result.json", "history.jsonl", check.SEEN, "start.json", "page.lock"):
        assert (folder / name).is_file() or name == "page.lock", (name, said)
    assert _whole_paths(here / ".judgekeeper", here, tmp_path, Path.home()) == {}


def test_the_open_page_writes_no_absolute_path(here, capsys, tmp_path):
    promptfoo_project(here, split(20, 16))
    assert main([*PAGE]) == 0
    capsys.readouterr()
    assert (here / ".judgekeeper" / "server.json").is_file()  # the page's lock
    assert _whole_paths(here / ".judgekeeper", here, tmp_path, Path.home()) == {}


def test_results_seen_keeps_paths_from_the_project_folder(here, capsys):
    _marked(here)
    assert main(["check"]) == 0
    seen = json.loads((here / ".judgekeeper" / check.SEEN).read_text(encoding="utf-8"))
    assert seen["read"] == ["results.json"] and seen["newest"] == "results.json"
    assert "promptfooconfig.yaml" in seen["configs"] and "root" not in seen
    assert not any(os.path.isabs(p) for p in seen["configs"])


def test_an_older_results_seen_with_whole_paths_still_reads(here, capsys, monkeypatch):
    _marked(here)
    main(["check"])
    main(["check"])
    path = here / ".judgekeeper" / check.SEEN
    seen = json.loads(path.read_text(encoding="utf-8"))
    whole = {"read": [str(here / p) for p in seen["read"]], "newest": str(here / seen["newest"]),
             "configs": [str(here / p) for p in seen["configs"]], "root": str(here)}
    path.write_text(json.dumps({**seen, **whole}), encoding="utf-8")
    capsys.readouterr()

    def refuse(*args, **kwargs):
        raise AssertionError("the results were read")

    monkeypatch.setattr(start, "find_judge", refuse)
    assert main(["check"]) == 0
    assert "Your LLM-as-a-judge has not changed" in capsys.readouterr().out
