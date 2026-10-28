"""scripts/make_site_shots.py: the project behind the website's pictures.

The script runs judgekeeper at a terminal, as a person does, on judgekeeper's own port, so the
pages it takes show no note about a link printed for a program, and the marking page's footer
shows the command a person types. Its made-up judge disagrees with the person often enough for
a decided result: "Your LLM-as-a-judge needs work.". No Chrome here: the pages are read over HTTP.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform == "win32",
                                reason="the script runs judgekeeper under a pseudo-terminal")

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "make_site_shots.py"


@pytest.fixture(scope="module")
def shots():
    spec = importlib.util.spec_from_file_location("make_site_shots", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_judge_and_the_person_split_clearly(shots):
    pairs = [(judge, mark) for _q, _a, judge, mark, _r in shots.ANSWERS]
    assert len(pairs) == 40
    assert pairs.count(("pass", "fail")) == 10
    assert pairs.count(("fail", "pass")) == 3


def test_the_pages_are_a_persons_and_the_judge_needs_work(shots, tmp_path, monkeypatch):
    monkeypatch.delenv("BROWSER", raising=False)
    folder = tmp_path / "support-bot"
    folder.mkdir()
    shots.make_project(folder)
    start = shots.Start(folder)
    try:
        assert "--port" not in start.process.args
        items = start.get("/state")["items"]
        page = start.get("/").decode("utf-8")
        assert "judgekeeper mark --no-browser" in page
        assert "--port" not in page
        shots.mark(start, items)
        result = start.get("/result").decode("utf-8")
    finally:
        start.stop()
    assert "Your LLM-as-a-judge needs work." in result
    assert "printed with no terminal" not in result
    assert "program" not in result
