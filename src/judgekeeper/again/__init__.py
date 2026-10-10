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
`deepeval`, `inspect`, `mlflow`, and `command` for the user's own judge command
(`--judge-command`, the `--exec` contract). With `dry`, the plan also checks the judge where
it would run: the installed promptfoo's version, or for the Python tools a small worker
script (`workers/`) run with the user's own Python, which builds the judge and checks it with
no API call. judgekeeper never imports DeepEval, Inspect AI or MLflow itself for this. The
menu's line uses a plan made without `dry`: it runs nothing.

Every process goes through `run_process`, which tests replace. After the plan, `approve` asks
before anything is spent (default No; `--yes` never answers it; without a terminal only
`--allow-calls N` does). Then each tool's `run` asks for real (`promptfoo.run`, `command.run`,
and for the Python tools `deepeval.run`, `inspect.run` and `mlflow.run`, which run their worker
in "run" mode through `worker_run`), and `fresh.finish` works out the numbers and saves them.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from judgekeeper import prices
from judgekeeper.redact import scrub

TIMES = 2
ALWAYS_ASK_ABOVE = 1000
WORKER_TIMEOUT = 300
REFERENCE = "https://www.judgekeeper.com/reference.html#bring-your-own-judge"
WRAP = ("To ask your judge again yourself, wrap it as a command: judgekeeper start --ask-again "
        f"--judge-command '...' (see {REFERENCE}).")
EXACT, CLOSE, CANT, OWN = "exact", "close", "cant", "own"


@dataclass
class AgainOptions:
    times: int | None = None  # --times; None: TIMES, or 1 when trying a new judge
    python: str | None = None  # --python
    fields: str | None = None  # --fields, DeepEval GEval: the parts the judge reads
    judge_command: str | None = None
    judge_model: str | None = None
    allow_calls: int | None = None  # --allow-calls


@dataclass
class Plan:
    tool: str
    judge: str
    status: str  # EXACT, CLOSE, CANT or OWN
    why: str  # one sentence, no final full stop
    short: str = ""  # a few words, for the menu, when the judge can't be asked again
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
    runner: list[str] = field(default_factory=list)  # the command that runs the tool
    download: bool = False  # the runner downloads the tool first (npx)
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


# Processes -------------------------------------------------------------------------------------

def run_process(argv: list[str], cwd: Path, env: dict | None = None,
                timeout: float | None = None):
    """The one place judgekeeper starts another program for asking again (tests replace it).
    Returns an object with returncode, stdout and stderr; a program that is not there gives
    returncode 127."""
    try:
        return subprocess.run(argv, cwd=cwd, env=env, capture_output=True, encoding="utf-8",
                              errors="replace", timeout=timeout, check=False)
    except FileNotFoundError as e:
        return subprocess.CompletedProcess(argv, 127, "", str(e))
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(argv, 124, "", f"timed out after {timeout:g}s")


def which(name: str) -> str | None:
    return shutil.which(name)


