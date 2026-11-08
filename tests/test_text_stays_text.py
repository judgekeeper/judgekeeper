"""What comes from a results file stays text: promptfoo gets answers and questions as plain text
(marked-answers.yaml and, in a promptfoo project, marked-answers.csv), they read back as marked,
and regrade.yaml carries only a plain model grader, plain settings and plain rule variables.
No test runs promptfoo or calls an API: the files are only text.
"""

from __future__ import annotations

import csv
import json
import os
import subprocess
from types import SimpleNamespace

import pytest
import yaml

from judgekeeper import check, fix, judgments, textio
from judgekeeper.fingerprint import JudgeFingerprint
from tests.start_projects import promptfoo_data
from tests.test_fix import RULE, project, run

TEMPLATES = [
    "{{ 7*7 }}", "a {{ env.HOME }} b", "{% if true %}x{% endif %}", "x{# gone #}y", "a #} b",
    "{% endraw %}{{ 7*7 }}", "{%- endraw -%}{{ 7*7 }}", "{%endraw%}{{7*7}}",
    "{% raw %}{{ 7*7 }}", "{{{ 7*7 }}}", "{{{{", "{%{#{{", '{{ "{" }}', '{{ "#" }}}', "{{question}}",
    "{{ question }} and {{ answer }}", '{{ "f" }}ile://x', "line one\n{{ 7*7 }}\nline three",
]
LOADERS = ["file://marker.txt", "file://marker.js", "file:///etc/hosts", "file://{{ env.HOME }}.txt",
           "file://a{% endraw %}{{ 7*7 }}", "file://x{# c #}y", "file://x\n", "package:left-pad:run",
           "package:{{ 7*7 }}"]
NEAR_MISSES = ["  file://x", "\nfile://x", "FILE://x", "File://x", "file:/x", "file:x",
               " package:x", "PACKAGE:x", "packages:x"]
PLAIN = ["Plain.", "} } {", "{", "ends with brace {", '{"json": {"a": 1}}', "a, b, c", "[1, 2]",
         "", "null", "12", "=SUM(A1:A9)"]
GRADER = {"provider": "openai", "model": "openai:gpt-4.1-mini"}


def _tests(rows):
    return yaml.safe_load(fix.tests_yaml(rows))


def _base(**over):
    return {"fingerprint": GRADER, "rule": RULE, "metric": "llm-rubric", "results_files": [],
            **over}


def _file_for(tmp_path, data):
    return fix._regrade_yaml(SimpleNamespace(root=tmp_path), data)


@pytest.fixture
def here(tmp_path, monkeypatch):
    root = tmp_path / "support-bot"
    root.mkdir()
    monkeypatch.chdir(root)
    return root


# marked-answers.yaml ---------------------------------------------------------------------------

@pytest.mark.parametrize("text", PLAIN + NEAR_MISSES)
def test_plain_text_is_written_as_before(text):
    row = fix.tests_yaml([("What is it?", text)])
    assert row == "- vars: " + fix._yaml_string({"question": "What is it?", "answer": text}) + "\n"


@pytest.mark.parametrize("text", [*TEMPLATES, "ends with a new line\n", "\n"])
def test_template_text_is_a_list_of_one_that_promptfoo_does_not_render(text):
    (test,) = _tests([("What is it?", text)])
    assert test == {"options": {"disableVarExpansion": True},
                    "vars": {"question": "What is it?", "answer": [text]}}


@pytest.mark.parametrize("text", LOADERS)
def test_text_promptfoo_would_load_never_starts_as_a_loader(text):
    (test,) = _tests([("What is it?", text)])
    value = test["vars"]["answer"]
    if text.startswith("file://"):  # a list does not help: promptfoo rewrites the value in it
        assert isinstance(value, str) and not value.startswith("file://")
    else:
        assert value == [text]
    assert fix.plain_var(value) == text


def test_a_hostile_question_and_answer_in_one_row():
    question, answer = "{% endraw %}{{ 7*7 }}", "file://marker.js"
    (test,) = _tests([(question, answer)])
    assert test["options"] == {"disableVarExpansion": True}
    assert test["vars"]["question"] == [question]
    assert fix.asked(test["vars"], answer) == question


@pytest.mark.parametrize("text", TEMPLATES + LOADERS + PLAIN + NEAR_MISSES)
def test_the_printed_form_reads_back_as_the_text(text):
    assert fix.unprinted(fix.printed(text)) == text


