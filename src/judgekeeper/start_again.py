"""Running `judgekeeper start` again: `.judgekeeper/` is read first, and what is saved there
decides what happens.

| What is saved                       | What start does                                        |
|-------------------------------------|--------------------------------------------------------|
| nothing                             | the full flow                                          |
| labeling not finished, no result    | asks to continue; yes reopens the page at the next     |
|                                     | answer, from the saved pool (no search)                |
| a result, and the judge's verdicts  | asks to label more; a new result replaces the old one, |
| are the same as last time           | which goes to history/                                 |
| a result, and new verdicts from the | a re-check: the saved labels against the new verdicts, |
| same tool and judge name            | with the new pool's group sizes, next to the last one  |
| anything, with --new                | moves it all (except baseline.json) to                 |
|                                     | previous-<date>/ and starts fresh; deletes nothing     |

A re-check finds the labeled answers in the new results by exact input and output. When
fewer than 15 Correct or 15 Wrong of them came back, the answers changed (the app writes
different outputs now), so the old labels do not apply: start offers to label the latest
results instead, moving the old check to previous-<date>/. Before a re-check replaces the
saved pool, the old start.json, pool files and labels are copied to history/check-<date>/.
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


def run(path: Path, talk, options: dict, port: int, open_browser: bool, new: bool) -> int:
    from judgekeeper import start

    ws = Workspace(_project(path)) if path.exists() else None
    if ws is not None and new:
        move_to_previous(ws, talk.say)
    elif ws is not None and ws.start.is_file():
        if not ws.result_json.is_file():
            return _unfinished(ws, talk, port, open_browser)
        found = start.find_judge(path, talk=talk, **options)
        return _again(ws, found, talk, port, open_browser)
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


def _again(ws: Workspace, found, talk, port: int, open_browser: bool) -> int:
    data = ws.data()
    last = json.loads(ws.result_json.read_text(encoding="utf-8"))
    if found.tool != data["tool"] or found.metric != data["metric"]:
        talk.say(f"Your last check was of the judge {data['judge']} ({data['tool']}). These "
                 f"results are of {found.judge}.")
        talk.say(f"To check these results instead, run judgekeeper start --new: your last "
                 f"check moves to {FOLDER}/{PREVIOUS}<date>/ and nothing is deleted.")
        return 0
    same_judge = judge_change(data["fingerprint"], found.fingerprint) is None
    if same_judge and {a.id: a.verdict for a in found.pool.answers} == _saved_verdicts(ws):
        more = ("Label more?" if last["check"] == "reliable"
                else "Label more for a reliable result?")
        question = f"Your last result ({last['made_at'][:10]}): {CHECKS[last['check']]}. {more}"
        if not talk.confirm(question, default=True, with_yes=True,
                            hint=f"{question} Run judgekeeper start --yes to open the labeling "
                                 "page."):
            return 0
        return _serve(ws, talk, port, open_browser)
    return _recheck(ws, found, last, talk, port, open_browser)


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
