"""Find the eval tool a project uses and the results it saved. Standard library only.

`search(root)` looks in one folder and nowhere else: never the home folder, never a tool's
own database. It reads only the environment variables that say where a tool saves results
(DEEPEVAL_RESULTS_FOLDER, INSPECT_LOG_DIR, MLFLOW_TRACKING_URI), and only when they point
inside the folder. It never opens a `.env` file.

The rules:
- Skip `.git`, `node_modules`, virtual environments, package folders, `__pycache__`,
  `.judgekeeper` and every other hidden folder except `.deepeval`. Never follow a symbolic
  link, to a file or a folder. The one place read inside `.judgekeeper` is `records/`, where
  `judgekeeper.record()` writes the judge's verdicts (`*.jsonl`); a records file elsewhere is
  found like a table.
- Look in the known places first (the folder itself, `.deepeval/`, `logs/`, the folders the
  variables name), then walk to a depth of four folders. Stop after MAX_FILES files or
  MAX_SECONDS seconds and say so.
- To tell whether a `.json` file is results, read at most its first HEAD_BYTES, in at most
  MAX_JSON files. A table (CSV, TSV or JSONL with input, output and verdict columns) is read
  up to its header, and only TABLE_DEPTH folders deep.
- Results over MAX_BYTES are listed, not read.
- In a project's folder (is_project), a folder below that is a project of its own (its own
  project file or `.judgekeeper/`) is not walked: its results are its own. It is kept in
  `nested`, and nested_results names the ones that hold results.
- DeepEval's hidden copies of its newest run count once; when a results folder holds its
  `test_run_*.json` files, those are read instead (_prefer_saved_runs).
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

from judgekeeper import textio

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
DEEPER = 4  # nothing found: folders further down where results-like files are named

SKIP_DIRS = frozenset({".git", "node_modules", ".venv", "venv", "site-packages",
                       "dist-packages", "__pycache__", ".judgekeeper"})
HIDDEN_KEPT = ".deepeval"
RECORDS_DIR = Path(".judgekeeper") / "records"  # where judgekeeper.record() writes
PROMPTFOO_CONFIGS = ("promptfooconfig.yaml", "promptfooconfig.yml", "promptfooconfig.json")
# DeepEval's hidden copies of its newest run, rewritten on every run: the full run, and the
# run under a "testRunData" key (deepeval/test_run/test_run.py, DeepEval 4.2).
DEEPEVAL_COPIES = (".latest_run_full.json", ".latest_test_run.json")
# A run DeepEval saved in its results folder: test_run_<date>_<time>.json, or before 3.9.9
# only <date>_<time>, with no .json (read when its content is a DeepEval run)
DEEPEVAL_RUN = re.compile(r"(?:test_run_)?(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})(?:\.json)?")
VERDICT_COLUMNS = ("verdict", "judge_verdict", "judge")
TABLE_SUFFIXES = (".csv", ".tsv", ".jsonl")
RESULTS_VARS = {"deepeval": "DEEPEVAL_RESULTS_FOLDER", "inspect": "INSPECT_LOG_DIR"}
INSPECT_SKIP = "logs.json"  # Inspect's listing of a log folder, not a log
DEEPEVAL_TEMP = ".temp_test_run_data.json"  # DeepEval's file while a run goes on, not results

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

    def too_big_message(self, program: str | None = None) -> str:
        program = program or textio.program()
        return (f"{self.rel} is {self.size / 1_000_000:,.0f} MB. Run {program} "
                f"{self.rel} to read it anyway.")

    def run_date(self) -> datetime | None:
        """The tool's own date for the results, when the file has one."""
        return _made_at(self)

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
    unreadable: list[tuple[str, str]] = field(default_factory=list)  # results-like: (rel, how)
    skipped: list[tuple[str, str]] = field(default_factory=list)  # results-like, not looked in
    nested: list[Path] = field(default_factory=list)  # projects of their own, not walked

    def readable(self, tool: str) -> list[Result]:
        return [r for r in self.results.get(tool, []) if not r.too_big]

    def too_big(self) -> list[Result]:
        return [r for rs in self.results.values() for r in rs if r.too_big]


