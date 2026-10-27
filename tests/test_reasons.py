"""Why the person disagrees with the LLM-as-a-judge: the reasons they tap on the live result page.

On each disagreement the person can see (never a mark kept aside), the result page asks "Why
did you mark it Fail?" (or Pass), with reasons to tap, buttons from the parts of their own
rule, their own reasons as buttons, an "Other…" box and "Mark this part" for words in the
answer. Each change is a stamped line in marks.jsonl with the same mark. report.html shows the
reasons read-only; `fix` counts them (plain counting, no AI), groups mistakes.md by them and
writes suggestions.md. judgekeeper never changes the rule. No test calls an API.
"""

from __future__ import annotations

import http.client
import json
import re
import threading
import urllib.request
from urllib.parse import urlsplit

import pytest

from judgekeeper import (
    batches,
    fix,
    marks,
    page,
    reasons,
    report_page,
    start,
    start_label,
)
from judgekeeper.cli import main
from judgekeeper.project import move_to_previous
from judgekeeper.start_label import StartSession, Workspace
from tests.start_projects import promptfoo_data
from tests.test_fix import TAG, N, _outputs, project
from tests.test_fix import run as run_fix
from tests.test_front import assert_one_next_at_the_end
from tests.test_label_server import Client

RULE = ("Every claim is supported by the article. The answer is polite; it never promises a "
        "refund.")
PARTS = ["Every claim is supported by the article", "The answer is polite",
         "it never promises a refund"]
KEPT = ("this answer is not on your result page yet: reasons are only for the disagreements "
        "it lists")


def _ready(root, rule: str = RULE):
    """A project with a result: (workspace, seen mistakes the LLM-as-a-judge passed, seen mistakes it
    failed, mistakes kept aside)."""
    ws = project(root, rule=rule)
    start_label.store_result(ws, StartSession(ws))  # the first result: some marks kept aside
    split = fix.read_split(ws)
    m = fix.Marks(ws)
    seen = [i for i in split.seen if m.person[i] != m.judge[i]]
    hidden = [i for i in split.hidden if m.person[i] != m.judge[i]]
    return (ws, [i for i in seen if m.judge[i] == "pass"],
            [i for i in seen if m.judge[i] == "fail"], hidden)


def _say(ws, item_id: str, **body):
    StartSession(ws).update({"id": item_id, **body})


def _lines(ws) -> list[dict]:
    return [json.loads(x) for x in ws.marks.read_text(encoding="utf-8").splitlines()][1:]


def _live(ws) -> str:
    """The result page as the marking page serves it at /result."""
    return start_label.live_result(ws, StartSession(ws), back="/?token=t")


def _report(ws) -> str:
    return ws.report_html.read_text(encoding="utf-8")


@pytest.fixture
def here(tmp_path, monkeypatch):
    root = tmp_path / "support-bot"
    root.mkdir()
    monkeypatch.chdir(root)
    return root


@pytest.fixture
def served():
    started = []

    def start(ws):
        server = page.page_server(ws, 0)
        thread = threading.Thread(target=server.serve, daemon=True)
        thread.start()
        started.append((server, thread))
        return Client(server)

    yield start
    for server, thread in started:
        server.stop()
        thread.join(timeout=5)


# Saving --------------------------------------------------------------------------------------

def test_a_post_with_only_reasons_keeps_the_mark_and_adds_a_stamped_line(here, served):
    ws, passes, _, _ = _ready(here)
    client = served(ws)
    before = len(_lines(ws))
    status, _ = client.label(id=passes[0], reasons=["wrong_fact", "rule_silent"],
                             note="Says 2019, the article says 2021")
    assert status == 200
    added = _lines(ws)[before:]
    assert len(added) == 1
    line = added[0]
    assert line["mark"] == "fail" and line["id"] == passes[0]
    assert line["reasons"] == ["wrong_fact", "rule_silent"]
    assert line["note"] == "Says 2019, the article says 2021"
    assert line["by"] == "page" and line["at"] and line["sitting"]
    assert marks.read(ws.marks).counted()[passes[0]] == "fail"


def test_a_post_with_only_a_note_keeps_the_taps_and_the_other_way_round(here):
    ws, passes, _, _ = _ready(here)
    _say(ws, passes[0], reasons=["rule_silent"], spans=[[0, 3]])
    _say(ws, passes[0], note="The price has no currency")
    last = marks.read(ws.marks).last[passes[0]]
    assert last["reasons"] == ["rule_silent"] and last["note"] == "The price has no currency"
    assert last["spans"] == [[0, 3]]
    _say(ws, passes[0], reasons=["wrong_fact"])
    last = marks.read(ws.marks).last[passes[0]]
    assert last["reasons"] == ["wrong_fact"] and last["note"] == "The price has no currency"


def test_a_reason_before_the_result_page_is_refused_and_sets_nothing_aside(here):
    ws = project(here)  # marked, no result page opened yet: nothing kept aside so far
    m = fix.Marks(ws)
    wrong = [i for i in m.person if m.person[i] != m.judge[i]]
    for i in wrong:
        with pytest.raises(ValueError) as e:
            _say(ws, i, reasons=["rule_silent"])
        assert str(e.value) == KEPT
    assert fix.read_split(ws) is None
    assert all("reasons" not in marks.read(ws.marks).last[i] for i in wrong)


def test_a_reason_line_keeps_the_time_of_the_mark(here):
    ws, passes, _, _ = _ready(here)
    at = marks.read(ws.marks).last[passes[0]]["at"]
    seconds = marks.read(ws.marks).last[passes[0]]["seconds"]
    _say(ws, passes[0], reasons=["no_answer"])
    last = marks.read(ws.marks).last[passes[0]]
    assert (last["at"], last["seconds"], last["reasons"]) == (at, seconds, ["no_answer"])


def test_the_page_shows_the_saved_taps_and_note_again(here):
    ws, passes, _, _ = _ready(here)
    _say(ws, passes[0], reasons=["wrong_fact"], note="Wrong year")
    html = _live(ws)
    row = _box(html, passes[0])
    assert re.search(r'aria-pressed="true"[^>]*data-reason="wrong_fact"', row)
    assert re.search(r'aria-pressed="false"[^>]*data-reason="no_answer"', row)
    assert 'value="Wrong year"' in row


