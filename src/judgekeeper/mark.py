"""`judgekeeper mark`: where marking stands, and the one thing that fits.

| What is there                                  | What mark does                           | Exit |
|------------------------------------------------|------------------------------------------|------|
| something must be asked (several tools,        | the same finding as `judgekeeper`        | 3    |
| judges, a pass mark, an own format...)         | (front.py): a question and its Next:     |      |
| no marking started                             | prepares the pool and the queue, starts  | 0    |
|                                                | the page in the background, prints the   |      |
|                                                | link (output A)                          |      |
| marking started, under 15 Pass + 15 Fail       | starts the page again if it is closed,   | 0    |
|                                                | prints the link and the count (A)        |      |
| at least 15 Pass + 15 Fail                     | the result from the marks, saved and     | 0    |
|                                                | printed (output B); the link if the page |      |
|                                                | is still open                            |      |
| marks for other results (a new eval run,       | says so and asks "Start over with these  | 3    |
| another judge, other files), or labels.csv     | results?" (the question list, then       |      |
| from 0.2                                       | --yes); yes moves the old marks to       |      |
|                                                | previous-<date>/ and goes on             |      |
| the same answers, but the judge's rule or      | carries on; the result says which judge  | 0    |
| model changed since marking started            | it is about                              |      |
| the page could not start in the background     | says so in one line                      | 3    |

The page runs in its own process (background.py), so the command returns at once. `--wait`
serves it in this terminal instead, `--stop` closes it, `--new` starts over (asked first).
Marks made by judgekeeper 0.2 (labels.csv) are never used: they have no stamps.

Like `judgekeeper`, the output holds counts, names and paths, never an answer's or an input's
text, and ends with exactly one `Next:` line. The page's link holds its token: printing it is
how the person gets the page.
"""

from __future__ import annotations

import sys
import webbrowser
from datetime import UTC, datetime
from pathlib import Path

from judgekeeper import (
    __version__,
    background,
    front,
    marks,
    start,
    start_again,
    start_label,
    targets,
)
from judgekeeper.fingerprint import rule_hash
from judgekeeper.label import DEFAULT_PORT, make_server, open_page
from judgekeeper.start import EXIT_QUESTION, Stop
from judgekeeper.start_label import FOLDER, StartSession, Workspace, made_lines, shown_folder

EXIT_OK = 0
START_OVER = f"Start over with these results? Your old marks move to {FOLDER}/previous-<date>/."
OLD_MARKS = (f"{FOLDER}/labels.csv holds marks from judgekeeper 0.2. They have no time stamps, "
             "so this version does not use them.")
NEXT_A = ("give the person the link above and ask them to mark answers until the page says it "
          "has enough. When they say they are done, run `{command}` again.")
NEXT_B = ("nothing. Tell the person the result above. Marking more on the page narrows the "
          "ranges.")
COULD_NOT = ("ask the person to run {command} in their own terminal (it keeps the page open "
             "there).")
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

__all__ = ["made_lines", "page_server", "run"]


class MarkTalk(front.FrontTalk):
    """front.FrontTalk for `judgekeeper mark`: printed commands start `judgekeeper mark`, and
    repeat --new while it is asked about. A choice made at a terminal is repeated as its flag,
    so the page's own process makes the same one."""

    program = "judgekeeper mark"

    def __init__(self, yes: bool, path: str | Path, options: dict, new: bool):
        self.new = new
        super().__init__(yes=yes, path=path, options=options)

    def refresh(self) -> None:
        super().refresh()
        if self.new:
            self.flags = (*self.flags, "--new")

    def start_command(self) -> str:
        """`judgekeeper start` with this run's flags: the command a result keeps, from which
        `start` builds its next steps (--review, --fix)."""
        return " ".join(("judgekeeper start", *start.repeated_flags(self.path, **self.options)))

    def remember(self, flag: str, chosen: str, line: str | None = None) -> None:
        super().remember(flag, chosen, line)
        if flag in front.ASKED:
            self.set(front.ASKED[flag], chosen)


