"""Find the eval tool a project uses and the results it saved. Standard library only.

`search(root)` looks in one folder and nowhere else: never the home folder, never a tool's
own database. It reads only the environment variables that say where a tool saves results
(DEEPEVAL_RESULTS_FOLDER, INSPECT_LOG_DIR, MLFLOW_TRACKING_URI), and only when they point
inside the folder. It never opens a `.env` file.

The rules:
- Skip `.git`, `node_modules`, virtual environments, package folders, `__pycache__`,
  `.judgekeeper` and every other hidden folder except `.deepeval`. Never follow a symbolic
  link, to a file or a folder. The one place read inside `.judgekeeper` is `records/`, where
  `judgekeeper.record()` writes the judge's verdicts (`*.jsonl`).
- Look in the known places first (the folder itself, `.deepeval/`, `logs/`, the folders the
  variables name), then walk to a depth of four folders. Stop after MAX_FILES files or
  MAX_SECONDS seconds and say so.
- To tell whether a `.json` file is results, read at most its first HEAD_BYTES, in at most
  MAX_JSON files. A table (CSV, TSV or JSONL with input, output and verdict columns) is read
  up to its header, and only TABLE_DEPTH folders deep.
- Results over MAX_BYTES are listed, not read.
- Nothing is written, and SQLite stores are opened read-only (by the reader, later).
"""

from __future__ import annotations

import csv
import io
import json
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

TOOLS = ("records", "promptfoo", "deepeval", "inspect", "mlflow", "table")
NAMES = {"records": "judgekeeper.record()", "promptfoo": "promptfoo", "deepeval": "DeepEval",
         "inspect": "Inspect AI", "mlflow": "MLflow", "table": "a plain table"}
EXTRAS = {"inspect": "inspect", "mlflow": "mlflow"}

MAX_FILES = 5000
MAX_SECONDS = 2
MAX_DEPTH = 4
MAX_JSON = 200
HEAD_BYTES = 64 * 1024
MAX_BYTES = 200 * 1000 * 1000
TABLE_DEPTH = 2

SKIP_DIRS = frozenset({".git", "node_modules", ".venv", "venv", "site-packages",
                       "dist-packages", "__pycache__", ".judgekeeper"})
HIDDEN_KEPT = ".deepeval"
RECORDS_DIR = Path(".judgekeeper") / "records"  # where judgekeeper.record() writes
PROMPTFOO_CONFIGS = ("promptfooconfig.yaml", "promptfooconfig.yml", "promptfooconfig.json")
DEEPEVAL_LATEST = ".latest_run_full.json"
DEEPEVAL_RUN = re.compile(r"test_run_(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})\.json")
VERDICT_COLUMNS = ("verdict", "judge_verdict", "judge")
TABLE_SUFFIXES = (".csv", ".tsv", ".jsonl")
RESULTS_VARS = {"deepeval": "DEEPEVAL_RESULTS_FOLDER", "inspect": "INSPECT_LOG_DIR"}
INSPECT_SKIP = "logs.json"  # Inspect's listing of a log folder, not a log

_DEPENDENCY = {"deepeval": re.compile(r"(?<![\w-])deepeval(?![\w-])", re.IGNORECASE),
               "inspect": re.compile(r"(?<![\w-])inspect[-_]ai(?![\w-])", re.IGNORECASE)}
_CREATED = re.compile(rb'"created"\s*:\s*"([^"]{10,40})"')


def _clock() -> float:
    return time.monotonic()


@dataclass
class Result:
    """One saved results file (or an MLflow store) found in the folder."""

    tool: str
    path: Path
    rel: str  # the path inside the folder, with forward slashes, for showing
    size: int = 0
    _date: datetime | None = field(default=None, repr=False, compare=False)

    @property
    def too_big(self) -> bool:
        return self.tool != "mlflow" and self.size > MAX_BYTES

    def too_big_message(self) -> str:
        return (f"{self.rel} is {self.size / 1_000_000:,.0f} MB. Run judgekeeper start "
                f"{self.rel} to read it anyway.")

    def date(self) -> datetime:
        """When the results were made: the tool's own date when the file has one, else the
        file's modified time. Always with a time zone."""
        if self._date is None:
            self._date = _made_at(self) or datetime.fromtimestamp(
                self.path.stat().st_mtime).astimezone()
        return self._date


@dataclass
class Search:
    root: Path
    results: dict[str, list[Result]] = field(default_factory=dict)
    signs: dict[str, list[str]] = field(default_factory=dict)  # tool -> configs, folders
    stopped: str | None = None  # why the walk stopped early, as a sentence
    notes: list[str] = field(default_factory=list)

    def readable(self, tool: str) -> list[Result]:
        return [r for r in self.results.get(tool, []) if not r.too_big]

    def too_big(self) -> list[Result]:
        return [r for rs in self.results.values() for r in rs if r.too_big]


# Reading as little as possible --------------------------------------------------------------

def _head(path: Path) -> bytes:
    with open(path, "rb") as f:
        return f.read(HEAD_BYTES)


