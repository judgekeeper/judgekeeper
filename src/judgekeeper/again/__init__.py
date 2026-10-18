"""Asking your judge again: the plan, made before any call.

judgekeeper can ask the user's own judge, through the user's own eval tool, about the answers
the person labeled: the judge's tool grades the saved answers again; the user's app is never
run. Before anything is spent, `make_plan` says what would run:

- the judge, and honestly whether this is exactly your judge, a close copy (naming what could
  not be confirmed), or a judge that can't be asked again (and why);
- which key the judge's tool will read (`keys`, names only) and the settings that change it;
- how many judge calls (labeled answers × times × calls per answer for that judge type) and
  a cost range at dated prices (`prices`);
- what the run touches.

One planner per tool, each `plan(ws, answers, opts, talk, dry) -> Plan`: `promptfoo`,
`deepeval`, `inspect` and `mlflow`. With `dry`, the plan
also checks the judge where it would run: the installed promptfoo's version, or for the
Python tools a small worker script (`workers/`) run with the user's own Python, which builds
the judge and checks it with no API call. judgekeeper never imports DeepEval, Inspect AI or
MLflow itself for this. A plan made without `dry` runs nothing.

Every process goes through `run_process`, which tests replace. After the plan, `judgekeeper
check` and `fix` ask before anything is spent. Then each tool's `run` asks for real
(`promptfoo.run`, and for the Python tools `deepeval.run`, `inspect.run` and `mlflow.run`, which
run their worker in "run" mode through `worker_run`), and `fresh.write_files` saves the run
files.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from judgekeeper import prices
from judgekeeper.redact import scrub
from judgekeeper.textio import jsonl_lines

TIMES = 2
WORKER_TIMEOUT = 300
EXACT, CLOSE, CANT = "exact", "close", "cant"


@dataclass
class AgainOptions:
    times: int | None = None  # --times; None: TIMES, or 1 when trying a new judge
    python: str | None = None  # the Python to run the eval tool with (default: user_python)
    fields: str | None = None  # --fields, DeepEval GEval: the parts the judge reads
    judge_model: str | None = None
    rule: str | None = None  # `judgekeeper fix`: a new rule, swapped in for the judge's own


@dataclass
class Plan:
    tool: str
    judge: str
    status: str  # EXACT, CLOSE or CANT
    why: str  # one sentence, no final full stop
    short: str = ""  # a few words, for the menu, when the judge can't be asked again
    plain: str = ""  # instead of "Your judge can't be asked again: <why>.", a whole sentence
    changed: str = ""  # what changed in the judge since the marks, when it asks another one
    model: str | None = None
    provider: str | None = None
    key_lines: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    times: int | None = None  # --times; None: TIMES, or 1 when trying a new judge
    calls_each: list[int] = field(default_factory=list)  # judge calls per answer, per time
    calls_note: str = ""  # "at least" or "up to"
    extra_calls: str = ""  # "plus 4 embedding calls per answer"
    tokens: list[tuple[int, int]] = field(default_factory=list)  # per answer, per time
    cost_text: str | None = None  # instead of the price line
    left_out: list[str] = field(default_factory=list)
    side_effects: list[str] = field(default_factory=list)
    labeled: int = 0  # every labeled answer, asked or left out
    settings: list[str] = field(default_factory=list)  # setting variable names that are set
    tool_version: str | None = None
    key_ok: bool = True  # the key the judge needs was found (by name)
    key_step: str | None = None  # when not: where to set it (keys.KeyCheck.step)
    runner: list[str] = field(default_factory=list)  # the command that runs the tool
    download: bool = False  # the runner downloads the tool first (npx)
    install: str | None = None  # a command to run in the project first: it installs the tool
    # (npm install promptfoo@<version>), or sets up its model (DeepEval's own `deepeval set-...`)
    payload: list = field(default_factory=list)  # per asked answer, for the tool's run
    job: dict = field(default_factory=dict)  # the rest of a worker's job for the run
    folder: Path | None = None  # where the run's files go (default: again/<date>/)

    def payload_answers(self) -> list[dict]:
        """The asked answers ({id, input, output, label, verdict}), in order."""
        return [p[0] if isinstance(p, tuple) else p for p in self.payload]

    @property
    def answers(self) -> int:
        return len(self.calls_each)

    @property
    def calls(self) -> int:
        return self.times * sum(self.calls_each)

    @property
    def cost(self) -> tuple[float, float] | None:
        return prices.estimate(self.model, self.tokens * self.times)


def cant(tool: str, judge: str, why: str, short: str = "") -> Plan:
    return Plan(tool=tool, judge=judge, status=CANT, why=why, short=short or why)


NOT_MARKED = "your newest results don't contain the answers you marked"
NOT_MARKED_PLAIN = ("Your newest results don't contain the answers you marked, so your judge "
                    "can't grade them again.")
NO_SWAP = "judgekeeper can't put a new rule into {what}, so it can't take a new rule"


def not_marked(tool: str, judge: str) -> Plan:
    """None of the marked answers is in the newest results: nothing to grade again."""
    plan = cant(tool, judge, NOT_MARKED)
    plan.plain = NOT_MARKED_PLAIN
    return plan


# Processes -------------------------------------------------------------------------------------

STOP_WAIT = 5  # seconds a stopped program gets to end before it is killed
TICK = 1.0  # seconds between two looks at a running program's progress
PROGRESS_EVERY = 5.0  # seconds between two progress lines at most
STILL_EVERY = 30.0  # seconds between two "still asking" lines when nothing can be counted
LOCAL_MODEL = ("A model on your computer can take minutes: the lines below show it is "
               "working.")
_progress = None  # called about every TICK seconds while run_process waits (watching)


@contextmanager
def watching(progress):
    """While the block runs, run_process calls `progress()` about every TICK seconds."""
    global _progress
    before, _progress = _progress, progress
    try:
        yield
    finally:
        _progress = before


class Progress:
    """The lines that show the judge is being asked: "12 of 72 asked", when the count moves
    on, at most every PROGRESS_EVERY seconds, and the last one; with no count (`total` None),
    "Still asking your judge: 1 min 20 s so far." every STILL_EVERY seconds."""

    def __init__(self, talk, total: int | None):
        self.talk, self.total = talk, total
        self.started = self.last_time = time.monotonic()
        self.last = 0

    def count(self, n: int) -> None:
        now = time.monotonic()
        if n > self.last and (n >= (self.total or 0) or now - self.last_time >= PROGRESS_EVERY):
            self.last, self.last_time = n, now
            self.talk.say(f"  {n:,} of {self.total:,} asked")

    def tick(self) -> None:
        now = time.monotonic()
        if now - self.last_time >= STILL_EVERY:
            self.last_time = now
            minutes, seconds = divmod(int(now - self.started), 60)
            spent = f"{minutes} min {seconds} s" if minutes else f"{seconds} s"
            self.talk.say(f"  Still asking your judge: {spent} so far.")


def local_model(plan) -> bool:
    """Whether the plan's judge runs on the person's own computer (Ollama)."""
    return plan.provider == "ollama" or str(plan.model or "").lower().startswith("ollama")


def _own_group() -> dict:
    """Start a program in its own process group, so it and every program it starts (a
    worker's model calls, promptfoo's node) can be stopped together."""
    if sys.platform == "win32":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def stop_group(proc) -> None:
    """Stop a program started with _own_group and everything it started: on Windows the
    whole tree (taskkill /T); elsewhere its process group, SIGTERM, then SIGKILL after
    STOP_WAIT seconds."""
    if proc.poll() is not None:
        return
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True,
                           check=False)
        else:
            os.killpg(proc.pid, signal.SIGTERM)
            try:
                proc.wait(timeout=STOP_WAIT)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
    except OSError:
        pass
    try:
        proc.kill()  # whatever is left of the program itself
    except OSError:
        pass


class _Terminated(KeyboardInterrupt):
    """SIGTERM while a program runs: stopped like Ctrl-C."""


@contextmanager
def _term_stops():
    """While the block runs, SIGTERM (what agents, editors and CI send to stop a command)
    raises _Terminated, so the program it waits for is stopped too, not left running and
    spending. Only in the main thread, where Python allows a handler."""
    if threading.current_thread() is not threading.main_thread():
        yield
        return

    def stop(signum, frame):
        raise _Terminated()

    before = signal.signal(signal.SIGTERM, stop)
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, before)


def run_process(argv: list[str], cwd: Path, env: dict | None = None,
                timeout: float | None = None):
    """The one place judgekeeper starts another program for asking again (tests replace it).
    Returns an object with returncode, stdout and stderr; a program that is not there gives
    returncode 127, one that is there but cannot be started (on Windows, a file that is not a
    program: WinError 193) 126. The program runs in its own process group: on Ctrl-C,
    SIGTERM, a timeout or any error, it and everything it started are stopped (stop_group)."""
    try:
        proc = subprocess.Popen(argv, cwd=cwd, env=env, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, encoding="utf-8", errors="replace",
                                **_own_group())
    except FileNotFoundError as e:
        return subprocess.CompletedProcess(argv, 127, "", str(e))
    except OSError as e:
        return subprocess.CompletedProcess(argv, 126, "", str(e))
    end = None if timeout is None else time.monotonic() + timeout
    with _term_stops():
        try:
            while True:
                wait = None if _progress is None else TICK
                if end is not None:
                    wait = max(0.0, end - time.monotonic()) if wait is None else min(
                        wait, max(0.0, end - time.monotonic()))
                try:
                    out, err = proc.communicate(timeout=wait)
                    break
                except subprocess.TimeoutExpired:
                    if end is not None and time.monotonic() >= end:
                        raise
                    try:
                        _progress()
                    except Exception:  # noqa: BLE001, S110 - a progress line never stops it
                        pass
        except subprocess.TimeoutExpired:
            stop_group(proc)
            proc.communicate()
            return subprocess.CompletedProcess(argv, 124, "", f"timed out after {timeout:g}s")
        except BaseException:
            stop_group(proc)
            raise
    return subprocess.CompletedProcess(argv, proc.returncode, out, err)


def which(name: str) -> str | None:
    return shutil.which(name)


def node_bin(root: Path, name: str) -> str | None:
    """The program `name` that npm installed in the project (node_modules/.bin), as it can be
    started, else None. On Windows that is npm's `name.cmd` (then `name.exe`): the plain
    `name` there is a shell script Windows cannot start (WinError 193). A `.cmd` is started
    with its full path first in the argument list, never through a shell."""
    folder = Path(root) / "node_modules" / ".bin"
    names = (f"{name}.cmd", f"{name}.exe") if sys.platform == "win32" else (name,)
    return next((str(folder / n) for n in names if (folder / n).is_file()), None)


def user_python(root: Path, given: str | None) -> str:
    """The Python the user runs their evals with: `given`, the active virtual environment,
    the project's .venv or venv, else the Python running judgekeeper."""
    if given:
        return given
    rel = Path("Scripts/python.exe") if sys.platform == "win32" else Path("bin/python")
    venv = os.environ.get("VIRTUAL_ENV")
    if venv and (Path(venv) / rel).exists():
        return str(Path(venv) / rel)
    for name in (".venv", "venv"):
        if (Path(root) / name / rel).exists():
            return str(Path(root) / name / rel)
    return sys.executable