def test_only_text_a_template_or_loader_would_touch_is_printed():
    for text in TEMPLATES + LOADERS:
        assert fix.acted_on(text), text
    for text in PLAIN + NEAR_MISSES:
        assert not fix.acted_on(text), text


# reading new.json back -------------------------------------------------------------------------

@pytest.mark.parametrize("answer", TEMPLATES + LOADERS + PLAIN[:5] + NEAR_MISSES)
def test_a_graded_row_asks_the_question_the_file_held(answer):
    question = "{{ question }}"
    (test,) = _tests([(question, answer)])
    assert fix.asked(test["vars"], answer) == question
    cells = {"question": fix.promptfoo_cell(question), "answer": fix.promptfoo_cell(answer)}
    assert fix.asked(cells, answer) == question  # the CSV's cells, as promptfoo hands them back


@pytest.mark.parametrize("plain, hostile", [
    ('{{ "f" }}ile://x', "file://x"),
    ('{{ "{" }}', "{"),
    ("49", "{{ 7*7 }}"),
    ("x", '{{ "x" }}'),
])
def test_two_rows_near_each_other_do_not_cross_match(plain, hostile):
    tests = _tests([("Same?", plain), ("Same?", hostile)])
    assert fix.plain_var(tests[0]["vars"]["answer"]) == plain
    assert fix.plain_var(tests[1]["vars"]["answer"]) == hostile
    assert fix.asked(tests[0]["vars"], hostile) == tests[0]["vars"]  # not this row's answer
    assert fix.asked(tests[1]["vars"], plain) == tests[1]["vars"]
    assert fix.unprinted(fix.promptfoo_cell(plain)) == plain
    assert fix.unprinted(fix.promptfoo_cell(hostile)) == hostile


@pytest.mark.parametrize("marked, saved", [
    ('{"json": {"a": 1}}', '{"json":{"a":1}}'),
    ("[1, 2]", "[1,2]"),
    ('["x", {"a": 1}]', '["x",{"a":1}]'),
    ('{"a": "é"}', '{"a":"é"}'),
])
def test_json_text_matches_as_promptfoo_saves_it(marked, saved):
    """promptfoo keeps the graded answer as it is and saves a var that is JSON without spaces."""
    assert set(check._marked_question({"question": marked})) & check._questions(
        {"question": saved, "answer": "Plain."})
    assert fix.asked({"question": "Asked?", "answer": saved}, marked) == "Asked?"


@pytest.mark.parametrize("text", ["[not json]", "{not json}", "Plain.", "{", "["])
def test_other_text_is_not_touched_by_the_json_form(text):
    assert check._json_text(text) == text


def test_a_list_is_never_undone_twice():
    assert fix.plain_var(['{{ "f" }}ile://x']) == '{{ "f" }}ile://x'
    assert fix.plain_var(["a", "b"]) == ["a", "b"]  # not a row of the file
    assert fix.plain_var([1]) == [1]


def test_the_question_of_a_graded_row_is_matched_as_marked():
    question, answer = "{{ 7*7 }}", "{% endraw %}x"
    (test,) = _tests([(question, answer)])
    assert question in check._questions(test["vars"])
    assert answer in check._questions(test["vars"])
    cells = {"question": fix.promptfoo_cell(question), "answer": "x"}
    assert question in check._questions(cells)


# marked-answers.csv ----------------------------------------------------------------------------

def test_a_last_new_line_in_a_cell_is_printed():
    assert fix.promptfoo_cell("line\n") == fix.printed("line\n") != "line\n"
    assert fix.unprinted(fix.promptfoo_cell("line\n")) == "line\n"



def _cells(ws):
    with (ws.dir / "fix" / "marked-answers.csv").open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def test_the_csv_of_a_promptfoo_project_is_printed_and_another_tools_is_not(here, monkeypatch):
    ws = project(here)
    rows = {"a": {"input": "{{ 7*7 }}", "output": "file://x"}}
    marks = SimpleNamespace(rows=rows, person=["a"], data={"tool": "promptfoo"})
    fix.write_answers(ws, marks)
    (row,) = _cells(ws)
    assert row["question"] == fix.printed("{{ 7*7 }}") and row["answer"] == fix.printed("file://x")
    assert "{{ 7*7 }}" not in json.dumps(row)
    marks.data["tool"] = "table"
    fix.write_answers(ws, marks)
    assert _cells(ws) == [{"question": "{{ 7*7 }}", "answer": "file://x"}]


