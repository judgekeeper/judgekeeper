"""Asking a DeepEval, Inspect AI or MLflow judge again, for real: the worker runs in the user's
Python in "run" mode and the judge grades the labeled answers; then the same numbers and files
as for promptfoo.

No test calls a paid API and none needs DeepEval, Inspect AI or MLflow: the workers run against
the stub packages in tests/again_stubs.py, which answer each judge call from a plan the test
writes and record everything the worker built and called.
"""

from __future__ import annotations

import builtins
import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from judgekeeper import again, keys, start, start_again, start_label
from judgekeeper.again import AgainOptions
from judgekeeper.again import deepeval as de
from judgekeeper.again import mlflow as mf
from judgekeeper.cli import main
from judgekeeper.judgments import read_run
from judgekeeper.start_label import StartSession, save_result
from tests import keyboard
from tests.conftest import FIXTURES
from tests.start_projects import (
    deepeval_data,
    deepeval_project,
    inspect_data,
    inspect_project,
    split,
)

SECRET = "sk-proj-THISisAfakeKEYthatMUSTbeSCRUBBED0123456789"
PY = ["--python", sys.executable]
FIELDS = ["--fields", "input,actual_output"]
DEEPEVAL_FILE = FIXTURES / "deepeval" / "results" / "test_run_20260930_120000.json"


def _quiet(line=""):
    pass


def _checked(root, maker, n_pass=20, n_fail=16):
    maker(root, split(n_pass, n_fail))
    ws = start_label.prepare(start.find_judge(root), say=_quiet)
    session = StartSession(ws)
    for q in ws.data()["queue"]:
        session.update({"id": q["id"], "label": q["group"]})
    save_result(ws, session, say=_quiet)
    return ws


def _saved(ws) -> dict:
    """{input: the judge's saved verdict is pass} for the labeled answers."""
    return {a["input"]: a["verdict"] == "pass" for a in again.labeled_answers(ws)}


def _inputs(ws) -> list[str]:
    return [a["input"] for a in again.labeled_answers(ws)]


@pytest.fixture(autouse=True)
def keyed(monkeypatch):
    for name in keys.all_names():
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", SECRET)
    monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET.replace("proj", "ant"))


@pytest.fixture
def terminal(monkeypatch):
    answers: list[str] = []
    monkeypatch.setattr(start, "_interactive", lambda: True)

    def fake_input(prompt=""):
        print(prompt)
        return answers.pop(0) if answers else keyboard.enter()

    monkeypatch.setattr(builtins, "input", fake_input)
    return answers


def ask(capsys, ws, *argv):
    code = main(["start", str(ws.root), "--ask-again", *PY, *map(str, argv)])
    out, _ = capsys.readouterr()
    return code, out


def _folder(ws) -> Path:
    (folder,) = (ws.dir / "again").iterdir()
    return folder


def _block(ws) -> dict:
    return json.loads(ws.result_json.read_text(encoding="utf-8"))["again"]


def _jobs(monkeypatch) -> list:
    """Keep each job the workers are given, with its time limit."""
    real, seen = again.run_process, []

    def spy(argv, cwd, env=None, timeout=None):
        seen.append((json.loads(Path(argv[2]).read_text(encoding="utf-8")), timeout))
        return real(argv, cwd, env, timeout)

    monkeypatch.setattr(again, "run_process", spy)
    return seen


# DeepEval ------------------------------------------------------------------------------------

@pytest.fixture
def deepeval_ws(tmp_path, stubs):
    ws = _checked(tmp_path, deepeval_project)
    stubs.plan(verdicts=_saved(ws))
    return ws


def test_deepeval_measures_each_answer_directly(deepeval_ws, stubs, capsys,
                                                monkeypatch):
    monkeypatch.setenv("CONFIDENT_API_KEY", "x" * 20)
    monkeypatch.setenv("DEEPEVAL_RESULTS_FOLDER", str(deepeval_ws.root / "r"))
    saved = (deepeval_ws.root / ".deepeval" / ".latest_run_full.json").read_bytes()
    code, out = ask(capsys, deepeval_ws, *FIELDS, "--allow-calls", 72)
    assert code == 0
    assert "Asking your judge 72 times through DeepEval. Ctrl-C stops it." in out
    assert "Asked twice more, your judge changed its mind on 0 of your 36 answers." in out
    measures = stubs("measure")
    assert len(measures) == 72 and all(m["show_indicator"] is False for m in measures)
    assert stubs("evaluate") == []
    assert all(e == {"kind": "import", "telemetry": "1", "confident": False,
                     "results_folder": False} for e in stubs("import"))
    built = [e["kwargs"] for e in stubs("construct")]
    assert built and all(kw["async_mode"] is False and kw["model"] is None
                         and kw["evaluation_params"] == ["input", "actual_output"]
                         for kw in built)
    first = measures[0]["case"]
    assert first["input"] in _inputs(deepeval_ws) and first["actual_output"].startswith("Answer")
    assert (deepeval_ws.root / ".deepeval" / ".latest_run_full.json").read_bytes() == saved
    assert not (deepeval_ws.root / "r").exists()
    names = sorted(p.name for p in _folder(deepeval_ws).iterdir())
    assert names == ["again.json", "deepeval.jsonl", "judge-again-1.jsonl", "judge-again-2.jsonl"]


