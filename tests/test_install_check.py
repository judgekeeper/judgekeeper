"""The install check (scripts/install_check.py) in small: reading a page link and a plan, the
fake judge's replies, the stand-in person's marks, and the workflow that runs it. Nothing is
installed and no tool is run."""

from __future__ import annotations

import importlib.util
import json
import re
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


def test_the_stand_in_person_marks_25_pass_and_25_fail(ic):
    marks = [ic.person_mark({"input": ic.quiz(i)[0], "output": ic.quiz(i)[1]})
             for i in range(1, ic.N + 1)]
    assert marks.count("pass") == 25 and marks.count("fail") == 25
    # It disagrees with the judge on 9 answers: 23-28 the judge passed, 31-33 it failed.
    judge = ["pass" if i in ic.JUDGE_PASSES else "fail" for i in range(1, ic.N + 1)]
    assert [i + 1 for i, (m, j) in enumerate(zip(marks, judge)) if m != j] == [
        23, 24, 25, 26, 27, 28, 31, 32, 33]


@pytest.mark.parametrize(("i", "ok"), [(1, True), (28, True), (29, False), (50, False)])
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


def test_the_workflow_runs_39_jobs_on_three_systems_6_of_them_through_uvx(ic):
    yaml = pytest.importorskip("yaml")
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    job = workflow["jobs"]["install-check"]
    matrix = job["strategy"]["matrix"]
    assert job["strategy"]["fail-fast"] is False and job["timeout-minutes"] == 30
    assert set(matrix["os"]) == {"ubuntu-latest", "windows-latest", "macos-latest"}
    assert tuple(matrix["tool"]) == ic.TOOLS
    assert matrix["python"] == ["3.12"] and matrix["via"] == ["venv"]
    extra = {(x["os"], x["tool"], x["python"], x["via"]) for x in matrix["include"]}
    pythons = {(o, "table", p, "venv") for o in matrix["os"] for p in ("3.11", "3.14")}
    uvx = {(o, t, "3.12", "uvx") for o in matrix["os"] for t in ("table", "promptfoo")}
    assert extra == pythons | uvx
    assert {t for _, t, _, _ in uvx} <= set(ic.UVX_TOOLS)
    assert len(matrix["os"]) * len(matrix["tool"]) + len(extra) == 39
    assert workflow["permissions"] == {"contents": "read"}
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "secrets." not in text and "persist-credentials: false" in text
    triggers = workflow[True]  # YAML 1.1 reads the key `on` as True
    assert set(triggers) == {"pull_request", "workflow_dispatch", "workflow_run"}
    assert triggers["workflow_run"] == {"workflows": ["Release"], "types": ["completed"]}
    assert triggers["workflow_dispatch"]["inputs"]["source"]["default"] == "build"


def test_the_uvx_jobs_get_uv_from_a_pinned_action_and_say_via(ic):
    yaml = pytest.importorskip("yaml")
    steps = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]["install-check"]["steps"]
    (uv,) = [s for s in steps if s.get("uses", "").startswith("astral-sh/setup-uv@")]
    assert re.fullmatch(r"astral-sh/setup-uv@[0-9a-f]{40}", uv["uses"])
    assert uv["if"] == "matrix.via == 'uvx'"
    (check,) = [s for s in steps if s.get("name") == "Run the install check"]
    assert check["env"]["VIA"] == "${{ matrix.via }}" and '--via "$VIA"' in check["run"]


def test_uvx_runs_judgekeeper_from_the_built_wheel_or_the_release(ic):
    wheel = Path("w") / "judgekeeper-1.0.0b1-py3-none-any.whl"
    assert ic.uvx_command("uvx", "build", wheel) == ["uvx", "--from", str(wheel), "judgekeeper"]
    assert ic.uvx_command("uvx", "pypi:1.0.0b1", None) == [
        "uvx", "--from", "judgekeeper==1.0.0b1", "judgekeeper"]


def test_uvx_is_only_for_tools_that_need_nothing_installed_in_the_project(ic, tmp_path, capsys):
    assert ic.UVX_TOOLS == ("table", "promptfoo", "own-format", "promptfoo-ollama")
    for tool in ("deepeval", "inspect", "mlflow", "record", "inspect-ollama"):
        with pytest.raises(SystemExit):
            ic.main(["--tool", tool, "--via", "uvx", "--work", str(tmp_path)])
        assert "--via uvx" in capsys.readouterr().err
    assert not list(tmp_path.iterdir())  # stopped before anything was made


def test_with_uvx_the_project_has_no_virtual_environment(ic, tmp_path):
    check = object.__new__(ic.Check)
    check.via, check.steps, check.env = "uvx", [], {}
    check.project, check.dist = tmp_path / "project", tmp_path / "wheel"
    check.make_project()
    assert not (check.project / ".venv").exists()
    assert check.steps == [("project with no virtual environment (uvx)", True, "")]


def test_the_marking_page_link_is_read_from_the_output(ic):
    out = ("Open this link in your browser to mark answers:\n"
           "http://127.0.0.1:54321/?token=Ab-c_9\n"
           "It shows the same answers one at a time.")
    assert ic.page_link(out) == ("http://127.0.0.1:54321", "Ab-c_9")