def test_a_printed_row_is_not_written_again_for_nothing(here, capsys):
    ws = project(here)
    rows = {"a": {"input": "{{ 7*7 }}", "output": "file://x"}}
    marks = SimpleNamespace(rows=rows, person=["a"], data={"tool": "promptfoo"})
    fix.write_answers(ws, marks)
    talk = SimpleNamespace(say=lambda: pytest.fail("written again"), para=print)
    fix._rewrite_lacking(talk, ws, marks, ["a"])


# regrade.yaml: what the results file may choose ------------------------------------------------

@pytest.mark.parametrize("provider, model", [
    ("python", "python:grader.py"), ("file", "file://x.py"), ("exec", "exec:./x"),
    ("https", "https://example.com/grade"), ("http", "http://127.0.0.1:1/x"),
    ("webhook", "webhook:http://example.com"), ("golang", "golang:x.go"), ("ruby", "ruby:x.rb"),
    ("package", "package:x:y"), ("script", "script:x"), ("mcp", "mcp:x"), ("browser", "browser:x"),
    ("OpenAI", "OpenAI:gpt-4.1"),
    ("openai", "openai:https://example.com/v1"), ("openai", "openai:chat:http://example.com"),
    ("openai", "openai:file://x.js"), ("openai", "openai:/etc/hosts"),
    ("openai", "openai:chat:/etc/hosts"), ("openai", "openai:../x"), ("openai", "openai:chat:../x"),
    ("openai", "openai:a//b"), ("openai", r"openai:a\b"), ("openai", "openai:"),
    ("openai", "openai:{{ env.X }}"), ("openai", "openai:a b"), ("openai", "openai:a\nb"),
    ("anthropic", "anthropic:messages:https://example.com"), ("azure", "azure:chat:file://x"),
])
def test_no_file_for_a_grader_that_is_not_a_plain_model(tmp_path, provider, model):
    assert _file_for(tmp_path, _base(fingerprint={"provider": provider, "model": model})) is None


@pytest.mark.parametrize("model", [
    "openai:gpt-4.1-mini", "openai:chat:gpt-4.1-mini", "openai:responses:gpt-5",
    "anthropic:messages:claude-sonnet-4-5-20250929", "anthropic:claude-sonnet-4-5",
    "azure:chat:my-deployment", "google:gemini-2.5-pro", "vertex:gemini-2.5-pro",
    "bedrock:us.anthropic.claude-sonnet-4-5-20250929-v1:0", "mistral:mistral-large-latest",
    "groq:llama-3.3-70b-versatile", "openrouter:meta-llama/llama-3.3-70b-instruct",
    "ollama:chat:llama3.3",
])
def test_a_plain_model_keeps_its_file(tmp_path, model):
    data = _base(fingerprint={"provider": model.split(":")[0], "model": model})
    text = _file_for(tmp_path, data)
    assert yaml.safe_load(text)["defaultTest"]["options"]["provider"] == model


def _grader_config(root, config, metric="llm-rubric", kind="llm-rubric", grader=None):
    data = promptfoo_data([True] * 25 + [False] * 25, rubric=RULE, metric=metric)
    for row in data["results"]["results"]:
        row["testCase"]["options"] = {"provider": {"id": grader or GRADER["model"],
                                                   "config": config}}
        row["gradingResult"]["componentResults"][0]["assertion"]["type"] = kind
    (root / "named.json").write_text(json.dumps(data), encoding="utf-8")


@pytest.mark.parametrize("config", [
    {"apiBaseUrl": "http://127.0.0.1:1/v1"}, {"apiHost": "example.com"}, {"baseUrl": "x"},
    {"basePath": "/x"}, {"url": "http://x"}, {"proxy": "http://x"}, {"endpoint": "http://x"},
    {"headers": {"X-Team": "support"}}, {"transformResponse": "json"}, {"transform": "x"},
    {"responseParser": "x"}, {"functionToolCallbacks": {"a": "file://x.js"}}, {"tools": "file://x"},
    {"mcp": {"enabled": True}}, {"temperature": 0, "apiBaseUrl": "http://x"},
    {"response_format": "file://x.json"}, {"response_format": {"schema": "file://x.json"}},
    {"stop": ["file://x"]}, {"stop": ["{{ env.X }}"]}, {"seed": "{{ env.X }}"},
    {"thinking": {"url": "https://example.com"}}, {"region": "x.example.com/"},
    {"region": "http://x"},
])
def test_no_file_for_a_config_that_is_not_plain_settings(here, config):
    ws = project(here)
    _grader_config(here, config)
    data = _base(results_files=["named.json"])
    assert fix._regrade_yaml(ws, data) is None


