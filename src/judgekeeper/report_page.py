"""The result page: what the marking page shows at /result, and `.judgekeeper/report.html`.

One self-contained page (look.py: nothing loaded from anywhere else); every string in it is
escaped. Its two scripts (the theme, read first; the switch, "Show all" and Copy) are fixed
text: the page's Content-Security-Policy lets exactly those run (by their hashes) and nothing
else, both when it is served and in the saved copy, which opens with no server.

One column, top to bottom: the verdict, the counts, the disagreements (the marks the person
can see), how many more are kept aside (the hidden marks: fix.py keeps those to test a new
rule fairly), More details (the estimates), and Fix it. Which of these show depends on the
result's level (targets.level):

| level                 | headline                          | shown                                |
|-----------------------|-----------------------------------|--------------------------------------|
| gate                  | Your judge is good enough to use. | all but Fix it                       |
| not_gate              | Your judge needs work.            | all                                  |
| check                 | Too early to tell.                | all but Fix it (it has real numbers) |
| too_early, no result  | Too early to tell.                | the counts only                      |
"""

from __future__ import annotations

from html import escape

from judgekeeper import look, targets
from judgekeeper.start_label import EARLY, GOOD, MARK_MORE, NEEDS

ROWS_SHOWN = 3  # disagreements shown in a group before "Show all"
KAPPA_MEANS = ("Kappa is agreement beyond coincidence. 0 means no better than coincidence, 1 "
               "means perfect agreement.")
STATES = {"gate": ("good", GOOD), "not_gate": ("needs", NEEDS), "check": ("plain", EARLY),
          "too_early": ("plain", EARLY), None: ("plain", EARLY)}
TICK = ('<svg viewBox="0 0 16 16" aria-hidden="true" focusable="false">'
        '<path d="M3 8.5l3.2 3.2L13 5"/></svg>')

# The page's script: fixed text, so its hash can be in the Content-Security-Policy.
SCRIPT = look.THEME_SWITCH + """
  (function () {
    Array.prototype.forEach.call(document.querySelectorAll(".more"), function (b) {
      b.addEventListener("click", function () {
        var open = b.getAttribute("aria-expanded") !== "true";
        b.setAttribute("aria-expanded", String(open));
        var table = document.getElementById(b.getAttribute("aria-controls"));
        Array.prototype.forEach.call(table.querySelectorAll("tr.extra"), function (row) {
          row.hidden = !open; });
        b.textContent = open ? "Show fewer" : "Show all";
      });
    });
    var copy = document.getElementById("copy"), timer;
    if (!copy) { return; }
    copy.addEventListener("click", function () {
      var text = document.getElementById(copy.getAttribute("data-copy")).textContent;
      function done(ok) {
        if (ok) { copy.innerHTML = '__TICK__Copied'; } else { copy.textContent = "Copy failed"; }
        copy.classList.toggle("done", ok);
        clearTimeout(timer);
        timer = setTimeout(function () {
          copy.textContent = "Copy"; copy.classList.toggle("done", false); }, 1500);
      }
      try { navigator.clipboard.writeText(text).then(function () { done(true); },
                                                     function () { done(false); }); }
      catch (e) { done(false); }
    });
  })();
""".replace("__TICK__", TICK)
CSP = ("default-src 'none'; script-src " + look.script_hash(look.THEME_FIRST) + " "
       + look.script_hash(SCRIPT) + "; style-src 'unsafe-inline'; font-src data:; "
       "img-src 'none'; base-uri 'none'; form-action 'none'")

