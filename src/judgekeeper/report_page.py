"""The result page: what the marking page shows at /result, and `.judgekeeper/report.html`.

One self-contained page (look.py: nothing loaded from anywhere else); every string in it is
escaped. Its two scripts (the theme, read first; the switch, opening rows and sections, Copy)
are fixed text: the page's Content-Security-Policy lets exactly those run (by their hashes)
and nothing else, both when it is served and in the saved copy, which opens with no server.

The numbers: the top rows count every mark ("too strict on 6": answers you passed that the
judge failed); "Where it goes wrong" shows only the mistakes on the marks the person can see,
and says how many more are among the hidden marks (fix.py keeps those aside to test a new rule
fairly). Shown plus hidden is the top rows' total.
"""

from __future__ import annotations

from html import escape

from judgekeeper import look, targets

ROWS_SHOWN = 3  # disagreements shown before "Show all"
ESTIMATES = ("These are estimates from {n} marked answers. Mark more answers to make them more "
             "precise.")
HIDDEN = ("{n} more {are} among your hidden marks, kept aside to test a new rule fairly.")
SAVED = ("This page is saved as <code>.judgekeeper/report.html</code>. Your marks and answers "
         "stay on this computer.")
EVAL_COMMANDS = {"deepeval": "deepeval test run", "inspect": "inspect eval"}
KAPPA_MEANS = "0 means no better than coincidence, 1 means it always agrees."
ADJUSTED = "of your marks, adjusted for how the answers were picked"

# The page's script: fixed text, so its hash can be in the Content-Security-Policy.
SCRIPT = look.THEME_SWITCH + """
  (function () {
    function each(selector, fn) {
      Array.prototype.forEach.call(document.querySelectorAll(selector), fn); }
    each(".row-open", function (b) {
      b.addEventListener("click", function () {
        var open = b.getAttribute("aria-expanded") !== "true";
        b.setAttribute("aria-expanded", String(open));
        b.closest("tr").classList.toggle("opened", open);
      });
    });
    var all = document.getElementById("show-all");
    if (all) {
      var shut = all.textContent;
      all.addEventListener("click", function () {
        var open = all.getAttribute("aria-expanded") !== "true";
        all.setAttribute("aria-expanded", String(open));
        each("#mistakes .extra", function (row) { row.hidden = !open; });
        all.textContent = open ? "Show fewer" : shut;
      });
    }
    var more = document.getElementById("more-toggle");
    more.addEventListener("click", function () {
      var open = more.getAttribute("aria-expanded") !== "true";
      more.setAttribute("aria-expanded", String(open));
      document.getElementById("more").hidden = !open;
    });
    each(".copy", function (b) {
      var timer;
      b.addEventListener("click", function () {
        var text = document.getElementById(b.getAttribute("data-copy")).textContent;
        function done(ok) {
          b.textContent = ok ? "Copied" : "Copy failed";
          clearTimeout(timer);
          timer = setTimeout(function () { b.textContent = "Copy"; }, 1500);
        }
        try { navigator.clipboard.writeText(text).then(function () { done(true); },
                                                       function () { done(false); }); }
        catch (e) { done(false); }
      });
    });
  })();
"""
CSP = ("default-src 'none'; script-src " + look.script_hash(look.THEME_FIRST) + " "
       + look.script_hash(SCRIPT) + "; style-src 'unsafe-inline'; font-src data:; "
       "img-src 'none'; base-uri 'none'; form-action 'none'")

