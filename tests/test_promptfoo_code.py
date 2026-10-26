"""A promptfoo judge is asked again only with values that can't make promptfoo run code: no
saved prompt, answer, var, rule or grader setting that loads a file, a package or a program,
no template code where promptfoo fills templates in, and no grader setting outside a list
known to be safe. `fix --yes` and `check --yes` refuse such a project (or leave the answer
out) before any call, and a fake promptfoo that runs what the real one would run leaves no
marker. The template code here only does sums: none of it could run anything. Made-up data
only; no test calls an AI API.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from judgekeeper import again
from judgekeeper.again import AgainOptions, make_plan
from judgekeeper.again import promptfoo as pf
from judgekeeper.again.fresh import AgainError
from tests import test_check, test_fix
from tests.start_projects import promptfoo_project
from tests.test_again_plan import _checked, _edit, _rows
from tests.test_fix import here, judge  # noqa: F401

CODE_VALUES = ["file://evil.js", "FILE://evil.js", "package:x", "exec:x", "python:x.py"]
MARKER = "ZQ-PWNED.txt"
OWN_CODE = "your LLM-as-a-judge runs your own code"
UNKNOWN = "its setting `mcp` is not one judgekeeper knows is safe"
MCP = [({"enabled": True, "server": {"command": "/bin/sh", "args": ["-c", "echo ran"]}}, UNKNOWN),
       ({"enabled": True, "server": {"path": "server.js"}}, UNKNOWN),
       ({"enabled": True, "servers": [{"command": "/bin/sh"}, {"path": "s.py"}]}, UNKNOWN),
       ({"enabled": True, "server": {"url": "http://127.0.0.1:9/mcp"}},
        "(url in your grader's settings)")]
ALLOWED = {"temperature": 0, "max_tokens": 300, "maxTokens": 300, "max_completion_tokens": 300,
           "top_p": 1, "topP": 0.5, "top_k": 40, "topK": 40, "seed": 7, "presence_penalty": 0,
           "frequency_penalty": 0, "reasoning_effort": "low", "apiKeyEnvar": "OPENAI_API_KEY",
           "apiVersion": "2024-10-21", "organization": "org-123", "region": "us-east-1",
           "projectId": "my-project-1", "location": "us-central1"}
# Template code, from parts: more than a name inside {{ }}, a tag, a comment
OPEN, CLOSE = "{" + "{", "}" + "}"
SUM = f"{OPEN} 6 * 7 {CLOSE}"
TEMPLATES = [SUM, "{" + "% if true %" + "}x{" + "% endif %" + "}", "{" + "# note #" + "}",
             f"{OPEN} question | upper {CLOSE}", f"Hi {OPEN} env.HOME {CLOSE}"]
FILLED = re.compile(r"\{\{\s*[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*\s*\}\}")


def _strings(value):
    """Every string promptfoo would read in a test, in its vars, answer, options and
    assertions."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from _strings(v)


def _template_code(text: str) -> bool:
    return "{%" in text or "{#" in text or "{{" in FILLED.sub("", text)


def _runs_code(test: dict) -> bool:
    """What promptfoo would run in `test`: a value that loads a file or a package, a grader's
    MCP server, or template code anywhere promptfoo fills templates in (not the answer)."""
    grader = (test.get("options") or {}).get("provider")
    mcp = isinstance(grader, dict) and "mcp" in (grader.get("config") or {})
    filled = {k: v for k, v in test.items() if k != "providerOutput"}
    return (mcp or any(s.strip().lower().startswith(pf.CODE_PREFIXES) for s in _strings(test))
            or any(_template_code(s) for s in _strings(filled)))


