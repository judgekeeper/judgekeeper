"""The folder rules (tests/test_folder_matrix.py's I1-I6), held over random folder trees, plus:

I7 a run never crashes (no exception, no "hit a problem it didn't expect");
I8 every command a run prints, pasted where its line says, does what the line says: it parses,
   any file or folder it names is there, and one that reads results finds results.

Each seed makes one tree (depth up to 5, 2-8 folders). Each folder gets a kind (nothing, a
project file, code, .git, a judge.json-only .judgekeeper/, a stray script), maybe results (CSV,
JSONL, promptfoo, DeepEval, Inspect) or answers with no grade, maybe a link to a file or folder,
maybe a session made by a real run (and then, maybe, a newer file of other questions). Results
share questions with another folder's or not; every file gets its own time. Then judgekeeper
runs once in a random folder (plain, `.`, a named file or `--tool X`) and every command it
prints is run in turn.

CI runs FIXED seeds. JK_FUZZ=5000 runs that many (JK_FUZZ_START sets the first; JK_FUZZ=seeds=
3,7 runs those); each failure
is shrunk to the smallest tree that still breaks the same rule, and JK_FUZZ_REPORT=<file>
collects them as JSON lines. No page opens: the page is served in a thread (conftest's
pages)."""

from __future__ import annotations

import csv
import dataclasses
import importlib.util
import json
import os
import random
import re
import shlex
import time
import traceback
from pathlib import Path

import pytest

from judgekeeper import cli, front, project
from tests.start_projects import (
    answer,
    deepeval_project,
    inspect_project,
    promptfoo_project,
    question,
    split,
    table_project,
)
from tests.test_front import flat

FIXED = (*range(13), 35, 100, 135, 201, 207)  # 12 and up: layouts once found here
KINDS = ("plain", "plain", "file", "code", "git", "judged", "script")
CONTENTS = ("none", "none", "csv", "jsonl", "promptfoo", "deepeval", "inspect", "answers")
NAMES = ("a", "b", "c", "data", "evals", "proj", "sub", "runs", "my evals")
PROJECT_FILES = ("pyproject.toml", "package.json", "requirements.txt", "setup.py",
                 "judgekeeper.toml")
CODE_FILES = ("app.py", "index.js", "main.ts")
CODE = (".py", ".js", ".ts")
HAS_INSPECT = importlib.util.find_spec("inspect_ai") is not None
NONE_FOUND = ("No eval results found", "No saved", "There is no file", "There is no folder")
READS_ELSEWHERE = ("mark", "check", "fix", "measure")
STARTS_OVER = ("Starting a new project here? Run",)  # finds nothing until answers are there
TOOLS_ = ("records", "promptfoo", "deepeval", "inspect", "mlflow", "table")


@dataclasses.dataclass
class Folder:
    path: str  # below the top, posix; "" is the top
    kind: str = "plain"
    content: str = "none"
    tag: str = ""
    rows: int = 12
    link: str = ""  # "file:<folder>", "dir:<folder>", "file:@out", "dir:@out"
    session: bool = False
    late: str = ""  # after the session: other.jsonl "beside" or in "more/"
    age: int = 0  # minutes before now


@dataclasses.dataclass
class Tree:
    folders: list[Folder]
    run_in: str
    argv: tuple[str, ...]


# The tree -----------------------------------------------------------------------------------

