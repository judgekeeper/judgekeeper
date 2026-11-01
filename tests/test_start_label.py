"""`judgekeeper`, labeling and the result: the queue, the labeling page, the result page, and
the files saved in `.judgekeeper/`.

No test opens a browser: the server runs in a thread and a test client clicks for the person.
"""

from __future__ import annotations

import json
import re
import threading

import pytest

from judgekeeper import label as label_mod
from judgekeeper import marks, start, start_label, targets, weighted
from judgekeeper.anchors import canonical_hash, load_anchors, manifest_path_for
from judgekeeper.fingerprint import JudgeFingerprint
from judgekeeper.judgments import read_run
from judgekeeper.records import LLM, RecordList, ScoreRecord
from tests.start_projects import promptfoo_project, save_result, split
from tests.test_label_server import Client


def _found(root, n_pass=20, n_fail=12, **kwargs):
    promptfoo_project(root, split(n_pass, n_fail), **kwargs)
    return start.find_judge(root)


def _answers(n_pass, n_fail):
    recs = RecordList(ScoreRecord(target_id=f"x{i}", name="j", annotator_kind=LLM,
                                  label="pass" if i < n_pass else "fail", input=f"q{i}",
                                  output=f"a{i}") for i in range(n_pass + n_fail))
    from judgekeeper.normalise import Normaliser

    return start.build_pool([("r", recs)], "j", Normaliser()).answers


def test_marks_for_other_results_point_at_new(tmp_path, monkeypatch):
    """Marks made on other results stop prepare, and the words say how to start over."""
    monkeypatch.chdir(tmp_path)
    ws = start_label.prepare(_found(tmp_path), say=lambda line: None)
    session = start_label.StartSession(ws)
    session.update({"id": session.items[0]["id"], "label": "pass", "seconds": 3})
    with pytest.raises(start.StartError) as err:
        start_label.prepare(_found(tmp_path, n_pass=12, n_fail=20), say=lambda line: None)
    said = str(err.value)
    assert "holds marks for other results; nothing was changed." in said
    from judgekeeper.textio import program

    assert f"run {program()} --new (your marks move to .judgekeeper/previous-<date>/)" in said
    assert "somewhere else" not in said


# The queue -------------------------------------------------------------------------------

def test_the_same_seed_gives_the_same_queue():
    answers = _answers(30, 12)
    assert start_label.build_queue(answers, 7) == start_label.build_queue(answers, 7)
    assert start_label.build_queue(answers, 7) != start_label.build_queue(answers, 8)


def test_the_first_ten_hold_five_and_five():
    for n_pass, n_fail in ((30, 12), (300, 40), (20, 20)):
        groups = [q["group"] for q in start_label.build_queue(_answers(n_pass, n_fail), 3)]
        assert groups[:10].count("pass") == 5, (n_pass, n_fail)


@pytest.mark.parametrize("n_pass, n_fail", [(30, 12), (90, 10), (300, 40), (40, 300), (12, 4),
                                            (200, 3), (60, 60)])
def test_the_end_of_the_queue_mixes_both_grades(n_pass, n_fail):
    """The last answers never all have one grade: their place would give it away."""
    for seed in range(5):
        groups = [q["group"] for q in start_label.build_queue(_answers(n_pass, n_fail), seed)]
        assert groups.count("pass") == n_pass and groups.count("fail") == n_fail
        assert set(groups[-20:]) == {"pass", "fail"}, (n_pass, n_fail, seed)


def test_a_fail_is_seen_early_and_late_when_few_answers_fail():
    groups = [q["group"] for q in start_label.build_queue(_answers(400, 40), 1)]
    assert groups[:30].count("fail") == 15  # enough for a first result, up front
    tail = groups[30:]
    for k in range(0, len(tail) - 20, 20):  # then about one in sixteen, to the end
        assert "fail" in tail[k:k + 40], k
    assert "fail" in tail[-20:]


