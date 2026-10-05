"""Bring your own judge: a Python callable or any program, run N times over the anchor set."""

import asyncio
import json
import sys

import pytest

from judgekeeper import check_judge
from judgekeeper.anchors import freeze
from judgekeeper.cli import main
from judgekeeper.custom import CallLimitError
from judgekeeper.normalise import NormaliseError
from tests.conftest import FIXTURES

EXEC = FIXTURES / "exec"


def _single(tmp_path, n=10):
    """Items s0..s{n-1}; even ones have a good output and human label pass."""
    path = tmp_path / "anchors.jsonl"
    items = [{"id": f"s{i}", "input": f"q{i}", "output": ("good " if i % 2 == 0 else "bad ")
              + str(i), "human_label": "pass" if i % 2 == 0 else "fail", "notes": "secret"}
             for i in range(n)]
    path.write_text("".join(json.dumps(i) + "\n" for i in items))
    freeze(path)
    return path


def _pairwise(tmp_path):
    path = tmp_path / "pairs.jsonl"
    items = [{"id": f"p{i}", "input": f"q{i}",
              "output_a": "good" if i % 2 == 0 else "meh",
              "output_b": "meh" if i % 2 == 0 else "good",
              "human_label": "A" if i % 2 == 0 else "B"} for i in range(6)]
    path.write_text("".join(json.dumps(i) + "\n" for i in items))
    freeze(path)
    return path


def _good(item):
    return "good" in item["output"]


SHAPES = {
    "bool": lambda item: _good(item),
    "str": lambda item: "PASS: ok" if _good(item) else "FAIL: no",
    "float": lambda item: 0.9 if _good(item) else 0.1,
    "tuple": lambda item: (_good(item), "because"),
    "dict": lambda item: {"passed": _good(item), "explanation": "because"},
}


@pytest.mark.parametrize("shape", SHAPES)
def test_sync_judge_each_shape(tmp_path, shape):
    pass_if = "score>=0.5" if shape == "float" else None
    r = check_judge(SHAPES[shape], _single(tmp_path), runs=2, pass_if=pass_if,
                    out=tmp_path / "out")
    assert r["n_runs"] == 2
    assert r["headline"]["tpr_mean"] == 1.0 and r["headline"]["tnr_mean"] == 1.0
    assert r["headline"]["kappa_mean"] == 1.0
    assert r["source"]["kind"] == "callable"
    assert r["normaliser"]["pass_if"] == pass_if
    assert (tmp_path / "out" / "report.html").is_file()


def test_async_judge(tmp_path):
    async def judge(item):
        await asyncio.sleep(0)
        return {"verdict": "pass" if _good(item) else "fail", "reason": "async"}

    r = check_judge(judge, _single(tmp_path), runs=3, out=tmp_path / "out")
    assert r["headline"]["kappa_mean"] == 1.0
    assert r["n_runs"] == 3


def test_async_judge_inside_a_running_loop(tmp_path):
    """Notebooks run an event loop already; check_judge must still work there."""
    async def judge(item):
        return _good(item)

    async def main_coro():
        return check_judge(judge, _single(tmp_path), runs=1, out=tmp_path / "out")

    assert asyncio.run(main_coro())["headline"]["kappa_mean"] == 1.0


def test_judge_that_raises_is_error_not_fail(tmp_path):
    def judge(item):
        if item["id"] in ("s1", "s2"):
            raise RuntimeError("rate limited")
        return _good(item)

    r = check_judge(judge, _single(tmp_path), runs=3, out=tmp_path / "out")
    assert r["headline"]["kappa_mean"] == 1.0
    assert r["errors"]["n"] == 6 and r["errors"]["items"] == ["s1", "s2"]
    assert "judge_errors" in {f["code"] for f in r["verdict"]["flags"]}
    line = (tmp_path / "out" / "runs" / "run-01.jsonl").read_text().splitlines()[2]
    rec = json.loads(line)
    assert rec["verdict"] == "error" and "RuntimeError: rate limited" in rec["error"]


