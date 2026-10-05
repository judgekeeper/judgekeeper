"""Asking a Python tool's judge again: the plan for DeepEval, Inspect AI and MLflow.

The plan runs a small worker script in the user's Python in "dry" mode: it builds the judge
and checks it, with no API call. Here the workers run against stub packages written into a
temporary folder (no DeepEval, Inspect or MLflow needed); the stubs record what was built
and fail loudly if anything would call a model or write results.
"""

from __future__ import annotations

import builtins
import json
import sys
import textwrap

import pytest

from judgekeeper import again, keys, start, start_label
from judgekeeper.again import AgainOptions, make_plan, plan_lines, user_python
from judgekeeper.again import deepeval as de
from judgekeeper.again import mlflow as mf
from judgekeeper.start_label import StartSession, save_result
from tests.conftest import FIXTURES
from tests.start_projects import deepeval_project, inspect_project, split

DEEPEVAL_FILE = FIXTURES / "deepeval" / "results" / "test_run_20260930_120000.json"


def _quiet(line=""):
    pass


def _checked(root, maker, n_pass=20, n_fail=16, **kwargs):
    maker(root, split(n_pass, n_fail), **kwargs)
    ws = start_label.prepare(start.find_judge(root), say=_quiet)
    session = StartSession(ws)
    for q in ws.data()["queue"]:
        session.update({"id": q["id"], "label": q["group"]})
    save_result(ws, session, say=_quiet)
    return ws


def _write(folder, files: dict):
    for name, text in files.items():
        path = folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(text), encoding="utf-8")


@pytest.fixture(autouse=True)
def no_keys(monkeypatch):
    for name in keys.all_names():
        monkeypatch.delenv(name, raising=False)


# Stub packages -------------------------------------------------------------------------------

STUB_DEEPEVAL = {
    "deepeval/__init__.py": """
        import json, os
        __version__ = os.environ.get("STUB_VERSION", "4.2.8")
        def _log(kind, **data):
            with open(os.environ["STUB_LOG"], "a") as f:
                f.write(json.dumps({"kind": kind, **data}, default=str) + "\\n")
        _log("import", telemetry=os.environ.get("DEEPEVAL_TELEMETRY_OPT_OUT"),
             confident="CONFIDENT_API_KEY" in os.environ,
             results_folder="DEEPEVAL_RESULTS_FOLDER" in os.environ)
        def evaluate(*a, **k):
            _log("evaluate")
            raise AssertionError("evaluate must never be called")
    """,
    "deepeval/metrics/__init__.py": """
        import os
        from deepeval import _log
        class _Metric:
            def __init__(self, **kwargs):
                _log("construct", cls=type(self).__name__, kwargs=kwargs)
                self.evaluation_model = os.environ.get("STUB_MODEL", "gpt-4.1")
            def measure(self, *a, **k):
                _log("measure")
                raise AssertionError("no judge call in a dry run")
        class GEval(_Metric): pass
        class AnswerRelevancyMetric(_Metric): pass
        class FaithfulnessMetric(_Metric): pass
        class HallucinationMetric(_Metric): pass
        class BiasMetric(_Metric): pass
        class ToxicityMetric(_Metric): pass
        class ContextualRelevancyMetric(_Metric): pass
        class ContextualPrecisionMetric(_Metric): pass
        class ContextualRecallMetric(_Metric): pass
    """,
    "deepeval/metrics/g_eval/__init__.py": """
        class Rubric:
            def __init__(self, score_range, expected_outcome):
                self.score_range, self.expected_outcome = score_range, expected_outcome
            def __repr__(self):
                return f"Rubric({self.score_range!r}, {self.expected_outcome!r})"
    """,
    "deepeval/test_case/__init__.py": """
        class SingleTurnParams(str):
            pass
        class LLMTestCase:
            def __init__(self, **kwargs):
                self.kwargs = kwargs
    """,
}

