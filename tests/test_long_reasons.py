"""A long reason on the result page: "Your reason: ..." is cut to one line, the row's "Show
more" opens it in full, and "Show less" puts it back on one line. The person's own reason
buttons show at most two lines, with the whole reason in their title and name."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from judgekeeper import report_page
from tests.test_long_text import _REASONS_DOM, _html, _with_reason

LONG = ("The answer gives the old price & says <free> delivery \"today\", " * 8).strip()


def _node(script: str) -> list:
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node to run the page's script")
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "page.js"
        path.write_text(script, encoding="utf-8")
        out = subprocess.run([node, str(path)], check=True, capture_output=True, text=True,
                             encoding="utf-8", timeout=60)
    return json.loads(out.stdout.strip().splitlines()[-1])


# The row's "Show more" counts the reason line --------------------------------------------------

_ROW_DOM = r"""
function List() { var a = []; a.contains = function (c) { return a.indexOf(c) >= 0; };
  a.toggle = function (c, on) { var i = a.indexOf(c); if (on && i < 0) { a.push(c); }
    if (!on && i >= 0) { a.splice(i, 1); } }; return a; }
function El() { this.attrs = {}; this.listeners = {}; this.hidden = false; this.classList = List();
  this.textContent = ""; this.scrollHeight = 100; this.clientHeight = 100;
  this.scrollWidth = 400; this.clientWidth = 400; }
El.prototype.getAttribute = function (k) { return k in this.attrs ? this.attrs[k] : null; };
El.prototype.setAttribute = function (k, v) { this.attrs[k] = String(v); };
El.prototype.hasAttribute = function (k) { return k in this.attrs; };
El.prototype.removeAttribute = function (k) { delete this.attrs[k]; };
El.prototype.addEventListener = function (t, f) { this.listeners[t] = f; };
El.prototype.getBoundingClientRect = function () { return {top: 10}; };
var row = new El(), button = new El(), cells = [new El(), new El()], said = new El();
button.closest = function () { return row; };
row.querySelectorAll = function (s) { return s.indexOf("said") >= 0 ? [said] : cells; };
var resized = [];
var document = {querySelectorAll: function (s) { return s === ".open-row" ? [button] : []; },
  addEventListener: function () {}};
var window = {addEventListener: function (t, f) { if (t === "resize") { resized.push(f); } }};
"""


def test_a_reason_line_too_long_for_its_row_gives_the_row_show_more():
    scenario = """
      var steps = [button.hidden];  // everything fits
      said.scrollWidth = 900; resized.forEach(function (f) { f(); });
      steps.push(button.hidden);  // the reason line is cut: Show more
      button.listeners.click(); steps.push([button.hidden, button.textContent]);
      said.scrollWidth = 400;  // open, the line wraps and fits
      resized.forEach(function (f) { f(); }); steps.push(button.hidden);
      said.scrollWidth = 900; button.listeners.click();  // Show less: one line, cut again
      steps.push([button.hidden, button.textContent, row.hasAttribute("data-open")]);
      console.log(JSON.stringify(steps));"""
    got = _node(_ROW_DOM + report_page.SCRIPT + scenario)
    assert got == [True, False, [False, "Show less"], False, [False, "Show more", False]]


def test_the_cells_alone_still_decide_when_the_reason_line_fits():
    scenario = """
      var steps = [];
      cells[1].scrollHeight = 300; resized.forEach(function (f) { f(); });
      steps.push([button.hidden, cells[1].classList.contains("cut")]);
      cells[1].scrollHeight = 100; resized.forEach(function (f) { f(); });
      steps.push(button.hidden);
      console.log(JSON.stringify(steps));"""
    assert _node(_ROW_DOM + report_page.SCRIPT + scenario) == [[False, True], True]


def test_an_open_row_shows_its_reason_line_whole_and_wrapped():
    assert ("tr[data-open] .said, tr[data-open] .said-text { white-space: normal; "
            "overflow-wrap: anywhere; }") in report_page.STYLE
    # its buttons stay by the reason's first line, not halfway down a long one
    assert ("tr[data-open] .why-line, tr[data-open] .row-foot { align-items: flex-start; }"
            in report_page.STYLE)
    # shut, the line stays one line, cut with "…"
    assert (".said-text, .said { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; "
            "min-width: 0; }") in report_page.STYLE


def test_a_reason_saved_tells_the_row_to_measure_again():
    scenario = """
      var events = [];
      window.dispatchEvent = function (e) { events.push(e.type); };
      window.fetch = function () { return {then: function (ok) { return ok(REPLY); }}; };
      parts[".said-text"].querySelector = function () { return new El("b"); };
      type("Gives the old price"); input.fire("keydown", {key: "Enter"});
      console.log(JSON.stringify(events));"""
    assert _node(_REASONS_DOM + _REPLY + report_page.REASONS_SCRIPT + scenario) == ["resize"]


# The page's answer to a reason saved, as the server sends it (summary.prompt: the coding
# agent's prompt now, when there is one)
_REPLY = """
var PROMPT = null, promptBox = new El("code");
var REPLY = {ok: true, json: function () { return {then: function (f) {
  return f({summary: PROMPT ? {prompt: PROMPT} : {}}); }}; }};