STYLE = """
:root { --paper: var(--bg); --sheet: var(--bg); --tint: var(--hover); --tint-2: var(--hover);
  --chip: var(--current); --ink: var(--text); --ink-2: var(--text); --ink-3: var(--muted);
  --rule: var(--line); --rule-2: var(--line); --rule-3: var(--line); --track: var(--line);
  --dash: var(--faint); --accent: var(--text); --accent-2: var(--text); --accent-bg: var(--current);
  --accent-line: var(--line); --mark-line: var(--text); --btn: var(--text); --btn-hover: var(--muted);
  --on-btn: var(--bg); --amber-solid: var(--amber); --amber-bg: var(--hover);
  --amber-line: var(--line); --amber-band: var(--line); --good-band: var(--line);
  --blue: var(--muted); --blue-solid: var(--muted); --blue-bg: var(--hover); --blue-line: var(--line); }
html { scroll-behavior: smooth; }
main.result { max-width: 1180px; margin: 0 auto; padding: 24px 24px 32px; display: flex;
  flex-direction: column; gap: 20px; }
.marks { display: inline-flex; align-items: center; gap: 8px; font-size: 13px; font-weight: 700; }
.row1 { display: flex; flex-wrap: wrap; gap: 20px; align-items: stretch; }
.res { flex: 1 1 560px; min-width: 0; overflow: hidden; display: flex; flex-direction: column; }
.res .head { padding: 12px 18px; }
.res .meta { font-size: 12.5px; font-weight: 600; color: var(--ink-3); }
.res .body { padding: 20px 24px 18px; display: flex; flex-direction: column; gap: 20px;
  flex: 1 1 auto; }
.res h1 { margin: 0; font-weight: 800; font-size: 32px; line-height: 1.15; letter-spacing: -.7px; }
.ests { display: flex; flex-direction: column; gap: 16px; }
.est { display: grid; grid-template-columns: 180px minmax(0, 1fr) 190px; gap: 16px;
  align-items: center; }
.est-label { font-size: 14px; font-weight: 700; line-height: 1.3; display: flex;
  flex-direction: column; gap: 2px; }
.est-label small { font-size: 12.5px; font-weight: 600; }
.est-label .strict { color: var(--blue); }
.est-label .easy { color: var(--amber); }
.bar { position: relative; height: 14px; background: var(--track); border-radius: 999px;
  overflow: hidden; }
.bar span { position: absolute; top: 0; bottom: 0; }
.bar .band { background: var(--good-band); }
.bar .fill { left: 0; border-radius: 999px; background: var(--accent); }
.est.weak .band { background: var(--amber-band); }
.est.weak .fill { background: var(--amber-solid); }
.est-val { display: flex; flex-direction: column; gap: 2px; }
.est-val b { font-size: 22px; font-weight: 800; line-height: 1; letter-spacing: -.4px;
  color: var(--accent); }
.est.weak .est-val b { color: var(--amber); }
.est-val span { font-size: 12px; color: var(--ink-3); }
.est-val .also { font-size: 12px; font-weight: 600; color: var(--ink-2); }
.foot { margin: auto 0 0; font-size: 12.5px; color: var(--ink-3); }
.next { flex: 1 1 340px; min-width: 0; overflow: hidden; display: flex; flex-direction: column;
  border-color: var(--mark-line); }
.next .head { padding: 12px 18px; background: var(--accent-bg); border-bottom-color: var(--accent-line); }
.next .ic { background: var(--btn); color: var(--on-btn); }
.next .body { padding: 18px 20px 20px; display: flex; flex-direction: column; gap: 14px;
  flex: 1 1 auto; }
.next h2 { margin: 0; font-size: 22px; font-weight: 800; letter-spacing: -.4px; line-height: 1.2; }
.next p { margin: 0; font-size: 14px; color: var(--ink-2); }
.steps { margin: 0; padding: 0; list-style: none; display: flex; flex-direction: column;
  gap: 10px; font-size: 14px; color: var(--ink-2); counter-reset: step; }
.steps > li { display: flex; gap: 10px; align-items: flex-start; flex-wrap: wrap; }
.steps > li::before { counter-increment: step; content: counter(step); flex: none; width: 22px;
  height: 22px; border-radius: 50%; background: var(--accent-bg); color: var(--accent);
  font-size: 12px; font-weight: 800; display: inline-flex; align-items: center;
  justify-content: center; }
.steps > li > span { flex: 1 1 0; min-width: 0; padding-top: 1px; }
.steps .cmdrow, .steps .rulebox { flex-basis: 100%; }
.cmdrow { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.cmd { flex: 1 1 200px; min-width: 0; display: flex; align-items: center; gap: 10px;
  background: var(--tint); border: 1px solid var(--rule); border-radius: 9px; padding: 10px 14px;
  font-family: var(--mono); font-size: 13.5px; overflow-wrap: anywhere; }
.cmd::before { content: "$"; color: var(--accent); }
.rulebox { margin: 0; padding: 10px 14px; background: var(--tint); border: 1px solid var(--rule);
  border-radius: 9px; font-size: 13.5px; line-height: 1.55; white-space: pre-wrap;
  overflow-wrap: anywhere; max-height: 14em; overflow: auto; }
.btn { height: 42px; padding: 0 16px; border-radius: 9px; border: 1px solid var(--btn);
  background: var(--btn); color: var(--on-btn); font-size: 14px; font-weight: 800;
  text-decoration: none; display: inline-flex; align-items: center; justify-content: center; }
.btn:hover { background: var(--btn-hover); border-color: var(--btn-hover); color: var(--on-btn); }
.next .mt { margin-top: auto; }
.warn { border-color: var(--amber-line); }
.warn .body { padding: 14px 18px; }
.warn ul { margin: 0; padding-left: 18px; font-size: 14px; color: var(--ink-2); }
.wrong { overflow: hidden; display: flex; flex-direction: column; }
.wrong .head { padding: 12px 18px; }
.lines { padding: 14px 18px; display: flex; flex-direction: column; gap: 6px; }
.lines p { margin: 0; font-size: 14.5px; }
.lines .seen { font-size: 12.5px; font-weight: 700; color: var(--ink-3); text-transform: uppercase;
  letter-spacing: .5px; }
.pills { display: inline-flex; gap: 6px; margin-right: 10px; vertical-align: 1px; }
.pill { font-size: 11px; font-weight: 800; border-radius: 999px; padding: 2px 9px;
  text-transform: uppercase; letter-spacing: .5px; border: 1px solid; }
.pill.easy { color: var(--amber); background: var(--amber-bg); border-color: var(--amber-line); }
.pill.strict { color: var(--blue); background: var(--blue-bg); border-color: var(--blue-line); }
table.mistakes { width: 100%; border-collapse: collapse; table-layout: fixed; font-size: 14px;
  line-height: 1.45; }
.mistakes thead th { padding: 8px 18px; font-size: 11px; font-weight: 700; color: var(--ink-3);
  text-transform: uppercase; letter-spacing: .6px; text-align: left; background: var(--tint);
  border-top: 1px solid var(--rule-2); }
.mistakes th.pad, .mistakes td.pad { width: 34px; padding: 0; }
.mistakes .group th { padding: 10px 18px 6px; font-size: 12.5px; font-weight: 800; text-align: left;
  border-top: 1px solid var(--rule-2); }
.mistakes .group i { display: inline-block; width: 8px; height: 8px; border-radius: 50%;
  margin-right: 8px; vertical-align: 1px; }
.mistakes .group.easy i { background: var(--amber-solid); }
.mistakes .group.strict i { background: var(--blue-solid); }
.mistakes td { padding: 10px 18px; border-top: 1px solid var(--rule-2); vertical-align: top; }
.mistakes .group + tr td { border-top: 0; }
.mistakes tr:not(.group):hover td { background: var(--tint-2); }
.clip { display: block; min-width: 0; overflow: hidden; text-overflow: ellipsis;
  white-space: nowrap; }
.opened .clip { white-space: pre-wrap; overflow: visible; overflow-wrap: anywhere; }
.row-open { border: 0; background: none; padding: 0; text-align: left; width: 100%;
  font-weight: 700; color: var(--ink); display: flex; gap: 8px; align-items: flex-start; }
.row-open svg { flex: none; width: 14px; height: 14px; margin-top: 3px; fill: none;
  stroke: var(--ink-3); stroke-width: 2.2; stroke-linecap: round; stroke-linejoin: round;
  transition: transform .15s; }
.row-open[aria-expanded="true"] svg { transform: rotate(90deg); }
.mistakes .ans { color: var(--ink-3); }
.mistakes .why { color: var(--ink-3); font-size: 13.5px; border-left: 2px solid var(--amber-solid);
  padding-left: 10px; }
.mistakes .strict-row .why { border-left-color: var(--blue-solid); }
.wrong .bottom { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between;
  gap: 10px 16px; padding: 12px 18px; border-top: 1px solid var(--rule-2); background: var(--tint); }
.wrong .bottom span { font-size: 12.5px; color: var(--ink-3); }
.link-btn { border: 1px solid var(--rule-3); background: var(--sheet); color: var(--ink);
  font-size: 13px; font-weight: 700; border-radius: 999px; padding: 7px 14px; min-height: 34px; }
.link-btn:hover { border-color: var(--accent); }
.more { overflow: hidden; }
#more-toggle { width: 100%; border: 0; background: var(--sheet); color: var(--ink); display: flex;
  align-items: center; gap: 10px; padding: 12px 18px; text-align: left; }
#more-toggle:hover { background: var(--tint); }
#more-toggle .title { font-size: 13px; font-weight: 800; flex: 1 1 auto; }
#more-toggle .chev { width: 16px; height: 16px; fill: none; stroke: var(--ink-3);
  stroke-width: 2.2; stroke-linecap: round; stroke-linejoin: round; transition: transform .15s; }
#more-toggle[aria-expanded="true"] .chev { transform: rotate(90deg); }
#more { border-top: 1px solid var(--rule-2); padding: 16px 18px 18px; display: flex;
  flex-direction: column; gap: 20px; }
#more[hidden] { display: none; }
.sub { margin: 0 0 10px; font-size: 11px; font-weight: 800; color: var(--ink-3);
  text-transform: uppercase; letter-spacing: .6px; }
.tl { margin: 0; padding: 0; list-style: none; }
.tl li { display: grid; grid-template-columns: 56px 12px minmax(0, 1fr); gap: 0 12px;
  align-items: start; padding: 6px 0; font-size: 14px; }
.tl .date { font-size: 13px; font-weight: 600; color: var(--ink-3); }
.tl .dot { width: 12px; height: 12px; border-radius: 50%; margin-top: 5px; background: var(--dash); }
.tl .small { display: block; font-size: 13px; color: var(--ink-3); }
.chip { font-size: 11px; font-weight: 800; text-transform: uppercase; letter-spacing: .6px;
  padding: 2px 8px; border-radius: 999px; background: var(--chip); margin-left: 4px; }
.facts { margin: 0; padding: 0; list-style: none; display: flex; flex-direction: column; gap: 8px;
  font-size: 13.5px; color: var(--ink-2); }
.facts b { color: var(--ink); }
.facts blockquote { margin: 6px 0 0; padding: 2px 0 2px 12px; border-left: 3px solid var(--rule-3);
  white-space: pre-wrap; overflow-wrap: anywhere; color: var(--ink); }
.saved-line { margin: 0; padding-top: 14px; border-top: 1px solid var(--rule-2); font-size: 13px;
  color: var(--ink-3); }
@media (max-width: 720px) {
  .est { grid-template-columns: minmax(0, 1fr) auto; gap: 8px 12px; }
  .est .bar { grid-column: 1 / -1; grid-row: 2; }
  .mistakes thead { display: none; }
  .mistakes, .mistakes tbody, .mistakes tr, .mistakes td, .mistakes th { display: block;
    width: auto; }
  .mistakes td { border-top: 0; padding: 4px 18px; }
  .mistakes tr:not(.group) { border-top: 1px solid var(--rule-2); padding: 6px 0; }
  .mistakes td[data-label]::before { content: attr(data-label); display: block; font-size: 11px;
    font-weight: 700; color: var(--ink-3); text-transform: uppercase; letter-spacing: .6px; }
  .mistakes td.pad { display: none; }
  .tl li { grid-template-columns: 48px 12px minmax(0, 1fr); }
  main.result { padding: 16px; }
  .res h1 { font-size: 26px; }
}
"""

