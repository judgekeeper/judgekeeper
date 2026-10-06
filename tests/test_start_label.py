"""`judgekeeper start`, labeling and the result: the queue, the labeling page, the result in
the terminal and the page, and the files saved in `.judgekeeper/`.

No test opens a browser: the server runs in a thread and a test client clicks for the person.
"""

from __future__ import annotations

import builtins
import json
import re
import threading

import pytest

from judgekeeper import label as label_mod
from judgekeeper import start, start_label, weighted
from judgekeeper.anchors import load_verified
from judgekeeper.cli import main
from judgekeeper.fingerprint import JudgeFingerprint
from judgekeeper.judgments import read_run
from judgekeeper.records import LLM, RecordList, ScoreRecord
from judgekeeper.textio import quote_arg
from tests.start_projects import promptfoo_project, split
from tests.test_label_server import Client, _read


def _found(root, n_pass=20, n_fail=12, **kwargs):
    promptfoo_project(root, split(n_pass, n_fail), **kwargs)
    return start.find_judge(root)


def _answers(n_pass, n_fail):
    recs = RecordList(ScoreRecord(target_id=f"x{i}", name="j", annotator_kind=LLM,
                                  label="pass" if i < n_pass else "fail", input=f"q{i}",
                                  output=f"a{i}") for i in range(n_pass + n_fail))
    from judgekeeper.normalise import Normaliser

    return start.build_pool([("r", recs)], "j", Normaliser()).answers


# The queue -------------------------------------------------------------------------------

def test_the_same_seed_gives_the_same_queue():
    answers = _answers(30, 12)
    assert start_label.build_queue(answers, 7) == start_label.build_queue(answers, 7)
    assert start_label.build_queue(answers, 7) != start_label.build_queue(answers, 8)


def test_blocks_of_ten_hold_five_and_five_while_both_groups_last():
    queue = start_label.build_queue(_answers(30, 12), 3)
    groups = [q["group"] for q in queue]
    assert groups[:10].count("pass") == 5 and groups[10:20].count("pass") == 5
    # 12 fails: blocks 1 and 2 take 10, block 3 takes the last 2 and 8 passes.
    assert groups[20:30].count("fail") == 2
    assert set(groups[30:]) == {"pass"}


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


def _server(ws):
    session = start_label.StartSession(ws)
    server = label_mod.LabelServer(session, port=0, page=start_label.page_template(),
                                   result=start_label.result_maker(ws, say=lambda line: None))
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
        assert set(data) == {"items", "start", "counts"}
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
        for needed in ("The question", "The answer", "white-space: pre-wrap", "17px",
                       "Correct <kbd>1</kbd>", "Wrong <kbd>2</kbd>", "Skip <kbd>S</kbd>",
                       "Undo <kbd>U</kbd>", "See my result", "#1E293B", "#10B981",
                       "prefers-color-scheme: dark", "A rough check needs 15 of each."):
            assert needed in page, needed
        data = _page_data(server)
        assert re.fullmatch(r"Question \d+\?", data["items"][0]["input"])
        assert " src=" not in page and "https://" not in page
    finally:
        server.stop()
        thread.join(timeout=5)


def test_clicks_are_written_to_labels_csv(workspace):
    _, ws = workspace
    server, thread, client = _server(ws)
    try:
        ids = [i["id"] for i in client.state()["items"]]
        assert client.label(id=ids[0], label="pass")[0] == 200   # Correct
        assert client.label(id=ids[1], label="fail")[0] == 200   # Wrong
        assert client.label(id=ids[2], deferred=True)[0] == 200  # Skip
        assert client.label(id=ids[3], label="pass")[0] == 200
        assert client.label(id=ids[3], label=None, deferred=False)[0] == 200  # Undo
        rows = {r["id"]: r for r in _read(ws.labels)}
        assert rows[ids[0]]["human_label"] == "pass"
        assert rows[ids[1]]["human_label"] == "fail"
        assert rows[ids[2]]["human_label"] == "" and rows[ids[2]]["notes"] == "skipped"
        assert rows[ids[3]]["human_label"] == ""
        assert list(_read(ws.labels)[0]) == ["id", "input", "output", "human_label", "notes"]
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
        assert "script-src" not in resp.getheader("Content-Security-Policy")
        html = payload.decode()
        assert "Too few labels to tell yet. Label more for a rough check." in html
        assert "<script" not in html
        assert "Keep labeling" in html
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
    assert "It agrees with you often enough to use as a gate." in payload.decode()
    thread.join(timeout=5)
    assert not thread.is_alive()


