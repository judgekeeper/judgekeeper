"""Reviewing the disagreements after a `judgekeeper start` result.

Step A ("Look again"): every disagreement mixed with as many answers the person and the judge
agreed on (at least 3), the judge still hidden. Step B ("See what your judge said"): only the
disagreements, with the judge's verdict and reason. The labels in labels.csv never change;
result.json gains a `review` block.

No test opens a browser: the server runs in a thread and a test client clicks for the person.
"""

from __future__ import annotations

import builtins
import csv
import json
import re
import threading

import pytest

from judgekeeper import label as label_mod
from judgekeeper import start, start_label, start_review
from judgekeeper.cli import main
from judgekeeper.start_label import StartSession, Workspace, save_result
from judgekeeper.start_review import ReviewSession, pick, review_lines
from judgekeeper.table import guard_cell
from tests.start_projects import promptfoo_project, split
from tests.test_label_server import Client


def _quiet(line=""):
    pass


def _reviewable(root, flip_pass=3, flip_fail=2, n_pass=20, n_fail=16, outputs=None,
                labeled=None):
    """A project with a result: the first `labeled` answers of the queue (all when None)
    labeled the way the judge saw them, except the first `flip_pass` of the judge's passes
    (marked Wrong) and the first `flip_fail` of its fails (marked Correct)."""
    promptfoo_project(root, split(n_pass, n_fail), outputs=outputs)
    ws = start_label.prepare(start.find_judge(root), say=_quiet)
    queue = ws.data()["queue"][:labeled]
    flipped = {"pass": [q["id"] for q in queue if q["group"] == "pass"][:flip_pass],
               "fail": [q["id"] for q in queue if q["group"] == "fail"][:flip_fail]}
    session = StartSession(ws)
    other = {"pass": "fail", "fail": "pass"}
    for q in queue:
        label = other[q["group"]] if q["id"] in flipped[q["group"]] else q["group"]
        session.update({"id": q["id"], "label": label})
    save_result(ws, session, say=_quiet)
    return ws, flipped


def _second_look(session, plan=None):
    """Answer step A: `plan` maps an id to its second label; any other answer keeps its
    first label."""
    plan = plan or {}
    for item in session.items:
        session.update({"id": item["id"], "second": plan.get(item["id"], item["first"])})


def _labeled(n_dis_pass, n_dis_fail, n_agree_pass, n_agree_fail):
    rows = []
    for group, n_dis, n_agree in (("pass", n_dis_pass, n_agree_pass),
                                  ("fail", n_dis_fail, n_agree_fail)):
        other = "fail" if group == "pass" else "pass"
        rows += [{"id": f"{group}-d{i}", "first": other, "judge": group} for i in range(n_dis)]
        rows += [{"id": f"{group}-a{i}", "first": group, "judge": group}
                 for i in range(n_agree)]
    return rows


# Step A: the picks ------------------------------------------------------------------------

def test_step_a_shows_every_disagreement_and_as_many_agreed_answers():
    picks = pick(_labeled(4, 3, 10, 10), seed=7)
    dis = [p for p in picks if p["disagreement"]]
    agreed = [p for p in picks if not p["disagreement"]]
    assert len(dis) == 7 and len(agreed) == 7
    assert sorted(p["judge"] for p in agreed) in (["fail"] * 3 + ["pass"] * 4,
                                                  ["fail"] * 4 + ["pass"] * 3)


def test_at_least_three_agreed_answers_are_mixed_in():
    picks = pick(_labeled(1, 0, 10, 10), seed=7)
    assert sum(p["disagreement"] for p in picks) == 1
    assert sum(not p["disagreement"] for p in picks) == 3


def test_when_one_group_runs_short_the_other_fills_in():
    picks = pick(_labeled(3, 3, 1, 10), seed=7)
    agreed = [p for p in picks if not p["disagreement"]]
    assert len(agreed) == 6
    assert [p["judge"] for p in agreed].count("pass") == 1