def test_an_unknown_reason_id_is_refused(here, served):
    ws, passes, _, _ = _ready(here)
    client = served(ws)
    status, body = client.label(id=passes[0], reasons=["too_long"])
    assert status == 400 and "too_long" in body["error"]
    assert "reasons" not in marks.read(ws.marks).last[passes[0]]


def test_reasons_must_be_a_list_of_ids(here):
    ws, passes, _, _ = _ready(here)
    for bad in ("wrong_fact", [1], ["wrong_fact", "wrong_fact"], None):
        with pytest.raises(ValueError):
            _say(ws, passes[0], reasons=bad)


def test_a_reason_needs_a_pass_or_fail_mark_first(here):
    ws, _, _, _ = _ready(here)
    unmarked = [i["id"] for i in StartSession(ws).items if not i["label"]]
    if unmarked:
        with pytest.raises(ValueError):
            _say(ws, unmarked[0], reasons=["wrong_fact"])


def test_reasons_are_only_for_answers_you_and_your_judge_disagree_on(here):
    ws, _, _, _ = _ready(here)
    m = fix.Marks(ws)
    agreed = next(i for i in fix.read_split(ws).seen if m.person[i] == m.judge[i])
    with pytest.raises(ValueError, match="disagree"):
        _say(ws, agreed, reasons=["wrong_fact"])


def test_more_than_500_characters_is_refused(here, served):
    ws, passes, _, _ = _ready(here)
    client = served(ws)
    status, body = client.label(id=passes[0], reasons=[], note="x" * 501)
    assert status == 400 and "500" in body["error"]
    status, _ = client.label(id=passes[0], reasons=[], note="x" * 500)
    assert status == 200


def test_a_secret_in_a_note_is_redacted(here):
    ws, passes, _, _ = _ready(here)
    key = "sk-ant-" + "api03-abcdefghijklmnopqrstuvwxyz0123456789"
    _say(ws, passes[0], reasons=[], note=f"It printed {key}")
    assert key not in ws.marks.read_text(encoding="utf-8")
    assert "[REDACTED]" in marks.read(ws.marks).last[passes[0]]["note"]


def test_an_empty_box_clears_the_note(here):
    ws, passes, _, _ = _ready(here)
    _say(ws, passes[0], reasons=[], note="Wrong year")
    _say(ws, passes[0], reasons=[], note="")
    assert not marks.read(ws.marks).last[passes[0]].get("note")
    assert 'value=""' in _box(_live(ws), passes[0])


def test_a_new_mark_keeps_reasons_only_when_the_same(here):
    ws, passes, _, _ = _ready(here)
    _say(ws, passes[0], reasons=["wrong_fact"])
    _say(ws, passes[0], label="fail", seconds=3)
    assert marks.read(ws.marks).last[passes[0]]["reasons"] == ["wrong_fact"]
    _say(ws, passes[0], label="pass", seconds=3)
    assert "reasons" not in marks.read(ws.marks).last[passes[0]]


# "I'm not sure about my own mark" ------------------------------------------------------------

def test_not_sure_never_changes_the_mark_and_is_counted(here, capsys):
    ws, passes, fails, _ = _ready(here)
    _say(ws, passes[0], reasons=["unsure"])
    _say(ws, fails[0], reasons=["unsure", "rule_silent"])
    counted = marks.read(ws.marks).counted()
    assert (counted[passes[0]], counted[fails[0]]) == ("fail", "pass")
    made = marks.made(marks.read(ws.marks))
    assert made["unsure"] == 2
    assert "You weren't sure about 2 of your marks." in start_label.made_lines(made)
    assert "You weren't sure about 2 of your marks." in _flat(_report(ws))


def test_measure_says_how_many_marks_you_werent_sure_about(here, capsys):
    from judgekeeper.cli import main

    ws, passes, _, _ = _ready(here)
    _say(ws, passes[0], reasons=["unsure"])
    capsys.readouterr()
    main(["--no-browser"])
    main(["--stop"])
    out = capsys.readouterr().out
    assert "You weren't sure about 1 of your marks." in out


# Changing a mark after the result page --------------------------------------------------------

def test_a_mark_changed_after_seeing_the_grades_is_stamped_and_counted(here):
    ws, passes, _, _ = _ready(here)  # the result page with the disagreements was made
    _say(ws, passes[0], label="pass", seconds=4)
    line = _lines(ws)[-1]
    assert line["mark"] == "pass" and line["after_result"] is True
    made = marks.made(marks.read(ws.marks))
    assert made["after_result"] == 1
    said = "You changed 1 mark after seeing your LLM-as-a-judge's grades."
    assert said in start_label.made_lines(made)
    assert _flat(_live(ws)).count(said) == 1


def test_a_mark_changed_before_any_grade_was_shown_is_not_stamped(here):
    ws = project(here, marked=20)  # too few marks for a result: no grade shown yet
    item = next(i for i in StartSession(ws).items if i["label"])
    _say(ws, item["id"], label="fail" if item["label"] == "pass" else "pass", seconds=4)
    assert "after_result" not in _lines(ws)[-1]


def test_a_first_mark_after_the_result_page_is_not_a_change(here):
    ws = project(here, marked=44)
    start_label.store_result(ws, StartSession(ws))
    new = next(i for i in StartSession(ws).items if not i["label"])
    _say(ws, new["id"], label="pass", seconds=4)
    assert "after_result" not in _lines(ws)[-1]


def test_the_result_page_has_no_button_to_change_a_mark(here):
    ws, _, _, _ = _ready(here)
    html = _live(ws)
    assert '"label"' not in html and "label:" not in report_page.REASONS_SCRIPT
    buttons = re.findall(r"<button[^>]*>(.*?)</button>", html, re.DOTALL)
    assert not any(b.strip() in ("Pass", "Fail") for b in buttons)


# Buttons from the person's own rule -----------------------------------------------------------

@pytest.mark.parametrize("rule, parts", [
    (RULE, PARTS),
    ("1. The answer is correct.\n2. It cites the article.\n3) It is short.",
     ["The answer is correct", "It cites the article", "It is short"]),
    ("- Correct facts only\n- No promises of refunds\n* Polite tone",
     ["Correct facts only", "No promises of refunds", "Polite tone"]),
    ("The answer is correct, cites the article and is polite.",
     ["The answer is correct", "cites the article", "is polite"]),
    ("The answer solves the customer's problem and is polite.", []),  # one part: no buttons
    ("", []),
])
def test_the_rule_is_split_into_its_parts_by_plain_text_rules(rule, parts):
    assert reasons.split_rule(rule) == parts