CHEVRON = ('<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="m9 6 6 6-6 '
           '6"/></svg>')


def _pct(x: float) -> str:
    return f"{x:.0%}"


def _two(x: float) -> str:
    """Two decimals, never "-0.00"."""
    text = f"{x:.2f}"
    return "0.00" if text == "-0.00" else text


def _e(value) -> str:
    return escape("" if value is None else str(value))


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def counts(r: dict) -> dict:
    """From every mark: how many you passed and failed, and how many of each the judge got
    the other way ("strict": you passed, it failed; "easy": you failed, it passed)."""
    g = r.get("groups") or {}
    gp, gf = g.get("pass") or {}, g.get("fail") or {}
    return {"passed": r["labels"]["correct"], "failed": r["labels"]["wrong"],
            "strict": int(gf.get("correct") or 0),
            "easy": int(gp.get("labeled") or 0) - int(gp.get("correct") or 0)}


def _est(r: dict, key: str, c: dict) -> str:
    """One estimate row: "You passed 15 · too strict on 6", the bar, and "your judge also
    passed about 61% (could be 42% to 78%)"."""
    from judgekeeper.start_label import too_early

    did = "passed" if key == "tpr" else "failed"
    n = c[did]
    other, word, cls = (c["strict"], "too strict", "strict") if key == "tpr" else (
        c["easy"], "too easy", "easy")
    small = f'<small class="{cls}">{word} on {other}</small>' if other else ""
    value, interval = r.get(key), r.get(f"{key}_interval")
    weak = targets.side(interval) != "yes"
    if too_early(value, interval):
        shown, sub, bar = "too early to tell", "Mark more answers to see this number.", ""
        said = f"You {did} {n}: too early to tell."
    else:
        lo, hi = interval
        exact = targets.width_word(interval) == "exact"
        shown = _pct(value) if exact else f"about {_pct(value)}"
        sub = "exactly" if exact else f"could be {_pct(lo)} to {_pct(hi)}"
        bar = (f'<span class="band" style="left: {lo * 100:.1f}%; width: {(hi - lo) * 100:.1f}%">'
               f'</span><span class="fill" style="width: {value * 100:.1f}%"></span>')
        said = f"You {did} {n}: your judge also {did} {shown} ({sub})."
    return (f'<div class="est{" weak" if weak else ""}"><p class="sr">{_e(said)}</p>'
            f'<div class="est-label" aria-hidden="true">You {did} {n}{small}</div>'
            f'<div class="bar" aria-hidden="true">{bar}</div>'
            f'<div class="est-val" aria-hidden="true"><span class="also">your judge also {did}'
            f'</span><b>{_e(shown)}</b><span>{_e(sub)}</span></div></div>')