def sniff_json(head: bytes) -> str | None:
    """The tool that wrote a JSON file, from its first bytes, or None."""
    text = head.decode("utf-8", errors="replace").lstrip("﻿ \t\r\n")
    if not text.startswith("{"):
        return None
    # Inspect first: its logs also have a "results" object (the scores) and "stats".
    if re.search(r'"eval"\s*:\s*\{', text) and re.search(r'"(status|samples)"\s*:', text):
        return "inspect"
    if re.search(r'"results"\s*:\s*\{', text) and re.search(
            r'"(evalId|promptfooVersion|prompts|stats)"\s*:', text):
        return "promptfoo"
    if re.search(r'"(testCases|conversationalTestCases|testRunData)"\s*:', text):
        return "deepeval"
    return None


def table_columns(path: Path) -> list[str]:
    """The column names of a CSV, TSV or JSONL file, from its first line only."""
    from judgekeeper.table import _delimiter

    text = _head(path).decode("utf-8", errors="replace").removeprefix("﻿")
    first = text.split("\n", 1)[0].rstrip("\r")
    if path.suffix.lower() == ".jsonl":
        try:
            row = json.loads(first)
        except ValueError:
            return []
        return list(row) if isinstance(row, dict) else []
    try:
        return next(csv.reader(io.StringIO(first),
                               delimiter=_delimiter(first, path.suffix.lower())), [])
    except csv.Error:
        return []


def is_table(columns) -> bool:
    columns = set(columns)
    outputs = "output" in columns or {"output_a", "output_b"} <= columns
    return "input" in columns and outputs and any(c in columns for c in VERDICT_COLUMNS)


def is_records(columns) -> bool:
    """A file of judgekeeper records, as judgekeeper.record() writes them."""
    return "annotator_kind" in columns or "schema_version" in columns


def classify_file(path: Path) -> str | None:
    """The tool whose results `path` is, or None. For a file named on the command line."""
    suffix = path.suffix.lower()
    if suffix == ".eval":
        return "inspect"
    if path.name == "mlflow.db":
        return "mlflow"
    if suffix == ".jsonl" and is_records(table_columns(path)):
        return "records"
    if suffix in TABLE_SUFFIXES:
        return "table" if is_table(table_columns(path)) else None
    if suffix == ".json":
        if DEEPEVAL_RUN.fullmatch(path.name) or path.name == DEEPEVAL_LATEST:
            return "deepeval"
        return sniff_json(_head(path))
    return None


def _made_at(result: Result) -> datetime | None:
    try:
        if result.tool == "promptfoo":
            from judgekeeper.textio import read_utf8

            data = json.loads(read_utf8(result.path, ValueError))
            stamp = (data.get("metadata") or {}).get("evaluationCreatedAt")
            return _parse_date(stamp)
        if result.tool == "deepeval":
            m = DEEPEVAL_RUN.fullmatch(result.path.name)
            return datetime(*map(int, m.groups())).astimezone() if m else None
        if result.tool == "inspect" and result.path.suffix.lower() == ".json":
            m = _CREATED.search(_head(result.path))
            return _parse_date(m[1].decode("utf-8", errors="replace")) if m else None
    except (OSError, ValueError, AttributeError):
        return None
    return None


def _parse_date(text) -> datetime | None:
    if not isinstance(text, str) or not text:
        return None
    try:
        return datetime.fromisoformat(text).astimezone()
    except ValueError:
        return None


# The walk ------------------------------------------------------------------------------------

class _Stop(Exception):
    pass


