"""`judgekeeper.record()`: save one judge verdict, one line, where the user's own judge runs.

    import judgekeeper
    judgekeeper.record(input=question, output=answer, score=0.82, pass_mark=0.5,
                       reason=reason, judge="claude-opus-5", rule=criteria, name="Safe wording")

Each call writes one record (records format version 2, annotator_kind LLM; see records.py)
as a JSON line to `.judgekeeper/records/<name>-<date>-<process id>.jsonl` under the project
root: the nearest folder upward from the current one with judgekeeper.toml, pyproject.toml,
setup.py, .git or requirements*.txt, never the home folder; else the current folder. One file
per process and judge name (the coverage.py approach: appending to one shared file is not
safe across processes on Windows or network drives), worked out from the process id on each
call, so a forked child gets its own file. A lock per file keeps threads' lines whole; each
line is written in one go and the file closed, so it is on disk at once.

It never breaks the user's program: any error inside is caught, one warning goes to the
`judgekeeper` logger once per process, and it returns nothing. `JUDGEKEEPER_RECORD=0` (or
false, off, no) turns it off, for production. Standard library only, and nothing else of
judgekeeper is imported, so `import judgekeeper` stays light.

SNIPPETS hold the same line for people who do not want the import (Python) or use another
language (TypeScript); AGENT_PROMPT asks a coding agent to add the call. `judgekeeper record
--snippet python|typescript` and `judgekeeper record --agent-prompt` print them.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import threading
import time
from pathlib import Path

SCHEMA_VERSION = 2  # records.SCHEMA_VERSION, kept here so nothing else is imported
FOLDER = Path(".judgekeeper") / "records"
MARKERS = ("judgekeeper.toml", "pyproject.toml", "setup.py", ".git")
OFF = frozenset({"0", "false", "off", "no"})
DEFAULT_NAME = "judge"
_UNSAFE = re.compile(r"[^A-Za-z0-9._]+")

logger = logging.getLogger("judgekeeper")
_lock = threading.Lock()  # guards the three below
_file_locks: dict[str, threading.Lock] = {}
_paths: dict[tuple[int, str], Path] = {}
_warned: set[int] = set()  # the processes that have shown the warning


class _RecordError(ValueError):
    """A value record() cannot write; its message is safe to show."""


def record(input=None, output=None, *, verdict=None, score=None, pass_mark=None, reason=None,
           judge=None, rule=None, name=None, temperature=None, id=None, metadata=None) -> None:
    """Save one verdict of your judge for judgekeeper. Never raises; returns nothing.

    `input` and `output`: the question and the answer judged (any JSON-able value; anything
    else is written as text). The verdict: `verdict` (pass or fail, True or False), or
    `score` with `pass_mark` (pass when score >= pass_mark). Optional: `reason`, `judge` (the
    judge's model), `rule` (its rule or criteria), `name` (which judge or criterion; default
    "judge"), `temperature`, `id` (the answer's id), `metadata` (a dict of anything else)."""
    try:
        if os.environ.get("JUDGEKEEPER_RECORD", "").strip().lower() in OFF:
            return
        line = _line(input, output, verdict, score, pass_mark, reason, judge, rule, name,
                     temperature, id, metadata)
        path = _path(name)
        with _lock_for(path):
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8", newline="\n") as f:
                f.write(line)
    except Exception as e:  # noqa: BLE001 - never into the user's program
        _warn(e)


def _label(verdict, score, pass_mark):
    if verdict is not None:
        if isinstance(verdict, bool):
            return "pass" if verdict else "fail"
        if isinstance(verdict, str) and verdict.strip().lower() in ("pass", "fail"):
            return verdict.strip().lower()
        return verdict
    if score is not None and pass_mark is not None:
        return "pass" if score >= _number(pass_mark, "pass_mark") else "fail"
    return None


def _number(value, what: str):
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise _RecordError(f"{what} must be a number")
    return None if isinstance(value, float) and math.isnan(value) else value


def _line(input, output, verdict, score, pass_mark, reason, judge, rule, name, temperature,
          id, metadata) -> str:
    if metadata is not None and not isinstance(metadata, dict):
        raise _RecordError("metadata must be a dict")
    score = None if score is None else _number(score, "score")
    meta = dict(metadata or {})
    if pass_mark is not None:
        meta.setdefault("pass_mark", _number(pass_mark, "pass_mark"))
    evaluator = {k: v for k, v in (("model", judge), ("temperature", temperature),
                                   ("rule", rule)) if v is not None}
    data = {"schema_version": SCHEMA_VERSION, "target_id": None if id is None else str(id),
            "name": DEFAULT_NAME if name is None else str(name), "annotator_kind": "LLM",
            "label": _label(verdict, score, pass_mark), "score": score,
            "explanation": None if reason is None else str(reason), "run": None,
            "input": input, "output": output, "evaluator": evaluator,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    if meta:
        data["metadata"] = meta
    return json.dumps(data, ensure_ascii=False, default=str) + "\n"


def project_root(start: Path | None = None) -> Path:
    """The nearest folder upward from `start` (the current folder) that looks like a project
    root, stopping below the home folder; else `start`."""
    here = (start or Path.cwd()).resolve()
    try:
        home = Path.home().resolve()
    except (RuntimeError, OSError):
        home = None
    for folder in (here, *here.parents):
        if folder == home:
            break
        if any((folder / m).exists() for m in MARKERS) or next(
                folder.glob("requirements*.txt"), None) is not None:
            return folder
    return here


def _path(name) -> Path:
    safe = _UNSAFE.sub("-", DEFAULT_NAME if name is None else str(name)).strip("-.")[:60]
    key = (os.getpid(), safe or DEFAULT_NAME)
    with _lock:
        if key not in _paths:
            day = time.strftime("%Y-%m-%d", time.gmtime())
            _paths[key] = project_root() / FOLDER / f"{key[1]}-{day}-{key[0]}.jsonl"
        return _paths[key]


def _lock_for(path: Path) -> threading.Lock:
    with _lock:
        return _file_locks.setdefault(str(path), threading.Lock())


def _warn(error: Exception) -> None:
    try:
        with _lock:
            if os.getpid() in _warned:
                return
            _warned.add(os.getpid())
        if isinstance(error, _RecordError):
            why = str(error)
        elif isinstance(error, OSError):
            why = f"{type(error).__name__}: {error.strerror or ''} {error.filename or ''}".strip()
        else:
            why = type(error).__name__  # its text may hold the user's data
        logger.warning("judgekeeper.record() could not save a verdict (%s). Your program goes "
                       "on; this warning is shown once.", why)
    except Exception:  # noqa: BLE001, S110 - even a failed warning must not reach the program
        pass


def _reset() -> None:
    """Forget the files, locks and warnings of this process (for tests)."""
    with _lock:
        _paths.clear()
        _file_locks.clear()
        _warned.clear()


SNIPPETS = {
    "python": '''\
# Saves each judge verdict for judgekeeper; run it from your project folder. Standard library only.
import json, os, time
def jk_record(input, output, verdict=None, score=None, reason=None, name="judge",
              judge=None, rule=None):
    try:
        folder, now = os.path.join(".judgekeeper", "records"), time.gmtime()
        os.makedirs(folder, exist_ok=True)
        line = {"schema_version": 2, "name": name, "annotator_kind": "LLM", "input": input,
                "output": output, "label": verdict, "score": score, "explanation": reason,
                "evaluator": {"model": judge, "rule": rule},
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", now)}
        file = "".join(c if c.isalnum() else "-" for c in name)
        file += f"-{time.strftime('%Y-%m-%d', now)}-{os.getpid()}.jsonl"
        with open(os.path.join(folder, file), "a", encoding="utf-8") as f:
            f.write(json.dumps(line, ensure_ascii=False, default=str) + "\\n")
    except Exception:
        pass  # a record never stops your program''',
    "typescript": '''\
// Saves each judge verdict for judgekeeper; run it from your project folder. Node.js only.
import { appendFileSync, mkdirSync } from "node:fs";
import { join } from "node:path";

type JkFields = { verdict?: "pass" | "fail" | boolean; score?: number; reason?: string;
                  name?: string; judge?: string; rule?: string };

export function jkRecord(input: unknown, output: unknown, f: JkFields = {}): void {
  try {
    const folder = join(".judgekeeper", "records"), name = f.name ?? "judge";
    const now = new Date().toISOString();
    mkdirSync(folder, { recursive: true });
    const line = { schema_version: 2, name, annotator_kind: "LLM", input, output,
      label: f.verdict ?? null, score: f.score ?? null, explanation: f.reason ?? null,
      evaluator: { model: f.judge ?? null, rule: f.rule ?? null }, created_at: now };
    const file = `${name.replace(/[^A-Za-z0-9]/g, "-")}-${now.slice(0, 10)}-${process.pid}.jsonl`;
    appendFileSync(join(folder, file), JSON.stringify(line) + "\\n");
  } catch { /* a record never stops your program */ }
}''',
}

AGENT_PROMPT = """\
In this project, my LLM judge runs in my own code. Please add judgekeeper's record() line, so
judgekeeper can check my judge against my own labels:

1. judgekeeper must be installed in this project's own Python environment, as a dev tool. If
   it is missing, install it there: for example `uv add --dev judgekeeper`, `poetry add
   --group dev judgekeeper`, or `pip install judgekeeper` with the project's virtual
   environment active.
2. Find where this project's LLM judge produces each score or verdict.
3. Right after it, add one call, with the values the judge just used and gave:

       import judgekeeper
       judgekeeper.record(input=..., output=..., score=..., pass_mark=..., reason=...,
                          judge="<the judge's model>", rule=<the judge's rule or criteria>,
                          name="<the judge's or criterion's name>")

   When the judge gives pass or fail, pass verdict=... instead of score and pass_mark. One
   call per judge or criterion. Only in the eval code, never in code that serves real users
   (it saves inputs and outputs to a file); JUDGEKEEPER_RECORD=0 turns it off.
4. Touch nothing else. record() catches its own errors and returns nothing, so it can never
   change what the program does; do not wrap it in code that could.
5. Show me the diff and wait for my yes before saving.
6. Then run the eval once, run `judgekeeper import records .judgekeeper/records --check`, and
   show me what it prints."""
