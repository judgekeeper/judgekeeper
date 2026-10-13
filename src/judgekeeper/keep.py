"""Keeping watch: automatic checks on and off, the "Turn on" page, and the status.

Only the person's click on the "Turn on" page turns automatic checks on: `judgekeeper` opens
it after a result with 25 Pass and 25 Fail marks (once: "No thanks" is remembered), and
`judgekeeper check --on` opens it again. The page refuses when its link was printed where a
coding agent could read it. The click writes .judgekeeper/checks.json and adds, each only when
it is not there yet:

| Where                         | What                                                       |
|-------------------------------|------------------------------------------------------------|
| .claude/settings.local.json   | PostToolUse hooks (Bash, Write|Edit): `check --hook`       |
| .cursor/hooks.json            | afterShellExecution and afterFileEdit, when .cursor/ exists |
| .pre-commit-config.yaml       | a `repo: local` hook running `check --fast`, when it exists |
| .git/hooks/pre-commit         | else a hook of its own, when there is none and no          |
|                               | core.hooksPath; else the line to add is said               |
| the dev requirements          | judgekeeper==<version>, when it runs from the project's    |
|                               | own environment                                            |

Then the page asks the judge once (check.baseline) and says "Keeping watch."

The hooks run judgekeeper the way it was started at the click, pinned to that version:
`uvx judgekeeper@<version>`, or the project's own judgekeeper (its path from the project).
Every change is listed in checks.json `added`, so `check --off` (anyone may run it, the agent
too) removes exactly that: a file judgekeeper made goes when it is unchanged; a file it added
to gets its old text back when it is unchanged since, else the added lines are taken out when
they are there as they were, else it is left alone and that is said. Marks, history and
verdicts stay.

checks.json: {"on", "since", "by": "page", "sitting", "allow_agent_judge", "runs", "added"};
after "No thanks" {"on": false, "declined", "by", "sitting"}; after --off "on" is false, "off"
holds the time and "added" is empty.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import stat
import sys
import threading
from pathlib import Path

from judgekeeper import __version__, find, marks, targets, textio
from judgekeeper.fingerprint import utc_now
from judgekeeper.marks import PRINTED
from judgekeeper.textio import line_ending, write_keeping, write_replacing

CHECKS = "checks.json"
TIMEOUT = 600  # seconds a hook may run
PROJECT_DIR = "${CLAUDE_PROJECT_DIR}"
CLAUDE = ".claude/settings.local.json"
CURSOR = ".cursor/hooks.json"
PRE_COMMIT = ".pre-commit-config.yaml"
GIT_HOOK = ".git/hooks/pre-commit"
AGENT_HOOK, COMMIT, REQUIREMENT = "agent hook", "pre-commit", "requirement"
CURSOR_EVENTS = ("afterShellExecution", "afterFileEdit")
ASKABLE = ("promptfoo", "deepeval", "inspect", "mlflow")  # judges judgekeeper can ask again
MARK = "# judgekeeper: re-checks your judge before each commit (no AI call)"

REFUSED = "Open judgekeeper in your own terminal to turn this on."
WATCHING = "Keeping watch. Your marks stay on this computer (.judgekeeper/ is not in git)."
ASKING = "Asking your judge once about your marked answers, to learn how steady it is."
DECLINED = "OK. judgekeeper won't ask again. To turn automatic checks on later, run {command}."
MARK_MORE = (f"Mark up to {targets.RELIABLE} Pass and {targets.RELIABLE} Fail to turn on "
             "automatic checks.")
OFF_LINE = "Automatic checks: off. To turn them on, run `{command}`."
KEPT = "Kept: your marks and history in .judgekeeper/ (judgekeeper never deletes your marks)."
NOT_YET = "Not checked automatically: new kinds of answers from your app (coming later)."


def _program(subcommand: str = "") -> str:
    return textio.program(subcommand)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# What is on ------------------------------------------------------------------------------------

def read(ws) -> dict:
    """checks.json, or {} when it is missing or can't be read."""
    try:
        data = json.loads((ws.dir / CHECKS).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def is_on(ws) -> bool:
    return read(ws).get("on") is True


def answered(ws) -> bool:
    """Whether the person answered the "Turn on" page (or turned checks off since)."""
    return (ws.dir / CHECKS).is_file()


def _write(ws, data: dict) -> None:
    marks._refuse_links(ws.dir / CHECKS)
    write_replacing(ws.dir / CHECKS, json.dumps(data, indent=2, ensure_ascii=False) + "\n")


# How the hooks run judgekeeper -----------------------------------------------------------------

def _prefix() -> Path:
    return Path(sys.prefix)


def _exe(name: str) -> str:
    return f"Scripts/{name}.exe" if os.name == "nt" else f"bin/{name}"


def runner(root: Path) -> tuple[list[str], str]:
    """(judgekeeper as the hooks run it, how): `uvx judgekeeper@<version>` ("uvx"); the
    project's own, its path from the project ("project"); else this one, by its full path
    ("here")."""
    if textio.started_by_uvx():
        return ["uvx", f"judgekeeper@{__version__}"], "uvx"
    prefix = _prefix().resolve()
    if prefix.is_relative_to(root):
        return [(prefix.relative_to(root) / _exe("judgekeeper")).as_posix()], "project"
    script = Path(sys.executable).parent / Path(_exe("judgekeeper")).name
    if script.is_file():
        return [str(script)], "here"
    return [sys.executable, "-m", "judgekeeper"], "here"


def _shell(argv: list[str], *more: str) -> str:
    return " ".join(shlex.quote(a) for a in (*argv, *more))


def _from(argv: list[str], how: str, folder: str) -> list[str]:
    """`argv` for a command run from `folder` (a path from the project; "." is the project)."""
    if how != "project" or folder == ".":
        return list(argv)
    return [f"{folder}/{argv[0]}", *argv[1:]]


# Adding ----------------------------------------------------------------------------------------

def _dump(data, old: str | None) -> str:
    """JSON text in the old file's line endings, ending as it ended (new: with a newline)."""
    eol = line_ending(old) if old else "\n"
    text = json.dumps(data, indent=2, ensure_ascii=False).replace("\n", eol)
    return text + (eol if old is None or old.endswith(("\n", "\r")) else "")


def _read_json(path: Path) -> tuple[str | None, dict | None]:
    """(the file's text or None when missing, its JSON object or None when it can't be read)."""
    if not path.is_file():
        return None, {}
    try:
        old = textio.read_utf8(path, ValueError)
        data = json.loads(old)
    except (OSError, ValueError):
        return "", None
    return old, data if isinstance(data, dict) else None


def _add_hooks(root: Path, rel: str, wanted: dict, base: dict) -> tuple[dict | None, str]:
    """Add the hook entries `wanted` ({event: [entry]}) to the JSON file `rel` (`base`: what a
    new file starts as). (what checks.json lists, or None; the line said)."""
    path = root / rel
    old, data = _read_json(path)
    if data is None:
        return None, f"{rel} can't be read as JSON, so it was left as it is."
    if old is None:
        data = dict(base)
    hooks = data.setdefault("hooks", {})
    if not isinstance(hooks, dict) or any(not isinstance(hooks.get(e, []), list)
                                          for e in wanted):
        return None, f"{rel} has hooks in a shape judgekeeper does not edit, so it was left as it is."
    added: dict = {}
    for event, entries in wanted.items():
        have = hooks.setdefault(event, [])
        for entry in entries:
            if entry not in have:
                have.append(entry)
                added.setdefault(event, []).append(entry)
    if not added:
        return None, ""
    made_folder = not path.parent.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    marks._refuse_links(path)
    write_keeping(path, _dump(data, old))
    return ({"file": rel, "kind": AGENT_HOOK, "created": old is None, "folder": made_folder,
             "hooks": added}, f"Added the agent hook to {rel}.")


def _claude(root: Path, argv: list[str], how: str) -> tuple[dict | None, str]:
    command = f"{PROJECT_DIR}/{argv[0]}" if how == "project" else argv[0]
    hook = {"type": "command", "command": command,
            "args": [*argv[1:], "check", "--hook", PROJECT_DIR], "timeout": TIMEOUT}
    wanted = {"PostToolUse": [{"matcher": m, "hooks": [hook]} for m in ("Bash", "Write|Edit")]}
    return _add_hooks(root, CLAUDE, wanted, {})


def _cursor(root: Path, argv: list[str]) -> tuple[dict | None, str]:
    hook = {"command": _shell(argv, "check", "--hook"), "timeout": TIMEOUT}
    return _add_hooks(root, CURSOR, {e: [hook] for e in CURSOR_EVENTS}, {"version": 1})


def git_root(root: Path) -> Path | None:
    for folder in (root, *root.parents):
        if (folder / ".git").exists():
            return folder
    return None


def _hooks_path(git: Path) -> bool:
    """Whether the repository's own config sets core.hooksPath (git then runs no hook in
    .git/hooks)."""
    try:
        text = (git / ".git" / "config").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return re.search(r"^\s*hookspath\s*=", text, re.IGNORECASE | re.MULTILINE) is not None


def _block(text: str, command: str) -> str | None:
    """A `repo: local` hook for .pre-commit-config.yaml, indented as its other repos, when
    `repos:` is its last top-level key and holds a list; else None."""
    lines = text.splitlines()
    at = next((i for i, x in enumerate(lines) if re.match(r"^repos:\s*(#.*)?$", x)), None)
    if at is None:
        return None
    rest = lines[at + 1:]
    if any(re.match(r"^[^\s#-]", x) for x in rest):
        return None
    item = next((m for x in rest if (m := re.match(r"^(\s*)- ", x))), None)
    if item is None:
        return None
    i = item[1]
    eol = line_ending(text)
    body = [MARK, "- repo: local", "  hooks:", "    - id: judgekeeper",
            "      name: judgekeeper", f"      entry: {command}", "      language: system",
            "      pass_filenames: false", "      always_run: true"]
    return "".join(f"{i}{x}{eol}" for x in body)


def _pre_commit(root: Path, argv: list[str], how: str) -> tuple[dict | None, str]:
    """The check before each commit: in .pre-commit-config.yaml, else .git/hooks/pre-commit;
    else the line to add."""
    git = git_root(root) or root
    folder = Path(os.path.relpath(root, git)).as_posix()
    command = _shell(_from(argv, how, folder), "check", "--fast",
                     *([] if folder == "." else [folder]))
    config = git / PRE_COMMIT
    rel = Path(os.path.relpath(config, root)).as_posix()
    if config.is_file():
        try:
            old = textio.read_utf8(config, ValueError)
        except (OSError, ValueError):
            old = None
        if old is not None and re.search(r"id:\s*judgekeeper\b", old):
            return None, ""
        block = None if old is None else _block(old, command)
        if block is None:
            return None, (f"{rel} was left as it is (judgekeeper doesn't edit its shape). To "
                          f"check before each commit, add a local hook that runs: {command}")
        eol = line_ending(old)
        new = old + ("" if not old or old.endswith(("\n", "\r")) else eol) + block
        write_keeping(config, new)
        return ({"file": rel, "kind": COMMIT, "before": old, "block": block, "sha256": _sha(new)},
                f"Added a check before each git commit to {rel}.")
    hook = git / GIT_HOOK
    rel = Path(os.path.relpath(hook, root)).as_posix()
    if not (git / ".git").is_dir():
        return None, ""
    if hook.exists() or _hooks_path(git):
        try:
            mine = MARK in hook.read_text(encoding="utf-8", errors="replace")
        except OSError:
            mine = False
        if mine:
            return None, ""
        return None, ("Your git pre-commit hook was left as it is. To check before each "
                      f"commit, add this line to it: {command}")
    text = (f"#!/bin/sh\n{MARK}\n# `judgekeeper check --off` removes this file.\n"
            f"exec {command}\n")
    hook.parent.mkdir(parents=True, exist_ok=True)
    with open(hook, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    hook.chmod(hook.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return ({"file": rel, "kind": COMMIT, "created": True, "sha256": _sha(text)},
            f"Added a check before each git commit to {rel}.")


def _requirement(root: Path) -> tuple[dict | None, str]:
    from judgekeeper.dev_requirements import RequirementsError, requirements_change

    spec = f"judgekeeper=={__version__}"
    try:
        change = requirements_change(root, spec)
    except RequirementsError as e:
        return None, str(e)
    if change is None:
        return None, ""
    if change.apply is None:
        return None, change.text + "."
    path = root / change.file
    before = textio.read_utf8(path, RequirementsError)
    change.apply()
    after = textio.read_utf8(path, RequirementsError)
    return ({"file": change.file, "kind": REQUIREMENT, "where": change.where, "before": before,
             "sha256": _sha(after)}, f"Added {spec} to {change.where}.")


def turn_on(ws, allow_agent_judge: bool, sitting: str) -> list[str]:
    """What the click does before asking the judge: the hooks, the check before each commit,
    the dev requirement, and checks.json. Returns the lines said. A piece already there is
    not added again."""
    root = Path(ws.root).resolve()
    old = read(ws) if is_on(ws) else {}
    argv, how = runner(root)
    added: list[dict] = []
    lines: list[str] = []
    data = {"on": True, "since": old.get("since") or utc_now(), "by": "page",
            "sitting": sitting, "allow_agent_judge": allow_agent_judge,
            "runs": _shell(argv), "added": list(old.get("added") or [])}
    steps = [lambda: _claude(root, argv, how)]
    if (root / ".cursor").is_dir():
        steps.append(lambda: _cursor(root, argv))
    steps.append(lambda: _pre_commit(root, argv, how))
    if how == "project":
        steps.append(lambda: _requirement(root))
    try:
        for step in steps:
            try:
                entry, line = step()
            except OSError as e:
                entry, line = None, f"Something could not be added: {textio.describe_os_error(e) or e}."
            if entry is not None:
                added.append(entry)
            if line:
                lines.append(line)
    finally:
        data["added"] += added
        _write(ws, data)
    return lines


def decline(ws, sitting: str) -> None:
    _write(ws, {"on": False, "declined": utc_now(), "by": "page", "sitting": sitting})


# Taking it out ---------------------------------------------------------------------------------

def _remove_hooks(root: Path, entry: dict) -> bool:
    path = root / entry["file"]
    old, data = _read_json(path)
    if old is None:
        return True  # gone already
    hooks = (data or {}).get("hooks")
    if not isinstance(hooks, dict):
        return False
    for event, entries in entry["hooks"].items():
        have = hooks.get(event)
        if not isinstance(have, list) or any(e not in have for e in entries):
            return False
    for event, entries in entry["hooks"].items():
        hooks[event] = [e for e in hooks[event] if e not in entries]
        if not hooks[event]:
            del hooks[event]
    if not hooks:
        del data["hooks"]
    if entry.get("created") and data in ({}, {"version": 1}):
        path.unlink()
        if entry.get("folder"):
            try:
                path.parent.rmdir()
            except OSError:
                pass
        return True
    write_keeping(path, _dump(data, old))
    return True


def _remove_text(root: Path, entry: dict) -> bool:
    path = root / entry["file"]
    try:
        now = path.read_bytes().decode("utf-8-sig")
    except FileNotFoundError:
        return True
    except (OSError, ValueError):
        return False
    if entry.get("created"):
        if _sha(now) != entry["sha256"]:
            return False
        path.unlink()
        return True
    if _sha(now) == entry["sha256"]:
        write_keeping(path, entry["before"])
        return True
    block = entry.get("block")
    if block and now.count(block) == 1:
        write_keeping(path, now.replace(block, ""))
        return True
    return False


def _what(entry: dict) -> str:
    if entry["kind"] == AGENT_HOOK:
        return f"the agent hook in {entry['file']}"
    if entry["kind"] == REQUIREMENT:
        return f"judgekeeper in {entry['where']}"
    if entry.get("created"):
        return f"the git pre-commit hook {entry['file']}"
    return f"the judgekeeper lines in {entry['file']}"


def turn_off(ws) -> tuple[list[str], list[str]] | None:
    """Take out what checks.json lists: (removed, left as they are), or None when automatic
    checks are not on."""
    data = read(ws)
    if data.get("on") is not True:
        return None
    root = Path(ws.root).resolve()
    removed, left, kept = [], [], []
    for entry in data.get("added") or []:
        try:
            done = (_remove_hooks if entry.get("kind") == AGENT_HOOK else _remove_text)(root, entry)
        except (OSError, KeyError, TypeError):
            done = False
        if done:
            removed.append(_what(entry))
        else:
            left.append(entry["file"])
            kept.append(entry)
    _write(ws, {**data, "on": False, "off": utc_now(), "added": kept})
    return removed, left


# The status ------------------------------------------------------------------------------------

def _checks_in(ws) -> list[dict]:
    try:
        text = ws.history_jsonl.read_text(encoding="utf-8")
    except OSError:
        return []
    out = []
    for raw in text.splitlines():
        try:
            line = json.loads(raw)
        except ValueError:
            continue
        if isinstance(line, dict) and line.get("kind") == "check":
            out.append(line)
    return out


def _last_check(ws) -> str:
    from judgekeeper.check import _day

    lines = _checks_in(ws)
    if not lines:
        return "Last check: none yet."
    last = lines[-1]
    day = _day(last.get("time"))
    if last.get("trigger") == "baseline":
        return (f"Last check: {day}, your judge asked once about {last.get('asked')} marked "
                f"answers (it changed its mind on {len(last.get('flipped') or [])}).")
    groups = last.get("groups") or {}
    worse = [k for k in ("passed", "failed") if (groups.get(k) or {}).get("verdict") == "worse"]
    said = (f"worse on answers you {' and '.join(worse)}" if worse else "no drop seen")
    return (f"Last check: {day}, your judge changed ({', '.join(last.get('changed') or [])}): "
            f"{said}.")


def status_lines(ws, command: str) -> list[str]:
    """Scene 5b's status: what is on, since when, what it runs and uses, the marks, the last
    check, what it can see and can't. `command` is `judgekeeper check` as the person runs it."""
    from judgekeeper import judge_setup
    from judgekeeper.check import _day, _steadiness
    from judgekeeper.start_label import shown_folder

    data = read(ws)
    lines = [(f"Automatic checks: ON since {_day(data.get('since'))}, turned on by the person "
              "on the page.")]
    kinds = {a.get("kind") for a in data.get("added") or []}
    when = (["your judge changes (agent hook)"] if AGENT_HOOK in kinds else []) + (
        ["before each git commit (no AI call)"] if COMMIT in kinds else [])
    lines.append(f"  Runs when: {', and '.join(when) if when else f'you run `{command}`'}.")
    saved = judge_setup.read(ws) or {}
    tool = (saved.get("setup") or {}).get("tool")
    if tool in ASKABLE:
        lines.append(f"  Uses: your own judge, through {find.NAMES[tool]}, with the key your "
                     "evals already use.")
    else:
        lines.append("  Uses: your judge's verdicts in your newest results (judgekeeper can't "
                     "ask this judge itself).")
    m = marks.read(ws.marks)
    counted = m.counted()
    n_pass = sum(v == "pass" for v in counted.values())
    n_fail = len(counted) - n_pass
    newest = max((m.last[i]["at"] for i in counted), default=None)
    lines.append(f"Your marks: {len(counted)} ({n_pass} Pass, {n_fail} Fail), the newest from "
                 f"{_day(newest)}.")
    lines.append(_last_check(ws))
    flip, right = _steadiness(ws)
    drop = targets.smallest_drop(n_pass, n_fail, flip, right)
    if drop is not None:
        lines.append(f"This set can see a drop of {drop} points or more.")
    lines += [NOT_YET, f"All checks: {shown_folder(ws)}/{ws.report_html.name} (History)", "",
              f"To turn automatic checks off: {command} --off"]
    return lines


# The report's History --------------------------------------------------------------------------

def _rate(x) -> str:
    return "?" if x is None else f"{x:.0%}"


def history_rows(lines: list[dict]) -> list[dict]:
    """One row per check in history.jsonl lines (in their order): date, what changed, marks
    tested, old against new per group, the verdict, exact or close."""
    from judgekeeper.check import GROUPS, _day

    rows = []
    for line in lines:
        if not isinstance(line, dict) or line.get("kind") != "check":
            continue
        free, asked = int(line.get("free") or 0), int(line.get("asked") or 0)
        parts = ([f"{free} free"] if free else []) + ([f"{asked} asked again"] if asked else [])
        row = {"date": _day(line.get("time")) or "",
               "tested": f"{free + asked} marks ({', '.join(parts)})" if parts else "0 marks",
               "exact": "close copy" if line.get("exact") == "close" else "exact"}
        if line.get("trigger") == "baseline":
            row.update(changed="Asked your judge once, to learn how steady it is", groups=[],
                       verdict=f"Changed its mind on {len(line.get('flipped') or [])} of {asked}")
        else:
            groups = line.get("groups") or {}
            shown = []
            for key, _, title in GROUPS:
                g = groups.get(key) or {}
                shown.append(f"{title}: {_rate(g.get('old'))} → {_rate(g.get('new'))}"
                             if g.get("n") else f"{title}: not tested")
            worse = any((groups.get(k) or {}).get("verdict") == "worse" for k in groups)
            row.update(changed=", ".join(line.get("changed") or []), groups=shown,
                       verdict="Worse" if worse else "No drop seen")
        rows.append(row)
    return rows


def report_rows(ws) -> list[dict]:
    """The History rows for report.html: newest first."""
    return list(reversed(history_rows(_checks_in(ws))))


# The page --------------------------------------------------------------------------------------

def _agent_can_write(ws) -> bool:
    from judgekeeper import judge_setup

    setup = (judge_setup.read(ws) or {}).get("setup") or {}
    return setup.get("kind") == judge_setup.AGENT and \
        (setup.get("agent") or {}).get("can_write") is not False


class KeepSession:
    """The "Turn on" page's session: no items to mark, two answers (POST /turn-on with
    {"allow_agent_judge": bool}, POST /no-thanks), and the work after the click in a thread
    of its own (the baseline asks the judge), which GET /state follows."""

    def __init__(self, ws):
        self.ws = ws
        self.out = ws.dir / CHECKS  # make_server checks it can be written
        self.items: list = []
        self.by_id: dict = {}
        self.link: str | None = None  # marks.PRINTED once the link was printed for an agent
        self.sitting = marks.new_sitting()
        self.phase = "on" if is_on(ws) else "ask"
        self.lines: list[str] = [WATCHING] if self.phase == "on" else []
        self.thread: threading.Thread | None = None
        self.posts = {"/turn-on": self._turn_on, "/no-thanks": self._no_thanks}

    def summary(self) -> dict:
        return {"done": False}

    def state(self) -> dict:
        return {"phase": self.phase, "lines": list(self.lines), "agent": _agent_can_write(self.ws)}

    def wait(self) -> None:
        if self.thread is not None:
            self.thread.join()

    def _turn_on(self, body: dict) -> dict:
        if self.link == PRINTED:
            return {"phase": "refused", "lines": [REFUSED]}
        if self.phase == "asking":
            return self.state()
        allow = body.get("allow_agent_judge") is True
        setup = turn_on(self.ws, allow, self.sitting)
        self.lines = [WATCHING, *setup, ASKING]
        self.phase = "asking"
        self.thread = threading.Thread(target=self._baseline, args=(setup,))
        self.thread.start()
        return self.state()

    def _baseline(self, setup: list[str]) -> None:
        from judgekeeper import check

        said = check.Said()
        try:
            check.baseline(str(Path(self.ws.root).resolve()), said)
        except Exception as e:  # noqa: BLE001 - the page says it; checks stay on
            said.say(f"Asking your judge once did not finish: {type(e).__name__}.")
        self.lines = [WATCHING, *setup, *said.lines]
        self.phase = "done"

    def _no_thanks(self, body: dict) -> dict:
        if self.phase != "ask":
            return self.state()
        decline(self.ws, self.sitting)
        self.phase = "declined"
        self.lines = [DECLINED.format(command=f"`{_program('check --on')}`")]
        return self.state()


def keep_server(ws, port: int, token: str | None = None):
    """The "Turn on" page for the project whose workspace is `ws`; it holds the project's
    lock, as the marking page does."""
    from judgekeeper import judge_setup
    from judgekeeper.label import make_server
    from judgekeeper.start_page import keep_page

    session = KeepSession(ws)
    tool = ((judge_setup.read(ws) or {}).get("setup") or {}).get("tool")
    n = len(marks.read(ws.marks).counted())
    return make_server(session, port, page=keep_page(find.NAMES.get(tool) if tool in ASKABLE
                                                     else None, n, _agent_can_write(ws)),
                       lock=ws.dir, stays=True, token=token)


__all__ = ["CHECKS", "KeepSession", "answered", "history_rows", "is_on", "keep_server", "read",
           "report_rows", "runner", "status_lines", "turn_off", "turn_on"]