@pytest.mark.parametrize("n_pass, n_fail", [(300, 20), (200, 25), (100, 16), (20, 300)])
def test_a_first_result_is_in_the_first_30_when_one_kind_is_rare(n_pass, n_fail):
    """15 of each up front even when the rarer kind has fewer than 30: when every mark agrees
    with the LLM-as-a-judge, 30 marks reach a first result."""
    for seed in range(5):
        groups = [q["group"] for q in start_label.build_queue(_answers(n_pass, n_fail), seed)]
        assert groups[:30].count("pass") == groups[:30].count("fail") == targets.ROUGH, seed
        assert "fail" in groups[-20:] and "pass" in groups[-20:], seed


def test_a_pool_with_one_kind_only_is_queued():
    for n_pass, n_fail in ((20, 0), (0, 20), (1, 1)):
        groups = [q["group"] for q in start_label.build_queue(_answers(n_pass, n_fail), 2)]
        assert groups.count("pass") == n_pass and groups.count("fail") == n_fail


def test_the_whole_pool_is_queued_once():
    answers = _answers(30, 12)
    queue = start_label.build_queue(answers, 5)
    assert sorted(q["id"] for q in queue) == sorted(a.id for a in answers)
    by_id = {a.id: a.verdict for a in answers}
    assert all(by_id[q["id"]] == q["group"] for q in queue)


def test_inside_a_block_the_order_is_shuffled():
    queues = {tuple(q["group"] for q in start_label.build_queue(_answers(20, 20), s)[:10])
              for s in range(20)}
    assert len(queues) > 1


# The labeling page -----------------------------------------------------------------------

@pytest.fixture
def workspace(tmp_path):
    found = _found(tmp_path)
    ws = start_label.prepare(found, say=lambda line: None)
    return found, ws


def _result_page(ws):
    """The server's result function, as the marking page has it: each call makes and saves a
    new result."""

    def make(session, back):
        r = start_label.store_result(ws, session)
        done = session.summary()["done"]
        return start_label.result_html(start_label._scrubbed(r), None if done else back)

    return make


def _server(ws):
    session = start_label.StartSession(ws)
    server = label_mod.LabelServer(session, port=0, page=start_label.page_template(),
                                   result=_result_page(ws))
    thread = threading.Thread(target=server.serve, daemon=True)
    thread.start()
    return server, thread, Client(server)


def _page_data(server) -> dict:
    page = server.page()[0]
    m = re.search(r'<script type="application/json" id="data">(.*?)</script>', page, re.DOTALL)
    return json.loads(m[1])


def test_the_page_never_holds_the_judges_verdict(workspace):
    found, ws = workspace
    server, thread, client = _server(ws)
    try:
        data = _page_data(server)
        assert set(data) == {"items", "total", "start", "counts", "status"}
        assert set(data["status"]) == {"text", "first", "ready", "headline"}
        for item in data["items"]:
            assert set(item) == {"id", "input", "output", "label", "skipped"}
        page = server.page()[0]
        for a in found.pool.answers:
            assert a.reason and a.reason not in page
        status, body = client.label(id=data["items"][0]["id"], label="pass")
        assert status == 200
        text = json.dumps(body) + json.dumps(client.state())
        for word in ("verdict", "score", "reason", "group", "rationale", "judge"):
            assert word not in text, word
    finally:
        server.stop()
        thread.join(timeout=5)


def test_the_page_shows_the_question_and_the_answer_as_written(workspace):
    _, ws = workspace
    server, thread, _ = _server(ws)
    try:
        page = " ".join(server.page()[0].split())
        for needed in (">Question</div>", ">Answer</div>", "white-space: pre-wrap",
                       "<span>Fail</span><kbd>←</kbd>", "<span>Pass</span><kbd>→</kbd>",
                       "<span>Skip this one</span><kbd>S</kbd>", "<span>Undo</span><kbd>Z</kbd>",
                       "See your result", "#1E293B", "#10B981", '"Manrope"'):
            assert needed in page, needed
        data = _page_data(server)
        assert re.fullmatch(r"Question \d+\?", data["items"][0]["input"])
        assert " src=" not in page and "https://" not in page
    finally:
        server.stop()
        thread.join(timeout=5)


