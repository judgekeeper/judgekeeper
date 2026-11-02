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


def test_files_given_in_full_from_outside_the_project_are_kept_from_it(here, capsys,
                                                                        tmp_path,
                                                                        tmp_path_factory):
    """Results, labels and fix/check files given by whole path from another folder (on
    another temp root): every path kept under .judgekeeper/ is from the project folder."""
    import shutil

    from tests.test_labels_import import write_labels
    from tests.test_regrade_files import breaking, project
    from tests.test_regrade_files import write as write_rows

    other = tmp_path_factory.mktemp("elsewhere")
    ws = project(here)  # every answer marked, then `fix`: half kept aside
    capsys.readouterr()
    new = other / write_rows(other, "new.csv", breaking(ws, "wrong"))
    said = []

    def step(*argv):
        code = main([str(a) for a in argv])
        said.append((argv, code, capsys.readouterr().out))
        return code

    step("fix", new)
    step("fix", new)  # tested before: read from split.json
    step("check", new)
    rows = [{"answer": r["output"], "label": r["verdict"]}
            for r in breaking(ws, "wrong")[:10]]
    labels = write_labels(other / "labels.csv", rows)
    step("--labels", labels, *PAGE)
    shutil.copy(here / "results.csv", other / "results.csv")
    step("check", other / "results.csv")
    (here / ".judgekeeper" / "result.json").unlink()  # Measure writes it again, as below
    step(other / "results.csv", *PAGE)  # result.json keeps this command's flags
    result = json.loads((here / ".judgekeeper" / "result.json").read_text(encoding="utf-8"))
    assert (here / ".judgekeeper" / "fix" / "split.json").is_file(), said
    assert result["flags"]["path"] != ".", (result["flags"], said[-1])
    found = _whole_paths(here / ".judgekeeper", here, other, tmp_path, Path.home())
    assert found == {}, (found, [s[:2] for s in said])
    whole = {str(other), os.path.realpath(other), str(tmp_path), os.path.realpath(tmp_path)}
    printed = [(argv, line) for argv, _, out in said for line in out.splitlines()
               if any(w in line for w in whole)]
    assert printed == [], printed  # every command it prints names them from here


def test_an_older_split_with_a_whole_path_still_reads(here, capsys, tmp_path_factory):
    from judgekeeper import fix
    from tests.test_regrade_files import breaking, project
    from tests.test_regrade_files import write as write_rows

    other = tmp_path_factory.mktemp("elsewhere")
    ws = project(here)
    new = other / write_rows(other, "new.csv", breaking(ws, "wrong"))
    assert main(["fix", str(new)]) == 0
    split = fix.read_split(ws)
    kept = os.path.relpath(os.path.realpath(new), os.path.realpath(here))
    assert split.tests[-1]["file"] == kept.replace(os.sep, "/")  # the same on every system
    split.tests[-1]["file"] = str(new)  # as an older judgekeeper kept it
    fix.save_split(ws, split)
    capsys.readouterr()
    assert main(["fix", str(new)]) == 0
    out = " ".join(capsys.readouterr().out.split())
    assert "You tested this LLM-as-a-judge before" in out and "has the same" not in out, out


def test_a_path_on_another_drive_is_kept_by_its_name(monkeypatch):
    from judgekeeper import textio

    def other_drive(path, start=None):
        raise ValueError("path is on mount 'D:', start on mount 'C:'")

    monkeypatch.setattr(os.path, "relpath", other_drive)
    assert textio.kept_path(os.path.join(os.sep, "data", "new.json"), os.sep) == "new.json"


def test_an_mlflow_store_given_in_full_is_kept_from_the_project(tmp_path):
    from judgekeeper import front

    root = tmp_path / "shop"
    root.mkdir()
    store = os.path.join(os.path.realpath(tmp_path), "stores", "mlflow.db")
    up = os.path.join("..", "stores", "mlflow.db").replace(os.sep, "/")
    assert front._kept_uri(store, root) == up
    assert front._kept_uri("sqlite:///" + store, root) == "sqlite:///" + up
    for given in ("sqlite:///mlflow.db", "http://127.0.0.1:5000", "databricks", "mlruns"):
        assert front._kept_uri(given, root) == given
