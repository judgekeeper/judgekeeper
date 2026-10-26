"""The Python workers read nothing from the project that could send a judge call elsewhere.

Each worker (DeepEval, Inspect AI, MLflow) runs from a new empty folder, never the project: the
tools read settings files from where they run (DeepEval's old `.deepeval/.deepeval`), and every
path a worker needs is in its job as a full path. litellm, which the tools import when it is
installed, loads no `.env` (LITELLM_MODE=PRODUCTION). DeepEval's model must be of the class its
saved name's provider uses. An Inspect log passes only known model settings, an MLflow judge's
stored model is the one the results name, and a new rule that goes into an Inspect template gets
the template checks.

No test calls a paid API: the workers run against the stub packages in tests/again_stubs.py, and
a local listener counts every request that would have gone elsewhere.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from judgekeeper import again, keys
from judgekeeper.again import AgainOptions, make_plan
from judgekeeper.again import inspect as ins
from judgekeeper.again import mlflow as mf
from judgekeeper.cli import main
from tests.start_projects import deepeval_project, inspect_project, split
from tests.test_again_tools import _checked, _info, _inspect_log, _traces

PY = AgainOptions(python=sys.executable)
WORKERS = Path(again.__file__).parent / "workers"


@pytest.fixture(autouse=True)
def no_keys(monkeypatch):
    for name in keys.all_names():
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("LITELLM_MODE", raising=False)


@pytest.fixture
def listener(monkeypatch):
    """A local HTTP server that keeps the path of every request it gets."""
    asked = []

    class Keep(BaseHTTPRequestHandler):
        def do_GET(self):
            asked.append(self.path)
            self.send_response(404)
            self.end_headers()

        do_HEAD = do_POST = do_PUT = do_GET

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Keep)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    for name in ("NO_PROXY", "no_proxy"):
        monkeypatch.setenv(name, "127.0.0.1")
    yield f"http://127.0.0.1:{server.server_address[1]}", asked
    server.shutdown()
    server.server_close()


def _worker(name: str):
    spec = importlib.util.spec_from_file_location(f"jk_{name}", WORKERS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Every worker runs from an empty folder, never the project ------------------------------------

@pytest.mark.parametrize("tool, job", [
    ("deepeval", {"mode": "dry", "metric": {"kind": "builtin", "class": "BiasMetric",
                                            "name": "Bias", "threshold": 0.5,
                                            "strict": False}}),
    ("inspect", {"mode": "dry", "scorer": "model_graded_qa"}),
    ("mlflow", {"mode": "dry", "name": "safety"}),
])
def test_a_worker_runs_outside_the_project_in_a_folder_removed_after(tmp_path, stubs, tool,
                                                                    job):
    project = tmp_path / "project"
    project.mkdir()
    again.run_worker(tool, sys.executable, job, project)
    (started, *_) = stubs("started")
    cwd = Path(started["cwd"]).resolve()
    assert not cwd.is_relative_to(project.resolve())
    assert not cwd.exists()  # removed afterwards
    assert started["litellm_mode"] == "PRODUCTION"


def test_deepeval_writes_its_cache_in_the_workers_own_folder(tmp_path, stubs):
    again.run_worker("deepeval", sys.executable, {"mode": "dry", "metric": {
        "kind": "builtin", "class": "BiasMetric", "name": "Bias", "threshold": 0.5,
        "strict": False}}, tmp_path)
    (started, *_) = stubs("started")
    assert Path(started["cache_folder"]).resolve().is_relative_to(
        Path(started["cwd"]).resolve())


def test_the_persons_own_litellm_mode_is_kept(tmp_path, stubs, monkeypatch):
    monkeypatch.setenv("LITELLM_MODE", "DEV")
    again.run_worker("inspect", sys.executable, {"mode": "dry", "scorer": "model_graded_qa"},
                     tmp_path)
    assert stubs("started")[0]["litellm_mode"] == "DEV"


LITELLM_LIKE = """
import os
from pathlib import Path