# Reading as little as possible --------------------------------------------------------------

def _head(path: Path) -> bytes:
    with open(path, "rb") as f:
        return f.read(HEAD_BYTES)


_RESULTS_WORDS = re.compile(r"result|output|eval|judg|score|verdict", re.IGNORECASE)


def _results_like(path: Path) -> bool:
    """A file judgekeeper would read if it could: one whose name says results."""
    suffix = path.suffix.lower()
    return ((suffix in (".json", ".eval") or suffix in TABLE_SUFFIXES)
            and bool(_RESULTS_WORDS.search(path.stem)))


def sniff_json(head: bytes) -> str | None:
    """The tool that wrote a JSON file, from its first bytes, or None."""
    text = head.decode("utf-8", errors="replace").lstrip("﻿ \t\r\n")
    if not text.startswith("{"):
        return None
    # Inspect first: its logs also have a "results" object (the scores) and "stats". An "eval"
    # that is not an object is still Inspect's, damaged, and its reader says so.
    if (re.search(r'"eval"\s*:', text) and re.search(r'"(status|samples)"\s*:', text)
            and not re.search(r'"(evalId|promptfooVersion)"\s*:', text)):
        return "inspect"
    if re.search(r'"results"\s*:\s*\{', text) and re.search(
            r'"(evalId|promptfooVersion|prompts|stats)"\s*:', text):
        return "promptfoo"
    if re.search(r'"results"\s*:', text) and re.search(r'"(evalId|promptfooVersion)"\s*:', text):
        return "promptfoo"  # of the wrong shape: its reader says what is wrong
    if re.search(r'"(testCases|conversationalTestCases|testRunData)"\s*:', text):
        return "deepeval"
    if re.match(r'\{\s*"head"\s*:\s*\{', text) and re.search(r'"body"\s*:\s*\[', text):
        return PROMPTFOO_TABLE
    return None


PROMPTFOO_TABLE = "promptfoo-table"  # `promptfoo eval -o table.json`: no judge's decisions
TABLE_OUTPUT = "is promptfoo's table output, which doesn't keep the judge's own decisions"


def table_columns(path: Path) -> list[str]:
    """The column names of a CSV, TSV or JSONL file, from its first line only, judgekeeper's
    own written as it knows them (table.column_name: "Input " is input)."""
    from judgekeeper.table import _delimiter, column_name

    text = _head(path).decode("utf-8", errors="replace").removeprefix("﻿")
    first = re.split(r"\r\n|\r|\n", text, maxsplit=1)[0]  # a CR-only file too
    if path.suffix.lower() == ".jsonl" and "\n" not in text:  # a first line over HEAD_BYTES
        with path.open("rb") as f:
            first = f.readline(MAX_BYTES).decode("utf-8", errors="replace")
        first = first.removeprefix("﻿").rstrip("\r\n")
    if path.suffix.lower() == ".jsonl":
        try:
            row = json.loads(first)
        except ValueError:
            return []
        return [column_name(c) for c in row] if isinstance(row, dict) else []
    try:
        return [column_name(c) for c in next(csv.reader(
            io.StringIO(first), delimiter=_delimiter(first, path.suffix.lower())), [])]
    except csv.Error:
        return []


def is_table(columns) -> bool:
    columns = set(columns)
    outputs = "output" in columns or {"output_a", "output_b"} <= columns
    return "input" in columns and outputs and any(c in columns for c in VERDICT_COLUMNS)


def title_row(path: Path) -> bool:
    """A CSV or TSV whose first row is a title, not the header: its second row reads as the
    header of a table."""
    from judgekeeper.table import _delimiter, column_name

    if path.suffix.lower() not in (".csv", ".tsv"):
        return False
    text = _head(path).decode("utf-8", errors="replace").removeprefix("﻿")
    lines = re.split(r"\r\n|\r|\n", text, maxsplit=2)
    if len(lines) < 3:
        return False
    try:
        second = next(csv.reader(io.StringIO(lines[1]),
                                 delimiter=_delimiter(lines[1], path.suffix.lower())), [])
    except csv.Error:
        return False
    return not is_table(table_columns(path)) and is_table([column_name(c) for c in second])


