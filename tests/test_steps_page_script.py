"""The steps marking page's script, run in node against a small stand-in for the browser
(as test_mark_page_script.py does for the answers page): picking a step, "All steps are
fine", Next and Undo by click and by key, the guards (held keys, Cmd/Ctrl/Alt, 250 ms after a
run shows, 400 ms between undos), the welcome box, "Show all", and what is sent. The tests
skip where node is not installed (CI's runners have it)."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from judgekeeper import steps_page

DOM = r"""
var NOW = 1000000; Date.now = function () { return NOW; };
var sent = [], reloads = 0, answer = null;
function El(tag) {
  this.tagName = (tag || "div").toUpperCase(); this.children = []; this.attrs = {};
  this.style = {}; this.hidden = false; this._text = ""; this.listeners = {};
  this.className = ""; this.parentNode = null; this.disabled = false; this.scrollTop = 0;
  var self = this;
  this.classList = {
    add: function (c) { if (!self.classList.contains(c)) { self.className += " " + c; } },
    remove: function (c) { self.className = self.className.split(" ").filter(
      function (x) { return x !== c; }).join(" "); },
    contains: function (c) { return self.className.split(" ").indexOf(c) > -1; },
    toggle: function (c, on) { if (on === undefined) { on = !self.classList.contains(c); }
      if (on) { self.classList.add(c); } else { self.classList.remove(c); } }
  };
}
Object.defineProperty(El.prototype, "textContent", {
  get: function () { return this._text + this.children.map(function (c) {
    return c.textContent; }).join(""); },
  set: function (v) { this._text = String(v); this.children = []; }
});
El.prototype.appendChild = function (c) {
  if (c.parentNode) { c.parentNode.removeChild(c); }
  this.children.push(c); c.parentNode = this; return c; };
El.prototype.removeChild = function (c) {
  this.children = this.children.filter(function (x) { return x !== c; }); c.parentNode = null; };
El.prototype.setAttribute = function (k, v) { this.attrs[k] = String(v); };
El.prototype.getAttribute = function (k) { return k in this.attrs ? this.attrs[k] : null; };
El.prototype.removeAttribute = function (k) { delete this.attrs[k]; };
El.prototype.addEventListener = function (t, f) {
  (this.listeners[t] = this.listeners[t] || []).push(f); };
El.prototype.focus = function () { document.activeElement = this; };
El.prototype.scrollIntoView = function () {};
El.prototype.closest = function (sel) {
  var e = this; while (e && !(sel.charAt(0) === "." ? e.classList.contains(sel.slice(1))
    : e.tagName === sel.toUpperCase())) { e = e.parentNode; } return e; };
El.prototype.fire = function (type, extra) {
  if (type === "click" && this.disabled) { return {type: type, defaultPrevented: false}; }
  var e = Object.assign({type: type, target: this, defaultPrevented: false, button: 0,
    preventDefault: function () { this.defaultPrevented = true; },
    stopPropagation: function () { this.stopped = true; }}, extra || {});
  var at = this;
  while (at && !e.stopped) {
    (at.listeners[type] || []).slice().forEach(function (f) { f(e); });
    at = type === "click" ? at.parentNode : null;  // a click bubbles, as in a browser
  }
  return e; };
var ids = {};
var document = {
  activeElement: null, listeners: {},
  getElementById: function (id) { if (!ids[id]) { ids[id] = new El(); ids[id].id = id; }
    return ids[id]; },
  createElement: function (t) { return new El(t); },
  createTextNode: function (t) { var e = new El("#text"); e._text = String(t); return e; },
  addEventListener: function (t, f) { (this.listeners[t] = this.listeners[t] || []).push(f); }
};
function key(k, extra) {
  var e = Object.assign({key: k, repeat: false, ctrlKey: false, metaKey: false, altKey: false,
    shiftKey: false, target: document.activeElement || ids["card"], defaultPrevented: false,
    preventDefault: function () { this.defaultPrevented = true; }}, extra || {});
  (document.listeners.keydown || []).forEach(function (f) { f(e); });
  return e;
}
var window = {location: {reload: function () { reloads += 1; }, href: ""},
              matchMedia: function () { return {matches: false}; }};