def test_at_most_6_parts_each_cut_to_60_characters_on_a_word():
    rule = " ".join(f"Rule {n} says the answer must mention the {n}th thing very clearly and "
                    "without any doubt at all." for n in range(1, 9))
    parts = reasons.split_rule(rule)
    assert len(parts) == 6
    assert all(len(p) <= 60 for p in parts) and parts[0].endswith("…")
    assert " ".join(parts[0][:-1].split()) == parts[0][:-1]  # cut on a word


FACTS_FIRST = ("Hours are Monday to Friday. Returns take 30 days. Shipping is free over $50. "
               "Support is by email. Refunds go to the card. The store is open 9am to 6pm. "
               "Gift cards never expire. Fail any answer that promises a refund.")


def test_a_long_rule_offers_its_first_parts_and_its_last():
    parts = reasons.split_rule(FACTS_FIRST)
    assert len(parts) == 6
    assert parts[:5] == ["Hours are Monday to Friday", "Returns take 30 days",
                         "Shipping is free over $50", "Support is by email",
                         "Refunds go to the card"]
    assert parts[5] == "Fail any answer that promises a refund"
    assert reasons.parts_left_out({"rule": FACTS_FIRST, "tool": "promptfoo"}) == 2
    assert reasons.parts_left_out({"rule": RULE, "tool": "promptfoo"}) == 0


def test_the_page_says_other_covers_the_parts_left_out(here):
    ws, passes, fails, _ = _ready(here, rule=FACTS_FIRST)
    box = _box(_live(ws), (passes or fails)[0])
    assert "6. Fail any answer that promises a refund" in box
    assert "“Other…” covers the 2 other parts of your rule." in box


def test_no_line_about_other_parts_when_every_part_has_a_button(here):
    ws, passes, fails, _ = _ready(here)
    assert "covers the" not in _box(_live(ws), (passes or fails)[0])


def test_no_rule_buttons_without_one_rule_for_every_answer():
    assert reasons.rule_parts({"rule": RULE, "tool": "promptfoo", "one_rule": False}) == []
    assert reasons.rule_parts({"rule": None, "tool": "promptfoo"}) == []
    assert reasons.rule_parts({"rule": RULE, "tool": "promptfoo"}) == PARTS


def test_rule_buttons_come_first_with_their_question(here):
    ws, passes, fails, _ = _ready(here)
    html = _live(ws)
    judge_passed, judge_failed = _box(html, passes[0]), _box(html, fails[0])
    assert "Which part of your rule does this answer break?" in judge_passed
    assert "Which part did your LLM-as-a-judge get wrong?" in judge_failed
    assert judge_passed.index('data-part="1"') < judge_passed.index('data-reason=')
    assert "Every claim is supported by the article" in judge_passed


def test_a_rule_with_one_part_gives_only_the_general_buttons(here):
    ws, passes, _, _ = _ready(here, rule="The answer solves the customer's problem and is "
                                          "polite.")
    box = _box(_live(ws), passes[0])
    assert "data-part=" not in box and 'data-reason="wrong_fact"' in box


def test_the_rule_is_shown_on_the_marking_page_only_behind_its_button(here):
    ws, _, _, _ = _ready(here)
    marking = start_label.page_template(ws.data())
    box = marking.split('<div class="rule" id="rule" hidden>', 1)[1].split("</div>", 1)[0]
    assert "supported by the article" in box
    assert marking.count("supported by the article") == 1


def test_rule_parts_are_saved_by_index_with_the_rules_hash(here):
    from judgekeeper.fingerprint import rule_hash

    ws, passes, _, _ = _ready(here)
    _say(ws, passes[0], reasons=[], rule_parts=[2])
    line = _lines(ws)[-1]
    assert line["rule_parts"] == [2] and line["rule_hash"] == rule_hash(RULE)
    for bad in ([0], [4], ["2"], [2, 2]):
        with pytest.raises(ValueError):
            _say(ws, passes[0], reasons=[], rule_parts=bad)


def test_fix_counts_the_rule_parts(here, capsys):
    ws, passes, _, _ = _ready(here)
    for i in passes[:2]:
        _say(ws, i, reasons=[], rule_parts=[1])
    _, out = run_fix(capsys)
    assert ("Your marks say your LLM-as-a-judge misses rule part 1, 'Every claim is supported "
            "by the article' (2).") in " ".join(out.split())


def test_rule_parts_of_an_older_rule_are_not_counted(here):
    ws, passes, _, _ = _ready(here)
    _say(ws, passes[0], reasons=[], rule_parts=[1])
    lines = ws.marks.read_text(encoding="utf-8").replace(
        _lines(ws)[-1]["rule_hash"], "sha256:" + "0" * 64)
    ws.marks.write_text(lines, encoding="utf-8")
    assert fix.Marks(ws).row(passes[0])["parts"] == []


# Point at the problem ------------------------------------------------------------------------

def test_marked_words_are_saved_as_offsets_at_most_3(here):
    ws, passes, _, _ = _ready(here)
    _say(ws, passes[0], reasons=[], spans=[[0, 6], [10, 14]])
    line = _lines(ws)[-1]
    assert line["spans"] == [[0, 6], [10, 14]]
    assert not any(isinstance(v, str) and "Answer" in v for v in line.values())  # not text
    for bad in ([[0, 1], [2, 3], [4, 5], [6, 7]], [[5, 5]], [[3, 1]], [[0, 100000]],
                [["0", 1]], [[0]]):
        with pytest.raises(ValueError):
            _say(ws, passes[0], reasons=[], spans=bad)


def test_marked_words_are_bold_in_the_answer_on_the_page_and_in_mistakes_md(here, capsys):
    ws, passes, _, _ = _ready(here)
    text = reasons.canonical(fix.Marks(ws).row(passes[0])["output"])
    start = text.index("refund")
    _say(ws, passes[0], reasons=["wrong_fact"], spans=[[start, start + 6]])
    assert '<b class="hl">refund</b>' in _box_row(_live(ws), passes[0])
    run_fix(capsys)
    md = (ws.dir / "fix" / "mistakes.md").read_text(encoding="utf-8")
    assert "**refund**" in md


def test_the_page_has_a_mark_this_part_button_for_each_box(here):
    ws, passes, _, _ = _ready(here)
    box = _box(_live(ws), passes[0])
    assert re.search(r'<button type="button" class="mark-part"[^>]*hidden>Mark this part'
                     r"</button>", box)