def _wrap(monkeypatch) -> dict:
    """promptfoo, as far as code goes: an eval whose tests would run code writes MARKER, as
    evil.js or an MCP server would. Wraps the fake already in place; counts the grading calls
    each eval makes."""
    inner = again.run_process
    holder = {"graded": 0}

    def runner(argv, cwd, env=None, timeout=None):
        if "eval" in argv:
            config = json.loads((Path(cwd) / argv[argv.index("-c") + 1]).read_text(
                encoding="utf-8"))
            tests = json.loads((Path(cwd) / config["tests"].removeprefix("file://"))
                               .read_text(encoding="utf-8"))
            if any(_runs_code(t) for t in tests):
                (Path(cwd) / MARKER).write_text("ran", encoding="utf-8")
            repeat = int(argv[argv.index("--repeat") + 1])
            holder["graded"] += repeat * sum(len(t["assert"]) for t in tests)
        return inner(argv, cwd, env, timeout)

    monkeypatch.setattr(again, "run_process", runner)
    return holder


def _flat(out: str) -> str:
    return " ".join(out.split())


def _stated(out: str) -> int:
    return int(re.search(r"(\d+) AI calls?", _flat(out))[1])


# fix --yes ------------------------------------------------------------------------------------

@pytest.fixture
def runs(judge, monkeypatch):  # noqa: F811
    return _wrap(monkeypatch)


@pytest.fixture
def fixing(here, capsys, judge, runs):  # noqa: F811
    """A fix project after the first run, with a new rule in rule.txt."""
    ws = test_fix.project(here)
    test_fix.run(capsys)
    (ws.dir / "fix" / "rule.txt").write_text(test_fix.NEW_RULE, encoding="utf-8")
    return ws




def _refused(code, out, judge, here, said=OWN_CODE):  # noqa: F811
    assert code == 3, out
    assert judge["evals"] == 0
    assert not (here / MARKER).exists()
    assert said in _flat(out)
    assert "AI calls" not in out


@pytest.mark.parametrize("value", CODE_VALUES)
def test_fix_never_hands_on_a_saved_prompt_that_loads_code(here, capsys, judge,  # noqa: F811
                                                           fixing, value):
    _edit(here, _rows(lambda row: row["prompt"].update(raw=value)))
    code, out = test_fix.run(capsys, "--yes")
    _refused(code, out, judge, here, f"{OWN_CODE} (a saved prompt that loads a file or script)")


@pytest.mark.parametrize("value", CODE_VALUES)
def test_fix_never_hands_on_an_answer_that_loads_code(here, capsys, judge,  # noqa: F811
                                                      runs, monkeypatch, value):
    monkeypatch.setattr(test_fix, "_outputs", lambda n=test_fix.N: [value] * n)
    ws = test_fix.project(here)
    test_fix.run(capsys)
    (ws.dir / "fix" / "rule.txt").write_text(test_fix.NEW_RULE, encoding="utf-8")
    code, out = test_fix.run(capsys, "--yes")
    _refused(code, out, judge, here)


def _grader(here, grader, name="results.json"):  # noqa: F811
    _edit(here, _rows(lambda row: row["testCase"]["options"].update(provider=grader)), name)


@pytest.mark.parametrize(("mcp", "said"), MCP)
def test_fix_never_hands_on_a_grader_with_an_mcp_server(here, capsys, judge,  # noqa: F811
                                                        fixing, mcp, said):
    _grader(here, {"id": "openai:chat:gpt-4.1-mini", "config": {"temperature": 0, "mcp": mcp}})
    code, out = test_fix.run(capsys, "--yes")
    _refused(code, out, judge, here, said)


def _assertions(change):
    def each(row):
        for c in row["gradingResult"]["componentResults"]:
            change(c["assertion"])
    return _rows(each)


# Each door promptfoo fills templates in: the saved prompt and a var (below) leave the answer
# out (all of them here), the grader, the rule and the rubric prompt refuse the judge
DOORS = {
    "prompt": lambda root: _edit(root, _rows(lambda row: row["prompt"].update(raw=SUM))),
    "grader": lambda root: _grader(root, {"id": "openai:chat:gpt-4.1-mini", "label": SUM}),
    "rule": lambda root: _edit(root, _assertions(lambda a: a.update(value=f"Be kind. {SUM}"))),
    "rubric": lambda root: _edit(root, _rows(
        lambda row: row["testCase"]["options"].update(rubricPrompt=f"Grade: {SUM}"))),
}


