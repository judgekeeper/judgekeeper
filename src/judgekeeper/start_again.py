"""Running `judgekeeper start` again: `.judgekeeper/` is read first, and what is saved there
decides what happens.

| What is saved                       | What start does                                        |
|-------------------------------------|--------------------------------------------------------|
| nothing                             | the full flow                                          |
| labeling not finished, no result    | asks to continue; yes reopens the page at the next     |
|                                     | answer, from the saved pool (no search)                |
| a result, and the judge's verdicts  | the menu: review the disagreements, label more (a new  |
| are the same as last time           | result replaces the old one, which goes to history/),  |
|                                     | ask the judge again (plan, a default-No question, run),|
|                                     | nothing; --review, --ask-again and --label-more answer |
| a result, and new verdicts from the | a re-check: the saved labels against the new verdicts, |
| same tool and judge name            | with the new pool's group sizes, next to the last one  |
| anything, with --new                | moves it all (except baseline.json) to                 |
|                                     | previous-<date>/ and starts fresh; deletes nothing     |

A re-check finds the labeled answers in the new results by exact input and output (and the
agent's steps, when the results keep them), and says when the judge or the app's version
changed since the last check. When fewer than 15 Correct or 15 Wrong of them came back, the
answers changed (the app writes different outputs now), so the old labels do not apply:
start offers to label the latest results instead, moving the old check to
previous-<date>/. Before a re-check replaces the
saved pool, the old start.json, pool files and labels are copied to history/check-<date>/.
After a re-check, at a terminal, the menu follows. `--review` reviews the saved result at once,
without looking for new results.
"""

from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path

from judgekeeper.fingerprint import utc_now
from judgekeeper.judgments import read_run
from judgekeeper.start_label import (
    CHECKS,
    FOLDER,
    ROUGH,
    StartSession,
    Workspace,
    compute,
    prepare,
    save_result,
)

KEPT = "baseline.json"  # set by `baseline set`, not part of a check
PREVIOUS = "previous-"


def _stamp() -> str:
    return utc_now().replace(":", "-")


def move_to_previous(ws: Workspace, say) -> Path | None:
    """Move everything in `.judgekeeper/` except baseline.json and earlier previous-<date>/
    folders into a new previous-<date>/ folder. Nothing is deleted."""
    if not ws.dir.is_dir():
        return None
    entries = [p for p in ws.dir.iterdir()
               if p.name != KEPT and not p.name.startswith(PREVIOUS)]
    if not entries:
        return None
    target = ws.dir / f"{PREVIOUS}{_stamp()}"
    n = 2
    while target.exists():
        target = ws.dir / f"{PREVIOUS}{_stamp()}-{n}"
        n += 1
    target.mkdir()
    for p in entries:
        p.replace(target / p.name)
    say(f"Moved your last check to {FOLDER}/{target.name}/. Nothing was deleted.")
    return target


def _labels(ws: Workspace) -> dict[str, str]:
    """{answer id: pass or fail} from labels.csv: the person's Correct and Wrong."""
    if not ws.labels.is_file():
        return {}
    from judgekeeper.table import sheet_id

    with ws.labels.open(encoding="utf-8", newline="") as f:
        return {sheet_id(row["id"]): row["human_label"] for row in csv.DictReader(f)
                if row.get("human_label") in ("pass", "fail")}


def _project(path: Path) -> Path:
    return path.resolve().parent if path.is_file() else path.resolve()


def run(path: Path, talk, options: dict, port: int, open_browser: bool, new: bool,
        then: str | None = None, again_options=None) -> int:
    """`then` answers the menu after a result: "review", "ask" or "label"."""
    from judgekeeper import start, start_review

    ws = Workspace(_project(path)) if path.exists() else None
    has_result = ws is not None and ws.result_json.is_file() and ws.start.is_file()
    if then == "review":
        if not has_result:
            talk.say("There is no result to review yet. Run judgekeeper start to label first.")
            return start.EXIT_USAGE
        return start_review.run(ws, talk, port, open_browser)
    if then == "ask":
        if not has_result:
            talk.say("There is no result to ask about yet. Run judgekeeper start to label "
                     "first.")
            return start.EXIT_USAGE
        return _ask_again(ws, talk, again_options)
    if then == "try" and not has_result:
        talk.say("There is no result yet to try a new judge on. Run judgekeeper start to label "
                 "first.")
        return start.EXIT_USAGE
    if ws is not None and new:
        move_to_previous(ws, talk.say)
    elif ws is not None and ws.start.is_file():
        if not ws.result_json.is_file():
            return _unfinished(ws, talk, port, open_browser)
        found = start.find_judge(path, talk=talk, prefer=ws.data()["metric"], **options)
        return _again(ws, found, talk, port, open_browser, then, again_options)
    found = start.find_judge(path, talk=talk, **options)
    return start.label_found(talk, found, port, open_browser)


