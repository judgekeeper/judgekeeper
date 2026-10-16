"""What the 1.0 commands keep from running judgekeeper again: moving a check to
previous-<date>/ (`--new`; nothing is deleted), the person's marks, the project folder of a
path, and what changed in the judge's identity, in words.
"""

from __future__ import annotations

from pathlib import Path

from judgekeeper import marks
from judgekeeper.fingerprint import utc_now
from judgekeeper.start_label import (
    FOLDER,
    Workspace,
)

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
    target.mkdir()
    for p in entries:
        p.replace(target / p.name)
    say(f"Moved your last check to {FOLDER}/{target.name}/. Nothing was deleted.")
    return target


def _labels(ws: Workspace) -> dict[str, str]:
    """{answer id: pass or fail} from marks.jsonl: the person's Pass and Fail marks."""
    return marks.read(ws.marks).counted()


def _project(path: Path) -> Path:
    """The project folder: the folder of a results file or of an MLflow store given as the
    path, so .judgekeeper/ is never made inside an mlruns/ folder."""
    from judgekeeper import find

    if path.is_file() or find.is_mlflow_folder(path):
        return path.resolve().parent
    return path.resolve()


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


