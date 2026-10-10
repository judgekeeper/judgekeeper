"""The look of `judgekeeper start`'s two pages: the labeling page (two columns, a side panel
with the progress, the judge's rule and the keys) and the result page (one line coloured by
its level, number boxes, the judge and what next).

No test runs the page's script: what the script shows comes from tables that Python tests.
"""

from __future__ import annotations

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

def test_the_labeling_page_has_the_bar_the_rule_and_the_key_hints(tmp_path):
    page = _flat(start_label.page_template(_ws(tmp_path).data()))
    for needed in ("Mark each answer Pass or Fail. What your judge decided stays hidden.",
                   "See your result", "Your judge's rule", "Mark each answer by this rule.",
                   "<kbd>←</kbd> or drag left: Fail", "<kbd>→</kbd> or drag right: Pass",
                   "Click a dot at the top to go back to any answer, skipped ones too.",
                   ("Every click is saved. Close the tab any time; run "
                    "<code>judgekeeper start</code> to continue."),
                   'aria-live="polite"', '<span class="saved" id="saved">Saved</span>'):
        assert needed in page, needed
    body = page.split("<main")[1].split("<script")[0]
    for gone in ("15", "25", "rough", "reliable", "Correct", "Wrong"):
        assert not re.search(rf"\b{gone}\b", body), gone
    # The whole rule, in quotes, folded when long, with "Show all" to unfold it.
    assert ('<p class="rule folded" id="rule">&quot;Is polite and correct. Second line of the '
            'rubric.&quot;</p>') in page
    assert 'id="show-all" type="button" hidden>Show all</button>' in page
    assert "…" not in page


def test_the_rule_card_is_left_out_when_there_is_no_rule():
    for about in ({}, {"rule": None}, {"rule": ""}):
        page = start_label.page_template(about)
        assert "Your judge's rule" not in page and 'id="rule"' not in page


def test_the_rule_is_set_as_text():
    page = start_label.page_template({"rule": "<script>alert(1)</script> __DATA__ __TOKEN__",
                                      "description": "<b>bot</b>"})
    assert "<script>alert(1)" not in page and "&lt;script&gt;alert(1)" in page
    assert "<b>bot</b>" not in page and "&lt;b&gt;bot&lt;/b&gt;" in page
    # The server fills these three in: text from a results file must not be one of them.
    assert page.count("__DATA__") == 1 and page.count("__TOKEN__") == 1


def test_the_description_line(tmp_path):
    page = start_label.page_template(_ws(tmp_path).data())
    assert '<span id="about" hidden>support bot</span>' in page  # the tag on the answer
    assert '<span id="about" hidden></span>' in start_label.page_template({})


def test_the_page_is_three_columns_on_a_laptop():
    page = start_label.page_template({"rule": "Be kind."})
    # The rule, the card, the key hints; nothing is promised below 1024 px, so no phone layout.
    assert ("grid-template-columns: minmax(200px, 300px) minmax(0, 720px) "
            "minmax(200px, 300px)") in page
    assert "@media (max-width" not in page
    assert "innerHTML" not in page  # every text goes through textContent


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

# (pool passes, pool fails, marked in the pass group, of them Pass, in the fail group, of
# them Pass). No target and no number is ever on the page: only what to do.
FEW = "Mark a few more answers to see your result."
ROUGH = "You can see your result now. Marking more answers narrows its ranges."


@pytest.mark.parametrize("counts, text, ready", [
    ((100, 100, 0, 0, 0, 0), FEW, False),
    ((100, 100, 22, 14, 22, 0), FEW, False),  # 14 marked Pass
    ((100, 100, 15, 14, 15, 1), ROUGH, True),
    ((100, 100, 25, 24, 25, 2), ROUGH, True),
    ((100, 100, 50, 48, 50, 2), "Your result is ready.", True),
])
def test_the_status_line(counts, text, ready):
    assert start_label.progress_status(*counts) == {"text": text, "ready": ready}


def test_the_status_line_says_which_range_more_marks_narrow():
    status = start_label.progress_status(900, 100, 25, 24, 25, 1)
    assert status["ready"] is True
    assert status["text"] == ("Marking more answers narrows the range for the answers you "
                              "marked Fail.")
    both = start_label.status_line({"check": "rough", "wide": {"tpr": 0.4, "tnr": None}})
    assert both == ("Marking more answers narrows the range for the answers you marked Pass "
                    "and Fail.")


