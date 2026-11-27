"""Ids with hidden characters (zero-width, right-to-left, ESC, NUL). The page's text is cleaned
of them (redact.visible), so the page never gets an id: it gets a key made from it
(redact.item_key), and a mark is saved under the exact id of the file."""

from __future__ import annotations

import json
import threading

import pytest

from judgekeeper import label, page, redact, start, start_label, steps, steps_page
from judgekeeper.start_label import Workspace
from tests.start_projects import answer, question
from tests.test_label_server import Client as AnswersClient
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


def test_an_older_tab_that_sends_a_run_id_is_told_to_load_again_and_saves_nothing(
        tmp_path, steps_client):
    client = steps_client(_runs(tmp_path, ["ab", "a\u200bb"]))
    status, body = _post(client, "ab", 1)  # an id, as a page from before the keys sends it
    assert status == 409 and body["stale"] is True  # the page loads its runs again
    assert not (tmp_path / ".judgekeeper" / "steps" / "marks.jsonl").exists()
    status, body = _post(client, "nope", 1)  # neither a key nor an id
    assert status == 404 and body == {"error": "no item with that id"}


def test_two_run_ids_with_one_key_stop_at_the_runs_file(tmp_path, monkeypatch):
    path = _runs(tmp_path, ["one", "two", "three"])
    monkeypatch.setattr(redact, "item_key", lambda text: "k" + "0" * 16)
    with pytest.raises(steps.StepsError) as e:
        steps_page.StepsSession(Workspace(tmp_path), path)
    assert str(e.value) == ("Line 2 of runs.jsonl has an id judgekeeper can't tell apart from "
                            "the id on line 1.")


# The answers page -------------------------------------------------------------------------

def _answers(tmp_path, monkeypatch, ids):
    """Graded results with their own ids, in JSONL (a CSV file can't hold a NUL); each answer
    shown once (no answer comes again)."""
    monkeypatch.setattr(start_label, "REPEAT_FROM", 10**6)
    (tmp_path / "results.jsonl").write_text("".join(json.dumps(
        {"id": item_id, "input": question(n), "output": answer(n),
         "verdict": "pass" if n < 21 else "fail"}) + "\n" for n, item_id in enumerate(ids)),
        encoding="utf-8")
    return start_label.prepare(start.find_judge(tmp_path), say=lambda line: None)


@pytest.fixture
def answers_client(tmp_path, monkeypatch):
    started = []

    def start_page(ids):
        ws = _answers(tmp_path, monkeypatch, ids)
        server = page.page_server(ws, 0)
        thread = threading.Thread(target=server.serve, daemon=True)
        thread.start()
        started.append((server, thread))
        return ws, AnswersClient(server)

    yield start_page
    for server, thread in started:
        server.stop()
        thread.join(timeout=5)


def _mark_every_answer(ws, client):
    """As the page goes: the first answer not marked, marked, then the next. The ids saved."""
    for n in range(42):
        state = client.state()
        item = state["items"][state["start"]]
        status, body = client.label(id=item["id"], label="pass", seconds=1)
        assert status == 200 and body["summary"]["n_labeled"] == n + 1, body
    lines = ws.marks.read_text(encoding="utf-8").splitlines()[1:]
    return [json.loads(line)["id"] for line in lines]


def _ids(**odd):
    ids = [f"id{i}" for i in range(42)]
    for at, value in odd.items():
        ids[int(at.removeprefix("at"))] = value
    return ids


def test_two_answer_ids_that_differ_by_a_hidden_character_stay_two_answers(answers_client):
    ids = _ids(at0="ab", at1="a\u200bb")
    ws, client = answers_client(ids)
    keys = [i["id"] for i in client.state()["items"]]
    assert len(set(keys)) == len(keys) == 42
    assert sorted(_mark_every_answer(ws, client)) == sorted(ids)  # each answer once


@pytest.mark.parametrize("hidden", list(HIDDEN.values()), ids=list(HIDDEN))
def test_an_answer_whose_id_has_a_hidden_character_is_saved_and_next_moves_on(answers_client,
                                                                               hidden):
    ids = _ids(at5=hidden)
    ws, client = answers_client(ids)
    assert sorted(_mark_every_answer(ws, client)) == sorted(ids)


def test_the_answers_page_never_gets_the_answer_ids(answers_client):
    _, client = answers_client(_ids(at0=FAKE_KEY, at1="plain-id"))
    for path in ("/", "/state"):
        text = _get(client, path)
        assert FAKE_KEY not in text and "plain-id" not in text, path
        assert redact.item_key("plain-id") in text, path


def test_an_older_tab_that_sends_an_answer_id_is_told_to_load_again_and_saves_nothing(
        answers_client):
    ws, client = answers_client(_ids(at0="ab", at1="a\u200bb"))
    resp, payload = client.request("POST", "/label", {"id": "ab", "label": "pass", "seconds": 1})
    assert resp.status == 409 and json.loads(payload)["stale"] is True  # the page loads again
    assert len(ws.marks.read_text(encoding="utf-8").splitlines()) <= 1  # no mark line
    resp, payload = client.request("POST", "/label", {"id": "nope", "label": "pass"})
    assert resp.status == 404 and json.loads(payload) == {"error": "no item with that id"}


def test_two_answer_ids_with_one_key_are_refused(tmp_path, monkeypatch):
    ws = _answers(tmp_path, monkeypatch, _ids())
    monkeypatch.setattr(label, "item_key", lambda text: "k" + "0" * 16)
    with pytest.raises(label.LabelError) as e:
        start_label.StartSession(ws)
    assert str(e.value) == label.TWO_KEYS and "id0" not in str(e.value)


# Ids that are not text or a whole number --------------------------------------------------

def _one_run(tmp_path, row: str):
    """A runs file of one run: `row` (JSON) and its steps."""
    path = tmp_path / "runs.jsonl"
    path.write_text(json.dumps({**json.loads(row), "steps": [{"role": "user", "content": "x"}]})
                    + "\n", encoding="utf-8")
    return path


@pytest.mark.parametrize("value", ["1.5", "true", "[1]", "1.0", '{"a": 1}'])
def test_an_id_of_another_kind_says_what_an_id_must_be(tmp_path, value):
    with pytest.raises(steps.StepsError) as e:
        steps.read_runs(_one_run(tmp_path, f'{{"id": {value}}}'))
    assert str(e.value) == "Line 1 of runs.jsonl has an id that is not text or a whole number."


@pytest.mark.parametrize("row", ["{}", '{"id": null}', '{"id": ""}', '{"id": "  "}'])
def test_a_run_with_no_id_says_it_has_none(tmp_path, row):
    with pytest.raises(steps.StepsError) as e:
        steps.read_runs(_one_run(tmp_path, row))
    assert str(e.value) == "Line 1 of runs.jsonl has no id."


def test_the_page_gets_a_key_for_every_id_it_is_sent():
    data = label.page_data({"runs": [{"id": "r1"}], "items": [{"id": "a"}], "again": {"id": "b"}})
    assert data == {"runs": [{"id": redact.item_key("r1")}],
                    "items": [{"id": redact.item_key("a")}], "again": {"id": redact.item_key("b")}}
