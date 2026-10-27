"""judgekeeper only reads files: no command starts a program (the marking page aside, which runs
in a thread here) or opens a network connection, on the results of every eval tool it reads.

`judgekeeper fix` writes mistakes.md and marked-answers.csv; the results of grading those
answers again, given as `judgekeeper fix <file>`, test the new rule on the marks kept aside.
`judgekeeper check <file>` compares the grades in a results file with all the marks. No test
calls an API.
"""

from __future__ import annotations

import contextlib
import csv
import json
import os
import re
import socket
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest

from judgekeeper import fix, label, table
from judgekeeper.cli import main
from judgekeeper.start_label import StartSession, Workspace
from tests.start_projects import (
    answer,
    deepeval_data,
    inspect_data,
    promptfoo_data,
    question,
)

N = 40
JUDGE_PASSES = 20  # the LLM-as-a-judge passes answers 0-19 and fails 20-39
WRONG = set(range(6)) | set(range(20, 24))  # the person disagrees on these
TOOLS = ("promptfoo", "deepeval", "inspect", "mlflow", "jsonl")
LOCAL = ("127.0.0.1", "::1", "localhost", "", None)
ROOT = Path(__file__).resolve().parent.parent


def judge(i: int) -> bool:
    return i < JUDGE_PASSES


def person(i: int) -> bool:
    return judge(i) != (i in WRONG)


# What judgekeeper may not do -------------------------------------------------------------------

@contextlib.contextmanager
def only_reads(monkeypatch):
    """No program started and no connection beyond this computer while the block runs:
    each attempt is kept (and refused), so a test sees it even when judgekeeper catches the
    error."""
    started, reached = [], []

    def refuse(name):
        def run(*args, **kwargs):
            started.append(name)
            raise OSError(f"{name} is not allowed here")
        return run

    real_connect, real_connect_ex = socket.socket.connect, socket.socket.connect_ex
    real_lookup = socket.getaddrinfo

    def host(address):
        return address[0] if isinstance(address, tuple) else address

    def connect(self, address):
        if self.family != getattr(socket, "AF_UNIX", None) and host(address) not in LOCAL:
            reached.append(address)
            raise OSError("no network here")
        return real_connect(self, address)

    def connect_ex(self, address):
        if self.family != getattr(socket, "AF_UNIX", None) and host(address) not in LOCAL:
            reached.append(address)
            return 111
        return real_connect_ex(self, address)

    def lookup(name, *args, **kwargs):
        if name not in LOCAL:
            reached.append(name)
            raise socket.gaierror("no network here")
        return real_lookup(name, *args, **kwargs)

    with monkeypatch.context() as m:
        m.setattr(subprocess.Popen, "__init__", refuse("subprocess"))
        for name in ("system", "popen", "fork", "forkpty", "posix_spawn", "posix_spawnp",
                     "startfile", *(n for n in dir(os) if n.startswith(("exec", "spawn")))):
            if hasattr(os, name):
                m.setattr(os, name, refuse(f"os.{name}"))
        m.setattr(socket.socket, "connect", connect)
        m.setattr(socket.socket, "connect_ex", connect_ex)
        m.setattr(socket, "getaddrinfo", lookup)
        yield started, reached
    assert started == [], f"a program was started: {started}"
    assert reached == [], f"the network was reached: {reached}"


# One project per eval tool ----------------------------------------------------------------------

MLFLOW_STORE = r"""
import json, os, sys
os.environ["MLFLOW_DISABLE_AGENT_HINT"] = "1"
import mlflow
from mlflow.entities import AssessmentSource

path, rows = sys.argv[1], json.loads(sys.argv[2])
mlflow.set_tracking_uri("sqlite:///" + path)
mlflow.set_experiment("support")
judge = AssessmentSource(source_type="LLM_JUDGE", source_id="openai:/gpt-4.1")

for q, a, verdict in rows:
    @mlflow.trace(name="app")
    def app(question):
        return a
    app(q)
    mlflow.flush_trace_async_logging()
    mlflow.log_feedback(trace_id=mlflow.get_last_active_trace_id(), name="helpful",
                        value=verdict, source=judge, rationale="because")
"""