# The person's own reasons become taps ---------------------------------------------------------

def test_other_text_becomes_a_button_on_every_other_disagreement(here):
    ws, passes, fails, _ = _ready(here)
    _say(ws, passes[0], reasons=[], note="Gives a price without the currency")
    own = reasons.own_chips(ws)
    assert [c["text"] for c in own] == ["Gives a price without the currency"]
    assert json.loads((ws.dir / "reasons.json").read_text(encoding="utf-8"))["own"] == own
    html = _live(ws)
    chip = f'data-reason="{own[0]["id"]}"'
    assert chip in _box(html, passes[1]) and chip in _box(html, fails[0])
    assert chip not in _box(html, passes[0])  # its own answer has the words in the box
    _say(ws, passes[1], reasons=[own[0]["id"]])
    assert marks.read(ws.marks).last[passes[1]]["reasons"] == [own[0]["id"]]


def test_typing_on_changes_the_button_and_never_makes_one_per_save(here):
    ws, passes, _, _ = _ready(here)
    for text in ("Gives", "Gives a price", "Gives a price without the currency"):
        _say(ws, passes[0], reasons=[], note=text)
    assert [c["text"] for c in reasons.own_chips(ws)] == ["Gives a price without the currency"]
    _say(ws, passes[0], reasons=[], note="")
    assert reasons.own_chips(ws) == []


def test_at_most_8_of_your_own_buttons(here, monkeypatch):
    monkeypatch.setattr(fix, "HIDDEN_TENTHS", 3)  # enough mistakes left to see for 9 buttons
    ws, passes, fails, _ = _ready(here)
    ids = (passes + fails)[:9]
    assert len(ids) == 9
    for n, i in enumerate(ids):
        _say(ws, i, reasons=[], note=f"My reason number {n}")
    assert len(reasons.own_chips(ws)) == 8


# Only marks the person can see ----------------------------------------------------------------

def test_a_kept_aside_mark_gets_no_box_and_its_post_is_refused(here, served):
    ws, _, _, hidden = _ready(here)
    assert hidden
    html = _live(ws)
    assert all(f'data-id="{i}"' not in html for i in hidden)
    client = served(ws)
    status, body = client.label(id=hidden[0], reasons=["wrong_fact"])
    assert status == 400 and body["error"] == KEPT
    status, body = client.label(id=hidden[0], note="sneaky")
    assert status == 400 and body["error"] == KEPT
    assert all("reasons" not in x and "note" not in x for x in _lines(ws) if x["id"] in hidden)


def test_a_mark_post_cannot_carry_a_note_or_reasons(here, served):
    ws, _, _, hidden = _ready(here)
    client = served(ws)
    group = fix.Marks(ws).judge[hidden[0]]
    mark = "fail" if group == "pass" else "pass"
    for extra in ({"note": "sneaky"}, {"reasons": ["wrong_fact"]}):
        status, _ = client.label(id=hidden[0], label=mark, seconds=2, **extra)
        assert status == 400
    assert all("reasons" not in x and "note" not in x for x in _lines(ws) if x["id"] in hidden)


def test_reasons_on_a_kept_aside_mark_are_never_used(here, capsys):
    ws, passes, _, hidden = _ready(here)
    group = fix.Marks(ws).judge[hidden[0]]
    marks.append(ws.marks, marks.stamp(hidden[0], "fail" if group == "pass" else "pass",
                                       group, None, "s", why={"reasons": ["wrong_fact"],
                                                              "note": "HIDDEN-WORDS"}))
    _say(ws, passes[0], reasons=["wrong_fact"])
    _, out = run_fix(capsys)
    assert "it has a wrong fact (1)" in " ".join(out.split())
    for name in ("mistakes.md", "suggestions.md"):
        assert "HIDDEN-WORDS" not in (ws.dir / "fix" / name).read_text(encoding="utf-8")


# Where reasons show up ------------------------------------------------------------------------

def test_report_html_shows_reasons_read_only_with_no_input(here):
    ws, passes, _, _ = _ready(here)
    _say(ws, passes[0], reasons=["wrong_fact", "rule_silent"], note="Wrong year")
    html = _report(ws)
    assert not re.search(r"<(input|textarea)\b|<[^>]*\saria-pressed=", html)
    flat = _flat(html)
    assert ("Your reason: it has a wrong fact; the rule doesn't say how to judge this; "
            "“Wrong year”") in flat
    assert "Add a reason" not in flat
    assert re.findall(r"<script>(.*?)</script>", html, re.DOTALL) == [report_page.SCRIPT]


def test_the_live_page_asks_why_and_says_fix_uses_the_reasons(here):
    ws, passes, fails, _ = _ready(here)
    html = _live(ws)
    assert "Add a reason to any answer below. <code>fix</code> uses them." in html
    assert "Why did you mark it Fail?" in _box(html, passes[0])
    assert "Why did you mark it Pass?" in _box(html, fails[0])
    for words in ("It has a wrong fact", "It doesn't answer the question",
                  "It leaves out something important", "It's unsafe or not allowed",
                  "Wrong format or tone", "The rule doesn't say how to judge this",
                  "I'm not sure about my own mark", "Other…"):
        assert _e(words) in _box(html, passes[0]), words
    for words in ("It's right, just worded differently", "Small slips don't matter here",
                  "Short, but it answers the question",
                  "The LLM-as-a-judge wanted something I didn't ask for"):
        assert _e(words) in _box(html, fails[0]) and _e(words) not in _box(html, passes[0])


def test_the_live_page_may_post_and_report_html_may_not(here):
    ws, _, _, _ = _ready(here)
    live = _live(ws)
    assert "connect-src 'self'" in live and report_page.script_csp(live=True) in live
    assert "connect-src" not in _report(ws)


def test_mistakes_md_says_your_reason_and_you_said(here, capsys):
    ws, passes, _, _ = _ready(here)
    _say(ws, passes[0], reasons=["wrong_fact"], rule_parts=[1], note="Wrong year")
    run_fix(capsys)
    md = (ws.dir / "fix" / "mistakes.md").read_text(encoding="utf-8")
    assert "<<<YOUR REASON\nWrong year\nYOUR REASON>>>" in md and "YOUR NOTE" not in md
    assert "You said: it has a wrong fact; rule part 1." in md