UVX_PYTHON = "the Python uvx runs judgekeeper with"


def python_name(python: str) -> str:
    """`python` as said to the person: its path, or, for the Python in uv's cache that uvx runs
    judgekeeper with, those words (the cache path means nothing to them)."""
    from judgekeeper.textio import started_by_uvx

    return UVX_PYTHON if python == sys.executable and started_by_uvx() else python


def your_python(python: str) -> str:
    """"your Python (<path>)", or UVX_PYTHON."""
    name = python_name(python)
    return name if name == UVX_PYTHON else f"your Python ({python})"


def start_worker(tool: str, python: str, job: dict, cwd: Path, out_path: Path,
                 env: dict | None = None, drop: tuple = (),
                 timeout: float | None = WORKER_TIMEOUT):
    """Run `workers/<tool>_worker.py job.json out.jsonl` with `python`, in the project folder,
    writing to `out_path`. The worker's environment is judgekeeper's, without the names in
    `drop`, with `env` on top. Returns the finished process."""
    worker = Path(__file__).parent / "workers" / f"{tool}_worker.py"
    environ = {k: v for k, v in os.environ.items() if k not in drop}
    environ.update(env or {})
    with tempfile.TemporaryDirectory(prefix="judgekeeper-") as tmp:
        job_path = Path(tmp) / "job.json"
        job_path.write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
        return run_process([python, str(worker), str(job_path), str(out_path)], cwd=cwd,
                           env=environ, timeout=timeout)