var marked = DATA.marked || 0;
function fetch(url, opts) {
  if (!opts || !opts.body) {  // GET /state, after a stale tab
    return Promise.resolve({ok: true, status: 200,
      json: function () { return Promise.resolve(REFRESHED || DATA); }});
  }
  var body = JSON.parse(opts.body);
  sent.push({url: url, body: body});
  if (answer) { return answer(body); }
  if (body.first_wrong_step === null) { marked -= 1; }
  else if (body.was === null) { marked += 1; }
  return Promise.resolve({ok: true, status: 200, json: function () {
    return Promise.resolve({summary: {marked: marked, total: DATA.total,
                                      done: marked === DATA.total}}); }});
}
var REFRESHED = null;
function settle() { return new Promise(function (r) { setImmediate(r); }); }
async function settled() { for (var n = 0; n < 6; n++) { await settle(); } }
function later(ms) { NOW += ms; }
function stepButtons() {
  return ids["steps"].children.map(function (li) { return li.children[0]; }); }
function picked() {
  var b = stepButtons().filter(function (b) { return b.classList.contains("you"); });
  return b.length ? +b[0].getAttribute("data-n") : ids["fine"].classList.contains("you") ? 0 : null;
}
function tags() {
  return stepButtons().map(function (b) {
    return b.children.filter(function (c) { return c.classList.contains("tag"); })
      .map(function (c) { return c.textContent; }).join(""); }); }
