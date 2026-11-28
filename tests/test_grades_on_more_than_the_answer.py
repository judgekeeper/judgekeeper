"""A grade can follow more than the question and the answer: the turns of a DeepEval
conversation, the documents a DeepEval case retrieved (retrievalContext, context), the run
behind a promptfoo agent assertion (agent-rubric, trajectory:goal-success). What the results
hold of it counts with the answer; when the results can't hold all of it, the answer is
compared, never taken as the same answer graded otherwise. An agent change there with the same
final answer read as "Only the grades changed" (exit 0) or "does not compare" (exit 3)."""

import copy
import json

import pytest

from judgekeeper import before_after
from tests.start_projects import deepeval_data, promptfoo_data
from tests.test_compare_after_check import _flat, _run

N = 40
VERDICTS = [i % 4 != 0 for i in range(N)]  # 30 pass, 10 fail
FLIP = [i for i, v in enumerate(VERDICTS) if v][:10]  # 10 passing cases that fail now
BROKE_10 = f"On the {N} questions in both results: fixed 0, broke 10,"
FILES = {"deepeval": ("results/test_run_20261101_120000.json",
                      "old/test_run_20261101_110000.json"),
         "promptfoo": ("results/output.json", "old/output.json")}  # (now, before)
NOW = FILES["deepeval"][0]


def _said(capsys, *argv) -> tuple[int, str]:
    code, out = _run(capsys, *argv, "--no-browser", "--port", "0")
    _run(capsys, "--stop")
    return code, _flat(out)


