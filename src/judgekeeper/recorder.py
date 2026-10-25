"""`judgekeeper.record()`: save one verdict of the user's LLM-as-a-judge as one JSON line.

    import judgekeeper
    judgekeeper.record(input=question, output=answer, score=0.82, pass_mark=0.5,
                       reason=reason, judge="claude-opus-5", rule=criteria, name="Safe wording")

Each call writes one record (see records.py) to the project root's `.judgekeeper/records/`,
in one file per process and judge name (`<name>-<date>-<process id>.jsonl`), as coverage.py
does: appending to one shared file is not safe across processes on Windows or network drives.

It never breaks the user's program: any error inside is caught and it returns nothing. The
first verdict it can't save is logged at once; later ones are counted and said when the
program ends, so no loss is silent. `JUDGEKEEPER_RECORD=0` turns it off. Standard library
only, and nothing else of judgekeeper is imported, so `import judgekeeper` stays light.
"""

from __future__ import annotations

import atexit
import json
import logging
import math
import numbers
import os
import re
import threading
import time
from collections.abc import Mapping
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
_lost: dict[int, int] = {}  # per process: verdicts not saved after the first warning


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
            _refuse_links(path)
            for folder in (path.parent.parent, path.parent):  # .judgekeeper/records/
                if not folder.is_dir():
                    folder.mkdir(mode=0o700, exist_ok=True)  # its owner's only
            flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_BINARY", 0)
            with os.fdopen(os.open(path, flags, 0o600), "a", encoding="utf-8",
                           newline="\n") as f:
                f.write(line)
    except Exception as e:  # noqa: BLE001 - never into the user's program
        _warn(e)


def _refuse_links(path: Path) -> None:
    """Never write through a link: .judgekeeper, its records folder and the file itself must
    not be one (a symlink, or on Windows a junction), as for marks (marks.py)."""
    for part in (path.parent.parent, path.parent, path):
        if part.is_symlink() or getattr(os.path, "isjunction", lambda _: False)(part):
            raise _RecordError(f"{part} is a link. judgekeeper does not write through links")


def _is_bool(value) -> bool:
    """A bool, or numpy's (numpy.bool_), which is not a Python bool."""
    return isinstance(value, bool) or getattr(getattr(value, "dtype", None), "kind", None) == "b"


def _label(verdict, score, pass_mark):
    if verdict is not None:
        if _is_bool(verdict):
            verdict = bool(verdict)
        if isinstance(verdict, bool):
            return "pass" if verdict else "fail"
        if isinstance(verdict, str) and verdict.strip().lower() in ("pass", "fail"):
            return verdict.strip().lower()
        return verdict
    if score is not None and pass_mark is not None:
        return "pass" if score >= _number(pass_mark, "pass_mark") else "fail"
    return None


def _number(value, what: str):
    """`value` as a plain int or float (None for NaN): any real number, a numpy number, a
    Decimal or numeric text; never a bool."""
    if _is_bool(value):
        raise _RecordError(f"{what} must be a number")
    if isinstance(value, numbers.Integral):
        return int(value)
    try:
        number = float(value.strip() if isinstance(value, str) else value)
    except (TypeError, ValueError, OverflowError, AttributeError):
        raise _RecordError(f"{what} must be a number") from None
    if math.isnan(number):
        return None
    if math.isinf(number):
        raise _RecordError(f"{what} must be a finite number")
    return number


def _line(input, output, verdict, score, pass_mark, reason, judge, rule, name, temperature,
          id, metadata) -> str:
    if metadata is not None and not isinstance(metadata, Mapping):
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
                _lost[os.getpid()] = _lost.get(os.getpid(), 0) + 1
                return
            _warned.add(os.getpid())
        if isinstance(error, _RecordError):
            why = str(error)
        elif isinstance(error, OSError):
            why = f"{type(error).__name__}: {error.strerror or ''} {error.filename or ''}".strip()
        else:
            why = type(error).__name__  # its text may hold the user's data
        logger.warning("judgekeeper.record() could not save a verdict (%s). Your program goes "
                       "on; any more it can't save are counted and said when it ends.", why)
    except Exception:  # noqa: BLE001, S110 - even a failed warning must not reach the program
        pass


def _say_lost() -> None:
    """At exit: how many more verdicts this process could not save, after the first."""
    try:
        n = _lost.pop(os.getpid(), 0)
        if n:
            logger.warning("judgekeeper.record() could not save %d more verdict%s.", n,
                           "" if n == 1 else "s")
    except Exception:  # noqa: BLE001, S110 - never into the user's program, even at exit
        pass


atexit.register(_say_lost)


def _reset() -> None:
    """Forget the files, locks and warnings of this process (for tests)."""
    with _lock:
        _paths.clear()
        _file_locks.clear()
        _warned.clear()
        _lost.clear()
