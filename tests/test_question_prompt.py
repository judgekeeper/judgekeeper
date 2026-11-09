"""No answers yet: when judgekeeper finds no results and no sign of an eval tool, it prints a
prompt for the person's coding agent to write test questions and save the AI's answers.
A project with an eval tool set up gets "run your eval once" instead, never the prompt."""
from __future__ import annotations

import json

import pytest

from tests.start_projects import split, table_project
from tests.test_front import assert_one_next_at_the_end, flat, run
from tests.test_uvx import UVX, by_uvx  # noqa: F401 (a fixture)

INTRO = "No answers yet? Paste this into your coding agent (Claude Code, Cursor or Codex):"
PROMPT = [
    ("Write about 20 test questions for the AI in this project, the way its real users would "
     "ask them."),
    ("Mix a few topics it should handle, a few kinds of users, and some hard cases (unclear, "
     "off-topic or tricky questions)."),
    ("Run the AI on each question and save the questions and answers in results.csv, with two "
     "columns: input (the question) and output (the answer)."),
    "Do not grade the answers. Then run {program}.",
]
KEY = "Running your AI may use your API key."
FIRST = "No answers yet?"
READS = ("judgekeeper can read results from promptfoo, DeepEval, Inspect AI, MLflow, or a CSV, "
         "TSV or JSONL file with input and output columns, and a verdict column if an "
         "LLM-as-a-judge graded them.")


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _prompt(out: str) -> list[str]:
    """What is said from "No answers yet?" to the line before Next, each of its lines whole
    again: a printed line goes on the one before it unless that one ends with "." or ":"."""
    lines = [line.rstrip() for line in out.splitlines()]
    start = next(i for i, line in enumerate(lines) if line.startswith(FIRST))
    end = next(i for i, line in enumerate(lines) if line.startswith("Next:"))
    whole: list[str] = []
    for line in lines[start:end]:
        assert len(line) <= 80, line  # wrapped as every other line
        if whole and whole[-1] and line and not whole[-1].endswith((".", ":")):
            whole[-1] += " " + line
        else:
            whole.append(line)
    return whole


def _expected(program: str = "judgekeeper") -> list[str]:
    """The intro, then each line of the prompt on a line of its own."""
    return [INTRO, "", *(line.format(program=program) for line in PROMPT), "", KEY, ""]


def test_an_empty_folder_gets_the_prompt_after_what_judgekeeper_reads(here, capsys):
    code, out, _ = run(capsys)
    assert code == 3
    assert _prompt(out) == _expected()
    assert flat(out).index(READS) < flat(out).index(FIRST)
    assert assert_one_next_at_the_end(out).startswith("Next: run your eval once")


def test_a_folder_with_files_but_no_eval_tool_gets_the_prompt(here, capsys):
    (here / "app.py").write_text("print('hello')\n", encoding="utf-8")
    (here / "README.md").write_text("# My bot\n", encoding="utf-8")
    code, out, _ = run(capsys)
    assert code == 3
    assert _prompt(out) == _expected()


@pytest.mark.usefixtures("by_uvx")
def test_the_prompt_names_judgekeeper_as_uvx_started_it(here, capsys):
    code, out, _ = run(capsys)
    assert code == 3
    assert _prompt(out) == _expected(UVX)


@pytest.mark.parametrize("file, text, said", [
    ("promptfooconfig.yaml", "description: x\n", "Found promptfoo in this folder"),
    ("requirements.txt", "deepeval\n", "Found DeepEval in this folder"),
    ("requirements.txt", "inspect-ai\n", "Found Inspect AI in this folder"),
    ("mlflow.db", "", "mlflow.db"),  # an MLflow store with nothing in it (said with or without the extra)
])
def test_an_eval_tool_with_no_results_gets_no_prompt(here, capsys, file, text, said):
    (here / file).write_text(text, encoding="utf-8")
    code, out, _ = run(capsys)
    assert code == 3
    assert said in flat(out), out
    assert FIRST not in out and "test questions" not in out, out


def test_the_promptfoo_config_keeps_its_own_save_lines(here, capsys):
    (here / "promptfooconfig.yaml").write_text("description: x\n", encoding="utf-8")
    _, out, _ = run(capsys)
    assert "promptfoo eval -o promptfoo-results.json" in out and FIRST not in out


def test_results_found_get_no_prompt(here, capsys):
    table_project(here, split(20, 16))
    code, out, err = run(capsys)
    assert code == 0, out + err
    assert FIRST not in out and "test questions" not in out


def test_saved_marks_without_their_results_get_no_prompt(here, capsys, monkeypatch):
    from judgekeeper import front

    monkeypatch.setattr(front, "_saved_marks", lambda root: 50)
    code, out, _ = run(capsys)
    assert code == 3
    assert "Your 50 marks are saved" in flat(out) and FIRST not in out


def test_a_results_file_too_big_to_look_into_gets_no_prompt(here, capsys):
    """It may hold the answers: the line that says how to read it is enough."""
    row = {"run_id": "run-0", "judge": "my-judge-v1",
           "cases": [{"case_id": f"case-{i}", "prompt": f"Question {i}?",
                      "responses": {"A": "x" * 200},
                      "scores": {"A": {"safe": {"score": 0.9, "reason": "r"}}}}
                     for i in range(600)]}
    (here / "evals.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
    code, out, _ = run(capsys)
    assert code == 3
    assert "too big to look into" in flat(out), out
    assert FIRST not in out
