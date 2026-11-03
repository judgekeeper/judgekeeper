"""The project folder of a path, and starting over: moving a check to previous-<date>/
(`--new`; nothing is deleted).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from judgekeeper import marks
from judgekeeper.fingerprint import utc_now
from judgekeeper.start_label import (
    FOLDER,
    Workspace,
)
from judgekeeper.textio import PRIVATE_FOLDER, kept_at

# Not part of a check: .gitignore, baseline.json (set by `baseline set`), records/
# (judgekeeper.record()); and what `judgekeeper check` keeps across marks: history.jsonl and
# the verdicts of each judge setup (verdicts/)
KEPT = (".gitignore", "baseline.json", "records", "history.jsonl", "verdicts")
PREVIOUS = "previous-"


def _stamp() -> str:
    return utc_now().replace(":", "-")


def move_to_previous(ws: Workspace, say) -> Path | None:
    """Move everything in `.judgekeeper/` except baseline.json, records/ and earlier
    previous-<date>/ folders into a new previous-<date>/ folder. Nothing is deleted. Said
    only when marks moved."""
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
    target.mkdir(mode=PRIVATE_FOLDER)
    what = ("your marks and results" if ws.result_json.is_file()  # a result was made
            else "your marks" if ws.marks.is_file() and marks.read(ws.marks).counted()
            else None)  # no marks: nothing of the person's moves, so nothing is said
    for p in entries:
        p.replace(target / p.name)
    if what is not None:
        say(f"Moved {what} to {FOLDER}/{target.name}/. Nothing was deleted.")
    return target


def project_of(path: Path) -> Path:
    """The project folder every command keeps .judgekeeper/ in. A results file or an MLflow
    store given as the path never moves it: it is found from the folder the command runs in.
    From there (or the folder given), the nearest folder up whose .judgekeeper/ holds marks,
    without leaving the project (a folder with find.PROJECT_MARKERS), when the results here
    are the ones it reads or there are none here (kept_apart); else the folder itself, the
    same with a path given or not."""
    here, given = _here(path)
    above = store_above(here)
    if above is None or above != here and _apart(here, above, given):
        return here
    return above


def kept_apart(here: Path, given: Path | None = None) -> tuple[Path, list[str]] | None:
    """(the folder above whose .judgekeeper/ holds marks, the results it reads) when the
    results in `here` (or the file or folder `given`) are not those and so get their own
    .judgekeeper/ in `here`."""
    here = Path(here).resolve()
    given = None if given is None else Path(given).resolve()
    above = store_above(here)
    if above is None or above == here or not _apart(here, above, given):
        return None
    return above, _read_by(above)


def _here(path: Path) -> tuple[Path, Path | None]:
    """(the folder the walk starts from, the results file or MLflow store given, if any)."""
    from judgekeeper import find

    if path.is_file() or find.is_mlflow_folder(path):
        return Path.cwd().resolve(), path.resolve()
    return path.resolve(), None


def store_above(here: Path) -> Path | None:
    """The nearest folder from `here` up whose .judgekeeper/ holds a session, without leaving
    the project or reaching the home folder."""
    try:
        home = Path.home().resolve()
    except (RuntimeError, OSError):
        home = None
    for folder in (here, *here.parents):
        if folder == home:
            break
        ws = Workspace(folder)
        if ws.start.is_file() or ws.labels.is_file():
            return folder
        if is_project(folder):
            break
    return None


def _read_by(store: Path) -> list[str]:
    """The results the session in `store` reads, named from `store`: the file (or folder)
    given by path when marking started, else the files it found."""
    import json

    try:
        data = json.loads(Workspace(store).start.read_text(encoding="utf-8"))
        given = data.get("given")
        files = [given] if isinstance(given, str) and given else data.get("results_files")
    except (OSError, ValueError, AttributeError):
        return []
    return [f for f in files if isinstance(f, str)] if isinstance(files, list) else []


def _apart(here: Path, store: Path, given: Path | None) -> bool:
    """Whether the results here (the one given, else those found in `here`) are other than
    the ones the session in `store` reads, or files beside them: then they get their own
    .judgekeeper/."""
    try:
        stamp = Workspace(store).start.stat().st_mtime_ns
    except OSError:
        stamp = 0
    return _apart_cached(here, store, given, stamp)


def forget() -> None:
    """Forget which results were found apart: each command looks again."""
    _apart_cached.cache_clear()


@lru_cache(maxsize=64)  # one command asks many times; the answer is the same
def _apart_cached(here: Path, store: Path, given: Path | None, stamp: int) -> bool:
    from judgekeeper import find

    if given is not None:
        mine = {given}
    elif not here.is_dir():  # a pipe or a device: the command refuses it
        return False
    else:
        found = find.search(here)
        mine = {r.path.resolve() for results in found.results.values() for r in results}
    if not mine:
        return False
    theirs = [Path(kept_at(f, store)).resolve() for f in _read_by(store)]
    # a file beside one it reads is its own too when it is the same eval (new results of it)
    return not all(any(m == t or m.is_relative_to(t) for t in theirs) or (
        any(not t.is_dir() and m.parent == t.parent for t in theirs) and _same_eval(m, store))
        for m in mine)


def _same_eval(path: Path, store: Path) -> bool:
    """Whether the results file `path` is of the eval the session in `store` marks: read the
    same way (its eval tool or format), with at least one of its answers (the same question,
    or the same answer: an id made the same way). A tool read another way than one file at
    a time (judgekeeper.record()'s files, an MLflow store) is the same eval by its tool."""
    import json

    from judgekeeper import find, start
    from judgekeeper.records import RecordsError, derive_record_id

    ws = Workspace(store)
    try:
        tool = json.loads(ws.start.read_text(encoding="utf-8")).get("tool")
        if not tool or find.classify_file(path) != tool:
            return False
        if tool not in ("table", "inspect", *start.FILE_READERS):
            return True
        held = [json.loads(line) for line in ws.pool.read_text(encoding="utf-8").splitlines()
                if line.strip()]
        records = start._read(find.Result(tool, path, path.name, path.stat().st_size)).records
    except (OSError, ValueError, AttributeError, RecordsError, start.StartError,
            *start.UNREADABLE):  # kept apart: the command says why it can't read it
        return False
    ids = {str(a.get("id")) for a in held}
    questions = {a.get("input") for a in held if a.get("input")}
    return any(r.input in questions or str(r.target_id or "") in ids
               or derive_record_id(r.input, r.output, r.trajectory) in ids for r in records)


def is_project(folder: Path) -> bool:
    from judgekeeper import find

    try:
        return any((folder / m).exists() for m in find.PROJECT_MARKERS)
    except OSError:
        return False
