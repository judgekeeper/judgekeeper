"""Asking your judge again, for real: promptfoo re-grades the labeled answers, or the user's
own judge command runs on them; then the numbers and the saved files.

No test calls a paid API and none needs Node or promptfoo: the one process function is
replaced by a fake promptfoo that reads the two files judgekeeper writes and answers as
promptfoo's `eval -o` would. One optional test runs the real promptfoo, when it is installed,
with a local fake grader.
"""

from __future__ import annotations

import builtins
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from judgekeeper import again, keys, start, start_label
from judgekeeper.again import AgainOptions, make_plan
from judgekeeper.again import promptfoo as pf
from judgekeeper.cli import main
from judgekeeper.judgments import read_run
from judgekeeper.start_label import StartSession
from tests import keyboard
from tests.conftest import FIXTURES
from tests.start_projects import (
    project_promptfoo,
    promptfoo_project,
    save_result,
    split,
)

CONFIG = ".judgekeeper-regrade.promptfoo.json"
TESTS = ".judgekeeper-regrade.tests.json"
SECRET = "sk-proj-THISisAfakeKEYthatMUSTbeSCRUBBED0123456789"


def _quiet(line=""):
    pass


def _checked(root, n_pass=20, n_fail=16, maker=promptfoo_project, **kwargs):
    maker(root, split(n_pass, n_fail), **kwargs)
    ws = start_label.prepare(start.find_judge(root), say=_quiet)
    session = StartSession(ws)
    for q in ws.data()["queue"]:
        session.update({"id": q["id"], "label": q["group"]})
    save_result(ws, session, say=_quiet)
    return ws


def _edit(root, change):
    path = root / "results.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    change(data)
    path.write_text(json.dumps(data), encoding="utf-8")


def _version(data):
    data.setdefault("metadata", {})["promptfooVersion"] = "0.123.1"


class FakePromptfoo:
    """promptfoo, as far as judgekeeper sees it: `--version`, and `eval` reading the two files
    judgekeeper wrote and writing the -o file. `flips` maps (answer id, repeat) to the opposite
    of the saved verdict; `prompt_changed` holds ids whose grading prompt comes back
    different; `extra` is put into every reason (a planted secret)."""

    def __init__(self, ws, version="0.123.1"):
        self.ws, self.version = ws, version
        self.calls, self.files_seen = [], {}
        self.flips, self.prompt_changed, self.errors = set(), set(), set()
        self.code, self.stderr, self.extra, self.interrupt = None, "", "", False
        saved = json.loads((ws.root / "results.json").read_text(encoding="utf-8"))
        self.saved = {}
        for row in saved["results"]["results"]:
            comp = row["gradingResult"]["componentResults"][0]
            self.saved[row["vars"]["question"]] = (row["success"], (comp.get("metadata") or {})
                                                   .get("renderedGradingPrompt"))

    def __call__(self, argv, cwd, env=None, timeout=None):
        self.calls.append(SimpleNamespace(argv=list(argv), cwd=Path(cwd), env=dict(env or {})))
        if argv[-1] == "--version":
            return SimpleNamespace(returncode=0, stdout=self.version + "\n", stderr="")
        assert "eval" in argv, argv
        cwd = Path(cwd)
        config = json.loads((cwd / argv[argv.index("-c") + 1]).read_text(encoding="utf-8"))
        tests = json.loads((cwd / config["tests"].removeprefix("file://")).read_text(
            encoding="utf-8"))
        self.files_seen = {"config": config, "tests": tests}
        if self.interrupt:
            raise KeyboardInterrupt
        if self.code not in (None, 0, 100):
            return SimpleNamespace(returncode=self.code, stdout="", stderr=self.stderr)
        times = int(argv[argv.index("--repeat") + 1])
        rows = []
        for r in range(times):
            for t in tests:
                saved, prompt = self.saved[t["vars"]["question"]]
                verdict = (not saved) if (t["description"], r) in self.flips else saved
                if t["description"] in self.prompt_changed:
                    prompt = "a different grading prompt"
                error = t["description"] in self.errors and r == 0
                comps = [{"assertion": a, "pass": None if error else verdict,
                          "score": None if error else int(verdict),
                          "reason": f"again {r}{self.extra}",
                          "metadata": {"renderedGradingPrompt": prompt} if prompt else {}}
                         for a in t["assert"]]
                rows.append({"testIdx": len(rows), "promptIdx": 0,
                             "description": t["description"],
                             "testCase": {"description": t["description"], "vars": t["vars"],
                                          "options": t.get("options", {})},
                             "vars": t["vars"], "prompt": {"raw": t["vars"]["judgekeeper_prompt"]},
                             "response": {"output": t["providerOutput"]},
                             "gradingResult": {"pass": verdict, "componentResults": comps},
                             "success": verdict})
        out = cwd / argv[argv.index("-o") + 1]
        out.write_text(json.dumps({"results": {"version": 3, "results": rows},
                                   "metadata": {"promptfooVersion": self.version},
                                   "config": config}), encoding="utf-8")
        failed = any(not row["success"] for row in rows)
        return SimpleNamespace(returncode=100 if failed else 0, stdout="", stderr="")