STUB_INSPECT = {
    "inspect_ai/__init__.py": """
        import os
        __version__ = os.environ.get("STUB_VERSION", "0.3.273")
        def score(*a, **k):
            raise AssertionError("no scoring in a dry run")
        async def score_async(*a, **k):
            raise AssertionError("no scoring in a dry run")
    """,
    "inspect_ai/_util/__init__.py": "",
    "inspect_ai/_util/dotenv.py": """
        import os
        if os.environ.get("STUB_NO_DOTENV"):
            raise ImportError("init_dotenv was renamed")
        def init_dotenv():
            raise AssertionError("a dry run loads no .env")
    """,
    "inspect_ai/_util/registry.py": """
        BUILTIN = {"model_graded_qa", "model_graded_fact", "match", "includes"}
        def registry_lookup(kind, name):
            base = name.split("/")[-1]
            return object() if kind == "scorer" and base in BUILTIN else None
    """,
}

STUB_MLFLOW = {
    "mlflow/__init__.py": """
        import os
        __version__ = os.environ.get("STUB_VERSION", "3.16.1")
        def _never(*a, **k):
            raise AssertionError("never")
    """,
    "mlflow/genai/__init__.py": """
        def evaluate(*a, **k):
            raise AssertionError("evaluate must never be called")
    """,
    "mlflow/genai/scorers/__init__.py": """
        import os
        REGISTERED = set(filter(None, os.environ.get("STUB_REGISTERED", "").split(",")))
        def get_scorer(name, version=None, **k):
            if name not in REGISTERED:
                raise ValueError(f"no scorer {name}")
            return object()
        class Correctness: pass
        class Safety: pass
        class RelevanceToQuery: pass
        class Guidelines: pass
    """,
}


@pytest.fixture
def stubs(tmp_path_factory, monkeypatch):
    """Put stub packages on the worker's path; returns the log the stubs write."""
    folder = tmp_path_factory.mktemp("stubs")
    _write(folder, {**STUB_DEEPEVAL, **STUB_INSPECT, **STUB_MLFLOW})
    log = folder / "stub-log.jsonl"
    log.write_text("")
    monkeypatch.setenv("PYTHONPATH", str(folder))
    monkeypatch.setenv("STUB_LOG", str(log))

    def entries():
        return [json.loads(x) for x in log.read_text().splitlines() if x.strip()]

    return entries


@pytest.fixture
def terminal(monkeypatch):
    answers: list[str] = []
    monkeypatch.setattr(start, "_interactive", lambda: True)

    def fake_input(prompt=""):
        print(prompt)
        return answers.pop(0) if answers else ""

    monkeypatch.setattr(builtins, "input", fake_input)
    return answers


PY = AgainOptions(python=sys.executable)


# The user's Python ---------------------------------------------------------------------------

def test_the_users_python(tmp_path, monkeypatch):
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    assert user_python(tmp_path, None) == sys.executable
    venv = tmp_path / ".venv" / ("Scripts" if sys.platform == "win32" else "bin")
    venv.mkdir(parents=True)
    exe = venv / ("python.exe" if sys.platform == "win32" else "python")
    exe.write_text("")
    assert user_python(tmp_path, None) == str(exe)
    other = tmp_path / "other"
    (other / "bin").mkdir(parents=True)
    (other / "Scripts").mkdir(parents=True)
    for p in (other / "bin" / "python", other / "Scripts" / "python.exe"):
        p.write_text("")
    monkeypatch.setenv("VIRTUAL_ENV", str(other))
    assert user_python(tmp_path, None).startswith(str(other))
    assert user_python(tmp_path, "/given/python") == "/given/python"


# DeepEval ------------------------------------------------------------------------------------

def _metrics(name=None):
    case = json.loads(DEEPEVAL_FILE.read_text())["testCases"][0]
    return {m["name"]: m for m in case["metricsData"]}, case


def test_deepeval_metric_kinds():
    metrics, _ = _metrics()
    assert de.classify(metrics["Correctness [GEval]"]) == "geval"
    assert de.classify(metrics["Answer Relevancy"]) == "builtin"
    assert de.classify({"name": "Flow [DAG]"}) == "dag"
    assert de.classify({"name": "Chat [Conversational GEval]"}) == "conversational"
    assert de.classify({"name": "My Metric", "verboseLogs": "whatever"}) == "custom"


