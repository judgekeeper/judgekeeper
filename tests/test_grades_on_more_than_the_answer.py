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
        reply = c["actualOutput"] + (" Something else entirely." if new else "")
        conv = {"name": c["name"], "scenario": c["input"], "success": c["success"],
                "metricsData": c["metricsData"]}
        if kind == "conv":
            conv["turns"] = [{"role": "user", "content": c["input"]},
                             {"role": "assistant", "content": reply}]
        cases.append(conv)
    if kind == "rag":
        data["testCases"] = cases
    else:
        data["conversationalTestCases"], data["testCases"] = cases, []
    _write(path, data)


def _promptfoo(path, kind: str, changed: bool) -> None:
    """promptfoo rows graded by `kind`, an assertion on the agent's run, which the file
    doesn't hold; the output stays the same."""
    data = promptfoo_data([not (changed and i in FLIP) and v for i, v in enumerate(VERDICTS)])
    for row in data["results"]["results"]:
        for c in row["gradingResult"]["componentResults"]:
            c["assertion"] = {"type": kind, "value": "The agent reached the user's goal."}
    _write(path, data)


WRITE = {
    "deepeval-turns": lambda path, changed: _deepeval(path, "conv", changed),
    "deepeval-retrieval": lambda path, changed: _deepeval(path, "rag", changed),
    "deepeval-no-turns": lambda path, changed: _deepeval(path, "noturns", changed),
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


@pytest.mark.parametrize("kind", ["rag", "conv"])
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