@pytest.fixture
def fake(monkeypatch, tmp_path):
    """A checked promptfoo project (36 labeled answers, version 0.123.1), the project's own
    promptfoo, and a fake behind the one process function."""
    ws = _checked(tmp_path)
    _edit(tmp_path, _version)
    project_promptfoo(tmp_path)
    fp = FakePromptfoo(ws)
    monkeypatch.setattr(again, "run_process", fp)
    monkeypatch.setattr(again, "which", lambda name: None)
    for name in keys.all_names():
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", SECRET)
    return fp


@pytest.fixture
def terminal(monkeypatch):
    answers: list[str] = []
    monkeypatch.setattr(start, "_interactive", lambda: True)

    def fake_input(prompt=""):
        print(prompt)
        return answers.pop(0) if answers else keyboard.enter()

    monkeypatch.setattr(builtins, "input", fake_input)
    return answers


class _Said:
    """The talk a tool's run gets, as `judgekeeper check` gives it: every line kept."""

    quiet = False
    yes = False

    def __init__(self):
        self.lines: list[str] = []

    def say(self, text: str = "") -> None:
        self.lines.append(text)


def ask_again(ws, *argv) -> tuple[int, str]:
    """Ask the judge again about the marked answers, as `judgekeeper check` and `fix` do: the
    plan, the tool's run, and one run file per time asked. `argv` may hold --times N,
    --fields LIST and --python PATH. (exit code, what the run said)."""
    from judgekeeper.again.fresh import AgainError, write_files

    args = [str(a) for a in argv]
    value = {flag: args[args.index(flag) + 1] for flag in
             ("--times", "--fields", "--python") if flag in args}
    options = AgainOptions(times=int(value["--times"]) if "--times" in value else None,
                           fields=value.get("--fields"), python=value.get("--python"))
    plan = make_plan(ws, options, dry=True)
    if plan.status == again.CANT:
        return 0, plan.why
    said = _Said()
    try:
        fresh = again.run_tool(ws, plan, said)
    except AgainError as e:
        return 1, str(e)
    except KeyboardInterrupt:
        return 130, "\n".join(said.lines)
    write_files(ws, plan, fresh)
    return 0, "\n".join(said.lines)


def run(capsys, *argv):
    """`judgekeeper` with `argv`; with --ask-again, the judge asked again (ask_again)."""
    args = [str(a) for a in argv]
    if "--ask-again" in args:
        ws = start_label.Workspace(Path(args[0]))
        code, out = ask_again(ws, *args[1:])
        capsys.readouterr()
        return code, out, ""
    code = main(args)
    out, err = capsys.readouterr()
    return code, out, err


def _again_dir(ws):
    (folder,) = (ws.dir / "again").iterdir()
    return folder


# The two files and the command ---------------------------------------------------------------