def test_clicks_are_written_to_marks_jsonl(workspace):
    _, ws = workspace
    server, thread, client = _server(ws)
    try:
        ids = [i["id"] for i in client.state()["items"]]
        assert client.label(id=ids[0], label="pass")[0] == 200   # Pass
        assert client.label(id=ids[1], label="fail")[0] == 200   # Fail
        assert client.label(id=ids[2], deferred=True)[0] == 200  # Skip
        assert client.label(id=ids[3], label="pass")[0] == 200
        assert client.label(id=ids[3], label=None, deferred=False)[0] == 200  # Undo
        last = marks.read(ws.marks).last
        assert last[ids[0]]["mark"] == "pass"
        assert last[ids[1]]["mark"] == "fail"
        assert last[ids[2]]["mark"] == "skip"
        assert last[ids[3]]["mark"] is None
        assert len(ws.marks.read_text(encoding="utf-8").splitlines()) == 1 + 5
    finally:
        server.stop()
        thread.join(timeout=5)


def test_the_counts_follow_the_persons_clicks(workspace):
    _, ws = workspace
    server, thread, client = _server(ws)
    try:
        ids = [i["id"] for i in client.state()["items"]]
        client.label(id=ids[0], label="pass")
        client.label(id=ids[1], label="pass")
        _, body = client.label(id=ids[2], label="fail")
        assert body["summary"]["counts"] == {"correct": 2, "wrong": 1, "skipped": 0}
        client.label(id=ids[3], deferred=True)
        assert client.state()["counts"] == {"correct": 2, "wrong": 1, "skipped": 1}
    finally:
        server.stop()
        thread.join(timeout=5)


def test_labeling_again_resumes_at_the_next_answer(workspace):
    _, ws = workspace
    session = start_label.StartSession(ws)
    ids = [i["id"] for i in session.items]
    session.update({"id": ids[0], "label": "pass"})
    session.update({"id": ids[1], "deferred": True})
    again = start_label.StartSession(ws)
    state = again.state()
    assert state["start"] == 2
    assert state["items"][1]["skipped"] is True
    assert state["counts"] == {"correct": 1, "wrong": 0, "skipped": 1}


def test_the_queue_order_is_the_page_order(workspace):
    _, ws = workspace
    queue = json.loads(ws.start.read_text(encoding="utf-8"))["queue"]
    assert [i["id"] for i in start_label.StartSession(ws).items] == [q["id"] for q in queue]


def test_the_token_and_host_checks_hold_for_this_page(workspace):
    _, ws = workspace
    server, thread, client = _server(ws)
    try:
        assert client.request("GET", "/", token=False)[0].status == 403
        assert client.request("GET", "/result", token=False)[0].status == 403
        assert client.request("GET", "/", host="evil.example:80")[0].status == 403
        assert client.request("GET", "/")[0].status == 200
    finally:
        server.stop()
        thread.join(timeout=5)


def test_see_my_result_works_before_everything_is_labeled(workspace):
    _, ws = workspace
    server, thread, client = _server(ws)
    try:
        ids = [i["id"] for i in client.state()["items"]]
        client.label(id=ids[0], label="pass")
        resp, payload = client.request("GET", "/result")
        assert resp.status == 200
        assert resp.getheader("Content-Type").startswith("text/html")
        from judgekeeper.report_page import LIVE_CSP

        assert resp.getheader("Content-Security-Policy") == f"{LIVE_CSP}; frame-ancestors 'none'"
        assert "font-src data:" in resp.getheader("Content-Security-Policy")
        html = payload.decode()
        assert ('<h1 id="verdict-h" class="plain">Mark a few more answers to see your '
                "result.</h1>") in html  # what the terminal says before 15 Pass and 15 Fail
        assert "Too early to tell" not in html
        assert f'<a href="/?token={server.token}">Mark more answers to get a result.</a>' in html
        assert thread.is_alive()  # answers are left: the person may go on
    finally:
        server.stop()
        thread.join(timeout=5)


def test_after_the_last_answer_the_result_is_served_and_the_server_stops(tmp_path):
    ws = start_label.prepare(_found(tmp_path, 20, 16), say=lambda line: None)
    _, thread, client = _server(ws)
    queue = {q["id"]: q["group"] for q in json.loads(ws.start.read_text(encoding="utf-8"))["queue"]}
    for item_id, group in queue.items():
        assert client.label(id=item_id, label=group)[0] == 200
    resp, payload = client.request("GET", "/result")
    assert resp.status == 200
    assert "Your <span class=\"term\">LLM-as-a-judge</span> is good enough to use." in payload.decode()
    thread.join(timeout=5)
    assert not thread.is_alive()


