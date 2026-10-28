"""The marking page and the result page, looked at closely: one fade, one link style, one size
of small text, labels never stacked, a calm width on a wide screen, and what a screen reader
hears after a mark."""

from __future__ import annotations

import re

from judgekeeper import look, mark_page, report_page, start_label
from tests.test_long_text import _html, _laptop, _one, _with_reason
from tests.test_mark_page_script import _data, _run
from tests.test_product_pages import NOT_GATE_TNR, _mistakes, _result

FADE = "linear-gradient(to bottom, #000 calc(100% - 1.5em), transparent)"


def _wide_report() -> str:
    return report_page.STYLE.split("@media (min-width: 721px) {", 1)[1].split("\n}\n", 1)[0]


def test_the_reason_column_is_muted_and_the_foot_line_is_not():
    style = report_page.STYLE
    assert ".tbl td[data-label]:nth-child(3) { color: var(--muted); }" in style
    assert ".tbl td:last-child { color" not in style  # the foot line is the row's last cell


def test_one_fade_over_the_last_line_everywhere():
    for style in (mark_page.STYLE, report_page.STYLE):
        fades = re.findall(r"mask-image: (linear-gradient\([^;]*\));", style)
        assert fades and set(fades) == {FADE}
    assert (".a-scroll.more-below, .question.long.cut:not(.open), .question.long.open.more-below,"
            "\n  .rule.more-below {") in _laptop()
    assert f".tbl td[data-label].cut {{ -webkit-mask-image: {FADE}; mask-image: {FADE}; }}" in (
        _wide_report())
    assert "bottom: 9px; width: 1.5em;" in mark_page.STYLE  # the code box's right edge


def test_the_open_rule_fades_while_there_is_more_below():
    got = _run("""
      var rule = ids["rule"]; rule.scrollHeight = 600; rule.clientHeight = 200;
      ids["rule-btn"].fire("click");
      var more = rule.className;
      rule.scrollTop = 400; rule.fire("scroll");
      console.log(JSON.stringify([more, rule.className]));""", data=_one("Q?"),
               before='document.getElementById("rule").hidden = true;')
    assert "more-below" in got[0].split() and "more-below" not in got[1].split()


def test_one_link_style():
    link = ("padding: 6px 0; font-size: 14px; color: var(--muted);\n  text-decoration: underline; "
            "text-decoration-color: var(--faint); text-underline-offset: 3px; }")
    assert f".quiet.q-more, .quiet.rule-btn {{ {link}" in mark_page.STYLE
    assert (".more, .open-row { font-size: 14px; color: var(--muted); text-decoration: underline;"
            "\n  text-decoration-color: var(--faint); text-underline-offset: 3px;") in (
        report_page.STYLE)
    # the rule button's right edge lines up with "Not marked yet": no padding to the side
    assert "\n.rule-btn { padding" not in mark_page.STYLE
    assert ".add-reason { font-size: 14px; color: var(--text);" in report_page.STYLE


def test_no_label_stacked_over_field_labels_and_room_under_the_metric():
    got = _run("""
      console.log(JSON.stringify(ids["q-label"].hidden));""",
               data=_one([["question", "Q?"], ["system", "Be kind."]]))
    assert got is True
    assert _run('console.log(JSON.stringify(ids["q-label"].hidden));', data=_one("Q?")) is False
    assert "margin-bottom: 22px; }" in mark_page.STYLE.split(".graded {", 1)[1].split("}")[0] + "}"


def test_faint_reads_at_4_7_to_1():
    assert "--faint: #767c86;" in look.TOKENS


def test_the_open_rule_fits_its_text():
    assert "background: var(--hover); width: fit-content; max-width: 100%; }" in mark_page.STYLE


def test_wide_screens_keep_a_comfortable_width():
    laptop = _laptop()
    assert ".row, .actions, .status, .foot { padding-right: max(40px, calc(100cqw - 1160px)); }" in laptop
    assert ".main { container-type: inline-size; }" in laptop
    assert ("padding-left: max(var(--gutter), calc((100% - 1376px) / 2));"
            in report_page.STYLE.split(".band {", 1)[1])
    # the two counts line up with the lists under them
    assert ".counts { padding-left: max(0px, calc((100% - 1376px) / 2 - var(--gutter)));" in (
        report_page.STYLE)


