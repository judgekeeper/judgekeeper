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


def test_question_numbers_come_from_any_shape(ic):
    assert ic.question_number("Question 12: what is 12 + 12?") == 12
    assert ic.question_number({"input": {"question": "Question 7: what is 7 + 7?"}}) == 7
    assert ic.question_number({"output": "The answer is 4."}) == 0


def _disagree(ic, result):
    """The answers the stand-in person marks otherwise than the judge, and their marks."""
    marks = {i: ic.person_mark({"input": ic.quiz(i)[0], "output": ic.quiz(i)[1]}, result)
             for i in range(1, ic.N + 1)}
    judge = {i: "pass" if i in ic.JUDGE_PASSES else "fail" for i in marks}
    return [i for i in marks if marks[i] != judge[i]], list(marks.values())


def test_the_stand_in_person_mostly_agrees_with_the_judge(ic):
    """One answer apart (29: the judge failed it, the person passed it): good enough."""
    disagree, marks = _disagree(ic, "good enough")
    assert disagree == [29] and marks.count("pass") == 29
    assert ic.person_mark({"input": ic.quiz(29)[0]}) == "pass"  # good enough is the default


def test_in_the_second_project_the_person_mostly_disagrees(ic):
    disagree, marks = _disagree(ic, "needs work")
    assert len(disagree) == 47 and marks.count("pass") == 25 == marks.count("fail")


def test_in_the_third_project_the_person_disagrees_on_9_too_few_to_tell(ic):
    disagree, marks = _disagree(ic, "too early")
    assert disagree == [23, 24, 25, 26, 27, 28, 31, 32, 33]
    assert marks.count("pass") == 25 == marks.count("fail")


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


def test_the_release_trigger_takes_only_this_repositorys_release():
    """`workflow_run` matches a workflow by name: a fork's own "Release" must not count."""
    yaml = pytest.importorskip("yaml")
    job = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]["install-check"]
    condition = " ".join(job["if"].split())
    for needed in ("github.event_name != 'workflow_run'",
                   "github.event.workflow_run.conclusion == 'success'",
                   "github.event.workflow_run.event == 'release'",
                   "github.event.workflow_run.head_repository.full_name == github.repository"):
        assert needed in condition, needed


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
           "It shows the answers one at a time.")
    assert ic.page_link(out) == ("http://127.0.0.1:54321", "Ab-c_9")


def _walk(ic, monkeypatch, tool, work, jk=None, toml=False):
    """The walk with every command faked: (the folder, the commands run, what each must print,
    the exit codes it may give), the page calls, and the steps. With `toml`, judgekeeper.toml
    is there, as the mapping run saves it."""
    check = object.__new__(ic.Check)
    check.tool, check.jk, check.port, check.steps = tool, jk or ["jk"], "5", []
    check.via = "uvx" if jk else "venv"
    check.version = "1.0.0"
    check.work, check.project = work, work / f"{tool} project"
    check.project.mkdir(parents=True, exist_ok=True)
    (check.project / ic.MARKER).write_text("", encoding="utf-8")
    if toml:
        (check.project / "judgekeeper.toml").write_text("[start]\n", encoding="utf-8")
    ran, posted = [], []

    class Done:
        returncode = 0
        stdout = "Open this link in your browser to mark answers:\nhttp://127.0.0.1:5/?token=t0k\n"

    def run(name, args, ok_codes=(0,), expect=(), cwd=None, **kwargs):
        args = [str(a) for a in args]
        assert args[:len(check.jk)] == check.jk, args
        ran.append((cwd or check.project, args[len(check.jk):], list(expect), ok_codes))
        return Done()

    def call(base, token, path, body=None):
        posted.append((base, token, path, body))
        if path == "/state":
            return {"items": [{"id": "a", "input": "Question 1: what is 1 + 1?"},
                              {"id": "b", "input": "Question 29: what is 29 + 29?"},
                              {"id": "c", "input": "Question 40: what is 40 + 40?"}],
                    "counts": {}}
        return {"summary": {}}

    monkeypatch.setattr(check, "run", run, raising=False)
    monkeypatch.setattr(check, "call", call, raising=False)
    monkeypatch.setattr(check, "make_results", lambda *a, **k: True, raising=False)
    check.walk()
    return check, ran, posted, check.steps


