"""`fix` and `check` with answers and no grades exit 3 every time, with failed-answers.md or
without it (every answer you can see passed)."""

from __future__ import annotations

import pytest

from judgekeeper import start_label
from tests.test_fixed_and_broke import Project, here, project  # noqa: F401
from tests.test_front import flat, run

NO_JUDGE = "Your answers have no grades, so there is no LLM-as-a-judge to {what}."


@pytest.mark.parametrize("fails", [set(), {0, 1, 2, 3, 4, 5}])
@pytest.mark.parametrize(("command", "what"), [("fix", "fix"), ("check", "re-check")])
def test_fix_and_check_with_no_judge_exit_3(project, fails, command, what):  # noqa: F811
    project.first(fails=fails, n=20)
    failed = start_label.Workspace(project.here).dir / "fix" / "failed-answers.md"
    assert failed.is_file() == bool(fails)
    code, out, err = run(project.capsys, command)
    assert code == 3, out + err
    assert NO_JUDGE.format(what=what) in flat(out + err), out + err
