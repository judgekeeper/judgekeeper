"""Stub DeepEval, Inspect AI and MLflow packages for the workers judgekeeper runs in the user's
Python. No real tool is needed: the stubs are written into a temporary folder that is put on
the worker's PYTHONPATH. They record what the worker built and called (in the file named by
STUB_LOG), fail loudly on anything judgekeeper must never call (`deepeval.evaluate`,
`mlflow.genai.evaluate`), and answer judge calls from a plan (the JSON file named by
STUB_PLAN):

- "verdicts": {key: True or False}, the verdict each answer gets (default True); the key is
  the answer's input (DeepEval, Inspect AI) or its trace id (MLflow);
- "flips": [[key, time]], the times an answer gets the opposite verdict;
- "errors": [[key, time]], the times the judge call raises;
- "values": {key: value}, a raw value given instead of a verdict;
- "prompt_changed": [key], Inspect answers whose grading prompt comes back different;
- "extra": text put into every reason (a planted secret).
"""

from __future__ import annotations

import json
import textwrap

import pytest

COMMON = """
    import json, os

    def _log(kind, **data):
        with open(os.environ["STUB_LOG"], "a") as f:
            f.write(json.dumps({"kind": kind, **data}, default=str) + "\\n")

    def _plan():
        path = os.environ.get("STUB_PLAN")
        if not path or not os.path.exists(path):
            return {}
        with open(path) as f:
            return json.load(f)

    _COUNTS = {}

    def _next(key):
        n = _COUNTS.get(key, 0)
        _COUNTS[key] = n + 1
        return n

    def _answer(key, time):
        plan = _plan()
        if [key, time] in plan.get("errors", []):
            raise RuntimeError(f"rate limited {plan.get('extra', '')}")
        if key in plan.get("values", {}):
            return plan["values"][key]
        verdict = plan.get("verdicts", {}).get(key, True)
        return (not verdict) if [key, time] in plan.get("flips", []) else verdict
"""