def _write(path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _deepeval(path, kind: str, changed: bool, agent: bool = True) -> None:
    """kind "conv": conversations (scenario and turns); "noturns": conversations saved without
    their turns; "rag": cases with a retrievalContext. `changed`: the 10 FLIP cases fail now,
    with a new reply or new documents when `agent`, else on the same ones."""
    data = deepeval_data(VERDICTS, model="gpt-4.1")
    cases = []
    for i, c in enumerate(data["testCases"]):
        c = copy.deepcopy(c)
        new = changed and i in FLIP
        if new:
            c["metricsData"][0].update(success=False, score=0.1)
            c["success"] = False
        new = new and agent
        if kind == "rag":
            c["retrievalContext"] = ["doc B, from the new retriever"] if new else ["doc A"]
            cases.append(c)
            continue
        if kind == "tools":  # under Tool Correctness: the tools the agent called
            c["metricsData"][0]["name"] = "Tool Correctness"
            c["toolsCalled"] = [{"name": "search_web" if new else "lookup_policy",
                                 "inputParameters": {"case": i}}]
            cases.append(c)
            continue
        reply = c["actualOutput"] + (" Something else entirely." if new else "")
        conv = {"name": c["name"], "scenario": c["input"], "success": c["success"],
                "metricsData": c["metricsData"]}
        if kind == "conv":
            conv["turns"] = [{"role": "user", "content": c["input"]},
                             {"role": "assistant", "content": reply}]
        cases.append(conv)
    if kind in ("rag", "tools"):
        data["testCases"] = cases
    else:
        data["conversationalTestCases"], data["testCases"] = cases, []
    _write(path, data)


def _promptfoo(path, kind: str, changed: bool, agent: bool = True) -> None:
    """promptfoo rows graded by `kind`: an assertion on the agent's run, which the file
    doesn't hold, or llm-rubric on a response whose tool calls and trace the file holds; the
    output stays the same, the FLIP rows' tool calls are new (with `agent`; else only their
    grades)."""
    data = promptfoo_data([not (changed and i in FLIP) and v for i, v in enumerate(VERDICTS)])
    for i, row in enumerate(data["results"]["results"]):
        tools = [{"name": "guess_answer" if changed and agent and i in FLIP else "lookup_order",
                  "args": {"id": i}}]
        row["response"] |= {"metadata": {"toolCalls": tools}, "cached": changed,
                            "tokenUsage": {"total": 40 + changed},
                            "trace": {"spans": [{"name": t["name"], "attributes": t["args"]}
                                                for t in tools]}}
        row["latencyMs"] = 5 + changed
        for c in row["gradingResult"]["componentResults"]:
            c["assertion"] = {"type": kind, "value": "The agent reached the user's goal."}
    _write(path, data)


WRITE = {
    "deepeval-turns": lambda path, changed: _deepeval(path, "conv", changed),
    "deepeval-retrieval": lambda path, changed: _deepeval(path, "rag", changed),
    "deepeval-no-turns": lambda path, changed: _deepeval(path, "noturns", changed),
    "deepeval-tools": lambda path, changed: _deepeval(path, "tools", changed),
    "promptfoo-tool-calls": lambda path, changed: _promptfoo(path, "llm-rubric", changed),
    "promptfoo-trajectory": lambda path, changed: _promptfoo(path, "trajectory:goal-success",
                                                             changed),
    "promptfoo-agent-rubric": lambda path, changed: _promptfoo(path, "agent-rubric", changed),
}


@pytest.mark.parametrize("before", [False, True], ids=["plain", "before"])
@pytest.mark.parametrize("kind", WRITE)
def test_an_agent_change_beside_the_answer_is_compared(tmp_path, monkeypatch, capsys, kind,
                                                       before):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CI", "true")
    now, old = FILES[kind.split("-")[0]]
    if before:
        WRITE[kind](tmp_path / old, False)
        WRITE[kind](tmp_path / now, True)
        code, out = _said(capsys, "results", "--before", old)
    else:
        WRITE[kind](tmp_path / now, False)
        assert _said(capsys)[0] == 0
        WRITE[kind](tmp_path / now, True)
        code, out = _said(capsys)
    assert code == 1 and BROKE_10 in out, out
    assert before_after.ONLY_GRADES not in out and before_after.ONLY_GRADES_BEFORE not in out


@pytest.mark.parametrize("kind", ["rag", "conv", "tools"])
def test_the_same_documents_and_turns_graded_otherwise_are_only_grades(tmp_path, monkeypatch,
                                                                        capsys, kind):
    """A guard: what the grade follows is all in the results and stayed the same."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CI", "true")
    _deepeval(tmp_path / NOW, kind, False)
    assert _said(capsys)[0] == 0
    _deepeval(tmp_path / NOW, kind, True, agent=False)
    code, out = _said(capsys)
    assert code == 0 and before_after.ONLY_GRADES in out, out


def test_the_same_tool_calls_graded_otherwise_are_only_grades(tmp_path, monkeypatch, capsys):
    """A guard: the same tool calls and trace; only what changes every run (cached, token
    usage, latency) changed with the grades."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CI", "true")
    path = tmp_path / FILES["promptfoo"][0]
    _promptfoo(path, "llm-rubric", False)
    assert _said(capsys)[0] == 0
    data = json.loads(path.read_text(encoding="utf-8"))
    for i, row in enumerate(data["results"]["results"]):
        row["response"] |= {"cached": True, "tokenUsage": {"total": 99}}
        row["latencyMs"] = 77
        if i in FLIP:
            for c in [row["gradingResult"], *row["gradingResult"]["componentResults"]]:
                c.update({"pass": False, "score": 0})
            row["success"] = False
    path.write_text(json.dumps(data), encoding="utf-8")
    code, out = _said(capsys)
    assert code == 0 and before_after.ONLY_GRADES in out, out


# MLflow: a judge on the trace can grade its steps (the spans under the root) -------------------

