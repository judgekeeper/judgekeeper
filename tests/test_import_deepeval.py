"""`judgekeeper import deepeval`: a DeepEval results folder in, a report out.

Fixture (tests/fixtures/deepeval/, made by make_framework_fixtures.py): three
`test_run_<timestamp>.json` files in `results/`, one per run, as DeepEval writes them to a
`results_folder`. Eight test cases with DeepEval's positional default names test_case_0..7,
metrics "Correctness [GEval]" and "Answer Relevancy". DeepEval stores no human verdict, so
labels come from labels.csv: c0-c3 pass, c4-c7 fail (ids derived from input and output), plus
one labeled id that no run judged.

The Correctness judge passes:  run 1: c0-c4    run 2: c0-c2    run 3: c0-c4

  runs 1, 3: TP 4, FN 0, TN 3, FP 1 (c4) -> TPR 1, TNR 3/4,
             po 7/8, judge passes 5 of 8, pe (4*5 + 4*3)/64 = 1/2, kappa (7/8-1/2)/(1/2) = 3/4
  run 2:     TP 3, FN 1 (c3), TN 4, FP 0 -> TPR 3/4, TNR 1,
             po 7/8, judge passes 3, pe (4*3 + 4*5)/64 = 1/2, kappa 3/4
  means:     TPR (1 + 3/4 + 1)/3 = 11/12, TNR (3/4 + 1 + 3/4)/3 = 5/6, kappa 3/4
  noise:     c3 and c4 flip (pass, fail, pass) -> 2/8 = 1/4 of items flipped
"""

import hashlib
import json
import shutil

import pytest

from judgekeeper import import_results
from judgekeeper.cli import main
from judgekeeper.readers import read_deepeval
from judgekeeper.table import derive_id
from tests.conftest import FIXTURES

DIR = FIXTURES / "deepeval"
RESULTS = DIR / "results"
LABELS = DIR / "labels.csv"
PROMPT = ("Criteria:\nIs the actual output factually correct given the input? \n \n"
          "Evaluation Steps:\n[\n    \"Check each claim in the actual output.\",\n"
          "    \"Penalise any claim that is false.\"\n] \n \nRubric:\nNone")


def test_one_command_turns_the_fixture_into_a_report(tmp_path, capsys):
    out = tmp_path / "rep"
    assert main(["import", "deepeval", str(RESULTS), "--metric", "Correctness [GEval]",
                 "--labels", str(LABELS), "--out", str(out)]) == 0
    r = json.loads((out / "report.json").read_text())
    assert r["n_runs"] == 3
    assert r["anchors"]["n_items"] == 8
    assert [x["kappa"] for x in r["runs"]] == pytest.approx([0.75, 0.75, 0.75])
    assert [x["tpr"] for x in r["runs"]] == pytest.approx([1, 0.75, 1])
    assert [x["tnr"] for x in r["runs"]] == pytest.approx([0.75, 1, 0.75])
    h = r["headline"]
    assert h["tpr_mean"] == pytest.approx(11 / 12)
    assert h["tnr_mean"] == pytest.approx(5 / 6)
    assert h["kappa_mean"] == pytest.approx(0.75)
    assert r["noise_floor"]["items_flipped_fraction"] == pytest.approx(0.25)
    assert r["source"]["kind"] == "deepeval"
    assert r["source"]["n_labeled_unjudged"] == 1
    assert any("1 labeled item has no judge verdict" in n for n in r["notes"])
    # the three files, in timestamp order, are the three runs
    for n, stamp in enumerate(("100000", "110000", "120000"), 1):
        header = json.loads((out / "runs" / f"run-0{n}.jsonl").read_text().splitlines()[0])
        assert header["source"]["file"] == f"test_run_20260930_{stamp}.json"
    printed = capsys.readouterr()
    assert "positional" in printed.err


def test_three_files_become_three_runs_whatever_the_path_form(tmp_path):
    files = sorted(RESULTS.glob("test_run_*.json"))
    by_files = import_results("deepeval", files, metric="Correctness [GEval]", labels=LABELS,
                              out=tmp_path / "a")
    by_glob = import_results("deepeval", [str(RESULTS / "test_run_*.json")],
                             metric="Correctness [GEval]", labels=LABELS, out=tmp_path / "b")
    assert by_files["n_runs"] == by_glob["n_runs"] == 3
    assert by_files["headline"] == by_glob["headline"]


def test_positional_names_fall_back_to_derived_ids_with_a_warning(tmp_path):
    records = read_deepeval(RESULTS / "test_run_20260930_100000.json")
    assert records.ids_derived
    assert any("positional" in w for w in records.warnings)
    first = next(r for r in records if r.name == "Correctness [GEval]")
    assert first.target_id == derive_id({"input": "What is 0 + 0?", "output": "0 + 0 = 0."})
    r = import_results("deepeval", [RESULTS], metric="Correctness [GEval]", labels=LABELS,
                       out=tmp_path)
    assert r["source"]["ids_derived"] is True
    assert any("positional" in f["message"] for f in r["verdict"]["flags"])