def test_geval_steps_criteria_and_rubric_from_the_saved_logs():
    metrics, _ = _metrics()
    g = de.parse_geval(metrics["Correctness [GEval]"]["verboseLogs"])
    assert g == {"criteria": "Is the actual output factually correct given the input?",
                 "steps": ["Check each claim in the actual output.",
                           "Penalise any claim that is false."],
                 "rubric": []}
    with_rubric = ('Criteria:\nC \n \nEvaluation Steps:\n[\n    "A",\n    "B"\n] \n \n'
                   'Rubric:\n0-4: bad\n5-10: good \n \nScore: 0.7')
    assert de.parse_geval(with_rubric)["rubric"] == [[[0, 4], "bad"], [[5, 10], "good"]]
    only_steps = 'Criteria:\nNone \n \nEvaluation Steps:\n[\n    "A"\n] \n \nRubric:\nNone'
    assert de.parse_geval(only_steps)["criteria"] is None


def test_steps_that_do_not_rebuild_the_saved_text_are_refused():
    ambiguous = ('Criteria:\nC \n \nEvaluation Steps:\n[\n    "A",\n    "B\nC"\n] \n \n'
                 'Rubric:\nNone')
    assert de.parse_geval(ambiguous) is None


def test_the_geval_job_from_the_fixture():
    metrics, _ = _metrics()
    job = de.metric_job(metrics["Correctness [GEval]"], ["input", "actual_output"])
    assert job == {
        "kind": "geval", "class": "GEval", "name": "Correctness", "suffix": True,
        "criteria": "Is the actual output factually correct given the input?",
        "steps": ["Check each claim in the actual output.", "Penalise any claim that is false."],
        "rubric": [], "fields": ["input", "actual_output"], "threshold": 0.5, "strict": False}
    built_in = de.metric_job(metrics["Answer Relevancy"], None)
    assert built_in["class"] == "AnswerRelevancyMetric" and built_in["kind"] == "builtin"


def test_the_deepeval_worker_dry_run_builds_and_checks_only(tmp_path, stubs, monkeypatch):
    monkeypatch.setenv("CONFIDENT_API_KEY", "x" * 20)
    monkeypatch.setenv("DEEPEVAL_RESULTS_FOLDER", str(tmp_path / "r"))
    metrics, _ = _metrics()
    job = {"mode": "dry", "metric": de.metric_job(metrics["Correctness [GEval]"],
                                                 ["input", "actual_output"])}
    out = again.run_worker("deepeval", sys.executable, job, tmp_path,
                           env=de.WORKER_ENV, drop=de.WORKER_DROP)
    assert out == {"ok": True, "version": "4.2.8", "evaluation_model": "gpt-4.1"}
    log = stubs()
    imported = next(e for e in log if e["kind"] == "import")
    assert imported == {"kind": "import", "telemetry": "1", "confident": False,
                        "results_folder": False}
    built = next(e for e in log if e["kind"] == "construct")
    kw = built["kwargs"]
    assert built["cls"] == "GEval"
    assert kw["name"] == "Correctness" and kw["_include_g_eval_suffix"] is True
    assert kw["evaluation_steps"] == ["Check each claim in the actual output.",
                                      "Penalise any claim that is false."]
    assert kw["evaluation_params"] == ["input", "actual_output"]
    assert kw["model"] is None and kw["async_mode"] is False and kw["threshold"] == 0.5
    assert not any(e["kind"] in ("evaluate", "measure") for e in log)
    assert not (tmp_path / "r").exists() and not (tmp_path / ".deepeval").exists()


def _missing(folder, monkeypatch, package):
    """A Python where `package` cannot be imported, whatever is installed."""
    _write(folder, {f"{package}/__init__.py":
                    f"raise ModuleNotFoundError(\"No module named {package}\", "
                    f"name={package!r})\n"})
    monkeypatch.setenv("PYTHONPATH", str(folder))