def generate(seed: int) -> Tree:
    rng = random.Random(seed)
    folders = [Folder("")]
    for _ in range(rng.randint(1, 7)):
        parents = [f for f in folders if f.path.count("/") < 4 or f.path == ""]
        parent = rng.choice(parents).path
        taken = {f.path for f in folders}
        name = rng.choice([n for n in NAMES if _join(parent, n) not in taken] or ["z"])
        if _join(parent, name) not in taken:
            folders.append(Folder(_join(parent, name)))
    tags = []
    for f in folders:
        f.kind = rng.choice(KINDS)
        f.content = rng.choice(CONTENTS)
        if f.content != "none":
            f.tag = rng.choice(tags) if tags and rng.random() < 0.4 else f"t{len(tags)}"
            tags.append(f.tag)
            f.rows = rng.choice((6, 12, 40))
            f.session = rng.random() < 0.3
            if f.session and rng.random() < 0.5:
                f.late = rng.choice(("beside", "more"))
        if rng.random() < 0.2:
            others = [o.path for o in folders if o is not f]
            target = rng.choice(others + ["@out"])
            f.link = f"{rng.choice(('file', 'dir'))}:{target}"
        f.age = rng.randint(0, 3000)
    run_in = rng.choice(folders).path
    how = rng.choice(("plain", "plain", "dot", "named", "tool"))
    argv: tuple[str, ...] = ()
    if how == "dot":
        argv = (".",)
    elif how == "tool":
        argv = ("--tool", rng.choice(("promptfoo", "deepeval", "inspect", "table")))
    elif how == "named":
        files = [f for f in folders if f.content not in ("none", "answers")]
        if files:
            f = rng.choice(files)
            argv = (os.path.relpath(_file_of(f), run_in or ".").replace(os.sep, "/"),)
    return Tree(folders, run_in, argv)


def _join(parent: str, name: str) -> str:
    return f"{parent}/{name}" if parent else name


def _file_of(f: Folder) -> str:
    """The results file a folder's content writes, below the top."""
    name = {"csv": "results.csv", "jsonl": "results.jsonl", "promptfoo": "results.json",
            "deepeval": ".deepeval/.latest_run_full.json",
            "inspect": "logs/2026-10-02_support.json" if HAS_INSPECT else "results.csv",
            "answers": "answers.csv"}[f.content]
    return _join(f.path, name)