def _walk(ic, monkeypatch, tool, project, jk=None):
    """The walk with every command faked: (the commands run, with what each must print), the
    page calls, and the steps."""
    check = object.__new__(ic.Check)
    check.tool, check.jk, check.port, check.steps = tool, jk or ["jk"], "5", []
    check.via = "uvx" if jk else "venv"
    check.version = "1.0.0"
    check.project = project
    ran, posted = [], []

    class Done:
        returncode = 0
        stdout = "Open this link in your browser to mark answers:\nhttp://127.0.0.1:5/?token=t0k\n"

    def run(name, args, ok_codes=(0,), expect=(), **kwargs):
        args = [str(a) for a in args]
        assert args[:len(check.jk)] == check.jk, args
        ran.append((args[len(check.jk):], list(expect)))
        return Done()

    def call(base, token, path, body=None):
        posted.append((base, token, path, body))
        if path == "/state":
            return {"items": [{"id": "a", "input": "Question 1: what is 1 + 1?"},
                              {"id": "b", "input": "Question 40: what is 40 + 40?"}],
                    "counts": {}}
        return {"summary": {}}

    monkeypatch.setattr(check, "run", run, raising=False)
    monkeypatch.setattr(check, "call", call, raising=False)
    for name in ("make_results", "serve", "fix_rule", "plan_then_go"):
        monkeypatch.setattr(check, name, lambda *a, **k: True, raising=False)
    check.walk()
    return ran, posted, check.steps


def _front(ic, commands):
    """The commands up to `--stop` (`judgekeeper` runs only), and those after it."""
    end = commands.index(["--stop"])
    fronts = commands[:end]
    assert not [c for c in fronts if c[:1] == ["check"]]
    return fronts, commands[end + 1:]


def test_the_walk_goes_through_judgekeeper(ic, monkeypatch, tmp_path):
    """`judgekeeper` (found, checked, the page in the background, its link printed: no
    browser), the stand-in person's marks posted to it, `judgekeeper` with the result, then
    `judgekeeper --stop`, before `judgekeeper start` takes over the result. No page turns on
    automatic checks."""
    ran, posted, steps = _walk(ic, monkeypatch, "table", tmp_path)
    fronts, after = _front(ic, [args for args, _ in ran])
    assert fronts == [["--no-browser", "--port", "5"], ["--no-browser", "--port", "5"]]
    assert after[0][:1] == ["start"]
    first = " ".join(ran[0][1])
    assert "Open this link" in first and "Your judge's grades: 28 Pass, 22 Fail" in first
    result = " ".join(ran[1][1])
    assert "Of the answers you passed" in result and "25 Fail" in result
    assert "automatic" not in result.lower()
    assert not [path for _, _, path, _ in posted if path in ("/turn-on", "/no-thanks")]
    assert not [name for name, *_ in steps if "Turn on" in name]
    labels = [body for _, _, path, body in posted if path == "/label"]
    assert [(b["id"], b["label"]) for b in labels] == [("a", "pass"), ("b", "fail")]
    assert all(isinstance(b["seconds"], (int, float)) for b in labels)


def test_for_an_own_format_the_mapping_run_is_the_first_look(ic, monkeypatch, tmp_path):
    """`judgekeeper --yes` maps the file and goes on: it says what was found and opens the
    page, so the first look is checked there, not in a second run."""
    (tmp_path / "judgekeeper.toml").write_text("[start]\n", encoding="utf-8")
    ran, _, steps = _walk(ic, monkeypatch, "own-format", tmp_path)
    fronts, _ = _front(ic, [args for args, _ in ran])
    assert fronts[0] == ["--yes", "--no-browser", "--port", "5"]
    assert fronts[1:] == [["--no-browser", "--port", "5"]]
    first = " ".join(ran[0][1])
    assert "Saved judgekeeper" in first and re.escape("my-judge-1") in first
    assert "Your judge's grades: 28 Pass, 22 Fail" in first and "Open this link" in first
    assert ("judgekeeper.toml saved", True) in [(name, ok) for name, ok, *_ in steps]


def test_the_walk_ends_with_the_re_check(ic, monkeypatch, tmp_path):
    """With the new rule in the results: `check --yes` (the person's yes to any calls, with no
    terminal) re-tests it on the marks; no flag of the automatic checks is run."""
    ran, _, _ = _walk(ic, monkeypatch, "promptfoo", tmp_path)
    commands = [args for args, _ in ran]
    assert [c for c in commands if c[:1] == ["check"]] == [["check", "--yes"]]
    assert commands[-1] == ["check", "--yes"]
    assert any("Re-checked on" in e for e in ran[-1][1])


def test_with_uvx_every_step_runs_judgekeeper_through_uvx(ic, monkeypatch, tmp_path):
    jk = ["uvx", "--from", "w.whl", "judgekeeper"]
    ran, _, _ = _walk(ic, monkeypatch, "promptfoo", tmp_path, jk=jk)
    fronts, after = _front(ic, [args for args, _ in ran])
    assert fronts[0] == ["--no-browser", "--port", "5"] and len(fronts) == 2
    assert after[0][:1] == ["start"]
    first, result = " ".join(ran[0][1]), " ".join(ran[1][1])
    assert "Next: [^`]*`uvx judgekeeper@" in first and "Next: [^`]*`uvx judgekeeper@" in result


def test_without_uvx_the_next_line_is_not_checked_for_uvx(ic, monkeypatch, tmp_path):
    ran, _, _ = _walk(ic, monkeypatch, "table", tmp_path)
    assert not [e for _, expect in ran for e in expect if "uvx" in e]