def last_error(proc) -> str:
    """The last line a process wrote to stderr, scrubbed, or its exit code."""
    tail = [x for x in (proc.stderr or "").strip().splitlines() if x.strip()]
    return scrub(tail[-1]) if tail else f"exit code {proc.returncode}"


def run_worker(tool: str, python: str, job: dict, cwd: Path, env: dict | None = None,
               drop: tuple = ()) -> dict:
    """Run a worker (`start_worker`) and return its last output line."""
    with tempfile.TemporaryDirectory(prefix="judgekeeper-") as tmp:
        out_path = Path(tmp) / "out.jsonl"
        proc = start_worker(tool, python, job, cwd, out_path, env=env, drop=drop)
        lines = (jsonl_lines(out_path.read_text(encoding="utf-8"))
                 if out_path.is_file() else [])
    lines = [x for x in lines if x.strip()]
    if lines:
        return json.loads(lines[-1])
    return {"ok": False, "error": last_error(proc)}


# The answers -----------------------------------------------------------------------------------

def labeled_answers(ws) -> list[dict]:
    """[{id, input, output, label, verdict}] for every answer labeled Correct or Wrong, in the
    order the person saw them (skips left out)."""
    from judgekeeper.judgments import read_run
    from judgekeeper.start_again import _labels

    labels = _labels(ws)
    _, records = read_run(ws.pool_judge)
    raw = {}
    for line in jsonl_lines(ws.pool.read_text(encoding="utf-8")):
        if line.strip():
            row = json.loads(line)
            raw[row["id"]] = row
    return [{"id": r["id"], "input": raw.get(r["id"], {}).get("input"),
             "output": raw.get(r["id"], {}).get("output"), "label": labels[r["id"]],
             "verdict": records[r["id"]]["verdict"]}
            for r in ws.data()["queue"] if r["id"] in labels]


