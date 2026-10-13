"""The default port taken: the page opens on the next free one (8766-8785) and nothing extra
is said, unless a judgekeeper page of another project holds it: then the output says so and how
to close it. When no port is free, the Next: line never suggests --wait, which would need the
same port."""

from __future__ import annotations

import socket
import threading

import pytest

from judgekeeper import page
from judgekeeper.cli import main
from judgekeeper.label import LabelServer, LabelSession
from tests.start_projects import promptfoo_project, split

ANOTHER = "A marking page for another project is open; close it there with `judgekeeper --stop`."


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
    assert ANOTHER in out.splitlines()


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
    assert out.rstrip().splitlines()[-1].startswith("Next: run `judgekeeper --port 0")