def test_never_more_agreed_answers_than_there_are():
    picks = pick(_labeled(5, 0, 1, 1), seed=7)
    assert sum(not p["disagreement"] for p in picks) == 2


def test_the_picks_are_seeded_and_mixed():
    rows = _labeled(4, 3, 10, 10)
    assert pick(rows, seed=7) == pick(rows, seed=7)
    orders = {tuple(p["disagreement"] for p in pick(rows, seed=s)) for s in range(20)}
    assert len(orders) > 1
    assert (True,) * 7 + (False,) * 7 not in orders or len(orders) > 5


def test_the_review_is_saved_with_its_seed_and_picks(tmp_path):
    ws, flipped = _reviewable(tmp_path)
    session = ReviewSession(ws)
    saved = json.loads(ws.review.read_text(encoding="utf-8"))
    assert isinstance(saved["seed"], int)
    assert [i["id"] for i in saved["items"]] == [i["id"] for i in session.items]
    dis = {i["id"] for i in session.items if i["disagreement"]}
    assert dis == set(flipped["pass"] + flipped["fail"])
    assert len(session.items) == 10


# Step A: the page data --------------------------------------------------------------------

def _page_data(page: str) -> dict:
    m = re.search(r'<script type="application/json" id="data">(.*?)</script>', page, re.DOTALL)
    return json.loads(m[1])


def _review_server(ws):
    server = label_mod.LabelServer(ReviewSession(ws), port=0,
                                   page=start_review.page_template(ws),
                                   result=start_review.result_maker(ws, say=_quiet))
    thread = threading.Thread(target=server.serve, daemon=True)
    thread.start()
    return server, thread, Client(server)


def test_step_a_holds_no_first_label_and_no_judge_verdict(tmp_path):
    ws, _ = _reviewable(tmp_path)
    server, thread, _client = _review_server(ws)
    try:
        page = server.page()[0]
        data = _page_data(page)
        assert data["step"] == "a"
        for item in data["items"]:
            assert set(item) == {"id", "input", "output", "second"}
        text = json.dumps(data)
        for word in ("verdict", "reason", "first", "judge", "disagree", "pass", "fail"):
            assert word not in text, word
        for i in range(36):
            assert f"reason {i}" not in page
        assert "Look again at a few answers. Your judge's verdict is still hidden." in page
    finally:
        server.stop()
        thread.join(5)


def test_step_a_has_not_sure_undo_and_a_counter(tmp_path):
    ws, _ = _reviewable(tmp_path)
    page = start_review.page_template(ws)
    for needed in ("Correct", "Wrong", "Not sure", "Undo", "<kbd>3</kbd>", "<kbd>U</kbd>",
                   " of "):
        assert needed in page, needed


def test_second_looks_are_saved_on_every_click(tmp_path):
    ws, _ = _reviewable(tmp_path)
    server, thread, client = _review_server(ws)
    try:
        first = client.state()["items"][0]["id"]
        status, body = client.label(id=first, second="unsure")
        assert status == 200 and body["summary"]["step"] == "a"
        saved = json.loads(ws.review.read_text(encoding="utf-8"))
        item = next(i for i in saved["items"] if i["id"] == first)
        assert item["second"] == "unsure" and item["second_at"]
        status, _ = client.label(id=first, second=None)  # Undo
        assert status == 200
        assert next(i for i in json.loads(ws.review.read_text(encoding="utf-8"))["items"]
                    if i["id"] == first)["second"] is None
    finally:
        server.stop()
        thread.join(5)


def test_a_review_page_refuses_a_labeling_click(tmp_path):
    ws, _ = _reviewable(tmp_path)
    server, thread, client = _review_server(ws)
    try:
        first = client.state()["items"][0]["id"]
        assert client.label(id=first, label="pass")[0] == 400
        assert client.label(id=first, second="maybe")[0] == 400
        assert client.label(id=first, choice="judge_wrong")[0] == 400  # step B not yet
    finally:
        server.stop()
        thread.join(5)


