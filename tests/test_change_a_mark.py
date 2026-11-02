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
