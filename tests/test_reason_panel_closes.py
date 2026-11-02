"""On the result page, a reason saved from a button or with Enter closes its panel, and the
row's line shows the reason; a pause while typing saves without closing it."""

from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from judgekeeper import report_page
from tests.test_long_text import _REASONS_DOM

_PANEL = r"""
var chip = new El("button"), panel = new El("div"), words = new El("b"), focused = null;
chip.attrs = {"aria-pressed": "false", "data-reason": "wrong_fact", "data-said": "a wrong fact"};
box.querySelectorAll = function () { return [chip]; };
parts[".said-text"].querySelector = function () { return words; };
var add = parts[".add-reason"];
add.attrs = {"aria-expanded": "false", "aria-controls": "wb-0"};
panel.hidden = true;
document.getElementById = function (id) { return id === "wb-0" ? panel : cell; };
El.prototype.focus = function () { focused = this; };
window.fetch = function (url, o) { sent.push(JSON.parse(o.body));
  return {then: function (ok) { ok({ok: true}); }}; };
function state() {
  return {open: !panel.hidden, expanded: add.getAttribute("aria-expanded"),
          button: add.textContent, said: parts[".said-now"].hidden ? null : words.textContent,
          focus: focused === add ? "add" : focused === input ? "input" : null};
}
"""


def _run(tmp_path, scenario: str):
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node to run the page's script")
    script = tmp_path / "page.js"
    script.write_text(_REASONS_DOM + _PANEL + report_page.REASONS_SCRIPT + scenario,
                      encoding="utf-8")
    out = subprocess.run([node, str(script)], check=True, capture_output=True, text=True,
                         encoding="utf-8", timeout=60)
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_a_reason_button_saved_closes_the_panel_and_shows_the_reason(tmp_path):
    got = _run(tmp_path, """
      var steps = [];
      add.fire("click"); steps.push(state());
      chip.fire("click"); steps.push(state());
      console.log(JSON.stringify(steps));""")
    assert got[0]["open"] and got[0]["expanded"] == "true"
    assert got[1] == {"open": False, "expanded": "false", "button": "Change",
                      "said": "a wrong fact", "focus": "add"}


def test_typing_saves_on_a_pause_and_closes_on_enter(tmp_path):
    got = _run(tmp_path, """
      var steps = [];
      add.fire("click"); type("Gives a price"); wait(1500); steps.push(state());
      input.fire("keydown", {key: "Enter"}); steps.push(state());
      add.fire("click"); input.fire("keydown", {key: "Enter"}); steps.push(state());
      steps.push(sent.length);  // Enter with nothing new: closed, not sent again
      console.log(JSON.stringify(steps));""")
    assert got[0]["open"] and got[0]["said"] == "“Gives a price”"
    assert not got[1]["open"] and got[1]["said"] == "“Gives a price”"
    assert not got[2]["open"] and got[3] == 1