# Step B -----------------------------------------------------------------------------------

def test_step_b_shows_only_the_disagreements_with_the_verdict_and_reason(tmp_path):
    ws, flipped = _reviewable(tmp_path)
    session = ReviewSession(ws)
    _second_look(session)
    state = session.state()
    assert state["step"] == "b"
    assert {i["id"] for i in state["items"]} == set(flipped["pass"] + flipped["fail"])
    raw = {r["id"]: r for r in (json.loads(line) for line in
                                ws.pool.read_text(encoding="utf-8").splitlines())}
    for item in state["items"]:
        n = int(re.search(r"\d+", json.dumps(raw[item["id"]]["input"]))[0])
        assert item["reason"] == f"reason {n}"
        judge = "Pass" if item["id"] in flipped["pass"] else "Fail"
        assert item["judge"] == judge
        assert set(item) == {"id", "input", "output", "said", "judge", "reason", "choice"}


def test_you_said_names_the_first_and_the_second_look(tmp_path):
    ws, flipped = _reviewable(tmp_path)
    p1, p2, p3 = flipped["pass"]
    session = ReviewSession(ws)
    _second_look(session, {p1: "pass", p2: "unsure"})
    said = {i["id"]: "".join(t for t, _ in i["said"]) for i in session.state()["items"]}
    assert said[p1] == "You said: Wrong (and Correct on a second look)"
    assert said[p2] == "You said: Wrong (and not sure on a second look)"
    assert said[p3] == "You said: Wrong (and Wrong again on a second look)"
    bold = [t for t, b in next(i for i in session.state()["items"] if i["id"] == p3)["said"]
            if b]
    assert bold == ["Wrong", "Wrong"]


def test_step_b_choices_undo_and_the_files(tmp_path):
    ws, flipped = _reviewable(tmp_path)
    p1, p2, p3 = flipped["pass"]
    f1, f2 = flipped["fail"]
    session = ReviewSession(ws)
    _second_look(session)
    for item_id, choice in ((p1, "slipped"), (p2, "judge_wrong"), (p3, "judge_wrong"),
                            (f1, "rule_unclear"), (f2, "judge_wrong")):
        session.update({"id": item_id, "choice": choice})
    session.update({"id": p3, "choice": None})  # Undo
    with ws.judge_mistakes.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert [r["id"] for r in rows] == [i["id"] for i in session.items
                                       if i["id"] in (p2, f2)]
    assert list(rows[0]) == ["id", "input", "output", "your_label", "second_look_label",
                             "judge_verdict", "judge_reason"]
    row = next(r for r in rows if r["id"] == p2)
    assert (row["your_label"], row["second_look_label"], row["judge_verdict"]) == (
        "fail", "fail", "pass")
    assert row["judge_reason"].startswith("reason ")
    with ws.rule_unclear.open(newline="", encoding="utf-8") as f:
        assert [r["id"] for r in csv.DictReader(f)] == [f1]
    assert session.summary()["step"] == "b"
    session.update({"id": p3, "choice": "judge_wrong"})
    assert session.summary()["step"] == "done" and session.summary()["done"]


def test_the_files_guard_against_spreadsheet_formulas(tmp_path):
    outputs = [f"=SUM({i})" for i in range(36)]
    ws, _ = _reviewable(tmp_path, outputs=outputs)
    session = ReviewSession(ws)
    _second_look(session)
    for item in session.items:
        if item["disagreement"]:
            session.update({"id": item["id"], "choice": "judge_wrong"})
    with ws.judge_mistakes.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 5
    for row in rows:
        assert row["output"].startswith("'=SUM(")
        assert row["output"] == guard_cell(row["output"][1:])


