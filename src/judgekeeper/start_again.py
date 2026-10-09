"""Running `judgekeeper start` again: `.judgekeeper/` is read first, and what is saved there
decides what happens.

| What is saved                       | What start does                                        |
|-------------------------------------|--------------------------------------------------------|
| nothing                             | the full flow                                          |
| labeling not finished, no result    | asks to continue; yes reopens the page at the next     |
|                                     | answer, from the saved pool (no search)                |
| a result, and the judge's verdicts  | the menu: review the disagreements, fix your judge     |
| are the same as last time           | (once the review found something to fix), label more   |
|                                     | (a new result replaces the old one, which goes to      |
|                                     | history/), ask the judge again (plan, a default-No     |
|                                     | question, run), nothing; --review, --fix, --ask-again  |
|                                     | and --label-more answer                                |
| a result, and new verdicts from the | a re-check: the saved labels against the new verdicts, |
| same tool and judge name            | with the new pool's group sizes, next to the last one  |
| anything, with --new                | moves it all (except baseline.json and records/) to    |
|                                     | previous-<date>/ and starts fresh; deletes nothing     |

A re-check finds the labeled answers in the new results by exact input and output (and the
agent's steps, when the results keep them), and says when the judge or the app's version
changed since the last check. When fewer than 15 Correct or 15 Wrong of them came back, the
answers changed (the app writes different outputs now), so the old labels do not apply:
start offers to label the latest results instead, moving the old check to previous-<date>/.
Before a re-check replaces the saved pool, the old start.json, pool files, labels and judge
check files are copied to history/check-<date>/. After a re-check, at a terminal, the menu
follows. `--review` reviews the saved result at once, without looking for new results; `--fix`
likewise.
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

# Not part of a check: baseline.json (set by `baseline set`) and records/ (judgekeeper.record())
KEPT = ("baseline.json", "records")
PREVIOUS = "previous-"


def _stamp() -> str:
    return utc_now().replace(":", "-")


def move_to_previous(ws: Workspace, say) -> Path | None:
    """Move everything in `.judgekeeper/` except baseline.json, records/ and earlier
    previous-<date>/ folders into a new previous-<date>/ folder. Nothing is deleted."""
    if not ws.dir.is_dir():
        return None
    entries = [p for p in ws.dir.iterdir()
               if p.name not in KEPT and not p.name.startswith(PREVIOUS)]
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
    """The project folder: the folder of a results file or of an MLflow store given as the
    path, so .judgekeeper/ is never made inside an mlruns/ folder."""
    from judgekeeper import find

    if path.is_file() or find.is_mlflow_folder(path):
        return path.resolve().parent
    return path.resolve()


def run(path: Path, talk, options: dict, port: int, open_browser: bool, new: bool,
        then: str | None = None, again_options=None, test_pass_mark: bool = False) -> int:
    """`then` answers the menu after a result: "review", "fix", "ask", "try" or "label".
    `test_pass_mark` (with "fix") tests the pass mark in the terminal."""
    from judgekeeper import start, start_fix, start_review

    ws = Workspace(_project(path)) if path.exists() else None
    has_result = ws is not None and ws.result_json.is_file() and ws.start.is_file()
    if then in BEFORE and not has_result:
        return _no_result_yet(path, ws, talk, then, options.get("tool"))
    if then == "review":
        return start_review.run(ws, talk, port, open_browser)
    if then == "fix":
        return start_fix.run(ws, talk, port, open_browser, test_pass_mark)
    if then == "ask":
        return _ask_again(ws, talk, again_options)
    if ws is not None and new:
        move_to_previous(ws, talk.say)
    elif ws is not None and ws.start.is_file():
        if not ws.result_json.is_file():
            return _unfinished(ws, talk, port, open_browser)
        found = start.find_judge(path, talk=talk, prefer=ws.data()["metric"],
                                 store=ws.data().get("mlflow_store"), **options)
        return _again(ws, found, talk, port, open_browser, then, again_options)
    found = start.find_judge(path, talk=talk, **options)
    return start.label_found(talk, found, port, open_browser)


# Judges that run in the user's own code: asking them again needs --judge-command.
OWN_CODE = {"records": "Your judge runs in your own code",
            "mapped": "Your judge runs in your own code",
            "table": "Your results are a table"}


# `--review`, `--fix`, `--ask-again` and `--try-new-judge` before a result: (flag, why there
# is nothing to do yet, what the flag does once there are labels).
PLAN = "shows the plan (how many calls, the cost, the key's name) and asks before any call."
BEFORE = {
    "review": ("--review", "There is no result to review yet: a review needs your labels.",
               "opens the answers where you and your judge disagree, to look at again."),
    "fix": ("--fix", "There is no result yet to fix your judge with: it needs your labels.",
            ("shows what your judge gets wrong, once you have looked again at where you "
             "disagree. Free.")),
    "ask": ("--ask-again", ("There is no result to ask about yet: asking your judge again "
                            "needs your labels."), PLAN),
    "try": ("--try-new-judge", ("There is no result yet to try a new judge on: trying one "
                                "needs your labels."), PLAN),
}


def _no_result_yet(path: Path, ws: Workspace | None, talk, then: str, tool: str | None) -> int:
    """A menu flag before a result: the exact command that labels first (with --yes when no
    one can answer its question), and what the flag does after. Exit 2: not a question,
    there is nothing to do yet."""
    from judgekeeper import start

    flag, why, does = BEFORE[then]
    label = talk.command() if start._interactive() else talk.command("--yes")
    talk.say(f"{why} Label first: {label}")
    talk.say(f"Then {talk.command(flag)} {does}")
    if then != "ask":
        return start.EXIT_USAGE
    if ws is not None and ws.start.is_file():
        tool = ws.data()["tool"]
    else:
        tool = start.known_tool(path, tool)
    if tool in OWN_CODE:
        talk.say(f"{OWN_CODE[tool]}, so asking it again needs --judge-command: your judge as a "
                 "command that reads one answer as JSON on stdin and prints its verdict.")
    return start.EXIT_USAGE


def _serve(ws: Workspace, talk, port: int, open_browser: bool) -> int:
    from judgekeeper import start_label

    return start_label.serve_workspace(ws, port, open_browser, talk.say, talk.command())


def _unfinished(ws: Workspace, talk, port: int, open_browser: bool) -> int:
    data = ws.data()
    talk.say(f"Using {', '.join(data['results_files'])}: the judge passed "
             f"{data['pool']['pass']} and failed {data['pool']['fail']}.")
    labels = list(_labels(ws).values())
    question = (f"You labeled {len(labels)} (Correct {labels.count('pass')}, Wrong "
                f"{labels.count('fail')}). Continue?")
    if not talk.confirm(question, default=True, with_yes=True,
                        hint=f"{question[:-len('Continue?')]}Continue labeling? Run "
                             f"{talk.command('--yes')} to continue, or "
                             f"{talk.command('--new')} to start over."):
        talk.say(f"To start over: {talk.command('--new')}")
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
        talk.say(f"Set the key, then run {talk.command('--ask-again')} again.")
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
                 f"(npm install --save-dev promptfoo@{version}), or run "
                 f"{talk.command(command)} in a terminal to let judgekeeper fetch it with npx.")
        return start.EXIT_QUESTION
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
    review the disagreements, fix the judge, ask the judge again, label more, or nothing."""
    from judgekeeper import again, new_judge, start, start_fix, start_review

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
    if start_fix.ready(ws):
        options.append(("fix", "Fix your judge", "(free)", "--fix"))
    if then is None and _can_ask(ws, again_options):
        plan = again.make_plan(ws, again_options, dry=False)
        options.append(("ask", *again.menu_text(plan), "--ask-again"))
    nothing_left = last.get("left") == 0
    if not nothing_left:
        options.append(("label", "Label more", "", "--label-more"))
    options.append(("nothing", "Nothing for now", "", None))
    if then == "label" and nothing_left or then is None and len(options) == 1:
        talk.say(ALL_LABELED)
        return 0
    if then is None:
        width = max(len(text) for _, text, _, _ in options)
        shown = [f"{text:<{width}}   {note}".rstrip() for _, text, note, _ in options]
        flags = [o for o in options if o[3]]
        width = max(len(talk.command(flag)) for _, _, _, flag in flags)
        hint = "\n".join(["What next? Run one of:"] + [
            f"  {talk.command(flag):<{width}}  {text}{' ' + note if note else ''}"
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
    if then == "fix":
        return start_fix.run(ws, talk, port, open_browser)
    if then == "ask":
        return _ask_again(ws, talk, again_options)
    if then == "label":
        return _serve(ws, talk, port, open_browser)
    return 0


ALL_LABELED = ("Every saved answer is labeled. After your next eval run, run judgekeeper "
               "start again.")


def _can_ask(ws: Workspace, again_options) -> bool:
    """Whether asking the judge again can work: its tool can run it, or you gave your own
    judge as a command."""
    from judgekeeper.start_label import ASKABLE

    return ws.data()["tool"] in ASKABLE or bool(getattr(again_options, "judge_command", None))


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
    talk.say(f"To check these results instead, run {talk.command('--new')}: your last "
             f"check moves to {FOLDER}/{PREVIOUS}<date>/ and nothing is deleted.")
    return 0


def _renamed(talk, data: dict, found, then: str | None) -> bool:
    """Whether the judge in the newest results is the new version of the saved one, whose
    name is not there any more. `--try-new-judge` says yes; else it is asked."""
    if then == "try":
        return True
    question = f"Is {found.metric} the new version of your judge {data['metric']}?"
    return talk.confirm(question, default=True, with_yes=True,
                        hint=f"{question} Run {talk.command('--try-new-judge')} to try it, or "
                             f"{talk.command('--new')} to check it as a new judge.")


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
        if None in (old.get("prompt_hash"), new.get("prompt_hash")):  # unknown is not changed
            was, now = (("recorded" if v else "not recorded")
                        for v in (old.get("prompt_hash"), new.get("prompt_hash")))
            parts.append(f"the prompt was {was}, now {now}")
        else:
            parts.append("the prompt changed")
    if old.get("temperature") != new.get("temperature"):
        parts.append(f"the temperature was {shown(old.get('temperature'))}, now "
                     f"{shown(new.get('temperature'))}")
    return "; ".join(parts) or None


def app_change(saved: dict, now: str | None) -> str | None:
    """What changed in the app's version, in words, or None. A saved check with no
    app_version has nothing to compare."""
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
    left = sum(i in found.pool.left for i in labels)  # in the results, but no real decision
    talk.say()
    talk.say(f"{len(back)} of your {len(labels)} labeled answers are in your latest results "
             f"({found.results[0].date():%Y-%m-%d}).")
    if left:
        talk.say(f"{left} of your labeled answers {'is' if left == 1 else 'are'} left out now: "
                 f"your judge made no real decision on {'it' if left == 1 else 'them'}.")
    start.say_check(talk, found)
    changed = judge_change(ws.data()["fingerprint"], found.fingerprint)
    if changed:
        talk.say(f"Your judge changed since your last check: {changed}.")
    app = app_change(ws.data(), found.app_version)
    if app:
        talk.say(f"Your app changed since your last check: {app}.")
    kept = list(back.values())
    if min(kept.count("pass"), kept.count("fail")) < ROUGH and len(back) < len(labels):
        if len(back) + left < len(labels):  # some are gone, not only left out
            talk.say(f"Fewer than {ROUGH} Correct or {ROUGH} Wrong of them came back "
                     "unchanged: your app gives different answers now, so the old labels do "
                     "not apply to them.")
        else:
            talk.say(f"Fewer than {ROUGH} Correct or {ROUGH} Wrong of them are left to "
                     "compare.")
        if not talk.confirm("Label your latest results?", default=True, with_yes=True,
                            hint=f"Label your latest results? Run {talk.command('--yes')} to "
                                 "label them."):
            return 0
        move_to_previous(ws, talk.say)
        return start.label_found(talk, found, port, open_browser)

    archive = ws.history / f"check-{_stamp()}"
    archive.mkdir(parents=True)
    for p in (ws.start, ws.pool, ws.pool_judge, ws.labels, ws.judge_check_json,
              ws.judge_check_csv):
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
