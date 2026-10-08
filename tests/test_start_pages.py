"""The look of `judgekeeper start`'s two pages: the labeling page (two columns, a side panel
with the progress, the judge's rule and the keys) and the result page (a verdict coloured by
its level, number boxes, the judge and what next).

No test runs the page's script: what the script shows comes from tables that Python tests.
"""

from __future__ import annotations

import json
import re
from html import unescape

import pytest

from judgekeeper import start, start_label, weighted
from tests.start_projects import RUBRIC, promptfoo_project, split


def _ws(root, n_pass=20, n_fail=12, **kwargs):
    promptfoo_project(root, split(n_pass, n_fail), **kwargs)
    return start_label.prepare(start.find_judge(root), say=lambda line: None)


def _flat(html: str) -> str:
    return " ".join(html.split())


# What `start` keeps for the pages --------------------------------------------------------

def test_the_full_rule_and_the_description_are_kept(tmp_path):
    promptfoo_project(tmp_path, split(20, 12))
    found = start.find_judge(tmp_path)
    assert found.rule == RUBRIC
    assert found.description == "support bot"
    data = start_label.prepare(found, say=lambda line: None).data()
    assert data["rule"] == RUBRIC and data["description"] == "support bot"


def test_without_a_description_there_is_none(tmp_path):
    promptfoo_project(tmp_path, split(20, 12), description=None)
    assert start.find_judge(tmp_path).description is None


def test_the_rule_is_the_whole_text_and_the_rubric_line_its_first_line():
    assert start.rule_text("Criteria: Be kind.\nAnd brief.") == "Be kind.\nAnd brief."
    assert start.rule_text("  ") is None and start.rule_text(None) is None
    assert start.rubric_line("Criteria: Be kind.\nAnd brief.") == "Be kind."
    long = "x" * 100
    assert start.rule_text(long) == long
    assert start.rubric_line(long).endswith("…")


# The labeling page -----------------------------------------------------------------------

def test_the_labeling_page_has_the_progress_rule_and_keys_cards(tmp_path):
    page = _flat(start_label.page_template(_ws(tmp_path).data()))
    for needed in ("Is this answer correct? Your judge's verdict is hidden.",
                   "Your progress", "15 rough", "25 reliable", "See my result →",
                   "What are you checking?", "Your judge's rule",
                   ("Mark each answer by what you think is right. The judge's verdict stays "
                    "hidden."), "Keys",
                   ("Every click is saved. Close the tab any time; run "
                    "<code>judgekeeper start</code> to continue."),
                   "See result →", 'aria-live="polite"'):
        assert needed in page, needed
    # The whole rule, in quotes, inside a fold-out that starts open.
    details = re.findall(r"<details[^>]*>", page)
    assert details == ["<details open>"]
    assert "&quot;Is polite and correct. Second line of the rubric.&quot;" in page
    assert "…" not in page


def test_the_rule_card_is_left_out_when_there_is_no_rule():
    for about in ({}, {"rule": None}, {"rule": ""}):
        page = start_label.page_template(about)
        assert "What are you checking?" not in page and "<details" not in page


def test_the_rule_is_set_as_text():
    page = start_label.page_template({"rule": "<script>alert(1)</script> __DATA__ __TOKEN__",
                                      "description": "<b>bot</b>"})
    assert "<script>alert(1)" not in page and "&lt;script&gt;alert(1)" in page
    assert "<b>bot</b>" not in page and "&lt;b&gt;bot&lt;/b&gt;" in page
    # The server fills these three in: text from a results file must not be one of them.
    assert page.count("__DATA__") == 1 and page.count("__TOKEN__") == 1


def test_the_description_line(tmp_path):
    page = start_label.page_template(_ws(tmp_path).data())
    assert '<span id="about">support bot</span>' in page
    assert '<span id="about"></span>' in start_label.page_template({})


def test_the_page_is_two_columns_on_a_laptop_and_one_on_a_phone():
    page = start_label.page_template({"rule": "Be kind."})
    assert "@media (max-width: 760px)" in page
    assert "grid-template-columns: minmax(0, 1fr) 320px" in page
    assert "position: sticky" in page  # Correct and Wrong stay on screen on a phone
    assert "innerHTML" not in page and "clientWidth" not in page


def test_the_rule_card_holds_no_reason_from_the_judge(tmp_path):
    page = start_label.page_template(_ws(tmp_path).data())
    assert not re.search(r"reason \d", page)


# How the question is shown ---------------------------------------------------------------