def _keep(i: int, drop) -> bool:
    return i not in drop


def write_results(tool: str, path: Path, verdicts: dict[int, bool], regraded: bool = False):
    """The results of `tool` at `path` for the answers in `verdicts` ({index: pass}).
    `regraded`: as from grading marked-answers.csv again (promptfoo's vars hold the answer
    too, so its answers are found by their text)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    order = sorted(verdicts)
    if tool == "promptfoo":
        data = promptfoo_data([verdicts[i] for i in order])
        rows = data["results"]["results"]
        for row, i in zip(rows, order, strict=True):
            qvars = {"question": question(i), **({"answer": answer(i)} if regraded else {})}
            row["vars"] = row["testCase"]["vars"] = qvars
            row["response"]["output"] = answer(i)
        path.write_text(json.dumps(data), encoding="utf-8")
    elif tool == "deepeval":
        data = deepeval_data([verdicts[i] for i in order])
        for case, i in zip(data["testCases"], order, strict=True):
            case.update(input=question(i), actualOutput=answer(i), name=f"case-{i}")
        path.write_text(json.dumps(data), encoding="utf-8")
    elif tool == "inspect":
        data = inspect_data([verdicts[i] for i in order])
        for sample, i in zip(data["samples"], order, strict=True):
            sample.update(id=i, input=question(i))
            sample["output"]["completion"] = answer(i)
        path.write_text(json.dumps(data), encoding="utf-8")
    elif tool == "mlflow":
        pytest.importorskip("mlflow")
        rows = [[question(i), answer(i), verdicts[i]] for i in order]
        script = path.parent / "make_store.py"
        script.write_text(MLFLOW_STORE, encoding="utf-8")
        subprocess.run([sys.executable, str(script), str(path), json.dumps(rows)], check=True,
                       cwd=path.parent, capture_output=True)
        script.unlink()
    else:
        path.write_text("".join(json.dumps({"input": question(i), "output": answer(i),
                                            "verdict": "pass" if verdicts[i] else "fail",
                                            "model": "gpt-4.1"}) + "\n" for i in order),
                        encoding="utf-8")
    return path


FIRST = {"promptfoo": "results.json", "deepeval": ".deepeval/.latest_run_full.json",
         "inspect": "logs/2026-10-02_support.json", "mlflow": "mlflow.db",
         "jsonl": "results.jsonl"}
NEW = {"promptfoo": "regraded.json", "deepeval": "regraded.json", "inspect": "regraded.json",
       "mlflow": "regraded/mlflow.db", "jsonl": "regraded.jsonl"}


@pytest.fixture
def here(tmp_path, monkeypatch):
    project = tmp_path / "support-bot"
    project.mkdir()
    monkeypatch.chdir(project)
    return project


def closed(ws: Workspace, timeout: float = 30) -> None:
    deadline = time.monotonic() + timeout
    while label.read_lock(ws.dir) is not None:
        assert time.monotonic() < deadline, "the marking page did not close"
        main(["--stop"])
        time.sleep(0.05)


def index(ws: Workspace) -> dict[str, int]:
    """{answer id: its index} from pool.jsonl."""
    out = {}
    for line in ws.pool.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        out[row["id"]] = int(re.search(r"Question (\d+)\?", json.dumps(row["input"]))[1])
    return out


def mark_all(ws: Workspace) -> None:
    where = index(ws)
    session = StartSession(ws)
    for item in session.items:
        session.update({"id": item["id"], "label": "pass" if person(where[item["id"]]) else "fail",
                        "seconds": 5})


def project(tool: str, root: Path, monkeypatch) -> Workspace:
    if tool == "promptfoo":
        (root / "promptfooconfig.yaml").write_text(
            "description: support bot\nprompts:\n  - 'Answer: {{question}}'\n", encoding="utf-8")
    write_results(tool, root / FIRST[tool], {i: judge(i) for i in range(N)})
    with only_reads(monkeypatch):
        assert main(["--no-browser"]) == 0
    ws = Workspace(root)
    mark_all(ws)
    with only_reads(monkeypatch):
        closed(ws)
    return ws


def run(capsys, *argv) -> tuple[int, str]:
    code = main([str(a) for a in argv])
    out, err = capsys.readouterr()
    for line in (out + err).splitlines():
        assert len(line) <= 80, line
    return code, out + err


def hidden(ws: Workspace) -> list[int]:
    where = index(ws)
    return sorted(where[i] for i in fix.read_split(ws).hidden)


def mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


# Every command, every reader --------------------------------------------------------------------

@pytest.mark.parametrize("tool", TOOLS)
def test_fix_round_trip_reads_files_only(tool, here, capsys, monkeypatch):
    ws = project(tool, here, monkeypatch)
    capsys.readouterr()
    with only_reads(monkeypatch):
        code, out = run(capsys, "mark", "--no-browser", "--stop")
        code, out = run(capsys, "fix")
    assert code == 0, out
    folder = ws.dir / "fix"
    if os.name != "nt":
        assert mode(folder / "mistakes.md") == mode(folder / "marked-answers.csv") == 0o600
    rows = list(csv.reader((folder / "marked-answers.csv").open(encoding="utf-8")))
    assert rows[0] == ["question", "answer"] and len(rows) == N + 1
    assert {tuple(r) for r in rows[1:]} == {(question(i), answer(i)) for i in range(N)}
    kept = hidden(ws)
    assert len(kept) == N // 2  # half of each cell: 3 + 2 of the mistakes, 7 + 8 of the rest
    assert fix.regrade_line(None if tool == "jsonl" else tool) in " ".join(out.split())
    file = {"inspect": fix.new_log(ws), "mlflow": fix.mlflow_store(ws)}.get(tool, fix.NEW_RESULTS)
    assert f"fix {file}" in " ".join(out.split())

    gone = kept[0]  # not graded again: said, and no verdict without it
    new = write_results(tool, here / NEW[tool],
                        {i: person(i) for i in range(N) if i != gone}, regraded=True)
    with only_reads(monkeypatch):
        code, out = run(capsys, "fix", new.relative_to(here))
    assert code == 3, out
    said = " ".join(out.split())
    assert (f"Result: can't tell. 1 of the {len(kept)} answers kept aside has no grade in your "
            "new results: 1 is not in the file.") in said
    again = fix.mlflow_store(ws) if tool == "mlflow" else "marked-answers.csv"  # a new run there
    assert again in said[said.rindex("Next:"):]
    assert fix.read_split(ws).tests == []

    new = write_results(tool, here / NEW[tool], {i: person(i) for i in range(N)}, regraded=True)
    with only_reads(monkeypatch):
        code, out = run(capsys, "fix", new.relative_to(here))
    assert code == 0, out
    assert f"tested on the {len(kept)} marks kept aside" in " ".join(out.split())
    test = fix.read_split(ws).tests[-1]
    assert test["n"] == len(kept) and test["broke"] == 0
    assert test["fixed"] == len(WRONG & set(kept))
    if os.name != "nt":
        assert all(mode(p) == 0o600 for p in folder.iterdir() if p.is_file())

    with only_reads(monkeypatch):
        code, out = run(capsys, "check")
        code, out = run(capsys, "check", new.relative_to(here))
    assert code in (0, 1), out


# The verdict's words ----------------------------------------------------------------------------

def _regraded(ws, here, verdicts) -> Path:
    return write_results("promptfoo", here / "regraded.json", verdicts, regraded=True)


def test_cant_tell_yet_says_how_many_mistakes_are_kept_aside(here, capsys, monkeypatch):
    ws = project("promptfoo", here, monkeypatch)
    capsys.readouterr()
    run(capsys, "fix")
    kept = hidden(ws)
    wrong = sorted(WRONG & set(kept))
    right = [i for i in kept if i not in WRONG]
    verdicts = {i: judge(i) for i in range(N)}
    verdicts[wrong[0]] = person(wrong[0])  # one fixed
    verdicts[right[0]] = not person(right[0])  # one broken
    code, out = run(capsys, "fix", _regraded(ws, here, verdicts).name)
    said = " ".join(out.split())
    assert code == 0 and "Result: can't tell yet." in said
    assert (f"Only {len(wrong)} of your LLM-as-a-judge's mistakes are kept aside; 'better' needs "
            "about 6 fixed and none broken. Mark more answers to get a clearer test.") in said


def test_worse_says_to_copy_the_old_rule_back(here, capsys, monkeypatch):
    ws = project("promptfoo", here, monkeypatch)
    capsys.readouterr()
    run(capsys, "fix")
    verdicts = {i: not person(i) for i in range(N)}  # every answer graded the other way
    code, out = run(capsys, "fix", _regraded(ws, here, verdicts).name)
    said = " ".join(out.split())
    assert code == 0 and "Result: it looks worse." in said
    assert "Next: copy your old rule back into your eval tool" in said


def test_fix_reads_only_results_of_the_same_tool_and_judge(here, capsys, monkeypatch):
    project("promptfoo", here, monkeypatch)
    capsys.readouterr()
    run(capsys, "fix")
    other = write_results("jsonl", here / "other.jsonl", {i: person(i) for i in range(N)})
    code, out = run(capsys, "fix", other.name)
    assert code == 2
    assert "judgekeeper compares an LLM-as-a-judge only within one eval tool" in \
        " ".join(out.split())


def test_results_with_no_rule_are_told_apart_by_their_grades(here, capsys, monkeypatch):
    """Grades from a file that holds no rule look like the same LLM-as-a-judge every time:
    a first test does not retire the marks kept aside, a second rule is a new test, and the
    same grades again are the test before."""
    ws = project("jsonl", here, monkeypatch)
    capsys.readouterr()
    run(capsys, "fix")
    kept = hidden(ws)
    wrong = sorted(WRONG & set(kept))
    first = {i: person(i) if i == wrong[0] else judge(i) for i in range(N)}
    second = {i: person(i) if i in wrong[:2] else judge(i) for i in range(N)}
    a = write_results("jsonl", here / "a.jsonl", first)
    b = write_results("jsonl", here / "b.jsonl", second)
    for path in (a, b):
        code, out = run(capsys, "fix", path.name)
        assert code == 0 and "You tested this LLM-as-a-judge before" not in out, out
    assert hidden(ws) == kept and len(fix.read_split(ws).rules()) == 2
    code, out = run(capsys, "fix", a.name)
    assert code == 0 and "You tested this LLM-as-a-judge before" in " ".join(out.split())
    assert len(fix.read_split(ws).tests) == 2


# What marked-answers.csv holds -----------------------------------------------------------------

KEY = "sk-ant-api03-" + "Zq7Xw2Lp" * 5
SNEAKY = {  # {index: (question, answer)}: each would run as a formula in a spreadsheet
    0: ("=HYPERLINK(\"https://example.com\") Question 0?", f"Use {KEY} to sign in."),
    1: ("\u200b+1 Question 1?", "\u2060@SUM(A1) Answer 1."),
    2: (" \ufeff-2 Question 2?", "\t=1+1 Answer 2."),
}


@pytest.mark.parametrize("cell", ["\u200b=1", "\u2060 @SUM(A1)", "\ufeff+1", " \u200d-2",
                                  "\u00ad\t1", "\x00=1"])
def test_unseen_characters_before_a_formula_still_guard_it(cell):
    assert table.guard_cell(cell) == "'" + cell
    assert table.unguard_cell(table.guard_cell(cell)) == cell


@pytest.mark.parametrize("space", ["\u00a0", "\u1680", "\u2000", "\u2005", "\u200a", "\u202f",
                                   "\u205f", "\u3000", "\u2028", "\u2029", "\n", "\r\n",
                                   "\x0b", "\x0c", "\x85"])
@pytest.mark.parametrize("start", ["=", "+", "-", "@"])
def test_any_space_or_line_break_before_a_formula_still_guards_it(space, start):
    cell = f"{space}{start}HYPERLINK(\"http://127.0.0.1:9/x\") Answer"
    assert table.guard_cell(cell) == "'" + cell
    assert table.unguard_cell(table.guard_cell(cell)) == cell


def test_marked_answers_hide_keys_and_guard_formulas(here, capsys, monkeypatch):
    texts = {i: SNEAKY.get(i, (question(i), answer(i))) for i in range(N)}
    (here / "results.jsonl").write_text("".join(json.dumps(
        {"input": q, "output": a, "verdict": "pass" if judge(i) else "fail",
         "model": "gpt-4.1"}) + "\n" for i, (q, a) in texts.items()), encoding="utf-8")
    with only_reads(monkeypatch):
        assert main(["--no-browser"]) == 0
    ws = Workspace(here)
    mark_all(ws)
    with only_reads(monkeypatch):
        closed(ws)
        capsys.readouterr()
        code, out = run(capsys, "fix")
    assert code == 0, out
    path = ws.dir / "fix" / "marked-answers.csv"
    written = path.read_text(encoding="utf-8")
    assert KEY not in written and "[REDACTED]" in written
    cells = [cell for row in list(csv.reader(written.splitlines(keepends=True)))[1:]
             for cell in row]
    assert len(cells) == 2 * N
    sneaky = [cell for cell in cells if table.unguard_cell(cell) != cell]
    assert len(sneaky) == 5  # all but the answer with the key, which starts with a word
    assert not [cell for cell in cells if table.unguard_cell(cell) == cell
                and table.guard_cell(cell) != cell]

    # graded again straight from the file, guard quotes and all: every answer is still found
    rows = list(csv.DictReader(written.splitlines(keepends=True)))
    where = {table.unguard_cell(r["question"]): r for r in rows}
    regraded = here / "regraded.jsonl"
    regraded.write_text("".join(json.dumps(
        {"input": where[q]["question"], "output": where[q]["answer"],
         "verdict": "pass" if person(i) else "fail", "model": "gpt-4.1"}) + "\n"
        for i, (q, _) in texts.items()), encoding="utf-8")
    with only_reads(monkeypatch):
        code, out = run(capsys, "fix", regraded.name)
    assert code == 0, out
    assert f"tested on the {len(hidden(ws))} marks kept aside" in " ".join(out.split())
    assert "not in your new results" not in out


# check ------------------------------------------------------------------------------------------

def test_check_with_a_file_says_one_run_and_exits_1_only_over_20_points(here, capsys,
                                                                       monkeypatch):
    ws = project("promptfoo", here, monkeypatch)
    capsys.readouterr()
    small = {i: judge(i) for i in range(N)}
    fails = [i for i in range(N) if not person(i) and not judge(i)]  # agreed fails
    for i in fails[:2]:  # 2 of 22 answers the person failed: about 9 points lower
        small[i] = True
    path = write_results("promptfoo", here / "small.json", small)
    data = json.loads(path.read_text(encoding="utf-8"))
    for row in data["results"]["results"]:  # another model: a changed LLM-as-a-judge
        row["testCase"]["options"]["provider"]["id"] = "openai:gpt-4.1"
    path.write_text(json.dumps(data), encoding="utf-8")
    with only_reads(monkeypatch):
        code, out = run(capsys, "check", path.name)
    assert code == 0, out
    assert "One run, so a small change may be chance." in out

    big = dict(small)
    for i in fails[:12]:  # 12 of 22: over 20 points lower
        big[i] = True
    path = write_results("promptfoo", here / "big.json", big)
    data = json.loads(path.read_text(encoding="utf-8"))
    for row in data["results"]["results"]:
        row["testCase"]["options"]["provider"]["id"] = "openai:gpt-4.1-nano"
    path.write_text(json.dumps(data), encoding="utf-8")
    code, out = run(capsys, "check", path.name)
    assert code == 1, out
    assert "One run, so a small change may be chance." in out
    assert ws.marks.is_file()


# Step 1 -----------------------------------------------------------------------------------------

def test_step_1_with_only_a_promptfoo_config_says_how_to_save_results(here, capsys,
                                                                      monkeypatch):
    (here / "promptfooconfig.yaml").write_text(
        "description: support bot\nprompts:\n  - 'Answer: {{question}}'\n", encoding="utf-8")
    with only_reads(monkeypatch):
        code, out = run(capsys)
    assert code == 3  # the person is needed: nothing to read yet
    said = " ".join(out.split())
    assert "promptfoo eval -o promptfoo-results.json" in said
    assert "promptfoo list evals" in said
    assert "promptfoo export eval <id> -o promptfoo-results.json" in said
    assert "latest" not in said
    assert not (here / ".judgekeeper" / "promptfoo-latest.json").exists()


# Flags ------------------------------------------------------------------------------------------

@pytest.mark.parametrize("argv", [["--fields", "input"], ["mark", "--fields", "input"],
                                  ["fix", "--yes"], ["check", "--yes"]])
def test_removed_flags_are_unknown(argv, here, capsys):
    assert main(argv) == 2
    assert f"unrecognized arguments: {argv[-2] if argv[-1] == 'input' else argv[-1]}" in \
        capsys.readouterr().err


# Programs started, in a fresh process -----------------------------------------------------------

WATCH = r"""
import json, os, sys
LOCAL = ("127.0.0.1", "::1", "localhost", "", None)
seen = []

