"""After `check` took on a rule `fix` tested, the result says what check said under its
result: the marks helped write the rule, so it may read a few points high; on the result
page, in report.html and in Measure, right under the verdict."""

from __future__ import annotations

import html as html_mod
import re

from judgekeeper import start_label
from judgekeeper.cli import main
from judgekeeper.start_label import StartSession
from tests import test_fix as base
from tests.test_accuracy_fix import NONE_YET, WARN

here = base.here  # the fixture: a project folder


def _flat(text: str) -> str:
    return " ".join(text.split())


def _words(page: str) -> str:
    body = page[page.index("<body"):]
    body = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", body, flags=re.DOTALL)
    return _flat(html_mod.unescape(re.sub(r"<[^>]+>", " ", body)))


def test_the_result_says_the_marks_helped_write_the_rule(here, capsys):
    from tests.test_accuracy_fix import _tested_by_fix
    from tests.test_check import MARKED, _marked, _results

    ws = _marked(here)
    assert main(["--no-browser"]) == 0  # a result, and report.html
    _results(here, MARKED, rubric="Is polite, correct and short.")  # no drop: taken on
    _tested_by_fix(here, ws)
    capsys.readouterr()
    assert main(["check"]) == 0
    checked = _flat(capsys.readouterr().out)
    assert WARN in checked and NONE_YET in checked, checked
    caveat = f"{WARN} {NONE_YET}"

    report = _words(ws.report_html.read_text(encoding="utf-8"))
    page = _words(start_label.live_result(ws, StartSession(ws)))
    for words in (report, page):
        assert caveat in words, words
        verdict = words.index("Your LLM-as-a-judge")
        assert verdict < words.index(caveat) < words.index("How often"), words

    assert main(["--no-browser"]) == 0
    out = _flat(capsys.readouterr().out)
    assert caveat in out, out
    assert out.index("Result: ") < out.index(caveat) < out.index("How often"), out


def test_a_result_with_no_such_rule_says_nothing_of_it(here, capsys):
    from tests.test_check import _marked

    ws = _marked(here)
    assert main(["--no-browser"]) == 0
    assert "looked at to write" not in capsys.readouterr().out
    assert "looked at to write" not in ws.report_html.read_text(encoding="utf-8")