def test_labels_csv_never_changes(tmp_path):
    ws, flipped = _reviewable(tmp_path)
    before = ws.labels.read_bytes()
    session = ReviewSession(ws)
    _second_look(session, {flipped["pass"][0]: "pass"})
    for item in session.items:
        if item["disagreement"]:
            session.update({"id": item["id"], "choice": "slipped"})
    assert ws.labels.read_bytes() == before


def test_step_b_is_refused_until_step_a_is_done(tmp_path):
    ws, flipped = _reviewable(tmp_path)
    session = ReviewSession(ws)
    with pytest.raises(ValueError):
        session.update({"id": flipped["pass"][0], "choice": "judge_wrong"})


def test_a_second_look_cannot_change_once_step_b_has_a_choice(tmp_path):
    ws, flipped = _reviewable(tmp_path)
    session = ReviewSession(ws)
    _second_look(session)
    session.update({"id": flipped["pass"][0], "choice": "slipped"})
    with pytest.raises(ValueError):
        session.update({"id": flipped["pass"][0], "second": "pass"})


# Resuming ---------------------------------------------------------------------------------

def test_the_review_resumes_within_step_a(tmp_path):
    ws, _ = _reviewable(tmp_path)
    session = ReviewSession(ws)
    for item in session.items[:4]:
        session.update({"id": item["id"], "second": item["first"]})
    again = ReviewSession(ws)
    assert [i["id"] for i in again.items] == [i["id"] for i in session.items]
    state = again.state()
    assert state["step"] == "a" and state["start"] == 4
    assert [i["second"] for i in state["items"][:4]] == [i["first"] for i in session.items[:4]]


def test_the_review_resumes_between_and_within_step_b(tmp_path):
    ws, _ = _reviewable(tmp_path)
    session = ReviewSession(ws)
    _second_look(session)
    assert ReviewSession(ws).state()["step"] == "b"
    first = session.state()["items"][0]["id"]
    session.update({"id": first, "choice": "slipped"})
    state = ReviewSession(ws).state()
    assert state["step"] == "b" and state["start"] == 1


def test_a_new_result_starts_a_new_review_and_keeps_the_old_one(tmp_path):
    ws, _ = _reviewable(tmp_path, labeled=24)
    session = ReviewSession(ws)
    _second_look(session)
    old = ws.review.read_bytes()
    more = StartSession(ws)  # labeling one more answer makes a new result
    q = ws.data()["queue"][24]
    more.update({"id": q["id"], "label": q["group"]})
    save_result(ws, more, say=_quiet)
    again = ReviewSession(ws)
    assert again.state()["step"] == "a"
    (kept,) = ws.history.glob("review-*")
    assert (kept / "review.json").read_bytes() == old


# The numbers ------------------------------------------------------------------------------

def _full_review(ws, flipped, second=None, choices=None):
    p1, p2, p3 = flipped["pass"]
    f1, f2 = flipped["fail"]
    session = ReviewSession(ws)
    _second_look(session, second if second is not None else {p1: "pass", p2: "unsure",
                                                             f1: "fail"})
    choices = choices or {p1: "slipped", p2: "judge_wrong", p3: "judge_wrong",
                          f1: "rule_unclear", f2: "judge_wrong"}
    for item_id, choice in choices.items():
        session.update({"id": item_id, "choice": choice})
    return session