def test_the_two_files_follow_promptfoos_shape(fake, capsys):
    ws = fake.ws
    code, _, _ = run(capsys, ws.root, "--ask-again")
    assert code == 0
    config, tests = fake.files_seen["config"], fake.files_seen["tests"]
    assert config == {"description": "judgekeeper re-check (temporary file)",
                      "prompts": ["{{judgekeeper_prompt}}"], "providers": ["echo"],
                      "evaluateOptions": {"cache": False}, "tests": f"file://{TESTS}"}
    assert len(tests) == 36
    raw = {r["id"]: r for r in (json.loads(x) for x in ws.pool.read_text(
        encoding="utf-8").splitlines())}
    for t in tests:
        assert t["description"] in raw
        assert t["providerOutput"] == raw[t["description"]]["output"]
        assert t["vars"]["question"] == raw[t["description"]]["input"]["question"]
        assert "judgekeeper_prompt" in t["vars"]
        assert t["options"]["provider"] == {"id": "openai:gpt-4.1-mini",
                                            "config": {"temperature": 0}}
        assert t["assert"] == [{"type": "llm-rubric",
                                "value": "Is polite and correct.\nSecond line of the rubric."}]


def test_the_command_has_every_flag_and_setting_and_never_grader(fake, capsys):
    ws = fake.ws
    run(capsys, ws.root, "--ask-again")
    (call,) = [c for c in fake.calls if "eval" in c.argv]
    argv = call.argv
    assert argv[:4] == [again.node_bin(ws.root, "promptfoo"), "eval", "-c", CONFIG]
    for flag in ("--no-cache", "--no-write", "--no-share", "--no-table", "--no-progress-bar"):
        assert flag in argv, flag
    assert argv[argv.index("--repeat") + 1] == "2"
    assert "--grader" not in argv
    out = argv[argv.index("-o") + 1]
    assert out.startswith(".judgekeeper/again/") and out.endswith("/promptfoo.json")
    assert call.cwd == ws.root
    for name, value in (("PROMPTFOO_CACHE_ENABLED", "false"),
                        ("PROMPTFOO_DISABLE_TELEMETRY", "1"), ("PROMPTFOO_DISABLE_UPDATE", "1"),
                        ("PROMPTFOO_DISABLE_SHARING", "1"), ("PROMPTFOO_DISABLE_DEBUG_LOG", "1"),
                        ("PROMPTFOO_DISABLE_ERROR_LOG", "1")):
        assert call.env[name] == value, name


def test_the_two_files_are_removed_after_success(fake, capsys):
    run(capsys, fake.ws.root, "--ask-again")
    assert not (fake.ws.root / CONFIG).exists() and not (fake.ws.root / TESTS).exists()


def test_the_two_files_are_removed_after_an_error(fake, capsys):
    fake.code, fake.stderr = 1, f"Error: provider failed with key {SECRET}\n"
    code, out, _ = run(capsys, fake.ws.root, "--ask-again")
    assert code == 1
    assert "promptfoo did not finish: Error: provider failed with key [REDACTED]" in out
    assert SECRET not in out
    assert not (fake.ws.root / CONFIG).exists() and not (fake.ws.root / TESTS).exists()


def test_the_two_files_are_removed_after_ctrl_c(fake, capsys):
    fake.interrupt = True
    code, _out, _ = run(capsys, fake.ws.root, "--ask-again")
    assert code == 130
    assert not (fake.ws.root / CONFIG).exists() and not (fake.ws.root / TESTS).exists()


def test_the_run_says_the_files_before_it_starts(fake, capsys):
    _, out, _ = run(capsys, fake.ws.root, "--ask-again")
    assert (f"Writing {CONFIG} and {TESTS} next to promptfooconfig.yaml; they are removed "
            "when promptfoo is done.") in out


def test_exit_100_is_finished(fake, capsys):
    fake.flips = {(a["id"], 0) for a in again.labeled_answers(fake.ws)[:3]}
    code, out, _ = run(capsys, fake.ws.root, "--ask-again")
    assert code == 0 and "promptfoo did not finish" not in out


# Which promptfoo ---------------------------------------------------------------------------