class _Walk:
    def __init__(self, root: Path):
        self.root = root
        self.search = Search(root=root)
        self.files = 0
        self.json_sniffed = 0
        self.seen_dirs: set[Path] = set()
        self.seen_files: set[Path] = set()
        self.started = _clock()

    def rel(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()

    def depth(self, path: Path) -> int:
        return len(path.relative_to(self.root).parts)

    def add(self, tool: str, path: Path, size: int = 0) -> None:
        found = self.search.results.setdefault(tool, [])
        if all(r.path != path for r in found):
            found.append(Result(tool, path, self.rel(path), size))

    def sign(self, tool: str, what: str) -> None:
        signs = self.search.signs.setdefault(tool, [])
        if what not in signs:
            signs.append(what)

    def tick(self) -> None:
        if self.files >= MAX_FILES:
            self.search.stopped = f"Stopped looking after {MAX_FILES:,} files."
            raise _Stop
        if _clock() - self.started > MAX_SECONDS:
            self.search.stopped = f"Stopped looking after {MAX_SECONDS} seconds."
            raise _Stop

    def file(self, entry: os.DirEntry) -> None:
        path = Path(entry.path)
        if path in self.seen_files:
            return
        self.tick()
        self.seen_files.add(path)
        self.files += 1
        try:
            self._classify(path, entry.name, entry.stat(follow_symlinks=False).st_size)
        except OSError:
            pass  # unreadable: not results

    def _classify(self, path: Path, name: str, size: int) -> None:
        lower = name.lower()
        suffix = path.suffix.lower()
        depth = self.depth(path)
        if lower in PROMPTFOO_CONFIGS:
            self.sign("promptfoo", self.rel(path))
        elif lower == "pyproject.toml" or (lower.startswith("requirements")
                                           and suffix == ".txt"):
            if depth <= TABLE_DEPTH and size <= HEAD_BYTES * 16:
                text = path.read_text(encoding="utf-8", errors="replace")
                for tool, pattern in _DEPENDENCY.items():
                    if pattern.search(text):
                        self.sign(tool, self.rel(path))
        elif name == "mlflow.db":
            self.add("mlflow", path, size)
        elif suffix == ".eval":
            self.add("inspect", path, size)
        elif suffix == ".json":
            if DEEPEVAL_RUN.fullmatch(name) or name == DEEPEVAL_LATEST:
                self.add("deepeval", path, size)
            elif name != INSPECT_SKIP and self.json_sniffed < MAX_JSON:
                self.json_sniffed += 1
                tool = sniff_json(_head(path))
                if tool:
                    self.add(tool, path, size)
        elif (suffix in TABLE_SUFFIXES and depth <= TABLE_DEPTH
              and is_table(table_columns(path))):
            self.add("table", path, size)

    def folder(self, path: Path) -> None:
        """Walk `path` breadth first, at most MAX_DEPTH folders below the root."""
        queue = [path]
        while queue:
            folder = queue.pop(0)
            if folder in self.seen_dirs:
                continue
            self.seen_dirs.add(folder)
            try:
                entries = sorted(os.scandir(folder), key=lambda e: e.name)
            except OSError:
                continue
            for entry in entries:
                if entry.is_symlink():
                    continue
                if entry.is_dir(follow_symlinks=False):
                    sub = Path(entry.path)
                    if entry.name == HIDDEN_KEPT:
                        self.sign("deepeval", self.rel(sub) + "/")
                    if entry.name == "mlruns":
                        self.add("mlflow", sub)
                        self.sign("mlflow", self.rel(sub) + "/")
                    elif _walked(entry.name) and self.depth(sub) <= MAX_DEPTH:
                        queue.append(sub)
                elif entry.is_file(follow_symlinks=False):
                    self.file(entry)


def _walked(name: str) -> bool:
    if name in SKIP_DIRS:
        return False
    return not name.startswith(".") or name == HIDDEN_KEPT


def _inside(root: Path, value: str | None) -> Path | None:
    """`value` as a folder inside `root`, or None."""
    if not value:
        return None
    path = Path(value)
    if not path.is_absolute():
        path = root / path
    try:
        path = path.resolve()
    except OSError:
        return None
    return path if path == root or root in path.parents else None


def _tracking_store(root: Path, uri: str | None) -> Path | None:
    """The local store MLFLOW_TRACKING_URI names, when it is inside `root`."""
    if not uri:
        return None
    for prefix in ("sqlite:///", "file://", ""):
        if uri.startswith(prefix) and (prefix or "://" not in uri):
            path = _inside(root, uri[len(prefix):])
            return path if path is not None and path.exists() else None
    return None


def search(root: str | Path) -> Search:
    """Every tool sign and saved result in `root`; see the module docstring for the rules."""
    root = Path(root).resolve()
    walk = _Walk(root)
    known = [root / ".deepeval", root / "logs"]
    for tool, var in RESULTS_VARS.items():
        value = os.environ.get(var)
        folder = _inside(root, value)
        if value and folder is None:
            walk.search.notes.append(f"{var} points outside this folder, so it was not read.")
        elif folder is not None:
            known.insert(0, folder)
            walk.sign(tool, var)
    store = _tracking_store(root, os.environ.get("MLFLOW_TRACKING_URI"))
    records = root / RECORDS_DIR
    try:
        if records.is_dir() and not records.is_symlink():
            for entry in sorted(os.scandir(records), key=lambda e: e.name):
                if (entry.name.endswith(".jsonl") and not entry.is_symlink()
                        and entry.is_file(follow_symlinks=False)):
                    walk.add("records", Path(entry.path), entry.stat().st_size)
        if store is not None and store.is_file():
            walk.add("mlflow", store, store.stat().st_size)
        elif store is not None and store.is_dir():
            walk.add("mlflow", store)
        for entry in sorted(os.scandir(root), key=lambda e: e.name):
            if entry.is_file(follow_symlinks=False) and not entry.is_symlink():
                walk.file(entry)
        for folder in known:
            if folder.is_dir() and not folder.is_symlink():
                walk.folder(folder)
        walk.folder(root)
    except _Stop:
        pass
    _drop_latest_copy(walk.search)
    return walk.search


def _drop_latest_copy(found: Search) -> None:
    """DeepEval writes `.latest_run_full.json` as a copy of its newest `test_run_*.json` when
    it keeps every run; then the copy is left out."""
    runs = found.results.get("deepeval", [])
    if any(DEEPEVAL_RUN.fullmatch(r.path.name) for r in runs):
        found.results["deepeval"] = [r for r in runs if r.path.name != DEEPEVAL_LATEST]