def test_the_deepeval_worker_says_when_deepeval_is_missing(tmp_path, monkeypatch):
    _missing(tmp_path / "nothing", monkeypatch, "deepeval")
    out = again.run_worker("deepeval", sys.executable,
                           {"mode": "dry", "metric": {"kind": "builtin",
                                                      "class": "AnswerRelevancyMetric"}},
                           tmp_path, env=de.WORKER_ENV, drop=de.WORKER_DROP)
    assert out["ok"] is False and out["missing"] == "deepeval"


def test_the_deepeval_plan(tmp_path, stubs, terminal):
    ws = _checked(tmp_path, deepeval_project)
    terminal += ["", "y"]  # the fields question takes its default; the version is confirmed
    p = make_plan(ws, PY, talk=start.Talk())
    assert (p.tool, p.status, p.answers, p.calls) == ("deepeval", "exact", 36, 72)
    lines = plan_lines(p)
    assert any("This is exactly your judge: DeepEval 4.2.8 measures your GEval metric" in x
               for x in lines)
    assert any("never deepeval.evaluate()" in x for x in lines)


def test_the_field_question_and_version_question(tmp_path, stubs, terminal, capsys):
    ws = _checked(tmp_path, deepeval_project)
    terminal += ["input, actual_output", "y"]
    make_plan(ws, PY, talk=start.Talk())
    out = capsys.readouterr().out
    # the saved cases have an expected output too: every field they have is listed
    assert "Your saved answers have: input, actual_output, expected_output." in out
    assert "Which fields does your judge read? [input, actual_output]" in out
    assert "Is DeepEval 4.2.8 the version you ran your eval with? [Y/n]" in out


def test_without_a_terminal_deepeval_is_a_close_copy(tmp_path, stubs):
    ws = _checked(tmp_path, deepeval_project)
    p = make_plan(ws, PY)
    assert p.status == "close"
    assert "which fields your judge reads was not confirmed" in p.why
    assert "the DeepEval version was not confirmed" in p.why
    p = make_plan(ws, AgainOptions(python=sys.executable, fields="input,actual_output"))
    assert "--fields" not in p.why


def test_a_different_model_stops(tmp_path, stubs, monkeypatch):
    ws = _checked(tmp_path, deepeval_project)
    monkeypatch.setenv("STUB_MODEL", "gpt-5.4")
    p = make_plan(ws, PY)
    assert p.status == "cant"
    assert p.why == ("your DeepEval settings pick gpt-5.4 now, but your saved verdicts came "
                     "from gpt-4.1")


def test_deepeval_not_installed(tmp_path, monkeypatch):
    ws = _checked(tmp_path, deepeval_project)
    _missing(tmp_path / "nothing", monkeypatch, "deepeval")
    p = make_plan(ws, PY)
    assert p.status == "cant"
    assert p.why == (f"DeepEval is not installed in {sys.executable}. Use --python to point at "
                     "the Python you run your evals with")


def test_the_menu_plan_runs_no_worker(tmp_path, stubs):
    ws = _checked(tmp_path, deepeval_project)
    p = make_plan(ws, PY, dry=False)
    assert p.calls == 72 and stubs() == []


def _deepeval_metric(root, change):
    path = root / ".deepeval" / ".latest_run_full.json"
    data = json.loads(path.read_text())
    for case in data["testCases"]:
        for m in case["metricsData"]:
            change(m)
    path.write_text(json.dumps(data))


def test_built_ins_are_always_a_close_copy(tmp_path, stubs, terminal):
    ws = _checked(tmp_path, deepeval_project)
    metrics, _ = _metrics()
    relevancy = metrics["Answer Relevancy"]

    def change(m):
        m.clear()
        m.update(relevancy)

    _deepeval_metric(tmp_path, change)
    data = ws.data()
    data["metric"] = "Answer Relevancy"  # as if the check had been of this metric
    ws.start.write_text(json.dumps(data))
    terminal += ["y"]
    p = make_plan(ws, PY, talk=start.Talk())
    assert p.status == "close" and "built-in" in p.why
    assert p.calls == 36 * 2 * 3


