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
    if above is None:
        return here
    marked = marks_above(above, given)
    if marked is not None:
        return marked
    return here if above != here and _apart(here, above, given) else above


def marks_above(store: Path, given: Path | None = None) -> Path | None:
    """The folder above `store` whose marks are for the results in `store`, when the session
    in `store` holds none and `store` is no project of its own: a run there used to start it,
    and every command passes over it now, leaving it as it is. Else None."""
    if is_project(store) or _holds_marks(store):
        return None
    above = store_above(store.parent)
    if above is None or not _holds_marks(above) or _apart(store, above, given):
        return None
    return above


def _holds_marks(folder: Path) -> bool:
    """Whether the .judgekeeper/ in `folder` holds marks, or a sheet of them (labels.csv). One
    that can't be read may hold them: it is never passed over."""
    ws = Workspace(folder)
    try:
        return ws.labels.is_file() or bool(marks.read(ws.marks).last)
    except (OSError, ValueError):
        return True


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
    except (OSError, ValueError, AttributeError, RecursionError):
        return []
    return [f for f in files if isinstance(f, str)] if isinstance(files, list) else []


def _apart(here: Path, store: Path, given: Path | None) -> bool:
    """Whether the results here (the one given, else those found in `here`) are neither the
    ones the session in `store` reads nor files beside them: then they get their own
    .judgekeeper/. Another eval beside them is the session's to say no to (other_eval)."""
    try:
        stamp = Workspace(store).start.stat().st_mtime_ns
    except OSError:
        stamp = 0
    return _apart_cached(here, store, given, stamp)


def forget() -> None:
    """Forget which results were found apart: each command looks again."""
    _apart_cached.cache_clear()
    _same_eval_cached.cache_clear()


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
    theirs = _theirs(store)
    # a file beside one it reads is its own: new results of it join, another eval is said so
    # (other_eval) and never gets marks of its own
    return not all(any(m == t or m.is_relative_to(t) or not t.is_dir() and m.parent == t.parent
                       for t in theirs) for m in mine)


def _theirs(store: Path) -> list[Path]:
    """The results files (or folders) the session in `store` reads, as full paths."""
    return [Path(kept_at(f, store)).resolve() for f in _read_by(store)]


OTHER_EVAL = ("{file} shares few questions with the results you marked ({marked}), so it looks "
              "like another eval.")
TO_MARK_IT = "To mark it, put it in a folder of its own and run `{program}` there."
OTHER_EVAL_NEXT = "put {file} in a folder of its own, then run `{program}` there."


def other_eval(store: Path, path: Path) -> Path | None:
    """The file the session in `store` reads that the results file `path` sits beside, when
    `path` is another eval (not _same_eval): it is never read, marked or given marks of its
    own (other_eval_line says why). None for one it reads, the same eval, or a file
    elsewhere."""
    path = Path(path).resolve()
    if not Workspace(store).start.is_file() or not path.is_file():
        return None
    theirs = _theirs(store)
    if any(path == t or path.is_relative_to(t) for t in theirs):
        return None
    beside = next((t for t in theirs if not t.is_dir() and path.parent == t.parent), None)
    if beside is None or not _results(path):  # a file it can't read as results: no eval
        return None
    try:
        stamps = (path.stat().st_mtime_ns, Workspace(store).pool.stat().st_mtime_ns)
    except OSError:
        stamps = (0, 0)
    return None if _same_eval_cached(path, Path(store).resolve(), stamps) else beside


def others_beside(store: Path) -> list[tuple[Path, Path]]:
    """(another eval, the file it sits beside) for each results file in the folder of a file
    the session in `store` reads that is another eval (other_eval), by name."""
    out, seen = [], set()
    for t in _theirs(store):
        folder = t.parent
        if t.is_dir() or folder in seen:
            continue
        seen.add(folder)
        try:
            files = sorted(f for f in folder.iterdir() if f.is_file()
                           and not f.name.startswith("."))
        except OSError:
            continue
        for f in files:
            if (beside := other_eval(store, f)) is not None:
                out.append((f.resolve(), beside))
    return out


def _results(path: Path) -> bool:
    """Whether judgekeeper reads `path` as results of an eval tool or a table."""
    from judgekeeper import find

    try:
        return find.classify_file(path) is not None
    except (OSError, ValueError, RecursionError):
        return False


def _answers(path: Path) -> bool:
    """Whether `path` is a table of answers with no grade (find.answers_only)."""
    import csv

    from judgekeeper import find

    try:
        return find.answers_only(path)
    except (OSError, ValueError, RecursionError, csv.Error):
        return False


def other_eval_line(path: Path, marked: Path) -> str:
    """The line for `path`, another eval beside `marked`: both named as every path line names
    them (textio.line_path), a typed path too."""
    return f"{_other_eval_said(path, marked)} {TO_MARK_IT.format(program=program_anywhere())}"


def other_eval_stop(path: Path, marked: Path) -> tuple[str, str]:
    """(the line, the Next step) for a command that stops at `path`, another eval beside
    `marked`."""
    from judgekeeper import textio

    return _other_eval_said(path, marked), OTHER_EVAL_NEXT.format(
        file=textio.line_path(path), program=program_anywhere())