def test_fix_counts_the_reasons_and_prints_the_two_lines_at_2_or_more(here, capsys):
    ws, passes, fails, _ = _ready(here)
    _say(ws, passes[0], reasons=["wrong_fact", "rule_silent"])
    _say(ws, passes[1], reasons=["wrong_fact"])
    _say(ws, fails[0], reasons=["rule_silent", "short_ok"])
    _, out = run_fix(capsys)
    flat = " ".join(out.split())
    assert ("Your reasons for your LLM-as-a-judge's mistakes: it has a wrong fact (2), the "
            "rule doesn't say how to judge this (2), short, but it answers the question (1)."
            ) in flat
    assert ("Your LLM-as-a-judge's rule may be missing something: write in it how to judge "
            "these answers.") in flat
    assert ("Your LLM-as-a-judge says Pass on answers with wrong facts: say in the rule that "
            "one wrong fact is a Fail.") in flat
    assert flat.index("Your reasons for") < flat.index("Your LLM-as-a-judge made")  # first


def test_one_tap_prints_no_extra_line(here, capsys):
    ws, passes, _, _ = _ready(here)
    _say(ws, passes[0], reasons=["wrong_fact", "rule_silent"])
    _, out = run_fix(capsys)
    flat = " ".join(out.split())
    assert "Your reasons for your LLM-as-a-judge's mistakes: it has a wrong fact (1)" in flat
    assert "rule may be missing" not in flat and "wrong facts" not in flat


def test_mistakes_md_groups_the_mistakes_by_their_most_tapped_reason(here, capsys):
    ws, passes, fails, _ = _ready(here)
    _say(ws, passes[0], reasons=["unsure", "wrong_fact"])
    _say(ws, passes[1], reasons=["wrong_fact"])
    _say(ws, passes[2], reasons=["wrong_fact", "no_answer"], note="Off topic")
    _say(ws, fails[0], reasons=["short_ok"])
    run_fix(capsys)
    md = (ws.dir / "fix" / "mistakes.md").read_text(encoding="utf-8")
    heads = re.findall(r"^## (Your reason: .*|No reason given.*|You weren't sure.*)$", md,
                       re.MULTILINE)
    assert heads[0] == "Your reason: it has a wrong fact (2)"
    assert heads[1] == "Your reason: short, but it answers the question (1)"
    assert heads[-1] == "You weren't sure about your mark"  # the last group, no count
    assert md.index("Off topic") < md.index("Your reason: short")  # its note beside it


def test_clue_words_come_from_answers_only_never_from_reasons(here, capsys):
    ws, passes, _, _ = _ready(here)
    for i in passes[:4]:
        _say(ws, i, reasons=[], note="Zebrafish zebrafish")
    _, out = run_fix(capsys)
    words = [x for x in " ".join(out.split()).split("Words found") if x][1:]
    assert not any("zebrafish" in w for w in words)


def test_without_reasons_mistakes_md_is_as_before(here, capsys):
    ws, _, _, _ = _ready(here)
    run_fix(capsys)
    md = (ws.dir / "fix" / "mistakes.md").read_text(encoding="utf-8")
    assert "Your reason:" not in md and "You said:" not in md
    assert not (ws.dir / "fix" / "suggestions.md").exists()


# Using both explanations ------------------------------------------------------------------------

def _mark_words(ws, item_id: str, words: str):
    text = reasons.canonical(fix.Marks(ws).row(item_id)["output"])
    start = text.index(words)
    _say(ws, item_id, reasons=["wrong_fact"], spans=[[start, start + len(words)]])


def test_missed_it_when_the_judges_reason_never_mentions_the_marked_words(here, capsys):
    ws, passes, _, _ = _ready(here)
    for i in passes[:2]:
        _mark_words(ws, i, "refund")
    _, out = run_fix(capsys)
    assert ("Your LLM-as-a-judge didn't mention the part you marked in 2 of 2 answers: it "
            "seems to miss these problems. A clearer rule may help, or a stronger model."
            ) in " ".join(out.split())


def test_allowed_it_when_the_judge_named_marked_words(here, capsys):
    ws, passes, _, _ = _ready(here)
    for i in passes[:2]:  # the judge's reason is "reason N", the answer "Answer N. ..."
        number = re.match(r"Answer (\d+)", fix.Marks(ws).row(i)["output"])[0]
        _mark_words(ws, i, number)
    _, out = run_fix(capsys)
    assert ("In 2 answers your LLM-as-a-judge mentioned the part you marked but still said "
            "Pass: your rule seems to allow this. Say in the rule that it's a Fail."
            ) in " ".join(out.split())


def test_the_missed_or_allowed_lines_need_only_one_answer():
    rows = [{"judge": "pass", "final": "fail", "output": "Costs 40 pebbles.",
             "reason": "Says 40 pebbles, fine.", "spans": [[6, 16]]},
            {"judge": "pass", "final": "fail", "output": "Costs 40 pebbles.",
             "reason": "Looks right.", "spans": [[6, 16]]}]
    lines = " ".join(reasons.clue_lines(rows))
    assert "didn't mention the part you marked in 1 of 2 answers" in lines
    assert ("In 1 answer your LLM-as-a-judge mentioned the part you marked but still said "
            "Pass: your rule seems to allow this.") in lines


def test_the_check_matches_numbers_and_rare_words_ignoring_case():
    rows = [{"judge": "pass", "final": "fail", "output": "It costs 40 Dollars today.",
             "reason": "The price of 40 is right.", "spans": [[9, 11]]},
            {"judge": "pass", "final": "fail", "output": "Ships to MARS soon.",
             "reason": "mars delivery is fine", "spans": [[9, 13]]},
            {"judge": "pass", "final": "fail", "output": "It is about the weather.",
             "reason": "Clear answer.", "spans": [[0, 8]]}]
    assert reasons.mentioned(rows) == (2, 1)  # (mentioned, not mentioned)