def is_records(columns) -> bool:
    """A file of judgekeeper records, as judgekeeper.record() writes them."""
    return "annotator_kind" in columns or "schema_version" in columns


def is_mlflow_folder(path: Path) -> bool:
    """Whether `path` is an MLflow folder store (`mlruns/`): it holds an experiment folder
    with meta.yaml. Its name is not enough: with an `mlflow.db` store, MLflow keeps logged
    artifacts in `./mlruns/<experiment>/<run>/artifacts`, a folder of the same name with no
    meta.yaml, which is not a store (and `.trash` is made by reading one)."""
    if not path.is_dir():
        return False
    try:
        return any(d.is_dir() and d.name.isdigit() and (d / "meta.yaml").is_file()
                   for d in path.iterdir())
    except OSError:
        return False


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
        if DEEPEVAL_RUN.fullmatch(path.name) or path.name in DEEPEVAL_COPIES:
            return "deepeval"
        tool = sniff_json(_head(path))
        return None if tool == PROMPTFOO_TABLE else tool
    if not suffix and DEEPEVAL_RUN.fullmatch(path.name) and sniff_json(_head(path)) == "deepeval":
        return "deepeval"  # DeepEval before 3.9.9: results/<date>_<time>
    return None


def is_promptfoo_table(path: Path) -> bool:
    try:
        return path.suffix.lower() == ".json" and sniff_json(_head(path)) == PROMPTFOO_TABLE
    except OSError:
        return False


def _made_at(result: Result) -> datetime | None:
    try:
        if result.tool == "promptfoo":
            data = textio.read_json(result.path, ValueError)
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
        self.project = is_project(root)  # a folder below that is a project is not walked
        self.files = 0
        self.json_sniffed = 0
        self.seen_dirs: set[Path] = set()
        self.seen_files: set[Path] = set()
        self.started = _clock()
        self.edge: list[Path] = []  # folders one below MAX_DEPTH, not walked

    def skip(self, path: Path, why: str, rel: str | None = None) -> None:
        """A results-like file the walk does not read: said when nothing is found."""
        item = (rel or self.rel(path), why)
        if item not in self.search.skipped:
            self.search.skipped.append(item)

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
            size = entry.stat(follow_symlinks=False).st_size
            if size == 0 and _results_like(path):
                self.search.unreadable.append((self.rel(path), "is empty"))
                return
            self._classify(path, entry.name, size)
        except PermissionError:
            if _results_like(path):
                denied = "can't be read: permission denied"
                self.search.unreadable.append((self.rel(path), denied))
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
        elif (not suffix and DEEPEVAL_RUN.fullmatch(name)
              and sniff_json(_head(path)) == "deepeval"):  # DeepEval before 3.9.9
            self.add("deepeval", path, size)
        elif suffix == ".json":
            if DEEPEVAL_RUN.fullmatch(name) or name in DEEPEVAL_COPIES:
                self.add("deepeval", path, size)
            elif name not in (INSPECT_SKIP, DEEPEVAL_TEMP) and self.json_sniffed < MAX_JSON:
                self.json_sniffed += 1
                tool = sniff_json(_head(path))
                if tool == PROMPTFOO_TABLE:
                    self.search.unreadable.append((self.rel(path), TABLE_OUTPUT))
                elif tool:
                    self.add(tool, path, size)
        elif suffix in TABLE_SUFFIXES and depth <= TABLE_DEPTH:
            if _head(path)[:2] in (b"\xff\xfe", b"\xfe\xff"):  # UTF-16: not read, but said
                self.skip(path, NOT_UTF8)
                return
            columns = table_columns(path)
            if suffix == ".jsonl" and is_records(columns):  # record()'s format, moved
                self.add("records", path, size)
            elif is_table(columns):
                self.add("table", path, size)
            elif title_row(path):
                self.search.unreadable.append((self.rel(path), TITLE_ROW))
        elif suffix in TABLE_SUFFIXES and _results_like(path):  # deeper than tables are read
            columns = table_columns(path)
            if is_table(columns) or (suffix == ".jsonl" and is_records(columns)):
                self.skip(path, _down(depth - 1))

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
                    if _results_like(Path(entry.path)) and entry.is_file():
                        self.skip(Path(entry.path), LINK)
                    continue
                if entry.is_dir(follow_symlinks=False):
                    sub = Path(entry.path)
                    if entry.name == HIDDEN_KEPT:
                        self.sign("deepeval", self.rel(sub) + "/")
                    if entry.name == "mlruns":
                        if is_mlflow_folder(sub):  # else only mlflow.db's artifacts
                            self.add("mlflow", sub)
                            self.sign("mlflow", self.rel(sub) + "/")
                    elif _walked(entry.name) and self.project and is_project(sub):
                        if sub not in self.search.nested:
                            self.search.nested.append(sub)
                    elif _walked(entry.name) and self.depth(sub) <= MAX_DEPTH:
                        queue.append(sub)
                    elif _walked(entry.name):
                        self.edge.append(sub)
                elif entry.is_file(follow_symlinks=False):
                    self.file(entry)