def run(path: str | Path = ".", tool: str | None = None, metric: str | None = None,
        experiment: str | None = None, tracking_uri: str | None = None,
        pass_if: str | None = None, label_map: str | None = None,
        judge_model: str | None = None, fields: str | None = None, yes: bool = False,
        port: int = DEFAULT_PORT, no_browser: bool = False, new: bool = False,
        wait: bool = False, stop: bool = False) -> int:
    """`judgekeeper mark`. Returns the exit code."""
    options = {"tool": tool, "metric": metric, "experiment": experiment,
               "tracking_uri": tracking_uri, "pass_if": pass_if, "label_map": label_map,
               "judge_model": judge_model, "fields": fields, "port": port,
               "no_browser": no_browser}
    talk = MarkTalk(yes=yes, path=path, options=options, new=new)
    talk.say(f"judgekeeper {__version__}")
    talk.say()
    try:
        if stop:
            return _stop(talk, Path(path))
        return _run(talk, Path(path), wait)
    except Stop as e:
        return front.EXIT_NEEDS_YOU if e.code == EXIT_QUESTION else e.code


def _link(text: str) -> None:
    """A line holding the page's link, printed whole: the token is how the person gets in."""
    print(text)
    sys.stdout.flush()


# The page --------------------------------------------------------------------------------

def page_server(ws: Workspace, port: int, command: str,
                start_command: str = "judgekeeper start"):
    """The page `mark` serves: marking, and the result (no review or fix). Every click is a
    stamped line in marks.jsonl. It holds the project's lock and stays open after the result,
    until /stop, Ctrl-C or 2 hours idle. `command` is how to come back to it; the result
    keeps `start_command`."""
    session = StartSession(ws)

    def result(session: StartSession, back: str) -> str:
        r = start_label.store_result(ws, session, start_command)
        return start_label.result_html(start_label._scrubbed(r), back, marking=command)

    return make_server(session, port, result=result,
                       page=start_label.page_template(ws.data(), command), lock=ws.dir,
                       stays=True)


def _page_args(talk: MarkTalk) -> list[str]:
    """The arguments the page's own process gets: the path and flags of this run (with the
    choices made at a terminal), --yes for the questions this run got past, and no browser."""
    path = front.answered(talk, saved=True)[0]
    args = [path]
    for name, flag in start.REPEATED:
        if talk.options.get(name) is not None:
            args += [flag, str(talk.options[name])]
    return [*args, "--port", str(talk.options["port"]), "--no-browser", "--yes"]


def _open_browser(talk: MarkTalk, url: str) -> None:
    """At a terminal the page opens in the browser too (not with --no-browser); never without
    one."""
    if start._interactive() and not talk.options["no_browser"]:
        webbrowser.open(url)


def _serve(server) -> None:
    try:
        server.serve()
    except KeyboardInterrupt:
        pass


# Running ---------------------------------------------------------------------------------

def _run(talk: MarkTalk, path: Path, wait: bool) -> int:
    found, mapped = front.find_found(talk, path)
    to_save = front._to_save(talk, found, mapped) if mapped is not None else None
    if not found.pool.answers:
        talk.ask_noted()
        talk.say("No answer has a clear Pass or Fail from your judge, so there is nothing to "
                 "mark.")
        raise talk.stop(EXIT_OK, "nothing. Tell the person their judge made no real decision "
                                 "on any answer; run judgekeeper again after their next eval "
                                 "run.")
    ws = Workspace(found.root)
    start_label.refuse_links(ws)
    why = _why_start_over(talk, ws, found)
    over = why is not None
    if over:
        for line in why:
            talk.say(line)
        over = talk.confirm(START_OVER, default=True, with_yes=True, hint="")
    talk.ask_noted()  # without a terminal, nothing is written or moved before the answers
    if to_save is not None:
        front._save(talk, found, to_save, made=True)
    if why is not None and not over:
        talk.say("Nothing was moved.")
        raise talk.stop(EXIT_OK, f"nothing. Your old marks stay in {FOLDER}/.")
    if over:
        if open_page(ws.dir):
            background.stop(ws.dir)
        start_again.move_to_previous(ws, talk.say)
    if not ws.start.is_file():
        front._write(found)  # judge.json and the free checks
        start_label.prepare(found, say=lambda line: None)
    counts = StartSession(ws).counts()
    if min(counts["correct"], counts["wrong"]) >= targets.ROUGH:
        return _result(talk, ws, found, wait)
    return _page(talk, ws, counts, wait)