STYLE = """
:root { --gutter: 32px; }
table { border-collapse: collapse; width: 100%; }
.mono { font-family: var(--mono); white-space: nowrap; }
.band { padding-left: var(--gutter); padding-right: var(--gutter); }
.verdict { padding-top: 88px; padding-bottom: 72px; text-align: center; }
.verdict h1 { margin: 0 auto; font-size: clamp(34px, 4vw, 56px); line-height: 1.1;
  letter-spacing: -.02em; font-weight: 800; max-width: 20ch; }
.verdict h1.needs { color: var(--amber); }
.verdict h1.good { color: var(--green); }
.verdict h1.plain { color: var(--text); }
.lead { margin: 20px auto 0; font-size: 20px; line-height: 1.4; color: var(--muted); }
.lead b { font-family: var(--mono); font-weight: 400; font-size: 18px; color: var(--text); }
.lead a { color: var(--text); text-decoration: underline; text-underline-offset: 3px; }
.lead code { font-size: 18px; color: var(--text); }
.counts { border-top: 1px solid var(--line); border-bottom: 1px solid var(--line); display: grid; grid-template-columns: 1fr 1fr; }
.counts p { margin: 0; padding: 32px var(--gutter); font-size: 19px; line-height: 1.4; font-weight: 500; }
.counts p + p { border-left: 1px solid var(--line); }
.left-out { margin: 16px 0 0; font-size: 15px; color: var(--muted); }
.group { padding-top: 64px; }
.gh { display: flex; align-items: baseline; justify-content: space-between; gap: 24px; }
.gh h2 { margin: 0; font-size: 24px; font-weight: 800; letter-spacing: -.01em; color: var(--amber); }
.more { font-size: 14px; color: var(--text); text-decoration: underline;
  text-underline-offset: 3px; white-space: nowrap; }
.tbl { margin-top: 32px; table-layout: fixed; }
.tbl col.c1 { width: 26%; } .tbl col.c2 { width: 48%; } .tbl col.c3 { width: 26%; }
.tbl th, .panel th { font-family: var(--mono); font-weight: 400; font-size: 12px;
  letter-spacing: .06em; text-transform: uppercase; color: var(--muted); text-align: left;
  border-bottom: 1px solid var(--line); }
.tbl th { padding: 0 32px 14px 0; }
.tbl td { font-size: 17px; line-height: 1.55; padding: 24px 32px 24px 0; vertical-align: top;
  border-bottom: 1px solid var(--line); white-space: pre-wrap; overflow-wrap: anywhere; }
.tbl th:last-child, .tbl td:last-child { padding-right: 0; }
.tbl td:last-child { color: var(--muted); }
.note { margin: 16px 0 0; font-size: 13px; color: var(--muted); text-align: left; }
.details { padding-top: 64px; }
.details h2, .fix h2 { margin: 0; font-size: 24px; font-weight: 800; letter-spacing: -.01em; }
.panel { margin-top: 32px; table-layout: fixed; }
.panel caption { text-align: left; font-size: 13px; color: var(--muted); padding: 0 0 12px; }
.panel col.d1 { width: 48%; } .panel col.d2 { width: 26%; } .panel col.d3 { width: 26%; }
.panel th { padding: 0 24px 10px 0; }
.panel thead td { border-bottom: 1px solid var(--line); }
.panel td { font-size: 17px; padding: 20px 32px 20px 0; border-bottom: 1px solid var(--line);
  vertical-align: top; }
.panel td + td { font-family: var(--mono); font-size: 15px; white-space: nowrap; }
.kappa { position: relative; display: inline-block; }
.kappa .i { font-size: 15px; color: var(--muted); margin-left: 6px; line-height: 1; }
.kappa .tip { position: absolute; left: 0; bottom: calc(100% + 8px); width: min(320px, 80vw);
  background: var(--bg); border: 1px solid var(--line); padding: 10px 12px; font-size: 13px;
  line-height: 1.45; color: var(--text); white-space: normal; display: none; z-index: 2; }
.kappa:hover .tip, .kappa:focus-within .tip { display: block; }
.fix { margin-top: 64px; border-top: 1px solid var(--line); padding-top: 48px; padding-bottom: 72px; }
.fix-in { display: grid; grid-template-columns: 1fr auto; gap: 24px 48px; align-items: center; }
.fix-in h2, .fix-in p { grid-column: 1; }
.fix-in .cmd { grid-column: 2; grid-row: 1 / span 2; }
.fix p { margin: 0; font-size: 17px; line-height: 1.6; color: var(--muted); max-width: 64ch; }
.fix p code { font-size: 15px; color: var(--text); }
.cmd { display: inline-grid; grid-template-columns: auto auto; border: 1px solid var(--line);
  min-width: min(360px, 100%); }
.cmd code { font-size: 17px; padding: 16px 24px; align-self: center; }
.cmd button { font-size: 13px; padding: 0 18px; border-left: 1px solid var(--line); color: var(--muted); min-width: 92px; }
.cmd button:hover, .cmd button.done { color: var(--text); }
.cmd button.done svg { width: 14px; height: 14px; vertical-align: -2px; margin-right: 6px;
  fill: none; stroke: currentColor; stroke-width: 2; stroke-linecap: round;
  stroke-linejoin: round; }
@media (max-width: 720px) {
  :root { --gutter: 16px; }
  .verdict { padding-top: 72px; padding-bottom: 64px; }
  .lead { font-size: 17px; }
  .counts { grid-template-columns: 1fr; }
  .counts p { font-size: 18px; padding: 24px var(--gutter); }
  .counts p + p { border-left: 0; border-top: 1px solid var(--line); }
  .gh { flex-direction: column; gap: 10px; }
  .gh h2 { font-size: 20px; }
  .tbl thead, .panel thead { display: none; }
  .tbl, .tbl tbody, .tbl tr, .tbl td { display: block; }
  .tbl tr { padding: 18px 0; border-bottom: 1px solid var(--line); }
  .tbl td { border: 0; padding: 0; font-size: 16px; }
  .tbl td + td { margin-top: 10px; }
  .tbl td::before { content: attr(data-label); display: block; font-family: var(--mono);
    font-size: 11px; letter-spacing: .06em; text-transform: uppercase; color: var(--muted);
    margin-bottom: 3px; }
  .panel, .panel tbody, .panel tr, .panel td, .panel caption { display: block; }
  .panel tr { padding: 12px 0; border-bottom: 1px solid var(--line); }
  .panel td { border: 0; padding: 0; }
  .panel td + td { margin-top: 4px; }
  .panel td[data-label]::before { content: attr(data-label) " "; font-family: var(--sans);
    color: var(--muted); font-size: 13px; }
  .fix { margin-top: 48px; padding-top: 40px; padding-bottom: 56px; }
  .fix-in { grid-template-columns: 1fr; }
  .fix-in .cmd { grid-column: 1; grid-row: auto; }
  .cmd { display: grid; grid-template-columns: 1fr auto; width: 100%; }
}
"""