def _find_dotenv():  # python-dotenv's find_dotenv from a script: up from this file's folder
    for folder in Path(__file__).resolve().parents:
        if (folder / ".env").is_file():
            return folder / ".env"

if os.getenv("LITELLM_MODE", "DEV") == "DEV":
    found = _find_dotenv()
    for line in (found.read_text().splitlines() if found else []):
        name, _, value = line.partition("=")
        os.environ.setdefault(name.strip(), value.strip())
"""


def test_litellm_in_the_project_venv_loads_no_env_file(tmp_path, stubs, monkeypatch):
    ws = _checked(tmp_path, deepeval_project)
    (tmp_path / ".env").write_text("OPENAI_BASE_URL=http://127.0.0.1:9/v1\n", encoding="utf-8")
    site = tmp_path / ".venv" / "lib" / "site-packages"
    (site / "litellm").mkdir(parents=True)
    (site / "litellm" / "__init__.py").write_text(LITELLM_LIKE, encoding="utf-8")
    import os

    stub_folder = Path(os.environ["STUB_LOG"]).parent
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join([str(stub_folder), str(site)]))
    monkeypatch.setenv("OPENAI_API_KEY", "x" * 30)
    from tests.test_again_run import ask_again

    ask_again(ws, "--python", sys.executable, "--fields", "input,actual_output", "--times", "1")
    calls = stubs("call_env")
    assert calls and all(c["base_url"] is None for c in calls), calls


def test_an_inspect_template_file_in_the_project_is_given_by_its_full_path(tmp_path, stubs):
    ws = _checked(tmp_path, inspect_project)
    (tmp_path / "prompts").mkdir()
    (tmp_path / "prompts" / "grade.txt").write_text("Grade {answer}", encoding="utf-8")
    _inspect_log(tmp_path, lambda d: d["eval"]["scorers"][0]["options"].update(
        template="prompts/grade.txt"))
    log = tmp_path / "logs" / "2026-10-02_support.json"
    sample = json.loads(log.read_text(encoding="utf-8"))["samples"][0]
    plan = make_plan(ws, PY)
    assert plan.status != "cant", plan.why
    assert Path(plan.job["template"]) == (tmp_path / "prompts" / "grade.txt").resolve()
    assert Path(plan.job["log"]).is_absolute()
    again.run_worker("inspect", sys.executable, {
        "mode": "run", **plan.job, "times": 1,
        "answers": [{"id": "a", "sample": sample["id"], "epoch": sample.get("epoch")}]},
        tmp_path)
    (created, *_) = stubs("registry_create")
    assert Path(created["options"]["template"]) == (tmp_path / "prompts" / "grade.txt").resolve()


def test_an_mlflow_folder_store_is_given_by_its_full_path(tmp_path, monkeypatch):
    from judgekeeper import start_label
    from tests.conftest import build_mlflow_folder_store

    build_mlflow_folder_store(tmp_path / "project" / "mlruns")
    monkeypatch.chdir(tmp_path)
    info = mf.assessment_info(start_label.Workspace(Path("project")), "helpful")
    assert Path(info["uri"]).is_absolute() and len(info["traces"]) == 4


# DeepEval's old settings file, and the class of its model -------------------------------------

def _keyfile(root: Path, settings: dict) -> None:
    (root / ".deepeval").mkdir(exist_ok=True)
    (root / ".deepeval" / ".deepeval").write_text(json.dumps(settings), encoding="utf-8")


def test_deepevals_old_settings_file_is_not_read(tmp_path, stubs, listener, monkeypatch):
    # The results name the local model the file sets up, so only the file's server is wrong
    address, asked = listener
    ws = _checked(tmp_path, deepeval_project, model="stubmodel (Local Model)")
    _keyfile(tmp_path, {"USE_LOCAL_MODEL": "YES", "LOCAL_MODEL_NAME": "stubmodel",
                        "LOCAL_MODEL_BASE_URL": f"{address}/v1", "LOCAL_MODEL_FORMAT": "json"})
    monkeypatch.setenv("OPENAI_API_KEY", "x" * 30)
    from tests.test_again_run import ask_again

    ask_again(ws, "--python", sys.executable, "--fields", "input,actual_output", "--times", "1")
    assert asked == []
    assert stubs("keyfile") == [] and stubs("import")


BEDROCK = {"USE_AWS_BEDROCK_MODEL": "YES", "AWS_BEDROCK_REGION": "us-east-1",
           "AWS_BEDROCK_MODEL_NAME": "gpt-4.1"}


def test_a_bedrock_setting_in_the_old_settings_file_is_not_read(tmp_path, stubs, monkeypatch):
    ws = _checked(tmp_path, deepeval_project)
    _keyfile(tmp_path, BEDROCK)
    monkeypatch.setenv("OPENAI_API_KEY", "x" * 30)
    p = make_plan(ws, AgainOptions(python=sys.executable, fields="input,actual_output"))
    assert stubs("keyfile") == []
    assert p.status != "cant", p.why  # DeepEval builds its OpenAI model, as the results name


def test_a_bedrock_setting_read_anyway_is_not_asked(tmp_path, stubs, monkeypatch):
    # A DeepEval that read the file whatever is set builds a Bedrock model, which reports the
    # bare name the results hold: its class gives it away
    ws = _checked(tmp_path, deepeval_project)
    _keyfile(tmp_path, BEDROCK)
    monkeypatch.setenv("STUB_KEYFILE", str(tmp_path / ".deepeval" / ".deepeval"))
    monkeypatch.setenv("OPENAI_API_KEY", "x" * 30)
    p = make_plan(ws, AgainOptions(python=sys.executable, fields="input,actual_output"))
    assert stubs("keyfile")
    assert p.status == "cant" and "AmazonBedrockModel" in p.why, p.why
    assert stubs("measure") == []


@pytest.mark.parametrize("setting, cls", [("USE_AWS_BEDROCK_MODEL", "AmazonBedrockModel"),
                                          (None, "LiteLLMModel"), (None, "PortkeyModel"),
                                          (None, "AzureOpenAIModel")])
def test_a_model_of_another_providers_class_is_not_asked(tmp_path, stubs, monkeypatch, setting,
                                                        cls):
    ws = _checked(tmp_path, deepeval_project)  # the results name gpt-4.1, an OpenAI name
    monkeypatch.setenv("OPENAI_API_KEY", "x" * 30)
    if setting:
        monkeypatch.setenv(setting, "YES")
    else:
        monkeypatch.setenv("STUB_MODEL_CLASS", cls)
    p = make_plan(ws, AgainOptions(python=sys.executable, fields="input,actual_output"))
    assert p.status == "cant" and cls in p.why, p.why
    assert stubs("measure") == []


def test_the_dry_worker_names_the_class_of_deepevals_model(tmp_path, stubs):
    out = again.run_worker("deepeval", sys.executable, {"mode": "dry", "metric": {
        "kind": "builtin", "class": "BiasMetric", "name": "Bias", "threshold": 0.5,
        "strict": False}}, tmp_path)
    assert out["model_class"] == "GPTModel"


@pytest.mark.parametrize("cls", ["GPTModel", "OpenAIModel"])  # OpenAIModel: DeepEval 4.2.9+
def test_an_openai_model_still_is_asked(tmp_path, stubs, monkeypatch, cls):
    monkeypatch.setenv("STUB_MODEL_CLASS", cls)
    ws = _checked(tmp_path, deepeval_project)
    monkeypatch.setenv("OPENAI_API_KEY", "x" * 30)
    p = make_plan(ws, AgainOptions(python=sys.executable, fields="input,actual_output"))
    assert p.status != "cant", p.why


# An Inspect log's model settings ---------------------------------------------------------------

GRADER = {"model": "openai/gpt-4.1-mini"}


@pytest.mark.parametrize("config, field", [
    ({"extra_body": {"model": "o1-pro", "n": 8}}, "extra_body"),
    ({"num_choices": 4}, "num_choices"),
    ({"fallback_models": ["openai/o1-pro"]}, "fallback_models"),
    ({"extra_headers": {"OpenAI-Project": "p"}}, "extra_headers"),
    ({"logprobs": True}, "logprobs"),
    ({"max_tokens": 100000}, "max_tokens"),
])
@pytest.mark.parametrize("where", ["grader role", "other role", "scorer model",
                                   "model under test"])
def test_an_inspect_model_setting_that_is_not_known_safe_is_not_asked(tmp_path, stubs, config,
                                                                      field, where):
    ws = _checked(tmp_path, inspect_project)

    def change(d):
        e = d["eval"]
        if where == "grader role":
            e["model_roles"] = {"grader": {**GRADER, "config": config}}
        elif where == "other role":
            e["model_roles"]["critic"] = {**GRADER, "config": config}
        elif where == "scorer model":
            e["model_roles"] = {}
            e["scorers"][0]["options"]["model"] = {**GRADER, "config": config}
        else:
            e["model_roles"] = {}
            e["model_generate_config"] = config
    _inspect_log(tmp_path, change)
    p = make_plan(ws, PY)
    assert p.status == "cant" and field in p.why, p.why
    assert stubs("get_model") == [] and stubs("score_async") == []


def test_known_safe_inspect_settings_are_still_asked(tmp_path, stubs):
    ws = _checked(tmp_path, inspect_project)
    _inspect_log(tmp_path, lambda d: d["eval"].update(model_roles={"grader": {**GRADER, "config": {
        "temperature": 0, "top_p": 1, "max_tokens": 32000, "seed": 1, "stop_seqs": ["x"],
        "system_message": "Be fair.", "reasoning_effort": "low", "max_retries": 2,
        "timeout": 60, "cache": True}}}))
    p = make_plan(ws, PY)
    assert p.status != "cant", p.why


def test_the_inspect_worker_refuses_a_setting_that_is_not_known_safe():
    worker = _worker("inspect_worker")

    class Config(dict):
        def __init__(self, **kw):
            super().__init__(**kw)

    made = []
    worker.uncached({"model": "openai/x", "config": {"temperature": 0}}, Config,
                    lambda name, config: made.append(config))
    assert made == [{"temperature": 0, "cache": False}]
    with pytest.raises(ValueError, match="extra_body"):
        worker.uncached({"model": "openai/x", "config": {"extra_body": {"n": 8}}}, Config,
                        lambda name, config: made.append(config))
    with pytest.raises(ValueError, match="max_tokens"):
        worker.uncached({"model": "openai/x", "config": {"max_tokens": 100000}}, Config,
                        lambda name, config: made.append(config))
    assert len(made) == 1


# A registered MLflow judge's stored model -----------------------------------------------------

def _registered(ws, monkeypatch, stubs, stored, source="openai:/gpt-4.1-nano"):
    data = ws.data()
    data["tool"] = "mlflow"
    ws.start.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(mf, "assessment_info", lambda ws, metric: _info(
        name="mine", scorer_name="mine", scorer_version="1", experiment="1",
        source_id=source, traces=_traces(ws)))
    monkeypatch.setenv("STUB_REGISTERED", "mine")
    monkeypatch.setenv("OPENAI_API_KEY", "x" * 30)
    stubs.plan(stored={"mine": stored})
    return make_plan(ws, PY)


def test_a_registered_judge_whose_stored_model_differs_is_not_asked(tmp_path, stubs,
                                                                  monkeypatch):
    ws = _checked(tmp_path, inspect_project)
    p = _registered(ws, monkeypatch, stubs, {"name": "mine", "builtin_scorer_pydantic_data": {
        "model": "openai:/o1-pro"}})
    assert p.status == "cant" and "openai:/o1-pro" in p.why and "gpt-4.1-nano" in p.why, p.why
    assert stubs("judge") == []


def test_a_registered_judge_with_its_own_model_is_asked(tmp_path, stubs, monkeypatch):
    ws = _checked(tmp_path, inspect_project)
    p = _registered(ws, monkeypatch, stubs, {"name": "mine", "builtin_scorer_pydantic_data": {
        "model": "openai:/gpt-4.1-nano"}})
    assert p.status != "cant", p.why


@pytest.mark.parametrize("empty", [None, {}])
def test_a_registered_judge_with_empty_extra_headers_is_asked(tmp_path, stubs, monkeypatch,
                                                              empty):
    # MLflow 3.17 stores "extra_headers": null in every built-in judge
    ws = _checked(tmp_path, inspect_project)
    p = _registered(ws, monkeypatch, stubs, {"name": "mine", "builtin_scorer_pydantic_data": {
        "model": "openai:/gpt-4.1-nano", "inference_params": None, "extra_headers": empty}})
    assert p.status != "cant", p.why


def test_a_registered_judge_with_stored_extra_headers_is_not_asked(tmp_path, stubs,
                                                                  monkeypatch):
    ws = _checked(tmp_path, inspect_project)
    p = _registered(ws, monkeypatch, stubs, {"name": "mine", "instructions_judge_pydantic_data": {
        "instructions": "Is {{ outputs }} kind?", "model": "openai:/gpt-4.1-nano",
        "extra_headers": {"OpenAI-Project": "p"}}})
    assert p.status == "cant" and "extra_headers" in p.why, p.why
    assert stubs("get_scorer") == []


# A new rule that goes into an Inspect template --------------------------------------------------

TEMPLATE = "Question: {question}\nAnswer: {answer}\nCriterion: {criterion}\nGRADE: C or I"


def _template_judge(root: Path):
    inspect_project(root, split(20, 16))
    _inspect_log(root, lambda d: d["eval"]["scorers"][0].update(
        options={"template": TEMPLATE, "model_role": "grader"}))


@pytest.mark.parametrize("rule", ["http://127.0.0.1:{port}/t?q={question}&a={answer}&c={criterion}",
                                  "~/x{question}{answer}{criterion}",
                                  "/etc/{question}{answer}{criterion}"])
def test_a_rule_that_inspect_would_read_or_fetch_is_not_asked(tmp_path, stubs, listener, rule):
    address, asked = listener
    rule = rule.replace("{port}", address.rsplit(":", 1)[1])
    ws = _checked(tmp_path, lambda root, verdicts: _template_judge(root))
    assert ws.data().get("rule_field") == "template"
    p = make_plan(ws, AgainOptions(python=sys.executable, rule=rule))
    assert p.status == "cant", p.why
    assert stubs("score_async") == [] and asked == []


def test_fix_refuses_a_rule_inspect_would_fetch(tmp_path, stubs, listener, monkeypatch,
                                               capsys):
    address, asked = listener
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x" * 30)
    monkeypatch.setenv("VIRTUAL_ENV", str(Path(sys.executable).parent.parent))
    ws = _checked(tmp_path, lambda root, verdicts: _template_judge(root))
    assert main(["fix"]) in (0, 3)
    (ws.dir / "fix" / "rule.txt").write_text(
        f"{address}/t?q={{question}}&a={{answer}}&c={{criterion}}&g=GRADE:", encoding="utf-8")
    capsys.readouterr()
    code = main(["fix", "--yes"])
    out = " ".join(capsys.readouterr().out.split())
    assert code == 3, out
    assert "online address" in out, out
    assert stubs("score_async") == [] and asked == []


def test_a_plain_rule_into_the_template_is_still_asked(tmp_path, stubs):
    ws = _checked(tmp_path, lambda root, verdicts: _template_judge(root))
    p = make_plan(ws, AgainOptions(python=sys.executable, rule=TEMPLATE.replace(
        "Question", "The question")))
    assert p.status != "cant", p.why


def test_the_template_checks_take_a_rule_too():
    assert ins.template_problem("http://x/{question}", Path()) is not None
    assert ins.template_problem("~/x{question}", Path()) is not None
    assert ins.template_problem("Grade {question} {answer}", Path()) is None