def _with_var(module, monkeypatch):
    """Every answer `module` makes has a var holding template code, from the start: a var
    added later would make them other answers."""
    made = module.promptfoo_data

    def data(*args, **kwargs):
        d = made(*args, **kwargs)
        for row in d["results"]["results"]:
            row["vars"]["topic"] = row["testCase"]["vars"]["topic"] = SUM
        return d
    monkeypatch.setattr(module, "promptfoo_data", data)


def test_fix_never_hands_on_a_var_with_template_code(here, capsys, judge,  # noqa: F811
                                                     runs, monkeypatch):
    _with_var(test_fix, monkeypatch)
    ws = test_fix.project(here)
    test_fix.run(capsys)
    (ws.dir / "fix" / "rule.txt").write_text(test_fix.NEW_RULE, encoding="utf-8")
    code, out = test_fix.run(capsys, "--yes")
    assert code == 3, out
    assert judge["evals"] == 0 and not (here / MARKER).exists()
    assert "template text" in _flat(out)


@pytest.mark.parametrize("door", DOORS)
def test_fix_never_hands_on_template_code(here, capsys, judge, fixing, door):  # noqa: F811
    DOORS[door](here)
    code, out = test_fix.run(capsys, "--yes")
    assert code == 3, out
    assert judge["evals"] == 0 and not (here / MARKER).exists()
    assert "AI calls" not in out


@pytest.mark.parametrize("grader", [{"text": "anthropic:claude-agent-sdk"},
                                    {"text": "https://example.invalid/x"}])
def test_fix_never_hands_on_a_grader_by_output_type(here, capsys, judge,  # noqa: F811
                                                    fixing, grader):
    _grader(here, grader)
    code, out = test_fix.run(capsys, "--yes")
    assert code == 3, out
    assert judge["evals"] == 0 and "AI calls" not in out


def _node(monkeypatch) -> None:
    """promptfoo's start, as far as its environment goes: node loads the file that
    NODE_OPTIONS names with --require, as the real one would, which writes MARKER."""
    inner = again.run_process

    def runner(argv, cwd, env=None, timeout=None):
        if "--require" in (env or {}).get("NODE_OPTIONS", ""):
            (Path(cwd) / MARKER).write_text("ran", encoding="utf-8")
        return inner(argv, cwd, env, timeout)

    monkeypatch.setattr(again, "run_process", runner)


def _env_block(root, *lines):
    config = root / "promptfooconfig.yaml"
    config.write_text(config.read_text(encoding="utf-8") + "env:\n"
                      + "".join(f"  {line}\n" for line in lines), encoding="utf-8")


@pytest.mark.parametrize(("line", "name"), [
    ("NODE_OPTIONS: --require ./x.js", "NODE_OPTIONS"), ("PATH: ./bin", "PATH"),
    ("OPENAI_BASE_URL: https://example.invalid/v1", "OPENAI_BASE_URL"),
    ("OPENAI_TEMPERATURE: '0'", "OPENAI_TEMPERATURE"),
])
def test_fix_refuses_a_config_env_it_does_not_pass_on(here, capsys, judge,  # noqa: F811
                                                       fixing, monkeypatch, line, name):
    _node(monkeypatch)
    _env_block(here, "OPENAI_API_KEY: sk-config-0123456789abcdef", line)
    code, out = test_fix.run(capsys, "--yes")
    _refused(code, out, judge, here,
             f"its config sets `{name}`, which judgekeeper does not pass on")