def _in(ran, folder):
    """The commands run in one project folder, and what each must print."""
    return [(args, expect, codes) for cwd, args, expect, codes in ran if cwd == folder]


def _front(ic, commands):
    """The commands up to `--stop` (`judgekeeper` runs only), and those after it."""
    end = commands.index(["--stop"])
    fronts = commands[:end]
    assert not [c for c in fronts if c[:1] == ["check"]]
    return fronts, commands[end + 1:]


def test_the_walk_goes_through_judgekeeper(ic, monkeypatch, tmp_path):
    """`judgekeeper` (found, checked, the page in the background, its link printed: no
    browser), the stand-in person's marks posted to it, `judgekeeper` with the result (good
    enough), then `judgekeeper --stop`. No page turns on automatic checks."""
    check, ran, posted, steps = _walk(ic, monkeypatch, "table", tmp_path)
    main = _in(ran, check.project)
    fronts, after = _front(ic, [args for args, _, _ in main])
    assert fronts == [["--no-browser", "--port", "5"], ["--no-browser", "--port", "5"]]
    assert after[0][:1] == ["fix"]
    first = " ".join(main[0][1])
    assert "Open this link" in first and "Your LLM-as-a-judge passed 28 answers and failed 22" in first
    result = " ".join(main[1][1])
    assert r"You\s+passed\s+\d+\s+answers\.\s+Of\s+those,\s+your\s+" in result
    assert "Result: your LLM-as-a-judge is good enough to use" in result and main[1][2] == (0,)
    assert "automatic" not in result.lower()
    assert not [path for _, _, path, _ in posted if path in ("/turn-on", "/no-thanks")]
    assert not [name for name, *_ in steps if "Turn on" in name]
    labels = [body for _, _, path, body in posted if path == "/label"]
    assert [(b["id"], b["label"]) for b in labels[:3]] == [("a", "pass"), ("b", "pass"),
                                                          ("c", "fail")]
    assert all(isinstance(b["seconds"], (int, float)) for b in labels)


def test_two_more_projects_give_needs_work_and_too_early(ic, monkeypatch, tmp_path):
    """Copies of the project with the same results, marked otherwise: mostly disagreeing,
    "needs work" (exit 0); disagreeing on 9 of 50, "too early to tell" (exit 3), and the Next
    line says to run the eval on more questions."""
    check, ran, posted, _ = _walk(ic, monkeypatch, "table", tmp_path)
    for result, code, said in (("needs work", 0, "your LLM-as-a-judge needs work"),
                               ("too early", 3, "too early to tell")):
        folder = check.other(result)
        assert folder.parent == tmp_path and (folder / ic.MARKER).is_file()
        runs = _in(ran, folder)
        assert [args for args, _, _ in runs] == [["--no-browser", "--port", "5"],
                                                 ["--no-browser", "--port", "5"], ["--stop"]]
        assert f"Result: {said}" in " ".join(runs[1][1]) and runs[1][2] == (code,)
    early = _in(ran, check.other("too early"))[1][1]
    printed = ("Next: run your eval on more questions, then run\n"
               "`judgekeeper mark`: the new answers join the ones you marked.")
    assert re.search(early[-1], printed)
    assert not re.search(early[-1], printed.replace("more questions", "more answers"))
    # Marked in order: the main project, then needs work, then too early.
    labels = [body["label"] for _, _, path, body in posted if path == "/label"]
    assert labels == ["pass", "pass", "fail", "pass", "pass", "pass", "pass", "fail", "fail"]


def test_for_an_own_format_the_mapping_run_is_the_first_look(ic, monkeypatch, tmp_path):
    """`judgekeeper --yes` maps the file and goes on: it says what was found and opens the
    page, so the first look is checked there, not in a second run. Each copy maps it too."""
    check, ran, _, steps = _walk(ic, monkeypatch, "own-format", tmp_path, toml=True)
    for folder in (check.project, check.other("needs work"), check.other("too early")):
        runs = _in(ran, folder)
        fronts, _ = _front(ic, [args for args, _, _ in runs])
        assert fronts[0] == ["--yes", "--no-browser", "--port", "5"]
        assert fronts[1:] == [["--no-browser", "--port", "5"]]
        first = " ".join(runs[0][1])
        assert "Saved judgekeeper" in first and re.escape("my-judge-1") in first
        assert "Your LLM-as-a-judge passed 28 answers and failed 22" in first and "Open this link" in first
    saved = [ok for name, ok, *_ in steps if name.startswith("judgekeeper.toml saved")]
    assert saved == [True, True, True]