@pytest.mark.parametrize("name, words", [("Flow [DAG]", "DAG"),
                                         ("Chat [Conversational GEval]", "conversational"),
                                         ("Mine", "custom metric")])
def test_dag_conversational_and_custom_metrics_are_refused(name, words):
    md = {"name": name, "verboseLogs": "something", "evaluationModel": "gpt-4.1"}
    assert words in de.cant_reason(md)


def test_geval_and_built_ins_are_not_refused():
    metrics, _ = _metrics()
    assert de.cant_reason(metrics["Correctness [GEval]"]) is None
    assert de.cant_reason(metrics["Answer Relevancy"]) is None


def test_no_evaluation_model_is_refused():
    assert "do not say which model" in de.cant_reason({"name": "Correctness [GEval]",
                                                       "verboseLogs": "Criteria:\nx"})


# Inspect AI ----------------------------------------------------------------------------------

def _inspect_log(root, change):
    path = root / "logs" / "2026-10-02_support.json"
    data = json.loads(path.read_text())
    change(data)
    path.write_text(json.dumps(data))


def test_the_inspect_plan(tmp_path, stubs):
    ws = _checked(tmp_path, inspect_project)
    p = make_plan(ws, PY)
    assert (p.tool, p.status, p.answers, p.calls) == ("inspect", "exact", 36, 72)
    lines = plan_lines(p)
    assert any("Inspect re-scores a copy of your log with the same scorer and grader" in x
               for x in lines)
    assert any("your log is never changed" in x for x in lines)
    assert all(0 < inp and out == 200 for inp, out in p.tokens)


def test_another_inspect_version_is_a_close_copy_until_the_prompts_match(tmp_path, stubs,
                                                                         monkeypatch):
    ws = _checked(tmp_path, inspect_project)
    _inspect_log(tmp_path, lambda d: d["eval"].__setitem__("packages",
                                                           {"inspect_ai": "0.3.273"}))
    monkeypatch.setenv("STUB_VERSION", "0.3.300")
    p = make_plan(ws, PY)
    assert p.status == "close"
    assert ("your Python has Inspect 0.3.300 and your log was made with 0.3.273; if the "
            "grading prompts match after the run, it is exactly your judge") == p.why


def test_a_custom_scorer_is_refused(tmp_path, stubs):
    ws = _checked(tmp_path, inspect_project)
    p = make_plan(ws, PY)  # the scorer in start.json is model_graded_qa
    assert p.status == "exact"

    def rename(data):
        data["eval"]["scorers"][0]["name"] = "my_scorer"

    _inspect_log(tmp_path, rename)
    p = make_plan(ws, PY)
    assert p.status == "cant"


def test_inspect_classification():
    from judgekeeper.again import inspect as ins

    assert ins.cant_reason("match", {}, builtin=True) == (
        "your judge is a rule (match), not a model, so asking again gives the same verdicts")
    assert "custom scorer" in ins.cant_reason("my_scorer", {}, builtin=False)
    assert "template file" in ins.cant_reason("model_graded_qa",
                                              {"template": "prompts/grade.txt"}, builtin=True)
    assert "include_history" in ins.cant_reason("model_graded_qa",
                                                {"include_history": "my_history_fn"},
                                                builtin=True)
    assert ins.cant_reason("model_graded_qa", {"template": "Grade {answer}"},
                           builtin=True) is None


def test_no_grader_means_the_model_under_test_judges(tmp_path, stubs):
    ws = _checked(tmp_path, inspect_project)

    def no_grader(data):
        data["eval"]["model_roles"] = {}
        data["eval"]["model"] = "openai/gpt-4o"

    _inspect_log(tmp_path, no_grader)
    lines = plan_lines(make_plan(ws, PY))
    assert ("  Your judge is your model under test, openai/gpt-4o; asking again calls it as a "
            "judge and needs its key.") in lines


