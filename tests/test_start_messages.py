"""What `judgekeeper` says when finding: a judge that passes nearly everything, an Inspect
.eval log, the question code in the reference, and the judge's rule cut short.

The person's marks decide Pass and Fail; the judge's fails only decide how the answers
are picked. So a judge that passes nearly everything goes on to marking.
"""

from __future__ import annotations

import sys
import types
import zipfile

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


# A judge that fails few answers ----------------------------------------------------------


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
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("header.json", "{}")
    from judgekeeper.readers.inspect_logs import eval_header

    assert eval_header(path)["task_file"] == "quiz.py"
    assert seen == [True]


# Hints repeat the flags you gave ---------------------------------------------------------


# --no-browser and saying No --------------------------------------------------------------


# The exit code for "stopped at a question" -----------------------------------------------


def test_the_reference_lists_the_question_code():
    from tests.website_pages import ROOT

    text = (ROOT / "docs" / "reference.md").read_text(encoding="utf-8")
    assert f"| {QUESTION} | you are needed" in text
    assert "stopped at a question it cannot ask (no terminal)" in text


# Resume and small wording ----------------------------------------------------------------


def test_the_rule_is_cut_at_a_word():
    rule = ("The answer is polite, is correct for a small UK online homeware shop (no made-up "
            "promises, never reveals passwords), and gives the customer a clear next step.")
    assert start.rubric_line(rule) == ("The answer is polite, is correct for a small UK online "
                                       "homeware shop…")
    assert start.rubric_line("x" * 100) == "x" * 69 + "…"  # no word to cut at


# --review, --ask-again and --try-new-judge before a result -----------------------------------