def test_the_review_lines_with_hand_worked_numbers(tmp_path):
    # Pool: 20 the judge passed, 16 it failed, all labeled. First labels: 3 of the passes
    # marked Wrong, 2 of the fails marked Correct. On a second look one of the 3 becomes
    # Correct (now 18 of 20 Correct in the pass group), one is Not sure (stays Wrong), and
    # one of the 2 becomes Wrong (1 of 16 Correct in the fail group).
    # TPR = 18 / (18 + 1) = 94.7%; TNR = 15 / (15 + 2) = 88.2%.
    ws, flipped = _reviewable(tmp_path)
    _full_review(ws, flipped)
    r = json.loads(ws.result_json.read_text(encoding="utf-8"))
    block = r["review"]
    assert block["second_look"]["tpr"] == pytest.approx(18 / 19)
    assert block["second_look"]["tnr"] == pytest.approx(15 / 17)
    assert review_lines(block) == [
        ("On a second look without the judge, you changed 2 of the 5 disagreements and 0 of "
         "the 5 answers you had agreed on. With your second-look labels: of the answers that "
         "should pass, your judge passed about 95%; of those that should fail, it failed about "
         "88%."),
        ("After seeing the judge: you called 3 judge mistakes, 1 slip of yours, and 1 unclear "
         "rule."),
        "Your first labels stay the main result.",
    ]
    assert r["tpr"] == pytest.approx(17 / 19) and r["tnr"] == pytest.approx(14 / 17)


def test_the_second_look_uses_the_group_weights(tmp_path):
    # 24 of 36 labeled: n_p of the judge's 20 passes and n_f of its 16 fails, so each labeled
    # pass weighs 20/n_p and each labeled fail 16/n_f. Second look: 1 of the 3 passes marked
    # Wrong turns Correct: a = (n_p - 2) / n_p, b = 2 / n_f, pi = 20/36, and
    # TPR = pi a / (pi a + (1 - pi) b).
    ws, flipped = _reviewable(tmp_path, labeled=24)
    groups = [q["group"] for q in ws.data()["queue"][:24]]
    n_p, n_f = groups.count("pass"), groups.count("fail")
    session = ReviewSession(ws)
    _second_look(session, {flipped["pass"][0]: "pass"})
    block = json.loads(ws.result_json.read_text(encoding="utf-8"))["review"]
    pi, a, b = 20 / 36, (n_p - 2) / n_p, 2 / n_f
    assert block["second_look"]["tpr"] == pytest.approx(pi * a / (pi * a + (1 - pi) * b))
    assert block["second_look"]["groups"]["pass"]["correct"] == n_p - 2


def test_step_b_choices_change_no_number(tmp_path):
    ws, flipped = _reviewable(tmp_path)
    _full_review(ws, flipped)
    one = json.loads(ws.result_json.read_text(encoding="utf-8"))
    other = tmp_path / "other"
    other.mkdir()
    ws2, flipped2 = _reviewable(other)
    q1, q2, q3 = flipped2["pass"]
    g1, g2 = flipped2["fail"]
    _full_review(ws2, flipped2, second={q1: "pass", q2: "unsure", g1: "fail"},
                 choices={q1: "judge_wrong", q2: "slipped", q3: "slipped", g1: "slipped",
                          g2: "slipped"})
    two = json.loads(ws2.result_json.read_text(encoding="utf-8"))
    for key in ("tpr", "tnr", "kappa"):
        assert one[key] == two[key]
        assert one["review"]["second_look"][key] == two["review"]["second_look"][key]


def test_several_changed_agreed_answers_say_the_rule_may_be_unclear(tmp_path):
    ws, _ = _reviewable(tmp_path)
    session = ReviewSession(ws)
    agreed = [i for i in session.items if not i["disagreement"]][:3]
    other = {"pass": "fail", "fail": "pass"}
    _second_look(session, {i["id"]: other[i["first"]] for i in agreed})
    lines = review_lines(json.loads(ws.result_json.read_text(encoding="utf-8"))["review"])
    assert "3 of the 5 answers you had agreed on" in lines[0]
    assert lines[0].endswith("You changed several answers on a second look: your rule may "
                             "be unclear.")


def test_two_changed_agreed_answers_do_not(tmp_path):
    ws, _ = _reviewable(tmp_path)
    session = ReviewSession(ws)
    agreed = [i for i in session.items if not i["disagreement"]][:2]
    other = {"pass": "fail", "fail": "pass"}
    _second_look(session, {i["id"]: other[i["first"]] for i in agreed})
    lines = review_lines(json.loads(ws.result_json.read_text(encoding="utf-8"))["review"])
    assert "rule may be unclear" not in " ".join(lines)