def test_the_inspect_cache_is_said(tmp_path, stubs):
    ws = _checked(tmp_path, inspect_project)

    def cached(data):
        data["eval"].setdefault("model_generate_config", {})["cache"] = True

    _inspect_log(tmp_path, cached)
    lines = plan_lines(make_plan(ws, PY))
    assert any("Inspect's cache is on in your log; judgekeeper turns it off" in x
               for x in lines)


def _openai_grader(root):
    def change(data):
        data["eval"]["model_roles"] = {"grader": {"model": "openai/gpt-4.1-mini", "config": {}}}

    _inspect_log(root, change)
    (root / ".env").write_text("OPENAI_API_KEY=x\n")


def test_inspect_loads_env_with_its_own_loader(tmp_path, stubs):
    ws = _checked(tmp_path, inspect_project)
    _openai_grader(tmp_path)
    lines = plan_lines(make_plan(ws, PY))
    assert ("  Your judge will use your OpenAI key (OPENAI_API_KEY, in .env in this folder; "
            "Inspect AI loads it).") in lines


def test_inspect_finds_the_nearest_env_upward_as_inspect_does(tmp_path, stubs):
    project = tmp_path / "project"
    project.mkdir()
    ws = _checked(project, inspect_project)
    _openai_grader(project)
    (project / ".env").unlink()
    (tmp_path / ".env").write_text("OPENAI_API_KEY=x\n")
    lines = plan_lines(make_plan(ws, PY))
    assert any("OPENAI_API_KEY, in ../.env" in x and "Inspect AI loads it" in x for x in lines)


def test_without_inspects_loader_the_key_must_be_in_the_shell(tmp_path, stubs, monkeypatch):
    ws = _checked(tmp_path, inspect_project)
    _openai_grader(tmp_path)
    monkeypatch.setenv("STUB_NO_DOTENV", "1")
    lines = plan_lines(make_plan(ws, PY))
    assert any(x.startswith("  Your judge needs OPENAI_API_KEY. It is in .env in this folder, "
                            "but Inspect AI does not load .env files when judgekeeper runs it: "
                            "set it in your shell (") and "OPENAI_API_KEY=" in x for x in lines)


def test_the_inspect_worker_reports_its_env_loader(tmp_path, stubs, monkeypatch):
    out = again.run_worker("inspect", sys.executable, {"mode": "dry",
                                                       "scorer": "model_graded_qa"}, tmp_path)
    assert out["dotenv"] is True
    monkeypatch.setenv("STUB_NO_DOTENV", "1")
    out = again.run_worker("inspect", sys.executable, {"mode": "dry",
                                                       "scorer": "model_graded_qa"}, tmp_path)
    assert out["ok"] is True and out["dotenv"] is False


# MLflow --------------------------------------------------------------------------------------

def _info(**kw):
    base = {"source_id": "openai:/gpt-4.1-mini", "scorer_name": None, "scorer_version": None,
            "name": "correctness", "guidelines": None, "instructions": None}
    return {**base, **kw}


@pytest.mark.parametrize("info, worker, status, words", [
    (_info(source_id="databricks"), {}, "cant",
     "Run judgekeeper inside your Databricks workspace"),
    (_info(source_id="endpoints:/my-judge"), {}, "cant",
     "Run judgekeeper inside your Databricks workspace"),
    (_info(scorer_name="tone", scorer_version="2"), {"registered": True}, "exact",
     "registered judge tone, version 2"),
    (_info(scorer_name="tone"), {"registered": True}, "close",
     "the latest registered version is used"),
    (_info(name="correctness"), {"builtin": True}, "exact", "MLflow's built-in"),
    (_info(name="guidelines", guidelines=1), {"builtin": True}, "exact", "one guideline"),
    (_info(name="guidelines", guidelines=3), {"builtin": True}, "cant", "several guidelines"),
    (_info(name="tone", instructions=True), {"version": "3.16.1"}, "close",
     "output type and temperature are not saved"),
    (_info(name="tone", instructions=True), {"version": "3.13.0"}, "cant", "before 3.14"),
    (_info(name="tone"), {}, "cant", "custom scorer"),
])
def test_mlflow_judges(info, worker, status, words):
    got_status, why = mf.classify(info, {"version": "3.16.1", **worker})
    assert got_status == status and words in why