# The result ------------------------------------------------------------------------------

def _result(n_pool_pass, n_pool_fail, n_p, c_p, n_f, c_f):
    return start_label.describe(weighted.corrected(n_pool_pass, n_pool_fail, n_p, c_p, n_f, c_f))


def test_the_verdict_levels_use_the_report_thresholds():
    top = _result(100, 100, 20, 19, 20, 1)        # TPR 0.95, TNR 0.95, kappa 0.9
    middle = _result(100, 100, 20, 17, 20, 2)     # TPR 17/19 = 0.89, TNR 18/21 = 0.86
    bottom = _result(100, 100, 20, 14, 20, 6)     # TPR 0.7
    too_few = _result(100, 100, 10, 9, 10, 1)     # 10 Correct, 10 Wrong
    assert top["verdict"] == "It agrees with you often enough to use as a gate."
    assert middle["verdict"] == ("It agrees with you often, but check its fails and passes by "
                                 "hand before relying on it.")
    assert bottom["verdict"] == "It does not agree with you often enough to use as a gate."
    assert too_few["verdict"] == "Too few labels to tell yet. Label more for a rough check."
    assert [r["check"] for r in (top, too_few)] == ["rough", "too_few"]
    assert _result(100, 100, 50, 48, 50, 2)["check"] == "reliable"


def test_the_terminal_result():
    r = _result(900, 100, 25, 20, 25, 10)
    lines = start_label.result_lines(r, saved=".judgekeeper")
    tpr_lo, tpr_hi = r["tpr_interval"]
    tnr_lo, tnr_hi = r["tnr_interval"]
    assert lines[0] == "Your result (rough check: 30 Correct, 20 Wrong)"
    assert (f"Of the answers you marked Correct, your judge passed about 95% "
            f"({tpr_lo:.0%} to {tpr_hi:.0%}).") in lines
    assert (f"Of the answers you marked Wrong, your judge failed about 25% "
            f"({tnr_lo:.0%} to {tnr_hi:.0%}).") in lines
    assert (f"  TPR 0.95 ({tpr_lo:.2f}–{tpr_hi:.2f})   TNR 0.25 ({tnr_lo:.2f}–"
            f"{tnr_hi:.2f})   kappa 0.25") in lines
    lo, hi = r["real_pass_rate_interval"]
    assert (f"  Your judge passes 90% of your answers. From your labels, about 76% should pass "
            f"({lo:.0%}–{hi:.0%}).") in lines
    assert ("  Corrected for picking half from the judge's passes and half from its fails."
            in lines)
    assert "  Label more for a reliable result:  judgekeeper start" in lines
    assert "  Check again after your next eval run:  judgekeeper start" in lines
    assert "  Saved in .judgekeeper/ (result.html is the page you just saw)" in lines


def test_an_unknown_rate_is_said_in_words():
    r = _result(100, 100, 20, 15, 0, 0)
    text = "\n".join(start_label.result_lines(r, saved=".judgekeeper"))
    assert "None" not in text and "nan" not in text
    assert ("How often your judge fails the answers you mark Wrong is unknown yet: label more "
            "answers to find out.") in text
    assert "TNR unknown" in text