def test_small_text_is_one_size():
    style = report_page.STYLE
    for sel in (".note {", ".left-out {", ".add-why {", ".panel caption {"):
        rule = style.split(sel, 1)[1].split("}", 1)[0]
        assert "font-size: 14px;" in rule and "max-width: 80ch;" in rule, sel


def test_the_list_title_drops_a_leading_label_and_reads_in_its_own_direction():
    got = _run("""
      var a = ids["queue"].children[0].children[0];
      var q = a.children.filter(function (c) { return c.className === "q"; })[0];
      console.log(JSON.stringify([q.textContent, q.getAttribute("dir")]));""",
               data=_one("question: How heavy can my bag be?\nsystem: Be kind."))
    assert got == ["How heavy can my bag be?", "auto"]


def test_the_folded_gap_is_a_quiet_line_screen_readers_skip():
    long = "Line one. " * 40 + "\n" + "More. " * 40 + "\n\nWhere is my bag?"
    got = _run("""
      var gap = ids["q-text"].children.filter(function (c) { return c.className === "q-gap"; })[0];
      console.log(JSON.stringify([gap.textContent, gap.getAttribute("aria-hidden")]));""",
               data=_one(long))
    assert got == ["…", "true"]
    assert ".question .q-gap { font-size: 13px; letter-spacing: .3em; color: var(--muted); }" in (
        _laptop())
    assert ".q-gap { display: block; font-size: 13px; letter-spacing: .3em;" in _wide_report()


def test_rule_parts_stand_in_one_column_inside_a_bordered_panel():
    html = _html([_with_reason({})], live=True, parts=["Be polite", "Never promise a refund"])
    assert '<div class="chips parts" role="group"' in html
    assert ".chips.parts { flex-direction: column; align-items: flex-start; }" in report_page.STYLE
    assert ".why-body { margin-top: 16px; padding-left: 16px; border-left: 2px solid var(--line); }" in (
        report_page.STYLE)


def test_right_to_left_text_sits_at_the_right_edge():
    assert ".answer:dir(rtl), .question:dir(rtl) { margin-left: auto; }" in mark_page.STYLE


def test_the_key_hints_are_readable():
    assert ".btn kbd { font-family: var(--sans); font-size: 13px; font-weight: 400; margin-left: 8px; }" in (
        mark_page.STYLE)
    assert "opacity: .85" not in mark_page.STYLE


def test_a_screen_reader_hears_each_mark():
    data = _data(3)
    got = _run("""
      var heard = [];
      async function press(k) { NOW += 5000; key(k); await settle(); heard.push(ids["done"].textContent); }
      await press("ArrowRight"); await press("ArrowLeft"); await press("s"); await press("z");
      console.log(JSON.stringify(heard));""", data=data)
    assert got == ["Marked Pass.", "Marked Fail.", "Skipped.", "Undone."]
    assert '<p class="sr" id="done" role="status"></p>' in mark_page.label_page("b", "jk mark")


def test_nothing_to_undo_is_said_calmly():
    got = _run("""
      key("z"); console.log(JSON.stringify([ids["status"].textContent, ids["status"].className]));""")
    assert got[0] == "Nothing to undo." and "calm" in got[1].split()
    assert ".status.calm { color: var(--muted); font-weight: 400; }" in mark_page.STYLE


def test_targets_are_big_enough_and_the_note_box_has_an_edge():
    style = report_page.STYLE
    assert ".open-row, .add-reason { padding: 3px 0; }" in style
    assert "min-width: 24px; min-height: 24px; }" in style.split(".kappa .i {", 1)[1]
    assert "border: 1px solid var(--faint); padding: 10px 12px; width: 100%; }" in style