def test_nothing_changed_on_a_second_look_gives_no_numbers_line(tmp_path):
    ws, _ = _reviewable(tmp_path)
    session = ReviewSession(ws)
    _second_look(session)
    lines = review_lines(json.loads(ws.result_json.read_text(encoding="utf-8"))["review"])
    assert lines[0] == "On a second look without the judge, you kept all 10 of your labels."
    assert "second-look labels" not in " ".join(lines)
    assert lines[-1] == "Your first labels stay the main result."


def test_no_review_block_before_step_a_is_done(tmp_path):
    ws, _ = _reviewable(tmp_path)
    session = ReviewSession(ws)
    session.update({"id": session.items[0]["id"], "second": session.items[0]["first"]})
    assert "review" not in json.loads(ws.result_json.read_text(encoding="utf-8"))
    assert start_label.result_lines(json.loads(ws.result_json.read_text(
        encoding="utf-8")))  # still fine


def test_step_b_so_far_is_said_while_unfinished(tmp_path):
    ws, flipped = _reviewable(tmp_path)
    session = ReviewSession(ws)
    _second_look(session)
    session.update({"id": flipped["pass"][0], "choice": "judge_wrong"})
    lines = review_lines(json.loads(ws.result_json.read_text(encoding="utf-8"))["review"])
    assert ("After seeing the judge (1 of 5 so far): you called 1 judge mistake, 0 slips of "
            "yours, and 0 unclear rules.") in lines


# The result -------------------------------------------------------------------------------

def test_the_result_counts_the_disagreements_and_says_how_to_review(tmp_path):
    ws, _ = _reviewable(tmp_path)
    r = json.loads(ws.result_json.read_text(encoding="utf-8"))
    assert r["disagreements"] == 5
    lines = start_label.result_lines(r)
    assert "  Review the 5 disagreements:  judgekeeper start --review" in lines
    page = ws.result_html.read_text(encoding="utf-8")
    assert "Review the 5 disagreements" in page
    assert "<code>judgekeeper start --review</code>" in page


def test_no_review_line_without_disagreements(tmp_path):
    ws, _ = _reviewable(tmp_path, flip_pass=0, flip_fail=0)
    r = json.loads(ws.result_json.read_text(encoding="utf-8"))
    assert r["disagreements"] == 0
    assert not any("--review" in line for line in start_label.result_lines(r))


def test_a_one_disagreement_line_is_singular(tmp_path):
    ws, _ = _reviewable(tmp_path, flip_pass=1, flip_fail=0)
    lines = start_label.result_lines(json.loads(ws.result_json.read_text(encoding="utf-8")))
    assert "  Review the 1 disagreement:  judgekeeper start --review" in lines


def test_the_result_after_a_review_shows_the_lines_and_the_files(tmp_path):
    ws, flipped = _reviewable(tmp_path)
    _full_review(ws, flipped)
    r = json.loads(ws.result_json.read_text(encoding="utf-8"))
    lines = start_label.result_lines(r)
    for line in review_lines(r["review"]):
        assert f"  {line}" in lines
    assert not any("--review" in line for line in lines)  # done: nothing left to review
    page = ws.result_html.read_text(encoding="utf-8")
    assert "you called 3 judge mistakes" in page
    assert "judge-mistakes.csv" in page and "rule-unclear.csv" in page
    assert page.count("<p class=\"sentence\">") == 2  # the main sentences are unchanged


def test_the_live_result_page_has_a_review_button(tmp_path):
    ws, _ = _reviewable(tmp_path, labeled=24)
    r = json.loads(ws.result_json.read_text(encoding="utf-8"))
    html = start_label.result_html(r, back="/?token=abc")
    assert 'href="/review?token=abc"' in html and "Review them" in html


