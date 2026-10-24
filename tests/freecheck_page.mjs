// The browser check's page code (website/assets/freecheck.js, setup) in node, on a small stand-in
// for check.html: node tests/freecheck_page.mjs STEP... prints, as JSON, what the page shows
// after each step. A step is "click:<example>", "drag:<example>" (dropped on the page),
// "file:<path>" (a file of your own dropped on the page) or "clear".
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { basename, dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import vm from "node:vm";

const SITE = join(dirname(fileURLToPath(import.meta.url)), "..", "website");
const EXAMPLE_TYPE = "application/x-judgekeeper-example";

class Node {
  constructor(tag, attrs = {}) {
    this.tagName = tag.toUpperCase();
    this.attrs = { ...attrs };
    this.children = [];
    this.listeners = {};
    this.hidden = "hidden" in attrs;
    this.className = attrs.class || "";
    this.id = attrs.id || "";
    this._text = "";
    const node = this;
    this.classList = {
      add: (c) => { if (!node.classList.contains(c)) node.className = (node.className + " " + c).trim(); },
      remove: (c) => { node.className = node.className.split(/\s+/).filter((x) => x !== c).join(" "); },
      toggle: (c, on) => (on ? node.classList.add(c) : node.classList.remove(c)),
      contains: (c) => node.className.split(/\s+/).includes(c),
    };
  }
  set textContent(t) { this.children = []; this._text = String(t); }
  get textContent() { return this._text + this.children.map((c) => c.textContent).join(""); }
  appendChild(c) { this.children.push(c); c.parentNode = this; if (this.onappend) this.onappend(c); return c; }
  replaceChildren() { this.children = []; this._text = ""; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
  addEventListener(t, f) { (this.listeners[t] = this.listeners[t] || []).push(f); }
  dispatch(t, e = {}) { (this.listeners[t] || []).forEach((f) => f({ preventDefault() {}, ...e })); }
  click() { this.dispatch("click"); }
  focus() { document.activeElement = this; }
  *all() { yield this; for (const c of this.children) yield* c.all(); }
  matches(sel) {
    if (sel.startsWith("#")) return this.id === sel.slice(1);
    if (sel.startsWith(".")) return this.classList.contains(sel.slice(1));
    const m = /^\[([\w-]+)\]$/.exec(sel);
    return m ? m[1] in this.attrs : false;
  }
  querySelector(sel) { for (const n of this.all()) if (n !== this && n.matches(sel)) return n; return null; }
  querySelectorAll(sel) { return [...this.all()].filter((n) => n !== this && n.matches(sel)); }
}

// The elements of check.html that carry an id or a class freecheck.js looks for, nested as there
const html = readFileSync(join(SITE, "check.html"), "utf8");
const body = new Node("body");
const stack = [body];
const VOID = new Set(["input", "img", "br", "meta", "link", "path", "rect", "circle", "polyline", "line"]);
for (const m of html.matchAll(/<(\/?)([a-z0-9]+)([^>]*?)(\/?)>|([^<]+)/g)) {
  if (m[5] !== undefined) { if (stack.length > 1) stack.at(-1)._text += m[5]; continue; }
  const [, close, tag, rest, self] = m;
  if (close) { while (stack.length > 1 && stack.pop().tagName !== tag.toUpperCase()); continue; }
  const attrs = {};
  for (const a of rest.matchAll(/([\w-:]+)(?:="([^"]*)")?/g)) attrs[a[1]] = a[2] === undefined ? "" : a[2];
  const node = stack.at(-1).appendChild(new Node(tag, attrs));
  if (!self && !VOID.has(tag)) stack.push(node);
}

const head = new Node("head");
const document = {
  readyState: "complete",
  head, body, activeElement: null, listeners: {},
  getElementById: (id) => body.querySelector("#" + id),
  querySelector: (sel) => body.querySelector(sel),
  querySelectorAll: (sel) => body.querySelectorAll(sel),
  createElement: (tag) => new Node(tag),
  addEventListener(t, f) { (this.listeners[t] = this.listeners[t] || []).push(f); },
  dispatch(t, e) { (this.listeners[t] || []).forEach((f) => f({ preventDefault() {}, ...e })); },
};
// an example's script, added to the page, runs as the browser would run it
head.onappend = (tag) => {
  const src = tag.attrs.src || tag.src;
  vm.runInThisContext(readFileSync(join(SITE, src), "utf8"));
  tag.onload();
};
globalThis.document = document;
globalThis.window = globalThis;
globalThis.FileReader = class {
  readAsArrayBuffer(file) { this.result = file.bytes; this.onload(); }
};

createRequire(import.meta.url)("../website/assets/freecheck.js");

function shown() {
  const one = (sel) => body.querySelector(sel);
  return {
    title: one("#ck-title").textContent,
    box: one(".fc-empty").hidden ? "file" : "empty",
    name: one("#fc-name").textContent,
    examples: !one(".fc-try").hidden,
    clear: !one("#fc-clear").hidden,
    waiting: !one("#ck-wait").hidden,
    output: one("#fc-result").textContent,
    has_file: one("#fc-drop").classList.contains("has-file"),
    focus: document.activeElement ? document.activeElement.id : null,
  };
}

const out = [];
for (const step of process.argv.slice(2)) {
  const [kind, arg] = [step.split(":")[0], step.slice(step.indexOf(":") + 1)];
  const card = body.querySelectorAll("[data-example-file]").find((b) => b.getAttribute("data-example-file") === arg);
  if (kind === "click") card.click();
  if (kind === "drag") {
    const data = {};
    const dataTransfer = { setData: (t, v) => { data[t] = v; }, getData: (t) => data[t] || "", files: [] };
    card.dispatch("dragstart", { dataTransfer });
    document.dispatch("drop", { dataTransfer });
  }
  if (kind === "file") {
    const bytes = readFileSync(arg);
    const file = { name: basename(arg), size: bytes.length, bytes: bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.length) };
    document.dispatch("drop", { dataTransfer: { getData: () => "", files: [file] } });
  }
  if (kind === "clear") body.querySelector("#fc-clear").click();
  out.push({ step, ...shown() });
}
console.log(JSON.stringify(out));