def _write_content(folder: Path, f: Folder) -> None:
    verdicts = split(f.rows // 2, f.rows - f.rows // 2)
    content = "csv" if f.content == "inspect" and not HAS_INSPECT else f.content
    if content == "csv":
        table_project(folder, verdicts, tag=f.tag)
    elif content == "jsonl":
        (folder / "results.jsonl").write_text("".join(
            json.dumps({"input": question(i, f.tag), "output": answer(i, f.tag),
                        "verdict": "pass" if v else "fail"}) + "\n"
            for i, v in enumerate(verdicts)), encoding="utf-8")
    elif content == "promptfoo":
        promptfoo_project(folder, verdicts, tag=f.tag, config=f.rows != 6)
    elif content == "deepeval":
        deepeval_project(folder, verdicts, tag=f.tag)
    elif content == "inspect":
        inspect_project(folder, verdicts, tag=f.tag)
    elif content == "answers":
        with (folder / "answers.csv").open("w", newline="", encoding="utf-8") as out:
            w = csv.writer(out)
            w.writerow(["input", "output"])
            w.writerows([question(i, f.tag), answer(i, f.tag)] for i in range(f.rows))


def _write_kind(folder: Path, f: Folder) -> None:
    pick = sum(map(ord, f.path))
    if f.kind == "file":
        (folder / PROJECT_FILES[pick % len(PROJECT_FILES)]).write_text("", encoding="utf-8")
    elif f.kind == "code":
        (folder / CODE_FILES[pick % len(CODE_FILES)]).write_text("", encoding="utf-8")
    elif f.kind == "script":
        (folder / "script.py").write_text("", encoding="utf-8")
    elif f.kind == "git":
        (folder / ".git").mkdir(exist_ok=True)
    elif f.kind == "judged":
        (folder / ".judgekeeper").mkdir(exist_ok=True)
        (folder / ".judgekeeper" / "judge.json").write_text("{}", encoding="utf-8")


def _age(folder: Path, minutes: int) -> None:
    when = time.time() - minutes * 60
    for p in folder.rglob("*"):
        if p.is_file() and not p.is_symlink() and ".judgekeeper" not in p.parts:
            os.utime(p, (when, when))


class World:
    """One tree built in `base`: home/t is the top, outside/ a folder away from home."""

    def __init__(self, base: Path, monkeypatch, capsys):
        self.base, self.monkeypatch, self.capsys = base, monkeypatch, capsys
        self.home = base / "home"
        self.top = self.home / "t"
        self.out = base / "outside"
        self.tags: dict[Path, str] = {}
        self.sessions: dict[Path, set[Path]] = {}
        self.reads: list[tuple[Path, list[Path]]] = []
        self.runs: list[dict] = []

        def spy(talk, path):
            found, saved = _REAL_FIND(talk, path)
            used = [r.path for r in found.results if r.rel in found.used] or \
                [r.path for r in found.results]
            self.reads.append((Path(os.path.abspath(found.root)),
                               [Path(os.path.abspath(p)) for p in used]))
            return found, saved

        monkeypatch.setattr(front, "find_found", spy)

    def build(self, tree: Tree) -> None:
        self.monkeypatch.setattr("pathlib.Path.home", lambda: self.home)
        table_project(self.out / "data", split(20, 20), tag="out")
        self.tags[self.out / "data" / "results.csv"] = "out"
        for f in tree.folders:
            folder = self.top / f.path
            folder.mkdir(parents=True, exist_ok=True)
            _write_kind(folder, f)
            if f.content != "none":
                _write_content(folder, f)
                self.tags[self.top / _file_of(f)] = f.tag
            _age(folder, f.age)
        for f in tree.folders:
            if f.link:
                self._link(tree, f)
        for f in tree.folders:  # a session started by a real run there
            if f.session and f.content != "none":
                self.reads.clear()
                code, _ = self.run(self.top / f.path, (), "session")
                if code == 0 and self.reads:
                    self.sessions[(self.top / f.path)] = set(self.reads[-1][1])
                if f.late:
                    more = self.top / f.path / ("more" if f.late == "more" else "")
                    more.mkdir(exist_ok=True)
                    other = more / "other.jsonl"
                    other.write_text("".join(json.dumps(
                        {"input": f"Unrelated {i}?", "output": f"Other {i}."}) + "\n"
                        for i in range(15)), encoding="utf-8")
                    later = time.time() + 60
                    os.utime(other, (later, later))
                    self.tags[other] = "late"

    def _link(self, tree: Tree, f: Folder) -> None:
        what, target = f.link.split(":", 1)
        if target == "@out":
            to = self.out / "data" / ("results.csv" if what == "file" else "")
        else:
            other = next((o for o in tree.folders if o.path == target), None)
            if other is None:
                return
            if what == "file":
                if other.content == "none":
                    return
                to = self.top / _file_of(other)
            else:
                to = self.top / target
        name = "linked.csv" if what == "file" else "linked"
        if what == "file" and to.suffix != ".csv":
            name = f"linked{to.suffix}"
        try:
            (self.top / f.path / name).symlink_to(to.resolve(), target_is_directory=what == "dir")
        except (OSError, NotImplementedError):
            return  # no links here (Windows without the right)

    # A run ----------------------------------------------------------------------------------

    def run(self, folder: Path, argv: tuple, why: str) -> tuple[int, str]:
        """judgekeeper run in `folder`; its invariants are checked and kept in self.runs."""
        before = self.files()
        empty = folder.is_dir() and not any(folder.iterdir())
        self.monkeypatch.chdir(folder)
        project.forget()
        _fresh(self.monkeypatch)
        self.reads.clear()
        crash = ""
        try:
            code = cli.main([*argv, "--no-browser", "--port", "0"])
        except BaseException as e:  # a crash is what I7 looks for
            if isinstance(e, KeyboardInterrupt):
                raise
            code, crash = -1, "".join(traceback.format_exception(e))[-1500:]
        out, err = self.capsys.readouterr()
        said = flat(out + err)
        broken = self.check(folder, argv, before, said, code, crash, empty)
        self.runs.append({"why": why, "in": self.rel(folder), "argv": list(argv), "code": code,
                          "broken": broken, "said": said})
        return code, said

    def files(self) -> dict[str, tuple[int, int]]:
        found = {}
        for root in (self.top, self.out):
            for p in root.rglob("*"):
                if ".git" in p.parts or p.is_symlink() or not p.is_file():
                    continue
                s = p.stat()
                found[p.as_posix()] = (s.st_size, s.st_mtime_ns)
        return found

    def rel(self, p: Path) -> str:
        try:
            return "t/" + p.relative_to(self.top).as_posix()
        except ValueError:
            return p.as_posix()

    def check(self, folder: Path, argv: tuple, before, said: str, code: int, crash: str,
              empty: bool) -> list[str]:
        broken = []
        if crash or "didn't expect" in said:
            broken.append(f"I7: exit {code} {crash}")
        after = self.files()
        changed = sorted(p for p in set(before) | set(after) if before.get(p) != after.get(p))
        named = any(Path(a).suffix for a in argv if not a.startswith("-"))
        if not self.reads:
            if changed:
                broken.append(f"I4: read nothing, wrote {[self.rel(Path(p)) for p in changed]}")
            return broken
        root, files = self.reads[-1]
        for f in files:  # I1
            inside = f.parent
            while inside != root and inside.is_relative_to(root):
                if _own(inside):
                    broken.append(f"I1: read {self.rel(f)} inside {self.rel(inside)}")
                    break
                inside = inside.parent
        tags = {self.tags.get(f) for f in files}
        if not named:  # I2
            subs = {f.relative_to(root).parts[0] for f in files
                    if f.is_relative_to(root) and len(f.relative_to(root).parts) > 1}
            if len(subs) > 1 and len(tags) > 1:
                broken.append(f"I2: pooled {sorted(subs)} with other questions")
        if empty and not argv:  # I3
            above = _project_above(folder, self.home)
            if root not in (folder, above):
                broken.append(f"I3: from an empty folder read {self.rel(root)}"
                              f" (project above: {self.rel(above) if above else None})")
        jk = root / ".judgekeeper"
        for p in changed:  # I4 (judgekeeper.toml: the answers saved, as asked, in its folder)
            if not Path(p).is_relative_to(jk) and Path(p) != root / "judgekeeper.toml":
                broken.append(f"I4: wrote {self.rel(Path(p))}, read {self.rel(root)}")
                break
        if root in self.sessions and not named and root == folder:  # I6
            kept = {self.tags.get(f) for f in self.sessions[root]}
            if tags - kept:
                broken.append(f"I6: read {sorted(self.rel(f) for f in files)} beside the "
                              f"session's {sorted(self.rel(f) for f in self.sessions[root])}")
        return broken

    # I8 -------------------------------------------------------------------------------------

    def follow(self, folder: Path, argv: tuple, said: str) -> None:
        """Run (or, for another step, parse) every command `said` prints. The command just run,
        printed again, is left out: its line says what to do first."""
        for where, args in commands(said):
            at = (folder / where).resolve() if where else folder
            if at == folder and _without_page_flags(args) == tuple(argv):
                continue
            text = shlex.join(["judgekeeper", *args])
            if not at.is_dir():
                self.note(folder, f"I8: `{text}` is to run in {where}, not a folder", said)
                continue
            try:
                ns = cli.parse_args(list(args))
            except SystemExit:
                self.note(folder, f"I8: `{text}` does not parse", said)
                continue
            path = getattr(ns, "path", None)
            if path and path != "." and not (at / path).exists():
                self.note(folder, f"I8: `{text}` names {path}, not in {self.rel(at)}", said)
                continue
            if getattr(ns, "command", None) in READS_ELSEWHERE or \
                    any(getattr(ns, flag, False) for flag in ("stop", "wait")):
                continue
            _, said2 = self.run(at, _without_page_flags(args), f"pasted `{text}`")
            if any(s in said2 for s in NONE_FOUND):
                self.note(at, f"I8: `{text}` in {self.rel(at)} found nothing", said2)

    def note(self, folder: Path, broken: str, said: str) -> None:
        self.runs.append({"why": "follow", "in": self.rel(folder), "argv": [], "code": None,
                          "broken": [broken], "said": said})


def _without_page_flags(args: list[str]) -> tuple[str, ...]:
    """The arguments without --no-browser and --port N (each run adds its own)."""
    kept, skip = [], False
    for a in args:
        if skip:
            skip = False
        elif a == "--port":
            skip = True
        elif a != "--no-browser" and not a.startswith("--port="):
            kept.append(a)
    return tuple(kept)


def _fresh(monkeypatch) -> None:
    """What conftest resets for each test, reset for each run."""
    from judgekeeper import keys, redact, textio
    from tests import keyboard

    keyboard.reset()
    monkeypatch.setattr(redact, "_named_vars", set())
    monkeypatch.setattr(redact, "_named_values", set())
    for name in ("_notes", "_noted", "_said"):
        monkeypatch.setattr(keys, name, type(getattr(keys, name))())
    monkeypatch.setattr(textio, "_held", {})


def _own(folder: Path) -> bool:
    """A project of its own: a project file, or its own .judgekeeper/ holding more than its
    .gitignore."""
    from judgekeeper import recorder

    if any((folder / name).exists() for name in recorder.MARKERS) or \
            any(folder.glob(recorder.REQUIREMENTS)):
        return True
    jk = folder / ".judgekeeper"
    return jk.is_dir() and any(p.name != ".gitignore" for p in jk.iterdir())


def _project_above(folder: Path, home: Path) -> Path | None:
    for above in folder.parents:
        if above == home or not above.is_relative_to(home):
            return None
        if _own(above) or any(p.suffix in CODE for p in above.iterdir() if p.is_file()):
            return above
    return None


def commands(said: str) -> list[tuple[str, list[str]]]:
    """(the folder to run in, below the run's, or "" for the same; the arguments) of each
    `judgekeeper ...` the output prints: "run `judgekeeper` in x/" runs in x/, "go to x/ (`cd
    x`), then run `judgekeeper` there" too. A command with a placeholder is left out."""
    parts = said.split("`")
    found = []
    for i in range(1, len(parts), 2):
        code = parts[i].strip()
        if not code.startswith("judgekeeper") or "<" in code or "..." in code:
            continue
        try:
            args = shlex.split(code)[1:]
        except ValueError:
            continue
        before = parts[i - 1]
        if any(before.rstrip().endswith(s) for s in STARTS_OVER):
            continue  # a command for later, once there are answers
        rest = parts[i + 1] if i + 1 < len(parts) else ""
        where = ""
        if (m := re.match(r" in (.+?)/(?:[.,;)]|\s|$)", rest)) and not m[1].startswith("your"):
            where = m[1]  # "in data/my evals/."
        elif i >= 2 and parts[i - 2].startswith("cd ") and parts[i - 1].strip() in (
                "), then run", "), then"):
            where = shlex.split(parts[i - 2])[1]
        if "--tool" in args and args[args.index("--tool") + 1:][:1] == ["NAME"]:
            offered = before[before.rfind("(") + 1:]  # "(deepeval, table for a CSV ...)"
            at = args.index("--tool") + 1
            found += [(where, [*args[:at], t, *args[at + 1:]]) for t in TOOLS_
                      if t in offered.replace(",", " ").split()]
            continue
        found.append((where, args))
    return found


def listing(tree: Tree) -> str:
    lines = []
    for f in sorted(tree.folders, key=lambda f: f.path):
        bits = [] if f.kind == "plain" else [f.kind]
        if f.content != "none":
            bits.append(f"{f.content} x{f.rows} q={f.tag}")
        if f.link:
            bits.append(f"link {f.link}")
        if f.session:
            bits.append("session" + (f" + newer other.jsonl {f.late}" if f.late else ""))
        bits.append(f"-{f.age}m")
        depth = f.path.count("/") + 1 if f.path else 0
        lines.append("  " * depth + (f.path.split("/")[-1] or "t") + "/  " + ", ".join(bits))
    lines.append(f"run in t/{tree.run_in}: judgekeeper {shlex.join(tree.argv)}".rstrip())
    return "\n".join(lines)


# Running a tree and shrinking it ------------------------------------------------------------

def failures(tree: Tree, base: Path, monkeypatch, capsys) -> list[dict]:
    """Every run of `tree` that broke a rule (the session runs, the run, what it printed),
    with the run itself; none when no rule broke."""
    world = World(base.resolve(), monkeypatch, capsys)
    world.build(tree)
    folder = world.top / tree.run_in
    _, said = world.run(folder, tree.argv, "run")
    world.follow(folder, tree.argv, said)
    if not any(r["broken"] for r in world.runs):
        return []
    return [r for r in world.runs if r["broken"] or r["why"] == "run"]  # and what the run said


def _rules(found: list[dict]) -> set[str]:
    return {b.split(":")[0] for r in found for b in r["broken"]}


def shrink(tree: Tree, rule: str, base: Path, monkeypatch, capsys) -> tuple[Tree, list[dict]]:
    """The smallest tree (fewest folders, then fewest features) that still breaks `rule`."""
    n = [0]

    def still(candidate: Tree) -> list[dict] | None:
        n[0] += 1
        found = failures(candidate, base / f"s{n[0]}", monkeypatch, capsys)
        return found if rule in _rules(found) else None

    best = failures(tree, base / "s0", monkeypatch, capsys)
    changed = True
    while changed and n[0] < 400:
        changed = False
        for candidate in _smaller(tree):
            found = still(candidate)
            if found:
                tree, best, changed = candidate, found, True
                break
    return tree, best


def _smaller(tree: Tree):
    for f in sorted(tree.folders, key=lambda f: -f.path.count("/")):
        if f.path and not (tree.run_in + "/").startswith(f.path + "/"):
            keep = [o for o in tree.folders if not (o.path + "/").startswith(f.path + "/")]
            argv = tree.argv
            if any(a.startswith(f.path) or f"/{f.path}/" in f"/{a}" for a in argv):
                continue
            yield Tree([dataclasses.replace(o, link="" if o.link.split(":", 1)[-1] == f.path
                                            else o.link) for o in keep], tree.run_in, argv)
    if tree.argv and not any(a.endswith((".csv", ".json", ".jsonl")) for a in tree.argv):
        yield Tree(tree.folders, tree.run_in, ())
    for i, f in enumerate(tree.folders):
        for change in ({"late": ""}, {"session": False, "late": ""}, {"link": ""},
                       {"kind": "plain"}, {"rows": 6}, {"age": 0}, {"content": "none"},
                       {"content": "csv"}):
            if all(getattr(f, k) == v for k, v in change.items()) or \
                    change.get("content") == "csv" and f.content == "none":
                continue  # each step is simpler: never back from none
            if "content" in change and any(_file_of(f).endswith(a.split("/")[-1])
                                           and a.split("/")[-1] for a in tree.argv
                                           if f.content != "none"):
                continue
            folders = list(tree.folders)
            folders[i] = dataclasses.replace(f, **change)
            yield Tree(folders, tree.run_in, tree.argv)


def _seeds():
    count = os.environ.get("JK_FUZZ")
    if not count:
        return list(FIXED)
    if count.startswith("seeds="):  # JK_FUZZ=seeds=301,355: those trees again
        return [int(n) for n in count.removeprefix("seeds=").split(",")]
    start = int(os.environ.get("JK_FUZZ_START", "0"))
    return list(range(start, start + int(count)))


_REAL_FIND = front.find_found
FINDINGS: dict[int, str] = {}  # seed: the finding it shows, until it is decided


@pytest.mark.parametrize("seed", [
    pytest.param(s, marks=pytest.mark.xfail(strict=True, reason=FINDINGS[s]))
    if s in FINDINGS else s for s in _seeds()])
def test_random_trees_keep_the_folder_rules(seed, tmp_path, monkeypatch, capsys):
    tree = generate(seed)
    found = failures(tree, tmp_path / "t0", monkeypatch, capsys)
    if not found:
        return
    rule = min(_rules(found))
    if os.environ.get("JK_FUZZ"):
        tree, found = shrink(tree, rule, tmp_path, monkeypatch, capsys)
    report = {"seed": seed, "rule": rule, "tree": listing(tree),
              "broken": [{k: r[k] for k in ("why", "in", "argv", "code", "broken")} | {
                  "said": r["said"][:1500]} for r in found]}
    if path := os.environ.get("JK_FUZZ_REPORT"):
        with open(path, "a", encoding="utf-8") as out:
            out.write(json.dumps(report) + "\n")
    pytest.fail(f"seed {seed} breaks {rule}\n{report['tree']}\n"
                + json.dumps(report["broken"], indent=1)[:4000])
