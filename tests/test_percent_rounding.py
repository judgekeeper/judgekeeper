"""A percentage rounds half up on the exact fraction it shows (23 of 40 is 58%, not the 57% a
float's 57.4999 gives), the same in every place one is shown."""

from __future__ import annotations

import json

import pytest

from judgekeeper import check, front, no_grades, report_page, start_label
from judgekeeper.textio import percent
from tests.test_answers_without_grades import _seen, mark, write_answers
from tests.test_front import flat, run


@pytest.mark.parametrize("x, places, shown", [
    (23 / 40, 0, "58%"), (39 / 40, 0, "98%"), (17 / 40, 0, "43%"), (0.5749, 0, "57%"),
    (1 / 3, 0, "33%"), (2 / 3, 0, "67%"), (0, 0, "0%"), (1, 0, "100%"),
    (0.12345, 1, "12.3%"), (1 / 8, 1, "12.5%"), (0.99125, 2, "99.13%"), (0.0005, 1, "0.1%")])
def test_half_up_on_the_exact_fraction(x, places, shown):
    assert percent(x, places) == shown


@pytest.mark.parametrize("pct", [check._pct, front._pct, start_label._pct, report_page._pct])
def test_every_place_uses_it(pct):
    assert pct(23 / 40) == "58%" and pct(17 / 40) == "43%"


def test_share_on_the_result_rounds_half_up():
    assert report_page.share(23 / 40) == "58%"
    assert report_page.share(39 / 40) == "98%"


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_23_of_40_passed_reads_about_58(here, capsys, pages):
    write_answers(here, 40)
    run(capsys, "--no-browser")
    mark(here, ["pass"] * 23 + ["fail"] * 17)
    code, out, err = run(capsys, "--no-browser")
    assert code == 0, out + err
    assert "You passed 23 of 40 answers." in flat(out)
    ws = start_label.Workspace(here)
    result = json.loads(ws.result_json.read_text(encoding="utf-8"))
    assert no_grades.rate_words(result).startswith("about 58%, between")
    page = " ".join(_seen(ws.report_html.read_text(encoding="utf-8")).split())
    assert "about 58%" in page and "about 57%" not in page