def _other_eval_said(path: Path, marked: Path) -> str:
    from judgekeeper import textio

    return OTHER_EVAL.format(file=textio.line_path(path), marked=textio.line_path(marked))


def program_anywhere() -> str:
    """judgekeeper as typed in a folder of its own: as typed here when that holds no path
    (`judgekeeper`, `uvx judgekeeper`, `python3 -P -m judgekeeper`), else plain `judgekeeper`:
    a path from here runs wrong there, and a whole or home path is never printed."""
    from judgekeeper import textio

    typed = textio.program()
    return "judgekeeper" if any(c in typed for c in "/\\~") else typed


@lru_cache(maxsize=64)  # a run asks for each file more than once
def _same_eval_cached(path: Path, store: Path, stamps: tuple[int, int]) -> bool:
    return _same_eval(path, store)


def _same_eval(path: Path, store: Path) -> bool:
    """Whether the results file `path` is of the eval the session in `store` marks: read by
    its own eval tool or format, sharing at least half the questions of the smaller side
    (compared as text, and as marked-answers.csv holds them, which promptfoo's `echo` regrade
    gives back: promptfoo's are a dict of vars, Inspect AI's can be chat messages), never by
    an answer word for word (another eval's refusal can be this one's); with no questions on
    either side, an answer id made the same way. A tool
    read another way than one file at a time (judgekeeper.record()'s files, an MLflow store)
    is the same eval by its tool. A file it can't read (or read only in part: a table past
    table.MAX_ROWS) is never called another eval: the command that reads it says why. Never
    an error here."""
    import json

    ws = Workspace(store)
    try:
        tool = json.loads(ws.start.read_text(encoding="utf-8")).get("tool")
        held = [json.loads(line) for line in ws.pool.read_text(encoding="utf-8").splitlines()
                if line.strip()]
    except (OSError, ValueError, AttributeError, RecursionError):
        return True  # the session's own files: the command says what is wrong with them
    from judgekeeper import no_grades

    return same_questions(path, tool, held, answers=no_grades.here(ws))


def same_questions(path: Path, tool: str | None, held: list, answers: bool = False) -> bool:
    """Whether the results file `path` is of the eval of `tool` whose answers are `held`
    (dicts with input, output and id), as _same_eval says. `answers`: `held` are answers
    marked with no grade, so a table of answers with no grade is read as they were."""
    from judgekeeper import find, start, table
    from judgekeeper.records import RecordsError, derive_record_id

    kind = find.classify_file(path)
    answers = answers and kind == "table" and _answers(path)
    if not tool or kind is None:
        return False
    if kind not in ("table", "inspect", *start.FILE_READERS):
        return kind == tool
    try:  # another tool's file too: one with these answers is no other eval, only misread
        records = start._read(find.Result(kind, path, path.name, path.stat().st_size),
                              answers).records
    except (OSError, ValueError, TypeError, AttributeError, RecordsError, start.StartError,
            *start.UNREADABLE):
        return True  # the command says why it can't read it
    rows = ([(a.get("input"), a.get("output")) for a in records.answers] if answers
            else [(r.input, r.output) for r in records])  # answers with no grade: as marked
    if not rows or len(rows) >= table.MAX_ROWS:  # none or only the first rows read
        return True  # can't tell: the command says what it found
    held = [a for a in held if isinstance(a, dict)]
    # distinct questions, never rows: repeats (epochs) and one row per assertion multiply rows
    ours = {frozenset(f) for f in (_forms(a.get("input"), a.get("output")) - {""} for a in held)
            if f}
    questions = set().union(*ours)
    theirs = {frozenset(f) for f in (_forms(q, a) - {""} for q, a in rows) if f}
    if questions and theirs:  # an answer a refusal or a stock line gives is no sign; half of
        # the smaller side: the same eval run on more questions is still this one
        return 2 * sum(bool(f & questions) for f in theirs) >= min(len(ours), len(theirs))
    ids = {str(a.get("id")) for a in held}
    if answers:  # each answer's id made as the marked ones' were (start._answers_only)
        return any(str(a.get("id")) in ids for a in records.answers)
    try:
        return any(derive_record_id(r.input, r.output, r.trajectory) in ids for r in records)
    except (TypeError, ValueError):
        return True


def _forms(question, answer) -> set[str]:
    """A question as text to compare, both ways: as it is (_as_text), and as
    marked-answers.csv holds it (fix.question_text), which a grade of that file gives back."""
    from judgekeeper.fix import question_text

    try:
        return {_as_text(question), question_text(question, answer)}
    except (TypeError, ValueError, AttributeError, RecursionError):
        return {_as_text(question)}


def _as_text(value) -> str:
    """A question as text to compare: itself, or JSON with its keys in order (a dict of vars,
    a list of messages); "" for none."""
    import json

    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)


def is_project(folder: Path) -> bool:
    from judgekeeper import find

    return find.has_marker(folder)