def test_deepeval_lines_carry_the_full_fingerprint(deepeval_ws, capsys):
    ask(capsys, deepeval_ws, *FIELDS, "--allow-calls", 72)
    for path in sorted(_folder(deepeval_ws).glob("judge-again-*.jsonl")):
        header, records = read_run(path)
        assert header["source"]["kind"] == "deepeval" and len(records) == 36
        for rec in records.values():
            fp = rec["fingerprint"]
            assert fp["provider"] == "openai" and fp["model"] == "gpt-4.1"
            assert fp["prompt_hash"] == deepeval_ws.data()["fingerprint"]["prompt_hash"]
            assert fp["tool"] == "deepeval" and fp["tool_version"] == "4.2.8"
            assert fp["judge_copy"] == "close copy"
            assert fp["judge_copy_why"] == ["the DeepEval version was not confirmed"]
            assert fp["created_at"]


def test_deepeval_exactly_your_judge_after_both_questions(deepeval_ws, capsys, terminal):
    terminal += ["", "y", "y"]  # the fields as pre-selected; the version; go ahead
    code = main(["start", str(deepeval_ws.root), "--ask-again", *PY])
    out = capsys.readouterr().out
    assert code == 0 and "This is exactly your judge" in out and "Go ahead? [y/N]" in out
    assert _block(deepeval_ws)["status"] == "exact"
    assert "close copy" not in out.split("Go ahead?")[1]


def _own_steps(root, verdicts):
    data = deepeval_data(verdicts)
    md = data["testCases"][0]["metricsData"][0]
    md["verboseLogs"] = md["verboseLogs"].replace("Check each claim", "Check every claim")
    path = root / ".deepeval" / ".latest_run_full.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_a_saved_model_name_is_used_when_deepeval_picks_another(deepeval_ws, stubs, capsys,
                                                                  monkeypatch):
    monkeypatch.setenv("STUB_MODEL", "gpt-5.4")
    code, out = ask(capsys, deepeval_ws, *FIELDS, "--allow-calls", 72)
    assert code == 0 and "Asked twice more" in out
    assert ("Your DeepEval settings pick gpt-5.4; judgekeeper builds your judge with the model "
            "your results name, gpt-4.1, and DeepEval confirms it.") in out
    run_built = [e["kwargs"]["model"] for e in stubs("construct")][2:]  # after the two checks
    assert run_built and set(run_built) == {"gpt-4.1"}
    _, records = read_run(_folder(deepeval_ws) / "judge-again-1.jsonl")
    assert all(r["fingerprint"]["model"] == "gpt-4.1" for r in records.values())


def test_a_close_copy_says_why_once(deepeval_ws, capsys):
    _, out = ask(capsys, deepeval_ws, *FIELDS, "--allow-calls", 72)
    result = out.split("Ctrl-C stops it.")[1]
    assert result.count("the DeepEval version was not confirmed") == 1
    assert "This was a close copy of your judge: the DeepEval version was not confirmed." in result
    numbers = [x for x in result.splitlines()
               if x.startswith(("Asked", "When you said", "Its first"))]
    assert len(numbers) == 4 and all(x.endswith(" (close copy)") for x in numbers)


def test_each_answer_keeps_its_own_saved_steps(tmp_path, stubs, capsys):
    ws = _checked(tmp_path, _own_steps)
    stubs.plan(verdicts=_saved(ws))
    ask(capsys, ws, *FIELDS, "--allow-calls", 72)
    steps = {m["input"]: m["steps"][0] for m in stubs("measure")}
    assert steps["Question 0?"] == "Check every claim in the actual output."
    assert steps["Question 1?"] == "Check each claim in the actual output."


def test_deepeval_flips_and_matches(deepeval_ws, stubs, capsys):
    inputs = _inputs(deepeval_ws)
    stubs.plan(verdicts=_saved(deepeval_ws),
               flips=[[inputs[0], 1], [inputs[1], 1], [inputs[2], 0]])
    _, out = ask(capsys, deepeval_ws, *FIELDS, "--allow-calls", 72)
    assert "Asked twice more, your judge changed its mind on 3 of your 36 answers." in out
    assert "Its first new decision matched the saved one on 35 of 36 answers (97%)." in out
    block = _block(deepeval_ws)
    assert block["steadiness"]["changed"] == 3 and block["counted"] == 36


