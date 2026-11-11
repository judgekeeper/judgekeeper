"""The marking page's script, run in node against a small stand-in for the browser: marking by
keyboard alone, quick keys and the lock on clicks, held keys and Cmd/Ctrl/Alt keys, skipping and undo,
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

NO_ANSWER = ("Not saved: judgekeeper's marking page isn't answering. To open it again, run "
             "the command at the bottom of this page. Your marks are kept.")  # gone, or no answer

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
  createTextNode: function (t) { var e = new El("#text"); e._text = String(t); return e; },
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
var popped = !!(DATA.status && DATA.status.ready);  // as the server keeps it on disk
function fetch(url, opts) {
  var body = JSON.parse(opts.body);
  sent.push({url: url, body: body});
  if (body.label === "pass") { counts.correct += 1; }
  if (body.label === "fail") { counts.wrong += 1; }
  if (body.deferred) { counts.skipped += 1; }
  return Promise.resolve({ok: true, json: function () {
    var popup = status.ready && !popped;
    popped = popped || popup;
    return Promise.resolve({summary: {counts: Object.assign({}, counts),
      status: Object.assign({}, status), popup: popup}}); }});
}
function settle() { return new Promise(function (r) { setImmediate(r); }); }
function later(ms) { NOW += ms; }
// The result-ready box opens after a pause with no mark (READY_WAIT_MS, real time)
function pause() { return new Promise(function (r) { setTimeout(r, 1300); }); }
// The page's elements, placed as the page has them.
var card = document.getElementById("answer-card");
main.appendChild(section); section.appendChild(card);
card.appendChild(document.getElementById("decide"));
document.getElementById("intro").hidden = true;
document.getElementById("ready").hidden = true;
document.getElementById("keep").hidden = true;
function tags(e) {  // every tag under e, text as "#TEXT"
  return Array.prototype.concat.apply([e.tagName], e.children.map(tags)); }
document.getElementById("data")._text = JSON.stringify(DATA);
"""