@pytest.mark.parametrize("name", ["OPENAI_BASE_URL", "ANTHROPIC_API_BASE", "NODE_OPTIONS",
                                  "PATH", "DYLD_INSERT_LIBRARIES", "npm_config_registry",
                                  "HTTPS_PROXY", "AZURE_OPENAI_API_HOST", "MY_ENDPOINT",
                                  "COMSPEC", "SHELL", "BASH_ENV", "ENV", "PYTHONPATH",
                                  "PYTHONSTARTUP"])
def test_fix_refuses_a_dotenv_that_redirects_promptfoo(here, capsys, judge,  # noqa: F811
                                                         fixing, name):
    (here / ".env").write_text(f"OPENAI_API_KEY=x\nexport {name}=x\n", encoding="utf-8")
    code, out = test_fix.run(capsys, "--yes")
    _refused(code, out, judge, here, f"your .env sets `{name}`")


@pytest.mark.parametrize("name", ["NO_PROXY", "no_proxy"])
def test_fix_still_asks_with_a_dotenv_that_only_skips_a_proxy(here, capsys, judge,  # noqa: F811
                                                              fixing, runs, name):
    (here / ".env").write_text(f"OPENAI_API_KEY=x\n{name}=localhost\n", encoding="utf-8")
    code, out = test_fix.run(capsys, "--yes")
    assert code == 0, out
    assert judge["evals"] == 2


def test_fix_still_asks_a_grader_with_only_known_settings(here, capsys, judge,  # noqa: F811
                                                          fixing, runs):
    _grader(here, {"id": "openai:chat:gpt-4.1-mini", "label": "grader", "config": ALLOWED})
    code, out = test_fix.run(capsys, "--yes")
    assert code == 0, out
    assert judge["evals"] == 2
    assert runs["graded"] == _stated(out)
    assert not (here / MARKER).exists()


# check --yes ----------------------------------------------------------------------------------

@pytest.fixture
def checking(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def asked(checking, monkeypatch):
    """test_check's judge: the project's own promptfoo (the fake) and a key in the shell."""
    from judgekeeper import keys
    from judgekeeper.start_label import Workspace
    from tests.start_projects import project_promptfoo
    from tests.test_again_run import FakePromptfoo

    project_promptfoo(checking)
    for name in keys.all_names():
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "x" * 30)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "y" * 30)
    monkeypatch.setattr(again, "which", lambda name: None)
    holder = {}

    def runner(argv, cwd, env=None, timeout=None):
        if "fake" not in holder:
            holder["fake"] = FakePromptfoo(Workspace(checking), version="0.124.1")
        return holder["fake"](argv, cwd, env, timeout)

    monkeypatch.setattr(again, "run_process", runner)
    return holder


@pytest.fixture
def check_runs(asked, monkeypatch):
    return _wrap(monkeypatch)


def _changed_judge(root, **kwargs):
    """A marked project whose newest results come from another judge: check asks it again."""
    test_check._marked(root, **kwargs)
    test_check._results(root, test_check.LENIENT, model=test_check.HAIKU,
                        outputs=test_check._new_outputs())


def _check_refused(capsys, root, holder, said=OWN_CODE):
    code, out = test_check.run(capsys, "--yes")
    assert code == 3, out
    assert test_check._evals(holder) == 0
    assert not (root / MARKER).exists()
    assert said in _flat(out)
    assert "AI calls" not in out


@pytest.mark.parametrize("value", CODE_VALUES)
def test_check_never_hands_on_a_saved_prompt_that_loads_code(checking, capsys, asked,
                                                             check_runs, value):
    _changed_judge(checking)
    _edit(checking, _rows(lambda row: row["prompt"].update(raw=value)))
    _check_refused(capsys, checking, asked,
                   f"{OWN_CODE} (a saved prompt that loads a file or script)")


@pytest.mark.parametrize("value", CODE_VALUES)
def test_check_never_hands_on_an_answer_that_loads_code(checking, capsys, asked, check_runs,
                                                        value):
    _changed_judge(checking, outputs=[value] * 50)
    _check_refused(capsys, checking, asked)