STORE = r"""
import json, os, sys
os.environ["MLFLOW_ALLOW_FILE_STORE"] = "true"
os.environ["MLFLOW_DISABLE_AGENT_HINT"] = "1"
import mlflow
from mlflow.entities import AssessmentSource

folder, verdicts, docs = sys.argv[1], json.loads(sys.argv[2]), json.loads(sys.argv[3])
mlflow.set_tracking_uri(folder)
mlflow.set_experiment("support")
judge = AssessmentSource(source_type="LLM_JUDGE", source_id="openai:/gpt-4.1")

@mlflow.trace(name="retrieve")
def retrieve(question):
    return [docs[int(question.split()[-1])]]

@mlflow.trace(name="app")
def app(question):
    retrieve(question)
    return f"answer to {question}"

for i, verdict in enumerate(verdicts):
    app(f"question {i}")
    mlflow.flush_trace_async_logging()
    trace_id = mlflow.get_last_active_trace_id()
    mlflow.log_feedback(trace_id=trace_id, name="grounded", value=verdict, source=judge)
"""


def _store(folder, changed: bool, steps: bool = True) -> None:
    """20 traces; `changed`: 8 passing ones fail now, with another retrieved document when
    `steps`. The final answers stay the same."""
    import subprocess
    import sys

    pytest.importorskip("mlflow")
    verdicts = [not (changed and i < 8) for i in range(20)]
    docs = ["doc B" if changed and steps and i < 8 else "doc A" for i in range(20)]
    folder.parent.mkdir(parents=True, exist_ok=True)
    script = folder.parent / f"make-{folder.parent.name}.py"
    script.write_text(STORE, encoding="utf-8")
    subprocess.run([sys.executable, str(script), str(folder), json.dumps(verdicts),
                    json.dumps(docs)], check=True, cwd=folder.parent, capture_output=True)
    script.unlink()


def test_an_mlflow_judge_on_changed_steps_is_compared(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CI", "true")
    _store(tmp_path / "old" / "mlruns", False)
    _store(tmp_path / "new" / "mlruns", True)
    monkeypatch.chdir(tmp_path / "new")
    code, out = _said(capsys, "mlruns", "--before", str(tmp_path / "old" / "mlruns"))
    assert code == 1 and "On the 20 questions in both results: fixed 0, broke 8," in out, out


def test_an_mlflow_judge_on_the_same_steps_graded_otherwise_is_only_grades(tmp_path,
                                                                          monkeypatch, capsys):
    """A guard: the same answers and steps, graded otherwise."""
    monkeypatch.setenv("CI", "true")
    _store(tmp_path / "old" / "mlruns", False)
    _store(tmp_path / "new" / "mlruns", True, steps=False)
    monkeypatch.chdir(tmp_path / "new")
    code, out = _said(capsys, "mlruns", "--before", str(tmp_path / "old" / "mlruns"))
    assert code == 3 and before_after.ONLY_GRADES_BEFORE in out, out


# A grade on parts of the run the results don't keep: a changed grade counts as a changed
# answer, and the run says so ------------------------------------------------------------------
UNREAD = ("These grades depend on parts of the run your results file doesn't keep, so a "
          "changed grade counts as a changed answer.")
REGRADE = {
    "promptfoo-trajectory": lambda path, changed: _promptfoo(path, "trajectory:goal-success",
                                                             changed, agent=False),
    "promptfoo-agent-rubric": lambda path, changed: _promptfoo(path, "agent-rubric", changed,
                                                               agent=False),
    "deepeval-no-turns": lambda path, changed: _deepeval(path, "noturns", changed,
                                                         agent=False),
}


@pytest.mark.parametrize("before", [False, True], ids=["plain", "before"])
@pytest.mark.parametrize("kind", REGRADE)
def test_a_grade_on_parts_the_file_doesnt_keep_says_so(tmp_path, monkeypatch, capsys, kind,
                                                       before):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CI", "true")
    now, old = FILES[kind.split("-")[0]]
    if before:
        REGRADE[kind](tmp_path / old, False)
        REGRADE[kind](tmp_path / now, True)
        code, out = _said(capsys, "results", "--before", old)
    else:
        REGRADE[kind](tmp_path / now, False)
        assert _said(capsys)[0] == 0
        REGRADE[kind](tmp_path / now, True)
        code, out = _said(capsys)
    assert code == 1 and BROKE_10 in out, out
    assert out.count(UNREAD) == 1 and out.index(UNREAD) < out.index("Your change made it worse")


def test_a_grade_on_parts_the_file_keeps_says_nothing_of_them(tmp_path, monkeypatch, capsys):
    """A guard: llm-rubric graded on the tool calls the file holds, graded otherwise."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CI", "true")
    now = tmp_path / FILES["promptfoo"][0]
    _promptfoo(now, "llm-rubric", False)
    assert _said(capsys)[0] == 0
    _promptfoo(now, "llm-rubric", True, agent=False)
    code, out = _said(capsys)
    assert code == 0 and before_after.ONLY_GRADES in out and UNREAD not in out, out


def test_an_agent_change_on_parts_the_file_keeps_says_nothing_of_them(tmp_path, monkeypatch,
                                                                      capsys):
    """Tool calls changed and graded by llm-rubric: compared, all of it in the file."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CI", "true")
    now = tmp_path / FILES["promptfoo"][0]
    _promptfoo(now, "llm-rubric", False)
    assert _said(capsys)[0] == 0
    _promptfoo(now, "llm-rubric", True)
    code, out = _said(capsys)
    assert code == 1 and BROKE_10 in out and UNREAD not in out, out