def test_the_walk_ends_with_the_re_check(ic, monkeypatch, tmp_path):
    """With the new rule in the results: `check` re-tests it on the marks; no flag of the
    automatic checks is run, and no step runs `judgekeeper start`, which is gone."""
    check, ran, _, _ = _walk(ic, monkeypatch, "promptfoo", tmp_path)
    assert not [args for _, args, _, _ in ran if args[:1] == ["start"]]
    main = _in(ran, check.project)
    commands = [args for args, _, _ in main]
    end = commands.index(["--stop"])
    assert commands[end + 1:] == [["fix"], ["check"]]
    assert [args for _, args, _, _ in ran if args[:1] == ["check"]] == [["check"]]
    assert ran[-1][1] == ["check"]
    assert any("Agreed with you:" in e for e in main[-1][1])


def test_with_uvx_every_step_runs_judgekeeper_through_uvx(ic, monkeypatch, tmp_path):
    jk = ["uvx", "--from", "w.whl", "judgekeeper"]
    check, ran, _, _ = _walk(ic, monkeypatch, "promptfoo", tmp_path, jk=jk)
    main = _in(ran, check.project)
    fronts, after = _front(ic, [args for args, _, _ in main])
    assert fronts[0] == ["--no-browser", "--port", "5"] and len(fronts) == 2
    assert after[0][:1] == ["fix"]
    first, result = " ".join(main[0][1]), " ".join(main[1][1])
    # The first look's Next: line names no command (mark, then click "See your result");
    # the result's does, through uvx.
    assert "uvx" not in first and ic.uvx_next(check.version) in result
    early = _in(ran, check.other("too early"))[1][1]
    assert re.search(early[-1], "Next: run your eval on more questions, then run\n"
                     "`uvx judgekeeper@1.0.0 mark`: the new answers join the ones you marked.")


@pytest.mark.parametrize(("version", "pre"), [("1.0.0", False), ("1.0.0rc1", True),
                                              ("1.0.0b1", True), ("1.0.0.dev1", True),
                                              ("1.0.1", False)])
def test_a_pre_release_is_told_by_judgekeepers_own_rule(ic, version, pre):
    from judgekeeper import textio

    assert ic.is_prerelease(version) is textio.is_prerelease(version) is pre


def test_the_uvx_next_line_names_the_version_only_for_a_pre_release(ic):
    said = ("Next: nothing to do. When you change your LLM-as-a-judge or\n"
            "update your eval tool, run `uvx judgekeeper{} check`.")
    plain, pinned = said.format(""), said.format("@1.0.0")
    assert re.search(ic.uvx_next("1.0.0"), plain)
    assert not re.search(ic.uvx_next("1.0.0"), pinned)
    rc = said.format("@1.0.0rc1")
    assert re.search(ic.uvx_next("1.0.0rc1"), rc)
    assert not re.search(ic.uvx_next("1.0.0rc1"), plain)


def test_without_uvx_the_next_line_is_not_checked_for_uvx(ic, monkeypatch, tmp_path):
    _, ran, _, _ = _walk(ic, monkeypatch, "table", tmp_path)
    assert not [e for _, _, expect, _ in ran for e in expect if "uvx" in e]


def test_the_walk_runs_fix_after_the_result(ic, monkeypatch, tmp_path):
    """`judgekeeper fix` (where the judge goes wrong, and the marked answers to grade again),
    for every tool; it never asks the judge or tests a rule itself."""
    for tool in ("promptfoo", "table"):
        check, ran, _, _ = _walk(ic, monkeypatch, tool, tmp_path / tool)
        main = _in(ran, check.project)
        commands = [args for args, _, _ in main]
        end = commands.index(["--stop"])
        assert commands[end + 1:] == [["fix"], ["check"]]
        assert main[end + 1][1] == [r"Step 4 of 5: Fix", r"mistakes\.md",
                                    r"marked-answers\.csv"]
        assert main[end + 1][2] == (0,)
