"""With MLflow, the new grades are a new run in the same store: every line that says what to
run next names the store (`judgekeeper fix mlflow.db`, or the mlruns/ folder), never
marked-answers.csv or a new results file."""

from __future__ import annotations

import json
import re
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

from judgekeeper import fix
from judgekeeper.cli import main
from tests.test_fix import here, project, run  # noqa: F401
from tests.test_front import next_lines

STORE = r"""
import os
os.environ["MLFLOW_ALLOW_FILE_STORE"] = "true"
os.environ["MLFLOW_DISABLE_AGENT_HINT"] = "1"
os.environ["MLFLOW_DISABLE_TELEMETRY"] = "true"
import mlflow
from mlflow.entities import AssessmentSource

mlflow.set_tracking_uri("mlruns")
mlflow.set_experiment("folder-store")
judge = AssessmentSource(source_type="LLM_JUDGE", source_id="openai:/gpt-4.1")

@mlflow.trace(name="app")
def app(question):
    return f"answer to {question}"

for i in range(40):
    app(f"question {i}")
    mlflow.flush_trace_async_logging()
    mlflow.log_feedback(trace_id=mlflow.get_last_active_trace_id(), name="helpful",
                        value=i % 2 == 0, source=judge)
"""


class _Talk:
    def command(self, sub: str = "") -> str:
        return f"judgekeeper {sub or 'fix'}"


def _as_mlflow(ws, store: str) -> None:
    data = json.loads(ws.start.read_text(encoding="utf-8"))
    data.update(tool="mlflow", mlflow_store=store)
    ws.start.write_text(json.dumps(data), encoding="utf-8")


@pytest.mark.parametrize("store", ["mlflow.db", "mlruns"])
def test_fix_names_the_mlflow_store_to_read_next(here, capsys, store):  # noqa: F811
    ws = project(here)
    _as_mlflow(ws, store)
    code, out = run(capsys)
    said = " ".join(out.split())
    assert code == 0, out
    assert f"then run `judgekeeper fix {store}`: it reads the newest run." in said, said
    assert fix.NEW_RESULTS not in said and "again, save the results" not in said, said


class _Marks:
    def __init__(self):
        self.data = {}


def test_the_lines_after_a_test_name_the_mlflow_store(here):  # noqa: F811
    ws = project(here)
    _as_mlflow(ws, "mlflow.db")
    worse = fix._after_step(_Talk(), ws, _Marks(), "worse", Path("mlflow.db"))
    assert "run `judgekeeper fix mlflow.db` again" in worse, worse
    better = fix._after_step(_Talk(), ws, _Marks(), "better", Path("mlflow.db"))
    assert "then run `judgekeeper check mlflow.db` to re-check it" in better, better
    missing = fix._regrade_same(_Talk(), ws)
    assert "`judgekeeper fix mlflow.db`" in missing and "marked-answers" not in missing, missing


def test_check_given_a_file_it_cant_read_names_the_mlflow_store(here, capsys):  # noqa: F811
    from judgekeeper.cli import main

    ws = project(here)
    _as_mlflow(ws, "mlflow.db")
    (here / "other.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    code = main(["check", "other.csv"])
    said = " ".join(capsys.readouterr().out.split())
    assert code == 2, said
    assert "Next: run `judgekeeper check mlflow.db`: it reads the newest run" in said, said


def test_start_keeps_the_mlflow_experiment_read(tmp_path, monkeypatch):
    """Several experiments may hold the same LLM-as-a-judge: the one marking started on is kept
    in start.json, so `check` and `fix` read that one again without asking."""
    from dataclasses import replace

    from judgekeeper import start, start_label
    from tests.start_projects import promptfoo_project, split

    monkeypatch.chdir(tmp_path)
    promptfoo_project(tmp_path, split(20, 16))
    found = replace(start.find_judge(tmp_path), experiment="app-a")
    ws = start_label.prepare(found, lambda *a, **k: None)
    assert json.loads(ws.start.read_text(encoding="utf-8"))["experiment"] == "app-a"


@pytest.mark.parametrize("given", [[], ["mlflow.db"]])
def test_check_and_fix_read_the_experiment_marking_started_on(here, capsys, monkeypatch,  # noqa: F811
                                                              given):
    from judgekeeper import start
    from judgekeeper.cli import main

    ws = project(here)
    _as_mlflow(ws, "mlflow.db")
    data = json.loads(ws.start.read_text(encoding="utf-8"))
    ws.start.write_text(json.dumps({**data, "experiment": "app-a"}), encoding="utf-8")
    (here / "mlflow.db").write_bytes(b"")
    asked = []

    def find_judge(path, **options):
        asked.append(options)
        raise start.StartError("stop here")

    monkeypatch.setattr(start, "find_judge", find_judge)
    main(["check", *given])
    if given:
        main(["fix", *given])
    capsys.readouterr()
    assert asked and all(o.get("experiment") == "app-a" for o in asked), asked


@pytest.fixture(scope="module")
def mlruns(tmp_path_factory):
    """A real MLflow folder store of 40 graded traces, made by the installed MLflow."""
    pytest.importorskip("mlflow")
    build = tmp_path_factory.mktemp("mlruns-build")
    (build / "make_store.py").write_text(STORE, encoding="utf-8")
    subprocess.run([sys.executable, "make_store.py"], cwd=build, check=True,
                   capture_output=True)
    return build / "mlruns"


def _printed(capsys, argv: list[str], sub: str) -> tuple[str, list[str]]:
    """What `argv` says, and the `judgekeeper {sub} ...` command its last Next: line names."""
    main(argv)
    out = capsys.readouterr().out
    commands = [shlex.split(c) for c in re.findall(r"`(judgekeeper [^`]*)`", next_lines(out)[-1])]
    return out, next(c[1:] for c in commands if c[1] == sub)


def test_the_printed_fix_and_check_commands_read_the_mlruns_store(mlruns, tmp_path,
                                                                  monkeypatch, capsys):
    import shutil

    from judgekeeper import start, start_label
    from judgekeeper.readers import mlflow_store
    from judgekeeper.start_label import StartSession
    from tests.start_projects import save_result

    monkeypatch.setattr(mlflow_store, "_walked", {})
    shutil.copytree(mlruns, tmp_path / "mlruns")
    monkeypatch.chdir(tmp_path)
    ws = start_label.prepare(start.find_judge(tmp_path), say=lambda line="": None)
    session = StartSession(ws)
    for i, q in enumerate(ws.data()["queue"]):  # 1 in 5 marked the other way: mistakes to fix
        session.update({"id": q["id"], "label": q["group"] if i % 5 else
                        {"pass": "fail", "fail": "pass"}[q["group"]]})
    save_result(ws, session, say=lambda line="": None)

    _, printed = _printed(capsys, ["fix"], "fix")
    assert printed == ["fix", "mlruns"]
    out, again = _printed(capsys, printed, "fix")
    said = " ".join(out.split())
    assert "New results: mlruns" in said and "same grades as when you marked" in said, said
    assert again == printed
    out, printed = _printed(capsys, ["check", "mlruns"], "check")
    said = " ".join(out.split())
    assert "New results: mlruns" in said and "has not changed" in said, said
    assert printed == ["check", "mlruns"]
    mlflow_store.remove_copies()
