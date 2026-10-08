"""Bring your own judge: a Python callable or any program, behind the Runner interface.

`judge(item: dict) -> bool | str | float | tuple | dict`, sync or async. The item is the anchor
item without its human label (and without notes, which may hint at it). Pairwise items are
judged twice, with the outputs in AB and BA order. Whatever the judge returns goes through the
normaliser; a judge that raises or returns nothing usable becomes an "error" judgment, which
is excluded from the metrics and counted in the report.

The `--exec` contract: one item as JSON on stdin per invocation; stdout is a bare verdict
(`pass`, `FAIL: reason`, `0.83`) or a JSON object the normaliser reads; a non-zero exit is an
error judgment. Both streams are UTF-8 on every platform.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import importlib
import inspect
import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from judgekeeper.anchors import PAIRWISE, item_kind, load_verified, seal_new
from judgekeeper.fingerprint import JudgeFingerprint
from judgekeeper.metrics import ERROR
from judgekeeper.normalise import Normaliser, UnmappedValue, unmapped_error
from judgekeeper.runners.base import Judgment
from judgekeeper.textio import split_command

# Hidden from the judge: the answer, and free text a labeler may have written about it.
HIDDEN_FIELDS = ("human_label", "notes")
MAX_CALLS_WITHOUT_YES = 1000
EXEC_TIMEOUT = 300.0
_SWAP = {"A": "B", "B": "A"}


class CallLimitError(Exception):
    """More judge calls than MAX_CALLS_WITHOUT_YES without an explicit yes."""


class CallableError(Exception):
    """--callable does not name an importable function."""


def count_calls(items: list[dict], runs: int) -> int:
    orders = 2 if items and item_kind(items[0]) == PAIRWISE else 1
    return len(items) * runs * orders


def check_call_limit(n_calls: int, yes: bool) -> None:
    if n_calls > MAX_CALLS_WITHOUT_YES and not yes:
        raise CallLimitError(f"{n_calls:,} judge calls is more than {MAX_CALLS_WITHOUT_YES:,}; "
                             "pass --yes (yes=True in Python) to run them")


def judge_view(item: dict) -> dict:
    return {k: v for k, v in item.items() if k not in HIDDEN_FIELDS}


def swapped(item: dict) -> dict:
    return {**item, "output_a": item["output_b"], "output_b": item["output_a"]}


def _run_coro(coro):
    """Run a coroutine to completion, also from inside a running loop (a notebook)."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


def _error(msg: str) -> Judgment:
    return Judgment(verdict=ERROR, raw_score=None, rationale="", error=msg)


class CustomRunner:
    """Runs `call(item)` for each item and normalises what comes back."""

    def __init__(self, call: Callable[[dict], Any], normaliser: Normaliser,
                 fingerprint: JudgeFingerprint, source: dict):
        self.call = call
        self.normaliser = normaliser
        self._fingerprint = fingerprint
        self.source = source
        self.unmapped: list = []

    @property
    def fingerprint(self) -> JudgeFingerprint:
        return self._fingerprint

    def _one(self, payload: dict) -> Judgment:
        try:
            raw = self.call(payload)
            if inspect.isawaitable(raw):
                raw = _run_coro(raw)
        except ExecFailed as e:  # our own wording: no exception name in front of it
            return _error(str(e))
        except Exception as e:  # noqa: BLE001 - any judge failure is an error judgment
            return _error(f"{type(e).__name__}: {e}")
        try:
            n = self.normaliser(raw)
        except UnmappedValue as e:
            self.unmapped.append(e.value)
            return _error(str(e))
        return Judgment(verdict=n.verdict, raw_score=n.raw_score, rationale=n.rationale,
                        error=n.error)

    def judge(self, item: dict) -> Judgment:
        payload = judge_view(item)
        if item_kind(item) != PAIRWISE:
            return self._one(payload)
        ab = self._one(payload)
        ba = self._one(swapped(payload))
        ba.verdict = _SWAP.get(ba.verdict, ba.verdict)
        ab.swapped = ba
        return ab

    def raise_if_unmapped(self) -> None:
        """Called after each run: stop before writing a run full of unmapped values."""
        if self.unmapped:
            raise unmapped_error(self.unmapped, "judge output",
                                 pass_if=self.normaliser.kind != PAIRWISE)


class ExecFailed(Exception):
    pass


