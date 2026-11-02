"""Every line judgekeeper says in its own words wraps at the same width (textio.WIDTH): the
check's result and its group lines, and Measure's two estimates."""

from __future__ import annotations

from judgekeeper import textio
from judgekeeper.cli import main
from tests import test_fix as base

here = base.here  # the fixture: a project folder

LONG = ("Result: no drop", "On answers you", "When you say", "On marks made after")


def _long(out: str) -> list[str]:
    return [x for x in out.splitlines() if len(x) > textio.WIDTH and "`" not in x
            and x.strip().startswith(LONG)]


def test_the_check_lines_wrap_at_the_same_width(here, capsys):
    from tests.test_check import MARKED, _marked, _results

    _marked(here)
    _results(here, MARKED, rubric="Is polite, correct and short.")
    capsys.readouterr()
    main(["check"])
    out = capsys.readouterr().out
    assert "Result: no drop bigger than" in out, out
    assert "On answers you pass" in " ".join(out.split()), out
    assert _long(out) == [], out


def test_the_estimates_wrap_at_the_same_width(tmp_path, monkeypatch, capsys):
    from judgekeeper import start, start_label
    from judgekeeper.start_label import StartSession
    from tests.start_projects import split, table_project

    monkeypatch.chdir(tmp_path)
    table_project(tmp_path, split(300, 300))
    ws = start_label.prepare(start.find_judge(tmp_path), say=lambda line: None)
    session = StartSession(ws)
    groups = {q["id"]: q["group"] for q in ws.data()["queue"]}
    for n, item in enumerate(session.items[:80]):
        wrong = n % 9 == 0
        mark = groups[item["id"]] if not wrong else {"pass": "fail", "fail": "pass"}[
            groups[item["id"]]]
        session.update({"id": item["id"], "label": mark, "seconds": 4})
    assert main(["--no-browser"]) == 0
    out = capsys.readouterr().out
    assert "When you say Pass, it also says Pass: about" in " ".join(out.split()), out
    assert _long(out) == [], out
