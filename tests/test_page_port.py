"""The default port taken: the page opens on the next free one (8766-8785) and nothing extra
is said, unless a judgekeeper page of another project holds it: then the output says so and how
to close it. When no port is free, the Next: line never suggests --wait, which would need the
same port."""

from __future__ import annotations

import os
import socket
import threading

import pytest

from judgekeeper import page
from judgekeeper.cli import main
from judgekeeper.label import LabelServer, LabelSession
from tests.start_projects import promptfoo_project, split, table_project
from tests.test_front import next_lines

ANOTHER = ("Another judgekeeper page is already open on port {old}, so this page uses port {new}. "
           "To close that one, run `judgekeeper --stop` in its folder.")


@pytest.fixture
def taken(monkeypatch):
    """A port that something listens on, as the default port; the ports after it as the
    others to try."""
    held = socket.socket()
    held.bind(("127.0.0.1", 0))
    held.listen()
    port = held.getsockname()[1]
    monkeypatch.setattr(page, "DEFAULT_PORT", port)
    monkeypatch.setattr(page, "OTHER_PORTS", range(port + 1, port + 21))
    yield held, port
    held.close()


@pytest.fixture
def here(tmp_path, monkeypatch):
    project = tmp_path / "a"
    project.mkdir()
    monkeypatch.chdir(project)
    promptfoo_project(project, split(20, 16))
    return project


def _run(capsys, *argv):
    code = main([str(a) for a in argv])
    out, _ = capsys.readouterr()
    return code, out


def _other_project_page(tmp_path, held: socket.socket, port: int):
    """A judgekeeper page of another project, on `port`."""
    held.close()
    items = tmp_path / "items.jsonl"
    items.write_text('{"id": "x", "input": "q", "output": "a"}\n', encoding="utf-8")
    server = LabelServer(LabelSession(items, tmp_path / "labels.csv"), port=port, page="<p>")
    thread = threading.Thread(target=server.serve, daemon=True)
    thread.start()
    return server, thread


def test_a_taken_default_port_gives_the_next_free_one(here, taken, capsys, pages):
    _, port = taken
    code, out = _run(capsys, "--port", port, "--no-browser")
    assert code == 0, out
    started, _ = pages
    assert started[-1]["port"] in page.OTHER_PORTS
    assert "another project" not in out and "--wait" not in out


def test_a_page_of_another_project_on_the_port_is_named(tmp_path, here, taken, capsys, pages):
    held, port = taken
    server, thread = _other_project_page(tmp_path, held, port)
    try:
        code, out = _run(capsys, "--port", port, "--no-browser")
    finally:
        server.stop()
        thread.join(timeout=5)
    assert code == 0, out
    started, _ = pages
    assert started[-1]["port"] in page.OTHER_PORTS
    said = ANOTHER.format(old=port, new=started[-1]["port"])
    assert said in " ".join(out.split()), out  # wrapped, as every other line


def test_a_free_port_is_chosen_quietly(taken):
    _, port = taken
    said = []
    assert page.choose_port(port, said.append) in page.OTHER_PORTS
    assert said == []


def test_a_port_that_is_not_the_default_is_kept(taken):
    _, port = taken
    assert page.choose_port(port + 100, print) == port + 100


def test_no_free_port_never_suggests_wait(here, taken, capsys, pages, monkeypatch):
    _, port = taken
    monkeypatch.setattr(page, "OTHER_PORTS", ())
    _, state = pages
    state["fail"] = True  # the page can't listen on a port in use
    code, out = _run(capsys, "--port", port, "--no-browser")
    assert code == 3, out
    assert "--wait" not in out
    assert f"Port {port} is in use" in out
    assert next_lines(out)[-1].startswith("Next: run `judgekeeper --port 0")


def test_a_taken_port_given_stops_before_anything_is_written(here, capsys, pages):
    """--port names a port something else listens on: the run says so and writes no
    .judgekeeper/ (a run again on a free port starts from nothing)."""
    held = socket.socket()
    held.bind(("127.0.0.1", 0))
    held.listen()
    port = held.getsockname()[1]
    try:
        code, out = _run(capsys, "--port", port, "--no-browser")
    finally:
        held.close()
    assert code == 3, out
    assert f"Port {port} is in use" in out
    assert not (here / ".judgekeeper").exists(), out
    after = " ".join(out.split("Next:")[-1].split())  # this project's command, on any free port
    assert "`judgekeeper --port 0 --no-browser`" in after and f"--port {port}" not in after, out


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def test_a_command_for_another_project_keeps_no_browser_and_never_the_port(tmp_path, capsys,
                                                                           pages, monkeypatch):
    """services/ holds loose/ (read) and rag/ (a project with a session of its own): the run with
    --port and --no-browser opens its page on that port, so the command it prints for rag/
    keeps --no-browser and leaves the port out (the default moves to a free one)."""
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    services = tmp_path / "services"
    table_project(services / "loose", split(20, 20), tag="l")
    (services / "rag").mkdir()
    (services / "rag" / "rag.py").write_text("", encoding="utf-8")
    (services / "rag" / "answers.csv").write_text(
        "input,output\n" + "".join(f"Q{i}?,A{i}.\n" for i in range(12)), encoding="utf-8")
    monkeypatch.chdir(services / "rag")
    _run(capsys, "answers.csv", "--port", 0, "--no-browser")  # its own session
    monkeypatch.chdir(services)
    port = _free_port()
    _, out = _run(capsys, "--port", port, "--no-browser")
    said = " ".join(out.split())
    assert "`judgekeeper rag --no-browser`" in said, said