def test_the_page_shows_the_status_the_server_sends():
    page = start_label.page_template({})
    assert "STATUS" not in page and "least < ROUGH" not in page  # no statistics in the page
    assert "summary.status" in page and "data.status" in page


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
    (CHECK, "amber", "warn", None),
    (NOT_GATE_TNR, "red", "cross", "It passes many answers you marked Fail."),
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
    assert "<span>It passes many answers you marked Fail.</span>" in box
    low_tpr = _result(*NOT_GATE_TPR)
    assert low_tpr["verdict_level"] == "not_gate" and low_tpr["tpr"] < low_tpr["tnr"]
    box = _verdict(start_label.result_html(low_tpr))
    assert "<span>It fails many answers you marked Pass.</span>" in box


def test_the_number_boxes():
    r = _result(*CHECK)
    html = _flat(start_label.result_html(r))
    lo, hi = r["tpr_interval"]
    for needed in ("When you said Pass", "When you said Fail", "How much you agree beyond luck",
                   f"{r['tpr']:.0%}</b>", f"{r['tnr']:.0%}</b>", f"{r['kappa']:.2f}</b>",
                   (f"Probably between {lo:.0%} and {hi:.0%}. Marking more answers narrows "
                    "this."),
                   (f"Probably between {r['tnr_interval'][0]:.0%} and "
                    f"{r['tnr_interval'][1]:.0%}. Marking more answers narrows this."),
                   "from 40 answers · 0.6 or more is good"):
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
    tnr = next(t for t in tiles if "When you said Fail" in t)
    assert '<b class="val">–</b>' in tnr and "rangebar" not in tnr
    assert "None" not in html and "nan" not in html


def test_the_pass_rate_box():
    r = _result(*CHECK)
    html = _flat(start_label.result_html(r))
    lo, hi = r["real_pass_rate_interval"]
    assert (f"Your judge passes <b>{r['judge_pass_rate']:.0%}</b> of your app's answers. From "
            f"your marks, about <b>{r['real_pass_rate']:.0%}</b> should pass (probably between "
            f"{lo:.0%} and {hi:.0%}).") in unescape(html)
    assert ("judgekeeper showed you half of your judge's passes and half of its fails, and "
            "corrects the numbers for that. The bar under each number is the range it is "
            "probably in.") in unescape(html)


def test_the_title_line_says_the_check_the_counts_and_the_date():
    html = _flat(start_label.result_html(_result(*CHECK)))
    assert "From the 40 answers you marked: 19 Pass, 21 Fail · 5 October 2026" in html
    assert "How often your judge agrees with you" in html
    assert "From the 20 answers you marked: 10 Pass, 10 Fail" in _flat(start_label.result_html(
        _result(*TOO_FEW)))


def test_mark_more_answers_says_why_with_no_target():
    html = _flat(start_label.result_html(_result(*CHECK), back="/?token=t"))
    assert "<b>Mark more answers</b>Marking more answers narrows the ranges." in html
    assert '<a class="btn" href="/?token=t">Mark more answers</a>' in html
    one_side = _flat(start_label.result_html(_result(100, 100, 30, 26, 20, 1)))  # 27, 23
    assert "<b>Mark more answers</b>Marking more answers narrows the ranges." in one_side
    reliable = start_label.result_html(_result(100, 100, 30, 28, 30, 2))
    assert "Mark more answers" not in reliable


def test_mark_more_answers_says_which_range_is_still_wide():
    r = _result(900, 100, 25, 24, 25, 1)  # 25 Pass, 25 Fail; the TNR range stays wide
    html = _flat(start_label.result_html(r, back="/?token=t"))
    assert ("<b>Mark more answers</b>Marking more answers narrows the range for the answers "
            "you marked Fail.") in html
    assert not re.search(r"\d\.\d\d wide", html)


def test_what_next_holds_the_three_steps():
    html = start_label.result_html(_result(*CHECK), back="/?token=t")
    assert re.findall(r"<li><b>(.*?)</b>", html) == ["Mark more answers",
                                                    "Ask your judge again",
                                                    "Check again after your next eval run"]
    assert "<code>judgekeeper start --ask-again</code>" in html  # a command: no button
    assert "<b>Check again after your next eval run</b> <code>judgekeeper start</code>" \
        in _flat(html)
    assert ("Saved in <code>.judgekeeper/</code> in your project. This page is "
            "<code>result.html</code> there.") in _flat(html)