def _copy_row(command: str, ident: str) -> str:
    return (f'<div class="cmdrow"><code class="cmd" id="{ident}">{_e(command)}</code>'
            f'<button type="button" class="btn copy" data-copy="{ident}">Copy</button></div>')


def _eval_command(r: dict) -> str | None:
    """The command that runs the person's eval, when judgekeeper knows it."""
    judge = r.get("judge") or {}
    tool = judge.get("tool")
    if tool == "promptfoo":
        files = [f for f in judge.get("results_files") or [] if f.endswith(".json")]
        return f"promptfoo eval -o {files[0]}" if len(files) == 1 else "promptfoo eval"
    return EVAL_COMMANDS.get(tool)


def commands(r: dict) -> dict[str, str]:
    """The commands the page names, from the one that made the result (r["command"]: the path
    and the person's flags), as the terminal prints them: `mark` keeps every flag, `check` and
    `fix` the path only."""
    from judgekeeper.textio import program

    run = r.get("command") or program()
    flags = run[len(program()):].strip() if run.startswith(program()) else ""
    if flags == "start" or flags.startswith("start "):  # a result made before 1.0
        flags = flags[len("start"):].strip()
        run = " ".join(x for x in (program(), flags) if x)
    path = "" if not flags or flags.startswith("-") else flags.split(" --")[0]
    return {"run": run, "mark": " ".join(x for x in (program("mark"), flags) if x),
            "check": " ".join(x for x in (program("check"), path) if x),
            "fix": " ".join(x for x in (program("fix"), path) if x)}