document.getElementById("intro").hidden = true;  // as the page's HTML has it
document.getElementById("see").hidden = true;
document.getElementById("data")._text = JSON.stringify(DATA);
"""


def _script() -> str:
    page = steps_page.page_template("judgekeeper steps runs.jsonl")
    return re.search(r'<script nonce="__NONCE__">\n(.*?)</script>', page, re.DOTALL)[1] \
        .replace("__TOKEN__", "t0k")


def _data(n=3, k=4, marks=None, intro=False, total=None, start=0, long=None) -> dict:
    marks = marks or {}
    runs = []
    for i in range(n):
        made = [{"role": "assistant" if s % 2 else "user", "text": f"Step {s + 1} of run {i}"}
                for s in range(k)]
        if long is not None:
            made[0]["text"] = long
        runs.append({"id": f"r{i}", "n": i + 1, "task": f"Task {i}" if i != 1 else None,
                     "steps": made, "mark": marks.get(i)})
    return {"runs": runs, "start": start, "total": total or n,
            "marked": sum(v is not None for v in marks.values()), "intro": intro}


def _run(scenario: str, data: dict | None = None) -> dict:
    node = shutil.which("node")
    if node is None:
        if os.environ.get("JUDGEKEEPER_NEEDS_NODE"):
            pytest.fail("node is missing: the page's script must run here")
        pytest.skip("needs node to run the page's script")
    code = (f"var DATA = {json.dumps(data or _data())};\n{DOM}\n" + _script()
            + "\n(async function () {\n" + scenario + "\n})();")
    with tempfile.TemporaryDirectory() as folder:
        script = Path(folder) / "page.js"
        script.write_text(code, encoding="utf-8")
        out = subprocess.run([node, str(script)], check=False, capture_output=True, text=True,
                             encoding="utf-8", timeout=60)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_the_first_run_shows_its_task_and_numbered_steps():
    got = _run("""
      console.log(JSON.stringify({task: ids["task"].textContent, row: ids["task-row"].hidden,
        n: stepButtons().length, first: stepButtons()[0].textContent,
        where: ids["where"].textContent, next: ids["next"].disabled}));""")
    assert got["task"] == "Task 0" and got["row"] is False and got["n"] == 4
    assert "1" in got["first"] and "user" in got["first"] and "Step 1 of run 0" in got["first"]
    assert got["where"] == "Run 1 of 3" and got["next"] is True


def test_clicking_a_step_selects_it_with_you_and_another_click_moves_it():
    got = _run("""
      later(300);
      stepButtons()[1].fire("click"); var one = [picked(), tags()];
      stepButtons()[3].fire("click"); var two = [picked(), tags()];
      console.log(JSON.stringify({one: one, two: two, sent: sent.length,
                                  next: ids["next"].disabled}));""")
    assert got["one"] == [2, ["", "You", "", ""]]
    assert got["two"] == [4, ["", "", "", "You"]]
    assert got["sent"] == 0 and got["next"] is False  # nothing saved until Next


def test_next_sends_the_pick_and_shows_the_next_run():
    got = _run("""
      later(5000); stepButtons()[2].fire("click"); ids["next"].fire("click"); await settled();
      console.log(JSON.stringify({sent: sent, task: ids["task"].textContent,
        row: ids["task-row"].hidden, where: ids["where"].textContent, pick: picked()}));""")
    assert len(got["sent"]) == 1
    body = got["sent"][0]["body"]
    assert got["sent"][0]["url"] == "/label?token=t0k"
    assert set(body) == {"id", "first_wrong_step", "was", "seconds"}
    assert body == {"id": "r0", "first_wrong_step": 3, "was": None, "seconds": 5}
    assert got["row"] is True  # run 2 has no task: no task row
    assert got["where"] == "Run 2 of 3" and got["pick"] is None


def test_all_steps_are_fine_sends_0():
    got = _run("""
      later(300); ids["fine"].fire("click"); var tag = picked();
      ids["next"].fire("click"); await settled();
      console.log(JSON.stringify({tag: tag, sent: sent[0].body.first_wrong_step}));""")
    assert got == {"tag": 0, "sent": 0}


def test_the_keys_pick_steps_0_is_fine_enter_and_arrow_go_on():
    got = _run("""
      later(300); key("2"); var a = picked(); key("4"); var b = picked();
      key("9"); var c = picked();  // run 1 has 4 steps: 9 picks nothing
      key("Enter"); await settled();
      later(300); key("0"); var d = picked(); key("ArrowRight"); await settled();
      console.log(JSON.stringify({a: a, b: b, c: c, d: d,
        sent: sent.map(function (s) { return s.body.first_wrong_step; })}));""")
    assert got == {"a": 2, "b": 4, "c": 4, "d": 0, "sent": [4, 0]}


def test_held_keys_and_modifier_keys_do_nothing():
    got = _run("""
      later(300);
      key("2", {repeat: true}); key("2", {metaKey: true}); key("2", {ctrlKey: true});
      key("2", {altKey: true});
      var none = picked();
      key("2"); key("Enter", {repeat: true}); key("Enter", {ctrlKey: true}); await settled();
      console.log(JSON.stringify({none: none, pick: picked(), sent: sent.length}));""")
    assert got == {"none": None, "pick": 2, "sent": 0}


def test_nothing_within_250_ms_of_a_run_showing():
    got = _run("""
      later(300); key("1"); key("Enter"); await settled();
      later(100); key("3"); var early = picked(); key("Enter"); await settled();
      var sentEarly = sent.length;
      later(200); key("3"); key("Enter"); await settled();
      console.log(JSON.stringify({early: early, sentEarly: sentEarly, sent: sent.length}));""")
    assert got == {"early": None, "sentEarly": 1, "sent": 2}


def test_undo_takes_back_the_last_saved_mark_and_waits_400_ms():
    got = _run("""
      later(300); key("2"); key("Enter"); await settled();
      later(300); key("3"); key("Enter"); await settled();
      later(500); key("z"); await settled();
      var back = [ids["where"].textContent, picked()];
      later(100); key("u"); await settled();  // within 400 ms: nothing
      var locked = sent.length;
      later(400); key("u"); await settled();
      console.log(JSON.stringify({back: back, locked: locked,
        where: ids["where"].textContent, pick: picked(),
        sent: sent.map(function (s) { return [s.body.id, s.body.first_wrong_step, s.body.was]; })
      }));""")
    assert got["back"] == ["Run 2 of 3", None]  # taken back: to pick again
    assert got["locked"] == 3
    assert got["sent"] == [["r0", 2, None], ["r1", 3, None], ["r1", None, 3], ["r0", None, 2]]
    assert got["where"] == "Run 1 of 3" and got["pick"] is None


def test_undo_with_nothing_to_take_back_says_so():
    got = _run("""later(300); ids["undo"].fire("click"); await settled();
      console.log(JSON.stringify({status: ids["status"].textContent, sent: sent.length}));""")
    assert got == {"status": "Nothing to undo.", "sent": 0}


def test_next_reads_see_your_result_on_the_last_unmarked_run_and_opens_it():
    got = _run("""
      var on = [ids["next-text"].textContent];
      later(300); key("1"); key("Enter"); await settled();
      on.push(ids["next-text"].textContent);
      later(300); key("0"); key("Enter"); await settled();
      await new Promise(function (r) { setTimeout(r, 50); });
      console.log(JSON.stringify({on: on, href: window.location.href}));""",
                data=_data(n=3, marks={1: 2}))
    assert got["on"] == ["Next", "See your result"]
    assert got["href"] == "/result?token=t0k"


def test_marked_runs_are_passed_over():
    got = _run("""
      later(300); key("1"); key("Enter"); await settled();
      console.log(JSON.stringify({where: ids["where"].textContent}));""",
                data=_data(n=4, marks={1: 0}))
    assert got["where"] == "Run 3 of 4"


def test_past_the_runs_the_page_holds_it_asks_for_more():
    got = _run("""
      later(300); key("1"); key("Enter"); await settled();
      later(300); key("1"); key("Enter"); await settled();
      console.log(JSON.stringify({reloads: reloads, href: window.location.href}));""",
                data=_data(n=2, total=5))
    assert got == {"reloads": 1, "href": ""}


def test_see_the_numbers_so_far_shows_from_the_first_mark():
    got = _run("""
      var before = ids["see"].hidden;
      later(300); key("1"); key("Enter"); await settled();
      console.log(JSON.stringify({before: before, after: ids["see"].hidden,
        text: ids["see"].textContent, href: ids["see"].getAttribute("href")}));""")
    assert got == {"before": True, "after": False, "text": "See the numbers so far",
                   "href": "/result?token=t0k"}


def test_the_welcome_box_shows_until_start_marking_and_keys_wait_for_it():
    got = _run("""
      var shown = !ids["intro"].hidden;
      later(300); key("1"); var behind = picked();
      ids["intro-ok"].fire("click");
      later(300); key("1");
      console.log(JSON.stringify({shown: shown, behind: behind, gone: ids["intro"].hidden,
                                  pick: picked()}));""", data=_data(intro=True))
    assert got == {"shown": True, "behind": None, "gone": True, "pick": 1}


def test_a_long_step_is_cut_at_600_characters_and_show_all_never_marks():
    got = _run("""
      function text() { return stepButtons()[0].children[1].children[1].textContent; }
      function more() { return ids["steps"].children[0].children[1]; }
      var other = ids["steps"].children[1].children[1];
      var cut = text().length, label = more().textContent, hiddenOther = !other || other.hidden;
      later(300); more().fire("click");
      var whole = text().length, label2 = more().textContent;
      more().fire("click");
      console.log(JSON.stringify({cut: cut, whole: whole, label: label, label2: label2,
        again: text().length, pick: picked(), sent: sent.length, other: hiddenOther}));""",
                data=_data(long="x" * 100_000))
    assert got["cut"] == 601  # 600 and "…"
    assert got["whole"] == 100_000 and got["again"] == 601
    assert got["label"] == "Show all" and got["label2"] == "Show less"
    assert got["pick"] is None and got["sent"] == 0 and got["other"] is True


def test_a_stale_tab_says_so_and_takes_the_list_again():
    got = _run("""
      answer = function () { return Promise.resolve({ok: false, status: 409, json: function () {
        return Promise.resolve({error: "x", stale: true}); }}); };
      REFRESHED = JSON.parse(JSON.stringify(DATA)); REFRESHED.runs[0].mark = 1;
      REFRESHED.start = 1; REFRESHED.marked = 1;
      later(300); key("2"); key("Enter"); await settled();
      console.log(JSON.stringify({status: ids["status"].textContent,
                                  where: ids["where"].textContent}));""")
    assert got["status"] == ("Not marked: this run was already marked in another tab. "
                             "The list is up to date again.")
    assert got["where"] == "Run 2 of 3"


def test_no_answer_from_judgekeeper_says_the_marks_are_kept():
    got = _run("""
      answer = function () { return Promise.reject(new Error("gone")); };
      later(300); key("2"); key("Enter"); await settled();
      console.log(JSON.stringify({status: ids["status"].textContent, pick: picked(),
                                  where: ids["where"].textContent}));""")
    assert got["status"].startswith("Not saved: judgekeeper's marking page isn't answering.")
    assert got["pick"] == 2 and got["where"] == "Run 1 of 3"


def test_two_hundred_steps_render_and_an_empty_one_says_so():
    data = _data(n=1, k=200)
    data["runs"][0]["steps"][7]["text"] = ""
    got = _run("""
      console.log(JSON.stringify({n: stepButtons().length,
        empty: stepButtons()[7].textContent}));""", data=data)
    assert got["n"] == 200 and "(empty step)" in got["empty"]


def test_a_marked_run_shown_again_shows_its_mark():
    got = _run("""console.log(JSON.stringify({pick: picked(), next: ids["next"].disabled}));""",
               data=_data(n=2, marks={0: 3}, start=0))
    assert got == {"pick": 3, "next": False}
