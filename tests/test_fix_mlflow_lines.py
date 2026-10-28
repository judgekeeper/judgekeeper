"""With MLflow, the new grades are a new run in the same store: every line that says what to
run next names the store (`judgekeeper fix mlflow.db`, or the mlruns/ folder), never
marked-answers.csv or a new results file."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from judgekeeper import fix
from tests.test_fix import here, project, run  # noqa: F401


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