def _pct(x: float) -> str:
    return f"{x:.0%}"


def _two(x: float) -> str:
    """Two decimals with a real minus sign, never "−0.00"."""
    text = f"{x:.2f}"
    return "0.00" if text == "-0.00" else text.replace("-", "−")


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


def _verdict(r: dict, c: dict, back: str | None) -> str:
    """The headline, and under it the disagreements, or (too early) how to mark more: a link
    to the marking page while it runs, the command in the saved copy."""
    level = r.get("verdict_level") if r["check"] != "too_few" else None
    cls, headline = STATES.get(level, STATES[None])
    if cls != "plain":
        lead = (f"You and your judge disagreed on <b>{c['strict'] + c['easy']}</b> of "
                f"<b>{c['passed'] + c['failed']}</b> answers.")
    elif back:
        lead = f'<a href="{_e(back)}">{_e(MARK_MORE)}</a>'
    else:
        lead = f"Run <code>{_e(commands(r)['mark'])}</code> to mark more answers."
    return (f'<section class="verdict band" aria-labelledby="verdict-h"><h1 id="verdict-h" '
            f'class="{cls}">{_e(headline)}</h1><p class="lead">{lead}</p></section>')


def count_line(did: str, n: int, judge_passed: int, judge_failed: int) -> str:
    """"You passed 15 answers. Of those, your judge passed 7 and failed 8.", numbers in mono."""
    def mono(x: int) -> str:
        return f'<span class="mono">{x}</span>'
    return (f"You {did} {mono(n)} {'answer' if n == 1 else 'answers'}. Of those, your judge "
            f"passed {mono(judge_passed)} and failed {mono(judge_failed)}.")


