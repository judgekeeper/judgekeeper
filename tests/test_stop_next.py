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