def next_step(r: dict, fixing: dict | None) -> dict:
    """The one next step, chosen from the result: {"kind", "title", "text", "command"} (and
    "rule", "where", "eval" for a tested rule). Like the terminal's Next: line."""
    from judgekeeper.front import FIX_FROM
    from judgekeeper.start_label import all_labeled

    cmd = commands(r)
    mark = {"kind": "mark", "title": "Mark more answers", "command": cmd["mark"]}
    if all_labeled(r):  # nothing left to mark: more answers come from the eval
        mark = {"kind": "eval", "title": "Run your eval on more questions",
                "text": "Every saved answer is marked. Run your eval again for more answers, "
                        "then:", "command": cmd["run"]}
    if r["check"] == "too_few" or r.get("verdict_level") == "too_early":
        return {"text": "Your result needs more marks before it can say how often your judge "
                        "agrees with you.", **mark}
    tested = (fixing or {}).get("tested")
    if tested:
        return {"kind": "use", "title": "Use your tested rule", "rule": tested["rule"],
                "where": tested.get("where"), "eval": _eval_command(r),
                "command": cmd["check"]}
    if len((fixing or {}).get("mistakes") or []) >= FIX_FROM:
        return {"kind": "fix", "title": "Try a better rule",
                "text": "See where your judge goes wrong, and test a new rule on marks kept "
                        "aside.", "command": cmd["fix"]}
    if r.get("verdict_level") == "check":
        return {"text": "More marks make your numbers more precise.", **mark}
    return {"kind": "done", "title": "Nothing to do",
            "text": "When you change your judge or update your eval tool, check it again:",
            "command": cmd["check"]}


def _next_card(step: dict, back: str | None) -> str:
    if step["kind"] == "use":
        where = step.get("where")
        put = (f"Put it in <code>{_e(where[0])}</code>, line {_e(where[1])}" if where else
               "Put it where your eval keeps your judge's rule")
        run = (f'Run your eval: <code>{_e(step["eval"])}</code>' if step.get("eval") else
               "Run your eval")
        body = ('<p>Your new rule did better on your hidden marks. It is not in your eval '
                'yet.</p><ol class="steps">'
                f'<li><span>{put}:</span><pre class="rulebox" id="rule-text">{_e(step["rule"])}'
                '</pre><div class="cmdrow"><button type="button" class="btn copy" '
                'data-copy="rule-text">Copy</button></div></li>'
                f"<li><span>{run}</span></li>"
                f'<li><span>Check again:</span>{_copy_row(step["command"], "next-cmd")}</li></ol>')
    else:
        go = (f'<a class="btn" href="{_e(back)}">Mark more answers</a>'
              if back and step["kind"] == "mark" else "")
        body = (f'<p>{_e(step["text"])}</p><div class="mt">{go}'
                f'{"" if go else _copy_row(step["command"], "next-cmd")}</div>')
    return ('<aside class="card next" aria-labelledby="next-h"><div class="head">'
            '<span class="ic" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M5 12h14m-6-6 '
            '6 6-6 6"/></svg></span><span class="title">Next step</span></div>'
            f'<div class="body"><h2 id="next-h">{_e(step["title"])}</h2>{body}</div></aside>')