def test_the_folder_above_is_named_with_no_browser_and_never_the_port(tmp_path, capsys,
                                                                      pages, monkeypatch):
    """proj/ holds results, proj/src/ nothing: the run in src/ names the folder above with
    --no-browser, never the port given."""
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    proj = tmp_path / "proj"
    promptfoo_project(proj, split(5, 5))
    (proj / "pyproject.toml").write_text("", encoding="utf-8")
    (proj / "src").mkdir()
    (proj / "src" / "app.py").write_text("", encoding="utf-8")
    monkeypatch.chdir(proj / "src")
    port = _free_port()
    _, out = _run(capsys, "--port", port, "--no-browser")
    said = " ".join(out.split())
    assert "Run `judgekeeper .. --no-browser`" in said, said


# One rule for every printed command: one for another project keeps --no-browser and leaves out
# --port (that port's page may be up); one for this project keeps both (its page there is
# closed and opened again)


def _layout(kind: str, top) -> tuple:
    """(the folder to run in, its arguments, {a printed command's start: "another" or "this"})."""
    from tests.test_folder_matrix import _answers_csv, _jsonl

    if kind == "results too":
        table_project(top / "loose", split(20, 20), tag="l")
        _answers_csv(top / "rag", 12, "r")
        (top / "rag" / "rag.py").write_text("", encoding="utf-8")
        return top / "rag", ("answers.csv",), {}
    if kind == "go to one":
        table_project(top / "a", split(3, 3), tag="a")
        table_project(top / "b", split(3, 3), tag="b")
        return top, (), {"judgekeeper": "another"}
    if kind == "belongs":
        table_project(top / "p", split(3, 3), tag="p")
        (top / "p" / "pyproject.toml").write_text("", encoding="utf-8")
        return top, (), {"judgekeeper": "another"}
    if kind == "left out":
        (top / "q" / "data").mkdir(parents=True)
        (top / "q" / "pyproject.toml").write_text("", encoding="utf-8")
        _jsonl(top / "q" / "data", 6, "q")
        return top, (".",), {"judgekeeper q": "another"}
    if kind == "other eval":
        table_project(top / "logs", split(5, 5), tag="a", name="graded.csv")
        old = table_project(top, split(3, 3), tag="b", name="top.csv")
        os.utime(old, (1, 1))
        return top, (), {"judgekeeper there": "another", "judgekeeper mark": "this"}
    if kind == "tool below":
        table_project(top / "p", split(3, 3), tag="p")
        (top / "p" / "pyproject.toml").write_text("", encoding="utf-8")
        return top, ("--tool", "deepeval"), {"judgekeeper": "another"}
    if kind == "new here":
        table_project(top, split(20, 20), tag="t")
        (top / "pyproject.toml").write_text("", encoding="utf-8")
        (top / "sub").mkdir()
        return top / "sub", (), {"judgekeeper .": "another"}
    raise AssertionError(kind)


@pytest.mark.parametrize("kind", ["go to one", "belongs", "left out", "other eval",
                                  "tool below", "new here", "results too"])
def test_every_command_keeps_no_browser_and_the_port_only_for_this_project(
        tmp_path, capsys, pages, monkeypatch, kind):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    top = tmp_path / "w"
    top.mkdir()
    folder, argv, expect = _layout(kind, top)
    port = _free_port()
    if kind == "results too":  # rag/ holds a session of its own; the run is in w/
        monkeypatch.chdir(folder)
        _run(capsys, *argv, "--port", 0, "--no-browser")
        main(["--stop"])
        capsys.readouterr()
        folder, argv, expect = top, (), {"judgekeeper rag": "another"}
    monkeypatch.chdir(folder)
    main([*argv, "--port", str(port), "--no-browser"])
    out, err = capsys.readouterr()
    main(["--stop"])
    said = " ".join((out + err).split())
    printed = [c for c in said.split("`")[1::2] if c.startswith("judgekeeper")]
    for start_, where in expect.items():
        if start_ == "judgekeeper there":  # "put it in a folder of its own and run ... there"
            found = [c for c, before in zip(said.split("`")[1::2], said.split("`")[::2])
                     if c.startswith("judgekeeper") and before.endswith("of its own and run ")]
        else:
            found = [c for c in printed if c == start_ or c.startswith(start_ + " ")]
        assert found, (start_, said)
        for command in found:
            assert "--no-browser" in command, (command, said)
            assert (f"--port {port}" in command) == (where == "this"), (command, said)