# The result ------------------------------------------------------------------------------

def _result(n_pool_pass, n_pool_fail, n_p, c_p, n_f, c_f):
    return start_label.describe(weighted.corrected(n_pool_pass, n_pool_fail, n_p, c_p, n_f, c_f))


def test_the_verdict_levels_follow_the_ranges():
    green = _result(500, 500, 50, 50, 50, 0)
    amber = _result(500, 500, 15, 13, 15, 2)       # 87% each side, ranges reach below 80%
    red = _result(500, 500, 40, 38, 40, 24)        # many answers it failed should pass
    early = _result(900, 100, 15, 15, 15, 0)       # the Fail side's range is wide: no colour
    too_few = _result(100, 100, 10, 9, 10, 1)      # 10 Pass, 10 Fail
    assert green["verdict"] == "Your LLM-as-a-judge is good enough to use."
    assert amber["verdict"] == "Too early to tell. Mark more answers to get a result."
    assert red["verdict"] == "Your LLM-as-a-judge needs work."
    assert early["verdict_level"] == "check"  # a wide range is never too early by itself
    assert early["verdict"] == "Too early to tell. Mark more answers to get a result."
    assert too_few["verdict"] == "Mark a few more answers to see your result."
    assert start_label.sentences(too_few) == [
        "Mark a few more answers to see your result. So far: 10 Pass, 10 Fail."]
    assert [r["check"] for r in (amber, too_few)] == ["result", "too_few"]
    assert _result(100, 100, 50, 48, 50, 2)["check"] == "result"


# 900 passes and 100 fails in the pool, 25 marked in each group, 24 and 1 marked Pass: 25
# marked Pass and 25 Fail, but the judge passes most answers, so the TNR range stays wide.


def test_the_targets_are_the_shared_ones():
    assert start_label.ROUGH == targets.ROUGH


def test_the_word_trust_is_nowhere():
    texts = [start_label.page_template()]
    for counts in ((100, 100, 20, 19, 20, 1), (100, 100, 20, 14, 20, 6), (100, 100, 2, 1, 0, 0)):
        r = _result(*counts)
        texts.append(start_label.result_html(r))
    assert not any("trust" in t.lower() for t in texts)


def test_the_result_page_stands_alone():
    html = start_label.result_html(_result(900, 100, 25, 20, 25, 10))
    for needed in ("Your <span class=\"term\">LLM-as-a-judge</span> needs work.", "You passed", "Kappa", "More details", "What next",
                   "judgekeeper fix", '"Manrope"'):
        assert needed in html, needed
    assert "<a " not in html.split("<body>")[1]  # no link back: commands only
    assert not re.search(r"https?://(?!www\.w3\.org/2000/svg)", html)
    assert "<link" not in html and "@import" not in html


# Saved files -----------------------------------------------------------------------------

def test_starting_to_label_writes_the_start_files(workspace):
    _, ws = workspace
    data = json.loads(ws.start.read_text(encoding="utf-8"))
    for key in ("tool", "results_files", "metric", "fingerprint", "pool", "left_out", "seed",
                "queue", "judgekeeper_version", "started_at", "judge"):
        assert key in data, key
    assert data["results_files"] == ["results.json"]
    assert data["pool"] == {"answers": 32, "pass": 20, "fail": 12}
    assert len(data["queue"]) == 32
    pool = [json.loads(line) for line in ws.pool.read_text(encoding="utf-8").splitlines()]
    assert set(pool[0]) == {"id", "input", "output"}
    header, records = read_run(ws.pool_judge)
    assert len(records) == 32
    fields = set(JudgeFingerprint().to_dict())
    for rec in records.values():
        assert set(rec["fingerprint"]) >= fields
        assert rec["fingerprint"]["model"] == "openai:gpt-4.1-mini"
    assert header["source"]["kind"] == "promptfoo"