def _result_card(r: dict, c: dict, content: dict) -> str:
    from judgekeeper.check import _day

    n = c["passed"] + c["failed"]
    day = _day(r.get("made_at"))
    meta = _plural(n, "mark", "marks") + (f" · made on {day}" if day else "")
    if r["check"] == "too_few":
        rows = f'<p>{_e(content["sentences"][0])}</p>'
        foot = ""
    else:
        rows = f'<div class="ests">{_est(r, "tpr", c)}{_est(r, "tnr", c)}</div>'
        foot = f'<p class="foot">{_e(ESTIMATES.format(n=n))}</p>'
    title = r["verdict"]
    return ('<section class="card res" aria-labelledby="result-h"><div class="head">'
            '<span class="ic green" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M12 '
            '2.5 4 5.5v6c0 4.6 3.3 8.5 8 9.9 4.7-1.4 8-5.3 8-9.9v-6l-8-3Z"/><path d="m8.5 12.2 '
            '2.4 2.4 4.8-5"/></svg></span><span class="title">Your result</span>'
            f'<span class="meta">{_e(meta)}</span></div><div class="body">'
            f'<h1 id="result-h">{_e(title)}</h1>{rows}{foot}</div></section>')


def _mistake_rows(mistakes: list[dict]) -> tuple[str, int]:
    """The table body: "It passed, you failed" first, then "It failed, you passed"; rows after
    the first ROWS_SHOWN start hidden."""
    rows, k = [], 0
    for judge, cls, title in (("pass", "easy", "It passed, you failed"),
                              ("fail", "strict", "It failed, you passed")):
        side = [m for m in mistakes if m.get("judge") == judge]
        if not side:
            continue
        extra = ' class="group {cls} extra" hidden' if k >= ROWS_SHOWN else ' class="group {cls}"'
        rows.append(f'<tr{extra.format(cls=cls)}><th colspan="4" scope="rowgroup">'
                    f'<i aria-hidden="true"></i>{title} ({len(side)})</th></tr>')
        for m in side:
            hide = " extra" if k >= ROWS_SHOWN else ""
            rows.append(
                f'<tr class="{cls}-row{hide}"{" hidden" if hide else ""}>'
                f'<td data-label="Question"><button type="button" class="row-open" '
                f'aria-expanded="false">{CHEVRON}<span class="clip">{_e(m["question"])}'
                '</span></button></td>'
                f'<td data-label="Answer" class="ans"><span class="clip">{_e(m["answer"])}'
                '</span></td>'
                f'<td data-label="Judge\'s reason"><span class="clip why">'
                f'{_e(m.get("reason") or "No reason given")}</span></td><td class="pad"></td></tr>')
            k += 1
    return "".join(rows), k