def user_python(root: Path, given: str | None) -> str:
    """The Python the user runs their evals with: --python, the active virtual environment,
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
        lines = (out_path.read_text(encoding="utf-8").splitlines()
                 if out_path.is_file() else [])
    lines = [x for x in lines if x.strip()]
    if lines:
        return json.loads(lines[-1])
    return {"ok": False, "error": last_error(proc)}


# The answers -----------------------------------------------------------------------------------

def labeled_answers(ws) -> list[dict]:
    """[{id, input, output, label, verdict}] for every answer labeled Correct or Wrong, in the
    order the person saw them (skips left out)."""
    from judgekeeper.start_review import labeled

    raw = {}
    for line in ws.pool.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            raw[row["id"]] = row
    return [{"id": r["id"], "input": raw.get(r["id"], {}).get("input"),
             "output": raw.get(r["id"], {}).get("output"), "label": r["first"],
             "verdict": r["judge"]} for r in labeled(ws)]


def left_out_line(n: int, why: str, why_many: str | None = None) -> str:
    if n == 1:
        return f"1 answer is left out: {why}."
    return f"{n} answers are left out: {why_many or why}."


# The plan --------------------------------------------------------------------------------------

def make_plan(ws, opts: AgainOptions | None = None, talk=None, dry: bool = True,
              new=None) -> Plan:
    """The plan for asking the judge of `ws` again. `dry` checks the judge where it would run
    (no API call); without it nothing runs (for the menu). `talk`, at a terminal, asks the
    few questions a plan may need (DeepEval's fields, a tool's version).

    With `new` (a new_judge.View), the judge is the new one in the newest results, rebuilt
    from them, and it grades the same labeled answers; it is asked once unless --times."""
    from dataclasses import replace

    from judgekeeper.again import command, deepeval, inspect, mlflow, promptfoo
    from judgekeeper.records import RecordsError

    opts = opts or AgainOptions()
    opts = replace(opts, times=opts.times or (1 if new is not None else TIMES))
    answers = labeled_answers(ws)
    source = new if new is not None else ws
    data = source.data()
    planners = {"promptfoo": promptfoo.plan, "deepeval": deepeval.plan,
                "inspect": inspect.plan, "mlflow": mlflow.plan}
    try:
        if opts.judge_command:
            plan = command.plan(source, answers, opts)
        elif data["tool"] in planners:
            plan = planners[data["tool"]](source, answers, opts, talk, dry,
                                          new=new is not None)
        elif data["tool"] == "mapped":
            plan = cant("mapped", data["judge"],
                        "your judge's verdicts are in your own results file, and judgekeeper "
                        "can't run the judge that made them",
                        short="your judge's verdicts are in your own results file")
        elif data["tool"] == "records":
            plan = cant("records", data["judge"],
                        "your judge's verdicts were saved by judgekeeper.record() in your own "
                        "code, and judgekeeper can't run the judge that made them",
                        short="your judge's verdicts were saved by judgekeeper.record()")
        else:
            plan = cant(data["tool"], data["judge"],
                        "your judge's verdicts are a table, and judgekeeper can't run the "
                        "judge that made them", short="your judge's verdicts are a table")
    except (OSError, ValueError, KeyError, RecordsError) as e:
        plan = cant(data["tool"], data["judge"],
                    f"your saved results could not be read again ({scrub(str(e))})",
                    short="your saved results could not be read again")
    plan.times = opts.times
    plan.labeled = len(answers)
    return plan


def _s(n: int, word: str) -> str:
    return f"{n:,} {word}{'' if n == 1 else 's'}"


def calls_line(p: Plan) -> str:
    each = set(p.calls_each)
    per = f" × {next(iter(each))} calls each" if len(each) == 1 and max(each) > 1 else ""
    note = f"{p.calls_note} " if p.calls_note else ""
    line = (f"{_s(p.answers, 'marked answer')} × {_s(p.times, 'time')}{per} = "
            f"{note}{p.calls:,} judge calls")
    if len(each) > 1:
        line += " (calls per answer differ by answer)"
    if p.extra_calls:
        line += f", {p.extra_calls}"
    return line + "."


def cost_words(p: Plan) -> str:
    if p.cost is None:
        return "cost unknown"
    return prices.amount(*p.cost)


def plan_lines(p: Plan, title: str = "Ask your judge again") -> list[str]:
    """The plan as the terminal shows it."""
    lines = [title, "", f"  Your judge: {p.judge}"]
    if p.status == CANT:
        return lines + [f"  Your judge can't be asked again: {p.why}.", f"  {WRAP}"]
    lines.append({EXACT: f"  This is exactly your judge: {p.why}.",
                  CLOSE: f"  This is a close copy of your judge: {p.why}.",
                  OWN: f"  This is your own judge command. {p.why}."}[p.status])
    lines += [f"  {x}" for x in (*p.key_lines, *p.notes)]
    lines += ["", f"  {calls_line(p)}"]
    lines.append(f"  {p.cost_text or prices.cost_line(p.model, p.provider, p.tokens * p.times)}")
    lines += [f"  {x}" for x in (*p.left_out, *p.side_effects)]
    return lines


def menu_text(p: Plan) -> tuple[str, str]:
    """The menu's line for asking again, and its note in brackets."""
    text = f"Ask your judge again about your {_s(p.labeled, 'marked answer')}"
    if p.status == CANT:
        return text, f"(can't: {p.short})"
    note = f"{p.calls_note} " if p.calls_note else ""
    return text, f"({note}{p.calls:,} calls, {cost_words(p)})"


def run_tool(ws, plan: Plan, talk):
    """Ask for real with the plan's tool (after the yes): its Fresh."""
    from judgekeeper.again import command, deepeval, inspect, mlflow, promptfoo

    runs = {"promptfoo": promptfoo.run, "command": command.run, "deepeval": deepeval.run,
            "inspect": inspect.run, "mlflow": mlflow.run}
    return runs[plan.tool](ws, plan, talk)


# Spending --------------------------------------------------------------------------------------

def approve(p: Plan, talk, allow_calls: int | None, command: str = "--ask-again") -> bool:
    """Whether to spend the plan's calls. The question defaults to No and `--yes` never
    answers it. Without a terminal, and above 1,000 calls at a terminal too, only
    `--allow-calls N` (N at least the planned calls) approves."""
    from judgekeeper.start import EXIT_QUESTION, EXIT_USAGE, Stop, _interactive

    if p.status == CANT:
        return False
    flag = talk.command(command, "--allow-calls", str(p.calls))
    if allow_calls is not None:
        if allow_calls >= p.calls:
            return True
        talk.say(f"--allow-calls {allow_calls:,} is below the {p.calls:,} calls planned. "
                 "Your judge was not called; nothing was spent.")
        raise Stop(EXIT_USAGE)
    if p.calls > ALWAYS_ASK_ABOVE:
        talk.say(f"More than 1,000 calls: to go ahead, run {flag}")
        raise Stop(EXIT_QUESTION)
    if not _interactive():
        talk.say(f"To go ahead without a terminal: {flag}")
        raise Stop(EXIT_QUESTION)
    return talk.confirm("Go ahead?", default=False, with_yes=False,
                        hint=f"To go ahead: {flag}")


__all__ = [
    "AgainOptions",
    "Plan",
    "approve",
    "make_plan",
    "menu_text",
    "plan_lines",
    "run_process",
    "run_worker",
    "start_worker",
    "user_python",
    "which",
]