def test_names_set_by_the_user_are_the_ids(tmp_path):
    src = RESULTS / "test_run_20260930_100000.json"
    data = json.loads(src.read_text())
    for case in data["testCases"]:
        case["name"] = "math-" + case["name"].rsplit("_", 1)[1]
    path = tmp_path / "test_run_1.json"
    path.write_text(json.dumps(data))
    records = read_deepeval(path)
    assert not records.ids_derived and not records.warnings
    assert {r.target_id for r in records} == {f"math-{i}" for i in range(8)}


def test_fingerprint_from_evaluation_model_and_verbose_logs(tmp_path):
    r = import_results("deepeval", [RESULTS], metric="Correctness [GEval]", labels=LABELS,
                       out=tmp_path)
    fp = r["fingerprint"]
    assert fp["model"] == "gpt-4.1"
    assert fp["provider"] == "openai"  # from the model id prefix; DeepEval stores no provider
    # Criteria, Evaluation Steps and Rubric; never the per-item Score line
    assert fp["prompt_hash"] == hashlib.sha256(PROMPT.encode()).hexdigest()
    assert fp["temperature"] is None
    assert r["source"]["threshold"] == 0.5
    assert "Criteria:" not in (tmp_path / "report.json").read_text()


def test_latest_run_full_is_one_run(tmp_path):
    hidden = tmp_path / ".deepeval"
    hidden.mkdir()
    shutil.copy(RESULTS / "test_run_20260930_110000.json", hidden / ".latest_run_full.json")
    r = import_results("deepeval", [hidden / ".latest_run_full.json"],
                       metric="Correctness [GEval]", labels=LABELS, out=tmp_path / "rep")
    assert r["n_runs"] == 1
    assert r["headline"]["kappa_mean"] == pytest.approx(0.75)
    assert r["noise_floor"]["status"] == "unknown: one run supplied"
    # a folder that holds only the rolling snapshot reads that
    r2 = import_results("deepeval", [tmp_path], metric="Correctness [GEval]", labels=LABELS,
                        out=tmp_path / "rep2")
    assert r2["n_runs"] == 1


def test_without_labels_it_says_where_labels_come_from(tmp_path, capsys):
    assert main(["import", "deepeval", str(RESULTS), "--metric", "Correctness [GEval]",
                 "--out", str(tmp_path)]) == 2
    assert "--labels" in capsys.readouterr().err


def test_pass_if_reads_the_score_instead_of_success(tmp_path):
    # scores are 0.9 (success) and 0.2 (failure): score>=0.95 fails everything
    r = import_results("deepeval", [RESULTS], metric="Correctness [GEval]", labels=LABELS,
                       pass_if="score>=0.95", out=tmp_path)
    assert r["headline"]["tpr_mean"] == 0
    assert r["headline"]["tnr_mean"] == 1
    assert r["normaliser"]["pass_if"] == "score>=0.95"


def test_conversational_test_cases_are_read_too(tmp_path):
    data = json.loads((RESULTS / "test_run_20260930_100000.json").read_text())
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
    path.write_text(json.dumps(data))
    [rec] = read_deepeval(path)
    assert (rec.target_id, rec.name, rec.label, rec.score) == (
        "support-chat-1", "Conversation Completeness", "fail", 0.3)
    assert rec.input == "A user asks for a refund."
    assert rec.explanation == "no refund offered"


def test_provider_only_when_the_model_id_leaves_no_doubt():
    from judgekeeper.readers.deepeval import provider_of

    assert provider_of("claude-haiku-4-5-20251001") == "anthropic"
    assert provider_of("gpt-4.1") == "openai"
    assert provider_of("gemini-2.5-flash") is None
    assert provider_of(None) is None


def test_labels_slice_column_gives_per_slice_numbers(tmp_path):
    rows = LABELS.read_text().splitlines()
    sliced = [rows[0] + ",slice"] + [f"{r},{'easy' if n % 2 else 'hard'}"
                                      for n, r in enumerate(rows[1:])]
    labels = tmp_path / "labels.csv"
    labels.write_text("\n".join(sliced) + "\n")
    r = import_results("deepeval", [RESULTS], metric="Correctness [GEval]", labels=labels,
                       out=tmp_path / "out")
    assert {s["slice"] for s in r["slices"]} == {"easy", "hard"}
    assert sum(s["n"] for s in r["slices"]) == r["anchors"]["n_items"]
    anchors = [json.loads(line) for line in (tmp_path / "out" / "anchors.jsonl").read_text().splitlines()]
    assert all(a["slice"] in {"easy", "hard"} for a in anchors)
