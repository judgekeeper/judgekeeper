"""One folder, two kinds of marking page: `judgekeeper steps` and then plain `judgekeeper` (or
the other way round) start the page again for the new command, with the same token. A tab
still showing the other kind sends its marks to the new page: each is refused with a 409 that
makes the tab load again, never answered 200 and dropped. Runs and answers have the same ids,
so the key the tab sends is one the new page knows."""

from __future__ import annotations

import json
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from judgekeeper import label, redact
from judgekeeper.cli import main
from tests.page_http import retried
from tests.test_mark_page_script import _run as answers_script
from tests.test_steps_page_script import _run as steps_script

IDS = [f"r{i}" for i in range(40)]


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runs = [{"id": i, "task": f"Task {i}", "steps": [{"role": "user", "content": f"Ask {i}"},
                                                     {"role": "assistant", "content": f"Do {i}"}]}
            for i in IDS]
    answers = [{"id": i, "input": f"What is question {i}?", "output": f"Answer {i}.",
                "verdict": "pass" if k % 2 else "fail"} for k, i in enumerate(IDS)]
    for name, rows in (("runs.jsonl", runs), ("answers.jsonl", answers)):
        (tmp_path / name).write_text("".join(json.dumps(r) + "\n" for r in rows),
                                     encoding="utf-8")
    return tmp_path


def _open(capsys, *argv) -> str:
    """Run judgekeeper with --no-browser --port 0; the link it printed."""
    main([*argv, "--no-browser", "--port", "0"])
    out = capsys.readouterr().out
    links = [x.strip() for x in out.splitlines() if x.strip().startswith("http://127.0.0.1:")]
    assert links, out
    return links[-1]


def _post(link: str, body: dict) -> tuple[int, dict]:
    base, token = link.split("/?")[0].split("/result")[0], link.split("token=")[1]
    request = Request(f"{base}/label?token={token}", data=json.dumps(body).encode("utf-8"),
                      method="POST", headers={"Content-Type": "application/json",
                                              "Origin": base, "Host": base.split("//")[1]})

    def send():
        try:
            with urlopen(request, timeout=5) as r:
                return r.status, json.loads(r.read())
        except HTTPError as e:
            return e.code, json.loads(e.read())

    return retried(send)


def _lines(path) -> list[dict]:
    if not path.is_file():
        return []
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


STEPS_MARKS = ".judgekeeper/steps/marks.jsonl"
ANSWERS_MARKS = ".judgekeeper/marks.jsonl"


def test_a_steps_mark_sent_to_the_answers_page_is_refused_and_loads_the_tab_again(
        here, capsys, pages):
    _open(capsys, "steps", "runs.jsonl")
    link = _open(capsys, "answers.jsonl")  # the page starts again, now for the answers
    status, body = _post(link, {"id": redact.item_key("r1"), "first_wrong_step": 1,
                                "was": None, "seconds": 2.5})
    main(["--stop"])
    assert status == 409 and body["stale"] is True and body["reload"] is True, body
    assert body["error"] == label.OTHER_PAGE
    assert not (here / STEPS_MARKS).exists()
    assert [x for x in _lines(here / ANSWERS_MARKS) if x.get("id") == "r1"] == []


def test_an_answers_mark_sent_to_the_steps_page_is_refused_and_loads_the_tab_again(
        here, capsys, pages):
    _open(capsys, "answers.jsonl")
    link = _open(capsys, "steps", "runs.jsonl")
    status, body = _post(link, {"id": redact.item_key("r1"), "label": "pass", "was": None,
                                "seconds": 2.5})
    main(["steps", "--stop"])
    assert status == 409 and body["stale"] is True and body["reload"] is True, body
    assert body["error"] == label.OTHER_PAGE
    assert [x for x in _lines(here / STEPS_MARKS) if x.get("id") == "r1"] == []


@pytest.mark.parametrize("body", [
    {"label": "pass"},  # a mark
    {"label": None, "deferred": False},  # Undo
    {"deferred": True},  # Skip
])
def test_the_answers_page_still_takes_its_own_changes(here, capsys, pages, body):
    link = _open(capsys, "answers.jsonl")
    status, reply = _post(link, {"id": redact.item_key("r1"), **body, "seconds": 2.5})
    main(["--stop"])
    assert status == 200, reply


def test_the_steps_page_still_takes_a_mark_and_an_undo(here, capsys, pages):
    link = _open(capsys, "steps", "runs.jsonl")
    marked = _post(link, {"id": redact.item_key("r1"), "first_wrong_step": 2, "was": None,
                          "seconds": 2})
    undone = _post(link, {"id": redact.item_key("r1"), "first_wrong_step": None, "was": 2,
                          "seconds": 2})
    main(["steps", "--stop"])
    assert marked[0] == 200 and undone[0] == 200, (marked, undone)
    assert [x["first_wrong_step"] for x in _lines(here / STEPS_MARKS) if x.get("id") == "r1"] \
        == [2, None]


RELOAD = """
  answer = function () { return Promise.resolve({ok: false, status: 409, json: function () {
    return Promise.resolve({error: "x", stale: true, reload: true}); }}); };
"""


def test_a_steps_tab_told_to_reload_loads_again_and_asks_for_no_list():
    got = steps_script(RELOAD + """
      REFRESHED = null;
      later(300); key("2"); key("Enter"); await settled();
      console.log(JSON.stringify({reloads: reloads, sent: sent.length}));""")
    assert got == {"reloads": 1, "sent": 1}


def test_an_answers_tab_told_to_reload_loads_again_and_asks_for_no_list():
    got = answers_script("""
      var asked = 0;
      fetch = function (url, opts) {
        if (url.indexOf("/state") > -1) { asked += 1; }
        if (opts && opts.body) { sent.push({url: url, body: JSON.parse(opts.body)}); }
        return Promise.resolve({ok: false, status: 409, json: function () {
          return Promise.resolve({error: "x", stale: true, reload: true}); }});
      };
      key("ArrowLeft"); for (var n = 0; n < 6; n++) { await settle(); }
      console.log(JSON.stringify({reloads: reloads, asked: asked, sent: sent.length}));""")
    assert got == {"reloads": 1, "asked": 0, "sent": 1}
