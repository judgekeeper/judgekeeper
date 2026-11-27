"""A first run (plain `judgekeeper`) that finds only agent runs, a JSONL file of `id` and
`steps`, names `judgekeeper steps` for them. Synthetic data only."""

from __future__ import annotations

import shutil

from judgekeeper import textio
from tests.test_steps import FIXTURES
from tests.test_steps_marks import here, run  # noqa: F401


def test_a_first_run_that_finds_only_agent_runs_names_steps(here, capsys):  # noqa: F811
    shutil.copy(FIXTURES / "runs.jsonl", here / "runs.jsonl")
    code, out, err = run(capsys, "--no-browser", "--port", "0")
    said = out + err
    assert code == 3, said
    nexts = [x for x in said.splitlines() if x.startswith("Next:")]
    assert len(nexts) == 1
    assert " ".join(said.split("Next:", 1)[1].split()) == (
        "mark where each agent run in runs.jsonl first went wrong: "
        "`judgekeeper steps runs.jsonl`.")
    assert "Paste this into your coding agent" not in said


def test_a_first_run_finds_agent_runs_one_folder_down(here, capsys):  # noqa: F811
    (here / "logs").mkdir()
    shutil.copy(FIXTURES / "runs.jsonl", here / "logs" / "agent runs.jsonl")
    code, out, err = run(capsys, "--no-browser", "--port", "0")
    said = " ".join((out + err).split())
    assert code == 3
    assert ("Next: mark where each agent run in logs/agent runs.jsonl first went wrong: "
            f"`judgekeeper steps {textio.path_arg('logs/agent runs.jsonl')}`.") in said


def test_results_next_to_agent_runs_are_read_as_before(here, capsys):  # noqa: F811
    shutil.copy(FIXTURES / "runs.jsonl", here / "runs.jsonl")
    (here / "results.csv").write_text("input,output\nq1,a1\nq2,a2\n", encoding="utf-8")
    _, out, err = run(capsys, "--no-browser", "--port", "0")
    assert "agent run in" not in out + err