@pytest.mark.parametrize("config", [
    {"temperature": 0}, {"temperature": 0.2, "max_tokens": 300}, {"maxTokens": 512, "top_p": 1},
    {"seed": 7, "stop": ["END"]}, {"reasoning_effort": "low"}, {"reasoning": {"effort": "low"}},
    {"thinking": {"type": "enabled", "budget_tokens": 2048}},
    {"response_format": {"type": "json_object"}}, {"region": "us-east-1"},
    {"max_completion_tokens": 300, "frequency_penalty": 0, "presence_penalty": 0},
])
def test_plain_settings_are_kept(here, config):
    ws = project(here)
    _grader_config(here, config)
    text = fix._regrade_yaml(ws, _base(results_files=["named.json"]))
    assert yaml.safe_load(text)["defaultTest"]["options"]["provider"] == {
        "id": GRADER["model"], "config": config}


def test_a_key_in_the_config_is_still_left_out_with_its_note(here):
    ws = project(here)
    _grader_config(here, {"temperature": 0, "apiKey": "abc", "apiKeyEnvar": "MY_KEY"})
    text = fix._regrade_yaml(ws, _base(results_files=["named.json"]))
    assert yaml.safe_load(text)["defaultTest"]["options"]["provider"]["config"] == {"temperature": 0}
    assert "# apiKey left out:" in text and "# apiKeyEnvar left out:" in text


@pytest.mark.parametrize("rule", [
    "{{ env }}", "{{env}}", "{{  env  }}", "{{env.X}}", "{{ env.X }}", "{{ env['X'] }}",
    "{{ _x }}", "{{_x}}", "{{ a.b }}", "{{ a . b }}", "{{ a[0] }}", "{{ a | upper }}", "{{ a() }}",
    "{{ 7*7 }}", '{{ "x" }}', "{{- a -}}", "{{{ a }}}", "{{ a }", "{% if a %}x{% endif %}",
    "{% raw %}x{% endraw %}", "{# note #}", "file://rule.txt", "file://rule.py", "package:x:y",
    "Is it good? {{ answer }} {{ env.X }}",
])
def test_no_file_for_a_rule_with_more_than_plain_variables(tmp_path, rule):
    assert _file_for(tmp_path, _base(rule=rule)) is None


@pytest.mark.parametrize("rule", [
    "Be polite.", "The question was {{question}}.", "{{ answer }} must answer {{  question  }}",
    "Compare {{output}} with {{context}} and {{ topic_2 }}.", 'Reply as {"pass": true}.',
    "a { b } c", "Use file://x as a word.", "{{question}}",
])
def test_a_normal_rule_keeps_its_file(tmp_path, rule):
    text = _file_for(tmp_path, _base(rule=rule))
    assert yaml.safe_load(text)["defaultTest"]["assert"][0]["value"] == rule


@pytest.mark.parametrize("metric", ["{{ env }}", "{{env.X}}", "{{ _x }}", "{{ a.b }}", "{{a}}",
                                    "{% if a %}x{% endif %}", "{# x #}"])
def test_no_file_for_a_metric_with_a_template(here, metric):
    ws = project(here)
    _grader_config(here, {}, metric=metric)
    assert fix._regrade_yaml(ws, _base(metric=metric, results_files=["named.json"])) is None


def test_a_code_assertion_is_never_carried(here):
    ws = project(here)
    _grader_config(here, {}, metric="correct", kind="python")
    assert fix._regrade_yaml(ws, _base(metric="correct", results_files=["named.json"])) is None


@pytest.mark.parametrize("grader, config, shown", [
    ("openai:gpt-4.1-mini", None, '"openai:gpt-4.1-mini"'),
    ("anthropic:messages:claude-sonnet-4-5-20250929", None,
     '"anthropic:messages:claude-sonnet-4-5-20250929"'),
    ("openai:gpt-4.1-mini", {"temperature": 0},
     '{"id": "openai:gpt-4.1-mini", "config": {"temperature": 0}}'),
])
def test_the_normal_file_is_the_same_byte_for_byte(here, grader, config, shown):
    ws = project(here)
    _grader_config(here, config or {}, grader=grader)
    data = _base(results_files=["named.json"],
                 fingerprint={"provider": grader.split(":")[0], "model": grader})
    assert fix._regrade_yaml(ws, data) == (
        'prompts: ["{{answer}}"]\n'
        f'providers: ["echo"]{fix.ECHO_NOTE}\n'
        f'tests: "file://marked-answers.yaml"{fix.TESTS_NOTE}\n'
        "defaultTest:\n"
        "  options:\n"
        f"    provider: {shown}\n"
        "  assert:\n"
        '    - type: "llm-rubric"\n'
        '      metric: "llm-rubric"\n'
        f"      value: {json.dumps(RULE, ensure_ascii=False)}{fix.RULE_NOTE}\n")


