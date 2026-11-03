"""After --stop, the Next line's command carries on the project as it reads its results:
on a scores project, with the pass mark in use and the flags the run was given."""

from __future__ import annotations

import re
import shlex

from judgekeeper.cli import main
from tests import test_fix
from tests.test_fix import _main, _rule_in_use, score_project

here = test_fix.here  # the fixture: a project folder


def _next_command(said: str) -> list[str]:
    return shlex.split(re.search(r"Next: run `([^`]+)` when you want to continue\.", said)[1])


def test_stop_after_a_new_pass_mark_names_a_run_that_reads_the_scores(here, capsys):
    ws = score_project(here)
    _main(capsys, "--pass-if", "score>=0.5", "--no-browser", "--port", "0")
    main(["--stop"])
    code, said = _main(capsys, "check", "--pass-if", "score>=0.72")
    assert code == 0 and _rule_in_use(ws) == "score>=0.72", said
    _main(capsys, "mark", "--pass-if", "score>=0.72", "--no-browser", "--port", "0")
    code, said = _main(capsys, "--stop")
    command = _next_command(said)
    assert command[0] == "judgekeeper" and "--stop" not in command, said
    assert command[command.index("--pass-if") + 1] == "score>=0.72", said
    assert "--no-browser" in command and command[command.index("--port") + 1] == "0", said
    code, said = _main(capsys, *command[1:])  # as printed: it reads the scores
    main(["--stop"])
    assert code == 0 and "do not say which score passes" not in said, said


def test_stop_with_no_result_yet_names_the_plain_run(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _, said = _main(capsys, "--stop")
    assert _next_command(said) == ["judgekeeper"], said


def test_stop_before_a_result_names_the_port_of_the_page_it_closed(here, capsys):
    """No result yet keeps the run's flags, but the page knows its port: the Next line
    carries it, so the page opens where it was."""
    from tests.start_projects import promptfoo_project, split

    promptfoo_project(here, split(30, 30))
    from judgekeeper.label import read_lock

    _main(capsys, "--port", "9771", "--no-browser")
    port = read_lock(here / ".judgekeeper")["port"]  # the tests' pages take a free port
    code, said = _main(capsys, "--stop")
    assert code == 0 and "Closed the marking page." in said, said
    assert _next_command(said) == ["judgekeeper", "--port", str(port)], said
    code, said = _main(capsys, "--stop")  # no page open: nothing to carry
    assert _next_command(said) == ["judgekeeper"], said


def test_stop_names_no_port_for_a_page_on_the_default_one(here, monkeypatch):
    """The page on the default port (as a run with no --port opens it): plain."""
    from judgekeeper import front
    from judgekeeper.label import DEFAULT_PORT
    from judgekeeper.start_label import Workspace

    talk = front.FrontTalk(yes=False, path=".", options={})
    assert front._continue_command(talk, Workspace(here), DEFAULT_PORT) == "judgekeeper"
    assert front._continue_command(talk, Workspace(here), 9771) == "judgekeeper --port 9771"