def test_suggestions_md_reason_lines(here, capsys, monkeypatch):
    monkeypatch.setattr(fix, "HIDDEN_TENTHS", 3)  # two seen mistakes the LLM-as-a-judge failed
    ws, passes, fails, _ = _ready(here)
    _say(ws, passes[0], reasons=["wrong_fact", "left_out"], note="the order number")
    _say(ws, passes[1], reasons=["wrong_fact", "left_out"])
    _say(ws, passes[2], reasons=["unsafe"], rule_parts=[3])
    _say(ws, fails[0], reasons=["short_ok"])
    _say(ws, fails[1], reasons=["short_ok"])
    _, out = run_fix(capsys)
    md = (ws.dir / "fix" / "suggestions.md").read_text(encoding="utf-8")
    suggested, once = md.split("## Seen once (not suggested yet)")
    assert "- Fail an answer with any wrong fact, even a small one." in suggested
    assert ("- Fail an answer that leaves out what you wrote below. (2 answers)\n"
            "<<<YOUR REASON\nthe order number\nYOUR REASON>>>") in suggested
    assert "- A short answer that answers the question is a Pass." in suggested
    assert "unsafe" not in suggested.lower()
    assert "Fail an answer that is unsafe or not allowed." in once
    assert ("Make this part of your rule more exact: 'it never promises a refund'. Your LLM-as-a-judge "
            "missed it 1 time.") in once
    assert "<<<ANSWER" in once  # listed with its answer, fenced as data
    assert "Fail when: “the order number”" in once  # the person's own button
    flat = " ".join(out.split())
    assert ("Suggestions from your reasons are in .judgekeeper/fix/suggestions.md. Copy the "
            "ones you agree with into your rule where your eval keeps it.") in flat
    assert not (ws.dir / "fix" / "rule.txt").exists()


@pytest.mark.parametrize("reason, line", [
    ("wrong_fact", "Fail an answer with any wrong fact, even a small one."),
    ("no_answer", "Fail an answer that doesn't answer the question asked."),
    ("left_out", "Fail an answer that leaves out something important."),
    ("worded_differently",
     "Pass a correct answer even when its words differ from what you expect."),
    ("small_slips", "Small slips in spelling or format don't make an answer Fail."),
    ("short_ok", "A short answer that answers the question is a Pass."),
    ("rule_silent", "Your rule doesn't cover 2 answers: write how to judge them."),
])
def test_each_suggested_line_comes_from_a_fixed_template(reason, line):
    judge = "fail" if reason in ("worded_differently", "small_slips", "short_ok") else "pass"
    rows = [{"id": f"a{n}", "judge": judge, "final": "fail" if judge == "pass" else "pass",
             "output": "An answer.", "reasons": [reason], "words": {}, "parts": [],
             "spans": [], "why": ""} for n in range(2)]
    assert f"- {line}" in reasons.suggestions_md(rows).split("## Seen once")[0]


def test_your_own_button_tapped_on_passes_is_pass_even_when(here):
    rows = [{"id": f"a{n}", "judge": "fail", "final": "pass", "output": "An answer.",
             "reasons": ["own-1"], "words": {"own-1": "No greeting"}, "parts": [],
             "spans": [], "why": ""} for n in range(2)]
    assert "- Pass even when: “No greeting”" in reasons.suggestions_md(rows)


# Batches, check and --new -----------------------------------------------------------------------

def test_new_moves_the_reasons_with_the_marks(here):
    ws, passes, _, _ = _ready(here)
    _say(ws, passes[0], reasons=[], note="My own words")
    target = move_to_previous(ws, lambda line: None)
    assert (target / "reasons.json").is_file() and (target / "marks.jsonl").is_file()
    assert not (ws.dir / "reasons.json").exists()


# Words ---------------------------------------------------------------------------------------

def test_the_reference_and_the_terminal_say_what_the_reasons_are_for():
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    reference = (root / "docs" / "reference.md").read_text(encoding="utf-8")
    assert "say why" in reference.lower() and "suggestions.md" in reference
    # the Guide keeps to the steps; the terminal says what the reasons are for
    from judgekeeper import start_label

    assert "uses your reasons" in start_label.SAY_WHY_FIX


# Helpers --------------------------------------------------------------------------------------

def _e(text: str) -> str:
    from html import escape

    return escape(text)


def _flat(html: str) -> str:
    from html import unescape

    return " ".join(unescape(re.sub(r"<[^>]+>", " ", html)).split())


def _box(html: str, item_id: str) -> str:
    """The reason box of one answer on the live page."""
    found = re.search(rf'<div class="why" data-id="{re.escape(item_id)}".*?</div></td></tr>',
                      html, re.DOTALL)
    assert found, item_id
    return found[0]


def _box_row(html: str, item_id: str) -> str:
    """The table row before an answer's reason box: its question, answer and judge's reason."""
    at = html.index(f'data-id="{item_id}"')
    return html[html.rindex("<tr", 0, html.rindex("<tr", 0, at)):at]


def test_the_workspace_has_the_reasons_file_name():
    assert reasons.FILE == "reasons.json" and Workspace(".").dir.name == ".judgekeeper"


# Every chip is a button ------------------------------------------------------------------------

def test_every_reason_chip_is_a_button_with_aria_pressed_and_its_id(here):
    ws, passes, fails, _ = _ready(here)
    _say(ws, passes[0], note="Gives a price without the currency")  # one of the person's own
    for item in (passes[1], fails[0]):
        chips = re.findall(r"<(\w+)([^>]*)class=\"chip\"([^>]*)>", _box(_live(ws), item))
        assert chips, item
        for tag, before, after in chips:
            attrs = before + after
            assert tag == "button" and 'type="button"' in attrs
            if "other" in attrs:
                assert 'aria-expanded="' in attrs  # Other… opens the box: not a reason
                continue
            assert re.search(r'aria-pressed="(true|false)"', attrs), attrs
            found = re.search(r'data-reason="([^"]+)"|data-part="(\d+)"', attrs)
            assert found, attrs
            if found[1]:
                assert found[1] in reasons.REASONS or found[1].startswith(reasons.OWN)


# Batches -------------------------------------------------------------------------------------

def _grow(root, n: int) -> list[str]:
    """The eval ran on `n` questions (more than before, the old ones kept): the new answers
    join as a batch; their ids."""
    half = n // 2
    data = promptfoo_data([True] * half + [False] * (n - half), rubric=RULE, tag=TAG,
                          outputs=_outputs(n))
    data["metadata"]["promptfooVersion"] = "0.124.1"
    (root / "results.json").write_text(json.dumps(data), encoding="utf-8")
    ws = Workspace(root)
    before = {q["id"] for q in ws.data()["queue"]}
    assert batches.add(ws, start.find_judge(root)) == n - N
    return [q["id"] for q in ws.data()["queue"] if q["id"] not in before]