def _wrong_card(c: dict, fixing: dict | None) -> str:
    """Where it goes wrong: the real pattern lines and the mistakes on the marks the person
    can see; the rest are among the hidden marks."""
    mistakes = (fixing or {}).get("mistakes") or []
    shown = len(mistakes)
    hidden = max(0, c["strict"] + c["easy"] - shown)
    if not shown and not hidden:
        return ""
    easy = sum(m.get("judge") == "pass" for m in mistakes)
    pills = []
    if easy:
        pills.append(f'<span class="pill easy">Too easy · {easy}</span>')
    if shown - easy:
        pills.append(f'<span class="pill strict">Too strict · {shown - easy}</span>')
    patterns = (fixing or {}).get("patterns") or []
    lines = []
    if hidden and shown:
        lines.append(f'<p class="seen">On the {_plural(shown, "answer", "answers")} you can '
                     "see:</p>")
    first = (f'<span class="pills">{"".join(pills)}</span>' if pills else "")
    if patterns:
        lines.append(f"<p>{first}<strong>{_e(patterns[0])}</strong> "
                     + " ".join(_e(x) for x in patterns[1:2]) + "</p>")
        lines += [f"<p>{_e(x)}</p>" for x in patterns[2:]]
    elif pills:
        lines.append(f"<p>{first}</p>")
    body, _ = _mistake_rows(mistakes)
    table = ""
    if body:
        table = ('<table class="mistakes" id="mistakes"><thead><tr><th scope="col">Question'
                 '</th><th scope="col">Answer</th><th scope="col">Judge\'s reason</th>'
                 f'<th class="pad"><span class="sr">Open</span></th></tr></thead><tbody>{body}'
                 "</tbody></table>")
    show_all = (f'<button type="button" class="link-btn" id="show-all" aria-expanded="false" '
                f'aria-controls="mistakes">Show all {shown} disagreements</button>'
                if shown > ROWS_SHOWN else "")
    rest = (_e(HIDDEN.format(n=hidden, are="is" if hidden == 1 else "are")) if hidden else "")
    bottom = (f'<div class="bottom">{show_all}<span>{rest}</span></div>'
              if show_all or rest else "")
    return ('<section class="card wrong" aria-labelledby="wrong-h"><div class="head">'
            '<span class="ic amber" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M12 9v4m0 '
            '4h.01M10.3 3.9 2.6 17.2A2 2 0 0 0 4.3 20h15.4a2 2 0 0 0 1.7-2.8L13.7 3.9a2 2 0 0 '
            '0-3.4 0Z"/></svg></span><h2 id="wrong-h">Where it goes wrong</h2></div>'
            f'<div class="lines">{"".join(lines)}</div>{table}{bottom}</section>')


def _warn_card(block: dict | None) -> str:
    """The judge check's findings (did the judge really judge?), amber."""
    if not block:
        return ""
    return (f'<section class="card warn" aria-label="{_e(block["title"])}"><div class="head">'
            '<span class="ic amber" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M12 9v4m0 '
            '4h.01"/><circle cx="12" cy="12" r="9"/></svg></span>'
            f'<h2>{_e(block["title"])}</h2></div><div class="body"><ul>'
            + "".join(f"<li>{_e(x)}</li>" for x in block["lines"]) + "</ul></div></section>")


def _history(rows: list[dict]) -> str:
    if not rows:
        return ""
    items = []
    for row in rows:
        what = row.get("changed") or "Checked your judge"
        tested = f" · {row['tested']}" if row.get("tested") and row["tested"] not in what else ""
        chip = f'<span class="chip">{_e(row["verdict"])}</span>' if row.get("verdict") else ""
        small = "".join(f'<span class="small">{_e(g)}</span>' for g in row.get("groups") or [])
        if row.get("exact") == "close copy":
            small += '<span class="small">Not an exact copy of your judge.</span>'
        items.append(f'<li><span class="date">{_e(row.get("date"))}</span>'
                     f'<span class="dot" aria-hidden="true"></span><div><span>{_e(what)}'
                     f"{_e(tested)} {chip}</span>{small}</div></li>")
    return f'<div><h3 class="sub">History</h3><ul class="tl">{"".join(items)}</ul></div>'


def _rate_fact(r: dict, key: str, c: dict) -> str:
    """TPR or TNR in Details, with what it means and the raw count beside the estimate."""
    from judgekeeper.start_label import too_early

    g = r.get("groups") or {}
    if key == "tpr":
        name, n = "TPR (true positive rate)", c["passed"]
        agree = c["passed"] - c["strict"]
        means = "Of the answers you passed, how many your judge also passed."
    else:
        name, n = "TNR (true negative rate)", c["failed"]
        agree = c["failed"] - c["easy"]
        means = "Of the answers you failed, how many your judge also failed."
    value, interval = r.get(key), r.get(f"{key}_interval")
    if g and not too_early(value, interval):
        lo, hi = interval
        shown = (f"about {_pct(value)} ({agree} of {n} {ADJUSTED}), could be {_pct(lo)} to "
                 f"{_pct(hi)}")
    else:
        shown = f"too early to tell ({agree} of {n} {ADJUSTED.split(',')[0]})"
    return f"<li><b>{name}: {_e(shown)}.</b> {_e(' '.join([means, *_notes(r, key)]))}</li>"


def _notes(r: dict, key: str) -> list[str]:
    """Under TPR or TNR: why its range is still wide when few answers are of that kind, and,
    when the marks include repeats, the most even a perfect judge could show (below 99%)."""
    from judgekeeper.start_label import BEST, FEW

    real = r.get("real_pass_rate")
    if r["check"] == "too_few" or real is None:
        return []
    out = []
    if targets.width_word(r.get(f"{key}_interval")) == "too_wide" and (
            (key == "tnr" and real > 0.5) or (key == "tpr" and real < 0.5)):
        out.append(FEW.format(kind="fail" if key == "tnr" else "pass"))
    repeats = r.get("repeats") or {}
    if repeats.get("of"):
        slip = targets.slip_rate(1 - repeats["same"] / repeats["of"])
        top = targets.best_possible(real, slip)[key]
        if top < 0.99:
            out.append(BEST.format(same=repeats["same"], of=repeats["of"], best=_pct(top)))
    return out