def _serve(ws: Workspace, talk, port: int, open_browser: bool) -> int:
    from judgekeeper import start_label

    return start_label.serve_workspace(ws, port, open_browser, talk.say)


def _unfinished(ws: Workspace, talk, port: int, open_browser: bool) -> int:
    labels = list(_labels(ws).values())
    question = (f"You labeled {len(labels)} (Correct {labels.count('pass')}, Wrong "
                f"{labels.count('fail')}). Continue?")
    if not talk.confirm(question, default=True, with_yes=True,
                        hint=f"{question[:-len('Continue?')]}Continue labeling? Run judgekeeper "
                             "start --yes to continue, or judgekeeper start --new to start "
                             "over."):
        talk.say("To start over: judgekeeper start --new")
        return 0
    return _serve(ws, talk, port, open_browser)


def _saved_verdicts(ws: Workspace) -> dict[str, str]:
    _, records = read_run(ws.pool_judge)
    return {i: r["verdict"] for i, r in records.items()}


ASKED_NOTHING = "Your judge was not called; nothing was spent."


def _ask_again(ws: Workspace, talk, again_options) -> int:
    """The plan for asking the judge again; then, after a yes (or --allow-calls), the calls
    and the numbers."""
    from judgekeeper import again
    from judgekeeper.again import fresh

    options = again_options or again.AgainOptions()
    plan = again.make_plan(ws, options, talk=talk, dry=True)
    talk.say()
    for line in again.plan_lines(plan):
        talk.say(line)
    if plan.status == again.CANT:
        return 0
    talk.say()
    if not plan.key_ok:
        talk.say("Set the key, then run judgekeeper start --ask-again again.")
        return 0
    if not again.approve(plan, talk, options.allow_calls):
        talk.say(ASKED_NOTHING)
        return 0
    stop = downloaded(plan, talk, "--ask-again")
    if stop is not None:
        return stop
    folder_before = set((ws.dir / "again").iterdir()) if (ws.dir / "again").is_dir() else set()
    try:
        result = again.run_tool(ws, plan, talk)
    except fresh.AgainError as e:
        talk.say(str(e))
        _drop_new_folders(ws, folder_before)
        return 1
    except KeyboardInterrupt:
        talk.say()
        talk.say("Stopped. Nothing was saved.")
        _drop_new_folders(ws, folder_before, keep_files=False)
        return 130
    fresh.finish(ws, plan, result, talk)
    return 0


def downloaded(plan, talk, command: str) -> int | None:
    """When the plan's tool must be downloaded first (npx), ask (default No). None to go on,
    else the exit code."""
    from judgekeeper import start

    if not plan.download:
        return None
    version = plan.tool_version
    if not start._interactive():
        talk.say(f"promptfoo {version} is not installed here. Install it in this project "
                 f"(npm install --save-dev promptfoo@{version}), or run judgekeeper start "
                 f"{command} in a terminal to let judgekeeper fetch it with npx.")
        return start.EXIT_USAGE
    if not talk.confirm(f"promptfoo {version} is not installed here. Download it with npx "
                        f"--yes promptfoo@{version}?", default=False, with_yes=False,
                        hint="Download promptfoo?"):
        talk.say(ASKED_NOTHING)
        return 0
    return None