def test_judge_returning_none_is_error(tmp_path):
    r = check_judge(lambda item: None if item["id"] == "s0" else _good(item),
                    _single(tmp_path), runs=1, out=tmp_path / "out")
    assert r["errors"]["items"] == ["s0"]


def test_judge_never_sees_the_human_label(tmp_path):
    seen = []

    def judge(item):
        seen.append(item)
        return True

    check_judge(judge, _single(tmp_path), runs=1, out=tmp_path / "out")
    assert seen and all("human_label" not in i and "notes" not in i for i in seen)


def test_unmapped_judge_output_is_usage_error(tmp_path):
    with pytest.raises(NormaliseError, match="'good'"):
        check_judge(lambda item: "good", _single(tmp_path), runs=2, out=tmp_path / "out")
    r = check_judge(lambda item: "good" if _good(item) else "bad", _single(tmp_path), runs=1,
                    label_map="good=pass,bad=fail", out=tmp_path / "out2")
    assert r["headline"]["kappa_mean"] == 1.0


def test_pairwise_judge_runs_ab_and_ba(tmp_path):
    calls = []

    def judge(item):
        calls.append((item["id"], item["output_a"], item["output_b"]))
        return "A" if "good" in item["output_a"] else "B"

    r = check_judge(judge, _pairwise(tmp_path), runs=1, out=tmp_path / "out")
    assert len(calls) == 12
    assert ("p0", "good", "meh") in calls and ("p0", "meh", "good") in calls
    assert r["headline"]["kappa_mean"] == 1.0
    assert r["position_bias"]["inconsistency_rate"] == 0.0
    assert r["position_bias"]["kappa_ba_mean"] == 1.0


def test_pairwise_judge_with_first_slot_bias(tmp_path):
    r = check_judge(lambda item: "A", _pairwise(tmp_path), runs=1, out=tmp_path / "out")
    pb = r["position_bias"]
    assert pb["inconsistency_rate"] == 1.0 and pb["p_first"] == 1.0


def test_fingerprint_dict_and_unknowns(tmp_path):
    r = check_judge(_good, _single(tmp_path), runs=1, out=tmp_path / "out",
                    fingerprint={"model": "gpt-x", "prompt": "Is it good?", "temperature": 0})
    fp = r["fingerprint"]
    assert fp["model"] == "gpt-x" and fp["temperature"] == 0.0 and len(fp["prompt_hash"]) == 64
    assert fp["provider"] is None and fp["endpoint"] == "unknown"
    assert r["source"]["metric"].endswith("_good")


def test_call_limit(tmp_path):
    anchors = _single(tmp_path, n=501)
    with pytest.raises(CallLimitError, match="1,002"):
        check_judge(_good, anchors, runs=2, out=tmp_path / "out")
    assert check_judge(_good, anchors, runs=2, out=tmp_path / "out", yes=True)["n_runs"] == 2


def test_anchor_list_is_frozen_for_you(tmp_path):
    items = [{"id": "a", "input": "q", "output": "good", "human_label": "pass"},
             {"id": "b", "input": "q", "output": "bad", "human_label": "fail"}]
    r = check_judge(_good, items, runs=1, out=tmp_path / "out")
    assert r["anchors"]["n_items"] == 2
    assert (tmp_path / "out" / "anchors.manifest.json").is_file()


# --- CLI -------------------------------------------------------------------------------------


def _validate(anchors, runs, tmp_path):
    out = tmp_path / "rep"
    assert main(["validate", str(anchors), str(runs), "--out", str(out)]) == 0
    return json.loads((out / "report.json").read_text())


