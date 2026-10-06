"""Judge results saved in a project's own format: `start` names a file that looks like them,
and never sends the user to run an eval that would save nothing it can read."""

from __future__ import annotations

import json
import os
import time

import pytest

from judgekeeper import own_format
from judgekeeper.cli import main
from tests.start_projects import own_format_project, promptfoo_project, split


def run(capsys, *argv):
    code = main(["start", *map(str, argv)])
    out, err = capsys.readouterr()
    return code, out, err


# Spotting the file ---------------------------------------------------------------------------

def test_a_nested_jsonl_of_scores_is_spotted(tmp_path):
    own_format_project(tmp_path)
    found = own_format.search(tmp_path)
    assert found is not None and found.rel == "data/prompt_evals.jsonl"


@pytest.mark.parametrize("value, judged", [
    ({"input": "q", "output": "a", "score": 1}, True),
    ({"prompt": "q", "response": "a", "verdict": "pass"}, True),
    ({"Question": "q", "Answer": "a", "Passed": True}, True),
    ({"runs": [{"cases": [{"user_input": "q", "actual_output": "a", "label": 1}]}]}, True),
    ({"input": "q", "output": "a"}, False),  # no score
    ({"label": "prod", "timeout": 3}, False),  # a setting called label
    ({"name": "app", "version": "1.0", "scripts": {"test": "pytest"}}, False),
    ([1, 2, 3], False),
    ("text", False),
])
def test_what_looks_like_judge_results(value, judged):
    assert own_format.looks_judged(value) is judged


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_unrelated_json_is_no_false_alarm(tmp_path):
    _write(tmp_path / "package.json", json.dumps({"name": "x", "scripts": {"test": "jest"}}))
    _write(tmp_path / "config" / "settings.json", json.dumps({"label": "prod", "retries": 3}))
    _write(tmp_path / "data" / "questions.jsonl",
           json.dumps({"input": "q", "output": "a"}) + "\n")
    _write(tmp_path / "data" / "notes.csv", "title,body\nA,B\n")
    assert own_format.search(tmp_path) is None


def test_a_csv_with_score_columns_is_spotted(tmp_path):
    _write(tmp_path / "out" / "judged.csv", "prompt,response,score\nq,a,0.4\n")
    assert own_format.search(tmp_path).rel == "out/judged.csv"


def test_an_old_file_is_not_named(tmp_path):
    path = own_format_project(tmp_path)
    old = time.time() - 120 * 86400
    os.utime(path, (old, old))
    assert own_format.search(tmp_path) is None


def test_files_in_skipped_folders_and_deep_down_are_not_read(tmp_path):
    line = json.dumps({"input": "q", "output": "a", "score": 1}) + "\n"
    _write(tmp_path / "node_modules" / "pkg" / "x.jsonl", line)
    _write(tmp_path / ".venv" / "x.jsonl", line)
    _write(tmp_path / "a" / "b" / "c" / "d" / "e" / "x.jsonl", line)
    assert own_format.search(tmp_path) is None


def test_results_judgekeeper_reads_already_are_not_named(tmp_path):
    promptfoo_project(tmp_path, split(3, 3))
    assert own_format.search(tmp_path) is None


def test_the_most_recently_changed_file_is_named(tmp_path):
    line = json.dumps({"input": "q", "output": "a", "score": 1}) + "\n"
    _write(tmp_path / "older.jsonl", line)
    _write(tmp_path / "newer.jsonl", line)
    now = time.time()
    os.utime(tmp_path / "older.jsonl", (now - 3600, now - 3600))
    assert own_format.search(tmp_path).rel == "newer.jsonl"


# What start says ------------------------------------------------------------------------------

def test_start_names_the_file_and_prints_the_prompt(tmp_path, capsys):
    own_format_project(tmp_path)
    code, out, _ = run(capsys, tmp_path)
    assert code == 2
    assert "data/prompt_evals.jsonl looks like saved judge results in your own format." in out
    assert ("To use it: turn it into a table with input, output and verdict columns (see "
            "www.judgekeeper.com/start.html#own-format), or ask your coding agent with the "
            "prompt below.") in out
    assert own_format.AGENT_PROMPT in out
    assert out.index("looks like saved judge results") < out.index("To use it") < \
        out.index(own_format.AGENT_PROMPT)


def test_deepeval_says_measure_saves_nothing_and_never_run_your_eval_again(tmp_path, capsys):
    own_format_project(tmp_path)
    _, out, _ = run(capsys, tmp_path)
    assert ("DeepEval is used here (requirements.txt), but DeepEval saves results only when "
            "your tests run through deepeval test run or evaluate(); calling a metric's "
            "measure() directly saves nothing.") in out
    assert "run your eval" not in out.lower()


def test_deepeval_without_an_own_file_still_gives_the_prompt(tmp_path, capsys):
    _write(tmp_path / "requirements.txt", "deepeval\n")
    code, out, _ = run(capsys, tmp_path)
    assert code == 2 and "run your eval" not in out.lower()
    assert ("If your judge saves its results in a format of its own: turn them into a table "
            "with input, output and verdict columns (see "
            "www.judgekeeper.com/start.html#own-format), or ask your coding agent with the "
            "prompt below.") in out
    assert own_format.AGENT_PROMPT in out


def test_inspect_still_says_to_run_the_eval(tmp_path, capsys):
    _write(tmp_path / "requirements.txt", "inspect-ai\n")
    _, out, _ = run(capsys, tmp_path)
    assert ("Inspect AI is used here (requirements.txt), but it has no saved logs in this "
            "folder yet. Run your eval (inspect eval saves its logs in logs/), then run "
            "judgekeeper start again.") in out


def test_an_empty_folder_prints_no_prompt(tmp_path, capsys):
    code, out, _ = run(capsys, tmp_path)
    assert code == 2 and "No saved eval results found" in out
    assert own_format.AGENT_PROMPT not in out


def test_the_agent_prompt_flag(tmp_path, capsys):
    code, out, _ = run(capsys, tmp_path / "not-there", "--agent-prompt")
    assert code == 0 and out == own_format.AGENT_PROMPT + "\n"


def test_the_agent_prompt_installs_inside_the_project_only():
    text = own_format.AGENT_PROMPT
    assert "this project's own Python environment" in text
    for outside in ("pipx", "uv tool", "uvx", "pip3 install", "--user", "-g "):
        assert outside not in text
    for column in ("id, input, output, verdict and reason", "judge_model", "pass or fail",
                   "never send the data anywhere", "judgekeeper start <the CSV file>"):
        assert column in text