def _label_everything(ws, agree=True):
    session = start_label.StartSession(ws)
    groups = {q["id"]: q["group"] for q in json.loads(ws.start.read_text(
        encoding="utf-8"))["queue"]}
    for item in session.items:
        group = groups[item["id"]]
        session.update({"id": item["id"],
                        "label": group if agree else ("fail" if group == "pass" else "pass")})
    return session


def _sealed(path):
    """The anchor set and its manifest, checked against each other."""
    items = load_anchors(path)
    manifest = json.loads(manifest_path_for(path).read_text(encoding="utf-8"))
    assert manifest["sha256"] == canonical_hash(items)
    return items, manifest


def test_a_result_writes_anchors_and_the_result_files(workspace):
    _, ws = workspace
    session = _label_everything(ws)
    save_result(ws, session, say=lambda line: None)
    items, manifest = _sealed(ws.anchors)
    assert len(items) == 32 and manifest["label_distribution"] == {"fail": 12, "pass": 20}
    result = json.loads(ws.result_json.read_text(encoding="utf-8"))
    for key in ("tpr", "tnr", "kappa", "tpr_interval", "real_pass_rate", "judge_pass_rate",
                "groups", "labels", "fingerprint", "made_at", "verdict", "level", "judge"):
        assert key in result, key
    assert result["tpr"] == 1 and result["tnr"] == 1
    html = ws.report_html.read_text(encoding="utf-8")
    assert html.startswith("<!doctype html>")
    assert 'LLM-as-a-judge:</span><span class="v" title="openai:gpt-4.1-mini">openai:gpt-4.1-mini' in html
    assert "results.json" not in html.split("<body>")[1]  # no file names or dates on the page


def test_a_second_result_moves_the_first_to_history(workspace):
    _, ws = workspace
    session = _label_everything(ws)
    save_result(ws, session, say=lambda line: None)
    first = ws.result_json.read_text(encoding="utf-8")
    item = session.items[0]
    session.update({"id": item["id"], "label": "fail" if item["label"] == "pass" else "pass"})
    save_result(ws, session, say=lambda line: None)
    history = sorted((ws.dir / "history").glob("result-*.json"))
    assert len(history) == 1 and history[0].read_text(encoding="utf-8") == first


def test_no_new_marks_keep_the_saved_result(workspace):
    # "See your result" or --label-more with nothing new: a new result would move the
    # finished review and fix to history/
    _, ws = workspace
    session = _label_everything(ws)
    save_result(ws, session, say=lambda line: None)
    first = ws.result_json.read_bytes()
    again = save_result(ws, start_label.StartSession(ws))
    assert ws.result_json.read_bytes() == first
    assert not (ws.dir / "history").exists()
    assert again["made_at"] == json.loads(first)["made_at"]


def test_skipped_answers_are_not_in_the_anchors(workspace):
    _, ws = workspace
    session = start_label.StartSession(ws)
    ids = [i["id"] for i in session.items]
    session.update({"id": ids[0], "label": "pass"})
    session.update({"id": ids[1], "deferred": True})
    save_result(ws, session, say=lambda line: None)
    items, _ = _sealed(ws.anchors)
    assert [i["id"] for i in items] == [ids[0]]


def test_secrets_in_the_results_are_scrubbed_in_every_saved_file(tmp_path):
    secret = "sk-ant-" + "q" * 40
    found = _found(tmp_path, tag=f" {secret}")
    ws = start_label.prepare(found, say=lambda line: None)
    session = _label_everything(ws)
    save_result(ws, session, say=lambda line: None)
    saved = [p for p in ws.dir.rglob("*") if p.is_file()]
    assert len(saved) >= 8
    for path in saved:
        assert secret not in path.read_text(encoding="utf-8"), path.name