def test_the_word_trust_is_nowhere():
    texts = [start_label.page_template()]
    for counts in ((100, 100, 20, 19, 20, 1), (100, 100, 20, 14, 20, 6), (100, 100, 2, 1, 0, 0)):
        r = _result(*counts)
        texts += start_label.result_lines(r, saved=".judgekeeper")
        texts.append(start_label.result_html(r))
    for n_pass, n_fail in ((171, 41), (58, 2), (20, 2), (40, 0)):
        pool = start.Pool(answers=[start.Answer(str(i), "q", "a", "pass" if i < n_pass else "fail",
                                                "", None, None, "x")
                                   for i in range(n_pass + n_fail)])
        texts += start.intro_lines(pool)
    assert not any("trust" in t.lower() for t in texts)


def test_the_result_page_stands_alone():
    html = start_label.result_html(_result(900, 100, 25, 20, 25, 10))
    for needed in ("Your result", "Of the answers you marked Correct", "TPR", "TNR", "kappa",
                   "What next", "judgekeeper start", "prefers-color-scheme: dark"):
        assert needed in html, needed
    assert "<script" not in html and "Keep labeling" not in html
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


def test_a_result_writes_anchors_and_the_result_files(workspace):
    _, ws = workspace
    session = _label_everything(ws)
    start_label.save_result(ws, session, say=lambda line: None)
    items, manifest = load_verified(ws.anchors)
    assert len(items) == 32 and manifest["label_distribution"] == {"fail": 12, "pass": 20}
    result = json.loads(ws.result_json.read_text(encoding="utf-8"))
    for key in ("tpr", "tnr", "kappa", "tpr_interval", "real_pass_rate", "judge_pass_rate",
                "groups", "labels", "fingerprint", "made_at", "verdict", "z", "judge"):
        assert key in result, key
    assert result["tpr"] == 1 and result["tnr"] == 1
    html = ws.result_html.read_text(encoding="utf-8")
    assert html.startswith("<!doctype html>")
    date = json.loads(ws.start.read_text(encoding="utf-8"))["results_date"]
    assert "<b>llm-rubric</b> · openai:gpt-4.1-mini" in html
    when = f"{start_label.in_words(date[:10])}, {date[11:]}"
    assert f"From results.json (promptfoo), saved {when}" in html


def test_a_second_result_moves_the_first_to_history(workspace):
    _, ws = workspace
    session = _label_everything(ws)
    start_label.save_result(ws, session, say=lambda line: None)
    first = ws.result_json.read_text(encoding="utf-8")
    start_label.save_result(ws, session, say=lambda line: None)
    history = sorted((ws.dir / "history").glob("result-*.json"))
    assert len(history) == 1 and history[0].read_text(encoding="utf-8") == first


def test_skipped_answers_are_not_in_the_anchors(workspace):
    _, ws = workspace
    session = start_label.StartSession(ws)
    ids = [i["id"] for i in session.items]
    session.update({"id": ids[0], "label": "pass"})
    session.update({"id": ids[1], "deferred": True})
    start_label.save_result(ws, session, say=lambda line: None)
    items, _ = load_verified(ws.anchors)
    assert [i["id"] for i in items] == [ids[0]]


def test_secrets_in_the_results_are_scrubbed_in_every_saved_file(tmp_path):
    secret = "sk-ant-" + "q" * 40
    found = _found(tmp_path, tag=f" {secret}")
    ws = start_label.prepare(found, say=lambda line: None)
    session = _label_everything(ws)
    start_label.save_result(ws, session, say=lambda line: None)
    saved = [p for p in ws.dir.rglob("*") if p.is_file()]
    assert len(saved) >= 8
    for path in saved:
        assert secret not in path.read_text(encoding="utf-8"), path.name


def test_the_first_save_says_what_the_folder_holds_once(tmp_path):
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
    start_label.save_result(ws, _label_everything(ws), say=lambda line: None)
    assert {p for p in tmp_path.rglob("*") if ".judgekeeper" not in p.parts} == before
    assert not (tmp_path / ".gitignore").exists()


# The whole flow --------------------------------------------------------------------------

