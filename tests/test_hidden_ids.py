"""Ids with hidden characters (zero-width, right-to-left, ESC, NUL). The page's text is cleaned
of them (redact.visible), so the page never gets an id: it gets a key made from it
(redact.item_key), and a mark is saved under the exact id of the file."""

from __future__ import annotations

import json

import pytest

from judgekeeper import redact, steps, steps_page
from judgekeeper.start_label import Workspace
from tests.test_steps_page import _lines, serve  # noqa: F401 - serve is a fixture

HIDDEN = {"zero-width": "zw\u200bspace", "right-to-left": "rtl\u202eabc",
          "ESC": "esc\x1b[31m", "NUL": "nul\x00x"}
FAKE_KEY = "sk-ant-api03-" + "Q" * 80


def _runs(tmp_path, ids, name="runs.jsonl"):
    """One run per id; its task says which one it is (the page never gets the id)."""
    path = tmp_path / name
    path.write_text("".join(json.dumps({"id": run_id, "task": f"Task {n}", "steps": [
        {"role": "user", "content": f"Question {n}"},
        {"role": "assistant", "content": f"Answer {n}"}]}) + "\n"
        for n, run_id in enumerate(ids)), encoding="utf-8")
    return path


def _keys(client) -> dict[str, str]:
    """Task -> the key the page has for that run."""
    return {run["task"]: run["id"] for run in client.request_json("/state")["runs"]}


def _post(client, key, step):
    """A mark as the page sends it: the key the page got from /state."""
    resp, payload = client.request("POST", "/label", {"id": key, "first_wrong_step": step,
                                                      "was": None, "seconds": 1})
    return resp.status, json.loads(payload)


def _get(client, path):
    resp, payload = client.request("GET", path)
    assert resp.status == 200
    return payload.decode("utf-8")


@pytest.fixture
def steps_client(serve):  # noqa: F811 - the fixture, used
    def start(path):
        client = serve(path)
        client.request_json = lambda path: json.loads(_get(client, path))
        return client
    return start


# The steps page ---------------------------------------------------------------------------

def test_two_run_ids_that_differ_by_a_hidden_character_stay_two_runs(tmp_path, steps_client):
    client = steps_client(_runs(tmp_path, ["ab", "a\u200bb"]))
    keys = _keys(client)
    assert len(set(keys.values())) == 2
    status, body = _post(client, keys["Task 1"], 1)
    assert status == 200 and body["summary"]["marked"] == 1
    assert _lines(tmp_path)[-1]["id"] == "a\u200bb"  # the run marked, not the other
    status, body = _post(client, keys["Task 0"], 0)
    assert status == 200 and body["summary"]["marked"] == 2  # not "marked in another tab"
    assert [line["id"] for line in _lines(tmp_path)[1:]] == ["a\u200bb", "ab"]


@pytest.mark.parametrize("hidden", list(HIDDEN.values()), ids=list(HIDDEN))
def test_a_run_whose_id_has_a_hidden_character_is_saved_and_next_moves_on(tmp_path,
                                                                           steps_client,
                                                                           hidden):
    client = steps_client(_runs(tmp_path, ["one", hidden, "three"]))
    for n in range(3):  # as the page goes: the first run not marked, then the next
        first = client.request_json("/state")["runs"][0]
        status, body = _post(client, first["id"], 1)
        assert status == 200 and body["summary"]["marked"] == n + 1
    assert client.request_json("/state")["marked"] == 3
    assert sorted(line["id"] for line in _lines(tmp_path)[1:]) == sorted(["one", hidden,
                                                                          "three"])


def test_a_runs_key_stays_the_same_when_the_page_opens_again(tmp_path, steps_client):
    path = _runs(tmp_path, ["ab", "a\u200bb", 7])
    first, again = _keys(steps_client(path)), _keys(steps_client(path))
    assert first == again
    assert first["Task 2"] == redact.item_key("7")


def test_the_page_never_gets_the_run_ids(tmp_path, steps_client):
    client = steps_client(_runs(tmp_path, [FAKE_KEY, "plain-id", "a\u200bb"]))
    for path in ("/", "/state"):
        text = _get(client, path)
        assert FAKE_KEY not in text and "plain-id" not in text, path
        assert redact.item_key("plain-id") in text, path


def test_a_tab_that_sends_a_run_id_instead_of_its_key_saves_nothing(tmp_path, steps_client):
    client = steps_client(_runs(tmp_path, ["ab", "a\u200bb"]))
    status, body = _post(client, "ab", 1)  # an id, not a key
    assert status == 404 and body == {"error": "no item with that id"}
    assert not (tmp_path / ".judgekeeper" / "steps" / "marks.jsonl").exists()


def test_two_run_ids_with_one_key_stop_at_the_runs_file(tmp_path, monkeypatch):
    path = _runs(tmp_path, ["one", "two", "three"])
    monkeypatch.setattr(redact, "item_key", lambda text: "k" + "0" * 16)
    with pytest.raises(steps.StepsError) as e:
        steps_page.StepsSession(Workspace(tmp_path), path)
    assert str(e.value) == ("Line 2 of runs.jsonl has an id judgekeeper can't tell apart from "
                            "the id on line 1.")