def _details(r: dict, c: dict, content: dict, back: str | None) -> str:

    facts = []
    if r["check"] != "too_few":
        kappa, (lo, hi) = r.get("kappa"), (r.get("kappa_interval") or (None, None))
        if kappa is not None:
            rng = f" (could be {_two(lo)} to {_two(hi)})" if lo is not None else ""
            facts.append(f"<li><b>Agreement beyond coincidence (kappa): {_two(kappa)}</b>{rng}. "
                         f"{_e(KAPPA_MEANS)}</li>")
        facts += [_rate_fact(r, "tpr", c), _rate_fact(r, "tnr", c)]
    if content.get("pass_rate"):
        facts.append("<li>" + "".join(f"<b>{_e(t)}</b>" if bold else _e(t)
                                      for t, bold in content["pass_rate"]) + "</li>")
    for line in [content.get("corrected"), *(content.get("made") or []), content.get("drop"),
                 content.get("drop_model"), *(content.get("picks") or [])]:
        if line:
            facts.append(f"<li>{_e(line)}</li>")
    judge = content["judge"]
    who = [f"<code>{_e(judge['model'])}</code>"]
    if judge.get("name"):
        who.append(f"({_e(judge['name'])})")
    facts.append("<li><b>Your judge:</b> " + " ".join(who)
                 + (f". {_e(judge['source'])}" if judge.get("source") else "")
                 + (f"<blockquote>{_e(judge['rule'])}</blockquote>" if judge.get("rule") else "")
                 + "</li>")
    if content.get("judge_check_quiet"):
        from judgekeeper.judge_check import TITLE

        facts.append(f"<li><b>{_e(TITLE)}</b> {_e(content['judge_check_quiet'])}</li>")
    cmd = commands(r)
    others = (f"<code>{_e(cmd['mark'])}</code> to mark more answers · "
              f"<code>{_e(cmd['check'])}</code> after you change your judge · "
              f"<code>{_e(cmd['fix'])}</code> to try a better rule")
    if back:
        others += f' · <a href="{_e(back)}">back to the marking page</a>'
    facts.append(f"<li><b>Other commands:</b> {others}</li>")
    return f'<div><h3 class="sub">Details</h3><ul class="facts">{"".join(facts)}</ul></div>'


def page(r: dict, content: dict, back: str | None = None, history: list[dict] | None = None,
         fixing: dict | None = None) -> str:
    """The result page. `r`: the result; `content`: its text (start_label.page_content);
    `back`: the link to the marking page while it runs (None in report.html); `history`: the
    History rows (check.report_rows); `fixing`: fix.report_section. The page carries its
    Content-Security-Policy in a meta tag, so the saved copy keeps it too."""
    from judgekeeper.front import tool_name

    c = counts(r)
    judge = r.get("judge") or {}
    tool = tool_name(judge.get("tool"), judge.get("results_files"))
    model = (r.get("fingerprint") or {}).get("model")
    left = look.meta(_e(model) if model else None, _e(tool) if tool else None)
    marks = (f'<span class="marks">Your marks: {c["passed"]} Pass · {c["failed"]} Fail</span>')
    step = next_step(r, fixing)
    more = (_history(history or []) + _details(r, c, content, back)
            + f'<p class="saved-line">{SAVED}</p>')
    meta = f'<meta http-equiv="Content-Security-Policy" content="{CSP}">\n'
    return (look.head("judgekeeper: your result", STYLE, "<script>", meta)
            + look.top(left, marks)
            + '<main class="result">'
            + f'<div class="row1">{_result_card(r, c, content)}{_next_card(step, back)}</div>'
            + _warn_card(content.get("judge_check"))
            + _wrong_card(c, fixing)
            + '<section class="card more"><button type="button" id="more-toggle" '
              'aria-expanded="false" aria-controls="more"><span class="ic" aria-hidden="true">'
              '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>'
              '</svg></span><span class="title">History and details</span>'
              '<svg class="chev" viewBox="0 0 24 24" aria-hidden="true"><path d="m9 6 6 6-6 6"/>'
              f'</svg></button><div id="more" hidden>{more}</div></section>'
            + f"</main>\n<script>{SCRIPT}</script>\n</body>\n</html>\n")