def _drop_new_folders(ws: Workspace, before: set, keep_files: bool = True) -> None:
    """Remove the again/<stamp>/ folder a run made, when it holds nothing (or, after Ctrl-C,
    only the tool's partial output)."""
    folder = ws.dir / "again"
    if not folder.is_dir():
        return
    for path in set(folder.iterdir()) - before:
        if not keep_files:
            for f in path.glob("*"):
                f.unlink()
        try:
            path.rmdir()
        except OSError:
            pass
    try:
        folder.rmdir()
    except OSError:
        pass


def _menu(ws: Workspace, talk, then: str | None, port: int, open_browser: bool,
          again_options=None, new=None) -> int:
    """What next after a result: try the new judge (when `new`, a new_judge.NewJudge),
    review the disagreements, ask the judge again, label more, or nothing."""
    from judgekeeper import again, new_judge, start, start_review

    last = json.loads(ws.result_json.read_text(encoding="utf-8"))
    labels = last.get("labels", {})
    talk.say()
    talk.say(f"Your last result ({last['made_at'][:10]}): {CHECKS[last['check']]} "
             f"({labels.get('correct', 0)} Correct, {labels.get('wrong', 0)} Wrong).")
    n = start_review.count(ws)
    options = []  # (answer, text, note, flag)
    if new is not None and then is None:
        options.append(("try", *new_judge.menu_text(ws, new, again_options),
                        "--try-new-judge"))
    if n:
        text = (f"Review the {n} answer{'' if n == 1 else 's'} where you and your judge "
                "disagree")
        options.append(("review", text, "(free)", "--review"))
    if then is None:
        plan = again.make_plan(ws, again_options, dry=False)
        options.append(("ask", *again.menu_text(plan), "--ask-again"))
    options += [("label", "Label more", "", "--label-more"),
                ("nothing", "Nothing for now", "", None)]
    if then is None:
        width = max(len(text) for _, text, _, _ in options)
        shown = [f"{text:<{width}}   {note}".rstrip() for _, text, note, _ in options]
        flags = [o for o in options if o[3]]
        hint = "\n".join(["What next? Run one of:"] + [
            f"  judgekeeper start {flag:<14} {text}{' ' + note if note else ''}"
            for _, text, note, flag in flags])
        talk.say()
        then = options[talk.choose("What next?", shown, hint, ask="Choose")][0]
    if then == "try":
        if new is None:
            talk.say(new_judge.NO_NEW)
            return start.EXIT_USAGE
        return new_judge.run(ws, new, talk, again_options, port, open_browser)
    if then == "review":
        return start_review.run(ws, talk, port, open_browser)
    if then == "ask":
        return _ask_again(ws, talk, again_options)
    if then == "label":
        return _serve(ws, talk, port, open_browser)
    return 0


def _again(ws: Workspace, found, talk, port: int, open_browser: bool,
           then: str | None = None, again_options=None) -> int:
    from judgekeeper import new_judge

    data = ws.data()
    last = json.loads(ws.result_json.read_text(encoding="utf-8"))
    new = None
    if found.tool != data["tool"] or (found.metric != data["metric"]
                                      and data["metric"] in found.metrics):
        return _another_judge(talk, data, found)
    if found.metric != data["metric"]:  # the judge's name changed
        if not _renamed(talk, data, found, then):
            return _another_judge(talk, data, found)
        new = new_judge.NewJudge(found, f"its name was {data['metric']}, now {found.metric}")
    else:
        change = judge_change(data["fingerprint"], found.fingerprint)
        if change:
            new = new_judge.NewJudge(found, change)
    if new is not None:
        talk.say()
        talk.say(f"Your judge changed since your last check: {new.change}.")
        return _menu(ws, talk, then, port, open_browser, again_options, new=new)
    if then == "try":
        talk.say(new_judge.NO_NEW)
        return 2
    if {a.id: a.verdict for a in found.pool.answers} == _saved_verdicts(ws):
        return _menu(ws, talk, then, port, open_browser, again_options)
    code = _recheck(ws, found, last, talk, port, open_browser)
    if code == 0 and ws.result_json.is_file() and ws.start.is_file() and (
            then is not None or start_interactive()):
        return _menu(ws, talk, then, port, open_browser, again_options)
    return code


def _another_judge(talk, data: dict, found) -> int:
    talk.say(f"Your last check was of the judge {data['judge']} ({data['tool']}). These "
             f"results are of {found.judge}.")
    talk.say(f"To check these results instead, run judgekeeper start --new: your last "
             f"check moves to {FOLDER}/{PREVIOUS}<date>/ and nothing is deleted.")
    return 0


