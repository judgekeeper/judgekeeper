"""The pure parts of fixing the judge that `judgekeeper fix` (fix.py) uses. No AI call and no
key.

- The cells of a mark (the judge's group, and whether it agrees with the person) and their
  weights (cell_weights): rounding up per cell sets aside more of the few disagreements than
  of the many agreed answers, so the numbers on either part weigh each answer by its cell, not
  only its group.
- The pass mark that fits the person's marks best, for a judge whose decisions are a score held
  against a pass mark (choose_mark), and where that pass mark probably is in the person's own
  files (locate: a read-only search, nothing is imported or run).

judgekeeper never edits the person's own files: it only says where the pass mark probably is.
"""

from __future__ import annotations

import itertools
import os
import re
from collections import Counter
from pathlib import Path

from judgekeeper import weighted

# Folders never searched: environments, judgekeeper's own, and where eval tools keep their
# results (DeepEval's runs, MLflow's folder store, Inspect's logs)
SEARCH_SKIP = {".venv", "venv", "node_modules", ".git", ".judgekeeper", "__pycache__",
               ".deepeval", "mlruns", "logs"}
SEARCH_DEPTH = 4
SEARCH_MAX_BYTES = 1_000_000
SEARCH_MAX_FILES = 5000
_NUMBER = r"[-+]?(?:\d+\.?\d*|\.\d+)"


def _mark(x: float) -> str:
    return f"{x:g}"


# The split --------------------------------------------------------------------------------


def cell(m: dict) -> tuple[str, bool]:
    """The cell of a final mark: the judge's group, and whether the judge agrees with it."""
    return m["judge"], m["judge"] == m["final"]


def cell_weights(marks: list[dict], part: list[dict], pool: dict) -> dict:
    """The weight of an answer in each cell of `part` (the used or the set-aside answers of
    `marks`): the pool's group size times the cell's share of the group's marks, over the
    cell's answers in the part. The numbers on the part are then those of all the marks."""
    labeled = Counter(cell(m) for m in marks)
    groups = Counter(m["judge"] for m in marks)
    here = Counter(cell(m) for m in part)
    return {c: pool[c[0]] * labeled[c] / groups[c[0]] / k for c, k in here.items()}


# The pass mark ----------------------------------------------------------------------------

def nice_mark(low: float, high: float) -> float:
    """The shortest number strictly between two neighbouring scores, near their middle."""
    middle = (low + high) / 2
    for digits in range(1, 7):
        mark = round(middle, digits)
        if low < mark < high:
            return mark
    return middle


def choose_mark(items: list[tuple[str, str, float]], current: float, op: str,
                weights: dict) -> float:
    """The pass mark that fits (group, final mark, score) items best: the best weighted
    (TPR + TNR) / 2 among a point between each two neighbouring scores; on a tie, the one
    nearest the current mark, which wins its own ties."""
    from judgekeeper.start import passes

    def fit(mark):
        t = weighted._table([(g, label, passes(s, op, mark)) for g, label, s in items], weights)
        return None if t["tpr"] is None or t["tnr"] is None else (t["tpr"] + t["tnr"]) / 2

    scores = sorted({s for _, _, s in items})
    best, best_fit = current, fit(current)
    for low, high in itertools.pairwise(scores):
        mark = nice_mark(low, high)
        f = fit(mark)
        if f is None:
            continue
        if best_fit is None or f > best_fit + 1e-12 or (
                abs(f - best_fit) <= 1e-12 and abs(mark - current) < abs(best - current)):
            best, best_fit = mark, f
    return best


def where_lines(pm: dict, mark: float) -> list[str]:
    """Where the pass mark lives, by where it came from. judgekeeper changes none of it."""
    m = _mark(mark)
    source = pm["source"]
    if source == "deepeval":
        return [f"Set threshold={m} in your metric, e.g. GEval(..., threshold={m})."]
    if source == "records":
        return [f"Set pass_mark={m} in your judgekeeper.record() line."]
    if source == "mapped" and pm.get("key"):
        return [(f"Your eval writes its pass mark in {pm['key']}: set it to {m} where your "
                 "eval sets it.")]
    if source == "mapped":
        return [f"Set pass_mark = {m} in judgekeeper.toml [start]."]
    if source == "pass_if":  # double quotes work in Windows cmd too
        rule = re.sub(rf"{_NUMBER}\s*$", m, pm.get("rule") or f"score{pm['op']}0")
        return [f'Use --pass-if "{rule}".']
    # a pass mark kept with each verdict, read from another tool's files
    return [(f"Set pass_mark={m} in your judgekeeper.record() line, or pass_mark = {m} in "
             "judgekeeper.toml [start].")]


def searched(pm: dict) -> str | None:
    """The name the pass mark is set with in the project's files, or None when it is not
    set in them (--pass-if, or a key a mapped file states it in)."""
    if pm["source"] == "pass_if" or (pm["source"] == "mapped" and pm.get("key")):
        return None
    return "threshold" if pm["source"] == "deepeval" else "pass_mark"


def _files(root: Path):
    """The project's files to search, shallow folders first: at most SEARCH_DEPTH folders
    deep, skipping SEARCH_SKIP and links, each under SEARCH_MAX_BYTES."""
    level, seen = [root], 0
    for _ in range(SEARCH_DEPTH + 1):
        folders = []
        for folder in level:
            try:
                entries = sorted(os.scandir(folder), key=lambda e: e.name)
            except OSError:
                continue
            for e in entries:
                try:
                    if e.is_symlink():
                        continue
                    if e.is_dir():
                        if e.name not in SEARCH_SKIP:
                            folders.append(Path(e.path))
                        continue
                    small = e.is_file() and e.stat().st_size <= SEARCH_MAX_BYTES
                except OSError:  # gone, or not ours to look at
                    continue
                if small:
                    seen += 1
                    if seen > SEARCH_MAX_FILES:
                        return
                    yield Path(e.path)
        level = folders


def locate(root: Path, name: str, value: float) -> tuple[str, int, str] | None:
    """(file, line number, line) of the first `name = value` in the project's text files, or
    None. It only reads: nothing is imported or run."""
    pattern = re.compile(rf"\b{re.escape(name)}\s*=\s*({_NUMBER})")
    for path in _files(Path(root)):
        try:
            data = path.read_bytes()
        except OSError:
            continue
        if b"\0" in data[:8192]:
            continue
        for n, line in enumerate(data.decode("utf-8", errors="replace").splitlines(), 1):
            for m in pattern.finditer(line):
                try:
                    if abs(float(m[1]) - value) < 1e-9:
                        return path.relative_to(root).as_posix(), n, line.strip()
                except ValueError:
                    continue
    return None


__all__ = []
