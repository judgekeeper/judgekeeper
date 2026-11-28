"""Every printed command that opens a page again repeats how the run opened it, by one rule:
`--port N` unless N is the default (0 too: any free port), and `--no-browser` when given. The
same in the terminal's Next: lines, after --stop and in a page's "To come back" footer, for
the answers page and the steps page alike."""

from __future__ import annotations

import json
from html import unescape

import pytest

from judgekeeper import start, steps_page
from judgekeeper.cli import main
from judgekeeper.start_label import Workspace
from tests.start_projects import promptfoo_project, split

FLAGS = "--port 0 --no-browser"


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _runs(here):
    rows = [{"id": f"r{i}", "task": f"Task {i}",
             "steps": [{"role": "user", "content": f"Ask {i}"},
                       {"role": "assistant", "content": f"Do {i}"}]} for i in range(4)]
    (here / "runs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows),
                                     encoding="utf-8")


def _out(capsys, *argv):
    code = main(list(argv))
    out, _ = capsys.readouterr()
    return code, " ".join(out.split())


def test_the_rule_is_one_helper():
    assert start.page_flags() == ()
    assert start.page_flags(0) == ("--port", "0")
    assert start.page_flags(8790, True) == ("--port", "8790", "--no-browser")
    assert start.page_flags(8765, True) == ("--no-browser",)
    # the answers page's footer says them by it
    assert unescape(start.come_back({"path": ".", "port": 0, "no_browser": True})) == \
        f"judgekeeper mark {FLAGS}"


def test_answers_stop_repeats_port_0_and_no_browser(here, capsys, pages):
    promptfoo_project(here, split(20, 16))
    main(["--port", "0", "--no-browser"])
    capsys.readouterr()
    code, out = _out(capsys, "--stop")
    assert code == 0 and "Closed the marking page." in out, out
    assert f"Next: run `judgekeeper {FLAGS}` when you want to continue." in out, out


def test_steps_stop_repeats_the_page_flags(here, capsys, pages):
    _runs(here)
    main(["steps", "runs.jsonl", "--port", "0", "--no-browser"])
    capsys.readouterr()
    code, out = _out(capsys, "steps", "--stop")
    assert code == 0 and "Closed the marking page." in out, out
    assert f"Next: run `judgekeeper steps runs.jsonl {FLAGS}` when you want to continue." in out


def test_plain_stop_on_a_steps_page_repeats_them_too(here, capsys, pages):
    _runs(here)
    main(["steps", "runs.jsonl", "--port", "8790", "--no-browser"])
    capsys.readouterr()
    _, out = _out(capsys, "--stop")
    assert ("Next: run `judgekeeper steps runs.jsonl --port 8790 --no-browser` when you want to "
            "continue.") in out, out


def test_steps_next_lines_repeat_them(here, capsys, pages):
    _runs(here)
    session = steps_page.StepsSession(Workspace(here), here / "runs.jsonl")
    session.update({"id": "r1", "first_wrong_step": 1, "was": None, "seconds": 1})
    _, out = _out(capsys, "steps", "runs.jsonl", "--port", "0", "--no-browser")
    assert f"`judgekeeper steps runs.jsonl {FLAGS} --reviewer PICKS.jsonl`" in out, out
    main(["steps", "--stop"])


def test_the_steps_page_footer_repeats_them(here):
    _runs(here)
    flags = steps_page.flags_for(here / "runs.jsonl", shown="runs.jsonl", port=0,
                                 no_browser=True)
    assert steps_page.come_back(flags) == f"judgekeeper steps runs.jsonl {FLAGS}"
    assert steps_page.come_back({**flags, "port": 8765, "no_browser": False}) == \
        "judgekeeper steps runs.jsonl"



def test_steps_on_a_taken_port_says_any_free_port_with_no_browser(here, capsys, pages):
    import socket

    _runs(here)
    _, state = pages
    state["fail"] = True  # the page can't listen on a port in use
    held = socket.socket()
    held.bind(("127.0.0.1", 0))
    held.listen()
    port = held.getsockname()[1]
    try:
        code, out = _out(capsys, "steps", "runs.jsonl", "--port", str(port), "--no-browser")
    finally:
        held.close()
    assert code == 3 and f"Port {port} is in use" in out, out
    assert f"Next: run `judgekeeper steps runs.jsonl {FLAGS}`" in out, out


@pytest.mark.parametrize("picked, said", [
    (4, "every run is marked, so add runs to runs.jsonl"),
    (3, "fix them in picks.jsonl and run"),
])
def test_the_next_line_once_every_run_is_marked_repeats_them(here, capsys, pages, picked,
                                                             said):
    """Every run marked and a number too few: the line to add runs, or to fix the picks file
    when a pick is left out, says the command with the run's page flags too."""
    _runs(here)
    session = steps_page.StepsSession(Workspace(here), here / "runs.jsonl")
    for i in range(4):
        session.update({"id": f"r{i}", "first_wrong_step": i % 2, "was": None, "seconds": 2})
    (here / "picks.jsonl").write_text("".join(
        json.dumps({"id": f"r{i}", "first_wrong_step": 1, "model": "m"}) + "\n"
        for i in range(picked)), encoding="utf-8")
    code, out = _out(capsys, "steps", "runs.jsonl", "--reviewer", "picks.jsonl", "--port", "0",
                     "--no-browser")
    main(["steps", "--stop"])
    assert code == 3 and said in out, out
    assert f"`judgekeeper steps runs.jsonl --reviewer picks.jsonl {FLAGS}`." in out, out
