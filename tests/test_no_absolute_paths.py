"""No file judgekeeper writes in .judgekeeper/ holds an absolute path: the folder may be
committed, and a path from the root names the user's own folders. Paths are kept relative to
the project folder (`..` allowed); files an older judgekeeper wrote with absolute paths
still read."""

from __future__ import annotations

import json
import os
import sys
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


# A path that would climb to the top folder, or above the home folder, names no folder ---------

USER = "ann-x"  # the user name in the home folder's path: no file or line may hold it


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A home folder at tmp/Users/ann-x: its parent folders are above the home folder."""
    folder = tmp_path / "Users" / USER
    (folder / "Desktop").mkdir(parents=True)
    real = Path(os.path.realpath(folder))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: real))
    return real


def test_a_kept_path_climbs_only_to_a_folder_below_the_home_folder(home, tmp_path):
    from judgekeeper import textio

    proj = home / "Desktop" / "proj"
    assert textio.kept_path(home / "Desktop" / "ext" / "r.csv", proj) == "../ext/r.csv"
    assert textio.kept_path(home / "r.csv", proj) == "../../r.csv"  # home is shared
    other = Path(os.path.realpath(tmp_path)) / "elsewhere" / "new.csv"  # shares above home
    assert textio.kept_path(other, proj) == "new.csv"
    top = Path(os.path.realpath(tmp_path)).anchor
    assert textio.kept_path(os.path.join(top, "jk-none", "new.csv"), proj) == "new.csv"
    work = Path(os.path.realpath(tmp_path)) / "work" / "proj"  # outside the home folder
    kept = textio.kept_path(home / "Desktop" / "r.csv", work)
    assert kept == "~/Desktop/r.csv"
    assert Path(textio.kept_at(kept, work)) == home / "Desktop" / "r.csv"
    assert textio.kept_path(work.parent / "r.csv", work) == "../r.csv"


def test_a_printed_path_climbs_only_to_a_folder_below_the_home_folder(home, tmp_path,
                                                                      monkeypatch):
    from judgekeeper import textio

    proj = home / "Desktop" / "proj"
    proj.mkdir()
    monkeypatch.chdir(proj)
    other = str(Path(os.path.realpath(tmp_path)) / "elsewhere" / "new.csv")
    assert textio.shown_from_here(other) == "new.csv"
    if os.name == "nt":  # a command that runs: in full when nothing shorter does (printed only)
        assert textio.runnable(other, labels=True) == textio.quote_arg(other)
    else:
        assert textio.runnable(other, labels=False) == "PATH"
        assert textio.runnable(other, labels=True) == "<file>"
    assert textio.shown_from_here(str(home / "Desktop" / "ext" / "r.csv")) == "../ext/r.csv"
    work = Path(os.path.realpath(tmp_path)) / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    inside = str(home / "Desktop" / "r.csv")
    assert textio.shown_from_here(inside) == textio._home_shown("Desktop/r.csv")
    assert (USER not in textio.runnable(inside, labels=False)) is (os.name != "nt")


def test_a_loop_given_whole_paths_from_anywhere_names_no_folder_above_the_project(
        home, tmp_path, tmp_path_factory, monkeypatch, capsys):
    """Results given by whole path on the first run, labels and fix/check files on another
    root, then `check <project>` from the top folder, the parent and another root: no file
    under .judgekeeper/ (report.html too) and no printed line names the home folder's path,
    or a folder above it."""
    from judgekeeper.start_label import StartSession, Workspace
    from tests.test_labels_import import write_labels
    from tests.test_regrade_files import COLUMNS, _row, _write, breaking, closed, regraded
    from tests.test_regrade_files import write as write_rows

    proj, ext = home / "Desktop" / "proj", home / "ext"
    proj.mkdir()
    ext.mkdir()
    other = Path(os.path.realpath(tmp_path_factory.mktemp("elsewhere")))
    _write(ext / "results.csv", [_row(i, 5) for i in range(60)], COLUMNS)
    monkeypatch.chdir(proj)
    said = []

    def step(*argv):
        code = main([str(a) for a in argv])
        out, err = capsys.readouterr()
        said.append((argv, code, out + err))
        return code

    assert step(ext / "results.csv", "--no-browser") == 0, said[-1]
    ws = Workspace(proj)
    closed(ws)
    session = StartSession(ws)
    pool = {r["id"]: r for r in map(json.loads,
                                    ws.pool.read_text(encoding="utf-8").splitlines())}
    for item in session.items:
        session.update({"id": item["id"], "seconds": 5,
                        "label": "fail" if "BAD" in pool[item["id"]]["output"] else "pass"})
    step(*PAGE)  # Measure: the result, and report.html
    background.stop(ws.dir)
    step("fix")
    flip = {"pass": "fail", "fail": "pass"}
    new = other / write_rows(other, "new.csv", [
        {**r, "verdict": flip[r["verdict"]]} if i % 2 == 0 else r
        for i, r in enumerate(regraded(ws))])
    step("fix", new)
    from judgekeeper import fix

    assert fix.read_split(ws).tests[-1]["file"] == "new.csv"  # shares only above home
    assert step("check", new) == 1 and "Worse" in said[-1][2], said[-1]
    report = " ".join((ws.dir / "report.html").read_text(encoding="utf-8").split())
    assert "grade the answers in .judgekeeper/fix/marked-answers.csv again" in report
    labels = write_labels(other / "labels.csv", [{"answer": r["output"], "label": r["verdict"]}
                                                 for r in breaking(ws, "wrong")[:10]])
    step("--labels", labels, *PAGE)
    background.stop(ws.dir)
    for cwd in (Path(proj.anchor), home / "Desktop", other):
        monkeypatch.chdir(cwd)
        step("check", proj)
        step("fix", proj)
    assert (ws.dir / "report.html").is_file() and json.loads(ws.start.read_text(
        encoding="utf-8"))["given"] == "../../ext/results.csv"
    above = (USER, "pytest-of", other.name, str(home), str(tmp_path))
    found = {}
    for f in sorted(ws.dir.rglob("*")):
        if f.is_file() and f.name not in ("server.json", "page.json"):
            text = f.read_bytes().decode("utf-8", "replace").replace("\\\\", "/")
            found.update({str(f.relative_to(ws.dir)): w for w in above
                          if w in text.replace("\\", "/")})
    assert found == {}, (found, [s[:2] for s in said])
    printed = [(argv, line) for argv, _, out in said for line in out.splitlines()
               if any(w in line for w in above)
               and not (os.name == "nt" and "`" in line)]  # a command runs: in full there
    assert printed == [], printed


@pytest.mark.skipif(os.name == "nt", reason="sh reads ~/; on Windows no command says it")
def test_a_printed_command_with_a_home_path_runs_as_pasted_from_the_top_folder(
        tmp_path, monkeypatch, capsys):
    """From a folder that shares only `/` with it, a path in the home folder holding a space
    is `~/'...'` in each printed command: pasted into sh, it finds the file."""
    import subprocess

    from judgekeeper import cli, textio
    from tests.start_projects import promptfoo_project

    home = Path(os.path.realpath(tmp_path)) / "Users" / USER
    proj = home / "Desktop" / "My Proj"
    proj.mkdir(parents=True)
    promptfoo_project(proj, split(20, 16))
    monkeypatch.setenv("HOME", str(home))  # Path.home(), and the shell's ~
    monkeypatch.chdir("/")

    def found(line: str, word: str) -> str:
        """The path the shell reads from `word` in `line`, a printed command."""
        assert word in line, line
        return subprocess.run(["sh", "-c", f"printf '%s' {word}"], capture_output=True,
                              text=True, check=True, cwd="/").stdout

    again = cli.again([str(proj / "promptfooconfig.yaml"), "--no-browser"])
    word = textio.runnable(str(proj / "promptfooconfig.yaml"), labels=False)
    assert word.startswith("~/'") and USER not in again
    assert found(again, word) == str(proj / "promptfooconfig.yaml")
    assert main(["--labels", str(proj)]) != 0
    out = " ".join(capsys.readouterr().out.split())
    folder = textio.runnable(str(proj), labels=False)
    assert f"To check that folder, put it first: judgekeeper {folder} --labels <file>" in out
    assert found(out, folder) == str(proj) and USER not in out


def test_the_file_line_from_the_top_folder_names_no_user(home, tmp_path, monkeypatch):
    """Screen 1's File: line for results outside the project, run from `/`: `~/...`, never
    Users/<name>/..."""
    from types import SimpleNamespace

    from judgekeeper import front, textio

    results = home / "ext" / "results.csv"
    work = Path(os.path.realpath(tmp_path)) / "work"
    found = SimpleNamespace(tool="table", root=work, used=["results.csv"], results=[
        SimpleNamespace(path=results, rel=textio.kept_path(results, work))])
    monkeypatch.chdir(Path(home.anchor))
    shown = front._read_from(found)
    assert USER not in shown and shown.endswith("results.csv"), shown
    assert shown == textio._home_shown("ext/results.csv")


@pytest.mark.skipif(os.name == "nt", reason="a POSIX path can't be faked on Windows")
def test_on_macos_paths_sharing_only_private_are_named_in_full(monkeypatch):
    """/tmp and /var are /private/tmp and /private/var on macOS: two paths that share only
    /private are named as when they share only `/`, never by climbing to it."""
    from judgekeeper import textio

    monkeypatch.setattr(sys, "platform", "darwin")
    proj = "/private/var/folders/xy/T/pytest-1/proj"
    monkeypatch.setattr(textio.os, "getcwd", lambda: proj)
    python = "/private/tmp/jk-kit/venv/bin/python"
    assert textio.command_path(python) == python
    assert textio.kept_path("/private/tmp/jk-kit/new.csv", proj) == "new.csv"
    assert textio.kept_path(proj + "/data/new.csv", proj) == "data/new.csv"
    assert textio.kept_path("/private/var/folders/xy/T/new.csv", proj) == "../../new.csv"
