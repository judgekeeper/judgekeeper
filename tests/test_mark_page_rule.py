"""The marking page says what is being graded: the metric's name above the answer, and a "Show
the rule" button that shows the LLM-as-a-judge's rule when the results file has one. The
LLM-as-a-judge's grade stays hidden."""

from __future__ import annotations

import re
from html import unescape

import pytest

from judgekeeper import mark_page, page, start, start_label, textio
from tests.start_projects import promptfoo_project, split
from tests.test_label_server import Client

KEY = "sk-ant-api03-" + "a" * 40


def _page(**kw) -> str:
    return mark_page.label_page(None, "judgekeeper mark", model="openai:gpt-4.1-mini",
                                tool="promptfoo", **kw)


def _text(html: str) -> str:
    html = html.split("<body>", 1)[-1].split("<script", 1)[0]
    return " ".join(unescape(re.sub(r"<[^>]+>", " ", html)).split())


def test_the_metric_name_shows_above_the_answer():
    html = _page(metric="faithful", rule="Pass only answers the sources back up.")
    shown = html.index('id="metric-name"')
    assert shown < html.index('id="a-text"')
    assert '<span class="metric-name" id="metric-name">faithful</span>' in html
    assert "Metric faithful" in _text(html)


def test_the_rule_is_behind_a_button():
    html = _page(metric="faithful", rule="Pass only answers <b>the sources</b> back up.")
    assert ('<button type="button" class="quiet rule-btn" id="rule-btn" aria-expanded="false" '
            'aria-controls="rule">Show the rule</button>') in html
    box = html.split('<div class="rule" id="rule" hidden>', 1)[1].split("</div>", 2)
    assert "Pass only answers &lt;b&gt;the sources&lt;/b&gt; back up." in "".join(box)
    assert "<b>the sources</b>" not in html  # escaped, never markup


def test_no_rule_no_button():
    html = _page(metric="faithful")
    assert 'id="rule-btn"' not in html and 'id="rule"' not in html
    assert "Show the rule" not in _text(html)
    assert "Metric faithful" in _text(html)
    html = _page()
    assert 'id="metric-name"' not in html and 'id="rule-btn"' not in html


def test_a_key_in_the_rule_is_hidden(monkeypatch):
    html = _page(metric="faithful", rule=f"Be kind. Call it with {KEY} if unsure.")
    assert KEY not in html and "[REDACTED]" in html


def test_a_long_rule_is_cut_with_an_ellipsis():
    rule = "Be kind. " * 1000
    html = _page(metric="m", rule=rule)
    box = html.split('<p class="rule-text" id="rule-text">', 1)[1].split("</p>", 1)[0]
    assert box.endswith("…") and len(box) <= mark_page.RULE_CHARS + 1


@pytest.mark.parametrize("joiner", ["\u200d", "\u200c", "\u200b"])
def test_a_long_key_split_by_a_hidden_character_is_hidden_whole_in_the_rule(joiner):
    head, tail = "sk-ant-api03-" + "a" * 20, "b" * 30
    html = _page(metric="m", rule=f"Use {head}{joiner}{tail} to call it.")
    box = html.split('<p class="rule-text" id="rule-text">', 1)[1].split("</p>", 1)[0]
    assert box == "Use [REDACTED] to call it."
    assert head not in html and tail not in html


def test_a_long_metric_name_is_cut_with_an_ellipsis():
    html = _page(metric="m" * 1000, rule="Be kind.")
    name = html.split('id="metric-name">', 1)[1].split("</span>", 1)[0]
    assert name == "m" * mark_page.METRIC_CHARS + "…"
    assert mark_page.METRIC_CHARS == 200
    assert "m" * 200 + "…" not in _page(metric="m" * 200)


def test_hidden_characters_in_the_metric_and_rule_are_dropped():
    html = _page(metric="faith\u202eful", rule="Be\u200b kind.")
    assert "\u202e" not in html and "\u200b" not in html
    assert ">faithful<" in html and "Be kind." in html


def test_the_names_the_server_fills_in_cannot_come_from_the_rule():
    html = _page(metric="__DATA__", rule="__TOKEN__ __NONCE__")
    assert html.count("__DATA__") == 1 and html.count("__TOKEN__") == 1
    assert html.count("__NONCE__") == 1


def test_the_button_shows_and_hides_the_rule_in_the_script():
    script = _page(metric="m", rule="r").split("<script nonce=", 1)[1]
    assert 'Show the rule' in script and 'Hide the rule' in script
    assert '"aria-expanded"' in script


def test_the_grade_stays_hidden_with_the_rule_shown(tmp_path):
    promptfoo_project(tmp_path, split(16, 16))
    ws = start_label.prepare(start.find_judge(tmp_path), say=lambda line: None)
    server = page.page_server(ws, 0)
    import threading

    thread = threading.Thread(target=server.serve, daemon=True)
    thread.start()
    try:
        _, payload = Client(server).request("GET", "/")
    finally:
        server.stop()
        thread.join(timeout=5)
    html = payload.decode()
    assert "Show the rule" in html and "Is polite and correct." in html
    assert ">llm-rubric<" in html
    for gone in ("reason 0", "gradingResult", '"verdict"', '"group"', '"judge"'):
        assert gone not in html, gone


def test_the_rule_is_left_out_when_each_test_has_its_own():
    html = start_label.page_template({"metric": "m", "rule": "Be kind.", "one_rule": False})
    assert 'id="rule-btn"' not in html and "Be kind." not in html
    assert ">m<" in html


# Values held out of the command on Windows ---------------------------------------------------

@pytest.mark.parametrize("windows", [True, False])
def test_held_values_on_the_page_are_scrubbed(monkeypatch, windows):
    monkeypatch.setattr(textio, "is_windows", lambda: windows)
    flags = start.run_flags(metric=f'acc"{KEY}"')
    command = start.command_from(flags, "mark", kept=True)
    html = mark_page.label_page(None, command, held=start.held_values(flags))
    assert KEY not in html
    assert "[REDACTED]" in html