def _why_start_over(talk: MarkTalk, ws: Workspace, found: start.Found) -> list[str] | None:
    """Why the marks saved in .judgekeeper/ can't be used for these results, in lines; [] for
    --new on marks that could be; None when marking can go on."""
    if ws.labels.is_file():
        return [OLD_MARKS]
    if not ws.start.is_file():
        return None
    try:
        data = ws.data()
        saved = {q["id"]: q["group"] for q in data["queue"]}
        tool, metric, judge = data["tool"], data["metric"], data["judge"]
    except (OSError, ValueError, KeyError, TypeError):
        return [f"judgekeeper can't read {FOLDER}/start.json, so the marks there can't be used."]
    files = list(data.get("results_files") or [])
    if (found.tool, found.metric) != (tool, metric):
        why = f"they are of the judge {judge} ({tool}), and these results are of {found.judge}"
    elif files != list(found.used):
        why = (f"they are of {', '.join(files) or 'other results'}, and the newest results "
               f"are {', '.join(found.used)}")
    elif saved != {a.id: a.verdict for a in found.pool.answers}:
        why = ("your eval ran again since marking started: the answers or your judge's "
               "verdicts changed")
    else:
        return [] if talk.new else None
    return [f"Your marks are for other results: {why}."]


def _page(talk: MarkTalk, ws: Workspace, counts: dict, wait: bool) -> int:
    """Output A: the page's link (started now unless it is open) and the count so far."""
    url, server = open_page(ws.dir), None
    if url is None and wait:
        server = page_server(ws, talk.options["port"], talk.command(), talk.start_command())
        url = server.url
    elif url is None:
        url = background.start(ws.dir, _page_args(talk))
        if url is None:
            talk.say(f"The marking page could not start in the background (what went wrong is "
                     f"in {shown_folder(ws)}/{background.LOG}).")
            raise talk.stop(EXIT_QUESTION, COULD_NOT.format(command=talk.command("--wait")))
    _open_browser(talk, url)
    _link(f"Marking page: {url}")
    talk.say("It shows one answer at a time. Your judge's verdict is hidden.")
    n = counts["correct"] + counts["wrong"]
    talk.say(f"Marked so far: {n} ({counts['correct']} Pass, {counts['wrong']} Fail). A first "
             f"result needs {targets.ROUGH} Pass and {targets.ROUGH} Fail.")
    if server is not None:
        talk.say("The page stays open while this runs. To stop it: Ctrl-C.")
    talk.say()
    talk.say("Next: " + NEXT_A.format(command=talk.command()))
    if server is not None:
        _serve(server)
    return EXIT_OK


def _pct(x: float) -> str:
    return f"{x:.0%}"


def _rate(said: str, did: str, value, interval) -> str:
    start_words = f"Of the answers you {said}, your judge {did}"
    if value is None:
        return f"{start_words}: not known yet."
    lo, hi = interval or (None, None)
    if lo is None or hi is None:
        return f"{start_words} {_pct(value)}."
    if hi - lo <= 1e-12:
        return f"{start_words} {_pct(value)} (exactly)."
    return f"{start_words} {_pct(value)} (range {_pct(lo)} to {_pct(hi)})."


