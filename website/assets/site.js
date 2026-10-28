/* judgekeeper.com: the copy buttons; on the home page the demo marking card, the terminal
   for each step and the public-dataset numbers.

   The only motion: the green underline passes once over the five words, each terminal
   screen is typed the first time it shows (Replay types it again), and the public-dataset
   numbers count up once. Under reduced motion all are instant. Nothing is stored and nothing
   is sent. */
(function () {
  "use strict";

  var reduce = !!(window.matchMedia &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches);

  function $(id) { return document.getElementById(id); }

  /* A phone: the width at which the home terminal wraps its lines (style.css, 600px). */
  function narrow() {
    return !!(window.matchMedia && window.matchMedia("(max-width: 600px)").matches);
  }

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

  /* The demo works like the marking page: the LLM-as-a-judge's grade stays hidden while you
     mark, and the end card shows, answer by answer, where you and it disagreed. */
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
        var done = state.filter(function (x) { return x === "pass" || x === "fail"; }).length;
        line.textContent = (s === "skip" ? "Skipped · " : "") + done + " of " + items.length + " marked";
      }
    }
    /* One row per answer on the end card: the question, your mark and the LLM-as-a-judge's
       grade, with a red dot where the two differ. */
    function fillList(marks) {
      var list = $("d-list"), head = make("li", "head", "");
      list.textContent = "";
      head.appendChild(make("span", "", ""));
      head.appendChild(make("span", "", "Question"));
      head.appendChild(make("span", "g", "You"));
      head.appendChild(make("span", "g", "LLM-as-a-judge"));
      list.appendChild(head);
      items.forEach(function (item, i) {
        var you = marks[i], judge = item[2], li = make("li", you === judge ? "agree" : "differ", "");
        li.appendChild(make("span", "dot", ""));
        li.appendChild(make("span", "q", item[0]));
        var mine = make("b", "g " + (you === "pass" ? "p" : "f"), you === "pass" ? "Pass" : "Fail");
        var its = make("b", "g " + (judge === "pass" ? "p" : "f"), judge === "pass" ? "Pass" : "Fail");
        mine.setAttribute("data-label", "You");  // shown before the grade on a small phone
        its.setAttribute("data-label", "LLM-as-a-judge");
        li.appendChild(mine);
        li.appendChild(its);
        list.appendChild(li);
      });
    }
    function finish() {
      var n = 0;
      items.forEach(function (item, i) { if (state[i] !== item[2]) n += 1; });
      var sum = $("d-sum");
      sum.textContent = "";
      var parts = n ? ["You and your LLM-as-a-judge disagreed on ", [n], " of ", [items.length], "."]
        : ["You and your LLM-as-a-judge agreed on all ", [items.length], "."];
      parts.forEach(function (part) {
        sum.appendChild(typeof part === "string" ? document.createTextNode(part)
          : make("span", "mono", String(part[0])));
      });
      sum.classList.toggle("ok", !n);
      fillList(state);
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

    /* One height for the card: that of its tallest answer or of the end card, measured on load,
       when the fonts arrive and on resize, so nothing below it moves while you mark. */
    function lockHeight() {
      var ended = card.classList.contains("is-end"), sum = $("d-sum"), said = sum.textContent;
      var tallest = 0;
      card.style.minHeight = "";
      card.classList.remove("is-end");
      items.forEach(function (item) {
        $("d-q").textContent = item[0];
        $("d-a").textContent = item[1];
        tallest = Math.max(tallest, card.offsetHeight);
      });
      sum.textContent = "You and your LLM-as-a-judge disagreed on " + items.length + " of " + items.length + ".";
      fillList(items.map(function (item) { return item[2] === "pass" ? "fail" : "pass"; }));
      card.classList.add("is-end");
      tallest = Math.max(tallest, card.offsetHeight);
      sum.textContent = said;
      card.classList.toggle("is-end", ended);
      render();
      card.style.minHeight = tallest + "px";
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
    lockHeight();
    var resized;
    window.addEventListener("resize", function () {
      clearTimeout(resized);
      resized = setTimeout(lockHeight, 100);
    });
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(lockHeight);
  }

  /* Colours for terminal text: the prompt and command, step headings, field labels, the result
     and the Next line. */
  function shade(text) {
    var esc = function (t) { return t.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;"); };
    var span = function (cls, t) { return '<span class="' + cls + '">' + t + '</span>'; };
    /* Words inside a line: Pass green, Fail red, outcome words, the main numbers, ranges dim,
       file names, quoted text and `commands`. Quoted text is left as it is inside. */
    var paint = function (t) {
      return t.split(/("[^"]*"|`[^`]*`)/).map(function (part, i) {
        if (i % 2) return span(part.charAt(0) === "`" ? "t-cmd" : "t-quote", part);
        return part
          .replace(/(\(between [^)]*\)|\(somewhere between [^)]*\))/g, function (x) { return span("t-dim", x); })
          .replace(/\b(about \d+%|\d+ of \d+\b)/g, function (x) { return span("t-num", x); })
          .replace(/\bPass\b/g, span("t-pass", "Pass"))
          .replace(/\bFail\b/g, span("t-fail", "Fail"))
          .replace(/\b(Worse|needs work)\b/g, function (x) { return span("t-warn", x); })
          .replace(/\b(Not sure)\b/g, function (x) { return span("t-unsure", x); })
          .replace(/\b(is better|Better)\b/g, function (x) { return span("t-good", x); })
          .replace(/(\.judgekeeper\/[\w\/.-]+|\b[\w-]+\.(?:json|yaml|yml|md|txt|html)\b)/g, function (x) { return span("t-path", x); })
          .replace(/(\[y\/N\]) y$/, function (x, q) { return span("t-dim", q) + " " + span("t-good", "y"); });
      }).join("");
    };
    return text.split("\n").map(function (line) {
      var m;
      if ((m = /^(\$ )(.*)$/.exec(line))) return '<span class="t-prompt">' + esc(m[1]) + '</span><span class="t-cmd">' + esc(m[2]) + '</span>';
      if (/^Step \d of 5: /.test(line)) return '<span class="t-step">' + esc(line) + '</span>';
      if (/^judgekeeper \d/.test(line)) return '<span class="t-dim">' + esc(line) + '</span>';
      if ((m = /^(Result: )(.*)$/.exec(line))) {
        var tone = /needs work|worse/i.test(m[2]) ? "t-warn" : /good enough|better/i.test(m[2]) ? "t-good" : "t-step";
        return '<span class="t-label">' + esc(m[1]) + '</span><span class="' + tone + '">' + esc(m[2]) + '</span>';
      }
      if ((m = /^(Next:)(.*)$/.exec(line))) return '<span class="t-next">' + esc(m[1]) + '</span>' + paint(esc(m[2]));
      if ((m = /^(Checked:)(.*)$/.exec(line))) return span("t-good", esc(m[1])) + paint(esc(m[2]));
      if (/^Agreed with you: /.test(line)) return span("t-label", esc(line));  // the table's head
      if ((m = /^([A-Z][A-Za-z -]{1,16}:)( {2,}.*)$/.exec(line))) return '<span class="t-label">' + esc(m[1]) + '</span>' + paint(esc(m[2]));
      return paint(esc(line));
    }).join("\n");
  }

  /* On a phone the terminal wraps its own lines, so a line the screen broke only to fit 64
     columns goes on after the one above it: a line that ends in a word or a comma, when neither
     line is laid out in columns (two spaces inside it) and the one above is not the command. */
  function joinLines(text) {
    var cols = /\S {2,}\S/;
    return text.split("\n").reduce(function (lines, line) {
      var last = lines.length ? lines[lines.length - 1] : "";
      if (line.trim() && /[A-Za-z,]$/.test(last) && !/^\$ /.test(last) && !cols.test(last) &&
          !cols.test(line)) {
        lines[lines.length - 1] = last + " " + line.trim();
      } else {
        lines.push(line);
      }
      return lines;
    }, []).join("\n");
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
    var fixTabs = $all("[data-screen]", tabs);
    var current = "find", fixTab = "fix", frame = null, seen = {};

    function screenKey() { return current === "fix" ? fixTab : current; }
    function underline(step) {
      words.forEach(function (w) { w.classList.toggle("is-on", w.getAttribute("data-step") === step); });
    }
    /* A tab list: only the chosen tab is in the Tab order; the arrow keys, Home and End move
       to another tab and choose it. */
    function choose(list, chosen) {
      list.forEach(function (b) {
        b.setAttribute("aria-selected", String(b === chosen));
        b.tabIndex = b === chosen ? 0 : -1;
      });
    }
    function arrows(list, go) {
      list.forEach(function (b, i) {
        b.addEventListener("keydown", function (e) {
          var n = list.length, to = { ArrowDown: i + 1, ArrowRight: i + 1, ArrowUp: i - 1,
            ArrowLeft: i - 1, Home: 0, End: n - 1 }[e.key];
          if (to === undefined || e.metaKey || e.ctrlKey || e.altKey) return;
          e.preventDefault();
          var next = list[(to + n) % n];
          next.focus();
          go(next);
        });
      });
    }
    function paint() {
      var tab = steps.filter(function (b) { return b.getAttribute("data-step") === current; })[0];
      choose(steps, tab);
      term.setAttribute("aria-labelledby", tab.id);
      underline(current);
      choose(fixTabs, fixTabs.filter(function (b) { return b.getAttribute("data-screen") === fixTab; })[0]);
      tabs.hidden = current !== "fix";
    }
    function type(key, animate) {
      var text = narrow() ? joinLines(screens[key]) : screens[key];
      seen[key] = true;
      if (frame) { cancelAnimationFrame(frame); frame = null; }
      out.style.minHeight = "";
      if (reduce || !animate) { out.innerHTML = shade(text); return; }
      // the box takes the height of the whole screen first, so nothing below it moves as it types
      out.innerHTML = shade(text);
      out.style.minHeight = out.offsetHeight + "px";
      var cursor = make("span", "cursor", "▋");
      var perSecond = Math.max(420, text.length / 2.2), start = null, shown = 0;
      out.textContent = "";
      out.appendChild(cursor);
      function step(now) {
        if (start === null) start = now;
        var want = Math.min(text.length, Math.floor((now - start) / 1000 * perSecond));
        if (want > shown) {
          shown = want;
          out.innerHTML = shade(text.slice(0, shown));
          out.appendChild(cursor);
        }
        if (shown < text.length) frame = requestAnimationFrame(step);
        else { cursor.remove(); out.innerHTML = shade(text); out.style.minHeight = ""; frame = null; }
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
    arrows(steps, function (b) { pick(b.getAttribute("data-step")); });
    /* A click on one of the five words brings the whole section into view, with the same space
       above the heading as below the box (or the heading near the top when the section is taller
       than the window). The address still gets #steps, as the link does without JavaScript. */
    function showSection() {
      var section = $("steps");
      if (!section) return;
      var first = section.querySelector("h2") || section, last = section.querySelector(".steps-grid") || section;
      var top = first.getBoundingClientRect().top + window.scrollY;
      var bottom = last.getBoundingClientRect().bottom + window.scrollY;
      var room = window.innerHeight, height = bottom - top;
      var y = height + 48 <= room ? top - (room - height) / 2 : top - 24;
      window.scrollTo({ top: Math.max(0, y), behavior: reduce ? "auto" : "smooth" });
    }
    words.forEach(function (w) {
      w.addEventListener("click", function (e) {
        e.preventDefault();
        pick(w.getAttribute("data-step"));
        showSection();
        if (history.replaceState) history.replaceState(null, "", "#steps");
      });
    });
    function pickScreen(b) {
      fixTab = b.getAttribute("data-screen");
      paint();
      show();
    }
    fixTabs.forEach(function (b) {
      b.addEventListener("click", function () { pickScreen(b); });
    });
    arrows(fixTabs, pickScreen);
    replay.addEventListener("click", function () { type(screenKey(), true); });
    paint();
    // on a phone the waiting screen has its lines joined already, so typing keeps its height
    if (narrow()) out.innerHTML = shade(joinLines(screens[screenKey()]));

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

  /* The two public-dataset numbers count up once when they come into view (not under reduced
     motion). The page's own text already holds the final numbers. */
  function setUpCounts() {
    var nums = $all(".rt-n");
    if (!nums.length || reduce || !("IntersectionObserver" in window)) return;
    if (narrow()) return;  // on a phone the numbers show as they are
    var seen = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (!e.isIntersecting) return;
        seen.unobserve(e.target);
        var el = e.target, to = +el.getAttribute("data-to"), t0 = null;
        function step(t) {
          if (t0 === null) t0 = t;
          var k = Math.min(1, (t - t0) / 900), ease = 1 - Math.pow(1 - k, 3);
          el.textContent = String(Math.round(to * ease));
          if (k < 1) requestAnimationFrame(step);
        }
        el.textContent = "0";
        requestAnimationFrame(step);
      });
    }, { threshold: 0.6 });
    nums.forEach(function (n) { seen.observe(n); });
  }

  /* On a phone a picture of the Guide opens over the page, wide enough to read, to swipe
     around; Close, a tap beside it or Escape closes it. Wider screens open the file. */
  function setUpShots() {
    var links = $all(".gx-shot a");
    if (!links.length || typeof HTMLDialogElement !== "function") return;
    var view = make("dialog", "shot-view"), bar = make("div", "shot-bar");
    var close = make("button", "shot-close", "Close"), pane = make("div", "shot-pane");
    var img = make("img", "", undefined);
    close.type = "button";
    view.setAttribute("aria-label", "Picture, full size");
    pane.tabIndex = 0;
    bar.appendChild(close);
    pane.appendChild(img);
    view.appendChild(bar);
    view.appendChild(pane);
    document.body.appendChild(view);
    function shut() { if (view.open) view.close(); }
    close.addEventListener("click", shut);
    view.addEventListener("click", function (e) { if (e.target === view || e.target === pane) shut(); });
    view.addEventListener("close", function () {
      document.documentElement.classList.remove("has-view");
      img.removeAttribute("src");
    });
    links.forEach(function (a) {
      a.addEventListener("click", function (e) {
        if (!narrow()) return;
        e.preventDefault();
        var shown = a.querySelector("img");
        img.src = a.getAttribute("href");
        img.alt = shown ? shown.alt : "";
        document.documentElement.classList.add("has-view");
        view.showModal();
        pane.scrollLeft = 0;
        pane.scrollTop = 0;
        close.focus();
      });
    });
  }

  /* On a phone only (a laptop's text stays as it is): "LLM-as-a-judge" in a step's words never
     breaks at its hyphens, and a path in a sentence may break after each "/". */
  function setUpPhoneBreaks() {
    if (!narrow()) return;
    $all(".steplist .d").forEach(function (d) {
      var parts = d.textContent.split("LLM-as-a-judge");
      if (parts.length < 2) return;
      d.textContent = "";
      parts.forEach(function (part, i) {
        if (i) d.appendChild(make("span", "nb", "LLM-as-a-judge"));
        d.appendChild(document.createTextNode(part));
      });
    });
    $all("code.path").forEach(function (code) {
      var parts = code.textContent.split("/");
      code.textContent = "";
      parts.forEach(function (part, i) {
        if (i) code.appendChild(document.createElement("wbr"));
        code.appendChild(document.createTextNode((i < parts.length - 1) ? part + "/" : part));
      });
    });
  }

  setUpCopy();
  setUpPhoneBreaks();
  setUpShots();
  setUpDemo();
  setUpTour();
  setUpCounts();
})();
