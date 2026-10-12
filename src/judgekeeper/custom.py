"""Your own judge as a program, behind the Runner interface (`start --judge-command`).

The judge gets the item without its human label (and without notes, which may hint at it).
Pairwise items are judged twice, with the outputs in AB and BA order. Whatever the judge
returns goes through the normaliser; a judge that fails or returns nothing usable becomes an
"error" judgment, which is not counted.

The contract: one item as JSON on stdin per invocation; stdout is a bare verdict
(`pass`, `FAIL: reason`, `0.83`) or a JSON object the normaliser reads; a non-zero exit is an
error judgment. Both streams are UTF-8 on every platform.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import inspect
import json
import os
import subprocess
from collections.abc import Callable
from typing import Any

from judgekeeper.anchors import PAIRWISE, item_kind
from judgekeeper.fingerprint import JudgeFingerprint
from judgekeeper.metrics import ERROR
from judgekeeper.normalise import Normaliser, UnmappedValue, unmapped_error
from judgekeeper.runners.base import Judgment
from judgekeeper.textio import split_command

# Hidden from the judge: the answer, and free text a labeler may have written about it.
HIDDEN_FIELDS = ("human_label", "notes")
EXEC_TIMEOUT = 300.0
_SWAP = {"A": "B", "B": "A"}


class CallableError(Exception):
    """The judge command cannot be read as a command."""


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
        raise CallableError(f"--judge-command {command!r} cannot be read as a command: "
                            f"{e}") from None
    if not argv:
        raise CallableError("--judge-command needs a command")

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