def verdict_line(r: dict) -> str:
    """The one line on how good the judge is: which way it goes wrong, when it is not good
    enough and leans one way."""
    tpr, tnr = r["tpr"], r["tnr"]
    if r["verdict_level"] == "not_gate" and None not in (tpr, tnr) and tpr != tnr:
        return ("Your judge passes too many answers you failed." if tnr < tpr
                else "Your judge fails too many answers you passed.")
    return r["verdict"]


def _which_judge(ws: Workspace, found: start.Found) -> str | None:
    """When the judge's rule or model changed since marking started: which judge the result
    is about, as it was then."""
    data = ws.data()
    same_rule = rule_hash(data.get("rule")) == rule_hash(found.rule)
    if same_rule and not start_again.judge_change(data["fingerprint"], found.fingerprint):
        return None
    head = marks.read(ws.marks).header or {}
    judge = head.get("judge") or start_label.judge_of(data)
    try:
        made = datetime.strptime(head.get("created_at") or data.get("started_at") or "",
                                 "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC).astimezone()
        day = f" on {made.day} {MONTHS[made.month - 1]}"
    except ValueError:
        day = ""
    model = judge.get("model") or "model not named"
    rule = judge.get("rule_hash")
    rule = f"rule hash {rule.removeprefix('sha256:')[:4]}" if rule else "rule not known"
    return f"This result is about your judge as it was{day}: {model}, {rule}."


def _result(talk: MarkTalk, ws: Workspace, found: start.Found, wait: bool) -> int:
    """Output B: the result from the marks, saved; the page's link while it is open."""
    session = StartSession(ws)
    r = start_label.store_result(ws, session, talk.start_command())
    made = r.get("made") or marks.made(marks.read(ws.marks), ids=set(session.by_id))
    for line in made_lines(made):
        talk.say(line)
    talk.say()
    talk.say(_rate("passed", "passed", r["tpr"], r.get("tpr_interval")))
    talk.say(_rate("failed", "failed", r["tnr"], r.get("tnr_interval")))
    kappa = "unknown" if r["kappa"] is None else f"{r['kappa']:.2f}"
    talk.say(f"Kappa (agreement beyond chance): {kappa}.")
    talk.say(verdict_line(r))
    which = _which_judge(ws, found)
    if which:
        talk.say(which)
    talk.say()
    drop = targets.drop_line(r.get("smallest_drop", targets.smallest_drop(
        r["labels"]["correct"], r["labels"]["wrong"])))
    if drop:
        talk.say(drop)
    talk.say(f"Report: {shown_folder(ws)}/{ws.report_html.name}")
    url, server = open_page(ws.dir), None
    if url is None and wait:
        server = page_server(ws, talk.options["port"], talk.command(), talk.start_command())
        url = server.url
        _open_browser(talk, url)
    if url is not None:
        _link(f"The page is still open if they want to mark more: {url}")
    talk.say()
    talk.say("Next: " + NEXT_B)
    if server is not None:
        _serve(server)
    return EXIT_OK


def _stop(talk: MarkTalk, path: Path) -> int:
    """--stop: close the page open for this project."""
    if not path.exists():
        raise start.StartError(f"file or folder not found: {path}")
    ws = Workspace(start_again._project(path))
    if open_page(ws.dir) is None:
        talk.say("No marking page is open.")
        raise talk.stop(EXIT_OK, f"nothing. Run `{talk.command()}` to open it.")
    if not background.stop(ws.dir):
        talk.say("The marking page did not close.")
        raise talk.stop(EXIT_QUESTION, "ask the person to close it with Ctrl-C in the terminal "
                                       "it runs in; else it closes by itself after 2 hours "
                                       "without a click.")
    talk.say("Closed the marking page. Your marks are saved.")
    raise talk.stop(EXIT_OK, f"nothing. Run `{talk.command()}` to open it again.")
