"""Judge results saved in a project's own format: spotting them, and the prompt for a coding
agent that turns them into judgekeeper's table.

When `start` finds no results it can read, it must not send the user to run their eval again
when that would not help (a DeepEval metric's `measure()` called directly saves nothing). It
looks instead for a recent JSON, JSONL or CSV file whose items hold a score-like key with an
input-like and an output-like key (looks_judged), at any depth, names it, and prints AGENT_PROMPT: a short
prompt to paste into a coding agent, which writes the converter. Standard library only;
nothing is written, and only the first part of each file is read.
"""

from __future__ import annotations

import csv
import io
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

from judgekeeper import find
from judgekeeper.mapper import SCORE_WORDS, _words

OWN_FORMAT_URL = "www.judgekeeper.com/start.html#own-format"
INSTALL_URL = "www.judgekeeper.com/start.html#install"
RECORD_URL = "www.judgekeeper.com/assistant.html#add-the-record-line"
AGENT_PROMPT = """\
In this project, my LLM judge saves its results in its own format. Please:

1. Install judgekeeper into this project's own Python environment, as a dev tool: for
   example `uv add --dev judgekeeper`, `poetry add --group dev judgekeeper`, or
   `pip install judgekeeper` with the project's virtual environment active.
2. Find where the judge's results are saved, and write a small script that turns them into
   judgekeeper's table: a CSV with the columns id, input, output, verdict and reason, plus
   judge_model when you can tell which model judged. The verdict is pass or fail.
3. Write one CSV per judge or criterion. Leave out rows where the judge gave an error, and
   scores made by a rule instead of an LLM.
4. Keep everything on this computer: never send the data anywhere.
5. Run `judgekeeper start <the CSV file>` and show me what it prints, so I can check the
   counts and the example rows."""

SCORE_KEYS = frozenset({"score", "scores", "verdict", "pass", "passed", "success", "label"})
INPUT_WORDS = ("input", "prompt", "question", "query", "instruction", "message")
OUTPUT_WORDS = ("output", "response", "answer", "completion", "reply", "generation")
SUFFIXES = (".json", ".jsonl", ".csv")
RECENT_DAYS = 90
MAX_FILES = 300
MAX_SECONDS = 2
JSON_BYTES = 2_000_000  # a .json file is parsed whole only up to this size
JSONL_LINES = 20
MAX_NESTING = 8


@dataclass
class OwnFile:
    path: Path
    rel: str


def _has(keys, words) -> bool:
    return any(w in k for k in keys for w in words)


def _within(d: dict, depth: int = 0):
    """(key in lower case, value) for every key of `d` and of the objects inside it, down to
    three levels, not going into lists: one item's keys."""
    for key, value in d.items():
        yield str(key).lower(), value
        if isinstance(value, dict) and depth < 3:
            yield from _within(value, depth + 1)


def _text(value) -> bool:
    return value is None or isinstance(value, str)  # None: a CSV cell, known by its name only


def looks_judged(value, depth: int = 0) -> bool:
    """Whether `value` holds, at any depth, an item: an input-like key holding text, an
    output-like key holding text (or one text per side, such as A and B), and a score-like
    key, in the item itself or in the objects inside it (not across lists)."""
    if depth > MAX_NESTING:
        return False
    if isinstance(value, dict):
        pairs = list(_within(value))
        if (any(k in SCORE_KEYS or _words(k) & set(SCORE_WORDS) for k, _ in pairs)
                and any(_has([k], INPUT_WORDS) and _text(v) for k, v in pairs)
                and any(_has([k], OUTPUT_WORDS) and (_text(v) or (isinstance(v, dict) and any(
                    isinstance(x, str) for x in v.values()))) for k, v in pairs)):
            return True
        return any(looks_judged(v, depth + 1) for v in value.values()
                   if isinstance(v, dict | list))
    if isinstance(value, list):
        return any(looks_judged(v, depth + 1) for v in value[:JSONL_LINES]
                   if isinstance(v, dict | list))
    return False


def _sample(path: Path):
    """What the file holds, as far as needed to judge its shape, or None."""
    suffix = path.suffix.lower()
    if suffix == ".json":
        if path.stat().st_size > JSON_BYTES:
            return None
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    head = find._head(path).decode("utf-8", errors="replace").removeprefix("﻿")
    if suffix == ".jsonl":
        rows = []
        for line in head.splitlines()[:JSONL_LINES]:
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
        return rows
    first = head.split("\n", 1)[0].rstrip("\r")
    columns = next(csv.reader(io.StringIO(first)), [])
    return {c: None for c in columns}


def search(root: Path) -> OwnFile | None:
    """The most recently changed file in `root` (at most find.MAX_DEPTH folders deep, changed
    in the last RECENT_DAYS days) that looks like judge results in a format of its own."""
    root = Path(root).resolve()
    since = time.time() - RECENT_DAYS * 86400
    started = time.monotonic()
    candidates: list[tuple[float, Path]] = []
    queue, seen = [root], 0
    while queue and seen < MAX_FILES and time.monotonic() - started < MAX_SECONDS:
        folder = queue.pop(0)
        try:
            entries = sorted(os.scandir(folder), key=lambda e: e.name)
        except OSError:
            continue
        for entry in entries:
            if entry.is_symlink():
                continue
            path = Path(entry.path)
            if entry.is_dir(follow_symlinks=False):
                if find._walked(entry.name) and len(path.relative_to(root).parts) <= \
                        find.MAX_DEPTH:
                    queue.append(path)
            elif entry.is_file(follow_symlinks=False) and path.suffix.lower() in SUFFIXES:
                seen += 1
                try:
                    changed = entry.stat(follow_symlinks=False).st_mtime
                except OSError:
                    continue
                if changed >= since:
                    candidates.append((changed, path))
    for _, path in sorted(candidates, reverse=True):
        if find.classify_file(path) is not None:
            continue  # a results file judgekeeper reads already
        try:
            if looks_judged(_sample(path)):
                return OwnFile(path, path.relative_to(root).as_posix())
        except (OSError, ValueError, csv.Error, RecursionError):
            continue
    return None


__all__ = ["AGENT_PROMPT", "OwnFile", "looks_judged", "search"]