def left_out_line(n: int, why: str, why_many: str | None = None) -> str:
    if n == 1:
        return f"1 answer is left out: {why}."
    return f"{n} answers are left out: {why_many or why}."


# The plan --------------------------------------------------------------------------------------

def make_plan(ws, opts: AgainOptions | None = None, talk=None, dry: bool = True,
              new=None, only: set[str] | None = None) -> Plan:
    """The plan for asking the judge of `ws` again. `dry` checks the judge where it would run
    (no API call); without it nothing runs (for the menu). `talk`, at a terminal, asks the
    few questions a plan may need (DeepEval's fields, a tool's version).

    With `new` (a check.View), the judge is the new one in the newest results, rebuilt
    from them, and it grades the same labeled answers; it is asked once unless --times.
    `only` (answer ids) keeps the plan to those labeled answers."""
    from dataclasses import replace

    from judgekeeper.again import deepeval, inspect, mlflow, promptfoo
    from judgekeeper.records import RecordsError

    opts = opts or AgainOptions()
    opts = replace(opts, times=opts.times or (1 if new is not None else TIMES))
    answers = [a for a in labeled_answers(ws) if only is None or a["id"] in only]
    source = new if new is not None else ws
    data = source.data()
    planners = {"promptfoo": promptfoo.plan, "deepeval": deepeval.plan,
                "inspect": inspect.plan, "mlflow": mlflow.plan}
    try:
        if data["tool"] in planners:
            plan = planners[data["tool"]](source, answers, opts, talk, dry,
                                          new=new is not None)
        elif data["tool"] == "mapped":
            plan = cant("mapped", data["judge"],
                        "your judge's decisions are in your own results file, and judgekeeper "
                        "can't run the judge that made them")
        elif data["tool"] == "records":
            plan = cant("records", data["judge"],
                        "your judge's decisions were saved by judgekeeper.record() in your own "
                        "code, and judgekeeper can't run the judge that made them")
        else:
            plan = cant(data["tool"], data["judge"],
                        "your judge's decisions are a table, and judgekeeper can't run the "
                        "judge that made them")
    except (OSError, ValueError, KeyError, RecordsError) as e:
        plan = cant(data["tool"], data["judge"],
                    f"your saved results could not be read again ({scrub(str(e))})",
                    short="your saved results could not be read again")
    plan.times = opts.times
    plan.labeled = len(answers)
    return plan


def run_tool(ws, plan: Plan, talk):
    """Ask for real with the plan's tool (after the yes): its Fresh."""
    from judgekeeper.again import deepeval, inspect, mlflow, promptfoo

    runs = {"promptfoo": promptfoo.run, "deepeval": deepeval.run,
            "inspect": inspect.run, "mlflow": mlflow.run}
    return runs[plan.tool](ws, plan, talk)


__all__ = [
    "AgainOptions",
    "Plan",
    "make_plan",
    "run_process",
    "run_worker",
    "start_worker",
    "user_python",
    "which",
]
