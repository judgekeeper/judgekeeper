"""A reason typed in "Other…" on the result page shows as a button on the other answers'
reason boxes as soon as it is saved, with no reload (up to reasons.MAX_OWN)."""

from __future__ import annotations

import http.client
import json
from urllib.parse import urlsplit

from judgekeeper import report_page
from tests.test_long_reasons import _node
from tests.test_reasons import _ready, _run, here  # noqa: F401


def _post(url: str, body: dict) -> tuple[int, dict]:
    u = urlsplit(url)
    conn = http.client.HTTPConnection(u.hostname, u.port, timeout=5)
    try:
        conn.request("POST", f"/label?{u.query}", body=json.dumps(body).encode(),
                     headers={"Origin": f"http://{u.hostname}:{u.port}",
                              "Content-Type": "application/json"})
        resp = conn.getresponse()
        return resp.status, json.loads(resp.read() or b"{}")
    finally:
        conn.close()


def test_a_reason_saved_answers_with_the_own_buttons(here, capsys, pages, no_browser):  # noqa: F811
    _, passes, _, _ = _ready(here)
    code, out = _run(capsys, "mark")
    assert code == 0, out
    url = no_browser[0]
    status, got = _post(url, {"id": passes[0], "reasons": [], "note": "Gives the old price"})
    assert status == 200, got
    assert got["own"] == [{"id": "own-1", "text": "Gives the old price", "from": passes[0]}]


# Two answers' reason boxes, as the page draws them -------------------------------------------

_TWO_BOXES = r"""
function El(tag) { this.tagName = tag; this.attrs = {}; this.listeners = {}; this.hidden = false;
  this.textContent = ""; this.value = ""; this.kids = []; this.parentNode = null;
  this.className = ""; }
El.prototype.getAttribute = function (k) { return k in this.attrs ? this.attrs[k] : null; };
El.prototype.setAttribute = function (k, v) { this.attrs[k] = String(v); };
El.prototype.hasAttribute = function (k) { return k in this.attrs; };
El.prototype.removeAttribute = function (k) { delete this.attrs[k]; };
El.prototype.addEventListener = function (t, f) { this.listeners[t] = f; };
El.prototype.focus = function () {};
El.prototype.appendChild = function (c) { c.parentNode = this; this.kids.push(c); return c; };
El.prototype.insertBefore = function (c, before) {
  c.parentNode = this; var i = this.kids.indexOf(before);
  this.kids.splice(i < 0 ? this.kids.length : i, 0, c); return c; };
El.prototype.remove = function () {
  var p = this.parentNode; if (p) { p.kids.splice(p.kids.indexOf(this), 1); } };
El.prototype.all = function () {
  var out = []; this.kids.forEach(function (k) { out.push(k); out = out.concat(k.all()); });
  return out; };
function match(el, s) {
  if (s === "[aria-pressed]") { return el.hasAttribute("aria-pressed"); }
  if (s === '[data-reason^="own-"]') {
    return (el.getAttribute("data-reason") || "").indexOf("own-") === 0; }
  if (s === "[data-reason]") { return el.hasAttribute("data-reason"); }
  return s === "." + el.className || s === el.tagName; }
El.prototype.querySelectorAll = function (s) {
  return this.all().filter(function (e) { return match(e, s); }); };
El.prototype.querySelector = function (s) { return this.querySelectorAll(s)[0] || null; };
function make(tag, cls, parent) { var e = new El(tag); e.className = cls.slice(1);
  parent.appendChild(e); return e; }
function Box(id) {
  var box = new El("div"); box.className = "why"; box.attrs = {"data-answer": "a-" + id,
    "data-id": id, "data-len": "10", "data-spans": "[]"};
  [".saved", ".mark-part", ".clear-part", ".add-reason", ".said-now"].forEach(function (c) {
    make("p", c, box); });
  var text = make("span", ".said-text", box); make("b", ".said-words", text);
  var chips = make("div", ".chips", box);
  var wrong = make("button", ".chip", chips); wrong.attrs = {"aria-pressed": "false",
    "data-reason": "wrong_fact", "data-said": "it has a wrong fact"};
  make("button", ".other", chips);
  box.appendChild(new El("input"));
  return box; }
var boxes = [Box("x1"), Box("x2")], cell = new El("td"), REPLY_OWN = [];
var document = {getElementById: function () { return new El("div"); },
  querySelectorAll: function (s) { return s === ".why" ? boxes : []; },
  querySelector: function () { return null; },
  addEventListener: function () {}, createRange: function () {},
  createElement: function (tag) { return new El(tag); }};
var location = {search: "?token=t"};
var window = {getSelection: function () { return {rangeCount: 0}; }, dispatchEvent: function () {},
  fetch: function () { return {then: function (ok) { return ok({ok: true, json: function () {
    return {then: function (f) { return f({summary: {}, own: REPLY_OWN}); }}; }}); }}; }};
function Event(type) { this.type = type; }
function own(box) { return box.querySelectorAll('[data-reason^="own-"]').map(function (b) {
  return [b.getAttribute("data-reason"), b.querySelector(".t").textContent,
          b.getAttribute("aria-pressed")]; }); }
"""


def test_an_own_reason_saved_shows_on_the_other_boxes_at_once():
    scenario = """
      var steps = [], input = boxes[0].querySelector("input");
      REPLY_OWN = [{id: "own-1", text: "Gives the old price", from: "x1"}];
      input.value = "Gives the old price"; input.listeners.keydown({key: "Enter",
        preventDefault: function () {}});
      steps.push(own(boxes[0]), own(boxes[1]));
      var chips = boxes[1].querySelector(".chips").kids;
      steps.push(chips[chips.length - 1].className);  // "Other…" stays the last button
      var b = boxes[1].querySelectorAll("[data-reason]").filter(function (x) {
        return x.getAttribute("data-reason") === "own-1"; })[0];
      b.listeners.click();  // the new button works on its own box
      steps.push(b.getAttribute("aria-pressed"));
      REPLY_OWN = [{id: "own-1", text: "Gives an old price", from: "x1"}];  // typed on
      input.value = "Gives an old price"; input.listeners.keydown({key: "Enter",
        preventDefault: function () {}});
      steps.push(own(boxes[1]));
      console.log(JSON.stringify(steps));"""
    got = _node(_TWO_BOXES + report_page.REASONS_SCRIPT.replace("__MAX__", "500") + scenario)
    assert got == [[], [["own-1", "Gives the old price", "false"]], "other", "true",
                   [["own-1", "Gives an old price", "true"]]]


def test_an_own_reason_gone_leaves_the_other_boxes_unless_tapped_there():
    scenario = """
      var input = boxes[0].querySelector("input");
      REPLY_OWN = [{id: "own-1", text: "Gives the old price", from: "x1"}];
      input.value = "Gives the old price"; input.listeners.keydown({key: "Enter",
        preventDefault: function () {}});
      REPLY_OWN = [];
      input.value = ""; input.listeners.keydown({key: "Enter", preventDefault: function () {}});
      console.log(JSON.stringify(own(boxes[1])));"""
    got = _node(_TWO_BOXES + report_page.REASONS_SCRIPT.replace("__MAX__", "500") + scenario)
    assert got == []
