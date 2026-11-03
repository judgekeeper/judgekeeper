"""`mark` on a project with fewer answers than a first result needs: the Next line says so in
the words the Find step uses, never to wait for a link that can't appear."""

from __future__ import annotations

import pytest

from judgekeeper.cli import main
from judgekeeper.start_label import StartSession, Workspace
from tests.start_projects import promptfoo_project, split
from tests.test_check import _flat


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.mark.parametrize("marked", [0, 6])
def test_mark_with_too_few_answers_says_to_run_the_eval_on_more(here, capsys, marked):
    promptfoo_project(here, split(15, 9))  # 24 answers: never 15 Pass and 15 Fail marks
    if marked:
        main(["mark", "--no-browser", "--port", "0"])
        main(["--stop"])
        session = StartSession(Workspace(here))
        for item in session.items[:marked]:
            session.update({"id": item["id"], "label": session.groups[item["id"]], "seconds": 4})
        capsys.readouterr()
    main(["mark", "--no-browser", "--port", "0"])
    said = _flat(capsys.readouterr().out)
    main(["--stop"])
    assert said.endswith("Next: mark your 24 answers on the page. Your marks are kept for when "
                         "more answers come. A first result needs at least 30 answers, so then "
                         "run your eval to make more answers (that makes model calls), and run "
                         "`judgekeeper mark --port 0 --no-browser` again."), said
    assert "See the numbers so far" not in said, said