def test_an_opened_row_shows_its_whole_text_without_scroll_boxes():
    assert ".tbl tr[data-open] td[data-label] { max-height: none; overflow: visible; }" in (
        _wide_report())
    html = start_label.result_html(_result(*NOT_GATE_TNR), fixing={"mistakes": _mistakes(1, 0)})
    assert "60vh" not in html


# Found by hand: an open box's tab stop and focus ----------------------------------------------

def test_the_next_answer_shuts_the_question_and_its_tab_stop():
    data = _data(2)
    data["items"][0].update(input="Q " * 100)
    data["items"][1].update(input="Line one\nline two " * 30)
    got = _run("""
      var q = ids["q-text"]; q.scrollHeight = 900; q.clientHeight = 100;
      ids["q-more"].fire("click");
      var open = q.getAttribute("tabindex");
      key("ArrowRight"); await settle();
      console.log(JSON.stringify([open, q.getAttribute("tabindex"),
        q.className.split(" ").indexOf("open")]));""", data=data)
    assert got == ["0", None, -1]


def test_shutting_a_focused_box_by_its_button_leaves_focus_on_the_button():
    got = _run("""
      var q = ids["q-text"], rule = ids["rule"];
      q.scrollHeight = 900; q.clientHeight = 100;
      ids["q-more"].fire("click"); q.focus();
      ids["q-more"].fire("click");  // Show less
      var afterQuestion = document.activeElement === ids["q-more"];
      ids["rule-btn"].fire("click"); rule.focus();
      ids["rule-btn"].fire("click");  // Hide the rule
      console.log(JSON.stringify([afterQuestion, document.activeElement === ids["rule-btn"]]));""",
               data=_one("Q " * 100), before='document.getElementById("rule").hidden = true;')
    assert got == [True, True]


# A browser drops focus from a box as soon as it is hidden: so does this rule.
LOSES_FOCUS = """
  var rule = document.getElementById("rule"), shut = true;
  Object.defineProperty(rule, "hidden", {get: function () { return shut; }, set: function (v) {
    shut = !!v; if (shut && document.activeElement === rule) { document.activeElement = null; } }});
"""


def test_hiding_the_focused_rule_leaves_focus_on_the_button_that_hid_it():
    got = _run("""
      var q = ids["q-text"], rule = ids["rule"], at = [];
      q.scrollHeight = 900; q.clientHeight = 100;
      ids["rule-btn"].fire("click"); rule.focus();
      ids["rule-btn"].fire("click");  // Hide the rule
      at.push(document.activeElement === ids["rule-btn"], rule.getAttribute("tabindex"));
      ids["rule-btn"].fire("click"); rule.focus();
      ids["q-more"].fire("click");  // Show all shuts the rule
      at.push(document.activeElement === ids["q-more"], rule.hidden);
      console.log(JSON.stringify(at));""", data=_one("Q " * 100), before=LOSES_FOCUS)
    assert got == [True, None, True, True]


def test_a_flag_keeps_its_tags_and_stray_tags_still_go():
    from judgekeeper import redact

    england = "\U0001F3F4\U000E0067\U000E0062\U000E0065\U000E006E\U000E0067\U000E007F"
    assert redact.visible(f"Go {england}!") == f"Go {england}!"
    assert redact.visible("a\U000E0067\U000E007Fb") == "ab"  # no black flag before them
    assert redact.visible("\U0001F3F4\U000E0067\U000E0062x") == "\U0001F3F4x"  # never ended
    assert redact.visible("\U0001F3F4\u200b\U000E0067\U000E007F") == "\U0001F3F4"
    assert redact.printable(england) == "\U0001F3F4"  # the terminal: as before


def _tags(text: str) -> str:
    return "".join(chr(0xE0000 + ord(c)) for c in text) + "\U000E007F"


def test_only_a_real_subdivision_flag_keeps_its_tags():
    from judgekeeper import redact

    for flag in ("\U0001F3F4" + _tags(code) for code in ("gbeng", "gbsct", "gbwls", "us06")):
        assert redact.visible(f"Go {flag}!") == f"Go {flag}!"  # England, Scotland, Wales
    for hidden in ("send the key", "ignoreall", "gbengx1", "GBENG", "g", "gb-eng"):
        assert redact.visible("\U0001F3F4" + _tags(hidden) + "!") == "\U0001F3F4!"