# judgekeeper's own output folders: 0.1's report folder (anchors.jsonl looks like a table)
# and 0.1.3's demo data. They are never "your LLM-as-a-judge" or "your own format".
OWN_FOLDERS = ("judgekeeper-report",)
OWN_PREFIXES = ("judgekeeper-demo",)


def _walked(name: str) -> bool:
    if name in SKIP_DIRS or name in OWN_FOLDERS or name.startswith(OWN_PREFIXES):
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


def records_above(folder: str | Path) -> Path | None:
    """The project root above `folder` whose .judgekeeper/records/ holds files that
    judgekeeper.record() wrote, found by record()'s own rule (recorder.project_root), when that
    is not `folder` itself; else None. record() saves there from any subfolder."""
    from judgekeeper.recorder import project_root

    folder = Path(folder).resolve()
    root = project_root(folder)
    if root == folder:
        return None
    records = root / RECORDS_DIR
    try:
        if records.is_dir() and not records.is_symlink() and any(
                p.suffix == ".jsonl" and p.is_file() for p in records.iterdir()):
            return root
    except OSError:
        return None
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
    _prefer_saved_runs(walk.search)
    if not any(walk.search.results.values()) and walk.search.stopped is None:
        _look_deeper(walk)
        _look_above(walk)
    return walk.search


LINK = "a link: judgekeeper doesn't follow links"
ABOVE = "in the folder above"
NOT_UTF8 = "not saved as UTF-8: save it as UTF-8"
TITLE_ROW = "has a title row above its header"
EXCEL = (".xlsx", ".xlsm", ".xls")
PROJECT_MARKERS = ("pyproject.toml", "package.json", ".git", "judgekeeper.toml", "setup.py")


def is_project(folder: Path) -> bool:
    """Whether `folder` is a project's own: a project file (PROJECT_MARKERS) or its own
    `.judgekeeper/`."""
    try:
        return any((folder / m).exists() for m in (*PROJECT_MARKERS, ".judgekeeper"))
    except OSError:
        return False


def nested_results(found: Search) -> list[str]:
    """The projects below the folder searched (`found.nested`) that hold results judgekeeper
    reads, by their path from it."""
    out = []
    for folder in found.nested:
        inner = search(folder)
        if any(inner.readable(t) for t in TOOLS) or inner.too_big():
            out.append(folder.relative_to(found.root).as_posix())
    return out


def _down(n: int) -> str:
    return f"{n} folder down" if n == 1 else f"{n} folders down"


def looked(root: Path) -> str:
    """How far the walk looks, said when nothing is found."""
    return f"{_down(MAX_DEPTH)} from {root.name} (tables: {_down(TABLE_DEPTH - 1)})"


def _look_deeper(walk: _Walk) -> None:
    """Nothing found: name results-like files up to DEEPER folders below where the walk
    stopped, by their names only, within the walk's own limits."""
    queue, files, started = list(walk.edge), 0, _clock()
    while queue:
        folder = queue.pop(0)
        try:
            entries = sorted(os.scandir(folder), key=lambda e: e.name)
        except OSError:
            continue
        for entry in entries:
            if files >= MAX_FILES or _clock() - started > MAX_SECONDS:
                return
            if entry.is_symlink():
                continue
            path = Path(entry.path)
            if entry.is_dir(follow_symlinks=False):
                if _walked(entry.name) and walk.depth(path) <= MAX_DEPTH + DEEPER:
                    queue.append(path)
            elif entry.is_file(follow_symlinks=False):
                files += 1
                if _results_like(path) or entry.name == "mlflow.db":
                    walk.skip(path, _down(walk.depth(path) - 1))


