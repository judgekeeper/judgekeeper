"""Fixes from the security reviews (the stranger test and the scenario test on 1.0).

- A page opened by the program named in BROWSER stamps its marks, and the result says so
  once; the docs never say the marks are the person's.
No test calls an AI API.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from judgekeeper import marks, start_label
from tests.start_projects import promptfoo_project, split
from tests.test_front import run
from tests.test_loop import _click, _flat, _post_marks

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


# 1. A page opened by the program named in BROWSER --------------------------------------------

BROWSER_LINE = ("{n} of your marks came through a page opened by the program named in BROWSER, "
                "so a program could have made them. If you marked them yourself, nothing to do.")


def _lines(ws) -> list[dict]:
    return [json.loads(x) for x in ws.marks.read_text(encoding="utf-8").splitlines()[1:]]


def test_a_page_opened_through_browser_stamps_its_marks(here, capsys, no_browser, monkeypatch):
    monkeypatch.setenv("BROWSER", "/usr/local/bin/save-the-link %s")
    promptfoo_project(here, split(20, 16))
    code, out, _ = run(capsys)
    assert code == 0, out
    ws = start_label.Workspace(here)
    assert _post_marks(no_browser[-1], ws, 36) == 36
    assert all(x["link"] == "browser-env" for x in _lines(ws))
    code, out, _ = run(capsys)
    assert code == 0, out
    assert _flat(out).count(BROWSER_LINE.format(n=36)) == 1  # once per Measure
    report = ws.report_html.read_text(encoding="utf-8")
    assert report.count(BROWSER_LINE.format(n=36)) == 1


def test_without_browser_set_nothing_is_stamped(here, capsys, no_browser, monkeypatch):
    monkeypatch.delenv("BROWSER", raising=False)
    promptfoo_project(here, split(20, 16))
    run(capsys)
    ws = start_label.Workspace(here)
    _post_marks(no_browser[-1], ws, 36)
    assert not any("link" in x for x in _lines(ws))
    _, out, _ = run(capsys)
    assert "named in BROWSER" not in out
    assert "named in BROWSER" not in ws.report_html.read_text(encoding="utf-8")


def test_marks_mostly_under_a_second_look_like_a_program():
    made = {"marks": 40, "pass": 20, "fail": 20, "sittings": 1, "seconds": 0,
            "under_second": 30, "not_counted": 0, "printed": 0, "browser_env": 0}
    said = start_label.made_lines(made)
    assert ("30 of your marks took under a second each. A result is only as good as the marks. "
            "This looks like a program, not a person.") in said
    made["under_second"] = 15  # more than a quarter, not more than half
    assert ("15 of your marks took under a second each. A result is only as good as the "
            "marks.") in start_label.made_lines(made)


def test_the_docs_never_say_the_marks_are_yours():
    said = ("The page accepts marks only from itself, so another website can't send marks. A "
            "program on your computer could, the same way it could edit your files.")
    for name in ("docs/reference.md", "CHANGELOG.md", "SECURITY.md"):
        text = " ".join((ROOT / name).read_text(encoding="utf-8").split())
        assert "so the marks are yours" not in text, name
        assert said in text, name
    assert "so the marks are yours" not in (ROOT / "website" / "reference.html").read_text(
        encoding="utf-8")


def test_a_kept_page_is_stamped_too(here, capsys, no_browser, monkeypatch):
    """The page still open from the run before, opened again through BROWSER."""
    promptfoo_project(here, split(20, 16))
    run(capsys)
    ws = start_label.Workspace(here)
    _click(ws, n=2)
    monkeypatch.setenv("BROWSER", "save-the-link")
    run(capsys, "mark")
    _post_marks(no_browser[-1], ws, 4)
    assert [x.get("link") for x in _lines(ws)][-2:] == ["browser-env", "browser-env"]
    assert marks.made(marks.read(ws.marks))["browser_env"] >= 2
