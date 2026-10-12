"""The DeepEval reader: DeepEval results files in, ScoreRecords out.

Fixture (tests/fixtures/deepeval/, made by make_framework_fixtures.py): three
`test_run_<timestamp>.json` files in `results/`, one per run, as DeepEval writes them to a
`results_folder`. Eight test cases with DeepEval's positional default names test_case_0..7,
metrics "Correctness [GEval]" and "Answer Relevancy". DeepEval stores no human verdict.

The Correctness judge passes:  run 1: c0-c4    run 2: c0-c2    run 3: c0-c4
"""

import hashlib
import json
import shutil

from judgekeeper.readers import read_deepeval
from judgekeeper.records import fingerprint_known
from judgekeeper.table import derive_id, make_fingerprint
from tests.conftest import FIXTURES

DIR = FIXTURES / "deepeval"
RESULTS = DIR / "results"
PROMPT = ("Criteria:\nIs the actual output factually correct given the input? \n \n"
          "Evaluation Steps:\n[\n    \"Check each claim in the actual output.\",\n"
          "    \"Penalise any claim that is false.\"\n] \n \nRubric:\nNone")


def test_each_file_is_one_run_of_both_metrics():
    runs = {}
    for f in sorted(RESULTS.glob("test_run_*.json")):
        records = read_deepeval(f)
        assert {r.name for r in records} == {"Correctness [GEval]", "Answer Relevancy"}
        assert all(r.annotator_kind == "LLM" for r in records)
        runs[f.name] = sorted(r.target_id for r in records if r.name == "Correctness [GEval]"
                              and r.label == "pass")
    assert len(runs) == 3
    # run 2 passes three cases, runs 1 and 3 five
    assert [len(v) for v in runs.values()] == [5, 3, 5]


def test_positional_names_fall_back_to_derived_ids_with_a_warning():
    records = read_deepeval(RESULTS / "test_run_20260930_100000.json")
    assert records.ids_derived
    assert any("positional" in w for w in records.warnings)
    first = next(r for r in records if r.name == "Correctness [GEval]")
    assert first.target_id == derive_id({"input": "What is 0 + 0?", "output": "0 + 0 = 0."})


def test_names_set_by_the_user_are_the_ids(tmp_path):
    src = RESULTS / "test_run_20260930_100000.json"
    data = json.loads(src.read_text(encoding="utf-8"))
    for case in data["testCases"]:
        case["name"] = "math-" + case["name"].rsplit("_", 1)[1]
    path = tmp_path / "test_run_1.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    records = read_deepeval(path)
    assert not records.ids_derived and not records.warnings
    assert {r.target_id for r in records} == {f"math-{i}" for i in range(8)}


def test_fingerprint_from_evaluation_model_and_verbose_logs():
    records = read_deepeval(RESULTS / "test_run_20260930_100000.json")
    rec = next(r for r in records if r.name == "Correctness [GEval]")
    fp = make_fingerprint(fingerprint_known(rec.evaluator))
    assert fp.model == "gpt-4.1"
    assert fp.provider == "openai"  # from the model id prefix; DeepEval stores no provider
    # Criteria, Evaluation Steps and Rubric; never the per-item Score line
    assert fp.prompt_hash == hashlib.sha256(PROMPT.encode()).hexdigest()
    assert fp.temperature is None
    assert records.per_metric["Correctness [GEval]"]["threshold"] == 0.5


def test_latest_run_full_is_read_like_a_test_run_file(tmp_path):
    hidden = tmp_path / ".deepeval"
    hidden.mkdir()
    shutil.copy(RESULTS / "test_run_20260930_110000.json", hidden / ".latest_run_full.json")
    latest = read_deepeval(hidden / ".latest_run_full.json")
    same = read_deepeval(RESULTS / "test_run_20260930_110000.json")
    # the same records; only a test_run file's name carries the time of the run
    assert [{**r.to_dict(), "created_at": None} for r in latest] == \
        [{**r.to_dict(), "created_at": None} for r in same]
    assert same[0].created_at == "2026-09-30T11:00:00" and latest[0].created_at is None


def test_conversational_test_cases_are_read_too(tmp_path):
    data = json.loads((RESULTS / "test_run_20260930_100000.json").read_text(encoding="utf-8"))
    data["testCases"] = []
    data["conversationalTestCases"] = [{
        "name": "support-chat-1", "success": True, "runDuration": 1.0,
        "scenario": "A user asks for a refund.",
        "turns": [{"role": "user", "content": "refund please"}],
        "metricsData": [{"name": "Conversation Completeness", "threshold": 0.5,
                         "success": False, "score": 0.3, "reason": "no refund offered",
                         "evaluationModel": "gpt-4.1"}],
    }]
    path = tmp_path / "test_run_1.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    [rec] = read_deepeval(path)
    assert (rec.target_id, rec.name, rec.label, rec.score) == (
        "support-chat-1", "Conversation Completeness", "fail", 0.3)
    assert rec.input == "A user asks for a refund."
    assert rec.explanation == "no refund offered"


def test_the_provider_from_the_model_name():
    from judgekeeper.readers.deepeval import provider_of

    assert provider_of("claude-haiku-4-5-20251001") == "anthropic"
    assert provider_of("claude-haiku-4-5 (Anthropic)") == "anthropic"
    assert provider_of("my-deployment (Azure)") == "azure"
    assert provider_of("gemini-2.5-flash (Gemini)") == "google"
    assert provider_of("llama3.3 (Ollama)") == "ollama"
    assert provider_of("grok-4.3 (Grok)") == "xai"
    assert provider_of("gpt-4.1") == "openai"
    # DeepEval builds an OpenAI model for any bare name
    assert provider_of("gemini-2.5-flash") == "openai"
    assert provider_of("my-model (Local Model)") is None
    assert provider_of(None) is None
