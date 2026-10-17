/* judgekeeper.com: the copy buttons; on the home page the demo marking card and the terminal
   for each step; on How it works the range example and the marks kept aside.

   The only motion: the green underline passes once over the five words, and each terminal
   screen is typed the first time it shows (Replay types it again). Under reduced motion both
   are instant. Nothing is stored and nothing is sent. */
(function () {
  "use strict";

  var reduce = !!(window.matchMedia &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches);

  function $(id) { return document.getElementById(id); }

  function $all(selector, root) {
    return Array.prototype.slice.call((root || document).querySelectorAll(selector));
  }

  function make(tag, cls, text) {
    var el = document.createElement(tag);
    if (cls) el.className = cls;
    if (text !== undefined) el.textContent = text;
    return el;
  }

  /* A copy button copies the command next to it and shows a tick for a moment. */
  function setUpCopy() {
    $all("[data-copy]").forEach(function (button) {
      var code = button.parentNode.querySelector("code");
      var said = button.querySelector(".copied");
      function done() {
        button.classList.add("done");
        said.textContent = "Copied";
        clearTimeout(button.jkTimer);
        button.jkTimer = setTimeout(function () {
          button.classList.remove("done");
          said.textContent = "";
        }, 1500);
      }
      function select() {
        var range = document.createRange();
        range.selectNodeContents(code);
        var sel = window.getSelection();
        sel.removeAllRanges();
        sel.addRange(range);
        try { document.execCommand("copy"); } catch (e) { /* the text stays selected */ }
        done();
      }
      button.addEventListener("click", function () {
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(code.textContent).then(done, select);
        } else {
          select();
        }
      });
    });
  }

  /* The demo works like the marking page: the judge's grade stays hidden while you mark, and
     the end card says how often you and the judge disagreed. */
  function setUpDemo() {
    var card = $("demo");
    if (!card) return;
    var items = JSON.parse($("demo-items").textContent);
    var state, history, cur;

    function reset() {
      state = items.map(function () { return "none"; });
      history = [];
      cur = 0;
      card.classList.remove("is-end");
      render();
    }
    function allMarked() {
      return state.every(function (s) { return s === "pass" || s === "fail"; });
    }
    function next() {
      var k, i;
      for (k = 1; k <= items.length; k++) {
        i = (cur + k) % items.length;
        if (state[i] === "none") return i;
      }
      for (k = 1; k <= items.length; k++) {
        i = (cur + k) % items.length;
        if (state[i] === "skip") return i;
      }
      return cur;
    }
    function render() {
      $("d-q").textContent = items[cur][0];
      $("d-a").textContent = items[cur][1];
      var line = $("d-state"), s = state[cur];
      line.textContent = "";
      if (s === "pass" || s === "fail") {
        line.appendChild(document.createTextNode("Marked "));
        line.appendChild(make("b", s === "pass" ? "p" : "f", s === "pass" ? "Pass" : "Fail"));
      } else {
        line.textContent = s === "skip" ? "Skipped" : "Not marked yet";
      }
    }
    function finish() {
      var n = 0;
      items.forEach(function (item, i) { if (state[i] !== item[2]) n += 1; });
      var sum = $("d-sum");
      sum.textContent = "";
      var parts = n ? ["You and your judge disagreed on ", [n], " of ", [items.length], "."]
        : ["You and your judge agreed on all ", [items.length], "."];
      parts.forEach(function (part) {
        sum.appendChild(typeof part === "string" ? document.createTextNode(part)
          : make("span", "mono", String(part[0])));
      });
      card.classList.add("is-end");
    }
    function mark(kind) {
      if (card.classList.contains("is-end")) return;
      history.push({ i: cur, before: state[cur] });
      state[cur] = kind;
      if (allMarked()) { finish(); return; }
      cur = next();
      render();
    }
    function undo() {
      var last = history.pop();
      if (!last) return;
      state[last.i] = last.before;
      cur = last.i;
      card.classList.remove("is-end");
      render();
    }

    $("d-fail").addEventListener("click", function () { mark("fail"); });
    $("d-pass").addEventListener("click", function () { mark("pass"); });
    $("d-skip").addEventListener("click", function () { mark("skip"); });
    $("d-undo").addEventListener("click", undo);
    $("d-again").addEventListener("click", function () {
      reset();
      card.focus({ preventScroll: true });
    });
    card.addEventListener("pointerdown", function () {
      if (!card.contains(document.activeElement)) card.focus({ preventScroll: true });
    });
    document.addEventListener("keydown", function (e) {
      if (!card.contains(document.activeElement) || e.metaKey || e.ctrlKey || e.altKey) return;
      var act = { ArrowLeft: "fail", ArrowRight: "pass", s: "skip", S: "skip" }[e.key];
      if (act) { e.preventDefault(); mark(act); }
      else if (e.key === "z" || e.key === "Z") { e.preventDefault(); undo(); }
    });
    reset();
  }

  /* The steps and their terminal. Each screen is typed the first time it shows; after that
     it shows at once, and Replay types it again. */
  function setUpTour() {
    var out = $("t-out");
    if (!out) return;
    var screens = {};
    $all("template[data-screen]").forEach(function (t) {
      screens[t.getAttribute("data-screen")] = t.content.textContent;
    });
    var tabs = $("t-tabs"), replay = $("t-replay"), term = $("term");
    var steps = $all(".steplist [data-step]"), words = $all(".five [data-step]");
    var current = "find", fixTab = "fix", frame = null, seen = {};

    function screenKey() { return current === "fix" ? fixTab : current; }
    function underline(step) {
      words.forEach(function (w) { w.classList.toggle("is-on", w.getAttribute("data-step") === step); });
    }
    function paint() {
      steps.forEach(function (b) {
        b.setAttribute("aria-selected", String(b.getAttribute("data-step") === current));
      });
      underline(current);
      $all("[data-screen]", tabs).forEach(function (b) {
        b.setAttribute("aria-selected", String(b.getAttribute("data-screen") === fixTab));
      });
      tabs.hidden = current !== "fix";
    }
    function type(key, animate) {
      var text = screens[key];
      seen[key] = true;
      if (frame) { cancelAnimationFrame(frame); frame = null; }
      if (reduce || !animate) { out.textContent = text; return; }
      var cursor = make("span", "cursor", "▋");
      var perSecond = Math.max(420, text.length / 2.2), start = null, shown = 0;
      out.textContent = "";
      out.appendChild(cursor);
      function step(now) {
        if (start === null) start = now;
        var want = Math.min(text.length, Math.floor((now - start) / 1000 * perSecond));
        if (want > shown) {
          shown = want;
          out.textContent = text.slice(0, shown);
          out.appendChild(cursor);
        }
        if (shown < text.length) frame = requestAnimationFrame(step);
        else { cursor.remove(); frame = null; }
      }
      frame = requestAnimationFrame(step);
    }
    function show() {
      var key = screenKey();
      type(key, !seen[key]);
    }
    function pick(step) {
      current = step;
      paint();
      show();
    }

    steps.forEach(function (b) {
      b.addEventListener("click", function () { pick(b.getAttribute("data-step")); });
    });
    words.forEach(function (w) {
      w.addEventListener("click", function () { pick(w.getAttribute("data-step")); });
    });
    $all("[data-screen]", tabs).forEach(function (b) {
      b.addEventListener("click", function () {
        fixTab = b.getAttribute("data-screen");
        paint();
        show();
      });
    });
    replay.addEventListener("click", function () { type(screenKey(), true); });
    paint();

    // The first screen is typed when the terminal comes into view.
    if ("IntersectionObserver" in window) {
      var watch = new IntersectionObserver(function (entries) {
        if (!entries[0].isIntersecting) return;
        watch.disconnect();
        if (!seen[screenKey()]) show();
      }, { threshold: 0.25 });
      watch.observe(term);
    } else {
      show();
    }

    // The hero's one moment: the green underline passes once over the five words, then rests
    // on the chosen step.
    function sweep() {
      var order = words.map(function (w) { return w.getAttribute("data-step"); });
      order.forEach(function (step, i) {
        setTimeout(function () { if (current === "find") underline(step); }, 700 + 260 * i);
      });
      setTimeout(paint, 700 + 260 * order.length);
    }
    if (!reduce && words.length && !location.hash) sweep();
  }

  /* How it works: more marks, a smaller range. An example with a judge right 61% of the time. */
  function setUpRange() {
    var input = $("n");
    if (!input) return;
    var count = $("n-out"), range = $("sim-range"), lo = $("sim-lo"), hi = $("sim-hi");
    var rate = 0.61, z = 2.054;
    function draw() {
      var k = Number(input.value), mid = (rate * k + 0.5) / (k + 1);
      var sd = Math.sqrt(mid * (1 - mid) / (k + 2));
      var a = Math.max(0, mid - z * sd), b = Math.min(1, mid + z * sd);
      count.value = String(k);
      count.textContent = String(k);
      range.style.left = (a * 100) + "%";
      range.style.width = ((b - a) * 100) + "%";
      lo.textContent = Math.round(a * 100) + "%";
      hi.textContent = Math.round(b * 100) + "%";
      $("sim-dot").style.left = (rate * 100) + "%";
    }
    input.addEventListener("input", draw);
    draw();
  }

  /* How it works: the 10 marks kept aside, and what judgekeeper says for each example. */
  var KEPT = {
    "6,0": "Result: your new rule is better. A difference this large is very unlikely to be a coincidence.",
    "4,0": "Result: safe to try. Not clearly better yet, but very unlikely to be more than 10 points worse.",
    "4,2": "Result: can't tell yet. That leans toward better, but a split this small could easily be a coincidence.",
    "1,3": "Result: it looks worse. Keep the old rule."
  };

  function setUpKept() {
    var row = $("kept-row");
    if (!row) return;
    var said = $("kept-out"), buttons = $all(".kept-btns button");
    function show(fixed, broke) {
      row.textContent = "";
      for (var i = 0; i < 10; i++) {
        row.appendChild(i < fixed ? make("span", "fx", "✓")
          : i < fixed + broke ? make("span", "br", "✕") : make("span"));
      }
      said.textContent = KEPT[fixed + "," + broke];
      buttons.forEach(function (b) {
        var on = b.getAttribute("data-fixed") === String(fixed) &&
          b.getAttribute("data-broke") === String(broke);
        b.setAttribute("aria-pressed", String(on));
      });
    }
    buttons.forEach(function (b) {
      b.addEventListener("click", function () {
        show(Number(b.getAttribute("data-fixed")), Number(b.getAttribute("data-broke")));
      });
    });
    show(6, 0);
  }

  setUpCopy();
  setUpDemo();
  setUpTour();
  setUpRange();
  setUpKept();
})();