def test_the_saved_page_has_commands_not_buttons():
    html = start_label.result_html(_result(*CHECK))
    assert "<button" not in html and 'class="btn"' not in html and "<a " not in html
    assert "Marking more answers narrows the ranges. <code>judgekeeper start</code>" in _flat(html)


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


def test_both_pages_are_navy_with_the_amber_and_respect_reduced_motion():
    for page in (start_label.page_template({}), start_label.result_html(_result(*CHECK))):
        assert "--bg: #0E1525" in page and "--card: #182235" in page
        assert "--amber: #FBBF24" in page and "--amber-bg:" in page
        assert "--pass: #34D399" in page and "--fail: #F59E8B" in page
        assert ":focus-visible" in page
        assert "@media (prefers-reduced-motion: reduce)" in page
        assert "prefers-color-scheme" not in page  # navy only: no light theme
        assert "transition: all" not in page


# When labeling more or asking again cannot help ------------------------------------------

def test_with_every_answer_marked_it_does_not_offer_to_mark_more():
    r = _result(*CHECK, left=0)
    html = _flat(start_label.result_html(r, back="/?token=t"))
    assert 'href="/?token=t"' not in html
    assert ("<b>Mark more answers</b>Every saved answer is marked. Run your eval again for "
            "more answers, then:") in html
    lines = start_label.result_lines(r)
    assert not any(line.startswith("  Mark more answers") for line in lines)


def test_with_answers_left_it_still_offers_to_mark_more():
    html = _flat(start_label.result_html(_result(*CHECK, left=7), back="/?token=t"))
    assert '<a class="btn" href="/?token=t">Mark more answers</a>' in html


@pytest.mark.parametrize("tool", ["records", "table", "mapped"])
def test_a_judge_it_cannot_ask_again_is_not_offered(tool):
    r = _result(*CHECK, judge={"tool": tool})
    assert "--ask-again" not in start_label.result_html(r)
    assert not any("--ask-again" in line for line in start_label.result_lines(r))


@pytest.mark.parametrize("tool", ["promptfoo", "deepeval", "inspect", "mlflow"])
def test_a_judge_it_can_ask_again_is_offered(tool):
    r = _result(*CHECK, judge={"tool": tool})
    assert "judgekeeper start --ask-again" in start_label.result_html(r)


# Too few marks: no numbers yet -----------------------------------------------------------

def test_too_few_marks_show_no_numbers():
    r = _result(100, 100, 2, 1, 1, 0)  # 1 Pass, 2 Fail
    body = _flat(start_label.result_html(r).split("<main")[1])
    assert "-0." not in body and "0.00" not in body and "%" not in body
    assert "Mark a few more answers to see your result. So far: 1 Pass, 2 Fail." in body
    assert body.count('<b class="val">–</b>') == 3 and "rangebar" not in body
    assert "ring" not in body and 'class="stmt"' not in body  # nothing to draw yet
    assert "judgekeeper showed you" not in body and 'class="facts"' not in body
    lines = start_label.result_lines(r)
    assert not any("TPR" in line or "%" in line for line in lines)


def test_the_result_links_start_hidden_until_a_rough_check():
    page = start_label.page_template({"rule": "x"})
    links = re.findall(r'<a class="btn green see"[^>]*>', page)
    assert len(links) == 1 and all(" hidden" in a for a in links)
    assert "a.hidden = !status.ready" in page  # the server says when: at 15 + 15
    assert "With so few" not in page


def test_the_card_has_one_fixed_height_so_the_buttons_never_move():
    page = start_label.page_template({})
    assert ".stack { position: relative; height: clamp(320px, 100vh - 300px, 440px); }" in page
    assert ".decide { display: grid; grid-template-columns: 1fr auto 1fr; gap: 12px;" in page
    assert ".scrollbox { flex: 1; min-height: 0; overflow: auto;" in page  # long answers scroll


def test_each_number_box_leads_with_its_plain_name():
    html = start_label.result_html(_result(*CHECK))
    tile = re.findall(r'<div class="tile">.*?</div>\s*</div>', html, re.DOTALL)[0]
    assert tile.startswith('<div class="tile"><div class="lbl">When you said Pass '
                           '<span class="abbr">TPR</span><b class="val">')