def project_folder(folder: Path) -> Path | None:
    """The nearest folder above `folder` that looks like a project's own (PROJECT_MARKERS),
    below the home folder; None when there is none."""
    try:
        home = Path.home().resolve()
    except (RuntimeError, OSError):
        home = None
    for above in folder.parents:
        if above == home:
            return None
        try:
            if any((above / m).exists() for m in PROJECT_MARKERS):
                return above
        except OSError:
            return None
    return None


def results_above(root: Path) -> Path | None:
    """The project folder above `root` when it holds results judgekeeper reads."""
    up = project_folder(root)
    if up is None:
        return None
    found = search(up)
    return up if any(found.readable(t) for t in TOOLS) or found.too_big() else None


def _look_above(walk: _Walk) -> None:
    """Nothing found and no project folder above: name results-like files in the folder
    just above."""
    root = walk.root
    if root.parent == root or project_folder(root) is not None:
        return
    try:
        if root.parent == Path.home().resolve():
            return
        entries = sorted(os.scandir(root.parent), key=lambda e: e.name)
    except (OSError, RuntimeError):
        return
    for entry in entries:
        path = Path(entry.path)
        if not entry.is_symlink() and entry.is_file() and _results_like(path):
            walk.skip(path, ABOVE, rel=f"../{entry.name}")


def _run_of(path: Path):
    """The test cases of a DeepEval run file, for comparing two files; None when unreadable."""
    try:
        if path.stat().st_size > MAX_BYTES:
            return None
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError, RecursionError):
        return None
    if isinstance(data, dict) and isinstance(data.get("testRunData"), dict):
        data = data["testRunData"]
    if not isinstance(data, dict) or "testRunLink" in data and "testCases" not in data:
        return None  # not a run, or only the link to it on Confident AI
    return data.get("testCases"), data.get("conversationalTestCases")


NEWEST_RUN = ("Read DeepEval's newest run, {read} ({read_day}). {other} holds an older run "
              "({other_day}); to check it, run `{command}`.")


def _day(result: Result) -> str:
    """"1 Oct", in local time."""
    day = result.date().astimezone()
    return f"{day.day} {MONTHS[day.month - 1]}"


MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _prefer_saved_runs(found: Search) -> None:
    """DeepEval's hidden copies (DEEPEVAL_COPIES) count once per folder: the full run when it
    is there (the other may hold only a link to the run on Confident AI), else the other. When
    a results folder holds `test_run_*.json` files too, the newest run by time is read, the
    copy or the results folder's, and a note names the other with both dates."""
    runs = found.results.get("deepeval", [])
    copies: dict[Path, Result] = {}
    for r in runs:
        if r.path.name in DEEPEVAL_COPIES:
            kept = copies.get(r.path.parent)
            if kept is None or r.path.name == DEEPEVAL_COPIES[0]:
                copies[r.path.parent] = r
    saved = [r for r in runs if DEEPEVAL_RUN.fullmatch(r.path.name)]
    if saved:
        newest = max(saved, key=lambda r: r.date())
        for copy in list(copies.values()):
            theirs, ours = _run_of(copy.path), _run_of(newest.path)
            if theirs is None or ours is None or theirs == ours:
                continue
            read, other = (copy, newest) if copy.date() > newest.date() else (newest, copy)
            found.notes.append(NEWEST_RUN.format(
                read=read.rel, read_day=_day(read), other=other.rel, other_day=_day(other),
                command=f"{textio.program()} {textio.quote_arg(other.rel)}"))
            if read is copy:  # the results folder's runs are older: the copy is read alone
                runs = [r for r in runs if r not in saved]
                break
        else:
            copies = {}
    if "deepeval" in found.results:
        found.results["deepeval"] = [r for r in runs if r.path.name not in DEEPEVAL_COPIES
                                     or r in copies.values()]
