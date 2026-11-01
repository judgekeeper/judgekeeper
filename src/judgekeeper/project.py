"""The project folder of a path, and starting over: moving a check to previous-<date>/
(`--new`; nothing is deleted).
"""

from __future__ import annotations

from pathlib import Path

from judgekeeper import marks
from judgekeeper.fingerprint import utc_now
from judgekeeper.start_label import (
    FOLDER,
    Workspace,
)
from judgekeeper.textio import PRIVATE_FOLDER

# Not part of a check: .gitignore, baseline.json (set by `baseline set`), records/
# (judgekeeper.record()); and what `judgekeeper check` keeps across marks: history.jsonl and
# the verdicts of each judge setup (verdicts/)
KEPT = (".gitignore", "baseline.json", "records", "history.jsonl", "verdicts")
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
    target.mkdir(mode=PRIVATE_FOLDER)
    what = ("your last check" if ws.result_json.is_file()  # a result was made
            else "your marks" if ws.marks.is_file() and marks.read(ws.marks).counted()
            else "your saved answers")
    for p in entries:
        p.replace(target / p.name)
    say(f"Moved {what} to {FOLDER}/{target.name}/. Nothing was deleted.")
    return target


def project_of(path: Path) -> Path:
    """The project folder every command keeps .judgekeeper/ in. A results file or an MLflow
    store given as the path never moves it: it is found from the folder the command runs in.
    From there (or the folder given), the nearest folder up whose .judgekeeper/ holds marks,
    without leaving the project (a folder with find.PROJECT_MARKERS); else the folder
    itself, the same with a path given or not."""
    from judgekeeper import find

    given = path.is_file() or find.is_mlflow_folder(path)
    here = Path.cwd().resolve() if given else path.resolve()
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
    return here


def is_project(folder: Path) -> bool:
    from judgekeeper import find

    try:
        return any((folder / m).exists() for m in find.PROJECT_MARKERS)
    except OSError:
        return False
