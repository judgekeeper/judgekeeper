"""A project's `.env` and `.npmrc` can't point the judge's calls, or the key, anywhere else.

When judgekeeper asks a judge again, the eval tool reads no `.env` of the project: promptfoo
and npx run from a new folder outside the project, Inspect AI's `.env` loader is not called and
DeepEval's is switched off. judgekeeper passes on from `.env` only the API key names, read as
dotenv reads them. The fakes here do what the real tools do with their working folder: promptfoo
loads `<cwd>/.env` (dotenv, no override), npm reads the `.npmrc` next to the nearest
`package.json` up from its working folder. No test calls an AI API.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

from judgekeeper import again, keys
from judgekeeper.again import AgainOptions, make_plan
from judgekeeper.again.fresh import write_files
from tests.start_projects import deepeval_project, inspect_project, project_promptfoo
from tests.test_again_python_run import _checked as _python_checked
from tests.test_again_python_run import _saved
from tests.test_again_run import FakePromptfoo, _checked, _edit, _Said

KEY = "sk-test-FROMdotENVthatMUSTbeSCRUBBED0123456789"
PORT_URL = "http://127.0.0.1:9/v1"
OWN = "https://api.openai.com/v1"  # where the judge's calls go when nothing redirects them
MARKER = "ZQ-NODE-RAN.txt"
# dotenv 17's line (lib/main.js), as promptfoo, Inspect AI and DeepEval read a .env
DOTENV = re.compile(r"^\s*(?:export\s+)?([\w.-]+)(?:\s*=\s*?|:\s+?)(\s*'(?:\\'|[^'])*'|"
                    r"\s*\"(?:\\\"|[^\"])*\"|\s*`(?:\\`|[^`])*`|[^#\r\n]+)?\s*(?:#.*)?$", re.MULTILINE)


def _dotenv(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    found = {}
    for m in DOTENV.finditer(path.read_text(encoding="utf-8")):
        found[m[1]] = (m[2] or "").strip().strip("'\"`")
    return found


class Tools:
    """The fake promptfoo, with what the real promptfoo and npm do with their working folder:
    `seen` holds, per eval, the environment promptfoo ended up with; `registry` each npm
    registry asked; `ran` each NODE_OPTIONS file node loaded."""

    def __init__(self, fake: FakePromptfoo):
        self.fake, self.seen, self.registry, self.ran = fake, [], [], []

    def __call__(self, argv, cwd, env=None, timeout=None):
        cwd, env = Path(cwd), dict(env or {})
        if Path(argv[0]).name == "npx":
            npmrc = self._npmrc(cwd)
            if npmrc.get("registry"):
                self.registry.append(npmrc["registry"])
            if "--require" in npmrc.get("node-options", ""):
                self.ran.append(npmrc["node-options"])
                (cwd / MARKER).write_text("ran", encoding="utf-8")
        if "eval" in argv:
            self.seen.append({**_dotenv(cwd / ".env"), **env})  # dotenv does not override
        return self.fake(argv, cwd, env, timeout)

    @staticmethod
    def _npmrc(cwd: Path) -> dict[str, str]:
        for folder in (cwd, *cwd.resolve().parents):
            if (folder / "package.json").is_file():
                rc = folder / ".npmrc"
                if not rc.is_file():
                    return {}
                return dict(line.split("=", 1) for line in rc.read_text(
                    encoding="utf-8").splitlines() if "=" in line)
        return {}

    def calls_go_to(self) -> set[str]:
        return {e.get("OPENAI_BASE_URL") or OWN for e in self.seen}


@pytest.fixture
def tools(monkeypatch, tmp_path):
    """A checked promptfoo project (its own promptfoo, results from 0.123.1), no key in the
    shell, and the fakes behind the one process function."""
    ws = _checked(tmp_path)
    _edit(tmp_path, lambda d: d.setdefault("metadata", {}).update(promptfooVersion="0.123.1"))
    project_promptfoo(tmp_path)
    t = Tools(FakePromptfoo(ws))
    monkeypatch.setattr(again, "run_process", t)
    monkeypatch.setattr(again, "which", lambda name, *a, **k: None)
    for name in keys.all_names() | {"AWS_CONFIG_FILE", "DATABASE_URL", "SECRET_KEY"}:
        monkeypatch.delenv(name, raising=False)
    return t


def _ask(ws) -> tuple[again.Plan, str]:
    plan = make_plan(ws, AgainOptions(), dry=True)
    assert plan.status != again.CANT, plan.why
    said = _Said()
    fresh = again.run_tool(ws, plan, said)
    write_files(ws, plan, fresh)
    return plan, "\n".join(said.lines)


def _written(ws) -> str:
    return "".join(p.read_text(encoding="utf-8", errors="replace")
                   for p in ws.dir.rglob("*") if p.is_file())


# The names in a .env, as dotenv reads them ----------------------------------------------------

def test_a_colon_line_is_a_name_too(tmp_path):
    (tmp_path / ".env").write_text(f"OPENAI_BASE_URL: {PORT_URL}\n"
                                   f"export ANTHROPIC_BASE_URL: {PORT_URL}\n"
                                   "no colon or equals\nTIME:10\n", encoding="utf-8")
    assert keys.names_in(tmp_path / ".env") == {"OPENAI_BASE_URL", "ANTHROPIC_BASE_URL"}


def test_a_colon_line_is_named_in_the_plan(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", KEY)
    (tmp_path / ".env").write_text(f"OPENAI_BASE_URL: {PORT_URL}\n", encoding="utf-8")
    k = keys.check("openai:gpt-4.1-mini", "promptfoo", tmp_path)
    assert k.not_passed == ["OPENAI_BASE_URL"]
    assert any(x.startswith("OPENAI_BASE_URL is set in .env, which judgekeeper does not pass on")
               for x in k.lines)


def test_values_are_read_as_dotenv_reads_them_and_only_for_the_names_asked(tmp_path):
    (tmp_path / ".env").write_text(
        "# a comment\n"
        "A=plain # a note\n"
        "B: colon\n"
        "export C=exported\n"
        "D='single # kept'\n"
        'E="two\\nlines"\n'
        'F="really\nover lines"\n'
        "G = spaced \n"
        "H=first\nH=last\n"
        "OTHER=never kept\n", encoding="utf-8")
    got = keys.env_values(tmp_path / ".env", {"A", "B", "C", "D", "E", "F", "G", "H", "X"})
    assert got == {"A": "plain", "B": "colon", "C": "exported", "D": "single # kept",
                   "E": "two\nlines", "F": "really\nover lines", "G": "spaced", "H": "last"}


# promptfoo ------------------------------------------------------------------------------------

@pytest.mark.parametrize("lines", [
    [f"OPENAI_API_KEY: {KEY}", f"OPENAI_BASE_URL: {PORT_URL}"],
    [f"OPENAI_API_KEY={KEY}", f"export OPENAI_BASE_URL={PORT_URL}"],
    [f"OPENAI_API_KEY={KEY}", "AWS_CONFIG_FILE=./aws.cfg"],
    [f"export OPENAI_API_KEY: '{KEY}'", "GOOGLE_APPLICATION_CREDENTIALS=./gcp.json",
     "GOOGLE_EXTERNAL_ACCOUNT_ALLOW_EXECUTABLES=1"],
])
def test_a_dotenv_never_redirects_promptfoo_and_its_key_is_still_passed(tools, lines):
    ws = tools.fake.ws
    (ws.root / ".env").write_text("\n".join(lines) + "\n", encoding="utf-8")
    tools.fake.extra = f" {KEY}"  # a reason that quotes the key
    _, said = _ask(ws)
    assert tools.seen and tools.calls_go_to() == {OWN}
    for env in tools.seen:
        assert env["OPENAI_API_KEY"] == KEY
        for name in ("AWS_CONFIG_FILE", "GOOGLE_APPLICATION_CREDENTIALS",
                     "GOOGLE_EXTERNAL_ACCOUNT_ALLOW_EXECUTABLES"):
            assert name not in env, name
    assert KEY not in said and KEY not in _written(ws)
    assert "[REDACTED]" in _written(ws)


def test_a_dotenv_with_app_settings_is_still_asked(tools):
    ws = tools.fake.ws
    (ws.root / ".env").write_text(f"DATABASE_URL=postgres://u:p@db.example/app\n"
                                  f"SECRET_KEY=app-secret\nOPENAI_API_KEY={KEY}\n",
                                  encoding="utf-8")
    _ask(ws)
    assert len(tools.seen) == 1
    assert "DATABASE_URL" not in tools.seen[0] and "SECRET_KEY" not in tools.seen[0]
    assert tools.seen[0]["OPENAI_API_KEY"] == KEY


def test_a_shell_key_wins_over_the_dotenv_one(tools, monkeypatch):
    ws = tools.fake.ws
    monkeypatch.setenv("OPENAI_API_KEY", "sk-shell-" + "x" * 30)
    (ws.root / ".env").write_text(f"OPENAI_API_KEY={KEY}\nDATABASE_URL=postgres://db/app\n",
                                  encoding="utf-8")
    _ask(ws)
    assert tools.seen[0]["OPENAI_API_KEY"] == "sk-shell-" + "x" * 30


def test_promptfoo_runs_from_a_new_folder_outside_the_project(tools):
    ws = tools.fake.ws
    (ws.root / ".env").write_text(f"OPENAI_API_KEY={KEY}\n", encoding="utf-8")
    _ask(ws)
    folders = [c.cwd for c in tools.fake.calls]
    assert len(folders) == 2  # --version, then eval
    for folder in folders:
        assert not folder.resolve().is_relative_to(ws.root.resolve())
        assert not folder.exists()  # removed afterwards
    (call,) = [c for c in tools.fake.calls if "eval" in c.argv]
    for flag in ("-c", "-o"):
        assert Path(call.argv[call.argv.index(flag) + 1]).is_absolute(), flag


@pytest.mark.parametrize("npmrc", ["registry=http://127.0.0.1:9/\n",
                                   "node-options=--require ./x.js\nprefer-offline=true\n"])
def test_a_project_npmrc_never_steers_npx(tools, monkeypatch, npmrc):
    ws = tools.fake.ws
    _edit(ws.root, lambda d: d["metadata"].update(promptfooVersion="0.124.0"))
    monkeypatch.setattr(again, "which", lambda name, *a, **k: (
        str(Path(sys.prefix) / "fake-bin" / "npx") if name == "npx" else None))
    (ws.root / "package.json").write_text("{}", encoding="utf-8")
    (ws.root / ".npmrc").write_text(npmrc, encoding="utf-8")
    (ws.root / ".env").write_text(f"OPENAI_API_KEY={KEY}\n", encoding="utf-8")
    plan, _ = _ask(ws)
    assert plan.download and Path(plan.runner[0]).name == "npx"
    assert [c for c in tools.fake.calls if "eval" in c.argv]
    assert tools.registry == [] and tools.ran == []
    assert not list(ws.root.rglob(MARKER))


# Inspect AI and DeepEval ----------------------------------------------------------------------

def _python_ask(ws, *argv):
    from tests.test_again_run import ask_again

    return ask_again(ws, "--python", sys.executable, *argv)


@pytest.fixture
def no_shell_key(monkeypatch):
    for name in keys.all_names():
        monkeypatch.delenv(name, raising=False)


def _redirecting_env(root: Path) -> None:
    (root / ".env").write_text(f"OPENAI_API_KEY={KEY}\nOPENAI_BASE_URL={PORT_URL}\n"
                               "DATABASE_URL=postgres://u:p@db.example/app\n", encoding="utf-8")


def _openai_grader(data):
    data["eval"]["model_roles"] = {"grader": {"model": "openai/gpt-4.1-mini", "config": {}}}


def test_inspect_gets_only_the_key_from_the_dotenv(tmp_path, stubs, no_shell_key,
                                                   monkeypatch):
    from tests.test_again_tools import _inspect_log

    ws = _python_checked(tmp_path, inspect_project)
    _inspect_log(tmp_path, _openai_grader)
    stubs.plan(verdicts=_saved(ws))
    _redirecting_env(tmp_path)
    given = []
    real = again.start_worker

    def spy(tool, python, job, cwd, out_path, env=None, drop=(), timeout=None):
        given.append(dict(env or {}))
        return real(tool, python, job, cwd, out_path, env=env, drop=drop, timeout=timeout)

    monkeypatch.setattr(again, "start_worker", spy)
    code, out = _python_ask(ws)
    assert code == 0, out
    assert stubs("dotenv") == []  # Inspect's own loader is never called
    calls = stubs("call_env")
    assert calls and {c["base_url"] for c in calls} == {None}
    assert {c["key"] for c in calls} == {KEY}
    assert given and given[-1] == {"OPENAI_API_KEY": KEY}


def test_deepeval_gets_only_the_key_from_the_dotenv(tmp_path, stubs, no_shell_key):
    ws = _python_checked(tmp_path, deepeval_project)
    stubs.plan(verdicts=_saved(ws))
    _redirecting_env(tmp_path)
    code, out = _python_ask(ws, "--fields", "input,actual_output")
    assert code == 0, out
    calls = stubs("call_env")
    assert calls and {c["base_url"] for c in calls} == {None}
    assert {c["key"] for c in calls} == {KEY}


def test_the_key_comes_from_each_tools_own_files_in_its_order(tmp_path, no_shell_key,
                                                            monkeypatch):
    monkeypatch.setenv("APP_ENV", "staging")
    (tmp_path / ".env").write_text("OPENAI_API_KEY=sk-from-dotenv-" + "a" * 20 + "\n"
                                   "MISTRAL_API_KEY=sk-mistral-" + "c" * 20 + "\n",
                                   encoding="utf-8")
    (tmp_path / ".env.staging").write_text("OPENAI_API_KEY=sk-from-staging-" + "b" * 20 + "\n",
                                           encoding="utf-8")
    (tmp_path / ".env.local").write_text(f"OPENAI_API_KEY={KEY}\n", encoding="utf-8")
    names = {"OPENAI_API_KEY", "MISTRAL_API_KEY"}
    assert keys.passed_on("deepeval", tmp_path, names) == {
        "OPENAI_API_KEY": KEY, "MISTRAL_API_KEY": "sk-mistral-" + "c" * 20}
    assert keys.passed_on("promptfoo", tmp_path, names)["OPENAI_API_KEY"].startswith(
        "sk-from-dotenv-")
    inner = tmp_path / "evals"
    inner.mkdir()
    assert keys.passed_on("inspect", inner, {"OPENAI_API_KEY"}) == {
        "OPENAI_API_KEY": "sk-from-dotenv-" + "a" * 20}  # the nearest .env upward
    monkeypatch.setenv("OPENAI_API_KEY", "sk-shell-" + "x" * 30)
    assert keys.passed_on("deepeval", tmp_path, names) == {
        "MISTRAL_API_KEY": "sk-mistral-" + "c" * 20}  # the shell's own wins


# Settings in .env that change the judge -------------------------------------------------------

@pytest.mark.parametrize(("line", "passed"), [
    ("OPENAI_TEMPERATURE=0.2", "0.2"), ("OPENAI_MAX_TOKENS: 300", "300"),
    ("OPENAI_TEMPERATURE='1'", "1")])
def test_a_plain_number_setting_for_the_grader_is_passed_on(tools, line, passed):
    ws = tools.fake.ws
    (ws.root / ".env").write_text(f"OPENAI_API_KEY={KEY}\n{line}\n", encoding="utf-8")
    plan, _ = _ask(ws)
    name = line.split("=")[0].split(":")[0]
    assert tools.seen[0][name] == passed
    assert plan.status == again.EXACT and plan.settings == [name]


@pytest.mark.parametrize("line", ["OPENAI_TEMPERATURE=0.2; curl x", "OPENAI_TEMPERATURE=$X",
                                  "ANTHROPIC_TEMPERATURE=0.5"])
def test_any_other_number_setting_is_not_passed_on(tools, line):
    ws = tools.fake.ws
    (ws.root / ".env").write_text(f"OPENAI_API_KEY={KEY}\n{line}\n", encoding="utf-8")
    _ask(ws)
    assert line.split("=")[0] not in tools.seen[0]


@pytest.mark.parametrize("line", [f"OPENAI_BASE_URL: {PORT_URL}", "OPENAI_API_HOST=x.example",
                                  "OPENAI_TEMPERATURE=hot", "HTTPS_PROXY=http://127.0.0.1:9"])
def test_a_dotenv_setting_not_passed_on_makes_a_close_copy_and_is_named(tools, line):
    ws = tools.fake.ws
    name = line.split("=")[0].split(":")[0]
    (ws.root / ".env").write_text(f"OPENAI_API_KEY={KEY}\n{line}\n", encoding="utf-8")
    plan = make_plan(ws, AgainOptions(), dry=True)
    assert plan.status == again.CLOSE
    assert f"your .env sets {name}, which judgekeeper does not pass on" in plan.why
    said = " ".join(plan.key_lines)
    assert (f"{name} is set in .env, which judgekeeper does not pass on: your LLM-as-a-judge is "
            f"asked without it. To use it, set it in your shell.") in said
    assert "it changes your LLM-as-a-judge" not in said and name not in plan.settings


def test_a_setting_in_the_shell_is_still_used_and_named(tools, monkeypatch):
    ws = tools.fake.ws
    monkeypatch.setenv("OPENAI_BASE_URL", OWN)
    (ws.root / ".env").write_text(f"OPENAI_API_KEY={KEY}\nOPENAI_BASE_URL={PORT_URL}\n",
                                  encoding="utf-8")
    plan, _ = _ask(ws)
    assert plan.status == again.EXACT and plan.settings == ["OPENAI_BASE_URL"]
    assert "OPENAI_BASE_URL is set; it changes your LLM-as-a-judge." in plan.key_lines
    assert tools.calls_go_to() == {OWN}


def test_an_inspect_dotenv_setting_makes_a_close_copy_that_stays_one(tmp_path, stubs,
                                                                     no_shell_key):
    from tests.test_again_tools import _inspect_log

    ws = _python_checked(tmp_path, inspect_project)
    _inspect_log(tmp_path, _openai_grader)
    stubs.plan(verdicts=_saved(ws))
    _redirecting_env(tmp_path)
    plan = make_plan(ws, AgainOptions(python=sys.executable), dry=True)
    assert plan.status == again.CLOSE
    assert "your .env sets OPENAI_BASE_URL, which judgekeeper does not pass on" in plan.why
    again.run_tool(ws, plan, _Said())
    assert plan.status == again.CLOSE  # matching prompts don't make it exactly your judge


def test_a_deepeval_dotenv_setting_makes_a_close_copy(tmp_path, stubs, no_shell_key):
    ws = _python_checked(tmp_path, deepeval_project)
    stubs.plan(verdicts=_saved(ws))
    (tmp_path / ".env.local").write_text(f"OPENAI_API_KEY={KEY}\nOPENAI_BASE_URL={PORT_URL}\n",
                                         encoding="utf-8")
    plan = make_plan(ws, AgainOptions(python=sys.executable, fields="input,actual_output"),
                     dry=True)
    assert plan.status == again.CLOSE
    assert "your .env sets OPENAI_BASE_URL, which judgekeeper does not pass on" in plan.why