def exec_judge(command: str, timeout: float = EXEC_TIMEOUT) -> Callable[[dict], Any]:
    """A judge that runs `command` once per item: item JSON on stdin, verdict on stdout.

    Both are UTF-8 on every platform, whatever the locale: the default on Windows is a legacy
    code page, which cannot hold every character an item may have. Output that is not UTF-8
    keeps its readable part (a leading `pass` still counts).

    A judge written in Python reads stdin in the locale's encoding unless told otherwise, so
    the program is started with PYTHONIOENCODING=utf-8 when the user has not set that
    variable. Programs in other languages ignore it.
    """
    try:
        argv = split_command(command)
    except ValueError as e:  # an unclosed quote
        raise CallableError(f"--exec {command!r} cannot be read as a command: {e}") from None
    if not argv:
        raise CallableError("--exec needs a command")

    def call(item: dict):
        env = {**os.environ}
        env.setdefault("PYTHONIOENCODING", "utf-8")
        try:
            proc = subprocess.run(argv, input=json.dumps(item, ensure_ascii=False),
                                  capture_output=True, encoding="utf-8", errors="replace",
                                  env=env, timeout=timeout, check=False)
        except subprocess.TimeoutExpired:
            raise ExecFailed(f"timed out after {timeout:g}s") from None
        except OSError as e:
            raise ExecFailed(f"cannot run {argv[0]!r}: {e.strerror}") from None
        if proc.returncode != 0:
            tail = proc.stderr.strip().splitlines()[-3:]
            raise ExecFailed(f"exit {proc.returncode}" + (f": {' '.join(tail)}" if tail else ""))
        text = proc.stdout.strip()
        if not text:
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text

    return call


def load_callable(spec: str) -> Callable:
    """`package.module:function` to the function. The working directory is importable."""
    module_name, sep, attr = spec.partition(":")
    if not sep or not module_name or not attr:
        raise CallableError(f"--callable {spec!r} must look like package.module:function")
    if "" not in sys.path and str(Path.cwd()) not in sys.path:
        sys.path.insert(0, str(Path.cwd()))
    try:
        obj = importlib.import_module(module_name)
    except ImportError as e:
        raise CallableError(f"cannot import {module_name!r}: {e}") from None
    for part in attr.split("."):
        if not hasattr(obj, part):
            raise CallableError(f"{module_name!r} has no attribute {attr!r}")
        obj = getattr(obj, part)
    if not callable(obj):
        raise CallableError(f"{spec!r} is not callable")
    return obj


def callable_name(fn: Callable) -> str:
    module = getattr(fn, "__module__", None) or "?"
    return f"{module}:{getattr(fn, '__qualname__', type(fn).__name__)}"


def _anchor_path(anchors, out: Path) -> Path:
    from judgekeeper.table import write_anchor_file

    if isinstance(anchors, str | Path):
        seal_new(anchors)  # a new anchor set is sealed on first use, as `judge` does
        return Path(anchors)
    path = out / "anchors.jsonl"
    write_anchor_file(path, list(anchors))
    return path


def check_judge(judge: Callable[[dict], Any], anchors, runs: int = 3,
                pass_if: str | None = None, label_map: dict | str | None = None,
                fingerprint: dict | None = None, out: str | Path | None = None,
                yes: bool = False) -> dict:
    """Run `judge` `runs` times over a frozen anchor set; write run files; return the report.

    `anchors` is an anchor JSONL path (sealed on first use, as `judgekeeper judge` does), or a
    list of anchor items (written under `out` and frozen for you). `fingerprint` is whatever
    you know about the judge: model, provider, prompt (text, hashed), temperature...; the rest
    is recorded as unknown. Files go under `out` (a temporary directory if None):
    `runs/run-NN.jsonl`, `report.json`, `report.html`.
    """
    from judgekeeper.judging import run_judge
    from judgekeeper.report import build_report
    from judgekeeper.table import make_fingerprint, write_report

    if runs < 1:
        raise ValueError("runs must be at least 1")
    out = Path(out) if out is not None else Path(tempfile.mkdtemp(prefix="judgekeeper-judge-"))
    out.mkdir(parents=True, exist_ok=True)
    anchors_path = _anchor_path(anchors, out)
    items, manifest = load_verified(anchors_path)
    check_call_limit(count_calls(items, runs), yes)
    runner = CustomRunner(judge, Normaliser(manifest["kind"], pass_if=pass_if,
                                            label_map=label_map),
                          make_fingerprint(fingerprint),
                          {"kind": "callable", "file": None, "metric": callable_name(judge)})
    runs_dir = out / "runs"
    runs_dir.mkdir(exist_ok=True)
    for old in runs_dir.glob("run-*.jsonl"):  # this directory is ours: no stale runs
        old.unlink()
    run_custom(items, runner, runs, runs_dir, manifest["sha256"], run_judge)
    report = build_report(anchors_path, runs_dir)
    write_report(report, out)
    return report


def run_custom(items, runner: CustomRunner, runs: int, runs_dir: Path, sha: str, run_judge,
               workers: int = 1, progress=None) -> list[Path]:
    return run_judge(items, runner, runs, runs_dir, sha, workers=workers, progress=progress,
                     source=runner.source, normaliser=runner.normaliser.describe(),
                     after_run=runner.raise_if_unmapped)