def test_a_new_batchs_disagreements_get_boxes_the_same_way(here, served):
    ws, _, _, _ = _ready(here)
    new = _grow(here, N + 10)
    judge = {q["id"]: q["group"] for q in ws.data()["queue"]}
    for i in new:  # the person disagrees with the judge on every new answer
        _say(ws, i, label="fail" if judge[i] == "pass" else "pass", seconds=4)
    html = _live(ws)
    boxed = [i for i in new if f'data-id="{i}"' in html]
    assert boxed  # the batch's disagreements the person can see have a box
    assert len(boxed) < len(new)  # some of the batch are kept aside, like the first batch
    status, _ = served(ws).label(id=boxed[0], reasons=["wrong_fact"]
                                 if judge[boxed[0]] == "pass" else ["short_ok"])
    assert status == 200
    assert _lines(ws)[-1]["id"] == boxed[0]
    assert "wrong_fact" in _lines(ws)[-1]["reasons"] or "short_ok" in _lines(ws)[-1]["reasons"]


# Getting back to the boxes later --------------------------------------------------------------

NEXT_ALL_MARKED = ("Next: run your eval on more questions, then run `judgekeeper mark`: the new "
                   "answers join the ones you marked.")
SAY_WHY = "Say why on the answers you and your LLM-as-a-judge disagree on; `fix` uses your reasons."


def _run(capsys, *argv) -> tuple[int, str]:
    capsys.readouterr()  # what setting the project up printed
    code = main([str(a) for a in argv])
    out, err = capsys.readouterr()
    assert TAG.strip() not in out + err
    return code, out + err


def _get(url: str) -> str:
    with urllib.request.urlopen(url, timeout=5) as resp:
        return resp.read().decode("utf-8")


def _post(url: str, body: dict) -> int:
    """A POST to /label as the page at `url` sends it (its token, its Origin)."""
    u = urlsplit(url)
    conn = http.client.HTTPConnection(u.hostname, u.port, timeout=5)
    try:
        conn.request("POST", f"/label?{u.query}", body=json.dumps(body).encode(),
                     headers={"Origin": f"http://{u.hostname}:{u.port}",
                              "Content-Type": "application/json"})
        resp = conn.getresponse()
        resp.read()
        return resp.status
    finally:
        conn.close()


def test_mark_with_every_answer_marked_opens_the_result_page_with_the_boxes(
        here, capsys, pages, no_browser):
    ws, passes, _, _ = _ready(here)
    code, out = _run(capsys, "mark")
    assert code == 0, out
    assert f"You have marked all {N} answers. There are no more to mark." in out
    flat = " ".join(out.split())
    assert f"Your result page is open in your browser. {SAY_WHY}" in flat
    assert assert_one_next_at_the_end(out) == NEXT_ALL_MARKED
    assert len(no_browser) == 1
    url = no_browser[0]
    assert re.fullmatch(r"http://127\.0\.0\.1:\d+/result\?token=[\w-]+", url), url
    html = _get(url)
    assert "Why did you mark it Fail?" in html and f'data-id="{passes[0]}"' in html
    assert 'data-reason="wrong_fact"' in _box(html, passes[0])
    before = len(_lines(ws))
    assert _post(url, {"id": passes[0], "reasons": ["wrong_fact"], "note": ""}) == 200
    added = _lines(ws)[before:]
    assert len(added) == 1 and added[0]["reasons"] == ["wrong_fact"]
    assert added[0]["mark"] == "fail"  # the mark as it was


def test_mark_all_marked_prints_the_result_link_without_browser(
        here, capsys, pages, no_browser):
    _, passes, _, _ = _ready(here)
    code, out = _run(capsys, "mark", "--no-browser")
    assert code == 0, out
    lines = out.splitlines()
    at = lines.index("Open this link in your browser to see your result:")
    url = lines[at + 1]
    assert re.fullmatch(r"http://127\.0\.0\.1:\d+/result\?token=[\w-]+", url), url
    assert SAY_WHY in " ".join(out.split())
    assert no_browser == []
    assert 'data-reason="wrong_fact"' in _box(_get(url), passes[0])
    assert assert_one_next_at_the_end(out) == NEXT_ALL_MARKED


def test_mark_opens_the_result_page_again_while_the_page_is_open(here, capsys, pages,
                                                                 no_browser):
    """The page open for this project is kept: its tab still works, and the result page is
    opened on it."""
    _ready(here)
    started = len(pages[0])  # setting the project up opened (and closed) the page once
    assert _run(capsys, "mark")[0] == 0
    assert _run(capsys, "mark")[0] == 0
    assert len(pages[0]) == started + 1 and len(no_browser) == 2
    assert no_browser[0] == no_browser[1]


def test_mark_with_every_answer_marked_and_no_disagreement_opens_no_page(here, capsys, pages,
                                                                         no_browser):
    from tests.start_projects import promptfoo_project, split
    from tests.test_mark import _click

    promptfoo_project(here, split(20, 16))
    assert _run(capsys, "mark")[0] == 0
    _click(Workspace(here))  # as the judge did: no disagreement
    assert _run(capsys)[0] == 0  # a result
    started = len(pages[0])
    code, out = _run(capsys, "mark")
    assert code == 0, out
    assert "You have marked all 36 answers. There are no more to mark." in out
    assert "result page" not in out and "Say why" not in out
    assert len(pages[0]) == started and len(no_browser) == 1  # the marking page, once


def test_measure_and_report_say_once_to_run_mark_to_say_why(here, capsys, pages, no_browser):
    ws, _, _, _ = _ready(here)
    code, out = _run(capsys)
    assert code == 0, out
    lines = out.splitlines()
    at = next(i for i, line in enumerate(lines) if line.startswith("  You failed "))
    n = re.search(r"disagreed on (\d+) of", out)[1]  # the disagreements counted just above
    tell = f"Tell judgekeeper why you disagree on these {n}: run `judgekeeper mark`."
    uses = "`judgekeeper fix` uses your reasons to find where your LLM-as-a-judge goes wrong."
    assert lines[at + 1] == ""
    flat = " ".join(out.split())
    assert f"{tell} {uses}" in flat and flat.index("You failed") < flat.index(tell)
    assert out.count("Tell judgekeeper why") == 1
    report = _report(ws)
    assert report.count(tell.replace("`judgekeeper mark`", "<code>judgekeeper mark</code>")) == 1
    assert uses.replace("`judgekeeper fix`", "<code>judgekeeper fix</code>") in report
    assert report.index("You said Fail, your LLM-as-a-judge said Pass") < report.index("Tell judgekeeper")
    assert "Tell judgekeeper why" not in _live(ws)  # the live page has the boxes