def test_npx_runs_after_a_yes(fake, capsys, terminal, monkeypatch):
    (fake.ws.root / "node_modules").rename(fake.ws.root / "node_modules-gone")
    monkeypatch.setattr(again, "which", lambda name: "/usr/bin/npx" if name == "npx" else None)
    terminal += ["y", "y"]
    code, _, _ = run(capsys, fake.ws.root, "--ask-again")
    (call,) = [c for c in fake.calls if "eval" in c.argv]
    assert code == 0 and call.argv[:4] == ["/usr/bin/npx", "--yes", "promptfoo@0.123.1", "eval"]


# What it says -------------------------------------------------------------------------------

def test_exactly_your_judge_has_no_close_copy_words(fake, capsys):
    _, out, _ = run(capsys, fake.ws.root, "--ask-again")
    assert "close copy" not in out


# The saved files ----------------------------------------------------------------------------

def test_every_line_carries_the_full_fingerprint(fake, capsys):
    fake.extra = f" (key {SECRET})"
    run(capsys, fake.ws.root, "--ask-again")
    folder = _again_dir(fake.ws)
    assert (folder / "promptfoo.json").is_file()
    runs = sorted(folder.glob("judge-again-*.jsonl"))
    assert [p.name for p in runs] == ["judge-again-1.jsonl", "judge-again-2.jsonl"]
    for path in runs:
        header, records = read_run(path)
        assert header["source"]["kind"] == "promptfoo"
        assert len(records) == 36
        for rec in records.values():
            fp = rec["fingerprint"]
            assert fp["provider"] == "openai" and fp["model"] == "openai:gpt-4.1-mini"
            assert fp["temperature"] == 0.0 and fp["prompt_hash"] and fp["created_at"]
            assert fp["tool"] == "promptfoo" and fp["tool_version"] == "0.123.1"
            assert fp["judge_copy"] == "exact" and fp["judge_copy_why"] == []
            assert fp["settings"] == []
    every = "".join(p.read_text(encoding="utf-8") for p in folder.iterdir())
    every += fake.ws.result_json.read_text(
        encoding="utf-8") + fake.ws.report_html.read_text(encoding="utf-8")
    assert SECRET not in every and "[REDACTED]" in every


def test_setting_names_go_into_the_fingerprint(fake, capsys, monkeypatch):
    monkeypatch.setenv("OPENAI_TEMPERATURE", "0.9")
    run(capsys, fake.ws.root, "--ask-again")
    _, records = read_run(_again_dir(fake.ws) / "judge-again-1.jsonl")
    assert all(r["fingerprint"]["settings"] == ["OPENAI_TEMPERATURE"] for r in records.values())


def test_the_main_result_does_not_change(fake, capsys):
    before = json.loads(fake.ws.result_json.read_text(encoding="utf-8"))
    labels = fake.ws.marks.read_bytes()
    run(capsys, fake.ws.root, "--ask-again")
    after = json.loads(fake.ws.result_json.read_text(encoding="utf-8"))
    for key in ("tpr", "tnr", "kappa", "made_at", "labels"):
        assert after[key] == before[key]
    assert fake.ws.marks.read_bytes() == labels


# The real promptfoo (optional) -----------------------------------------------------------------

@pytest.mark.skipif(shutil.which("promptfoo") is None, reason="promptfoo is not installed")
def test_a_real_regrade_matches_every_grading_prompt(tmp_path, monkeypatch):
    real = FIXTURES / "promptfoo" / "real"
    project = tmp_path / "real"
    shutil.copytree(real, project)
    (project / "labels.csv").unlink()
    ws = start_label.prepare(start.find_judge(project), say=_quiet)
    session = StartSession(ws)
    for q in ws.data()["queue"]:
        session.update({"id": q["id"], "label": q["group"]})
    save_result(ws, session, say=_quiet)
    monkeypatch.setattr(pf, "_code", lambda values: False)  # the fake grader is exec: code
    plan = make_plan(ws, AgainOptions(times=1))
    assert plan.status != "cant", plan.why
    fresh = pf.run(ws, plan, start.Talk(quiet=True))
    assert fresh.not_counted == {}
    assert len(fresh.verdicts) == plan.answers