STUB_DEEPEVAL = {
    "deepeval/__init__.py": COMMON + """
    __version__ = os.environ.get("STUB_VERSION", "4.2.8")
    _log("import", telemetry=os.environ.get("DEEPEVAL_TELEMETRY_OPT_OUT"),
         confident="CONFIDENT_API_KEY" in os.environ,
         results_folder="DEEPEVAL_RESULTS_FOLDER" in os.environ)

    def evaluate(*a, **k):
        _log("evaluate")
        raise AssertionError("evaluate must never be called")
    """,
    "deepeval/metrics/__init__.py": """
    import os
    from deepeval import _answer, _log, _next, _plan

    class _Metric:
        def __init__(self, **kwargs):
            _log("construct", cls=type(self).__name__, kwargs=kwargs)
            self.kwargs = kwargs
            model = kwargs.get("model")
            if model is None:  # DeepEval's own settings pick the model: STUB_MODEL
                self.evaluation_model = os.environ.get("STUB_MODEL", "gpt-4.1")
            elif isinstance(model, str):  # a name: OpenAI, unless a USE_* setting says other
                self.evaluation_model = model + os.environ.get("STUB_STRING_SUFFIX", "")
            else:
                self.evaluation_model = model.get_model_name()
            self.threshold = kwargs.get("threshold", 0.5)

        def measure(self, case, _show_indicator=True, **k):
            key = case.kwargs.get("input")
            time = _next(key)
            _log("measure", cls=type(self).__name__, input=key, time=time,
                 show_indicator=_show_indicator, case=case.kwargs,
                 steps=self.kwargs.get("evaluation_steps"))
            value = _answer(key, time)
            if isinstance(value, bool):
                self.success, self.score = value, 0.9 if value else 0.1
            else:
                self.success, self.score = None, value
            self.reason = f"again {time}{_plan().get('extra', '')}"
            self.evaluation_cost = 0.0005
            steps = self.kwargs.get("evaluation_steps")
            self.verbose_logs = (
                f"Criteria:\\n{self.kwargs.get('criteria')} \\n \\nEvaluation Steps:\\n"
                + "[\\n" + ",\\n".join(f'    "{s}"' for s in steps or []) + "\\n] \\n \\n"
                "Rubric:\\nNone \\n \\nScore: 0.9") if steps is not None else None
            return self.score

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
    "deepeval/models/__init__.py": """
    from deepeval import _log

    class _Model:
        LABEL = ""
        def __init__(self, model=None, **kwargs):
            _log("model", cls=type(self).__name__, model=model, kwargs=kwargs)
            self.name = model
        def get_model_name(self):
            return f"{self.name} ({self.LABEL})"
        def __repr__(self):
            return f"{type(self).__name__}({self.name!r})"

    class AnthropicModel(_Model): LABEL = "Anthropic"
    class GeminiModel(_Model): LABEL = "Gemini"
    class DeepSeekModel(_Model): LABEL = "Deepseek"
    class GrokModel(_Model): LABEL = "Grok"
    class KimiModel(_Model): LABEL = "KIMI"
    class AzureOpenAIModel(_Model): LABEL = "Azure"
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

    class ToolCall:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
        def __repr__(self):
            return f"ToolCall({self.kwargs!r})"

    class LLMTestCase:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
    """,
}

STUB_INSPECT = {
    "inspect_ai/__init__.py": COMMON + """
    import builtins, copy

    __version__ = os.environ.get("STUB_VERSION", "0.3.273")

    _open = builtins.open
    def _watch(file, mode="r", *a, **k):  # any write to an Inspect log is recorded
        if str(file).endswith((".json", ".eval")) and "logs" in str(file) and (
                set(mode) & set("wax+")):
            _log("log-written", file=str(file), mode=mode)
        return _open(file, mode, *a, **k)
    builtins.open = _watch

    class Message:
        def __init__(self, role, content):
            self.role, self.content = role, content

    def score(*a, **k):
        raise AssertionError("the worker uses score_async")

    async def score_async(log, scorers, metrics=None, epochs_reducer=None, model=None,
                          model_roles=None, action=None, display=None, copy=True,
                          samples=None):
        time = _next("score_async")
        _log("score_async", time=time, action=action, copy=copy,
             model=getattr(model, "name", model),
             model_cache=getattr(getattr(model, "config", None), "cache", "unset"),
             roles={k: [v.name, v.config.cache] for k, v in (model_roles or {}).items()},
             scorer=[s.name for s in scorers], options=[s.options for s in scorers])
        new = __import__("copy").deepcopy(log) if copy else log
        plan = _plan()
        for s in new.samples:
            value = _answer(s.input, time)
            if isinstance(value, bool):
                value = "C" if value else "I"
            old = s.scores.get(scorers[0].name)
            saved = ((old.metadata or {}).get("grading") or [None])[0] if old else None
            prompt = saved["content"] if isinstance(saved, dict) else f"Grade {s.input}"
            if s.input in plan.get("prompt_changed", []):
                prompt = "a different grading prompt"
            s.scores[f"{scorers[0].name}-1"] = Score(
                value=value, explanation=f"again {time}{plan.get('extra', '')}",
                metadata={"grading": [Message("user", prompt),
                                      Message("assistant", f"GRADE: {value}")]})
        return new

    class Score:
        def __init__(self, value, explanation=None, metadata=None):
            self.value, self.explanation, self.metadata = value, explanation, metadata
    """,
    "inspect_ai/_util/__init__.py": "",
    "inspect_ai/_util/dotenv.py": """
    import os
    from inspect_ai import _log
    if os.environ.get("STUB_NO_DOTENV"):
        raise ImportError("init_dotenv was renamed")
    def init_dotenv():
        _log("dotenv")
    """,
    "inspect_ai/_util/registry.py": """
    BUILTIN = {"model_graded_qa", "model_graded_fact", "match", "includes"}
    def registry_lookup(kind, name):
        base = name.split("/")[-1]
        return object() if kind == "scorer" and base in BUILTIN else None
    """,
    "inspect_ai/util/__init__.py": """
    from inspect_ai import _log
    from inspect_ai._util.registry import registry_lookup

    class Scorer:
        def __init__(self, name, options):
            self.name, self.options = name, options

    def registry_create(kind, name, **options):
        if not name.startswith("inspect_ai/") or registry_lookup(kind, name) is None:
            raise ValueError(f"{name} not found")
        shown = {k: (getattr(v, "name", v), getattr(getattr(v, "config", None), "cache", None))
                 if hasattr(v, "config") else v for k, v in options.items()}
        _log("registry_create", name=name, options=shown)
        return Scorer(name.split("/")[-1], shown)
    """,
    "inspect_ai/model/__init__.py": """
    from inspect_ai import _log

    class GenerateConfig:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)
        @property
        def cache(self):
            return self.__dict__.get("cache")
        def model_dump(self, exclude_none=False):
            return {k: v for k, v in self.__dict__.items() if v is not None or not exclude_none}

    class Model:
        def __init__(self, name, config, base_url, args):
            self.name, self.config, self.base_url, self.args = name, config, base_url, args

    def get_model(model=None, *, config=None, base_url=None, **args):
        _log("get_model", model=model, config=(config or GenerateConfig()).model_dump(),
             base_url=base_url, args=args)
        return Model(model, config or GenerateConfig(), base_url, args)
    """,
    "inspect_ai/log/__init__.py": """
    import json
    from inspect_ai import _log
    from inspect_ai.model import GenerateConfig

    class Obj:
        def __init__(self, **kw):
            self.__dict__.update(kw)

    def _score(d):
        return Obj(value=d.get("value"), explanation=d.get("explanation"),
                   metadata=d.get("metadata") or {})

    def read_eval_log(path):
        _log("read_eval_log", path=str(path))
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        e = d["eval"]
        roles = {k: Obj(model=v.get("model"), config=GenerateConfig(**(v.get("config") or {})),
                        base_url=v.get("base_url"), args=v.get("args") or {})
                 for k, v in (e.get("model_roles") or {}).items()}
        spec = Obj(model=e.get("model"), model_roles=roles or None,
                   scorers=[Obj(name=s["name"], options=s.get("options") or {})
                            for s in e.get("scorers") or []],
                   model_generate_config=GenerateConfig(**(e.get("model_generate_config")
                                                           or {})),
                   model_base_url=e.get("model_base_url"), model_args=e.get("model_args") or {},
                   packages=e.get("packages") or {})
        samples = [Obj(id=s["id"], epoch=s.get("epoch"), input=s["input"],
                       scores={k: _score(v) for k, v in (s.get("scores") or {}).items()})
                   for s in d.get("samples") or []]
        return Obj(eval=spec, samples=samples)
    """,
}

STUB_MLFLOW = {
    "mlflow/__init__.py": COMMON + """
    __version__ = os.environ.get("STUB_VERSION", "3.16.1")
    _log("import", telemetry=os.environ.get("MLFLOW_DISABLE_TELEMETRY"))

    def set_tracking_uri(uri):
        _log("set_tracking_uri", uri=uri)

    class _Assessment:
        def __init__(self, d):
            self.d = d
        def to_dictionary(self):
            return self.d

    class _Trace:
        def __init__(self, trace_id, d):
            self.trace_id = trace_id
            self.info = type("Info", (), {"assessments": [_Assessment(a) for a in
                                                          d.get("assessments", [])]})()

    class MlflowClient:
        def __init__(self, tracking_uri=None):
            _log("client", uri=tracking_uri)
        def get_trace(self, trace_id):
            _log("get_trace", trace=trace_id)
            return _Trace(trace_id, _plan().get("traces", {}).get(trace_id, {}))
        def __getattr__(self, name):  # anything else (log_*, set_*, delete_*): never
            _log("client-call", name=name)
            raise AssertionError(f"MlflowClient.{name} must not be called")
    """,
    "mlflow/genai/__init__.py": """
    from mlflow import _log
    def evaluate(*a, **k):
        _log("evaluate")
        raise AssertionError("evaluate must never be called")
    """,
    "mlflow/genai/judges/__init__.py": """
    from mlflow import _log
    from mlflow.genai.scorers import _Judge

    def make_judge(name, instructions, model=None, **k):
        _log("make_judge", name=name, instructions=instructions, model=model, other=k)
        return _Judge(name)
    """,
    "mlflow/genai/scorers/__init__.py": """
    import os
    from mlflow import _answer, _log, _next, _plan

    REGISTERED = set(filter(None, os.environ.get("STUB_REGISTERED", "").split(",")))

    class Feedback:
        def __init__(self, value, rationale, error=None):
            self.value, self.rationale, self.error = value, rationale, error

    class _Error:
        def __init__(self, message):
            self.error_code, self.error_message = "ERROR", message

    class _Judge:
        def __init__(self, name=None, **kwargs):
            self.name = name or type(self).__name__.lower()
            _log("construct", cls=type(self).__name__, kwargs=kwargs)
        def __call__(self, *, inputs=None, outputs=None, expectations=None, trace=None,
                     session=None):
            key = getattr(trace, "trace_id", None) or _plan().get("by_input", {}).get(
                str(inputs))
            time = _next(key)
            _log("judge", name=self.name, inputs=inputs, outputs=outputs,
                 expectations=expectations, trace=getattr(trace, "trace_id", None), time=time)
            try:
                value = _answer(key, time)
            except RuntimeError as e:
                return Feedback(None, None, _Error(str(e)))
            if isinstance(value, bool):
                value = "yes" if value else "no"
            return Feedback(value, f"again {time}{_plan().get('extra', '')}")

    def get_scorer(*, name, experiment_id=None, version=None):
        _log("get_scorer", name=name, experiment_id=experiment_id, version=version)
        if name not in REGISTERED:
            raise ValueError(f"no scorer {name}")
        return _Judge(name)

    class Correctness(_Judge): pass
    class Safety(_Judge): pass
    class Guidelines(_Judge): pass

    class RelevanceToQuery(_Judge):  # as in MLflow: no expectations, no trace
        def __call__(self, *, inputs=None, outputs=None):
            return super().__call__(inputs=inputs, outputs=outputs)
    """,
}


def write(folder, files: dict) -> None:
    for name, text in files.items():
        path = folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(text), encoding="utf-8")


@pytest.fixture
def stubs(tmp_path_factory, monkeypatch):
    """Put the stub packages on the worker's path; returns a function that reads the stubs'
    log. `stubs.plan(...)` writes the plan the stubs answer from."""
    folder = tmp_path_factory.mktemp("stubs")
    write(folder, {**STUB_DEEPEVAL, **STUB_INSPECT, **STUB_MLFLOW})
    log = folder / "stub-log.jsonl"
    log.write_text("")
    plan_path = folder / "stub-plan.json"
    monkeypatch.setenv("PYTHONPATH", str(folder))
    monkeypatch.setenv("STUB_LOG", str(log))
    monkeypatch.setenv("STUB_PLAN", str(plan_path))

    def entries(kind: str | None = None):
        rows = [json.loads(x) for x in log.read_text().splitlines() if x.strip()]
        return [r for r in rows if kind is None or r["kind"] == kind]

    def plan(**data):
        plan_path.write_text(json.dumps(data))

    entries.plan = plan
    return entries
