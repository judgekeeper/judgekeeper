"""A mark can always be changed: with every answer marked, `judgekeeper mark` opens the marking
page (not a stop), a mark changed there makes the result again, and the result page links back
to the list."""

from __future__ import annotations

import json
import urllib.request

import pytest

from judgekeeper import start_label
from judgekeeper.cli import main
from tests.start_projects import promptfoo_project, split
from tests.test_front import assert_one_next_at_the_end
from tests.test_mark import _click
from tests.test_reasons import _post

NEXT_ALL_MARKED = ("Next: run your eval on more questions, then run `judgekeeper mark`: the new "
                   "answers join the ones you marked.")


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _get(url: str) -> str:
    with urllib.request.urlopen(url, timeout=5) as resp:
        return resp.read().decode("utf-8")


def _result(ws) -> dict:
    return json.loads(ws.result_json.read_text(encoding="utf-8"))


def test_every_answer_marked_mark_opens_the_list_and_a_changed_mark_counts(
        here, capsys, pages, no_browser):
    promptfoo_project(here, split(20, 16))
    assert main(["mark", "--port", "0"]) == 0
    main(["--stop"])
    ws = start_label.Workspace(here)
    _click(ws)  # every answer, as the LLM-as-a-judge did
    assert main(["--port", "0"]) == 0  # the result
    main(["--stop"])
    assert _result(ws)["disagreements"] == 0
    capsys.readouterr()
    no_browser.clear()
    code = main(["mark", "--port", "0"])
    out = capsys.readouterr().out
    assert code == 0, out
    flat = " ".join(out.split())
    assert "You have marked all 36 answers.\n" in out, out
    assert ("The marking page is open in your browser. To change a mark, click it in the "
            "list.") in flat, out
    assert assert_one_next_at_the_end(out) == NEXT_ALL_MARKED
    url = no_browser[-1]
    assert "/result" not in url, url
    state = json.loads(_get(url.replace("/?", "/state?")))
    item = state["items"][-1]
    other = "fail" if item["label"] == "pass" else "pass"
    assert _post(url, {"id": item["id"], "label": other, "seconds": 4}) == 200
    page = _get(url.replace("/?", "/result?"))
    assert _result(ws)["disagreements"] == 1
    assert "Change a mark</a>: click it in the list and mark it again." in page
    main(["--stop"])


CHANGE_NO_BROWSER = "To change a mark, click it in the list."  # under the link printed
CHANGE_ON_RESULT = 'To change a mark, open the page and click "Change a mark".'


def _all_marked(here, disagree: int = 0):
    promptfoo_project(here, split(20, 16))
    assert main(["mark", "--port", "0"]) == 0
    main(["--stop"])
    ws = start_label.Workspace(here)
    _click(ws)  # every answer, as the LLM-as-a-judge did; then `disagree` turned
    session = start_label.StartSession(ws)
    turned = []  # as many Pass marks turned as Fail ones: each kind keeps enough for a result
    for kind in ("pass", "fail"):
        turned += [i for i in session.items if i["label"] == kind][:disagree // 2]
    for item in turned:
        other = "fail" if item["label"] == "pass" else "pass"
        session.update({"id": item["id"], "label": other, "seconds": 7})
    return ws


def test_mark_with_no_browser_and_every_answer_marked_says_how_to_change_one(
        here, capsys, pages, no_browser):
    _all_marked(here)
    capsys.readouterr()
    code = main(["mark", "--port", "0", "--no-browser"])
    out = capsys.readouterr().out
    main(["--stop"])
    assert code == 0, out
    assert CHANGE_NO_BROWSER in " ".join(out.split()), out


@pytest.mark.parametrize("flags", [[], ["--no-browser"]])
def test_mark_at_the_result_page_says_how_to_change_a_mark(here, capsys, pages, no_browser,
                                                           flags):
    """With disagreements to say why on, `mark` opens the result page: it says how to change
    a mark there too, with a browser or without."""
    _all_marked(here, disagree=2)
    capsys.readouterr()
    code = main(["mark", "--port", "0", *flags])
    out = capsys.readouterr().out
    main(["--stop"])
    assert code == 0, out
    flat = " ".join(out.split())
    assert "Say why on the answers" in flat, out
    assert CHANGE_ON_RESULT in flat, out


def test_z_after_a_changed_mark_puts_the_old_mark_back_and_every_step_stays(
        here, capsys, pages, no_browser):
    """Pass, changed to Fail, then Z: the page sends the earlier mark, an ordinary mark line
    (older reads take it as any mark); the result counts Pass again, and marks.jsonl keeps
    all three steps."""
    from judgekeeper import marks

    ws = _all_marked(here)
    capsys.readouterr()
    no_browser.clear()
    assert main(["mark", "--port", "0"]) == 0
    url = no_browser[-1]
    state = json.loads(_get(url.replace("/?", "/state?")))
    item = next(i for i in state["items"] if i["label"] == "pass")
    assert _post(url, {"id": item["id"], "label": "fail", "seconds": 4}) == 200
    _get(url.replace("/?", "/result?"))
    assert _result(ws)["disagreements"] == 1
    assert _post(url, {"id": item["id"], "label": "pass", "deferred": False,
                       "seconds": 2}) == 200  # Z, as the page sends it
    _get(url.replace("/?", "/result?"))
    assert _result(ws)["disagreements"] == 0
    main(["--stop"])
    m = marks.read(ws.marks)
    assert m.last[item["id"]]["mark"] == "pass"
    assert item["id"] not in m.after_result  # back to the mark it had: no change counted
    lines = [json.loads(x) for x in ws.marks.read_text(encoding="utf-8").splitlines()[1:]]
    steps = [x for x in lines if x.get("id") == item["id"]]
    assert [x["mark"] for x in steps] == ["pass", "fail", "pass"]
    usual = set(steps[0])
    assert all(set(x) - {"after_result"} <= usual for x in steps), steps
