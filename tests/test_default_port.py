"""Tests never take judgekeeper's own port, 8765, and never depend on it being free: a person's
page, another checkout's tests or a test running alongside may hold it. A test that binds it
fails at once and says so; a test whose page is served in this process sees the port as free
and serves on another."""

from __future__ import annotations

import socket
import subprocess
import sys

import pytest

from judgekeeper import label, page
from judgekeeper.cli import main
from tests.conftest import OWN_PORT, TAKES_OWN_PORT
from tests.test_steps_open import here  # noqa: F401  (the fixture)


class _HeldElsewhere(socket.socket):
    """A socket for which judgekeeper's port is held by something outside this test."""

    def bind(self, address):
        if address[1] == label.DEFAULT_PORT:
            raise OSError(48, "Address already in use")
        return super().bind(address)


def test_the_guarded_port_is_judgekeepers_own():
    assert label.DEFAULT_PORT == 8765 and OWN_PORT.endswith("8765")


def test_a_page_on_the_default_port_elsewhere_changes_nothing_here(here, capsys, pages,  # noqa: F811
                                                                    monkeypatch):
    monkeypatch.setattr(socket, "socket", _HeldElsewhere)
    monkeypatch.setattr(page, "is_page", lambda port: True)
    code = main(["steps", "runs.jsonl", "--no-browser"])
    out = capsys.readouterr().out
    started, _ = pages
    assert code == 0, out
    assert "Another judgekeeper page" not in out
    assert started[-1]["port"] == label.DEFAULT_PORT


def test_a_page_served_here_with_wait_takes_another_port(here, capsys, pages,  # noqa: F811
                                                          monkeypatch):
    served = []

    def serve(server):  # the person closes the page at once
        served.append(server.port)
        server.stop()
        server.serve()

    monkeypatch.setattr(page, "serve", serve)
    main(["steps", "runs.jsonl", "--wait", "--no-browser"])
    capsys.readouterr()
    assert served and served[0] != label.DEFAULT_PORT


def test_binding_the_default_port_fails_the_test_at_once():
    with socket.socket() as s, pytest.raises(RuntimeError, match=OWN_PORT):
        s.bind(("127.0.0.1", label.DEFAULT_PORT))


def test_a_python_a_test_starts_cannot_bind_it_either():
    run = subprocess.run([sys.executable, "-c",
                          "import socket; socket.socket().bind(('127.0.0.1', 8765))"],
                         capture_output=True, text=True, timeout=60, check=False)
    assert run.returncode != 0 and OWN_PORT in run.stderr, run.stderr


def test_a_test_that_must_show_the_port_says_so(monkeypatch):
    """scripts/make_site_shots.py serves on 8765, as a person does, for the website's
    pictures: its test names that, and only then is the port let through."""
    from tests.conftest import _guard

    bind = ("socket.bind", (None, ("127.0.0.1", label.DEFAULT_PORT)))
    with pytest.raises(RuntimeError, match=OWN_PORT):
        _guard(*bind)
    monkeypatch.setenv(TAKES_OWN_PORT, "1")
    _guard(*bind)
    _guard("socket.bind", (None, ("127.0.0.1", 0)))
