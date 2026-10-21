"""A result saved by an older judgekeeper is worked out again from the marks before it is shown:
a fix to the numbers reaches a folder measured before it. A result saved by this one is not.
The old result is the shape 1.0.0b1 left: a judge that passed every answer, 23 Pass and 17 Fail
marks, ranges of no width, `b: null` and no numbers version.
"""

from __future__ import annotations

import json
import re

import pytest

from judgekeeper import judge_setup, start, start_label
from judgekeeper.start_label import StartSession, Workspace, store_result
from tests.start_projects import promptfoo_project
from tests.test_front import run

AGAIN = "Your numbers were worked out again with this version of judgekeeper."


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _marked(here) -> Workspace:
    """40 answers the judge passed, marked 23 Pass and 17 Fail."""
    promptfoo_project(here, [True] * 40)
    found = start.find_judge(here)
    judge_setup.save(Workspace(here), judge_setup.of(found), found.metric)
    ws = start_label.prepare(found, say=lambda line: None)
    session = StartSession(ws)
    for n, item in enumerate(session.items):
        session.update({"id": item["id"], "label": "pass" if n < 23 else "fail", "seconds": 6})
    return ws


def _old(ws: Workspace) -> dict:
    """The result as an older judgekeeper saved it: no numbers version, ranges of no width."""
    r = store_result(ws, StartSession(ws))
    old = {k: v for k, v in r.items() if k != "numbers_version"}
    old.update(b=None, tpr_interval=[1.0, 1.0], tnr_interval=[0.0, 0.0],
               judgekeeper_version="1.0.0b1", made_at="2026-10-01T10:00:00Z")
    ws.result_json.write_text(json.dumps(old, indent=2) + "\n", encoding="utf-8")
    ws.report_html.write_text(start_label.result_html(old), encoding="utf-8")
    start_label._same_time(ws.report_html, ws.result_json)  # not a half-saved result
    return old


def _no_width(text: str) -> bool:
    """A range of no width, as the terminal ("between 0% and 0%") or a page ("0% and 0%")
    says it."""
    return bool(re.search(r"\b(\d+)% and \1%", text))


def test_an_old_result_is_worked_out_again_before_it_is_shown(here, capsys):
    ws = _marked(here)
    _old(ws)
    assert _no_width(ws.report_html.read_text(encoding="utf-8"))
    code, out, err = run(capsys, "--no-browser")
    assert code == 0, out + err
    assert AGAIN in " ".join(out.split())
    assert not _no_width(out)
    assert re.search(r"Pass: about 100% \(between \d\d% and 100%\)", " ".join(out.split()))
    r = json.loads(ws.result_json.read_text(encoding="utf-8"))
    assert r["numbers_version"] == start_label.NUMBERS_VERSION
    assert r["tpr_interval"][0] < 1.0 and r["tnr_interval"][1] > 0.0
    assert not _no_width(ws.report_html.read_text(encoding="utf-8"))
    saved = [json.loads(p.read_text(encoding="utf-8")) for p in ws.history.glob("result-*.json")]
    assert [s["tpr_interval"] for s in saved] == [[1.0, 1.0]]  # the old result, kept


def test_the_line_is_said_once(here, capsys):
    ws = _marked(here)
    _old(ws)
    run(capsys, "--no-browser")
    code, out, err = run(capsys, "--no-browser")
    assert code == 0, out + err
    assert AGAIN not in " ".join(out.split())


def test_a_result_saved_by_this_version_is_not_worked_out_again(here, capsys, monkeypatch):
    ws = _marked(here)
    store_result(ws, StartSession(ws))
    before = ws.result_json.read_text(encoding="utf-8")

    def no_compute(*args, **kwargs):
        raise AssertionError("worked out again")

    monkeypatch.setattr(start_label, "compute", no_compute)
    code, out, err = run(capsys, "--no-browser")
    assert code == 0, out + err
    assert AGAIN not in " ".join(out.split())
    assert ws.result_json.read_text(encoding="utf-8") == before
    assert not list(ws.history.glob("result-*.json"))


def test_a_report_drawn_again_by_fix_or_a_reason_uses_the_new_numbers(here):
    ws = _marked(here)
    _old(ws)
    start_label.write_report(ws)  # what fix, check and a reason on the page do
    assert not _no_width(ws.report_html.read_text(encoding="utf-8"))
    r = json.loads(ws.result_json.read_text(encoding="utf-8"))
    assert r["numbers_version"] == start_label.NUMBERS_VERSION
    assert len(list(ws.history.glob("result-*.json"))) == 1


def test_the_marking_page_result_uses_the_new_numbers(here):
    ws = _marked(here)
    _old(ws)
    page = start_label.live_result(ws, StartSession(ws))
    assert not _no_width(page)
