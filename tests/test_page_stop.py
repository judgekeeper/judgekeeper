"""`--stop` closes the page even when server.json is gone: the page records itself in a second
file in .judgekeeper/. A page nobody can close any more stops by itself after 30 minutes
without a request."""

from __future__ import annotations

import pytest

from judgekeeper import label
from judgekeeper.cli import main
from tests.start_projects import promptfoo_project, split
from tests.test_fix_mlflow_lines import STORE


@pytest.fixture(scope="module")
def mlruns46(tmp_path_factory):
    """A real MLflow folder store of 46 graded traces (23 passed, 23 failed), so 20 marks in
    each group leave answers to mark."""
    import subprocess
    import sys

    pytest.importorskip("mlflow")
    build = tmp_path_factory.mktemp("mlruns-46")
    (build / "make_store.py").write_text(STORE.replace("range(40)", "range(46)"),
                                         encoding="utf-8")
    subprocess.run([sys.executable, "make_store.py"], cwd=build, check=True,
                   capture_output=True)
    return build / "mlruns"


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    promptfoo_project(tmp_path, split(20, 16))
    return tmp_path


def _run(capsys, *argv):
    code = main([str(a) for a in argv])
    out, _ = capsys.readouterr()
    return code, out


def test_stop_closes_the_page_when_server_json_is_gone(here, capsys, pages):
    code, out = _run(capsys, "--no-browser")
    assert code == 0, out
    folder = here / ".judgekeeper"
    (folder / label.LOCK).unlink()
    assert label.is_open(folder)  # found through the second record
    code, out = _run(capsys, "--stop")
    assert code == 0, out
    assert "Closed the marking page." in out
    assert not label.is_open(folder)
    assert not (folder / label.LOCK_COPY).exists()


def test_both_records_are_the_same_and_gone_once_the_page_stops(here, capsys, pages):
    code, out = _run(capsys, "--no-browser")
    assert code == 0, out
    folder = here / ".judgekeeper"
    copy = (folder / label.LOCK_COPY).read_text(encoding="utf-8")
    assert copy == (folder / label.LOCK).read_text(encoding="utf-8")
    assert _run(capsys, "--stop")[0] == 0
    assert not (folder / label.LOCK).exists() and not (folder / label.LOCK_COPY).exists()


def test_an_idle_page_closes_after_30_minutes():
    assert label.IDLE_TIMEOUT == 30 * 60


# Ctrl-C --------------------------------------------------------------------------------------

def test_ctrl_c_before_the_link_is_printed_stops_the_page_too(here, capsys, pages, monkeypatch):
    from judgekeeper import page

    def interrupted(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(page, "show", interrupted)
    code, out = _run(capsys, "--no-browser")
    assert code == 130
    assert "\nStopped.\n" in out and "token=" not in out
    assert not label.is_open(here / ".judgekeeper")  # no page left running


def test_ctrl_c_on_wait_says_stopped_and_exits_130(here, capsys, monkeypatch):
    real = label.LabelServer.serve

    def interrupted(self, *args, **kwargs):  # Ctrl-C while the page is served
        self.stop()
        real(self, *args, **kwargs)
        raise KeyboardInterrupt

    monkeypatch.setattr(label.LabelServer, "serve", interrupted)
    monkeypatch.setattr("webbrowser.open", lambda *a, **k: True)
    code, out = _run(capsys, "--wait")
    assert code == 130, out
    assert out.rstrip().splitlines()[-2:] == [
        "Stopped.", "Next: run `judgekeeper --wait` to carry on."]
    assert not label.is_open(here / ".judgekeeper")


@pytest.mark.parametrize("tool", ["csv", "mlflow"])
def test_wait_with_a_result_and_answers_left_serves_until_ctrl_c(tmp_path, capsys, monkeypatch,
                                                                 request, tool):
    """The result, then the page: --wait served it, but asked its own page, not served yet,
    whether it was open, and stopped at once (busy, exit 3), its server.json left. Ctrl-C
    after the result's Next: line adds no second one."""
    import shutil

    from judgekeeper import judge_setup, start, start_label
    from judgekeeper.start_label import StartSession
    from tests.start_projects import table_project

    monkeypatch.chdir(tmp_path)
    if tool == "mlflow":
        from judgekeeper.readers import mlflow_store

        monkeypatch.setattr(mlflow_store, "_walked", {})
        shutil.copytree(request.getfixturevalue("mlruns46"), tmp_path / "mlruns")
        request.addfinalizer(mlflow_store.remove_copies)
    else:
        table_project(tmp_path, split(23, 23))
    found = start.find_judge(tmp_path)
    judge_setup.save(start_label.Workspace(tmp_path), judge_setup.of(found), found.metric)
    ws = start_label.prepare(found, say=lambda line="": None)
    session = StartSession(ws)
    queue = ws.data()["queue"]
    # 20 in each group, 6 left to mark
    picked = [q for g in ("pass", "fail") for q in [x for x in queue if x["group"] == g][:20]]
    for q in picked:
        session.update({"id": q["id"], "label": q["group"], "seconds": 5})
    real = label.LabelServer.serve

    def interrupted(self, *args, **kwargs):  # Ctrl-C while the page is served
        self.stop()
        real(self, *args, **kwargs)
        raise KeyboardInterrupt

    monkeypatch.setattr(label.LabelServer, "serve", interrupted)
    code, out = _run(capsys, "--wait", "--no-browser", "--port", "0")
    assert code == 130, out
    assert "Result:" in out and "not answering" not in out
    assert "Stopped." not in out and out.count("Next:") == 1  # Next: was the last word
    assert not (ws.dir / label.LOCK).exists() and not label.is_open(ws.dir)
