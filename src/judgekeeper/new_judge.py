"""Try your new judge on your old marks.

The loop this serves: the review shows the judge's mistakes; the person changes the judge's
rule (or model) in their own tool and runs their eval once; now they want to know whether the
new judge is better, without marking everything again.

`start` finds the new judge in the newest results: the same tool, and a judge whose identity
(model, prompt, temperature) differs from the one saved in `.judgekeeper/start.json`, or whose
name changed and which the person confirms is the new version. Then, after the same plan and
default-No question as asking the judge again (`again`):

- the new judge is rebuilt from the newest results (a `View` of the workspace) and grades the
  answers the person already marked, never the new outputs; once, unless `--times`;
- both judges are shown against the same marks, side by side, weighted by the saved groups
  (that is how the answers were picked), with the warning that a judge changed after seeing
  mistakes on these answers will look better on them;
- then a confirmation check: answers from the newest results the person never marked, half
  from the new judge's passes and half from its fails, aiming at 10 Pass and 10 Fail.

When Fix your judge set answers aside for this result (fix.json), the new judge is also tested
on those first, as a change is there (start_fix.new_judge_test): how many it fixed and broke.

Saved in `.judgekeeper/new-judge-<date>/`: `new-judge.json` (the numbers), `new-judge-<n>.jsonl`
(one run file per time asked, every line with the full fingerprint), the tool's own output, and
`confirm/` (the confirmation check, a check of its own). `result.json` gains a `new_judge`
block; the main result stays the old judge's until `judgekeeper start --new`. Trying the same
new judge again asks nothing again: it shows the saved numbers and offers the confirmation.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path

from judgekeeper import weighted
from judgekeeper.fingerprint import utc_now
from judgekeeper.start_label import FOLDER, Workspace, say_opened

TITLE = "Try your new judge"
COMMAND = "--try-new-judge"
QUICK = 10
QUICK_STATUS = [(0, "Mark a few more new answers to see the result.", False),
                (QUICK, ("You can see the result now. Marking more answers narrows its "
                         "ranges."), True)]
WARNING = ("You changed your judge after seeing mistakes on these answers, so it will look "
           "better on them.")
CONFIRM = f"Mark {QUICK} Pass and {QUICK} Fail new answers to confirm?"
FAIR_TEST_FAILED = "Couldn't run the fair test on the answers kept aside."
NO_NEW = ("Your newest results hold the same judge as your last check, so there is no new "
          "judge to try.")


@dataclass
class NewJudge:
    found: object  # start.Found: the newest results and the new judge's pool
    change: str  # what changed, in words


class View:
    """A workspace seen through the newest results: the new judge's tool, files, name and
    fingerprint; everything else (the marked answers, the pool's groups) is the saved check's.
    `data()["saved"]` is the saved check's own start.json."""

    def __init__(self, ws: Workspace, found):
        self.ws, self.found = ws, found
        self.root, self.dir = ws.root, ws.dir

    def data(self) -> dict:
        saved = self.ws.data()
        f = self.found
        return {**saved, "tool": f.tool, "results_files": list(f.used), "metric": f.metric,
                "judge": f.judge, "fingerprint": f.fingerprint, "saved": saved}


# Before asking -------------------------------------------------------------------------------

def tried(ws: Workspace, new: NewJudge) -> dict | None:
    """The saved `new_judge` block when this same new judge was already tried, else None."""
    from judgekeeper.start_again import judge_change

    if not ws.result_json.is_file():
        return None
    block = json.loads(ws.result_json.read_text(encoding="utf-8")).get("new_judge")
    if not block or (block.get("tool"), block.get("metric")) != (new.found.tool,
                                                                 new.found.metric):
        return None
    if judge_change(block.get("found_fingerprint") or {}, new.found.fingerprint) is not None:
        return None
    return block if (ws.root / block["folder"]).is_dir() else None


def menu_text(ws: Workspace, new: NewJudge, opts) -> tuple[str, str]:
    """The menu's line for trying the new judge, and its note in brackets."""
    from judgekeeper import again

    n = len(again.labeled_answers(ws))
    text = f"Try your new judge on your {n} marked answer{'' if n == 1 else 's'}"
    block = tried(ws, new)
    if block:
        return text, f"(free: tried on {block['made_at'][:10]})"
    plan = again.make_plan(ws, opts, dry=False, new=View(ws, new.found))
    if plan.status == again.CANT:
        return text, f"(can't: {plan.short})"
    note = f"{plan.calls_note} " if plan.calls_note else ""
    return text, f"({note}{plan.calls:,} calls, {again.cost_words(plan)})"


# Asking --------------------------------------------------------------------------------------

def _folder(ws: Workspace) -> Path:
    stamp = utc_now().replace(":", "-")
    folder = ws.dir / f"new-judge-{stamp}"
    n = 2
    while folder.exists():
        folder = ws.dir / f"new-judge-{stamp}-{n}"
        n += 1
    return folder


def _drop(folder: Path, keep_files: bool) -> None:
    if not folder.is_dir():
        return
    if not keep_files:
        for f in folder.glob("*"):
            if f.is_file():
                f.unlink()
    try:
        folder.rmdir()
    except OSError:
        pass


def run(ws: Workspace, new: NewJudge, talk, opts, port: int, open_browser: bool) -> int:
    """The plan, the question, the calls, the numbers; then the confirmation offer."""
    from judgekeeper import again
    from judgekeeper.again.fresh import AgainError
    from judgekeeper.start_again import ASKED_NOTHING, downloaded

    opts = opts or again.AgainOptions()
    block = tried(ws, new)
    if block:
        talk.say()
        talk.say(f"You already tried this judge on {block['made_at'][:10]}; it is not asked "
                 "again.")
        talk.say()
        for line in lines(block):
            talk.say(line)
        return offer_confirmation(ws, new, block, talk, port, open_browser)
    view = View(ws, new.found)
    plan = again.make_plan(ws, opts, talk=talk, dry=True, new=view)
    talk.say()
    for line in again.plan_lines(plan, TITLE):
        talk.say(line)
    if plan.status == again.CANT:
        return 0
    talk.say()
    if not plan.key_ok:
        talk.say(f"Set the key, then run {talk.command(COMMAND)} again.")
        return 0
    if not again.approve(plan, talk, opts.allow_calls, COMMAND):
        talk.say(ASKED_NOTHING)
        return 0
    stop = downloaded(plan, talk, COMMAND)
    if stop is not None:
        return stop
    plan.folder = _folder(ws)
    try:
        fresh = again.run_tool(view, plan, talk)
    except AgainError as e:
        talk.say(str(e))
        _drop(plan.folder, keep_files=True)
        return 1
    except KeyboardInterrupt:
        talk.say()
        talk.say("Stopped. Nothing was saved.")
        _drop(plan.folder, keep_files=False)
        return 130
    block = finish(ws, view, plan, fresh, new)
    talk.say()
    for line in lines(block):
        talk.say(line)
    return offer_confirmation(ws, new, block, talk, port, open_browser)


# The numbers ---------------------------------------------------------------------------------

def _old_numbers(r: dict) -> dict:
    """The old judge's numbers: from asking it again when that was done, else the result."""
    today = (r.get("again") or {}).get("today")
    if today and today.get("tpr") is not None or today and today.get("tnr") is not None:
        return {"source": "asked again", "date": (r["again"].get("made_at") or "")[:10],
                **{k: today.get(k) for k in ("tpr", "tpr_interval", "tnr", "tnr_interval")}}
    return {"source": "result", "date": (r.get("made_at") or "")[:10],
            **{k: r.get(k) for k in ("tpr", "tpr_interval", "tnr", "tnr_interval")}}


def finish(ws: Workspace, view: View, plan, fresh, new: NewJudge) -> dict:
    """Write the run files and new-judge.json, and put the block in result.json."""
    from judgekeeper.again import CLOSE
    from judgekeeper.again.fresh import write_files
    from judgekeeper.start_fix import new_judge_test
    from judgekeeper.start_label import _write_json

    metric = view.data()["metric"]
    write_files(ws, plan, fresh, prefix="new-judge", metric=metric)
    data = ws.data()
    counted = [a for a in plan.payload_answers() if a["id"] in fresh.verdicts]
    items = [(a["verdict"], a["label"], fresh.verdicts[a["id"]][0]) for a in counted]
    numbers = weighted.general(items, data["pool"]["pass"], data["pool"]["fail"])
    r = json.loads(ws.result_json.read_text(encoding="utf-8"))
    block = {
        "made_at": utc_now(), "folder": f"{FOLDER}/{fresh.folder.name}", "tool": plan.tool,
        "tool_version": plan.tool_version, "judge": plan.judge, "metric": metric,
        "change": new.change, "status": plan.status, "why": plan.why, "times": plan.times,
        "asked": plan.answers, "counted": len(counted),
        "not_counted": [{"id": i, "why": w} for i, w in fresh.not_counted.items()],
        "fingerprint": fresh.fingerprint, "found_fingerprint": new.found.fingerprint,
        "close": plan.status == CLOSE, "old": _old_numbers(r),
        "new": {k: numbers[k] for k in ("tpr", "tpr_interval", "tnr", "tnr_interval",
                                        "kappa", "interval_methods")},
        "confirmation": None, "notes": list(fresh.notes),
    }
    try:
        aside = new_judge_test(ws, {i: v[0] for i, v in fresh.verdicts.items()}, new.change)
    except Exception:  # noqa: BLE001 - the new judge's result stands without the fair test
        aside = {"kind": "error", "lines": [FAIR_TEST_FAILED]}
    if aside is not None:
        block["aside"] = aside
    _write_json(fresh.folder / "new-judge.json", block)
    save(ws, block)
    return block


def save(ws: Workspace, block: dict) -> None:
    """Put the block in result.json (an earlier one to history/) and redraw result.html."""
    from judgekeeper.start_label import _scrubbed, _write_json, result_html

    r = json.loads(ws.result_json.read_text(encoding="utf-8"))
    old = r.get("new_judge")
    if old and old.get("made_at") != block.get("made_at"):
        ws.history.mkdir(exist_ok=True)
        target = ws.history / f"new-judge-{old['made_at'].replace(':', '-')}.json"
        _write_json(target, old)
    r["new_judge"] = block
    _write_json(ws.result_json, r)
    ws.result_html.write_text(result_html(_scrubbed(r)), encoding="utf-8")


def _share(value, interval) -> str:
    if value is None:
        return "unknown"
    lo, hi = interval or (None, None)
    return (f"{value:.0%}" if lo is None or hi is None
            else f"{value:.0%} ({lo:.0%} to {hi:.0%})")


def lines(block: dict) -> list[str]:
    """Old judge and new judge side by side, the warning, and the confirmation's result."""
    from judgekeeper.again.fresh import NOT_COUNTED

    old, now = block["old"], block["new"]
    tail = " (close copy)" if block.get("close") else ""
    out = [*block["aside"]["lines"], ""] if block.get("aside") else []
    out.append(f"Your new judge vs your old judge, on your {block['counted']} marked answers:")
    width = len("When you said Pass, the judge also said Pass:")
    for key, said in (("tnr", "Fail"), ("tpr", "Pass")):
        label = f"When you said {said}, the judge also said {said}:".ljust(width)
        out.append(f"  {label}  old {_share(old[key], old[f'{key}_interval'])}  ->  "
                   f"new {_share(now[key], now[f'{key}_interval'])}{tail}")
    if old.get("source") == "asked again":
        out.append(f"The old numbers are from asking your old judge again on {old['date']}.")
    if block.get("close"):
        out.append(f"This was a close copy of your new judge: {block['why']}.")
    counts: dict[str, int] = {}
    for item in block.get("not_counted") or []:
        counts[item["why"]] = counts.get(item["why"], 0) + 1
    for why, k in counts.items():
        one, many = NOT_COUNTED.get(why, (why, why))
        out.append(f"1 answer was not counted: {one}." if k == 1 else
                   f"{k} answers were not counted: {many}.")
    out += list(block.get("notes") or [])
    out.append(WARNING)
    if block.get("confirmation"):
        out += [""] + confirmation_lines(block["confirmation"])
    return out


# The confirmation check ------------------------------------------------------------------

def offer_confirmation(ws: Workspace, new: NewJudge, block: dict, talk, port: int,
                       open_browser: bool) -> int:
    from judgekeeper import start

    if not start._interactive() and not talk.yes:
        talk.say(f"To confirm on new answers, mark {QUICK} Pass and {QUICK} Fail: "
                 f"{talk.command(COMMAND)}")
        return 0
    if not talk.confirm(CONFIRM, default=True, with_yes=True, hint=CONFIRM):
        return 0
    cws = confirmation_workspace(ws, new, block, talk)
    if cws is None:
        return 0
    return serve_confirmation(ws, cws, port, open_browser, talk.say, talk.command())


def confirmation_workspace(ws: Workspace, new: NewJudge, block: dict, talk) -> Workspace | None:
    """The confirmation check's own folder, with the answers of the newest results the person
    never marked (exact input and output), queued half from the new judge's passes and half
    from its fails."""
    from judgekeeper.again import labeled_answers
    from judgekeeper.start import Pool
    from judgekeeper.start_label import prepare

    marked = {a["id"] for a in labeled_answers(ws)}
    answers = [a for a in new.found.pool.answers if a.id not in marked]
    if not answers:
        talk.say("Your newest results hold no answers you have not marked yet. Run your eval "
                 "on new questions, then try again.")
        return None
    pool = Pool(answers=answers)
    for count, did, label in ((pool.n_pass, "passed", "Pass"), (pool.n_fail, "failed", "Fail")):
        if count < QUICK:
            talk.say(f"Your new judge {did} only {count} of the answers you have not marked, "
                     f"so you may not reach {QUICK} {label}.")
    cws = Workspace(ws.root, folder=ws.root / block["folder"] / "confirm")
    prepare(replace(new.found, pool=pool, check=None), say=lambda *a: None, ws=cws)
    return cws


def confirmation_page(cws: Workspace) -> str:
    from judgekeeper.start_page import label_page

    data = cws.data()
    return label_page(data.get("description"), data.get("rule"))


def quick_status(session) -> dict:
    """The line under the meters for the quick check: from the counts alone (QUICK_STATUS)."""
    counts = session.counts()
    least = min(counts["correct"], counts["wrong"])
    _, text, ready = [s for s in QUICK_STATUS if least >= s[0]][-1]
    return {"text": text, "ready": ready}


def serve_confirmation(ws: Workspace, cws: Workspace, port: int, open_browser: bool,
                       say, command: str = "judgekeeper start") -> int:
    """Serve the confirmation page until the last answer, Ctrl-C or 2 hours idle. `command`
    (start.Talk.command) is what the person runs to continue."""
    from judgekeeper.label import make_server
    from judgekeeper.start_label import StartSession, _scrubbed, result_html

    session = StartSession(cws, status=quick_status)
    made: list[bool] = []

    def result(session, back):
        r = finish_confirmation(ws, cws, session, say)
        done = session.summary()["done"]
        made.append(done)
        return result_html(_scrubbed(r), None if done else back)

    server = make_server(session, port, result=result, page=confirmation_page(cws))
    say_opened(server.url, open_browser, say, command, f" {COMMAND}")
    try:
        server.serve()
    except KeyboardInterrupt:
        pass
    summary = session.summary()
    if summary["done"] and not any(made) or not summary["done"] and summary["n_labeled"]:
        finish_confirmation(ws, cws, session, say)
    return 0


def finish_confirmation(ws: Workspace, cws: Workspace, session, say) -> dict:
    """The confirmation's result: saved in confirm/ and in the main result's new_judge block,
    and said. Returns the main result."""
    from judgekeeper.start_label import _scrubbed, _write_json, compute, result_html

    r = compute(cws, session)
    least = min(r["labels"]["correct"], r["labels"]["wrong"])
    confirmation = {"made_at": r["made_at"], "labels": r["labels"],
                    "check": "quick" if least >= QUICK else "too_few",
                    **{k: r[k] for k in ("tpr", "tpr_interval", "tnr", "tnr_interval", "kappa")}}
    _write_json(cws.result_json, {**r, "check": confirmation["check"],
                                  "confirmation": confirmation})
    main = json.loads(ws.result_json.read_text(encoding="utf-8"))
    block = dict(main["new_judge"], confirmation=confirmation)
    _write_json(ws.root / block["folder"] / "new-judge.json", block)
    save(ws, block)
    main["new_judge"] = block
    cws.result_html.write_text(result_html(_scrubbed(main)), encoding="utf-8")
    say("")
    for line in confirmation_lines(confirmation):
        say(line)
    return main


def confirmation_lines(c: dict) -> list[str]:
    n = c["labels"]["correct"] + c["labels"]["wrong"]
    check = ("quick check" if c["check"] == "quick" else
             f"fewer than {QUICK} Pass or {QUICK} Fail: the ranges are very wide")
    return [f"On {n} new answers you marked ({check}):",
            (f"  When you said Fail, your new judge also said Fail about "
             f"{_share(c['tnr'], c['tnr_interval'])} of the time."),
            (f"  When you said Pass, it also said Pass about "
             f"{_share(c['tpr'], c['tpr_interval'])} of the time.")]


__all__ = ["NO_NEW", "NewJudge", "View", "confirmation_page", "finish_confirmation", "lines",
           "menu_text", "run", "serve_confirmation", "tried"]