document.querySelector = function (s) { return s === ".cmd.prompt code" ? promptBox : null; };
"""


def test_a_reason_saved_puts_the_prompt_the_terminal_says_in_the_box():
    scenario = """
      window.dispatchEvent = function () {};
      window.fetch = function () { return {then: function (ok) { return ok(REPLY); }}; };
      parts[".said-text"].querySelector = function () { return new El("b"); };
      promptBox.textContent = "Read it. It lists answers my AI gave that I marked Fail.";
      var seen = [];
      type("Gives the old price"); input.fire("keydown", {key: "Enter"});
      seen.push(promptBox.textContent);  // no prompt in the answer: the box stays as it is
      PROMPT = "Read it. It lists answers my AI gave that I marked Fail, with my reasons.";
      type("Gives the old price again"); input.fire("keydown", {key: "Enter"});
      seen.push(promptBox.textContent);
      console.log(JSON.stringify(seen));"""
    assert _node(_REASONS_DOM + _REPLY + report_page.REASONS_SCRIPT + scenario) == [
        "Read it. It lists answers my AI gave that I marked Fail.",
        "Read it. It lists answers my AI gave that I marked Fail, with my reasons."]


# The person's own reason buttons ---------------------------------------------------------------

def _chips(html: str) -> list[str]:
    return re.findall(r'<button type="button" class="chip"[^>]*>', html)


def test_an_own_reason_button_has_the_whole_reason_in_its_title_and_name():
    own = [{"id": "own-1", "text": LONG, "from": "other-answer"}]
    html = _html([_with_reason({})], live=True, own=own)
    mine = [c for c in _chips(html) if 'data-reason="own-1"' in c]
    assert len(mine) == 1
    whole = report_page._e(LONG)
    assert f'title="{whole}"' in mine[0] and f'aria-label="{whole}"' in mine[0]
    assert "<free>" not in mine[0] and "&lt;free&gt;" in mine[0]
    built_in = [c for c in _chips(html) if 'data-reason="own-' not in c]
    assert built_in and all("title=" not in c and "aria-label=" not in c for c in built_in)


def test_an_own_reason_button_shows_at_most_two_lines_and_breaks_long_words():
    """The text, not the button, stops at two lines: a button cut at two lines would let the
    third line show in its padding."""
    own = [{"id": "own-1", "text": LONG, "from": "other-answer"}]
    html = _html([_with_reason({})], live=True, own=own)
    assert f'<span class="t">{report_page._e(LONG)}</span></button>' in html
    rule = report_page.STYLE.split('.chip[data-reason^="own-"] .t {', 1)[1].split("}", 1)[0]
    for part in ("display: -webkit-box;", "-webkit-line-clamp: 2;", "line-clamp: 2;",
                 "-webkit-box-orient: vertical;", "overflow: hidden;", "overflow-wrap: anywhere;"):
        assert part in rule, part