def test_deepeval_says_the_real_cost(deepeval_ws, capsys):
    _, out = ask(capsys, deepeval_ws, *FIELDS, "--allow-calls", 72)
    assert "DeepEval says these calls cost $0.04 in all." in out


def test_an_answer_with_an_error_is_not_counted(deepeval_ws, stubs, capsys):
    first = _inputs(deepeval_ws)[0]
    stubs.plan(verdicts=_saved(deepeval_ws), errors=[[first, 1]], extra=f" key {SECRET}")
    code, out = ask(capsys, deepeval_ws, *FIELDS, "--allow-calls", 72)
    assert code == 0
    assert "1 answer was not counted: the judge's tool gave an error for it." in out
    assert "The first error: RuntimeError: rate limited" in out
    assert _block(deepeval_ws)["counted"] == 35
    every = "".join(p.read_text(encoding="utf-8") for p in _folder(deepeval_ws).iterdir())
    every += deepeval_ws.result_json.read_text(
        encoding="utf-8") + deepeval_ws.result_html.read_text(encoding="utf-8") + out
    assert SECRET not in every and "[REDACTED]" in every


def test_when_every_call_fails_nothing_is_counted(deepeval_ws, stubs, capsys):
    stubs.plan(errors=[[i, t] for i in _inputs(deepeval_ws) for t in (0, 1)])
    code, out = ask(capsys, deepeval_ws, *FIELDS, "--allow-calls", 72)
    assert code == 1
    assert "DeepEval could not ask your judge: RuntimeError: rate limited" in out
    assert "again" not in json.loads(deepeval_ws.result_json.read_text(encoding="utf-8"))


def test_a_worker_that_does_not_finish(deepeval_ws, capsys, monkeypatch):
    real = again.run_process

    def crash(argv, cwd, env=None, timeout=None):
        if json.loads(Path(argv[2]).read_text(encoding="utf-8"))["mode"] == "run":
            return subprocess.CompletedProcess(argv, 1, "", "Traceback\nImportError: boom\n")
        return real(argv, cwd, env, timeout)

    monkeypatch.setattr(again, "run_process", crash)
    code, out = ask(capsys, deepeval_ws, *FIELDS, "--allow-calls", 72)
    assert code == 1 and "DeepEval did not finish: ImportError: boom" in out
    assert not (deepeval_ws.dir / "again").exists()


def test_ctrl_c_saves_nothing(deepeval_ws, capsys, monkeypatch):
    real = again.run_process

    def interrupted(argv, cwd, env=None, timeout=None):
        if json.loads(Path(argv[2]).read_text(encoding="utf-8"))["mode"] == "run":
            raise KeyboardInterrupt
        return real(argv, cwd, env, timeout)

    monkeypatch.setattr(again, "run_process", interrupted)
    code, out = ask(capsys, deepeval_ws, *FIELDS, "--allow-calls", 72)
    assert code == 130 and "Stopped. Nothing was saved." in out
    assert not (deepeval_ws.dir / "again").exists()


def test_the_run_has_no_time_limit_and_the_whole_job(deepeval_ws, capsys, monkeypatch):
    jobs = _jobs(monkeypatch)
    ask(capsys, deepeval_ws, *FIELDS, "--allow-calls", 72)
    (dry, dry_limit), (run, run_limit) = jobs
    assert dry["mode"] == "dry" and dry_limit == again.WORKER_TIMEOUT
    assert run["mode"] == "run" and run_limit is None and run["times"] == 2
    assert len(run["answers"]) == 36
    item = run["answers"][0]
    assert set(item) == {"id", "case", "metric"}
    assert set(item["case"]) == {"input", "actual_output", "expected_output"}


def test_no_spends_nothing_and_runs_no_judge(deepeval_ws, stubs, capsys, terminal):
    terminal += ["", "y", ""]  # fields; version; Enter at Go ahead? (No)
    code = main(["start", str(deepeval_ws.root), "--ask-again", *PY])
    out = capsys.readouterr().out
    assert code == 0 and out.rstrip().endswith("Your judge was not called; nothing was spent.")
    assert stubs("measure") == []