def test_a_grader_with_a_host_of_its_own_gets_the_steps_not_a_file(here, capsys):
    ws = project(here)
    data = json.loads(next(here.glob("*results*.json")).read_text(encoding="utf-8"))
    for row in data["results"]["results"]:
        row["testCase"]["options"] = {"provider": {"id": GRADER["model"],
                                                   "config": {"apiHost": "example.com"}}}
    next(here.glob("*results*.json")).write_text(json.dumps(data), encoding="utf-8")
    code, out = run(capsys)
    assert code == 0, out
    assert not (ws.dir / "fix" / "regrade.yaml").exists()
    flat = " ".join(out.split())
    assert fix.REGRADE["promptfoo"] in flat, flat
    assert "regrade.yaml" not in flat and "three steps" not in flat, flat


# a program in the current folder ---------------------------------------------------------------

def test_a_python_found_in_the_current_folder_is_never_started(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(textio, "_imports", {})
    monkeypatch.setattr("shutil.which", lambda name, *a, **k: str(tmp_path / "py.exe"))
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("started it"))
    assert textio.imports_judgekeeper("py") is False


def test_a_python_found_by_a_relative_name_is_never_started(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(textio, "_imports", {})
    monkeypatch.setattr("shutil.which", lambda name, *a, **k: os.path.join(".", "py.exe"))
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("started it"))
    assert textio.imports_judgekeeper("py") is False


def test_a_python_elsewhere_on_the_path_is_still_asked(tmp_path, monkeypatch):
    here, there = tmp_path / "here", tmp_path / "there"
    here.mkdir()
    there.mkdir()
    monkeypatch.chdir(here)
    monkeypatch.setattr(textio, "_imports", {})
    monkeypatch.setattr("shutil.which", lambda name, *a, **k: str(there / "python3"))
    started = []

    def fake(cmd, **kw):
        started.append(cmd[0])
        return SimpleNamespace(returncode=1, stdout="")

    monkeypatch.setattr(subprocess, "run", fake)
    assert textio.imports_judgekeeper("python3") is False
    assert started == [str(there / "python3")]


# keys in ids and file names --------------------------------------------------------------------

KEY = "sk-ant-" + "abcdefghijklmnop1234567890"


def _fingerprint():
    return JudgeFingerprint(provider="openai", model="gpt-4.1-mini", temperature=0,
                            created_at="2026-01-01T00:00:00+00:00")


def test_a_key_in_an_id_is_not_written_with_the_judgment(tmp_path):
    from judgekeeper.runners.base import Judgment

    fp = _fingerprint()
    rec = judgments.judgment_to_record(f"row-{KEY}", Judgment(verdict="pass", raw_score=None,
                                                              rationale=""), fp)
    path = tmp_path / "pool-judge.jsonl"
    judgments.write_run(path, 1, "", fp, [rec])
    assert KEY not in path.read_text(encoding="utf-8")


def test_a_key_in_an_id_is_not_written_with_the_verdicts(here):
    ws = project(here)
    found = SimpleNamespace(fingerprint={"provider": "openai"})
    check._save_verdicts(ws, {"rule": "r"}, found, {f"row-{KEY}": "pass"})
    (path,) = (ws.dir / "verdicts").glob("*.jsonl")
    assert KEY not in path.read_text(encoding="utf-8")


def test_a_key_in_a_file_name_is_not_written_to_the_results_seen(here, monkeypatch):
    ws = project(here)
    name = here / f"results-{KEY}.json"
    name.write_text("{}", encoding="utf-8")
    state = SimpleNamespace(ws=ws)
    found = SimpleNamespace(results=[SimpleNamespace(path=name)])
    monkeypatch.setattr(check, "_key", lambda *a: "k")
    monkeypatch.setattr(check, "_configs", lambda f: [name])
    check._remember(state, found, {"rule": "r"})
    assert KEY not in (ws.dir / check.SEEN).read_text(encoding="utf-8")