def _renamed(talk, data: dict, found, then: str | None) -> bool:
    """Whether the judge in the newest results is the new version of the saved one, whose
    name is not there any more. `--try-new-judge` says yes; else it is asked."""
    if then == "try":
        return True
    question = f"Is {found.metric} the new version of your judge {data['metric']}?"
    return talk.confirm(question, default=True, with_yes=True,
                        hint=f"{question} Run judgekeeper start --try-new-judge to try it, or "
                             "judgekeeper start --new to check it as a new judge.")


def start_interactive() -> bool:
    from judgekeeper import start

    return start._interactive()


def judge_change(old: dict, new: dict) -> str | None:
    """What changed in the judge's identity, in words, or None."""
    parts = []

    def shown(value):
        return "not recorded" if value is None else value

    if old.get("model") != new.get("model"):
        parts.append(f"the model was {shown(old.get('model'))}, now {shown(new.get('model'))}")
    elif old.get("provider") != new.get("provider"):
        parts.append(f"the provider was {shown(old.get('provider'))}, now "
                     f"{shown(new.get('provider'))}")
    if old.get("prompt_hash") != new.get("prompt_hash"):
        parts.append("the prompt changed")
    if old.get("temperature") != new.get("temperature"):
        parts.append(f"the temperature was {shown(old.get('temperature'))}, now "
                     f"{shown(new.get('temperature'))}")
    return "; ".join(parts) or None


def app_change(saved: dict, now: str | None) -> str | None:
    """What changed in the app's version, in words, or None. A check saved before
    judgekeeper kept app versions has nothing to compare."""
    if "app_version" not in saved or saved["app_version"] == now:
        return None

    def shown(value):
        return "not recorded" if value is None else value

    return f"its version was {shown(saved['app_version'])}, now {shown(now)}"


def _share(value) -> str:
    return "an unknown share" if value is None else f"about {value:.0%}"


def _recheck(ws: Workspace, found, last: dict, talk, port: int, open_browser: bool) -> int:
    from judgekeeper import start

    labels = _labels(ws)
    pool = {a.id for a in found.pool.answers}
    back = {i: label for i, label in labels.items() if i in pool}
    talk.say()
    talk.say(f"{len(back)} of your {len(labels)} labeled answers are in your latest results "
             f"({found.results[0].date():%Y-%m-%d}).")
    changed = judge_change(ws.data()["fingerprint"], found.fingerprint)
    if changed:
        talk.say(f"Your judge changed since your last check: {changed}.")
    app = app_change(ws.data(), found.app_version)
    if app:
        talk.say(f"Your app changed since your last check: {app}.")
    kept = list(back.values())
    if min(kept.count("pass"), kept.count("fail")) < ROUGH and len(back) < len(labels):
        talk.say(f"Fewer than {ROUGH} Correct or {ROUGH} Wrong of them came back unchanged: "
                 "your app gives different answers now, so the old labels do not apply to "
                 "them.")
        if not talk.confirm("Label your latest results?", default=True, with_yes=True,
                            hint="Label your latest results? Run judgekeeper start --yes to "
                                 "label them."):
            return 0
        move_to_previous(ws, talk.say)
        return start.label_found(talk, found, port, open_browser)

    archive = ws.history / f"check-{_stamp()}"
    archive.mkdir(parents=True)
    for p in (ws.start, ws.pool, ws.pool_judge, ws.labels):
        if p.is_file():
            shutil.copy2(p, archive / p.name)
    ws.labels.unlink(missing_ok=True)
    prepare(found, talk.say)
    session = StartSession(ws)
    for item_id, label in back.items():
        session.by_id[item_id]["label"] = label
    session.write()

    now = compute(ws, session)
    talk.say()
    for key, marked, did in (("tpr", "Correct", "passed"), ("tnr", "Wrong", "failed")):
        talk.say(f"Of the answers you marked {marked}, your judge {did} {_share(last[key])} "
                 f"before and {_share(now[key])} now.")
    save_result(ws, session, talk.say)
    return 0