DB_STORE = r"""
import json, os, sys
os.environ["MLFLOW_DISABLE_AGENT_HINT"] = "1"
os.environ["MLFLOW_DISABLE_TELEMETRY"] = "true"
import mlflow
from mlflow.entities import AssessmentSource

mlflow.set_tracking_uri("sqlite:///mlflow.db")
mlflow.set_experiment("qa")
judge = AssessmentSource(source_type="LLM_JUDGE", source_id="openai:/gpt-4.1-mini")
for i, verdict in enumerate(json.loads(sys.argv[1])):
    with mlflow.start_span(name="app") as span:
        span.set_inputs({"question": f"Question {i}?"})
        span.set_outputs({"answer": f"Answer {i}."})
        trace_id = span.trace_id
    mlflow.flush_trace_async_logging()
    mlflow.log_feedback(trace_id=trace_id, name="correctness", value=verdict, source=judge)
mlflow.flush_trace_async_logging()
"""


def _store_without_spans(folder, changed: bool) -> None:
    """mlflow.db with 20 judged traces, 8 passing ones failing when `changed`, the answers
    the same; then its spans deleted, as a store whose spans are kept on another server."""
    import sqlite3
    import subprocess
    import sys
    from contextlib import closing

    pytest.importorskip("mlflow")
    folder.mkdir(parents=True)
    (folder / "make.py").write_text(DB_STORE, encoding="utf-8")
    verdicts = [not (changed and i < 8) for i in range(20)]
    subprocess.run([sys.executable, "make.py", json.dumps(verdicts)], check=True, cwd=folder,
                   capture_output=True)
    (folder / "make.py").unlink()
    with closing(sqlite3.connect(folder / "mlflow.db")) as con:
        con.execute("delete from spans")
        con.execute("delete from trace_tags where key = 'mlflow.trace.spansLocation'")
        con.execute("update trace_tags set value = ? || request_id where key = "
                    "'mlflow.artifactLocation'",
                    ("https://store.invalid/api/2.0/mlflow-artifacts/artifacts/x/",))
        con.commit()


def test_an_mlflow_judge_on_traces_without_their_spans_says_so(tmp_path, monkeypatch, capsys):
    """The traces' spans not in the store: the judge may have graded steps judgekeeper can't
    read."""
    monkeypatch.setenv("CI", "true")
    _store_without_spans(tmp_path / "old", False)
    _store_without_spans(tmp_path / "new", True)
    monkeypatch.chdir(tmp_path / "new")
    code, out = _said(capsys, "mlflow.db", "--before", str(tmp_path / "old" / "mlflow.db"))
    assert code == 1 and "On the 20 questions in both results: fixed 0, broke 8," in out, out
    assert out.count(UNREAD) == 1, out