def test_cli_callable(tmp_path, capsys):
    anchors = _single(tmp_path)
    runs = tmp_path / "runs"
    assert main(["judge", str(anchors), "--callable", "tests.judges_for_tests:keyword_judge",
                 "--runs", "3", "--out", str(runs)]) == 0
    assert "30 judge calls" in capsys.readouterr().err
    header = json.loads((runs / "run-01.jsonl").read_text().splitlines()[0])
    assert header["source"] == {"kind": "callable", "file": None,
                                "metric": "tests.judges_for_tests:keyword_judge"}
    r = _validate(anchors, runs, tmp_path)
    assert r["headline"]["kappa_mean"] == 1.0 and r["n_runs"] == 3


def test_cli_callable_pairwise(tmp_path):
    anchors = _pairwise(tmp_path)
    runs = tmp_path / "runs"
    assert main(["judge", str(anchors), "--callable", "tests.judges_for_tests:pick_good",
                 "--runs", "1", "--out", str(runs)]) == 0
    assert _validate(anchors, runs, tmp_path)["position_bias"]["inconsistency_rate"] == 0.0


def test_cli_callable_not_found(tmp_path, capsys):
    assert main(["judge", str(_single(tmp_path)), "--callable", "tests.judges_for_tests:nope",
                 "--out", str(tmp_path / "runs")]) == 2
    assert "nope" in capsys.readouterr().err


def _exec(script: str) -> str:
    return f'"{sys.executable}" "{EXEC / script}"'


def test_cli_exec_bare_verdict(tmp_path):
    anchors = _single(tmp_path)
    runs = tmp_path / "runs"
    assert main(["judge", str(anchors), "--exec", _exec("bare.py"), "--runs", "2",
                 "--out", str(runs)]) == 0
    header = json.loads((runs / "run-01.jsonl").read_text().splitlines()[0])
    assert header["source"]["kind"] == "exec"
    assert _validate(anchors, runs, tmp_path)["headline"]["kappa_mean"] == 1.0


def test_cli_exec_json_verdict(tmp_path):
    anchors = _single(tmp_path)
    runs = tmp_path / "runs"
    assert main(["judge", str(anchors), "--exec", _exec("json_verdict.py"), "--runs", "1",
                 "--out", str(runs)]) == 0
    rec = json.loads((runs / "run-01.jsonl").read_text().splitlines()[1])
    assert rec["verdict"] == "pass" and rec["rationale"] == "saw s0"


def test_cli_exec_nonzero_exit_is_error(tmp_path):
    anchors = _single(tmp_path, n=12)
    runs = tmp_path / "runs"
    assert main(["judge", str(anchors), "--exec", _exec("fails_some.py"), "--runs", "1",
                 "--out", str(runs)]) == 0
    recs = {json.loads(x)["id"]: json.loads(x)
            for x in (runs / "run-01.jsonl").read_text().splitlines()[1:]}
    assert recs["s1"]["verdict"] == "error" and "exit 3" in recs["s1"]["error"]
    assert "judge crashed" in recs["s1"]["error"]
    assert recs["s2"]["verdict"] == "pass"
    r = _validate(anchors, runs, tmp_path)
    assert r["errors"]["items"] == ["s1", "s11"]
    assert r["headline"]["kappa_mean"] == 1.0


def test_cli_needs_yes_above_1000_calls(tmp_path, capsys):
    anchors = _single(tmp_path, n=501)
    args = ["judge", str(anchors), "--callable", "tests.judges_for_tests:keyword_judge",
            "--runs", "2", "--out", str(tmp_path / "runs")]
    assert main(args) == 2
    err = capsys.readouterr().err
    assert "1,002 judge calls" in err and "--yes" in err
    assert main([*args, "--yes"]) == 0


def test_cli_one_judge_source_only(tmp_path):
    anchors = _single(tmp_path)
    assert main(["judge", str(anchors), "--out", str(tmp_path / "r")]) == 2
    assert main(["judge", str(anchors), "--runner", "replay", "--callable", "a:b",
                 "--out", str(tmp_path / "r")]) == 2