@pytest.fixture
def clicker(monkeypatch):
    """Replace the server loop: a client labels like the person would, then stops."""
    plan = {"labels": "agree", "stop_after": None, "opened": []}
    original = label_mod.LabelServer.serve
    monkeypatch.setattr("webbrowser.open", lambda url: plan["opened"].append(url))

    def serve(self, idle_timeout=None):
        thread = threading.Thread(target=original, args=(self, idle_timeout), daemon=True)
        thread.start()
        client = Client(self)
        ws = self.session.workspace
        groups = {q["id"]: q["group"] for q in json.loads(ws.start.read_text(
            encoding="utf-8"))["queue"]}
        for n, item in enumerate(client.state()["items"]):
            if plan["stop_after"] is not None and n == plan["stop_after"]:
                self.stop()
                thread.join(timeout=5)
                raise KeyboardInterrupt
            client.label(id=item["id"], label=groups[item["id"]])
        plan["page"] = client.request("GET", "/result")[1].decode()
        thread.join(timeout=5)

    monkeypatch.setattr(label_mod.LabelServer, "serve", serve)
    return plan


def _run(capsys, *argv):
    code = main(["start", *map(str, argv)])
    out, err = capsys.readouterr()
    return code, out, err


def test_start_labels_and_shows_the_result(tmp_path, capsys, clicker):
    promptfoo_project(tmp_path, split(20, 16))
    code, out, _ = _run(capsys, tmp_path, "--yes", "--port", "0")
    assert code == 0
    assert "Labeling page: http://127.0.0.1:" in out
    assert len(clicker["opened"]) == 1
    assert "Your result (rough check: 20 Correct, 16 Wrong)" in out
    assert "It agrees with you often enough to use as a gate." in out
    assert "Saved in .judgekeeper/. It holds your answers' text" in out
    assert "It agrees with you often enough to use as a gate." in clicker["page"]
    assert (tmp_path / ".judgekeeper" / "result.html").is_file()


def test_no_browser_prints_the_link_only(tmp_path, capsys, clicker):
    promptfoo_project(tmp_path, split(20, 12))
    code, out, _ = _run(capsys, tmp_path, "--yes", "--no-browser", "--port", "0")
    assert code == 0
    assert clicker["opened"] == []
    assert "Labeling page: http://127.0.0.1:" in out


def test_ctrl_c_says_everything_is_saved(tmp_path, capsys, clicker):
    promptfoo_project(tmp_path, split(20, 12))
    clicker["stop_after"] = 5
    code, out, _ = _run(capsys, tmp_path, "--yes", "--no-browser", "--port", "0")
    assert code == 0
    assert (f"Stopped. 5 labeled; run judgekeeper start {quote_arg(tmp_path)} --port 0 "
            "--no-browser to continue.") in out
    assert "Your result" not in out


def test_a_person_is_asked_before_the_page_opens(tmp_path, capsys, clicker, monkeypatch):
    promptfoo_project(tmp_path, split(20, 12))
    monkeypatch.setattr(start, "_interactive", lambda: True)
    answers = ["n"]
    monkeypatch.setattr(builtins, "input", lambda prompt="": print(prompt) or answers.pop(0))
    code, out, _ = _run(capsys, tmp_path, "--port", "0")
    assert code == 0
    assert "Open the labeling page now? [Y/n]" in out
    assert not (tmp_path / ".judgekeeper").exists()


def test_without_a_terminal_the_page_needs_yes(tmp_path, capsys, clicker):
    promptfoo_project(tmp_path, split(20, 12))
    code, out, _ = _run(capsys, tmp_path)
    assert code == start.EXIT_QUESTION
    assert (f"Open the labeling page? Run judgekeeper start {quote_arg(tmp_path)} --yes to open "
            "it.") in out
    assert not (tmp_path / ".judgekeeper").exists()


def test_a_port_in_use_is_a_usage_error(tmp_path, capsys, monkeypatch):
    import socket

    promptfoo_project(tmp_path, split(20, 12))
    busy = socket.socket()
    busy.bind(("127.0.0.1", 0))
    busy.listen()
    try:
        code, _, err = _run(capsys, tmp_path, "--yes", "--no-browser", "--port",
                            busy.getsockname()[1])
    finally:
        busy.close()
    assert code == 2 and "try --port" in err
