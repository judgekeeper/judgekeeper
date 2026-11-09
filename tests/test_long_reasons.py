"""A long reason on the result page: "Your reason: ..." is cut to one line, the row's "Show
more" opens it in full, and "Show less" puts it back on one line."""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from judgekeeper import report_page
from tests.test_long_text import _REASONS_DOM


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
      window.fetch = function () { return {then: function (ok) { ok({ok: true}); }}; };
      parts[".said-text"].querySelector = function () { return new El("b"); };
      type("Gives the old price"); input.fire("keydown", {key: "Enter"});
      console.log(JSON.stringify(events));"""
    assert _node(_REASONS_DOM + report_page.REASONS_SCRIPT + scenario) == ["resize"]