def test_the_labeling_server_switches_to_the_review(tmp_path):
    ws, _ = _reviewable(tmp_path, labeled=24)
    opened = []
    server = label_mod.LabelServer(
        StartSession(ws), port=0, page=start_label.page_template(ws.data()),
        result=start_label.result_maker(ws, say=_quiet),
        switches={"/review": start_review.switch(ws, _quiet, opened)})
    thread = threading.Thread(target=server.serve, daemon=True)
    thread.start()
    client = Client(server)
    try:
        resp, _ = client.request("GET", "/review")
        assert resp.status == 303
        assert resp.getheader("Location") == f"/?token={server.token}"
        assert client.state()["step"] == "a" and opened == [True]
        resp, _ = client.request("GET", "/review", token=False)
        assert resp.status == 403
    finally:
        server.stop()
        thread.join(5)


# The page served by `start --review` ------------------------------------------------------

def test_the_review_ends_on_the_result_page_and_stops(tmp_path):
    ws, _ = _reviewable(tmp_path)
    server, thread, client = _review_server(ws)
    try:
        for item in client.state()["items"]:
            client.label(id=item["id"], second="unsure")
        state = client.state()
        assert state["step"] == "b"
        for item in state["items"]:
            status, body = client.label(id=item["id"], choice="rule_unclear")
            assert status == 200
        assert body["summary"]["done"]
        resp, payload = client.request("GET", "/result")
        assert resp.status == 200
        assert b"you called 0 judge mistakes, 0 slips of yours, and 5 unclear rules" in payload
        thread.join(5)
        assert not thread.is_alive()
    finally:
        server.stop()


def test_step_b_page_shows_the_three_choices(tmp_path):
    ws, _ = _reviewable(tmp_path)
    page = start_review.page_template(ws)
    for needed in ("The judge was wrong", "I slipped", "The rule is unclear",
                   "See what your judge said", "Your judge said", "Your judge's reason"):
        assert needed in page, needed


# The menu ---------------------------------------------------------------------------------

@pytest.fixture
def served(monkeypatch):
    calls = []

    def serve(ws, port, open_browser, say):
        calls.append(("label", ws.dir))
        return 0

    def review(ws, port, open_browser, say):
        calls.append(("review", ws.dir))
        return 0

    monkeypatch.setattr(start_label, "serve_workspace", serve)
    monkeypatch.setattr(start_review, "serve_review", review)
    return calls


@pytest.fixture
def terminal(monkeypatch):
    answers: list[str] = []
    monkeypatch.setattr(start, "_interactive", lambda: True)

    def fake_input(prompt=""):
        print(prompt)
        return answers.pop(0) if answers else ""

    monkeypatch.setattr(builtins, "input", fake_input)
    return answers


def run(capsys, *argv):
    code = main(["start", *map(str, argv)])
    out, err = capsys.readouterr()
    return code, out, err


def test_the_menu_after_a_result(tmp_path, capsys, served, terminal):
    ws, _ = _reviewable(tmp_path)
    made = json.loads(ws.result_json.read_text(encoding="utf-8"))["made_at"][:10]
    terminal.append("4")
    code, out, _ = run(capsys, tmp_path)
    assert code == 0 and served == []
    assert f"Your last result ({made}): rough check (19 Correct, 17 Wrong)." in out
    assert "What next?" in out
    assert "  1. Review the 5 answers where you and your judge disagree   (free)" in out
    assert "  2. Ask your judge again about your 36 labeled answers       (72 calls, " in out
    assert "  3. Label more" in out and "  4. Nothing for now" in out
    assert "Choose [1-4]:" in out


def test_menu_choice_one_opens_the_review(tmp_path, capsys, served, terminal):
    ws, _ = _reviewable(tmp_path)
    terminal.append("1")
    code, _, _ = run(capsys, tmp_path)
    assert code == 0 and served == [("review", ws.dir)]


def test_menu_choice_three_opens_the_labeling_page(tmp_path, capsys, served, terminal):
    ws, _ = _reviewable(tmp_path)
    terminal.append("3")
    code, _, _ = run(capsys, tmp_path)
    assert code == 0 and served == [("label", ws.dir)]


