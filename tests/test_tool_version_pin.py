"""DeepEval pinned in uv.lock, its runs saved in a results folder: the version is the
project's, read the same when `check` is given a run's file as when it reads the project, so
going from one to the other never says the eval tool changed."""

from __future__ import annotations

import contextlib
import io

from judgekeeper.cli import main
from judgekeeper.start_label import StartSession, Workspace
from tests.start_projects import deepeval_project
from tests.test_fix import closed, here  # noqa: F401

LOCK = ('version = 1\n\n[[package]]\nname = "deepeval"\nversion = "4.3.2"\n\n'
        '[[package]]\nname = "x"\nversion = "0"\n')


def test_a_run_file_then_the_project_keep_the_locked_version(here, capsys):  # noqa: F811
    (here / "pyproject.toml").write_text(
        '[project]\nname = "x"\nversion = "0"\ndependencies = ["deepeval"]\n', encoding="utf-8")
    (here / "uv.lock").write_text(LOCK, encoding="utf-8")
    verdicts = [True] * 25 + [False] * 25
    deepeval_project(here, verdicts, name="deepeval-results/test_run_20261027_100000.json")
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        assert main(["--no-browser"]) == 0
        ws = Workspace(here)
        closed(ws)
        session = StartSession(ws)
        for n, item in enumerate(session.items):
            label = session.groups[item["id"]]
            if n % 5 == 0:
                label = {"pass": "fail", "fail": "pass"}[label]
            session.update({"id": item["id"], "label": label, "seconds": 5})
    newer = deepeval_project(here, [True] * 24 + [False] * 26,
                             name="deepeval-results/test_run_20261027_110000.json")
    capsys.readouterr()
    for args in (["check", str(newer.relative_to(here))], ["check"]):
        main(args)
        said = " ".join(capsys.readouterr().out.split())
        assert "eval tool changed" not in said and "version unknown" not in said, said
