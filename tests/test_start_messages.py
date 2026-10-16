"""What `judgekeeper start` says: a judge that fails few answers, hints that must work as
printed, `--no-browser` and No, the exit code for "stopped at a question", resuming, the
judge's rule cut short, choosing a judge, and `--ask-again` before any labels.

The person's marks decide Pass and Fail; the judge's fails only decide how the answers
are picked. So a judge that passes nearly everything goes on to labeling, with a note.
"""

from __future__ import annotations

import sys
import types

from judgekeeper import start
from judgekeeper.cli import main
from tests.start_projects import (
    inspect_data,
    promptfoo_project,
    split,
)

QUESTION = start.EXIT_QUESTION


def run(capsys, *argv):
    code = main([*map(str, argv)])
    out, err = capsys.readouterr()
    return code, out, err


# 1. A judge that fails few answers -------------------------------------------------------


def test_with_enough_of_both_nothing_is_said_about_the_picking(tmp_path, capsys):
    promptfoo_project(tmp_path, split(25, 15))
    _, out, _ = run(capsys, tmp_path, "--yes")
    assert "You'll see" not in out and "failed only" not in out


def test_an_eval_log_is_read_with_inspect_for_its_task_file(tmp_path, monkeypatch):
    """A .eval log is a zip archive Inspect compresses its own way: its header is read with
    inspect_ai, as the log itself is."""
    header = inspect_data(split(1, 0))["eval"]
    header["task_file"] = "quiz.py"

    class Log:
        eval = types.SimpleNamespace(model_dump=lambda mode="json": header)

    seen = []

    def read_eval_log(path, header_only=False):
        seen.append(header_only)
        return Log()

    log = types.ModuleType("inspect_ai.log")
    log.read_eval_log = read_eval_log
    monkeypatch.setitem(sys.modules, "inspect_ai", types.ModuleType("inspect_ai"))
    monkeypatch.setitem(sys.modules, "inspect_ai.log", log)
    path = tmp_path / "logs" / "2026-10-06_quiz.eval"
    path.parent.mkdir()
    path.write_bytes(b"PK\x03\x04")
    from judgekeeper.readers.inspect_logs import eval_header

    assert eval_header(path)["task_file"] == "quiz.py"
    assert seen == [True]


# 2. Hints repeat the flags you gave ------------------------------------------------------


# 3. --no-browser and saying No -----------------------------------------------------------


# 4. The exit code for "stopped at a question" --------------------------------------------


def test_the_reference_lists_the_question_code():
    from tests.website_pages import ROOT

    text = (ROOT / "docs" / "reference.md").read_text(encoding="utf-8")
    assert f"| {QUESTION} | you are needed" in text
    assert "stopped at a question it cannot ask (no terminal)" in text


# 5. Resume and small wording -------------------------------------------------------------


def test_the_rule_is_cut_at_a_word():
    rule = ("The answer is polite, is correct for a small UK online homeware shop (no made-up "
            "promises, never reveals passwords), and gives the customer a clear next step.")
    assert start.rubric_line(rule) == ("The answer is polite, is correct for a small UK online "
                                       "homeware shop…")
    assert start.rubric_line("x" * 100) == "x" * 69 + "…"  # no word to cut at


# --review, --ask-again and --try-new-judge before a result -----------------------------------