def test_the_first_save_says_what_the_folder_holds_once(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # run in the project: the folder is .judgekeeper here
    found = _found(tmp_path)
    said = []
    start_label.prepare(found, say=said.append)
    start_label.prepare(found, say=said.append)
    note = ("Saved in .judgekeeper/. It holds your answers' text: commit it only if your data "
            "may live in your repo.")
    assert said.count(note) == 1


def test_preparing_again_keeps_the_queue_and_the_labels(tmp_path):
    found = _found(tmp_path)
    ws = start_label.prepare(found, say=lambda line: None)
    queue = json.loads(ws.start.read_text(encoding="utf-8"))["queue"]
    session = start_label.StartSession(ws)
    session.update({"id": session.items[0]["id"], "label": "fail"})
    ws = start_label.prepare(start.find_judge(tmp_path), say=lambda line: None)
    assert json.loads(ws.start.read_text(encoding="utf-8"))["queue"] == queue
    assert start_label.StartSession(ws).items[0]["label"] == "fail"


def test_new_verdicts_on_the_same_answers_make_a_new_queue(tmp_path):
    ws = start_label.prepare(_found(tmp_path, 20, 12), say=lambda line: None)
    promptfoo_project(tmp_path, split(12, 20))  # the same answers, judged the other way
    ws = start_label.prepare(start.find_judge(tmp_path), say=lambda line: None)
    groups = [q["group"] for q in ws.data()["queue"]]
    assert groups.count("pass") == 12 and groups.count("fail") == 20


def test_nothing_is_written_outside_the_folder(tmp_path):
    found = _found(tmp_path)
    before = {p for p in tmp_path.rglob("*") if ".judgekeeper" not in p.parts}
    ws = start_label.prepare(found, say=lambda line: None)
    save_result(ws, _label_everything(ws), say=lambda line: None)
    assert {p for p in tmp_path.rglob("*") if ".judgekeeper" not in p.parts} == before
    assert not (tmp_path / ".gitignore").exists()


# The whole flow --------------------------------------------------------------------------


@pytest.mark.parametrize("correct, wrong", [(20, 4), (3, 30), (9, 2)])
def test_every_answer_marked_but_a_kind_short_says_why_there_is_no_result(correct, wrong):
    r = {"check": "too_few", "left": 0, "labels": {"correct": correct, "wrong": wrong}}
    first = (f"You've marked every answer: {correct} Pass, {wrong} Fail. A result needs at "
             "least 15 of each.")
    then = ("Next: run your eval on more questions, then run `judgekeeper mark`: the new "
            "answers join the ones you marked.")
    assert start_label.sentences(r) == [first, then]
    r["left"] = 3  # answers still to mark: mark more, as before
    assert start_label.sentences(r)[0].startswith("Mark a few more answers")


# A big pool: the page gets the answers it needs, never the whole pool ---------------------

@pytest.fixture
def big(tmp_path):
    found = _found(tmp_path, n_pass=1500, n_fail=1500)
    return start_label.prepare(found, say=lambda line: None)


def test_the_page_gets_the_next_answers_not_the_whole_pool(big):
    session = start_label.StartSession(big)
    state = session.state()
    assert state["total"] == 3000
    assert len(state["items"]) == start_label.AHEAD
    assert len(json.dumps(state)) < 100_000


@pytest.mark.parametrize("seed, again", [(0, False), (45, True)])  # 45: one comes back at 150
def test_marking_moves_the_window_and_keeps_every_mark_before_it(tmp_path, monkeypatch, seed,
                                                                 again):
    monkeypatch.setattr(start_label.secrets, "randbelow", lambda n: seed)
    big = start_label.prepare(_found(tmp_path, n_pass=1500, n_fail=1500), say=lambda line: None)
    session = start_label.StartSession(big)
    ids = [i["id"] for i in session.items]
    for k in range(150):
        session.update({"id": ids[k], "label": "pass" if k % 2 else "fail"})
    session.update({"id": ids[150], "deferred": True})
    state = start_label.StartSession(big).state()
    items = [i for i in state["items"] if "again" not in i]
    assert len(state["items"]) - len(items) == again
    assert len(items) == 151 + start_label.AHEAD
    assert state["start"] == 151 and state["items"][150]["skipped"] is True
    assert ("again" in state["items"][151]) == again  # shown again first, where marking goes on
    assert [i["id"] for i in items] == ids[:151 + start_label.AHEAD]
    assert state["counts"] == {"correct": 75, "wrong": 75, "skipped": 1}
    assert state["total"] == 3000 + again


def test_a_small_pool_is_sent_whole(workspace):
    _, ws = workspace
    state = start_label.StartSession(ws).state()
    assert len(state["items"]) == state["total"] == 32