def test_a_plain_question_is_shown_as_written():
    assert start_label.question_view("How do I sleep?\nThanks.") == "How do I sleep?\nThanks."
    assert start_label.question_view(None) == ""


def test_one_named_value_shows_only_the_value():
    assert start_label.question_view({"question": "How do I sleep?"}) == "How do I sleep?"
    assert start_label.question_view({"n": 3}) == "3"


def test_several_named_values_show_each_name_and_value():
    assert start_label.question_view({"question": "Hi?", "user": "Sam", "n": [1, 2]}) == [
        ["question", "Hi?"], ["user", "Sam"], ["n", "[1, 2]"]]


def test_a_script_in_the_question_stays_text(tmp_path):
    shown = start_label.question_view({"q": "<script>alert(1)</script>"})
    assert shown == "<script>alert(1)</script>"  # data: the page sets it with textContent
    assert "textContent" in start_label.page_template({})


def test_the_page_shows_the_question_without_its_name(tmp_path):
    ws = _ws(tmp_path)
    items = start_label.StartSession(ws).state()["items"]
    assert all(re.fullmatch(r"Question \d+\?", it["input"]) for it in items)


# The status line -------------------------------------------------------------------------

@pytest.mark.parametrize("correct, wrong, text, ready", [
    (0, 0, "A rough check needs 15 of each.", False),
    (14, 30, "A rough check needs 15 of each.", False),
    (15, 15, "Rough check ready. A reliable result needs 25 of each.", True),
    (25, 24, "Rough check ready. A reliable result needs 25 of each.", True),
    (25, 25, "Reliable result ready.", True),
])
def test_the_status_line(correct, wrong, text, ready):
    assert start_label.progress_status(correct, wrong) == (text, ready)


def test_the_page_uses_the_same_status_lines():
    page = start_label.page_template({})
    for _, text, _ in start_label.STATUS:
        assert json.dumps(text) in page


# The result page -------------------------------------------------------------------------

def _result(n_pool_pass, n_pool_fail, n_p, c_p, n_f, c_f, **extra):
    r = start_label.describe(weighted.corrected(n_pool_pass, n_pool_fail, n_p, c_p, n_f, c_f))
    r.update(made_at="2026-10-05T12:00:00Z", **extra)
    return r


GATE = (100, 100, 20, 19, 20, 1)
CHECK = (100, 100, 20, 17, 20, 2)
NOT_GATE_TNR = (100, 100, 25, 17, 25, 1)   # 18 Correct, 32 Wrong: TPR 0.94, TNR 0.75
NOT_GATE_TPR = (100, 100, 25, 24, 25, 8)   # 32 Correct, 18 Wrong: TPR 0.75, TNR 0.94
TOO_FEW = (100, 100, 10, 9, 10, 1)


def _verdict(html: str) -> str:
    return re.search(r'<div class="verdict[^"]*".*?</div>\s*</div>', html, re.DOTALL)[0]


@pytest.mark.parametrize("counts, colour, icon, second", [
    (GATE, "green", "tick", "Keep checking it after changes to its model or rule."),
    (CHECK, "amber", "warn", "Close to good enough. Labeling more will make this surer."),
    (NOT_GATE_TNR, "red", "cross", "Look at where it disagreed before relying on it."),
    (TOO_FEW, "grey", None, None),
])
def test_each_level_has_its_colour_icon_and_second_line(counts, colour, icon, second):
    r = _result(*counts)
    box = _verdict(start_label.result_html(r))
    assert f'class="verdict {colour}"' in box
    assert r["verdict"] in box
    if icon:
        assert f'class="vicon {icon}"' in box and 'aria-hidden="true"' in box
    else:
        assert "<svg" not in box
    if second:
        assert second in box
    else:
        assert "<span>" not in box


def test_a_bad_result_names_the_weaker_side():
    low_tnr = _result(*NOT_GATE_TNR)
    assert low_tnr["tnr"] < low_tnr["tpr"]
    box = _verdict(start_label.result_html(low_tnr))
    assert ("<span>It misses many answers you marked Wrong. Look at where it disagreed before "
            "relying on it.</span>") in box
    low_tpr = _result(*NOT_GATE_TPR)
    assert low_tpr["verdict_level"] == "not_gate" and low_tpr["tpr"] < low_tpr["tnr"]
    box = _verdict(start_label.result_html(low_tpr))
    assert ("<span>It fails many answers you marked Correct. Look at where it disagreed "
            "before relying on it.</span>") in box


