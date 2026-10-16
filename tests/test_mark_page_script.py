"""The marking page's script, run in node against a small stand-in for the browser: marking by
keyboard alone, the lock after each mark, held keys and Cmd/Ctrl/Alt keys, skipping and undo,
the welcome box, and no target number.

The stand-in has only what the page uses: elements by id, text, attributes, classes and
listeners; `fetch` records each request and answers as the server does. The tests skip where
node is not installed (CI's runners have it).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from judgekeeper import mark_page

DOM = r"""
var NOW = 1000000; Date.now = function () { return NOW; };
var sent = [], reloads = 0, stored = {}, storageWorks = true;
function El(tag) {
  this.tagName = (tag || "div").toUpperCase(); this.children = []; this.attrs = {};
  this.style = {}; this.hidden = false; this._text = ""; this.listeners = {};
  this.className = ""; this.parentNode = null; this.scrollTop = 0; this.clientHeight = 0;
  this.scrollHeight = 0; this.offsetTop = 0; this.offsetHeight = 0; this.disabled = false;
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
Object.defineProperty(El.prototype, "innerHTML", {
  get: function () { return this._html || ""; }, set: function (v) { this._html = v; } });
El.prototype.appendChild = function (c) {
  if (c.parentNode) { c.parentNode.removeChild(c); }
  this.children.push(c); c.parentNode = this; return c; };
El.prototype.removeChild = function (c) {
  this.children = this.children.filter(function (x) { return x !== c; }); c.parentNode = null; };
El.prototype.insertBefore = function (c, ref) {
  if (c.parentNode) { c.parentNode.removeChild(c); }
  var i = this.children.indexOf(ref); this.children.splice(i < 0 ? this.children.length : i, 0, c);
  c.parentNode = this; return c; };
El.prototype.setAttribute = function (k, v) { this.attrs[k] = String(v); };
El.prototype.getAttribute = function (k) { return k in this.attrs ? this.attrs[k] : null; };
El.prototype.removeAttribute = function (k) { delete this.attrs[k]; };
El.prototype.addEventListener = function (t, f) {
  (this.listeners[t] = this.listeners[t] || []).push(f); };
El.prototype.focus = function () { document.activeElement = this; };
El.prototype.getBoundingClientRect = function () {
  return {top: 0, bottom: 100, left: 0, right: 100}; };
El.prototype.querySelector = function () { return null; };
El.prototype.closest = function (sel) {
  var e = this; while (e && e.tagName !== sel.toUpperCase()) { e = e.parentNode; } return e; };
El.prototype.fire = function (type, extra) {
  var e = Object.assign({type: type, target: this, defaultPrevented: false,
    preventDefault: function () { this.defaultPrevented = true; }}, extra || {});
  (this.listeners[type] || []).slice().forEach(function (f) { f(e); });
  return e; };
var ids = {};
var main = new El("main"), section = new El("section");
var document = {
  activeElement: null, documentElement: new El("html"), listeners: {},
  getElementById: function (id) { if (!ids[id]) { ids[id] = new El(); ids[id].id = id; }
    return ids[id]; },
  createElement: function (t) { return new El(t); },
  querySelectorAll: function () { return []; },
  addEventListener: function (t, f) { (this.listeners[t] = this.listeners[t] || []).push(f); }
};
function key(k, extra) {
  var e = Object.assign({key: k, repeat: false, ctrlKey: false, metaKey: false, altKey: false,
    target: document.activeElement || ids["answer-card"], defaultPrevented: false,
    preventDefault: function () { this.defaultPrevented = true; }}, extra || {});
  (document.listeners.keydown || []).forEach(function (f) { f(e); });
  return e;
}
var window = {
  localStorage: {
    getItem: function (k) { if (!storageWorks) { throw new Error("blocked"); }
      return k in stored ? stored[k] : null; },
    setItem: function (k, v) { if (!storageWorks) { throw new Error("blocked"); }
      stored[k] = String(v); }
  },
  matchMedia: function () { return {matches: false, addEventListener: function () {}}; },
  location: {reload: function () { reloads += 1; }, href: ""},
  innerHeight: 800, innerWidth: 1400
};
var counts = {correct: 0, wrong: 0, skipped: 0}, status = {text: "Keep going.", ready: false};
function fetch(url, opts) {
  var body = JSON.parse(opts.body);
  sent.push({url: url, body: body});
  if (body.label === "pass") { counts.correct += 1; }
  if (body.label === "fail") { counts.wrong += 1; }
  if (body.deferred) { counts.skipped += 1; }
  return Promise.resolve({ok: true, json: function () {
    return Promise.resolve({summary: {counts: counts, status: status}}); }});
}
function settle() { return new Promise(function (r) { setImmediate(r); }); }
function later(ms) { NOW += ms; }
// The page's elements, placed as the page has them.
var card = document.getElementById("answer-card"), rail = document.getElementById("rail");
main.appendChild(section); section.appendChild(card); main.appendChild(rail);
card.appendChild(document.getElementById("decide"));
document.getElementById("intro").hidden = true;
document.getElementById("rule").scrollHeight = 10;
document.getElementById("data")._text = JSON.stringify(DATA);
"""


def _script() -> str:
    page = mark_page.label_page("support bot", "Be kind.", "judgekeeper mark",
                                model="gpt-4.1-mini", tool="promptfoo")
    return re.search(r'<script nonce="__NONCE__">\n(.*?)</script>', page, re.DOTALL)[1] \
        .replace("__TOKEN__", "t0k")


def _data(n: int = 6, **extra) -> dict:
    items = [{"id": f"a{i}", "input": f"Question {i}?", "output": f"Answer {i}.", "label": None,
              "skipped": False} for i in range(n)]
    return {"items": items, "total": n, "start": 0,
            "counts": {"correct": 0, "wrong": 0, "skipped": 0},
            "status": {"text": "Keep going.", "ready": False}, **extra}


def _run(scenario: str, data: dict | None = None, seen_intro: bool = True,
         before: str = "") -> dict:
    """Run the page's script (after `before`), then `scenario` (async JS that ends by printing
    one JSON line)."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node to run the page's script")
    code = (f"var DATA = {json.dumps(data or _data())};\n{DOM}\n"
            + ('stored["judgekeeper-intro-seen"] = "1";\n' if seen_intro else "") + before
            + _script() + "\n(async function () {\n" + scenario + "\n})();")
    with tempfile.TemporaryDirectory() as folder:  # a file: too long for a command line
        script = Path(folder) / "page.js"
        script.write_text(code, encoding="utf-8")
        out = subprocess.run([node, str(script)], check=True, capture_output=True, text=True,
                             encoding="utf-8", timeout=60)
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_the_arrow_keys_mark_pass_and_fail_and_the_next_answer_comes():
    got = _run("""
      var before = ids["ans-pos"].textContent;
      key("ArrowRight"); await settle();
      var after = ids["ans-pos"].textContent;
      later(400); key("ArrowLeft"); await settle();
      console.log(JSON.stringify({before: before, after: after, now: ids["ans-pos"].textContent,
        sent: sent.map(function (s) { return [s.body.id, s.body.label]; }),
        url: sent[0].url, focus: document.activeElement === ids["answer-card"]}));""")
    assert got["before"] == "Answer 1" and got["after"] == "Answer 2" and got["now"] == "Answer 3"
    assert got["sent"] == [["a0", "pass"], ["a1", "fail"]]
    assert got["url"] == "/label?token=t0k" and got["focus"]