@pytest.mark.parametrize(("mcp", "said"), MCP)
def test_check_never_hands_on_a_grader_with_an_mcp_server(checking, capsys, asked, check_runs,
                                                          mcp, said):
    _changed_judge(checking)
    _grader(checking, {"id": test_check.HAIKU, "config": {"mcp": mcp}})
    _check_refused(capsys, checking, asked, said)


def test_check_never_hands_on_a_var_with_template_code(checking, capsys, asked, check_runs,
                                                       monkeypatch):
    _with_var(test_check, monkeypatch)
    _changed_judge(checking)
    code, out = test_check.run(capsys, "--yes")
    assert code == 3, out
    assert test_check._evals(asked) == 0 and not (checking / MARKER).exists()
    assert "template text" in _flat(out)


@pytest.mark.parametrize("door", DOORS)
def test_check_never_hands_on_template_code(checking, capsys, asked, check_runs, door):
    _changed_judge(checking)
    DOORS[door](checking)
    code, out = test_check.run(capsys, "--yes")
    assert code == 3, out
    assert test_check._evals(asked) == 0 and not (checking / MARKER).exists()


# The plan: which grader settings are known ----------------------------------------------------

@pytest.mark.parametrize(("grader", "key"), [
    *[({"id": "openai:chat:gpt-4.1-mini", "config": {"mcp": m}}, "mcp") for m, _ in MCP[:3]],
    ({"id": "openai:chat:gpt-4.1-mini", "config": {"tools": [{"type": "function"}]}}, "tools"),
    ({"id": "openai:chat:gpt-4.1-mini", "config": {"zq_new_setting": 1}}, "zq_new_setting"),
    ({"id": "openai:chat:gpt-4.1-mini", "config": {"headers": {"X-A": "b"}}}, "headers"),
    ({"id": "openai:chat:gpt-4.1-mini", "env": {"OPENAI_API_KEY": "x"}}, "env"),
    ({"id": "openai:chat:gpt-4.1-mini", "prompts": ["p"]}, "prompts"),
    ({"text": {"id": "openai:chat:gpt-4.1-mini", "config": {"mcp": MCP[0][0]}}}, "mcp"),
    ({"zq": {"id": "openai:chat:gpt-4.1-mini"}}, "zq"),
    ({"id": "openai:chat:gpt-4.1-mini", "text": "openai:chat:gpt-4.1"}, "text"),
    ({"id": "openai:chat:gpt-4.1-mini", "config": ["temperature"]}, "config"),
    *[({"id": "openai:chat:gpt-4.1-mini", "config": {k: v}}, k) for k, v in [
        ("response_format", {"type": "json_object"}), ("reasoning", {"effort": "low"}),
        ("thinking", {"type": "enabled", "budget_tokens": 1024}), ("stop", ["END"]),
        ("tool_choice", "auto"), ("functions", []), ("passthrough", {}), ("basePath", "x"),
        ("apiKey", "sk-x")]],
])
def test_a_grader_setting_judgekeeper_does_not_know_is_not_asked(tmp_path, grader, key):
    ws = _checked(tmp_path)
    _grader(tmp_path, grader)
    p = make_plan(ws, AgainOptions(), dry=False)
    assert p.status == "cant"
    assert (f"its setting `{key}` is not one judgekeeper knows is safe" in p.why
            or f"({key} in your grader's settings)" in p.why), p.why  # the address check


@pytest.mark.parametrize("grader", [
    {"id": "openai:chat:gpt-4.1-mini", "label": "mine", "config": ALLOWED},
    {"id": "anthropic:messages:claude-haiku-4-5", "config": {"temperature": 0}},
    {"text": {"id": "openai:chat:gpt-4.1-mini", "config": {"temperature": 0}}},
    {"id": "openai:chat:gpt-4.1-mini"},
])
def test_a_grader_with_only_known_settings_is_asked(tmp_path, grader):
    ws = _checked(tmp_path)
    _grader(tmp_path, grader)
    p = make_plan(ws, AgainOptions(), dry=False)
    assert p.status != "cant", p.why