def _script() -> str:
    page = mark_page.label_page("support bot", "judgekeeper mark",
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
    one JSON line). `seen_intro` False: the project has no marks yet, so the server asks for
    the welcome box (state()'s `intro`)."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node to run the page's script")
    data = {**(data or _data()), **({} if seen_intro else {"intro": True})}
    code = (f"var DATA = {json.dumps(data)};\n{DOM}\n" + before
            + _script() + "\n(async function () {\n" + scenario + "\n})();")
    with tempfile.TemporaryDirectory() as folder:  # a file: too long for a command line
        script = Path(folder) / "page.js"
        script.write_text(code, encoding="utf-8")
        out = subprocess.run([node, str(script)], check=True, capture_output=True, text=True,
                             encoding="utf-8", timeout=60)
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_the_arrow_keys_mark_pass_and_fail_and_the_next_answer_comes():
    got = _run("""
      var before = ids["q-text"].textContent;
      key("ArrowRight"); await settle();
      var after = ids["q-text"].textContent;
      later(400); key("ArrowLeft"); await settle();
      console.log(JSON.stringify({before: before, after: after, now: ids["q-text"].textContent,
        sent: sent.map(function (s) { return [s.body.id, s.body.label]; }),
        url: sent[0].url, focus: document.activeElement === ids["answer-card"]}));""")
    assert got["before"] == "Question 0?" and got["after"] == "Question 1?" and got["now"] == "Question 2?"
    assert got["sent"] == [["a0", "pass"], ["a1", "fail"]]
    assert got["url"] == "/label?token=t0k" and got["focus"]


def test_a_second_key_soon_after_a_saved_mark_marks_the_next_answer():
    got = _run("""
      key("ArrowRight"); await settle();
      later(300); key("ArrowLeft"); await settle();
      console.log(JSON.stringify({sent: sent.map(function (s) { return [s.body.id, s.body.label]; }),
        at: ids["q-text"].textContent}));""")
    assert got == {"sent": [["a0", "pass"], ["a1", "fail"]], "at": "Question 2?"}


def test_two_presses_1_ms_apart_mark_one_answer():
    """The second press comes before anyone could read the next answer: it does nothing, so
    an answer is never marked unseen. A press 250 ms after it shows marks it."""
    got = _run("""
      key("ArrowRight"); await settle();
      later(1); key("ArrowLeft"); await settle();
      later(1); key("s"); await settle();
      var first = [sent.length, ids["q-text"].textContent];
      later(250); key("ArrowLeft"); await settle();
      console.log(JSON.stringify({first: first, at: ids["q-text"].textContent,
        sent: sent.map(function (s) { return [s.body.id, s.body.label]; })}));""")
    assert got["first"] == [1, "Question 1?"]
    assert got["sent"] == [["a0", "pass"], ["a1", "fail"]] and got["at"] == "Question 2?"


def test_keys_pressed_while_a_mark_is_saved_never_mark_the_next_answer():
    got = _run("""
      var answer = [], real = fetch;
      fetch = function (url, opts) { var r = real(url, opts);
        return new Promise(function (ok) { answer.push(function () { ok(r); }); }); };
      key("ArrowRight"); key("ArrowLeft"); key("s"); await settle();
      var waiting = [sent.length, ids["q-text"].textContent];
      while (answer.length) { answer.shift()(); for (var n = 0; n < 4; n++) { await settle(); } }
      console.log(JSON.stringify({waiting: waiting, at: ids["q-text"].textContent,
        sent: sent.map(function (s) { return [s.body.id, s.body.label || "skip"]; })}));""")
    assert got["waiting"] == [1, "Question 0?"]  # one save at a time
    assert got["sent"] == [["a0", "pass"]]  # the next answer was not on screen yet
    assert got["at"] == "Question 1?"


def test_an_answer_behind_the_ready_box_counts_its_seconds_from_when_the_box_closed():
    """The seconds a mark sends are the time its answer was on screen: not the time the
    "Your result is ready" box covered it."""
    got = _run("""
      status = {text: "Ready.", ready: true, headline: "Good enough"};
      key("ArrowRight"); await settle(); await pause();
      var box = !ids["ready"].hidden;
      later(14000); ids["ready-box"].fire("keydown", {key: "Escape"}); await settle();
      later(2000); key("ArrowLeft"); await settle();
      console.log(JSON.stringify({box: box, seconds: sent[1].body.seconds}));""")
    assert got == {"box": True, "seconds": 2}


def test_a_double_click_marks_one_answer():
    got = _run("""
      ids["pass"].fire("click"); await settle();
      later(100); ids["pass"].fire("click"); await settle();
      console.log(JSON.stringify({sent: sent.length, at: ids["q-text"].textContent}));""")
    assert got == {"sent": 1, "at": "Question 1?"}


def test_twelve_clicks_0_3_s_apart_mark_twelve_answers_each_the_one_on_screen():
    got = _run("""
      var shown = [];
      for (var n = 0; n < 12; n++) {
        shown.push(ids["q-text"].textContent.replace("Question ", "a").replace("?", ""));
        ids[n % 3 ? "pass" : "fail"].fire("click"); await settle(); later(300);
      }
      console.log(JSON.stringify({shown: shown,
        sent: sent.map(function (s) { return s.body.id; })}));""", data=_data(14))
    assert got["sent"] == [f"a{i}" for i in range(12)] == got["shown"]


def test_the_ready_box_waits_for_a_pause_so_it_takes_no_click_meant_for_an_answer():
    """The result turns ready at the 2nd mark; clicks go on 0.3 s apart and all count. The
    box opens once marking stops for a moment, over the answer then on screen."""
    got = _run("""
      ids["pass"].fire("click"); await settle(); later(300);
      status.first = true; status.ready = true;
      var hidden = [];
      for (var n = 0; n < 6; n++) {
        ids["fail"].fire("click"); await settle(); later(300);
        hidden.push(ids["ready"].hidden);
        await new Promise(function (r) { setTimeout(r, 300); });
      }
      await pause();
      console.log(JSON.stringify({hidden: hidden, sent: sent.length,
        box: !ids["ready"].hidden, at: ids["q-text"].textContent}));""", data=_data(12))
    assert got["hidden"] == [True] * 6 and got["sent"] == 7
    assert got["box"] is True and got["at"] == "Question 7?"


def test_an_undo_during_the_wait_keeps_the_ready_box_shut_until_the_result_is_ready_again():
    """The result turns ready, then an undo in the wait takes it back below ready: the box
    stays shut, and opens once a later mark makes the result ready again."""
    got = _run("""
      ids["pass"].fire("click"); await settle(); later(300);
      status.first = true; status.ready = true;
      ids["fail"].fire("click"); await settle(); later(300);
      status.ready = false;  // the undo takes the result back below ready
      ids["undo"].fire("click"); await settle(); later(300);
      await pause();
      var shut = ids["ready"].hidden;
      status.ready = true;
      ids["fail"].fire("click"); await settle(); later(300);
      await pause();
      console.log(JSON.stringify({shut: shut, box: !ids["ready"].hidden}));""", data=_data(12))
    assert got == {"shut": True, "box": True}


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
      var back = ids["q-text"].textContent;
      key("s"); await settle(); later(500);
      for (var i = 0; i < 2; i++) { key("ArrowRight"); await settle(); later(500); }
      var end = [ids["end"].hidden, ids["answer-card"].hidden, ids["again"].hidden,
                 ids["end-note"].hidden, ids["again"].textContent, ids["count"].textContent,
                 window.location.href];
      var title = ids["end-title"].textContent;
      ids["again"].fire("click"); await settle();
      console.log(JSON.stringify({skipped: skipped, undone: undone, back: back, end: end,
        title: title, again: ids["q-text"].textContent}));""", data=_data(3))
    assert got["skipped"] == {"deferred": True, "id": "a0", "seconds": 0}
    assert got["undone"] == {"label": None, "deferred": False, "id": "a0", "seconds": 0}
    assert got["back"] == "Question 0?"
    # The end card in the answer card's place: the title, one button, no note, no result yet
    assert got["end"] == [False, True, False, True, "Mark it", "2 marked", ""]
    assert got["title"] == ("The only answer left is the one you skipped. Mark it now, or run "
                            "your eval on more questions.")
    assert got["again"] == "Question 0?"


def test_the_end_card_with_more_than_one_skipped_answer_left():
    got = _run("""
      key("s"); await settle(); later(500);
      key("s"); await settle(); later(500);
      key("ArrowRight"); await settle(); later(500);
      console.log(JSON.stringify({title: ids["end-title"].textContent,
        again: ids["again"].textContent}));""", data=_data(3))
    assert got == {"title": ("The only answers left are the 2 you skipped. Mark them now, or run "
                             "your eval on more questions."), "again": "Mark them"}


@pytest.mark.parametrize(("n", "title", "button"), [
    (1, "You skipped one answer. Go back to it, or leave it out.", "Go back to it"),
    (2, "You skipped 2 answers. Go back to them, or leave them out.", "Go back to them"),
])
def test_with_a_result_the_end_card_never_says_to_run_the_eval_for_skipped_answers(n, title,
                                                                                    button):
    """With a coloured result already, only skipped answers left: look again or leave them
    out. "Run your eval on more questions" is for a result that is too early to tell."""
    got = _run(f"""
      popped = true; status = {{text: "Ready.", ready: true, headline: "Good enough"}};
      for (var i = 0; i < {n}; i++) {{ key("s"); await settle(); later(500); }}
      for (var i = {n}; i < 3; i++) {{ key("ArrowRight"); await settle(); later(500); }}
      console.log(JSON.stringify({{title: ids["end-title"].textContent,
        again: ids["again"].hidden, button: ids["again"].textContent}}));""", data=_data(3))
    assert got == {"title": title, "again": False, "button": button}


def test_end_card_focus_and_enter():
    got = _run("""
      key("s"); await settle(); later(500);
      key("ArrowRight"); await settle(); later(500);
      var focus = [document.activeElement === ids["end"],
                   document.activeElement === ids["again"]];
      ids["end"].fire("keydown", {key: "Enter"}); await settle();
      console.log(JSON.stringify({focus: focus, at: ids["q-text"].textContent,
        card: ids["answer-card"].hidden}));""", data=_data(2))
    assert got == {"focus": [True, False], "at": "Question 0?", "card": False}  # no ring on open


def test_with_every_answer_marked_the_end_card_says_so_and_the_result_opens():
    got = _run("""
      for (var i = 0; i < 3; i++) { key("ArrowRight"); await settle(); later(500); }
      console.log(JSON.stringify({end: ids["end"].hidden, card: ids["answer-card"].hidden,
        title: ids["end-title"].textContent, note: ids["end-note"].hidden,
        again: ids["again"].hidden, href: window.location.href}));""", data=_data(3))
    assert got == {"end": False, "card": True, "title": "You marked every answer.",
                   "note": False, "again": True, "href": "/result?token=t0k"}


def test_opened_with_every_answer_marked_a_mark_can_be_changed_from_the_list():
    """`mark` with every answer marked: the page opens on a card that says how to change a
    mark, not on the result; a mark changed from the list keeps that card (the bar links to
    the result), and Z puts back the mark it had."""
    data = _data(3)
    for item in data["items"]:
        item["label"] = "pass"
    data["counts"] = {"correct": 3, "wrong": 0, "skipped": 0}
    got = _run("""
      var opened = {end: ids["end"].hidden, title: ids["end-title"].textContent,
        note: ids["end-note"].textContent, shown: !ids["end-note"].hidden,
        href: window.location.href};
      var link = new El("a"); link.setAttribute("data-k", "2");
      ids["queue"].fire("click", {target: link}); await settle();
      var picked = ids["ans-status"].textContent;
      counts.correct = 2;  // the server's counts: the 3 marks, one of them now changed
      key("ArrowLeft"); await settle(); later(500);
      var changed = {end: ids["end"].hidden, title: ids["end-title"].textContent,
        note: ids["end-note"].textContent, href: window.location.href};
      key("z"); await settle(); later(500);
      var undone = {card: ids["answer-card"].hidden, status: ids["ans-status"].textContent};
      console.log(JSON.stringify({opened: opened, picked: picked, changed: changed,
        undone: undone, sent: sent.map(function (s) { return [s.body.id, s.body.label]; }),
        end: ids["end"].hidden, href: window.location.href}));""", data=data)
    marked_all = {"end": False, "title": "You have marked all 3 answers.",
                  "note": "To change a mark, click it in the list."}
    assert got == {"opened": {**marked_all, "shown": True, "href": ""},
                   "picked": "Marked Pass", "changed": {**marked_all, "href": ""},
                   "undone": {"card": False, "status": "Marked Pass"},
                   "sent": [["a2", "fail"], ["a2", "pass"]],
                   "end": True, "href": ""}


def test_end_card_with_no_result_says_what_comes_next():
    """The server says every answer is marked and a kind is still short (status.done): the end
    card says it in the terminal's words, and no result opens."""
    lines = ["You've marked every answer: 3 Pass, 0 Fail. A result needs at least 15 of each.",
             "Next: run your eval on more questions, then run `judgekeeper --new`."]
    got = _run("""
      status = {text: "x", ready: false, done: DONE};
      for (var i = 0; i < 3; i++) { key("ArrowRight"); await settle(); later(500); }
      console.log(JSON.stringify({end: ids["end"].hidden, title: ids["end-title"].textContent,
        note: ids["end-note"].textContent, shown: !ids["end-note"].hidden,
        again: ids["again"].hidden, href: window.location.href}));""",
        data=_data(3), before=f"var DONE = {json.dumps(lines)};\n")
    assert got == {"end": False, "title": lines[0], "note": lines[1].replace("`", ""),
                   "shown": True,
                   "again": True, "href": ""}


def test_the_end_cards_command_shows_as_code_without_its_backticks():
    lines = ["You've marked every answer: 3 Pass, 0 Fail. A result needs at least 15 of each.",
             ("Next: run your eval on more questions, then run `judgekeeper --new` to mark "
              "the new results. `--new` moves your marks to .judgekeeper/previous-<date>/.")]
    got = _run("""
      status = {text: "x", ready: false, done: DONE};
      for (var i = 0; i < 3; i++) { key("ArrowRight"); await settle(); later(500); }
      console.log(JSON.stringify(ids["end-note"].children.map(function (c) {
        return [c.tagName, c.textContent]; })));""",
        data=_data(3), before=f"var DONE = {json.dumps(lines)};\n")
    assert got == [["#TEXT", "Next: run your eval on more questions, then run "],
                   ["CODE", "judgekeeper --new"],
                   ["#TEXT", " to mark the new results. "],
                   ["CODE", "--new"],
                   ["#TEXT", " moves your marks to .judgekeeper/previous-<date>/."]]


def test_going_back_to_a_marked_answer_says_its_mark():
    data = _data(3)
    data["items"][0]["label"] = "fail"
    data["start"] = 1
    got = _run("""
      var link = new El("a"); link.setAttribute("data-k", "0");
      ids["queue"].fire("click", {target: link}); await settle();
      console.log(JSON.stringify({status: ids["ans-status"].textContent,
        pressed: ids["fail"].getAttribute("aria-pressed")}));""", data=data)
    assert got == {"status": "Marked Fail", "pressed": "true"}


def test_after_a_mark_only_the_mark_word_is_coloured():
    data = _data(4)
    data["items"][0]["label"], data["items"][1]["label"] = "pass", "fail"
    data["items"][2]["skipped"] = True
    data["start"] = 3
    got = _run("""
      function state() { var st = ids["ans-status"];
        return [st.textContent, st.children.map(function (c) { return [c.className,
          c.textContent]; })]; }
      var open = state(), link = new El("a");
      function go(k) { link.setAttribute("data-k", String(k));
        ids["queue"].fire("click", {target: link}); }
      go(2); var skipped = state();
      go(0); var passed = state();
      go(1);
      console.log(JSON.stringify({open: open, skipped: skipped, passed: passed,
        failed: state()}));""", data=data)
    assert got["open"] == ["", []]  # not marked yet: nothing said
    assert got["skipped"] == ["Skipped", []]
    assert got["passed"] == ["Marked Pass", [["", "Marked "], ["said pass", "Pass"]]]
    assert got["failed"] == ["Marked Fail", [["", "Marked "], ["said fail", "Fail"]]]


def test_the_bar_follows_the_marks_toward_a_result_and_the_count_the_marks():
    got = _run("""
      var start = [ids["progress"].getAttribute("aria-valuenow"),
                   ids["progress"].getAttribute("aria-valuetext"), ids["count"].textContent];
      key("ArrowRight"); await settle(); later(500);
      key("s"); await settle(); later(500);
      var two = [ids["progress"].getAttribute("aria-valuenow"),
                 ids["progress"].getAttribute("aria-valuetext"), ids["see"].hidden,
                 ids["count"].textContent];
      status.first = true;
      key("ArrowLeft"); await settle(); later(500);
      var first = [ids["progress"].getAttribute("aria-valuenow"), ids["see"].hidden,
                   ids["see"].textContent];
      status.ready = true;
      key("ArrowLeft"); await settle();
      console.log(JSON.stringify({start: start, two: two, first: first,
        ready: [ids["progress"].getAttribute("aria-valuenow"), ids["see"].hidden,
                ids["count"].textContent, ids["see"].textContent],
        texts: [ids["q-text"].textContent, ids["ans-status"].textContent]}));""")
    assert got["start"] == ["0", "0 answers looked at", "0 marked"]
    share = round(1 / (2 * mark_page.ROUGH) * 100)  # one Pass; the skip counts for nothing
    assert got["two"] == [str(share), "2 answers looked at", True, "1 marked"]
    assert got["first"] == ["100", False, "See the numbers so far"]  # too early: no "ready"
    assert got["ready"] == ["100", False, "3 marked", "See your result"]
    assert got["texts"] == ["Question 4?", ""]  # not marked yet: no words


def test_the_undo_button_undoes_like_the_key():
    got = _run("""
      key("ArrowRight"); await settle(); later(500);
      ids["undo"].fire("click"); await settle();
      console.log(JSON.stringify({sent: sent.map(function (s) { return s.body.label; }),
        at: ids["q-text"].textContent}));""")
    assert got == {"sent": ["pass", None], "at": "Question 0?"}


def test_the_welcome_box_opens_once_and_keys_wait_until_it_is_closed():
    got = _run("""
      var open = !ids["intro"].hidden, focused = document.activeElement === ids["intro-box"];
      inert = ids["app"].getAttribute("inert");
      key("ArrowRight"); await settle();
      var whileOpen = sent.length;
      ids["intro-box"].fire("keydown", {key: "Enter"});
      later(500); key("ArrowRight"); await settle();
      console.log(JSON.stringify({open: open, focused: focused, whileOpen: whileOpen,
        closed: ids["intro"].hidden, stored: Object.keys(stored).length,
        after: sent.length, button: document.activeElement === ids["intro-ok"],
        inert: [inert, ids["app"].getAttribute("inert")]}));""",
               seen_intro=False, before="var inert = null;\n")
    assert got == {"open": True, "focused": True, "whileOpen": 0, "closed": True, "stored": 0,
                   "after": 1, "button": False,  # the box, not its button: no ring on open
                   "inert": ["", None]}  # the page behind: inert while the box is open


def test_the_first_answer_takes_no_key_in_the_first_250_ms_after_the_box_closes():
    got = _run("""
      ids["intro-box"].fire("keydown", {key: "Enter"});
      key("ArrowRight"); await settle();
      var at_once = sent.length;
      later(100); key("ArrowRight"); await settle();
      var soon = sent.length;
      later(250); key("ArrowRight"); await settle();
      console.log(JSON.stringify({at_once: at_once, soon: soon,
        sent: sent.map(function (s) { return [s.body.id, s.body.label]; })}));""",
               seen_intro=False)
    assert got == {"at_once": 0, "soon": 0, "sent": [["a0", "pass"]]}


def test_the_welcome_box_keeps_tab_on_its_button_and_esc_starts_too():
    got = _run("""
      var tab = ids["intro-box"].fire("keydown", {key: "Tab"});
      var onButton = document.activeElement === ids["intro-ok"];
      ids["intro-box"].fire("keydown", {key: "Escape"});
      console.log(JSON.stringify({kept: tab.defaultPrevented, onButton: onButton,
        closed: ids["intro"].hidden}));""", seen_intro=False)
    assert got == {"kept": True, "onButton": True, "closed": True}


def test_no_welcome_box_when_every_answer_is_marked():
    """A page the server asks the box on, with every answer marked: no "Start marking" box
    over "You have marked all N answers"; it still shows once answers are left."""
    data = _data(3)
    for item in data["items"]:
        item["label"] = "pass"
    data["counts"] = {"correct": 3, "wrong": 0, "skipped": 0}
    got = _run("""
      console.log(JSON.stringify({box: !ids["intro"].hidden, end: !ids["end"].hidden,
        title: ids["end-title"].textContent, inert: document.getElementById("app").getAttribute("inert") !== null,
        stored: Object.keys(stored).length}));""", data=data, seen_intro=False)
    assert got == {"box": False, "end": True, "title": "You have marked all 3 answers.",
                   "inert": False, "stored": 0}
    got = _run('console.log(JSON.stringify({box: !ids["intro"].hidden}));', seen_intro=False)
    assert got == {"box": True}


def test_a_blocked_storage_still_shows_the_page_and_the_box():
    got = _run("""
      console.log(JSON.stringify({open: !ids["intro"].hidden,
        shown: ids["q-text"].textContent}));""", seen_intro=False,
               before="storageWorks = false;\n")
    assert got == {"open": True, "shown": "Question 0?"}


def test_a_failed_save_says_so_and_keeps_the_answer():
    got = _run("""
      fetch = function () { return Promise.resolve({ok: false, json: function () {
        return Promise.resolve({error: "no space left"}); }}); };
      key("ArrowRight"); await settle(); await settle();
      console.log(JSON.stringify({status: ids["status"].textContent,
        at: ids["q-text"].textContent}));""")
    assert got == {"status": "Not saved: no space left", "at": "Question 0?"}


def test_a_save_with_no_answer_in_10_seconds_says_so_and_can_be_tried_again():
    got = _run("""
      var hung = fetch;
      fetch = function (url, opts) { return new Promise(function (ok, no) {
        opts.signal.addEventListener("abort", function () { no(new Error("aborted")); }); }); };
      key("ArrowRight"); await settle();
      var waiting = document.getElementById("status").textContent;
      timers.forEach(function (t) { t.f(); }); await settle(); await settle();
      var said = ids["status"].textContent, at = ids["q-text"].textContent;
      fetch = hung; later(500); key("ArrowRight"); await settle(); await settle();
      console.log(JSON.stringify({waiting: waiting, said: said, at: at,
        ms: timers.map(function (t) { return t.ms; }), then: sent.length}));""",
               before="""
      var timers = [], soon = setTimeout;
      setTimeout = function (f, ms) {
        if (ms >= 5000) { timers.push({f: f, ms: ms}); return 0; } return soon(f, ms); };
      """)
    assert got["waiting"] == ""
    assert got["said"] == NO_ANSWER
    assert got["at"] == "Question 0?" and got["then"] == 1  # tried again: saved
    assert got["ms"] == [10000, 10000]  # one wait per save


def _phone(width: int, still: bool = False) -> str:
    """A window `width` px wide (reduced motion when `still`); the scrolls of the bar above the
    card are kept."""
    return f"""
      window.innerWidth = {width};
      window.matchMedia = function (q) {{
        var m = /max-width: (\\d+)px/.exec(q);
        return {{matches: m ? window.innerWidth <= +m[1]
                         : q.indexOf("reduce") > -1 && {json.dumps(still)},
                addEventListener: function () {{}}}};
      }};
      var scrolled = [];
      El.prototype.scrollIntoView = function (o) {{
        if (this === ids["progress-box"]) {{ scrolled.push(o); }} }};
    """


_PICK = """
      scrolled.length = 0;
      var link = new El("a"); link.setAttribute("data-k", "4");
      ids["queue"].fire("click", {target: link}); await settle();
      console.log(JSON.stringify({at: ids["q-text"].textContent, scrolled: scrolled}));"""


def test_on_a_phone_an_answer_picked_from_the_list_scrolls_into_view():
    """At 390px the list sits below the card: the card picked comes into view, smoothly, with
    the bar, its link and its line above it."""
    got = _run(_PICK, before=_phone(390))
    assert got == {"at": "Question 4?", "scrolled": [{"behavior": "smooth", "block": "start"}]}


def test_on_a_phone_with_reduced_motion_the_card_comes_at_once():
    got = _run(_PICK, before=_phone(390, still=True))
    assert got["scrolled"] == [{"behavior": "auto", "block": "start"}]


def test_on_a_wide_screen_the_card_does_not_scroll():
    """Next to the list, the card is already in view: focus moves without a scroll."""
    got = _run(_PICK, before=_phone(1400))
    assert got == {"at": "Question 4?", "scrolled": []}


# The input shows once -------------------------------------------------------------------------

SHOWN = """
  function parts(e) { return e.children.filter(function (c) { return c.tagName !== "#TEXT"; })
    .map(function (c) { return [c.className, c.textContent]; }); }
  var side = ids["queue"].children[0].children[0].children.filter(function (c) {
    return c.className === "q"; })[0];
  console.log(JSON.stringify({heading: ids["q-label"].textContent, hidden: ids["q-row"].hidden,
    labelHidden: ids["q-label"].hidden,
    text: ids["q-text"].textContent, parts: parts(ids["q-text"]),
    answer: ids["a-text"].textContent, side: side.textContent}));"""


def _input(value, output: str) -> dict:
    data = _data(1)
    data["items"][0].update(input=value, output=output)
    return data


def test_a_part_that_is_the_answer_is_left_out_and_one_part_shows_as_plain_text():
    got = _run(SHOWN, data=_input([["question", "Q"], ["answer", " A "]], "A"))
    assert got["heading"] == "Question" and got["hidden"] is False
    assert got["text"] == "Q" and got["parts"] == [] and got["answer"] == "A"
    assert got["side"] == "Q"


def test_two_parts_left_show_with_their_names_and_no_label_above_them():
    got = _run(SHOWN, data=_input([["question", "Q"], ["context", "C"]], "X"))
    assert got["labelHidden"] is True and got["hidden"] is False  # no stacked labels
    assert got["parts"] == [["field-name", "question"], ["field", "Q"],
                            ["field-name", "context"], ["field", "C"]]
    assert got["side"] == "Q"


def test_an_input_that_is_only_the_answer_hides_the_question_row():
    got = _run(SHOWN, data=_input([["answer", "A"]], "A"))
    assert got["hidden"] is True and got["text"] == "" and got["answer"] == "A"
    assert got["side"] == ""


def test_a_plain_text_input_is_unchanged():
    got = _run(SHOWN, data=_input("Is it A?\nSecond line", "A"))
    assert got["heading"] == "Question" and got["hidden"] is False
    assert got["text"] == "Is it A?\nSecond line" and got["side"] == "Is it A?"


def test_the_next_answer_sets_the_heading_and_row_again():
    data = _data(2)
    data["items"][0].update(input=[["answer", "A"]], output="A")
    data["items"][1].update(input=[["question", "Q"], ["context", "C"]], output="X")
    got = _run("""
      key("ArrowRight"); await settle();
      console.log(JSON.stringify({label: ids["q-label"].hidden,
        hidden: ids["q-row"].hidden}));""", data=data)
    assert got == {"label": True, "hidden": False}


def test_a_repeat_graded_differently_says_its_run_and_nothing_else():
    """An answer the LLM-as-a-judge graded more than once, with different grades: its card
    says which run it is in one short line, never the grade; other cards say nothing."""
    data = _data(2)
    data["items"][0]["run"] = [2, 3]
    got = _run("""
      var first = [ids["a-run"].textContent, ids["a-run"].hidden];
      key("ArrowRight"); await settle();
      console.log(JSON.stringify({first: first,
        second: [ids["a-run"].textContent, ids["a-run"].hidden]}));""", data=data)
    assert got == {"first": ["Run 2 of 3: graded differently", False], "second": ["", True]}


def test_the_run_line_is_on_the_page_hidden_until_an_answer_has_one():
    page = mark_page.label_page("support bot", "judgekeeper mark")
    assert '<p class="run" id="a-run" hidden></p>' in page


def _bar(counts: dict, ready: bool = False, first: bool | None = None) -> list:
    """[the bar's value, whether the line under it is hidden, that line]: `first`, the first
    numbers are in (with `ready`, a coloured verdict, too)."""
    first = ready if first is None else first
    return _run("""
      console.log(JSON.stringify([ids["progress"].getAttribute("aria-valuenow"),
                                  ids["keep"].hidden, ids["keep"].textContent]));""",
                data=_data(60, counts=counts,  # enough answers for a first result
                           status={"text": "x", "first": first, "ready": ready}))


def test_the_bar_counts_pass_and_fail_each_up_to_the_rough_number_and_never_fills_before_ready():
    rough = mark_page.ROUGH
    assert rough == 15
    assert _bar({"correct": 0, "wrong": 0, "skipped": 0})[0] == "0"
    assert _bar({"correct": 15, "wrong": 0, "skipped": 0})[0] == "50"
    assert _bar({"correct": 40, "wrong": 0, "skipped": 0})[0] == "50"  # more of one kind: no more
    assert _bar({"correct": 20, "wrong": 3, "skipped": 0})[0] == "60"
    assert _bar({"correct": 0, "wrong": 0, "skipped": 40})[0] == "0"  # skipped: nothing
    assert _bar({"correct": 15, "wrong": 15, "skipped": 0})[0] == "90"  # no numbers: not full
    assert _bar({"correct": 15, "wrong": 15, "skipped": 0}, first=True)[0] == "100"
    assert _bar({"correct": 15, "wrong": 15, "skipped": 0}, ready=True)[0] == "100"


def test_the_calm_line_shows_once_enough_are_looked_at_and_no_result_yet():
    first = mark_page.FIRST
    assert _bar({"correct": 5, "wrong": 5, "skipped": 0})[1] is True
    assert _bar({"correct": first, "wrong": 0, "skipped": 0})[1] is False
    assert _bar({"correct": 10, "wrong": 10, "skipped": first - 20})[1] is False  # skips look too
    assert _bar({"correct": first, "wrong": 0, "skipped": 0}, ready=True)[1] is True
    keep = "Keep going: your result appears once there are enough Pass and Fail marks."
    assert _bar({"correct": first, "wrong": 0, "skipped": 0})[2] == keep
    # the first numbers, too early to tell: the line says so, even before FIRST looked at
    shown = _bar({"correct": 15, "wrong": 15, "skipped": 0}, first=True)
    assert shown[1] is False
    assert shown[2] == "Your first numbers are in. Too early to tell: keep marking."
    page = mark_page.label_page(None)
    assert ('<p class="keep" id="keep" hidden>Keep going: your result appears once there are '
            "enough Pass and Fail marks.</p>") in page


def test_a_card_shown_again_still_lets_the_bar_say_only_a_skipped_answer_is_left():
    """An answer shown again adds a card, never an answer: with every other answer marked and
    one skipped, the line under the bar says what the end card says."""
    data = _data(60, counts={"correct": 30, "wrong": 29, "skipped": 1},
                 status={"text": "x", "first": False, "ready": False})
    for i, it in enumerate(data["items"]):
        it.update({"label": "pass" if i % 2 else "fail"} if i else {"skipped": True})
    data["items"].insert(1, {"id": "a5", "input": "Question 5?", "output": "Answer 5.",
                             "label": None, "skipped": False, "again": 0})
    data["total"], data["start"] = 61, 1
    got = _run("""
      console.log(JSON.stringify([ids["keep"].hidden, ids["keep"].textContent]));""",
               data=data)
    assert got == [False, ("The only answer left is the one you skipped. Mark it now, or run "
                           "your eval on more questions.")]


def test_the_ready_box_comes_once_when_the_result_turns_ready_and_esc_keeps_marking():
    got = _run("""
      key("ArrowRight"); await settle();
      var before = [ids["ready"].hidden, document.getElementById("app").getAttribute("inert")];
      status.first = true; status.ready = true; later(500);
      status.headline = "Your LLM-as-a-judge needs work.";  // still sent; the box never shows it
      key("ArrowLeft"); await settle(); await pause();
      var shown = [ids["ready"].hidden, document.getElementById("app").getAttribute("inert"),
                   document.activeElement === ids["ready-box"], ids["ready-see"].getAttribute("href"),
                   sent.length, ids["ready-box"].textContent.indexOf("needs work")];
      key("ArrowRight"); await settle();  // behind the box: nothing is marked
      var behind = sent.length;
      ids["ready-box"].fire("keydown", {key: "Escape"});
      var closed = [ids["ready"].hidden, document.getElementById("app").getAttribute("inert"),
                    document.activeElement === ids["answer-card"]];
      later(500); key("ArrowRight"); await settle();
      console.log(JSON.stringify({before: before, shown: shown, behind: behind, closed: closed,
                                  again: ids["ready"].hidden, sent: sent.length}));""")
    assert got["before"] == [True, None]
    assert got["shown"] == [False, "", True, "/result?token=t0k", 2, -1]
    assert got["behind"] == 2
    assert got["closed"] == [True, None, True]
    assert got["again"] is True and got["sent"] == 3


def test_the_ready_box_buttons_and_tab_stay_inside_it():
    got = _run("""
      status.ready = true;
      key("ArrowRight"); await settle(); await pause();
      var open = !ids["ready"].hidden;
      ids["ready-box"].fire("keydown", {key: "Tab"});
      var first = document.activeElement === ids["ready-see"];
      ids["ready-see"].fire("keydown", {key: "Tab"});  // on the box's key handler only
      ids["ready-box"].fire("keydown", {key: "Tab", shiftKey: true});
      var back = document.activeElement === ids["ready-keep"];
      ids["ready-keep"].fire("click");
      console.log(JSON.stringify({open: open, first: first, back: back,
        closed: ids["ready"].hidden, focus: document.activeElement === ids["answer-card"],
        sent: sent.length}));""")
    assert got == {"open": True, "first": True, "back": True, "closed": True, "focus": True,
                   "sent": 1}


def test_the_ready_box_does_not_come_when_the_page_opens_already_ready():
    got = _run("""
      key("ArrowRight"); await settle();
      console.log(JSON.stringify({hidden: ids["ready"].hidden}));""",
               data=_data(counts={"correct": 15, "wrong": 15, "skipped": 0},
                          status={"text": "x", "ready": True}),
               before="status.ready = true;\n")
    assert got == {"hidden": True}


def test_the_ready_box_has_the_welcome_boxs_look_and_its_words():
    page = mark_page.label_page(None)
    box = page[page.index('<div class="scrim" id="ready"'):page.index('<script type="application')]
    assert 'class="intro" id="ready-box" role="dialog" aria-modal="true"' in box
    assert "judgekeeper" in box and 'class="brand"' in box  # the logo
    assert '<h2 id="ready-title">Your result is ready.</h2>' in box
    assert "ready-note" not in box and 'class="note"' not in box  # no verdict line: the page has it
    assert '<a class="go" id="ready-see" href="#">See your result</a>' in box
    assert 'id="ready-keep">Keep marking</button>' in box


def test_bold_and_bullets_in_an_answer_are_built_without_innerhtml_and_all_else_is_text():
    answer = ("**<img src=x onerror=alert(1)>** and <script>alert(1)</script>\n"
              "- <b>x</b>\n- **two** items\n**unclosed and * a star\nlast line")
    got = _run("""
      var a = ids["a-text"];
      console.log(JSON.stringify({tags: tags(a), text: a.textContent, html: a.innerHTML,
        strong: a.children.filter(function (c) { return c.tagName === "STRONG"; })
          .map(function (c) { return c.textContent; })}));""",
               data=_data(1, items=[{"id": "a0", "input": "Q?", "output": answer, "label": None,
                                      "skipped": False}]))
    assert set(got["tags"]) <= {"DIV", "#TEXT", "STRONG", "UL", "LI"}, got["tags"]
    assert got["html"] == ""
    assert "<script>alert(1)</script>" in got["text"] and "<b>x</b>" in got["text"]
    assert "**unclosed and * a star" in got["text"]  # an unclosed ** stays as stars
    assert got["strong"] == ["<img src=x onerror=alert(1)>"]
    assert got["tags"].count("LI") == 2 and got["tags"].count("UL") == 1


def test_bold_and_bullets_work_in_a_question_and_in_its_named_parts():
    got = _run("""
      var q = ids["q-text"];
      console.log(JSON.stringify({tags: tags(q), text: q.textContent}));""",
               data=_data(1, items=[{"id": "a0", "output": "A.", "label": None, "skipped": False,
                                      "input": [["Topic", "**Pass** if <i>kind</i>"],
                                                ["Rules", "- one\n- two"]]}]))
    assert set(got["tags"]) <= {"DIV", "SPAN", "#TEXT", "STRONG", "UL", "LI"}, got["tags"]
    assert got["tags"].count("STRONG") == 1 and got["tags"].count("LI") == 2
    assert "<i>kind</i>" in got["text"] and "**" not in got["text"]


def test_a_verdict_that_goes_back_to_too_early_changes_the_link_and_never_reopens_the_box():
    got = _run("""
      status.first = true; status.ready = true; status.headline = "x"; later(500);
      key("ArrowRight"); await settle(); await pause();
      var opened = !ids["ready"].hidden;
      ids["ready-box"].fire("keydown", {key: "Escape"});
      status.ready = false; status.headline = null; later(500);
      key("ArrowRight"); await settle();
      var back = [ids["see"].textContent, ids["keep"].hidden, ids["keep"].textContent];
      status.ready = true; status.headline = "x"; later(500);
      key("ArrowRight"); await settle(); await pause();
      console.log(JSON.stringify({opened: opened, back: back, box: ids["ready"].hidden,
                                  link: ids["see"].textContent}));""")
    assert got["opened"] is True
    assert got["back"] == ["See the numbers so far", False,
                           "Your first numbers are in. Too early to tell: keep marking."]
    assert got["box"] is True  # once only
    assert got["link"] == "See your result"


# A page left open while marks are imported -----------------------------------------------------

STALE = """
  var stateAsked = 0;
  function answer(summary) { return Promise.resolve({ok: true, json: function () {
    return Promise.resolve({summary: summary}); }}); }
  fetch = function (url, opts) {
    if (url.indexOf("/state") === 0) {
      stateAsked += 1;
      var items = DATA.items.map(function (it, k) {  // a1 and a2 came in from the import
        return Object.assign({}, it, {label: k === 0 ? "pass" : (k < 3 ? "fail" : null)}); });
      return Promise.resolve({ok: true, json: function () { return Promise.resolve(
        {items: items, total: items.length, start: 3, version: "v3",
         counts: {correct: 1, wrong: 2, skipped: 0}, status: {text: "Keep going.", ready: false}});
      }});
    }
    var body = JSON.parse(opts.body); sent.push({url: url, body: body});
    return answer({counts: {correct: 1, wrong: 2, skipped: 0}, version: "v3",
                   before: BEFORE, status: {text: "Keep going.", ready: false}});
  };
"""


def test_an_answer_opened_from_the_list_has_no_word_from_the_mark_before():
    """"Marked Fail." is said after a mark, for a screen reader. Open another answer from the
    list and it is gone: it was about the answer before, not this one."""
    got = _run("""
      function wait(ms) { return new Promise(function (r) { realTimeout(r, ms); }); }
      key("ArrowLeft"); await settle(); await wait(250);
      var after = ids["done"].textContent;
      var link = new El("a"); link.setAttribute("data-k", "3");
      ids["queue"].fire("click", {target: link}); await settle(); await wait(250);
      console.log(JSON.stringify({after: after, opened: ids["done"].textContent,
        at: ids["q-text"].textContent}));""", before="var realTimeout = setTimeout;\n")
    assert got == {"after": "Marked Fail.", "opened": "", "at": "Question 3?"}


def test_a_page_whose_marks_changed_takes_the_new_list_before_the_next_answer():
    got = _run("var BEFORE = 'v2';" + STALE + """
      key("ArrowRight"); for (var n = 0; n < 6; n++) { await settle(); }
      console.log(JSON.stringify({at: ids["q-text"].textContent, stateAsked: stateAsked,
        reloads: reloads, heard: ids["done"].textContent,
        sent: sent.map(function (s) { return [s.body.id, s.body.label]; })}));""",
               _data(version="v1"))
    assert got["sent"] == [["a0", "pass"]] and got["stateAsked"] == 1
    assert got["at"] == "Question 3?"  # not a1, which the import marked
    assert got["reloads"] == 0


def test_a_page_whose_marks_did_not_change_goes_on_as_before():
    got = _run("var BEFORE = 'v1';" + STALE + """
      key("ArrowRight"); for (var n = 0; n < 6; n++) { await settle(); }
      later(400); key("ArrowLeft"); for (var n = 0; n < 6; n++) { await settle(); }
      console.log(JSON.stringify({at: ids["q-text"].textContent, stateAsked: stateAsked}));""",
               _data(version="v1"))
    # the first mark's version before is the page's; the second's (still "v1") is not the
    # "v3" the first answer gave, so it takes the list again
    assert got == {"at": "Question 3?", "stateAsked": 1}


def test_a_server_that_says_no_version_never_makes_the_page_ask_again():
    got = _run("""
      key("ArrowRight"); await settle();
      console.log(JSON.stringify({at: ids["q-text"].textContent, reloads: reloads}));""")
    assert got == {"at": "Question 1?", "reloads": 0}


def test_z_on_a_first_mark_still_takes_it_back_and_on_a_changed_one_puts_the_old_back():
    got = _run("""
      key("ArrowRight"); await settle(); later(500);  // a0: Pass, a first mark
      key("z"); await settle(); later(500);           // taken back: a0 unmarked
      var first = ids["ans-status"].textContent;
      key("ArrowRight"); await settle(); later(500);  // a0: Pass again, a1 shows
      var link = new El("a"); link.setAttribute("data-k", "0");
      ids["queue"].fire("click", {target: link}); await settle();
      key("ArrowLeft"); await settle(); later(500);   // a0 changed to Fail
      key("z"); await settle(); later(500);           // back to Pass
      console.log(JSON.stringify({first: first, now: ids["ans-status"].textContent,
        sent: sent.map(function (s) { return [s.body.id, s.body.label]; })}));""",
        data=_data(3))
    assert got == {"first": "", "now": "Marked Pass",
                   "sent": [["a0", "pass"], ["a0", None], ["a0", "pass"], ["a0", "fail"],
                            ["a0", "pass"]]}


def test_marks_that_wait_fill_no_bar_and_the_page_says_so_once():
    """Marks on answers the new LLM-as-a-judge never graded count for nothing in the bar; the
    line under it says how many wait and how to count them, with the command as code."""
    line = ("20 of your marks wait: your new LLM-as-a-judge has no Pass or Fail grade on those "
            "answers yet. To count them, grade all your answers with your new LLM-as-a-judge, "
            "then run `judgekeeper check <new results file>`.")
    counts = {"correct": 15, "wrong": 15, "skipped": 0, "toward": {"correct": 15, "wrong": 0}}
    got = _run("""
      var w = ids["waiting"];
      console.log(JSON.stringify([ids["progress"].getAttribute("aria-valuenow"), w.hidden,
        w.textContent, tags(w).filter(function (t) { return t === "CODE"; }).length]));""",
               data=_data(counts=counts, status={"text": "x", "first": False, "ready": False,
                                                 "waiting": line}))
    assert got == ["50", False, line.replace("`", ""), 1]
    got = _run('console.log(JSON.stringify([ids["waiting"].hidden]));',
               data=_data(counts={"correct": 1, "wrong": 1, "skipped": 0},
                          status={"text": "x", "first": False, "ready": False}))
    assert got == [True]


def test_with_only_marks_that_wait_left_the_page_never_says_keep_marking():
    """No answer the new LLM-as-a-judge graded is left to mark (status.only_wait): no mark can
    move the result, so the line under the bar is gone; the wait line is the step."""
    counts = {"correct": 20, "wrong": 20, "skipped": 0, "toward": {"correct": 15, "wrong": 15}}
    keep = 'console.log(JSON.stringify([ids["keep"].hidden, ids["waiting"].hidden]));'
    status = {"text": "x", "first": True, "ready": False, "waiting": "20 of your marks wait."}
    assert _run(keep, data=_data(counts=counts, status=status)) == [False, False]
    assert _run(keep, data=_data(counts=counts, status={**status, "only_wait": True})) == [
        True, False]


def test_a_saved_mark_keeps_the_list_rows_so_a_click_is_never_lost():
    """The answers list is updated in place after each save (each row's link kept, only its
    text, icon and state changed): a click pressed on a row while a mark is saved lands on the
    same row when it is let go, and opens it."""
    got = _run("""
      function rows() { return ids["queue"].children.map(function (li) {
        return li.children[0]; }); }
      function state(a) { return [a.getAttribute("aria-current"),
        a.children[a.children.length - 1].textContent, a.children[2].innerHTML]; }
      var before = rows(), icon = state(before[0])[2];
      key("ArrowRight"); await settle();  // saved: the list is drawn again
      var after = rows();
      var same = before.length === after.length && before.every(function (a, i) {
        return a === after[i]; });
      var states = [state(after[0]), state(after[1])];
      ids["queue"].fire("click", {target: before[3].children[1]}); await settle();
      console.log(JSON.stringify({same: same, n: after.length, states: states,
        iconChanged: states[0][2] !== icon, opened: ids["q-text"].textContent}));""")
    assert got["same"] and got["n"] == 6
    assert got["states"][0][:2] == [None, ", marked Pass"] and got["iconChanged"]
    assert got["states"][1][:2] == ["true", ", not marked"]
    assert got["opened"] == "Question 3?"


@pytest.mark.parametrize("n", [8, 4])
def test_the_list_grows_or_shrinks_with_the_answers_and_keeps_the_rows_it_has(n):
    """A new list from the server (marks written elsewhere, /state) with more or fewer
    answers: rows are added or taken away at the end; the rows kept are the same links."""
    got = _run(f"var NEWN = {n};" + """
      function rows() { return ids["queue"].children.map(function (li) {
        return li.children[0]; }); }
      fetch = function (url, opts) {
        if (url.indexOf("/state") === 0) {
          var items = [];
          for (var k = 0; k < NEWN; k++) { items.push({id: "a" + k, input: "Question " + k + "?",
            output: "Answer " + k + ".", label: k === 0 ? "pass" : null, skipped: false}); }
          return Promise.resolve({ok: true, json: function () { return Promise.resolve(
            {items: items, total: NEWN, start: 1, version: "v3",
             counts: {correct: 1, wrong: 0, skipped: 0},
             status: {text: "Keep going.", ready: false}}); }});
        }
        sent.push({url: url, body: JSON.parse(opts.body)});
        return Promise.resolve({ok: true, json: function () { return Promise.resolve(
          {summary: {counts: {correct: 1, wrong: 0, skipped: 0}, version: "v3", before: "v2",
                     status: {text: "Keep going.", ready: false}}}); }});
      };
      var before = rows();
      key("ArrowRight"); for (var n = 0; n < 6; n++) { await settle(); }
      var after = rows(), kept = Math.min(before.length, after.length);
      console.log(JSON.stringify({n: after.length, same: before.slice(0, kept).every(
        function (a, i) { return a === after[i]; }),
        last: after[after.length - 1].children[1].textContent}));""", _data(version="v1"))
    assert got == {"n": n, "same": True, "last": f"Question {n - 1}?"}


@pytest.mark.parametrize("first", [False, True])
def test_the_line_under_the_bar_says_only_skipped_answers_are_left_as_the_card_does(first):
    """59 of 60 marked and 1 skipped, no coloured result: the line under the bar says what
    the card in the middle says, never to keep going. With an answer left: keep going."""
    data = _data(60, counts={"correct": 45, "wrong": 14, "skipped": 1},
                 status={"text": "x", "first": first, "ready": False})
    for item in data["items"][:59]:
        item["label"] = "pass"
    data["items"][59]["skipped"] = True
    show = 'console.log(JSON.stringify([ids["keep"].hidden, ids["keep"].textContent]));'
    card = ("The only answer left is the one you skipped. Mark it now, or run your eval on more "
            "questions.")
    assert _run(show, data=data) == [False, card]
    data["counts"] = {"correct": 45, "wrong": 13, "skipped": 1}
    data["items"][58]["label"] = None
    said = _run(show, data=data)[1]
    assert said == (mark_page.KEEP_GOING if not first else
                    "Your first numbers are in. Too early to tell: keep marking.")


def test_the_line_under_the_bar_names_the_marks_a_group_still_needs():
    """Enough Pass and Fail marks, too few on the answers the LLM-as-a-judge failed: the line
    under the bar says so, as the terminal does, not only to keep going."""
    group = ("You marked 13 answers your LLM-as-a-judge failed. Your LLM-as-a-judge failed only "
             "14 answers, so a result needs your marks on all 14.")
    data = _data(60, counts={"correct": 20, "wrong": 16, "skipped": 0},
                 status={"text": "x", "first": False, "ready": False, "group": group})
    for item in data["items"][:36]:
        item["label"] = "pass"
    show = 'console.log(JSON.stringify([ids["keep"].hidden, ids["keep"].textContent]));'
    assert _run(show, data=data) == [False, group]


def test_the_line_under_the_bar_says_a_first_result_needs_more_answers():
    """24 answers, a few marked: no result can appear on the page, so the line under the bar
    says what the terminal says, never to keep going for one."""
    from judgekeeper import start

    data = _data(24, counts={"correct": 4, "wrong": 2, "skipped": 0},
                 status={"text": "x", "first": False, "ready": False, "few": True})
    for item in data["items"][:6]:
        item["label"] = "pass"
    show = 'console.log(JSON.stringify([ids["keep"].hidden, ids["keep"].textContent]));'
    assert _run(show, data=data) == [False, (
        f"A first result needs at least {start.MIN_POOL} answers. Your marks are kept for when "
        "more answers come.")]


def test_a_named_part_equal_to_the_answer_shows_unless_it_is_the_answer():
    def shown(parts):
        got = _run("""console.log(JSON.stringify({text: ids["q-text"].textContent}));""",
                   data=_data(1, items=[{"id": "a0", "output": "23", "label": None,
                                         "skipped": False, "input": parts}]))
        return got["text"]

    text = shown([["question", "What is 38 - 15?"], ["i", "23"]])
    assert text == "questionWhat is 38 - 15?i23", text  # each name above its value
    assert shown([["question", "What is 38 - 15?"], ["answer", "23"]]) == "What is 38 - 15?"