def test_a_missing_key_stops_before_the_question(deepeval_ws, stubs, capsys,
                                                 monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY")
    code, out = ask(capsys, deepeval_ws, *FIELDS, "--allow-calls", 72)
    assert code == 0 and "Your judge needs OPENAI_API_KEY" in out
    assert "Set the key, then run judgekeeper start " in out
    assert " --fields input,actual_output --ask-again again." in out  # your flags, repeated
    assert stubs("measure") == []


def _builtin(name="Answer Relevancy", old_direction=False):
    relevancy = next(m for m in json.loads(DEEPEVAL_FILE.read_text(
        encoding="utf-8"))["testCases"][0][
        "metricsData"] if m["name"] == "Answer Relevancy")

    def maker(root, verdicts):
        data = deepeval_data(verdicts)
        for case, v in zip(data["testCases"], verdicts, strict=True):
            md = copy.deepcopy(relevancy)
            high = 0.9 if v else 0.1
            md.update(name=name, success=v, threshold=0.5, evaluationModel="gpt-4.1",
                      score=1 - high if old_direction else high)
            case["metricsData"] = [md]
        path = root / ".deepeval" / ".latest_run_full.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(data), encoding="utf-8")
    return maker


def test_a_built_in_metric_is_asked_as_a_close_copy(tmp_path, stubs, capsys):
    ws = _checked(tmp_path, _builtin())
    stubs.plan(verdicts=_saved(ws))
    code, out = ask(capsys, ws, "--allow-calls", 216)
    assert code == 0 and "36 marked answers × 2 times × 3 calls each = 216 judge calls." in out
    assert {e["cls"] for e in stubs("construct")} == {"AnswerRelevancyMetric"}
    assert len(stubs("measure")) == 72  # one measure() makes the metric's 3 calls
    assert _block(ws)["status"] == "close"


def test_a_score_the_other_way_round_is_refused(tmp_path, stubs, capsys,
                                                monkeypatch):
    ws = _checked(tmp_path, _builtin("Hallucination", old_direction=True))
    code, out = ask(capsys, ws, "--allow-calls", 144)
    assert code == 0
    assert ("Your judge can't be asked again: your saved Hallucination scores come from a "
            "DeepEval before 4.2.0, which scores Hallucination the other way round from your "
            "DeepEval 4.2.8") in out
    assert stubs("measure") == []
    monkeypatch.setenv("STUB_VERSION", "4.1.8")
    stubs.plan(verdicts=_saved(ws))
    code, out = ask(capsys, ws, "--allow-calls", 144)
    assert code == 0 and "Asked twice more" in out


def test_a_new_style_score_runs_with_a_new_deepeval(tmp_path, stubs, capsys):
    ws = _checked(tmp_path, _builtin("Hallucination"))
    stubs.plan(verdicts=_saved(ws))
    code, out = ask(capsys, ws, "--allow-calls", 144)
    assert code == 0 and "Asked twice more" in out


@pytest.mark.parametrize("line, job, version, verdict", [
    ({"success": True, "score": 0.1}, {"kind": "geval", "threshold": 0.5}, "4.2.8", "pass"),
    ({"success": False, "score": 0.9}, {"kind": "geval", "threshold": 0.5}, "4.2.8", "fail"),
    ({"success": None, "score": 0.7}, {"kind": "geval", "threshold": 0.5}, "4.2.8", "pass"),
    ({"success": None, "score": 0.7}, {"kind": "builtin", "class": "HallucinationMetric",
                                       "threshold": 0.5}, "4.2.8", "pass"),
    ({"success": None, "score": 0.7}, {"kind": "builtin", "class": "HallucinationMetric",
                                       "threshold": 0.5}, "4.1.8", "fail"),
    ({"success": None, "score": None}, {"kind": "geval", "threshold": 0.5}, "4.2.8", None),
])
def test_deepeval_verdicts(line, job, version, verdict):
    assert de.verdict_of(line, job, version) == verdict


def test_saved_score_direction():
    assert de.direction({"score": 0.1, "success": True, "threshold": 0.5}) == "low"
    assert de.direction({"score": 0.9, "success": True, "threshold": 0.5}) == "high"
    assert de.direction({"score": 0.5, "success": True, "threshold": 0.5}) is None
    assert de.direction({"score": None, "success": True, "threshold": 0.5}) is None


# Inspect AI ----------------------------------------------------------------------------------

def _inspect(change=None, prompts=False):
    def maker(root, verdicts):
        data = inspect_data(verdicts)
        data["eval"]["packages"] = {"inspect_ai": "0.3.273"}
        if prompts:
            for s in data["samples"]:
                s["scores"]["model_graded_qa"]["metadata"] = {"grading": [
                    {"role": "user", "content": f"Grade {s['input']}"},
                    {"role": "assistant", "content": "GRADE: C"}]}
        if change:
            change(data)
        path = root / "logs" / "2026-10-02_support.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(data), encoding="utf-8")
    return maker


@pytest.fixture
def inspect_ws(tmp_path, stubs):
    ws = _checked(tmp_path, _inspect())
    stubs.plan(verdicts=_saved(ws))
    return ws


def test_inspect_rescores_a_copy_of_the_log(inspect_ws, stubs, capsys):
    log = inspect_ws.root / "logs" / "2026-10-02_support.json"
    before = log.read_bytes()
    code, out = ask(capsys, inspect_ws, "--allow-calls", 72)
    assert code == 0
    assert "Asking your judge 72 times through Inspect AI. Ctrl-C stops it." in out
    assert "Asked twice more, your judge changed its mind on 0 of your 36 answers." in out
    assert [e["path"] for e in stubs("read_eval_log")] == [str(log)]
    scored = stubs("score_async")
    assert len(scored) == 2
    for e in scored:
        assert e["action"] == "append" and e["copy"] is True
        assert e["roles"] == {"grader": ["anthropic/claude-haiku-4-5", False]}
        assert e["model"] == "mockllm/model"  # the model under test can't be called
        assert e["scorer"] == ["model_graded_qa"]
    created = stubs("registry_create")
    assert created and created[0]["name"] == "inspect_ai/model_graded_qa"
    assert created[0]["options"] == {"instructions": "Grade the answer as C (correct) or I "
                                                     "(incorrect).", "partial_credit": True,
                                     "model_role": "grader"}
    assert stubs("dotenv"), "Inspect's own .env loader is used"
    assert stubs("log-written") == [] and log.read_bytes() == before
    assert (_folder(inspect_ws) / "inspect.jsonl").is_file()


def test_inspect_lines_carry_the_full_fingerprint(inspect_ws, capsys):
    ask(capsys, inspect_ws, "--allow-calls", 72)
    _, records = read_run(_folder(inspect_ws) / "judge-again-1.jsonl")
    saved = inspect_ws.data()["fingerprint"]
    for rec in records.values():
        fp = rec["fingerprint"]
        assert fp["model"] == "anthropic/claude-haiku-4-5" and fp["provider"] == "anthropic"
        assert fp["temperature"] == 0.0 and fp["prompt_hash"] == saved["prompt_hash"]
        assert fp["tool"] == "inspect" and fp["tool_version"] == "0.3.273"
        assert fp["judge_copy"] == "exact"


def test_the_grader_cache_is_turned_off_and_the_rest_kept(tmp_path, stubs, capsys):
    def cached(data):
        data["eval"]["model_roles"]["grader"]["config"]["cache"] = True

    ws = _checked(tmp_path, _inspect(cached))
    stubs.plan(verdicts=_saved(ws))
    ask(capsys, ws, "--allow-calls", 72)
    graders = [e for e in stubs("get_model") if e["model"] == "anthropic/claude-haiku-4-5"]
    assert graders and all(e["config"] == {"temperature": 0.0, "cache": False} for e in graders)


def test_a_changed_grading_prompt_is_not_counted(tmp_path, stubs, capsys):
    ws = _checked(tmp_path, _inspect(prompts=True))
    first = _inputs(ws)[0]
    stubs.plan(verdicts=_saved(ws), prompt_changed=[first])
    _, out = ask(capsys, ws, "--allow-calls", 72)
    assert ("1 answer was not counted: its grading prompt differs from the saved one, so it "
            "was not the same judge input.") in out
    assert _block(ws)["counted"] == 35


def test_matching_prompts_make_another_version_exactly_your_judge(tmp_path, stubs,
                                                                  capsys, monkeypatch):
    monkeypatch.setenv("STUB_VERSION", "0.3.300")
    ws = _checked(tmp_path, _inspect(prompts=True))
    stubs.plan(verdicts=_saved(ws))
    _, out = ask(capsys, ws, "--allow-calls", 72)
    assert "This is a close copy of your judge: your Python has Inspect 0.3.300" in out
    block = _block(ws)
    assert block["status"] == "exact"
    assert block["why"] == ("the grading prompts matched your saved ones on every answer "
                            "(Inspect 0.3.300 here; your log was made with 0.3.273)")
    _, records = read_run(_folder(ws) / "judge-again-1.jsonl")
    assert all(r["fingerprint"]["judge_copy"] == "exact" for r in records.values())


def test_without_saved_prompts_another_version_stays_a_close_copy(inspect_ws, stubs,
                                                                  capsys, monkeypatch):
    monkeypatch.setenv("STUB_VERSION", "0.3.300")
    ask(capsys, inspect_ws, "--allow-calls", 72)
    assert _block(inspect_ws)["status"] == "close"


def test_no_grader_asks_the_model_under_test_as_the_judge(tmp_path, stubs,
                                                          capsys):
    def no_grader(data):
        data["eval"]["model_roles"] = {}
        data["eval"]["model"] = "openai/gpt-4o"
        data["eval"]["model_generate_config"] = {"cache": True, "max_tokens": 100}

    ws = _checked(tmp_path, _inspect(no_grader))
    stubs.plan(verdicts=_saved(ws))
    code, out = ask(capsys, ws, "--allow-calls", 72)
    assert code == 0 and "Your judge is your model under test, openai/gpt-4o" in out
    for e in stubs("score_async"):
        assert e["model"] == "openai/gpt-4o" and e["model_cache"] is False and e["roles"] == {}
    tested = [e for e in stubs("get_model") if e["model"] == "openai/gpt-4o"]
    assert tested[0]["config"] == {"cache": False, "max_tokens": 100}


def test_a_grader_given_as_a_scorer_option(tmp_path, stubs, capsys):
    def option(data):
        data["eval"]["model_roles"] = {}
        data["eval"]["scorers"][0]["options"]["model"] = "openai/gpt-4.1-mini"

    ws = _checked(tmp_path, _inspect(option))
    stubs.plan(verdicts=_saved(ws))
    code, _ = ask(capsys, ws, "--allow-calls", 72)
    assert code == 0
    assert stubs("registry_create")[0]["options"]["model"] == ["openai/gpt-4.1-mini", False]
    assert all(e["model"] == "mockllm/model" for e in stubs("score_async"))


def test_a_partial_grade_is_not_a_clear_verdict(inspect_ws, stubs, capsys):
    first = _inputs(inspect_ws)[0]
    stubs.plan(verdicts=_saved(inspect_ws), values={first: "P"})
    _, out = ask(capsys, inspect_ws, "--allow-calls", 72)
    assert "1 answer was not counted: the judge gave no clear decision." in out


def test_without_inspects_loader_nothing_is_loaded(inspect_ws, stubs, capsys,
                                                   monkeypatch):
    monkeypatch.setenv("STUB_NO_DOTENV", "1")
    code, _ = ask(capsys, inspect_ws, "--allow-calls", 72)
    assert code == 0 and stubs("dotenv") == []


def test_the_inspect_job(inspect_ws, capsys, monkeypatch):
    jobs = _jobs(monkeypatch)
    ask(capsys, inspect_ws, "--allow-calls", 72)
    run = jobs[-1][0]
    assert run["mode"] == "run" and run["scorer"] == "model_graded_qa"
    assert run["log"] == str(inspect_ws.root / "logs" / "2026-10-02_support.json")
    assert len(run["answers"]) == 36 and set(run["answers"][0]) == {"id", "sample", "epoch"}


# MLflow --------------------------------------------------------------------------------------

def _mlflow_ws(root, monkeypatch, **info):
    """A check whose judge is in an MLflow store, as `assessment_info` would read it."""
    ws = _checked(root, inspect_project)
    data = ws.data()
    data["tool"] = "mlflow"
    ws.start.write_text(json.dumps(data), encoding="utf-8")
    answers = again.labeled_answers(ws)
    traces = {a["id"]: f"tr-{n}" for n, a in enumerate(answers)}
    base = {"source_id": "openai:/gpt-4.1-mini", "scorer_name": None, "scorer_version": None,
            "name": "safety", "guidelines": None, "instructions": False, "trace": False,
            "text": None, "experiment": "1", "uri": "sqlite:////tmp/judgekeeper-mlflow-x/mlflow.db",
            "traces": traces}
    monkeypatch.setattr(mf, "assessment_info", lambda ws, metric: {**base, **info})
    by_input = {str(a["input"]): traces[a["id"]] for a in answers}
    verdicts = {traces[a["id"]]: a["verdict"] == "pass" for a in answers}
    return ws, traces, by_input, verdicts


def ask_mlflow(ws, capsys, allow=72, **kw):
    options = AgainOptions(python=sys.executable, allow_calls=allow, **kw)
    code = start_again._ask_again(ws, start.Talk(), options)
    return code, capsys.readouterr().out


def test_mlflow_calls_a_built_in_judge_directly(tmp_path, stubs, capsys,
                                                monkeypatch):
    ws, traces, by_input, verdicts = _mlflow_ws(tmp_path, monkeypatch)
    stubs.plan(verdicts=verdicts, by_input=by_input)
    code, out = ask_mlflow(ws, capsys)
    assert code == 0
    assert "Asking your judge 72 times through MLflow. Ctrl-C stops it." in out
    assert "Asked twice more, your judge changed its mind on 0 of your 36 answers." in out
    assert stubs("construct") == [{"kind": "construct", "cls": "Safety",
                                   "kwargs": {"model": "openai:/gpt-4.1-mini"}}]
    calls = stubs("judge")
    assert len(calls) == 72 and calls[0]["inputs"].startswith("Question")
    assert calls[0]["outputs"].startswith("Answer") and calls[0]["trace"] is None
    assert stubs("evaluate") == [] and stubs("client-call") == []
    assert all(e["telemetry"] == "true" for e in stubs("import"))
    assert sorted(e["trace"] for e in stubs("get_trace")) == sorted(traces.values())
    assert {e["uri"] for e in stubs("set_tracking_uri")} == {
        "sqlite:////tmp/judgekeeper-mlflow-x/mlflow.db"}


def test_mlflow_lines_carry_the_full_fingerprint(tmp_path, stubs, capsys,
                                                 monkeypatch):
    ws, _, by_input, verdicts = _mlflow_ws(tmp_path, monkeypatch)
    stubs.plan(verdicts=verdicts, by_input=by_input)
    ask_mlflow(ws, capsys)
    header, records = read_run(_folder(ws) / "judge-again-1.jsonl")
    assert header["source"]["kind"] == "mlflow"
    for rec in records.values():
        fp = rec["fingerprint"]
        assert fp["model"] == "openai:/gpt-4.1-mini" and fp["provider"] == "openai"
        assert fp["tool"] == "mlflow" and fp["tool_version"] == "3.16.1"
        assert fp["judge_copy"] == "close copy"
        assert fp["judge_copy_why"] == [(
            "MLflow's built-in safety judge with the model saved with your assessments; the "
            "MLflow version was not confirmed")]


def test_mlflow_flips_and_errors(tmp_path, stubs, capsys, monkeypatch):
    ws, traces, by_input, verdicts = _mlflow_ws(tmp_path, monkeypatch)
    ids = list(traces.values())
    stubs.plan(verdicts=verdicts, by_input=by_input, flips=[[ids[0], 1], [ids[1], 1]],
               errors=[[ids[2], 0]])
    _, out = ask_mlflow(ws, capsys)
    assert "Asked twice more, your judge changed its mind on 2 of your 35 answers." in out
    assert "1 answer was not counted: the judge's tool gave an error for it." in out


def test_a_registered_judge_comes_back_by_name_and_version(tmp_path, stubs, capsys,
                                                           monkeypatch, terminal):
    ws, _, by_input, verdicts = _mlflow_ws(tmp_path, monkeypatch, name="tone",
                                           scorer_name="tone", scorer_version="2")
    monkeypatch.setenv("STUB_REGISTERED", "tone")
    stubs.plan(verdicts=verdicts, by_input=by_input)
    terminal += ["y"]  # the MLflow version is the one the eval ran with
    code, out = ask_mlflow(ws, capsys)
    assert code == 0 and "This is exactly your judge: MLflow calls your registered judge tone" \
        in out
    run = stubs("get_scorer")[-1]
    assert (run["name"], run["version"], run["experiment_id"]) == ("tone", 2, "1")
    assert _block(ws)["status"] == "exact"


def test_guidelines_come_back_with_their_one_guideline(tmp_path, stubs, capsys,
                                                       monkeypatch):
    ws, _, by_input, verdicts = _mlflow_ws(tmp_path, monkeypatch, name="guidelines",
                                           guidelines=1, text="Be kind.")
    stubs.plan(verdicts=verdicts, by_input=by_input)
    code, _ = ask_mlflow(ws, capsys)
    assert code == 0
    assert stubs("construct") == [{"kind": "construct", "cls": "Guidelines", "kwargs": {
        "guidelines": "Be kind.", "model": "openai:/gpt-4.1-mini"}}]


def test_an_unregistered_make_judge_is_rebuilt(tmp_path, stubs, capsys,
                                               monkeypatch):
    text = "Is {{ outputs }} kind?"
    ws, _, by_input, verdicts = _mlflow_ws(tmp_path, monkeypatch, name="tone",
                                           instructions=True, text=text)
    stubs.plan(verdicts=verdicts, by_input=by_input)
    code, _ = ask_mlflow(ws, capsys)
    assert code == 0
    made = stubs("make_judge")[0]
    assert (made["name"], made["instructions"], made["model"]) == (
        "tone", text, "openai:/gpt-4.1-mini")
    assert _block(ws)["status"] == "close"


def test_a_trace_judge_is_given_the_trace(tmp_path, stubs, capsys, monkeypatch):
    ws, _, by_input, verdicts = _mlflow_ws(tmp_path, monkeypatch, name="tone",
                                           instructions=True, trace=True,
                                           text="Look at {{ trace }}")
    stubs.plan(verdicts=verdicts, by_input=by_input)
    code, _ = ask_mlflow(ws, capsys, allow=2160)
    assert code == 0
    calls = stubs("judge")
    assert all(c["trace"] and c["inputs"] is None for c in calls)


def test_expectations_are_read_from_the_trace(tmp_path, stubs, capsys,
                                              monkeypatch):
    ws, traces, by_input, verdicts = _mlflow_ws(tmp_path, monkeypatch, name="correctness")
    first = next(iter(traces.values()))
    stubs.plan(verdicts=verdicts, by_input=by_input, traces={first: {"assessments": [
        {"assessment_name": "expected_response", "expectation": {"value": "Paris"}},
        {"assessment_name": "old", "expectation": {"value": "Rome"}, "valid": False},
        {"assessment_name": "correctness", "feedback": {"value": "yes"}}]}})
    ask_mlflow(ws, capsys)
    calls = [c for c in stubs("judge") if by_input.get(c["inputs"]) == first]
    assert calls and all(c["expectations"] == {"expected_response": "Paris"} for c in calls)
    others = [c for c in stubs("judge") if by_input.get(c["inputs"]) != first]
    assert all(c["expectations"] is None for c in others)


def test_a_judge_gets_only_what_it_takes(tmp_path, stubs, capsys, monkeypatch):
    ws, traces, by_input, verdicts = _mlflow_ws(tmp_path, monkeypatch, name="relevance_to_query")
    first = next(iter(traces.values()))
    stubs.plan(verdicts=verdicts, by_input=by_input, traces={first: {"assessments": [
        {"assessment_name": "expected_response", "expectation": {"value": "Paris"}}]}})
    code, out = ask_mlflow(ws, capsys)
    assert code == 0 and "Asked twice more" in out
    assert all(c["expectations"] is None for c in stubs("judge"))


def test_answers_not_in_the_store_are_left_out(tmp_path, stubs, capsys,
                                               monkeypatch):
    ws, traces, by_input, verdicts = _mlflow_ws(tmp_path, monkeypatch)
    gone = next(iter(traces))
    info = mf.assessment_info(ws, "safety")
    info["traces"] = {k: v for k, v in traces.items() if k != gone}
    monkeypatch.setattr(mf, "assessment_info", lambda ws, metric: info)
    stubs.plan(verdicts=verdicts, by_input=by_input)
    _, out = ask_mlflow(ws, capsys, allow=70)
    assert "35 marked answers × 2 times = 70 judge calls." in out
    assert "1 answer is left out: it is not in your MLflow store any more." in out


def test_mlflow_needs_the_key_in_the_shell(tmp_path, stubs, capsys, monkeypatch):
    ws, *_ = _mlflow_ws(tmp_path, monkeypatch)
    monkeypatch.delenv("OPENAI_API_KEY")
    (tmp_path / ".env").write_text("OPENAI_API_KEY=x\n", encoding="utf-8")
    code, out = ask_mlflow(ws, capsys)
    assert code == 0 and "MLflow does not load .env files" in out
    assert "Set the key, then run judgekeeper start --ask-again again." in out
    assert stubs("judge") == []


@pytest.mark.parametrize("meta, want", [
    ({"guideline": "Be kind."}, {"guidelines": 1, "instructions": False, "trace": False,
                                 "text": "Be kind."}),
    ({"guideline": "Be kind.\nBe short."}, {"guidelines": 2, "instructions": False,
                                            "trace": False, "text": "Be kind.\nBe short."}),
    ({"guidelines": ["a", "b"]}, {"guidelines": 2, "instructions": False, "trace": False,
                                  "text": None}),
    ({"guideline": "Is {{ outputs }} kind?"}, {"guidelines": None, "instructions": True,
                                               "trace": False,
                                               "text": "Is {{ outputs }} kind?"}),
    ({"guideline": "Look at {{ trace }}"}, {"guidelines": None, "instructions": True,
                                            "trace": True, "text": "Look at {{ trace }}"}),
    ({}, {"guidelines": None, "instructions": False, "trace": False, "text": None}),
])
def test_what_an_assessment_says_about_its_judge(meta, want):
    assert mf.judge_meta(meta) == want


def test_trace_ids_come_from_a_real_store(tmp_path):
    from tests.conftest import build_mlflow_store

    build_mlflow_store(tmp_path)
    info = mf.assessment_info(start_label.Workspace(tmp_path), "correctness")
    assert info["traces"] and all(v.startswith("tr-") for v in info["traces"].values())
    # a temporary copy of the store, read with a plain address: no read-only form
    assert info["experiment"] and info["uri"].startswith("sqlite:///")
    assert "mode=ro" not in info["uri"]


# All three -----------------------------------------------------------------------------------

def test_no_tool_says_not_switched_on(deepeval_ws, capsys):
    _, out = ask(capsys, deepeval_ws, *FIELDS, "--allow-calls", 72)
    assert "not switched on" not in out