@pytest.mark.parametrize(("key", "value"), [
    ("region", "evil.example/x?"), ("region", "global.example"), ("location", "a.b/c"),
    ("projectId", "p/../../x"), ("apiVersion", "1&x=y"), ("organization", "org\nX-Evil: 1"),
    ("temperature", "0"), ("temperature", True), ("seed", None), ("reasoning_effort", "max"),
    ("reasoning_effort", SUM), ("max_tokens", [1]), ("apiKeyEnvar", 5)])
def test_a_known_setting_that_could_name_another_server_is_not_asked(tmp_path, key, value):
    ws = _checked(tmp_path)
    _grader(tmp_path, {"id": "openai:chat:gpt-4.1-mini", "config": {key: value}})
    p = make_plan(ws, AgainOptions(), dry=False)
    assert p.status == "cant"
    assert f"its setting `{key}`" in p.why or f"({key} " in p.why, p.why  # or the key check


@pytest.mark.parametrize("value", TEMPLATES)
@pytest.mark.parametrize("where", ["prompt", "var"])
def test_an_answer_with_template_code_in_its_prompt_or_vars_is_left_out(tmp_path, value, where):
    def change(data):
        row = data["results"]["results"][0]
        if where == "prompt":
            row["prompt"]["raw"] = f"Answer this: {value}"
        else:
            row["vars"]["topic"] = row["testCase"]["vars"]["topic"] = value

    def maker(root, *args, **kwargs):
        promptfoo_project(root, *args, **kwargs)
        _edit(root, change)
    ws = _checked(tmp_path, maker=maker)
    before = len([a for a in ws.data()["queue"]])
    p = make_plan(ws, AgainOptions(), dry=False)
    assert p.status != "cant", p.why
    assert len(p.payload) == before - 1
    assert any("template text" in line for line in p.left_out), p.left_out


@pytest.mark.parametrize("value", TEMPLATES)
@pytest.mark.parametrize("where", ["rule", "rubricPrompt", "default rubricPrompt", "grader id",
                                   "grader label"])
def test_template_code_in_the_rule_rubric_or_grader_refuses_the_judge(tmp_path, value, where):
    ws = _checked(tmp_path)
    if where == "rule":
        _edit(tmp_path, _assertions(lambda a: a.update(value=f"Be kind. {value}")))
    elif where == "rubricPrompt":
        _edit(tmp_path, _rows(lambda row: row["testCase"]["options"].update(rubricPrompt=value)))
    elif where == "default rubricPrompt":
        _edit(tmp_path, lambda d: d["config"].update(
            defaultTest={"options": {"rubricPrompt": value}}))
    elif where == "grader id":
        _grader(tmp_path, f"openai:chat:{value}")
    else:
        _grader(tmp_path, {"id": "openai:chat:gpt-4.1-mini", "label": value})
    p = make_plan(ws, AgainOptions(), dry=False)
    assert p.status == "cant" and "template code" in p.why, p.why


@pytest.mark.parametrize("text", [f"Pass if {OPEN}output{CLOSE} is kind.",
                                  f"{OPEN} vars.topic {CLOSE}: {OPEN} question {CLOSE}"])
def test_a_plain_name_in_a_rule_rubric_or_prompt_is_still_asked(tmp_path, text):
    ws = _checked(tmp_path)

    def change(row):
        row["prompt"]["raw"] = text
        row["testCase"]["options"]["rubricPrompt"] = text
        for c in row["gradingResult"]["componentResults"]:
            c["assertion"]["value"] = text
    _edit(tmp_path, _rows(change))
    p = make_plan(ws, AgainOptions(), dry=False)
    assert p.status != "cant", p.why
    assert not p.left_out


