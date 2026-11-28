"""A steps tab left open while the runs change (the runs file rewritten, or another runs file,
then `judgekeeper steps` again on the same link) never saves a mark for steps the person did
not see: each run the page gets carries its steps' hash, the page sends it back with each mark
and Undo, and a hash that is not the run's now, or a run the page no longer has, is refused
with a 409 that loads the tab again. The page that opens then says so until a mark is saved."""

from __future__ import annotations

import json

import pytest

from judgekeeper import redact
from judgekeeper.cli import main
from tests.test_page_kind_switch import _lines, _open, _post
from tests.test_steps_page_script import _data
from tests.test_steps_page_script import _run as steps_script

IDS = [f"r{i}" for i in range(1, 7)]
CHANGED_LINE = "Your last mark was not saved: the runs changed, so this page loaded them again."
MARKS = ".judgekeeper/steps/marks.jsonl"


def _runs(word: str) -> str:
    return "".join(json.dumps({"id": i, "task": f"{word} task {i}", "steps": [
        {"role": "user", "content": f"{word} q {i}"},
        {"role": "assistant", "content": f"{word} a {i}"},
        {"role": "assistant", "content": f"{word} b {i}"}]}) + "\n" for i in IDS)


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "runs.jsonl").write_text(_runs("ALPHA"), encoding="utf-8")
    (tmp_path / "runsB.jsonl").write_text(_runs("BRAVO"), encoding="utf-8")
    return tmp_path


def _state(link: str) -> dict:
    from urllib.request import Request, urlopen

    base, token = link.split("/?")[0], link.split("token=")[1]
    request = Request(f"{base}/state?token={token}", headers={"Host": base.split("//")[1]})
    with urlopen(request, timeout=5) as r:
        return json.loads(r.read())


def _shown(link: str, run_id: str) -> dict:
    """The run as the page got it: its key and the steps' hash it carries."""
    key = redact.item_key(run_id)
    (run,) = [r for r in _state(link)["runs"] if r["id"] == key]
    return run


def _r4_lines(here) -> list[dict]:
    return [x for x in _lines(here / MARKS) if x.get("id") == "r4"]


@pytest.mark.parametrize("again", [("steps", "runs.jsonl"), ("steps", "runsB.jsonl")],
                         ids=["rewritten-in-place", "another-runs-file"])
def test_a_mark_for_steps_the_page_no_longer_has_is_refused_and_loads_the_tab_again(
        here, capsys, pages, again):
    link = _open(capsys, "steps", "runs.jsonl")
    seen = _shown(link, "r4")
    if again[1] == "runs.jsonl":
        (here / "runs.jsonl").write_text(_runs("BRAVO"), encoding="utf-8")
    link = _open(capsys, *again)  # the page starts again (from a terminal, on the same port)
    status, body = _post(link, {"id": seen["id"], "first_wrong_step": 3, "was": None,
                                "seconds": 2, "steps_hash": seen["steps_hash"]})
    main(["steps", "--stop"])
    assert status == 409 and body["reload"] is True and body["changed"] is True, body
    assert _r4_lines(here) == []


def test_an_undo_for_steps_the_page_no_longer_has_is_refused_too(here, capsys, pages):
    link = _open(capsys, "steps", "runs.jsonl")
    seen = _shown(link, "r4")
    status, _ = _post(link, {"id": seen["id"], "first_wrong_step": 2, "was": None, "seconds": 2,
                             "steps_hash": seen["steps_hash"]})
    assert status == 200
    (here / "runs.jsonl").write_text(_runs("BRAVO"), encoding="utf-8")
    link = _open(capsys, "steps", "runs.jsonl")
    status, body = _post(link, {"id": seen["id"], "first_wrong_step": None, "was": 2,
                                "seconds": 2, "steps_hash": seen["steps_hash"]})
    main(["steps", "--stop"])
    assert status == 409 and body.get("reload") is True and body.get("changed") is True, body
    assert [x["first_wrong_step"] for x in _r4_lines(here)] == [2]