def test_a_second_key_within_400_ms_does_nothing():
    got = _run("""
      key("ArrowRight"); await settle();
      later(399); key("ArrowRight"); await settle();
      var early = sent.length;
      later(1); key("ArrowRight"); await settle();
      console.log(JSON.stringify({early: early, late: sent.length}));""")
    assert got == {"early": 1, "late": 2}


def test_a_held_key_or_one_with_cmd_ctrl_or_alt_does_nothing():
    got = _run("""
      key("ArrowRight", {repeat: true}); later(500);
      key("ArrowRight", {metaKey: true}); later(500);
      key("ArrowLeft", {ctrlKey: true}); later(500);
      key("s", {altKey: true}); await settle();
      console.log(JSON.stringify({sent: sent.length}));""")
    assert got == {"sent": 0}


def test_skip_and_undo_by_key_and_skipped_answers_come_back_at_the_end():
    got = _run("""
      key("s"); await settle(); later(500);
      var skipped = sent[0].body;
      key("z"); await settle(); later(500);
      var undone = sent[1].body;
      var back = ids["ans-pos"].textContent;
      key("s"); await settle(); later(500);
      for (var i = 0; i < 2; i++) { key("ArrowRight"); await settle(); later(500); }
      var end = ids["end"].hidden, title = ids["end-title"].textContent;
      ids["again"].fire("click"); await settle();
      console.log(JSON.stringify({skipped: skipped, undone: undone, back: back, end: end,
        title: title, again: ids["ans-pos"].textContent}));""", data=_data(3))
    assert got["skipped"] == {"deferred": True, "id": "a0", "seconds": 0}
    assert got["undone"] == {"label": None, "deferred": False, "id": "a0", "seconds": 0}
    assert got["back"] == "Answer 1"
    assert got["end"] is False and got["title"] == "1 skipped answer. Look again, or leave it out."
    assert got["again"] == "Answer 1"