def test_the_number_boxes():
    r = _result(*CHECK)
    html = _flat(start_label.result_html(r))
    lo, hi = r["tpr_interval"]
    for needed in ("Good answers it passed", "Bad answers it failed",
                   "Agreement beyond chance",
                   f"{lo:.2f} to {hi:.2f} · from 19 Correct",
                   f"{r['tnr_interval'][0]:.2f} to {r['tnr_interval'][1]:.2f} · from 21 Wrong",
                   "from 40 labels · 0.6 or more is good"):
        assert needed in html, needed
    tiles = re.findall(r'<div class="tile">.*?</div>\s*</div>', start_label.result_html(r),
                       re.DOTALL)
    assert len(tiles) == 3
    assert all('class="rangebar"' in t for t in tiles)
    assert "<span style" in tiles[0] and "<span style" not in tiles[2]  # kappa: the mark only


def test_the_kappa_line_reads_the_gate(monkeypatch):
    monkeypatch.setattr(start_label, "KAPPA_GATE", 0.7)
    assert "0.7 or more is good" in start_label.result_html(_result(*GATE))


def test_an_unknown_rate_shows_a_dash_and_no_bar():  # only with too few labels
    r = _result(100, 100, 20, 15, 0, 0)
    assert r["tnr"] is None
    html = start_label.result_html(r)
    tiles = re.findall(r'<div class="tile">.*?</div>\s*</div>', html, re.DOTALL)
    tnr = next(t for t in tiles if "Bad answers it failed" in t)
    assert '<div class="val">–</div>' in tnr and "rangebar" not in tnr
    assert "None" not in html and "nan" not in html


def test_the_pass_rate_box():
    r = _result(*CHECK)
    html = _flat(start_label.result_html(r))
    lo, hi = r["real_pass_rate_interval"]
    assert (f"Your judge passes <b>{r['judge_pass_rate']:.0%}</b> of your app's answers. From "
            f"your labels, about <b>{r['real_pass_rate']:.0%}</b> should pass ({lo:.0%} to "
            f"{hi:.0%}).") in unescape(html)
    assert ("Numbers are corrected for picking half from the judge's passes and half from "
            "its fails. The bar under each number shows how sure it is: narrower is surer."
            ) in unescape(html)


def test_the_title_line_says_the_check_the_counts_and_the_date():
    html = _flat(start_label.result_html(_result(*CHECK)))
    assert "Rough check · 19 marked Correct, 21 marked Wrong · 5 October 2026" in html
    assert "How often your judge agrees with you" in html
    assert "Too few labels · 10 marked Correct" in _flat(start_label.result_html(
        _result(*TOO_FEW)))


def test_make_it_reliable_says_the_real_numbers_still_needed():
    html = _flat(start_label.result_html(_result(*CHECK), back="/?token=t"))
    assert "<b>Make it a reliable result</b>6 more Correct and 4 more Wrong." in html
    assert '<a class="btn" href="/?token=t">Keep labeling</a>' in html
    one_side = _flat(start_label.result_html(_result(100, 100, 30, 26, 20, 1)))  # 27, 23
    assert "<b>Make it a reliable result</b>2 more Wrong." in one_side
    reliable = start_label.result_html(_result(100, 100, 30, 28, 30, 2))
    assert "Make it a reliable result" not in reliable


def test_what_next_holds_the_three_steps():
    html = start_label.result_html(_result(*CHECK), back="/?token=t")
    assert re.findall(r"<li><b>(.*?)</b>", html) == ["Make it a reliable result",
                                                    "Ask your judge again",
                                                    "Check again later"]
    assert "<code>judgekeeper start --ask-again</code>" in html  # a command: no button
    assert "<b>Check again later</b>After your next eval run: <code>judgekeeper start</code>" \
        in _flat(html)
    assert ("Saved in <code>.judgekeeper/</code> in your project. This page is "
            "<code>result.html</code> there.") in _flat(html)


def test_the_saved_page_has_commands_not_buttons():
    html = start_label.result_html(_result(*CHECK))
    assert "<button" not in html and 'class="btn"' not in html and "<a " not in html
    assert "Keep labeling" not in html
    assert "6 more Correct and 4 more Wrong. <code>judgekeeper start</code>" in _flat(html)


