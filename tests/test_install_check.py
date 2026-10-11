"""The install check (scripts/install_check.py) in small: reading a page link and a plan, the
fake judge's replies, the stand-in person's marks, and the workflow that runs it. Nothing is
installed and no tool is run."""

from __future__ import annotations

import importlib.util
import json
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "install_check.py"
WORKFLOW = ROOT / ".github" / "workflows" / "install-check.yml"


@pytest.fixture(scope="module")
def ic():
    spec = importlib.util.spec_from_file_location("install_check", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _content(reply: dict) -> str:
    return reply["choices"][0]["message"]["content"]


def _ask(i: int, model: str) -> dict:
    return {"model": model, "messages": [{"role": "user", "content": f"Question {i}: what is "
                                                                     f"{i} + {i}?"}]}


def test_the_page_link_is_read_from_the_output(ic):
    out = ("Every click is saved.\nOpen this link in your browser: "
           "http://127.0.0.1:54321/?token=Ab-c_9\n  To stop: Ctrl-C.")
    assert ic.page_link(out) == ("http://127.0.0.1:54321", "Ab-c_9")
    assert ic.page_link("judgekeeper found your LLM-as-a-judge:") is None


def test_n_is_read_from_the_plan(ic):
    plan = ("  40 marked answers × 2 times = 1,080 judge calls.\n\nTo go ahead without a "
            "terminal: judgekeeper start --port 50000 --ask-again --allow-calls 1,080")
    assert ic.planned_calls(plan) == 1080
    assert ic.planned_calls("  40 marked answers × 1 time = 40 judge calls.") == 40
    assert ic.planned_calls("Your judge can't be asked again: a custom scorer.") is None


def test_question_numbers_come_from_any_shape(ic):
    assert ic.question_number("Question 12: what is 12 + 12?") == 12
    assert ic.question_number({"input": {"question": "Question 7: what is 7 + 7?"}}) == 7
    assert ic.question_number({"output": "The answer is 4."}) == 0


def test_the_stand_in_person_marks_25_pass_and_15_fail(ic):
    marks = [ic.person_mark({"input": ic.quiz(i)[0], "output": ic.quiz(i)[1]})
             for i in range(1, ic.N + 1)]
    assert marks.count("pass") == 25 and marks.count("fail") == 15
    # It disagrees with the judge on 9 answers: 23-28 the judge passed, 31-33 it failed.
    judge = ["pass" if i in ic.JUDGE_PASSES else "fail" for i in range(1, ic.N + 1)]
    assert [i + 1 for i, (m, j) in enumerate(zip(marks, judge)) if m != j] == [
        23, 24, 25, 26, 27, 28, 31, 32, 33]


@pytest.mark.parametrize(("i", "ok"), [(1, True), (28, True), (29, False), (40, False)])
def test_the_fake_judge_passes_1_to_28_in_each_tools_shape(ic, i, ok):
    status, reply = ic.fake_reply("/v1/chat/completions", _ask(i, ic.MODELS["promptfoo"]))
    assert status == 200 and json.loads(_content(reply))["pass"] is ok
    _, reply = ic.fake_reply("/v1/chat/completions", _ask(i, ic.MODELS["inspect"]))
    assert _content(reply).endswith("GRADE: C" if ok else "GRADE: I")
    _, reply = ic.fake_reply("/v1/chat/completions", _ask(i, ic.MODELS["deepeval"]))
    assert json.loads(_content(reply))["score"] == (9 if ok else 1)
    _, reply = ic.fake_reply("/v1/chat/completions", _ask(i, ic.MODELS["mlflow"]))
    assert json.loads(_content(reply))["result"] == ("pass" if ok else "fail")
    _, reply = ic.fake_reply("/v1/chat/completions", _ask(i, ic.MODELS["own"]))
    assert json.loads(_content(reply))["verdict"] == ("pass" if ok else "fail")


def test_the_fake_judge_answers_ollamas_own_api_and_its_openai_one(ic):
    status, reply = ic.fake_reply("/api/chat", _ask(3, ic.OLLAMA_MODEL))
    assert status == 200 and reply["done"] is True
    assert json.loads(reply["message"]["content"])["pass"] is True  # promptfoo's llm-rubric
    _, reply = ic.fake_reply("/v1/chat/completions", _ask(33, ic.OLLAMA_MODEL))
    assert _content(reply).endswith("GRADE: I")  # Inspect AI's grader role
    _, tags = ic.fake_reply("/api/tags", {})
    assert tags["models"][0]["name"] == ic.OLLAMA_MODEL
    assert ic.fake_reply("/v1/embeddings", {})[0] == 404


def test_the_fake_judge_gives_logprobs_when_asked(ic):
    _, reply = ic.fake_reply("/v1/chat/completions",
                             {**_ask(1, ic.MODELS["deepeval"]), "logprobs": True})
    tokens = reply["choices"][0]["logprobs"]["content"]
    assert "".join(t["token"] for t in tokens) == _content(reply)


def test_the_fake_judge_serves_and_counts_its_calls(ic):
    judge = ic.FakeJudge()
    try:
        request = urllib.request.Request(f"{judge.url}/v1/chat/completions",
                                         data=json.dumps(_ask(30, ic.MODELS["own"])).encode(),
                                         headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=10) as r:
            assert json.loads(_content(json.loads(r.read())))["verdict"] == "fail"
        with urllib.request.urlopen(f"{judge.url}/api/tags", timeout=10) as r:
            assert json.loads(r.read())["models"]
    finally:
        judge.stop()
    assert judge.calls == [(ic.MODELS["own"], 30)]  # the model list is not a judge call


def test_the_rule_keeps_the_parts_each_tool_needs(ic):
    assert ic.rule_for("promptfoo", ic.RULE_NEW) == ic.RULE_NEW
    assert ic.rule_for("inspect-ollama", ic.RULE_NEW).endswith("GRADE: C or GRADE: I.")
    assert "{{ outputs }}" in ic.rule_for("mlflow", ic.RULE_NEW)


def test_the_source_names_the_version_to_expect(ic):
    assert ic.source_version("pypi:0.2.0") == "0.2.0"
    assert ic.source_version("build") == ic.source_version("build").strip()
    for wrong in ("pypi:", "pypi:0.2.0; rm -rf /", "wheel"):
        with pytest.raises(SystemExit):
            ic.source_version(wrong)


def test_pages_never_get_the_default_port_or_the_ones_kept_free(ic, monkeypatch):
    ports = iter([8765, 8805, 50123])

    class FakeSocket:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def bind(self, address):
            self.port = next(ports)

        def getsockname(self):
            return ("127.0.0.1", self.port)

    monkeypatch.setattr(ic.socket, "socket", FakeSocket)
    assert ic.free_port() == 50123


def test_only_a_folder_the_script_made_is_removed(ic, tmp_path):
    theirs = tmp_path / "theirs"
    theirs.mkdir()
    (theirs / "keep.txt").write_text("x", encoding="utf-8")
    with pytest.raises(SystemExit):
        ic.remove_own(theirs)
    assert (theirs / "keep.txt").is_file()
    ours = tmp_path / "ours"
    (ours / "sub").mkdir(parents=True)
    (ours / ic.MARKER).write_text("", encoding="utf-8")
    ic.remove_own(ours)
    assert not ours.exists()


def test_the_workflow_runs_33_jobs_on_three_systems(ic):
    yaml = pytest.importorskip("yaml")
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    job = workflow["jobs"]["install-check"]
    matrix = job["strategy"]["matrix"]
    assert job["strategy"]["fail-fast"] is False and job["timeout-minutes"] == 30
    assert set(matrix["os"]) == {"ubuntu-latest", "windows-latest", "macos-latest"}
    assert tuple(matrix["tool"]) == ic.TOOLS
    extra = {(x["os"], x["tool"], x["python"]) for x in matrix["include"]}
    assert extra == {(o, "table", p) for o in matrix["os"] for p in ("3.11", "3.14")}
    assert len(matrix["os"]) * len(matrix["tool"]) * len(matrix["python"]) + len(extra) == 33
    assert workflow["permissions"] == {"contents": "read"}
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "secrets." not in text and "persist-credentials: false" in text
    triggers = workflow[True]  # YAML 1.1 reads the key `on` as True
    assert set(triggers) == {"pull_request", "workflow_dispatch", "workflow_run"}
    assert triggers["workflow_run"] == {"workflows": ["Release"], "types": ["completed"]}
    assert triggers["workflow_dispatch"]["inputs"]["source"]["default"] == "build"