def _counts(r: dict, c: dict) -> str:
    """The two counts, and the answers the judge gave no Pass or Fail on (left out), if any."""
    from judgekeeper.judge_check import NO_DECISION

    row = ('<div class="counts">'
           f'<p>{count_line("passed", c["passed"], c["passed"] - c["strict"], c["strict"])}</p>'
           f'<p>{count_line("failed", c["failed"], c["easy"], c["failed"] - c["easy"])}</p>'
           "</div>")
    block = r.get("judge_check") or {}
    none = sum(int(block.get(k) or 0) for k in NO_DECISION)
    if none:
        row += (f'<p class="left-out band">Your judge gave no Pass or Fail on '
                f'{_plural(none, "answer", "answers")}. '
                f'{"It is" if none == 1 else "They are"} left out.</p>')
    return row


def _group(key: str, said: str, judge: str, rows: list[dict]) -> str:
    """One group of disagreements: its title, "Show all" past ROWS_SHOWN rows, the table."""
    why = f"Why your judge {judge} it"
    body = []
    for k, m in enumerate(rows):
        extra = ' class="extra" hidden' if k >= ROWS_SHOWN else ""
        body.append(f'<tr{extra}><td data-label="Question">{_e(m["question"])}</td>'
                    f'<td data-label="Answer">{_e(m["answer"])}</td>'
                    f'<td data-label="{why}">{_e(m.get("reason") or "No reason given")}</td>'
                    "</tr>")
    more = (f'<button type="button" class="more" aria-expanded="false" '
            f'aria-controls="t-{key}">Show all</button>' if len(rows) > ROWS_SHOWN else "")
    return (f'<section class="group band" aria-labelledby="g-{key}"><div class="gh">'
            f'<h2 id="g-{key}">{said} ({len(rows)})</h2>{more}</div>'
            f'<table class="tbl" id="t-{key}"><colgroup><col class="c1"><col class="c2">'
            '<col class="c3"></colgroup><thead><tr><th scope="col">Question</th>'
            f'<th scope="col">Answer</th><th scope="col">{why}</th></tr></thead>'
            f'<tbody>{"".join(body)}</tbody></table></section>')


def _groups(c: dict, fixing: dict | None) -> str:
    """The disagreements on the marks the person can see, in two groups, and how many more
    are among the hidden marks."""
    mistakes = (fixing or {}).get("mistakes") or []
    out = []
    for key, said, judge in (("easy", "You said Fail, your judge said Pass", "pass"),
                             ("strict", "You said Pass, your judge said Fail", "fail")):
        rows = [m for m in mistakes if m.get("judge") == judge]
        if rows:
            out.append(_group(key, said, "passed" if judge == "pass" else "failed", rows))
    hidden = max(0, c["strict"] + c["easy"] - len(mistakes))
    if hidden:
        out.append(f'<div class="band"><p class="note">* {hidden} more '
                   f'{"is" if hidden == 1 else "are"} kept aside to test your new rule '
                   "fairly.</p></div>")
    return "".join(out)


def estimate(value, interval) -> tuple[str, str]:
    """An estimate and its range for More details: "about 57%", "37% and 74%". Too early to
    tell while the range is too wide. A range of no width (a judge that passes or fails every
    answer) is exact, with no "about". Ends that round to the same percent are shown with one
    decimal, never as one point."""
    from judgekeeper.start_label import too_early

    if too_early(value, interval):
        return "too early to tell", "–"
    lo, hi = interval
    if targets.width_word(interval) == "exact":
        return _pct(value), f"{_pct(lo)} and {_pct(hi)}"
    if _pct(lo) == _pct(hi):
        return f"about {_pct(value)}", f"{lo:.1%} and {hi:.1%}"
    return f"about {_pct(value)}", f"{_pct(lo)} and {_pct(hi)}"