def test_the_judge_card_shows_the_full_rule(tmp_path):
    ws = _ws(tmp_path)
    session = start_label.StartSession(ws)
    groups = {q["id"]: q["group"] for q in ws.data()["queue"]}
    for item in session.items:
        session.update({"id": item["id"], "label": groups[item["id"]]})
    start_label.save_result(ws, session, say=lambda line: None)
    html = _flat(ws.result_html.read_text(encoding="utf-8"))
    assert "<b>llm-rubric</b> · openai:gpt-4.1-mini" in html
    assert ('<div class="rule">&quot;Is polite and correct. Second line of the rubric.&quot;'
            '</div>') in html
    assert "…" not in html
    date = ws.data()["results_date"]  # "2026-10-05 05:30"
    when = start_label.in_words(date[:10]) + ", " + date[11:]
    assert f"From results.json (promptfoo), saved {when}" in html


def test_dates_in_words():
    assert start_label.in_words("2026-10-05") == "5 October 2026"
    assert start_label.in_words("2026-01-31") == "31 January 2026"
    assert start_label.in_words("not a date") == "not a date"


def test_both_pages_follow_the_computers_theme_and_hold_the_amber():
    for page in (start_label.page_template({}), start_label.result_html(_result(*CHECK))):
        assert "prefers-color-scheme: dark" in page
        assert "--care:" in page and "--care-bg:" in page
        assert ":focus-visible" in page
        assert "@media (max-width: 760px)" in page


# When labeling more or asking again cannot help ------------------------------------------

def test_with_every_answer_labeled_it_does_not_offer_to_label_more():
    r = _result(*CHECK, left=0)
    html = _flat(start_label.result_html(r, back="/?token=t"))
    assert "Keep labeling" not in html
    assert ("<b>Make it a reliable result</b>Every saved answer is labeled. Run your evals "
            "again for more answers, then:") in html
    lines = start_label.result_lines(r)
    assert not any(line.startswith("  Label more") for line in lines)


def test_with_answers_left_it_still_offers_to_label_more():
    html = _flat(start_label.result_html(_result(*CHECK, left=7), back="/?token=t"))
    assert '<a class="btn" href="/?token=t">Keep labeling</a>' in html


@pytest.mark.parametrize("tool", ["records", "table", "mapped"])
def test_a_judge_it_cannot_ask_again_is_not_offered(tool):
    r = _result(*CHECK, judge={"tool": tool})
    assert "--ask-again" not in start_label.result_html(r)
    assert not any("--ask-again" in line for line in start_label.result_lines(r))


@pytest.mark.parametrize("tool", ["promptfoo", "deepeval", "inspect", "mlflow"])
def test_a_judge_it_can_ask_again_is_offered(tool):
    r = _result(*CHECK, judge={"tool": tool})
    assert "judgekeeper start --ask-again" in start_label.result_html(r)


# Too few labels: no numbers yet ----------------------------------------------------------

def test_too_few_labels_show_no_numbers():
    r = _result(100, 100, 2, 1, 1, 0)  # 1 Correct, 2 Wrong
    body = _flat(start_label.result_html(r).split("<main>")[1])
    assert "-0." not in body and "0.00" not in body and "%" not in body
    assert "Too few labels to tell yet." in body
    assert ("A rough check needs 15 you mark Correct and 15 you mark Wrong. So far: 1 "
            "Correct, 2 Wrong.") in body
    assert body.count('<div class="val">–</div>') == 3 and "rangebar" not in body
    assert "Numbers are corrected" not in body and 'class="facts"' not in body
    lines = start_label.result_lines(r)
    assert not any("TPR" in line or "%" in line for line in lines)


def test_the_result_links_start_hidden_until_a_rough_check():
    page = start_label.page_template({"rule": "x"})
    links = re.findall(r'<a class="seelink see"[^>]*>', page)
    assert len(links) == 2 and all(" hidden" in a for a in links)
    assert "a.hidden = least < ROUGH" in page  # the script shows them at 15 + 15
    assert "With so few labels" not in page


def test_the_answer_box_does_not_stretch_to_fill_the_screen():
    page = start_label.page_template({})
    answer = re.search(r"#answer \{([^}]*)\}", page)[1]
    assert "flex: 0 1 auto" in answer
    assert ".choices { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin-top: 18px; }" in page


def test_each_number_box_leads_with_its_plain_name():
    html = start_label.result_html(_result(*CHECK))
    tile = re.findall(r'<div class="tile">.*?</div>\s*</div>', html, re.DOTALL)[0]
    assert tile.startswith('<div class="tile"><div class="lbl">Good answers it passed '
                           '<span class="abbr">TPR</span></div>')