# Template code split across two vars: each part alone is clean, the filled-in text is not.
# A promptfoo that fills templates in twice would run it.
SPLIT = {"a": "{", "b": "{" + " env.HOME " + CLOSE}
SPLIT_TEXT = f"{OPEN}a{CLOSE}{OPEN} vars.b {CLOSE}"


def _split(row, where):
    if where == "prompt":
        row["prompt"]["raw"] = SPLIT_TEXT
    elif where == "rule":
        for c in row["gradingResult"]["componentResults"]:
            c["assertion"]["value"] = f"Be kind. {SPLIT_TEXT}"
    else:
        row["testCase"]["options"]["rubricPrompt"] = f"Grade: {SPLIT_TEXT}"


@pytest.mark.parametrize("where", ["prompt", "rule", "rubric"])
def test_template_code_split_across_two_vars_leaves_the_answer_out(tmp_path, where):
    def change(data):
        first, second = data["results"]["results"][:2]
        first["vars"].update(SPLIT)
        first["testCase"]["vars"].update(SPLIT)
        _split(first, where)
        second["prompt"]["raw"] = f"{OPEN} question {CLOSE}"  # a plain name: still asked

    def maker(root, *args, **kwargs):
        promptfoo_project(root, *args, **kwargs)
        _edit(root, change)
    ws = _checked(tmp_path, maker=maker)
    rows = json.loads((tmp_path / "results.json").read_text(encoding="utf-8"))["results"]
    first, second = rows["results"][:2]
    p = make_plan(ws, AgainOptions(), dry=False)
    assert p.status != "cant", p.why
    asked = [row for _, row, _, _, _ in p.payload]
    assert first not in asked and second in asked
    assert len(p.payload) == len(ws.data()["queue"]) - 1
    assert any("1 " in line and "template text" in line for line in p.left_out), p.left_out


def test_fix_never_hands_on_template_code_split_across_two_vars(here, capsys, judge,  # noqa: F811
                                                                 runs, monkeypatch):
    made = test_fix.promptfoo_data

    def data(*args, **kwargs):
        d = made(*args, **kwargs)
        for row in d["results"]["results"]:
            row["vars"].update(SPLIT)
            row["testCase"]["vars"].update(SPLIT)
            _split(row, "prompt")
        return d
    monkeypatch.setattr(test_fix, "promptfoo_data", data)
    ws = test_fix.project(here)
    test_fix.run(capsys)
    (ws.dir / "fix" / "rule.txt").write_text(test_fix.NEW_RULE, encoding="utf-8")
    code, out = test_fix.run(capsys, "--yes")
    assert code == 3, out
    assert judge["evals"] == 0 and runs["graded"] == 0
    assert "template text" in _flat(out)


# The last check, just before the tests file is written ------------------------------------------

def _leaves(value, path=()):
    """The path to every string in `value`."""
    if isinstance(value, str):
        yield path
    elif isinstance(value, dict):
        for k, v in value.items():
            yield from _leaves(v, (*path, k))
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from _leaves(v, (*path, i))


def _set(value, path, new):
    for step in path[:-1]:
        value = value[step]
    value[path[-1]] = new


def test_every_string_in_a_test_goes_through_the_last_check(tmp_path):
    ws = _checked(tmp_path)
    entry = pf.test_entry(*make_plan(ws, AgainOptions(), dry=False).payload[0])
    entry["vars"]["list"] = ["a", {"b": "c"}]
    assert pf.loads_code(entry) is None
    paths = list(_leaves(entry))
    assert {p[0] for p in paths} >= {"vars", "providerOutput", "options", "assert"}
    assert ("vars", "judgekeeper_prompt") in paths and ("vars", "list", 1, "b") in paths
    for path in paths:
        for value in (*CODE_VALUES, "  file://evil.js", "see file://x.js", "file://data.json"):
            changed = copy.deepcopy(entry)
            _set(changed, path, value)
            assert pf.loads_code(changed), (path, value)
        for value in TEMPLATES:  # promptfoo never fills in the saved answer
            changed = copy.deepcopy(entry)
            _set(changed, path, value)
            assert bool(pf.loads_code(changed)) is (path[0] != "providerOutput"), path