def test_measure_says_nothing_about_why_when_you_agreed_on_all(here, capsys, pages,
                                                                no_browser):
    from tests.start_projects import promptfoo_project, split
    from tests.test_mark import _click

    promptfoo_project(here, split(20, 16))
    assert _run(capsys, "mark")[0] == 0
    _click(Workspace(here))
    code, out = _run(capsys)
    assert code == 0 and "agreed on all 36 answers" in out, out
    assert "To say why" not in out and "To say why" not in _report(Workspace(here))


# The page in a browser: 390px and desktop, keyboard only, screen-reader labels ----------------

# The live result page in a frame of `width`; its fetch records each post. It taps a reason,
# opens Other…, types and leaves the box, marks words in the answer, then measures.
BROWSER_CHECK = """
var f = document.getElementById("f");
f.addEventListener("load", function () {
  var w = f.contentWindow, d = f.contentDocument, out = {width: w.innerWidth}, sent = [];
  w.fetch = function (url, opts) {
    sent.push({url: url, body: JSON.parse(opts.body)});
    return Promise.resolve({ok: true, json: function () { return Promise.resolve({}); }});
  };
  var box = d.querySelector(".why"), all = d.querySelectorAll(".why button, .why input");
  out.wide = d.documentElement.scrollWidth > w.innerWidth + 1;
  out.outside = Array.prototype.filter.call(all, function (e) {
    var r = e.getBoundingClientRect(); return r.right > w.innerWidth + 1 || r.left < -1;
  }).length;
  var chips = box.querySelectorAll(".chip"), first = chips[0].getBoundingClientRect(),
      last = chips[chips.length - 1].getBoundingClientRect();
  out.wraps = last.top > first.top;
  out.controls = Array.prototype.every.call(all, function (e) {
    return (e.tagName === "BUTTON" && e.type === "button" || e.tagName === "INPUT") &&
      e.getAttribute("tabindex") !== "-1"; });
  out.named = Array.prototype.every.call(box.querySelectorAll("button"), function (b) {
    return (b.textContent || b.getAttribute("aria-label") || "").trim().length > 0; });
  var label = d.getElementById(box.getAttribute("aria-labelledby"));
  out.group = box.getAttribute("role") === "group" && !!label && label.textContent.length > 0;
  out.live = box.querySelector(".saved").getAttribute("aria-live") === "polite";
  var chip = box.querySelector('[data-reason="wrong_fact"]');
  chip.focus();
  var s = w.getComputedStyle(chip);
  out.ring = s.outlineStyle === "solid" && s.outlineWidth !== "0px";
  chip.click();
  out.pressed = chip.getAttribute("aria-pressed");
  var other = box.querySelector(".other");
  other.click();
  var input = box.querySelector("input");
  out.opened = other.getAttribute("aria-expanded") === "true" && !input.closest("[hidden]");
  out.focused = d.activeElement === input;
  out.labelled = input.labels.length === 1 && input.labels[0].textContent.trim().length > 0;
  out.max = input.maxLength;
  input.value = "Gives a price"; input.dispatchEvent(new w.Event("input"));
  input.blur();
  var cell = d.getElementById(box.getAttribute("data-answer")), text = cell.firstChild;
  var range = d.createRange(); range.setStart(text, 0); range.setEnd(text, 6);
  var sel = w.getSelection(); sel.removeAllRanges(); sel.addRange(range);
  d.dispatchEvent(new w.Event("selectionchange"));
  setTimeout(function () {
    var mark = box.querySelector(".mark-part");
    out.markShown = !mark.hidden;
    mark.click();
    setTimeout(function () {
      out.bold = cell.querySelectorAll("b.hl").length;
      out.saved = box.querySelector(".saved").textContent;
      out.sent = sent.map(function (x) { return x.body; });
      out.token = sent.length ? sent[0].url : "";
      document.getElementById("out").textContent = JSON.stringify(out);
    }, 1500);
  }, 300);
});
"""


@pytest.mark.parametrize("width", [390, 1200])
def test_the_reason_box_in_a_browser(here, tmp_path, width):
    import subprocess

    from tests.test_pages_and_files import _chrome

    chrome = _chrome()
    if chrome is None:
        pytest.skip("needs Chrome")
    ws, passes, _, _ = _ready(here)
    srcdoc = _live(ws).replace("&", "&amp;").replace('"', "&quot;")
    harness = tmp_path / "harness.html"
    harness.write_text(
        '<!doctype html><html><body style="margin:0"><p id="out"></p>'
        f'<iframe id="f" style="width:{width}px;height:900px;border:0" srcdoc="{srcdoc}">'
        f"</iframe><script>{BROWSER_CHECK}</script></body></html>", encoding="utf-8")
    try:
        done = subprocess.run(
            [chrome, "--headless=new", "--disable-gpu", "--no-first-run", "--no-sandbox",
             f"--user-data-dir={tmp_path / 'profile'}", f"--window-size={width + 100},1000",
             "--virtual-time-budget=8000", "--dump-dom", harness.as_uri()],
            check=False, capture_output=True, text=True, encoding="utf-8", timeout=90)
    except (OSError, subprocess.TimeoutExpired):
        pytest.skip("Chrome did not start")
    found = re.search(r'<p id="out">(\{.*?\})</p>', done.stdout)
    if not found:
        pytest.skip("Chrome did not run the page")
    got = json.loads(found[1].replace("&quot;", '"').replace("&amp;", "&"))
    assert got["width"] == width
    assert not got["wide"] and got["outside"] == 0  # no sideways scroll, nothing cut off
    assert got["wraps"] is True  # the buttons wrap onto more lines
    assert got["controls"] and got["named"] and got["group"] and got["live"]
    assert got["ring"] is True
    assert got["pressed"] == "true"
    assert got["opened"] and got["focused"] and got["labelled"] and got["max"] == 500
    assert got["markShown"] is True and got["bold"] == 1
    assert got["saved"] == "Saved"
    first, *rest = got["sent"]
    assert first == {"id": passes[0], "reasons": ["wrong_fact"], "rule_parts": [],
                     "spans": [], "note": ""}
    assert any(x["note"] == "Gives a price" for x in rest)
    assert rest[-1]["spans"] == [[0, 6]]
    assert got["token"].startswith("/label?token=")