def test_the_mlflow_worker_dry_run(tmp_path, stubs, monkeypatch):
    monkeypatch.setenv("STUB_REGISTERED", "tone")
    out = again.run_worker("mlflow", sys.executable,
                           {"mode": "dry", "name": "tone", "version": "2"}, tmp_path,
                           env=mf.WORKER_ENV)
    assert out == {"ok": True, "version": "3.16.1", "registered": True, "builtin": False}
    out = again.run_worker("mlflow", sys.executable, {"mode": "dry", "name": "safety"},
                           tmp_path, env=mf.WORKER_ENV)
    assert out["registered"] is False and out["builtin"] is True


def test_the_mlflow_plan(tmp_path, stubs, monkeypatch, terminal):
    ws = _checked(tmp_path, inspect_project)  # any check: the store is read through info
    data = ws.data()
    data["tool"] = "mlflow"
    ws.start.write_text(json.dumps(data))
    monkeypatch.setattr(mf, "assessment_info", lambda ws, metric: _info(name="safety"))
    monkeypatch.setenv("OPENAI_API_KEY", "x" * 30)
    terminal += ["y"]
    p = make_plan(ws, PY, talk=start.Talk())
    assert p.status == "exact" and p.model == "openai:/gpt-4.1-mini"
    lines = plan_lines(p)
    assert any("never mlflow.genai.evaluate()" in x for x in lines)
    assert ("  Your judge will use your OpenAI key (OPENAI_API_KEY, set in your shell)."
            in lines)


def test_a_trace_judge_is_up_to_thirty_calls(tmp_path, stubs, monkeypatch):
    ws = _checked(tmp_path, inspect_project)
    data = ws.data()
    data["tool"] = "mlflow"
    ws.start.write_text(json.dumps(data))
    monkeypatch.setattr(mf, "assessment_info",
                        lambda ws, metric: _info(name="tone", instructions=True, trace=True))
    p = make_plan(ws, PY)
    assert "  36 labeled answers × 2 times × 30 calls each = up to 2,160 judge calls." in \
        plan_lines(p)


def test_one_assessment_is_read_from_a_real_store(tmp_path):
    from tests.conftest import build_mlflow_store

    build_mlflow_store(tmp_path)
    ws = start_label.Workspace(tmp_path)
    info = mf.assessment_info(ws, "concise")
    assert info["source_id"] == "fake:/judge-model-1" and info["name"] == "concise"
    assert info["scorer_name"] and info["scorer_version"]
    plain = mf.assessment_info(ws, "correctness")
    assert plain["scorer_name"] is None and plain["instructions"] is False
    with pytest.raises(ValueError):
        mf.assessment_info(ws, "no-such-judge")


def test_the_fields_listed_are_the_ones_the_saved_cases_have():
    assert de.case_fields({"input": "q", "actualOutput": "a"}) == ["input", "actual_output"]
    assert de.case_fields({"input": "q", "actualOutput": "a", "expectedOutput": None,
                           "context": ["c"], "retrievalContext": ["r"]}) == [
        "input", "actual_output", "context", "retrieval_context"]


def test_a_field_the_saved_cases_lack_is_refused(tmp_path, stubs, terminal):
    ws = _checked(tmp_path, deepeval_project)
    terminal += ["input, retrieval_context"]
    p = make_plan(ws, PY, talk=start.Talk())
    assert p.status == "cant"
    assert "your saved answers have no retrieval_context" in p.why


def test_a_version_not_confirmed_is_a_close_copy(tmp_path, stubs, terminal):
    ws = _checked(tmp_path, deepeval_project)
    terminal += ["", "n"]  # the fields as pre-selected; the version not confirmed
    p = make_plan(ws, PY, talk=start.Talk())
    assert p.status == "close"
    assert p.why == "the DeepEval version was not confirmed"