def test_the_last_check_writes_nothing_and_runs_nothing(tmp_path, monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("promptfoo was started")

    ws = _checked(tmp_path)
    monkeypatch.setattr(again, "run_process", refuse)
    p = make_plan(ws, AgainOptions(), dry=False)
    p.runner = ["promptfoo"]
    answer, row, comps, opts, default = p.payload[0]
    p.payload[0] = (answer, {**row, "response": {"output": "file://evil.js"}}, comps, opts,
                    default)
    with pytest.raises(AgainError) as e:
        pf.run(ws, p, SimpleNamespace(say=lambda *a, **k: None))
    assert OWN_CODE in str(e.value)
    assert not (tmp_path / pf.CONFIG).exists() and not (tmp_path / pf.TESTS).exists()


@pytest.mark.parametrize("where", ["prompt", "rule", "rubric"])
def test_the_last_check_finds_template_code_split_across_two_vars(tmp_path, monkeypatch,
                                                                    where):
    def refuse(*args, **kwargs):
        raise AssertionError("promptfoo was started")

    ws = _checked(tmp_path)
    monkeypatch.setattr(again, "run_process", refuse)
    p = make_plan(ws, AgainOptions(), dry=False)
    p.runner = ["promptfoo"]
    answer, row, comps, opts, default = copy.deepcopy(p.payload[0])
    row["vars"].update(SPLIT)
    if where == "prompt":
        row["prompt"]["raw"] = SPLIT_TEXT
    elif where == "rule":
        comps = [{**c, "assertion": {**c["assertion"], "value": SPLIT_TEXT}} for c in comps]
    else:
        opts = {**opts, "rubricPrompt": SPLIT_TEXT}
    p.payload[0] = (answer, row, comps, opts, default)
    with pytest.raises(AgainError) as e:
        pf.run(ws, p, SimpleNamespace(say=lambda *a, **k: None))
    assert "template code" in str(e.value)
    assert not (tmp_path / pf.CONFIG).exists() and not (tmp_path / pf.TESTS).exists()


def test_the_last_check_finds_a_grader_by_output_type(tmp_path, monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("promptfoo was started")

    ws = _checked(tmp_path)
    monkeypatch.setattr(again, "run_process", refuse)
    p = make_plan(ws, AgainOptions(), dry=False)
    p.runner = ["promptfoo"]
    answer, row, comps, opts, default = copy.deepcopy(p.payload[0])
    p.payload[0] = (answer, row, comps, {**opts, "provider": {"text": "echo"}}, default)
    with pytest.raises(AgainError) as e:
        pf.run(ws, p, SimpleNamespace(say=lambda *a, **k: None))
    assert OWN_CODE in str(e.value)
    assert not (tmp_path / pf.CONFIG).exists() and not (tmp_path / pf.TESTS).exists()


def test_the_last_check_finds_a_config_env_set_after_the_plan(tmp_path, monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("promptfoo was started")

    ws = _checked(tmp_path)
    monkeypatch.setattr(again, "run_process", refuse)
    p = make_plan(ws, AgainOptions(), dry=False)
    p.runner = ["promptfoo"]
    (tmp_path / "promptfooconfig.yaml").write_text("env:\n  NODE_OPTIONS: --require ./x.js\n",
                                                   encoding="utf-8")
    with pytest.raises(AgainError) as e:
        pf.run(ws, p, SimpleNamespace(say=lambda *a, **k: None))
    assert "`NODE_OPTIONS`" in str(e.value)
    assert not (tmp_path / pf.CONFIG).exists() and not (tmp_path / pf.TESTS).exists()


def test_a_version_with_other_digits_does_not_read_as_one():
    assert pf.VERSION.fullmatch("0.124.1")
    assert not pf.VERSION.fullmatch("٠.١٢٣.٠")