def test_the_flags_answer_the_menu(tmp_path, capsys, served):
    ws, _ = _reviewable(tmp_path)
    code, out, _ = run(capsys, tmp_path, "--label-more")
    assert code == 0 and served == [("label", ws.dir)] and "What next?" not in out
    code, out, _ = run(capsys, tmp_path, "--review")
    assert code == 0 and served[-1] == ("review", ws.dir) and "What next?" not in out


def test_without_a_terminal_the_menu_is_printed_as_flags(tmp_path, capsys, served):
    _reviewable(tmp_path)
    code, out, _ = run(capsys, tmp_path)
    assert code == 2 and served == []
    assert "judgekeeper start --review" in out
    assert "judgekeeper start --ask-again" in out
    assert "judgekeeper start --label-more" in out
    code, out, _ = run(capsys, tmp_path, "--yes")  # --yes never picks from the menu
    assert code == 2 and served == []


def test_with_no_disagreements_the_menu_has_no_review(tmp_path, capsys, served, terminal):
    _reviewable(tmp_path, flip_pass=0, flip_fail=0)
    terminal.append("2")
    code, out, _ = run(capsys, tmp_path)
    assert code == 0
    assert "Review the" not in out
    assert "  1. Ask your judge again" in out
    assert "  2. Label more" in out and "Choose [1-3]:" in out


def test_review_with_no_disagreements_says_so(tmp_path, capsys, served):
    _reviewable(tmp_path, flip_pass=0, flip_fail=0)
    code, out, _ = run(capsys, tmp_path, "--review")
    assert code == 0 and served == []
    assert "You and your judge agree on every answer you labeled: nothing to review." in out


def test_review_without_a_result_says_to_label_first(tmp_path, capsys, served):
    promptfoo_project(tmp_path, split(20, 16))
    code, out, _ = run(capsys, tmp_path, "--review")
    assert code == 2 and served == []
    assert "There is no result to review yet." in out


def test_review_says_what_the_two_steps_are(tmp_path, capsys, served):
    ws, _ = _reviewable(tmp_path)
    code, out, _ = run(capsys, tmp_path, "--review")
    assert code == 0 and served == [("review", ws.dir)]
    assert "Review the 5 answers where you and your judge disagree. Free: no AI call." in out
    assert "Step 1: look again at 10 answers" in out
    assert "Step 2: see what your judge said" in out


def test_a_finished_review_says_its_lines_again(tmp_path, capsys, served):
    ws, flipped = _reviewable(tmp_path)
    _full_review(ws, flipped)
    code, out, _ = run(capsys, tmp_path, "--review")
    assert code == 0 and served == []
    assert "you called 3 judge mistakes" in out
    assert ".judgekeeper/judge-mistakes.csv" in out


def test_the_menu_follows_a_recheck_at_a_terminal(tmp_path, capsys, served, terminal):
    from tests.test_start_again import _rewrite

    _reviewable(tmp_path)
    _rewrite(tmp_path, split(16, 20))
    terminal.append("3")
    code, out, _ = run(capsys, tmp_path)
    assert code == 0
    assert out.index("now.") < out.index("What next?")


def test_review_and_new_cannot_be_used_together(tmp_path, capsys, served):
    _reviewable(tmp_path)
    code, _, err = run(capsys, tmp_path, "--review", "--new")
    assert code == 2 and "not allowed with argument" in err
    assert Workspace(tmp_path).result_json.is_file()


def test_resuming_at_step_b_says_so(tmp_path, capsys, served):
    ws, _ = _reviewable(tmp_path)
    _second_look(ReviewSession(ws))
    code, out, _ = run(capsys, tmp_path, "--review")
    assert code == 0 and served == [("review", ws.dir)]
    assert "You looked again at all 10 answers. Carrying on at step 2." in out