def test_a_mark_with_the_steps_the_page_shows_still_saves(here, capsys, pages):
    link = _open(capsys, "steps", "runs.jsonl")
    seen = _shown(link, "r4")
    status, body = _post(link, {"id": seen["id"], "first_wrong_step": 3, "was": None,
                                "seconds": 2, "steps_hash": seen["steps_hash"]})
    main(["steps", "--stop"])
    assert status == 200, body
    assert [(x["first_wrong_step"], x["steps_hash"]) for x in _r4_lines(here)] == [
        (3, seen["steps_hash"])]


# The page ---------------------------------------------------------------------------------
def _hashed() -> dict:
    data = _data()
    for k, run in enumerate(data["runs"]):
        run["steps_hash"] = f"hash-{k}"
    return data


def test_the_page_sends_the_hash_of_the_steps_it_shows_with_a_mark_and_an_undo():
    got = steps_script("""
      later(300); key("2"); key("Enter"); await settled();
      later(300); key("z"); await settled();
      console.log(JSON.stringify(sent.map(function (s) { return s.body.steps_hash; })));""",
        _hashed())
    assert got == ["hash-0", "hash-0"]


def test_a_tab_told_the_runs_changed_opens_its_link_saying_so():
    got = steps_script("""
      answer = function () { return Promise.resolve({ok: false, status: 409, json: function () {
        return Promise.resolve({error: "x", stale: true, reload: true, changed: true}); }}); };
      REFRESHED = null;
      later(300); key("2"); key("Enter"); await settled();
      console.log(JSON.stringify({reloads: reloads, href: window.location.href}));""",
        _hashed())
    assert got == {"reloads": 0, "href": "/?token=t0k&changed=1"}


def test_the_steps_page_opened_so_says_the_runs_changed_until_a_mark_is_saved():
    got = steps_script("""
      var first = ids["status"].textContent;
      later(300); key("1"); key("Enter"); await settled();
      console.log(JSON.stringify({first: first, replaced: replaced,
                                  after: ids["status"].textContent}));""", _hashed(),
        before="""
      var replaced = [];
      window.location.search = "?token=t0k&changed=1";
      window.location.pathname = "/";
      window.history = {replaceState: function (s, t, u) { replaced.push(u); }};
    """)
    assert got == {"first": CHANGED_LINE, "replaced": ["/?token=t0k"], "after": ""}


# Runs under other ids: the page's key names no run the page has now ------------------------
OTHER_IDS = [f"b-{i}" for i in range(1, 7)]


def _other_runs() -> str:
    return "".join(json.dumps({"id": i, "task": f"BRAVO task {i}", "steps": [
        {"role": "user", "content": f"BRAVO q {i}"},
        {"role": "assistant", "content": f"BRAVO a {i}"},
        {"role": "assistant", "content": f"BRAVO b {i}"}]}) + "\n" for i in OTHER_IDS)


@pytest.mark.parametrize("undo", [False, True], ids=["mark", "undo"])
def test_a_step_mark_for_a_run_the_page_no_longer_has_loads_the_tab_again(
        here, capsys, pages, undo):
    (here / "runsC.jsonl").write_text(_other_runs(), encoding="utf-8")
    link = _open(capsys, "steps", "runs.jsonl")
    seen = _shown(link, "r4")
    if undo:
        assert _post(link, {"id": seen["id"], "first_wrong_step": 2, "was": None,
                            "seconds": 2, "steps_hash": seen["steps_hash"]})[0] == 200
    link = _open(capsys, "steps", "runsC.jsonl")  # other ids, the same page
    status, body = _post(link, {"id": seen["id"], "first_wrong_step": None if undo else 3,
                                "was": 2 if undo else None, "seconds": 2,
                                "steps_hash": seen["steps_hash"]})
    main(["steps", "--stop"])
    assert status == 409 and body.get("reload") is True and body.get("changed") is True, body
    assert [x["first_wrong_step"] for x in _r4_lines(here)] == ([2] if undo else [])


def test_an_id_sent_without_the_steps_hash_is_still_not_found(here, capsys, pages):
    link = _open(capsys, "steps", "runs.jsonl")
    status, body = _post(link, {"id": "nope", "first_wrong_step": 1, "was": None,
                                "seconds": 2})
    main(["steps", "--stop"])
    assert status == 404 and body == {"error": "no item with that id"}