def test_going_back_to_a_marked_answer_says_its_mark():
    data = _data(3)
    data["items"][0]["label"] = "fail"
    data["start"] = 1
    got = _run("""
      var link = new El("a"); link.setAttribute("data-k", "0");
      ids["queue"].fire("click", {target: link}); await settle();
      console.log(JSON.stringify({status: ids["ans-status"].textContent,
        pressed: ids["fail"].getAttribute("aria-pressed")}));""", data=data)
    assert got == {"status": "Your mark: Fail. Press the other button to change it.",
                   "pressed": "true"}


def test_the_bar_follows_answers_looked_at_and_no_number_is_a_target():
    got = _run("""
      var start = [ids["progress"].getAttribute("aria-valuenow"),
                   ids["progress"].getAttribute("aria-valuetext")];
      key("ArrowRight"); await settle(); later(500);
      key("s"); await settle(); later(500);
      var two = [ids["progress"].getAttribute("aria-valuenow"),
                 ids["progress"].getAttribute("aria-valuetext"), ids["see"].hidden,
                 ids["progress-label"].textContent];
      status.ready = true;
      key("ArrowLeft"); await settle();
      console.log(JSON.stringify({start: start, two: two,
        ready: [ids["bar"].style.width, ids["see"].hidden, ids["progress-label"].textContent],
        texts: [ids["ans-pos"].textContent, ids["ans-status"].textContent]}));""")
    assert got["start"] == ["0", "0 answers looked at"]
    share = round(2 / mark_page.FIRST * 100)
    assert got["two"] == [str(share), "2 answers looked at", True, "Toward your first result"]
    assert got["ready"] == ["100%", False, "Ready for your first result"]
    assert not any(re.search(r"\bof \d", t) for t in got["texts"])  # "Answer 4", no total


def test_the_welcome_box_opens_once_and_keys_wait_until_it_is_closed():
    got = _run("""
      var open = !ids["intro"].hidden, focused = document.activeElement === ids["intro-box"];
      key("ArrowRight"); await settle();
      var whileOpen = sent.length;
      ids["intro-box"].fire("keydown", {key: "Enter"});
      later(500); key("ArrowRight"); await settle();
      console.log(JSON.stringify({open: open, focused: focused, whileOpen: whileOpen,
        closed: ids["intro"].hidden, seen: stored["judgekeeper-intro-seen"],
        after: sent.length, button: document.activeElement === ids["intro-ok"]}));""",
               seen_intro=False)
    assert got == {"open": True, "focused": True, "whileOpen": 0, "closed": True, "seen": "1",
                   "after": 1, "button": False}  # the box, not its button: no ring on open


def test_the_welcome_box_keeps_tab_on_its_button_and_esc_starts_too():
    got = _run("""
      var tab = ids["intro-box"].fire("keydown", {key: "Tab"});
      var onButton = document.activeElement === ids["intro-ok"];
      ids["intro-box"].fire("keydown", {key: "Escape"});
      console.log(JSON.stringify({kept: tab.defaultPrevented, onButton: onButton,
        closed: ids["intro"].hidden}));""", seen_intro=False)
    assert got == {"kept": True, "onButton": True, "closed": True}


def test_a_blocked_storage_still_shows_the_page_and_the_box():
    got = _run("""
      console.log(JSON.stringify({open: !ids["intro"].hidden,
        shown: ids["ans-pos"].textContent}));""", seen_intro=False,
               before="storageWorks = false;\n")
    assert got == {"open": True, "shown": "Answer 1"}


def test_a_failed_save_says_so_and_keeps_the_answer():
    got = _run("""
      fetch = function () { return Promise.resolve({ok: false, json: function () {
        return Promise.resolve({error: "no space left"}); }}); };
      key("ArrowRight"); await settle(); await settle();
      console.log(JSON.stringify({status: ids["status"].textContent,
        at: ids["ans-pos"].textContent}));""")
    assert got == {"status": "Not saved: no space left", "at": "Answer 1"}