def _details(r: dict) -> str:
    """More details: how often the judge agrees with the person, estimated (weighted, with
    their ranges), and kappa."""
    rows = []
    for said, key in (("Pass", "tpr"), ("Fail", "tnr")):
        est, between = estimate(r.get(key), r.get(f"{key}_interval"))
        rows.append((f"When you say {said}, your judge also says {said}", est, between))
    kappa, (lo, hi) = r.get("kappa"), (r.get("kappa_interval") or (None, None))
    tip = ('<span class="kappa">Kappa<button type="button" class="i" aria-describedby='
           '"kappa-tip" aria-label="What kappa means">ⓘ</button><span class="tip" '
           f'role="tooltip" id="kappa-tip">{_e(KAPPA_MEANS)}</span></span>')
    body = "".join(f'<tr><td>{_e(name)}</td><td data-label="Estimate">{_e(est)}</td>'
                   f'<td data-label="Between">{_e(between)}</td></tr>'
                   for name, est, between in rows)
    body += (f'<tr><td>{tip}</td><td data-label="Estimate">'
             f'{_two(kappa) if kappa is not None else "–"}</td><td data-label="Between">'
             f'{f"{_two(lo)} and {_two(hi)}" if lo is not None else "–"}</td></tr>')
    return ('<section class="details band" aria-labelledby="details-h">'
            '<h2 id="details-h">More details</h2><table class="panel">'
            "<caption>How often your judge agrees with you (estimates)</caption>"
            '<colgroup><col class="d1"><col class="d2"><col class="d3"></colgroup>'
            '<thead><tr><td></td><th scope="col">Estimate</th><th scope="col">Between</th>'
            f"</tr></thead><tbody>{body}</tbody></table></section>")


def _fix(r: dict) -> str:
    """Fix it: the command that saves the clues and tests a new rule, with Copy."""
    fix = _e(commands(r)["fix"])
    return ('<section class="fix band" aria-labelledby="fix-h"><div class="fix-in">'
            '<h2 id="fix-h">Fix it</h2>'
            f"<p>In your project folder, open a terminal and run <code>{fix}</code>. It saves "
            "the clues and tells you where to write a better rule. Then run "
            f"<code>{fix}</code> again to test it.</p>"
            f'<div class="cmd"><code id="fix-cmd">{fix}</code><button type="button" '
            'class="copy" id="copy" data-copy="fix-cmd">Copy</button></div></div></section>')


def page(r: dict, back: str | None = None, fixing: dict | None = None) -> str:
    """The result page. `r`: the result; `back`: the link to the marking page while it runs
    (None in report.html); `fixing`: fix.report_section (the mistakes the person can see).
    The page carries its Content-Security-Policy in a meta tag, so the saved copy keeps it
    too."""
    from judgekeeper.front import tool_name

    c = counts(r)
    judge = r.get("judge") or {}
    tool = tool_name(judge.get("tool"), judge.get("results_files"))
    model = (r.get("fingerprint") or {}).get("model")
    left = look.meta(_e(model) if model else None, _e(tool) if tool else None)
    level = r.get("verdict_level") if r["check"] != "too_few" else None
    parts = [_verdict(r, c, back), _counts(r, c)]
    if level not in ("too_early", None):  # real numbers: the disagreements and the estimates
        parts += [_groups(c, fixing), _details(r)]
    if level == "not_gate":
        parts.append(_fix(r))
    meta = f'<meta http-equiv="Content-Security-Policy" content="{CSP}">\n'
    return (look.head("judgekeeper: your result", STYLE, "<script>", meta)
            + look.top(left, "") + '<main class="result">' + "".join(parts)
            + f"</main>\n<script>{SCRIPT}</script>\n</body>\n</html>\n")