# Found by hand: names kept through fix and a grade of marked-answers.csv again ----------------

SYSTEM = "You are the support assistant.\nAnswer from the policy only."
CHAT = "user: Where is my bag?\nassistant: Let me look.\nuser: Is it lost?"


def _named_project(root):
    """A promptfoo project whose questions are two named values, every answer marked."""
    import contextlib
    import io
    import json

    from judgekeeper.cli import main
    from judgekeeper.start_label import StartSession, Workspace
    from tests.start_projects import promptfoo_data, question
    from tests.test_fix import closed

    n = 60
    data = promptfoo_data([i % 2 == 0 for i in range(n)])
    for i, row in enumerate(data["results"]["results"]):
        row["vars"] = row["testCase"]["vars"] = (
            {"question": question(i), "system": SYSTEM} if i else {"question": CHAT})
    (root / "results.json").write_text(json.dumps(data), encoding="utf-8")
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        assert main(["--no-browser"]) == 0
        ws = Workspace(root)
        closed(ws)
        session = StartSession(ws)
        for k, item in enumerate(session.items):
            session.update({"id": item["id"], "label": "pass" if k % 2 else "fail",
                            "seconds": 3})
        main(["fix"])
    return ws, data


def test_a_grade_of_marked_answers_again_keeps_the_names_on_both_pages(tmp_path, monkeypatch):
    import csv
    import json

    from judgekeeper import batches, fix, start
    from judgekeeper.start_label import StartSession

    root = tmp_path / "bot"
    root.mkdir()
    monkeypatch.chdir(root)
    ws, data = _named_project(root)
    with open(ws.dir / "fix" / "marked-answers.csv", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    named = next(r for r in rows if r["question"].startswith("question: "))
    assert named["question"].endswith("system: " + SYSTEM)  # display(vars): one text
    # the eval asks marked-answers.csv again: its question comes back as one value, with a
    # new answer, so it joins as a new batch
    again = json.loads(json.dumps(data))
    row = again["results"]["results"][0]
    row["vars"] = row["testCase"]["vars"] = {"question": named["question"], "answer": "New."}
    row["response"]["output"] = "New."
    again["results"]["results"] = [row]
    (root / "again.json").write_text(json.dumps(again), encoding="utf-8")
    assert batches.add(ws, start.find_judge(root)) == 1
    new = next(r for r in StartSession(ws).state()["items"] if r["output"] == "New.")
    assert new["input"][0] == ["question", named["question"].split("\n")[0][len("question: "):]]
    assert ["system", SYSTEM] in new["input"]  # the marking page and its list: the names
    m = fix.Marks(ws)
    shown = fix._fields(m, {"id": new["id"], "output": "New."})
    assert shown and ["system", SYSTEM] in shown  # the result page and report.html


def test_a_chat_transcript_stays_plain_text_on_both_pages(tmp_path, monkeypatch):
    from judgekeeper import fix
    from judgekeeper.start_label import StartSession, shown_question

    root = tmp_path / "bot"
    root.mkdir()
    monkeypatch.chdir(root)
    ws, _ = _named_project(root)
    items = StartSession(ws).state()["items"]
    chat = [i for i in items if i["input"] == CHAT]
    assert chat  # shown as it is
    assert shown_question(ws, CHAT) == CHAT
    m = fix.Marks(ws)
    assert fix._question(m, {"id": chat[0]["id"], "output": ""}) == CHAT


# Shut, a long row or group comes back into view -------------------------------------------

def _report_script(scenario: str) -> dict:
    """The result page's script in node, against a small stand-in: one row with its Show all,
    one group with its Show N more, and each one's top on the screen given by `top`."""
    import json
    import shutil
    import subprocess
    import tempfile
    from pathlib import Path

    import pytest

    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node to run the page's script")
    stub = r"""
var scrolled = [];
function El(name) { this.name = name; this.attrs = {}; this.hidden = false; this.listeners = {};
  this.textContent = ""; this.className = ""; this.rows = []; this.top = 0; this.up = null;
  var self = this; this.classList = { toggle: function () {}, contains: function () {
    return false; } }; }
El.prototype.getAttribute = function (k) { return k in this.attrs ? this.attrs[k] : null; };
El.prototype.setAttribute = function (k, v) { this.attrs[k] = String(v); };
El.prototype.hasAttribute = function (k) { return k in this.attrs; };
El.prototype.removeAttribute = function (k) { delete this.attrs[k]; };
El.prototype.addEventListener = function (t, f) { this.listeners[t] = f; };
El.prototype.querySelectorAll = function () { return this.rows; };
El.prototype.closest = function (sel) { return this.up[sel] || null; };
El.prototype.getBoundingClientRect = function () { return {top: this.top}; };
El.prototype.scrollIntoView = function (o) { scrolled.push([this.name, o && o.block]); };
var row = new El("row"), open = new El("open-row"), section = new El("section");
var table = new El("table"), more = new El("more");
open.up = {tr: row}; more.up = {section: section};
more.attrs["aria-controls"] = "t-easy"; more.attrs["data-n"] = "2";
table.rows = [new El(), new El()];
var document = {documentElement: new El("html"),
  getElementById: function (id) { return id === "t-easy" ? table : null; },
  querySelectorAll: function (s) { return s === ".open-row" ? [open] : s === ".more" ? [more] : []; },
  addEventListener: function () {}};
var window = {addEventListener: function () {}};
"""
    with tempfile.TemporaryDirectory() as folder:
        script = Path(folder) / "page.js"
        script.write_text(stub + report_page.SCRIPT + scenario, encoding="utf-8")
        out = subprocess.run([node, str(script)], check=True, capture_output=True, text=True,
                             encoding="utf-8", timeout=60)
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_a_shut_row_or_group_above_the_screen_comes_back_into_view():
    got = _report_script(r"""
      var seen = [];
      open.listeners.click(); row.top = -4000; open.listeners.click();  // opened, read, shut
      seen.push(scrolled.splice(0));
      open.listeners.click(); row.top = 120; open.listeners.click();  // still on the screen
      seen.push(scrolled.splice(0));
      more.listeners.click(); section.top = -900; more.listeners.click();
      seen.push(scrolled.splice(0));
      more.listeners.click(); section.top = 0; more.listeners.click();
      seen.push(scrolled.splice(0));
      console.log(JSON.stringify(seen));""")
    assert got == [[["row", "start"]], [], [["section", "start"]], []]


# What the person reads is the text as written: "->" stays "->" ------------------------------

NO_LIGATURES = ' { font-variant-ligatures: none; font-feature-settings: "calt" 0, "liga" 0; }'


def test_answers_questions_and_reasons_show_no_ligatures():
    assert (".question, .answer, .item .q, .rule" + NO_LIGATURES) in mark_page.STYLE
    assert (".tbl td[data-label], .said, .why" + NO_LIGATURES) in report_page.STYLE
    html = start_label.result_html(_result(*NOT_GATE_TNR), fixing={"mistakes": _mistakes(1, 0)})
    assert ".tbl td[data-label], .said, .why" + NO_LIGATURES in html  # the live result page


def test_the_foot_line_is_centred_under_the_buttons_on_a_wide_screen():
    laptop = _laptop()
    assert (".row, .actions, .status, .foot { padding-right: max(40px, calc(100cqw - 1160px)); }"
            in laptop)
    # a short wide screen keeps that right padding: no shorthand puts 40px back
    short = mark_page.STYLE.split("@media (min-width: 761px) and (max-height: 800px) {", 1)[1]
    short = short.split("\n}\n", 1)[0]
    assert ".actions { padding-top: 12px; padding-bottom: 8px; }" in short
    assert ".foot { padding-top: 8px; padding-bottom: 8px; }" in short