def hook(event, args):
    if event == "subprocess.Popen":
        argv = args[1] if isinstance(args[1], (list, tuple)) else [args[1] or args[0]]
        seen.append(["program", os.path.basename(str(argv[0]))])
    elif event in ("os.system", "os.exec", "os.posix_spawn", "os.spawn", "os.startfile"):
        seen.append(["program", event])
    elif event == "socket.connect":
        address = args[1]
        host = address[0] if isinstance(address, tuple) else None
        if host not in LOCAL:
            seen.append(["network", str(host)])
    elif event == "socket.getaddrinfo" and args[0] not in LOCAL:
        seen.append(["network", str(args[0])])

sys.addaudithook(hook)
from judgekeeper.cli import main
try:
    code = main(sys.argv[2:])
finally:
    with open(sys.argv[1], "w", encoding="utf-8") as f:
        json.dump(seen, f)
sys.exit(code)
"""
MLFLOW_TOOLS = {"uname", "file"}  # MLflow's own library runs these as it loads


@pytest.mark.parametrize("tool", ["mlflow", "jsonl"])
def test_fix_and_check_start_no_program_in_a_fresh_process(tool, here, capsys, monkeypatch,
                                                            tmp_path):
    ws = project(tool, here, monkeypatch)
    new = write_results(tool, here / ("regraded/mlflow.db" if tool == "mlflow"
                                      else "regraded.jsonl"),
                        {i: person(i) for i in range(N)}, regraded=True)
    script = tmp_path / "watch.py"
    script.write_text(WATCH, encoding="utf-8")
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    for argv in (["fix"], ["fix", str(new.relative_to(here))], ["check"]):
        seen_file = tmp_path / "seen.json"
        done = subprocess.run([sys.executable, str(script), str(seen_file), *argv], cwd=here,
                              env=env, capture_output=True, text=True, timeout=300,
                              stdin=subprocess.DEVNULL, check=False)
        assert done.returncode in (0, 1, 3), done.stdout + done.stderr
        seen = json.loads(seen_file.read_text(encoding="utf-8"))
        assert [s for s in seen if s[0] == "network"] == [], (argv, seen)
        programs = {s[1] for s in seen if s[0] == "program"}
        assert programs <= (MLFLOW_TOOLS if tool == "mlflow" else set()), (argv, programs)
    assert ws.dir.is_dir()


# The main command after a change ----------------------------------------------------------------

def test_main_command_names_the_judge_of_the_result_and_points_to_check(here, capsys,
                                                                       monkeypatch):
    ws = project("promptfoo", here, monkeypatch)
    capsys.readouterr()
    data = json.loads((here / "results.json").read_text(encoding="utf-8"))
    for row in data["results"]["results"]:  # the same tool and judge, another model
        row["testCase"]["options"]["provider"]["id"] = "openai:gpt-4.1"
    (here / "results.json").write_text(json.dumps(data), encoding="utf-8")
    capsys.readouterr()
    with only_reads(monkeypatch):
        code, out = run(capsys, "--no-browser")
    closed(ws)
    assert code == 0, out
    said = " ".join(out.split())
    assert "This result is about your LLM-as-a-judge as it was" in said
    assert "openai:gpt-4.1-mini" in said
    assert re.search(r"Next: .*`judgekeeper check`", said), said
