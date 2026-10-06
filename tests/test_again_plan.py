"""Asking your judge again: the plan before any call (promptfoo, a judge command, a table),
the spending question, and the menu. Nothing here runs a judge: the one process function is
replaced, and only `--version` is ever answered."""

from __future__ import annotations

import builtins
import json
from types import SimpleNamespace

import pytest

from judgekeeper import again, keys, start, start_label
from judgekeeper.again import AgainOptions, approve, make_plan, plan_lines
from judgekeeper.cli import main
from judgekeeper.start_label import StartSession, save_result
from tests.start_projects import promptfoo_project, split, table_project


def _quiet(line=""):
    pass


def _checked(root, n_pass=20, n_fail=16, labeled=None, maker=promptfoo_project, **kwargs):
    """A project with a result: the first `labeled` answers (all when None) labeled the way
    the judge saw them."""
    maker(root, split(n_pass, n_fail), **kwargs)
    ws = start_label.prepare(start.find_judge(root), say=_quiet)
    session = StartSession(ws)
    for q in ws.data()["queue"][:labeled]:
        session.update({"id": q["id"], "label": q["group"]})
    save_result(ws, session, say=_quiet)
    return ws


def _edit(root, change, name="results.json"):
    """Change the saved promptfoo results: change(data) or change(row) for every row."""
    path = root / name
    data = json.loads(path.read_text(encoding="utf-8"))
    change(data)
    path.write_text(json.dumps(data), encoding="utf-8")


def _rows(fn):
    def change(data):
        for row in data["results"]["results"]:
            fn(row)
    return change


def _version(v="0.123.1"):
    def change(data):
        data.setdefault("metadata", {})["promptfooVersion"] = v
    return change


@pytest.fixture(autouse=True)
def no_processes(monkeypatch):
    """Only `--version` is answered; promptfoo and npx are not installed unless a test says
    so. Key variables are cleared."""
    calls = []
    versions = {}

    def run_process(argv, cwd, env=None, timeout=None):
        calls.append(list(argv))
        if argv[-1] == "--version" and argv[0] in versions:
            return SimpleNamespace(returncode=0, stdout=versions[argv[0]] + "\n", stderr="")
        raise AssertionError(f"no process may run here: {argv}")

    monkeypatch.setattr(again, "run_process", run_process)
    installed = {}
    monkeypatch.setattr(again, "which", lambda name: installed.get(name))
    for name in keys.all_names():
        monkeypatch.delenv(name, raising=False)
    return SimpleNamespace(calls=calls, versions=versions, installed=installed)


def _local_promptfoo(root, procs, version="0.123.1"):
    binary = root / "node_modules" / ".bin" / "promptfoo"
    binary.parent.mkdir(parents=True)
    binary.write_text("", encoding="utf-8")
    procs.versions[str(binary)] = version
    return binary


# promptfoo ---------------------------------------------------------------------------------

def test_the_plan_for_promptfoo_with_the_same_version(tmp_path, monkeypatch, no_processes):
    ws = _checked(tmp_path)
    _edit(tmp_path, _version())
    _local_promptfoo(tmp_path, no_processes)
    monkeypatch.setenv("OPENAI_API_KEY", "x" * 30)
    p = make_plan(ws, AgainOptions())
    assert (p.tool, p.status, p.answers, p.times, p.calls) == ("promptfoo", "exact", 36, 2, 72)
    lines = plan_lines(p)
    judge = ws.data()["judge"]
    assert lines[:3] == ["Ask your judge again", "", f"  Your judge: {judge} (promptfoo 0.123.1)"]
    assert ("  This is exactly your judge: promptfoo re-grades your saved answers with your own "
            "settings.") in lines
    assert ("  Your judge will use your OpenAI key (OPENAI_API_KEY, set in your shell)."
            in lines)
    assert "  36 labeled answers × 2 times = 72 judge calls." in lines
    assert any(x.startswith("  About $") and x.endswith(
        "at OpenAI's prices from 2026-10-05; check your provider.") for x in lines)
    assert ("  Your app is not run. Nothing is written to promptfoo's database or shared."
            in lines)
    assert ("  Two temporary files are written next to promptfooconfig.yaml and removed "
            "afterwards.") in lines


def test_only_labeled_answers_are_asked(tmp_path):
    ws = _checked(tmp_path, labeled=24)
    assert make_plan(ws, AgainOptions(), dry=False).answers == 24


def test_times_multiply_the_calls(tmp_path):
    ws = _checked(tmp_path)
    p = make_plan(ws, AgainOptions(times=3), dry=False)
    assert p.calls == 108
    assert "  36 labeled answers × 3 times = 108 judge calls." in plan_lines(p)


def test_tokens_come_from_tokens_used(tmp_path):
    ws = _checked(tmp_path)

    def used(row):
        for c in row["gradingResult"]["componentResults"]:
            c["tokensUsed"] = {"total": 1100, "prompt": 1000, "completion": 100}

    _edit(tmp_path, _rows(used))
    p = make_plan(ws, AgainOptions(), dry=False)
    assert p.tokens == [(1000, 100)] * 36
    # 72 calls x (1000 x $0.40 + 100 x $1.60) / 1e6 = $0.04032: $0.02 to $0.10
    assert p.cost == pytest.approx((0.02016, 0.1008))


def test_without_tokens_used_characters_over_four(tmp_path):
    ws = _checked(tmp_path)
    p = make_plan(ws, AgainOptions(), dry=False)
    assert all(out == 200 and 0 < inp < 200 for inp, out in p.tokens)


def test_no_recorded_version_is_a_close_copy(tmp_path, no_processes):
    ws = _checked(tmp_path)
    _local_promptfoo(tmp_path, no_processes, "0.123.1")
    p = make_plan(ws, AgainOptions())
    assert p.status == "close"
    assert "  This is a close copy of your judge: promptfoo version not recorded." in plan_lines(p)


def test_another_installed_version_means_npx(tmp_path, no_processes):
    ws = _checked(tmp_path)
    _edit(tmp_path, _version())
    _local_promptfoo(tmp_path, no_processes, "0.120.0")
    no_processes.installed["npx"] = "/usr/bin/npx"
    p = make_plan(ws, AgainOptions())
    assert p.status == "exact"
    assert ("  Your promptfoo is 0.120.0; your results were made with promptfoo 0.123.1. "
            "judgekeeper would run npx --yes promptfoo@0.123.1, which downloads it; it asks "
            "first.") in plan_lines(p)


def test_promptfoo_on_the_path_is_used_when_its_version_matches(tmp_path, no_processes):
    ws = _checked(tmp_path)
    _edit(tmp_path, _version())
    no_processes.installed["promptfoo"] = "/usr/local/bin/promptfoo"
    no_processes.versions["/usr/local/bin/promptfoo"] = "0.123.1"
    assert make_plan(ws, AgainOptions()).status == "exact"


def test_no_promptfoo_and_no_npx_cant(tmp_path):
    ws = _checked(tmp_path)
    _edit(tmp_path, _version())
    p = make_plan(ws, AgainOptions())
    assert p.status == "cant"
    assert "promptfoo is not installed here, and npx (Node.js) was not found" in p.why


def test_the_menu_plan_runs_no_process(tmp_path, no_processes):
    ws = _checked(tmp_path)
    _edit(tmp_path, _version())
    make_plan(ws, AgainOptions(), dry=False)
    assert no_processes.calls == []


def test_the_default_grader_is_probably(tmp_path, monkeypatch, no_processes):
    ws = _checked(tmp_path, model=None)
    _edit(tmp_path, _version())
    _local_promptfoo(tmp_path, no_processes)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x" * 30)
    p = make_plan(ws, AgainOptions())
    assert p.status == "close"
    assert p.model == "claude-sonnet-4-6" and p.provider == "anthropic"
    lines = plan_lines(p)
    assert any("promptfoo's default grader, probably claude-sonnet-4-6 with promptfoo 0.123.1"
               in x for x in lines)
    assert ("  Your judge will use your Anthropic key (ANTHROPIC_API_KEY, set in your shell)."
            in lines)


@pytest.mark.parametrize("grader, words", [
    ({"modelName": "gpt-4.1-mini", "config": {}}, "--grader"),
    ({"id": "openai:gpt-4.1-mini", "config": {"apiKey": "[REDACTED]"}}, "secret"),
    ("exec: python3 grade.py", "your own code"),
    ("file://grader.js", "your own code"),
    ("python:grader.py", "your own code"),
])
def test_graders_that_cant_be_rebuilt(tmp_path, grader, words):
    ws = _checked(tmp_path)

    def change(row):
        row["testCase"]["options"]["provider"] = grader

    _edit(tmp_path, _rows(change))
    p = make_plan(ws, AgainOptions(), dry=False)
    assert p.status == "cant" and words in p.why
    lines = plan_lines(p)
    assert any(x.startswith("  Your judge can't be asked again: ") for x in lines)
    assert any("wrap it as a command: judgekeeper start --ask-again --judge-command" in x
               for x in lines)


def test_a_rubric_from_a_file_is_your_own_code(tmp_path):
    ws = _checked(tmp_path)

    def change(row):
        for c in row["gradingResult"]["componentResults"]:
            c["assertion"]["value"] = "file://rubric.js"

    _edit(tmp_path, _rows(change))
    p = make_plan(ws, AgainOptions(), dry=False)
    assert p.status == "cant" and "your own code" in p.why


def test_template_text_leaves_an_answer_out_for_prompt_using_types(tmp_path):
    ws = _checked(tmp_path, metric="judge")
    first = {"done": False}

    def change(row):
        for c in row["gradingResult"]["componentResults"]:
            c["assertion"]["type"] = "factuality"
        if not first["done"]:
            row["prompt"] = {"raw": "Answer: {{ question }}"}
            first["done"] = True

    _edit(tmp_path, _rows(change))
    p = make_plan(ws, AgainOptions(), dry=False)
    assert p.answers == 35
    assert any("1 answer is left out: its saved prompt or input holds template text" in x
               for x in plan_lines(p))


def test_template_text_does_not_matter_to_llm_rubric(tmp_path):
    ws = _checked(tmp_path)

    def change(row):
        row["prompt"] = {"raw": "Answer: {{ question }}"}

    _edit(tmp_path, _rows(change))
    assert make_plan(ws, AgainOptions(), dry=False).answers == 36


def test_an_empty_answer_is_left_out(tmp_path):
    outputs = [f"Answer {i}." for i in range(36)]
    outputs[0] = ""
    ws = _checked(tmp_path, outputs=outputs)
    p = make_plan(ws, AgainOptions(), dry=False)
    assert p.answers == 35
    assert any("1 answer is left out: it is empty" in x for x in plan_lines(p))


@pytest.mark.parametrize("type_, calls", [("llm-rubric", 1), ("factuality", 1),
                                          ("model-graded-closedqa", 1), ("g-eval", 2),
                                          ("context-faithfulness", 2),
                                          ("answer-relevance", 3)])
def test_calls_per_judge_type(tmp_path, type_, calls):
    ws = _checked(tmp_path, metric="judge")

    def change(row):
        for c in row["gradingResult"]["componentResults"]:
            c["assertion"]["type"] = type_

    _edit(tmp_path, _rows(change))
    p = make_plan(ws, AgainOptions(), dry=False)
    assert p.calls == 36 * 2 * calls


def test_g_eval_with_several_criteria(tmp_path):
    ws = _checked(tmp_path, metric="judge")

    def change(row):
        for c in row["gradingResult"]["componentResults"]:
            c["assertion"].update(type="g-eval", value=["Is correct.", "Is polite.", "Short."])

    _edit(tmp_path, _rows(change))
    p = make_plan(ws, AgainOptions(), dry=False)
    assert p.calls == 36 * 2 * 6
    assert "  36 labeled answers × 2 times × 6 calls each = 432 judge calls." in plan_lines(p)


def test_answer_relevance_mentions_its_embedding_calls(tmp_path):
    ws = _checked(tmp_path, metric="judge")

    def change(row):
        for c in row["gradingResult"]["componentResults"]:
            c["assertion"]["type"] = "answer-relevance"

    _edit(tmp_path, _rows(change))
    lines = plan_lines(make_plan(ws, AgainOptions(), dry=False))
    assert any("plus 4 embedding calls per answer" in x for x in lines)


def test_an_unknown_type_says_at_least(tmp_path):
    ws = _checked(tmp_path, metric="judge")

    def change(row):
        for c in row["gradingResult"]["componentResults"]:
            c["assertion"]["type"] = "conversation-relevance"

    _edit(tmp_path, _rows(change))
    p = make_plan(ws, AgainOptions(), dry=False)
    assert "  36 labeled answers × 2 times = at least 72 judge calls." in plan_lines(p)


def test_the_cache_warning(tmp_path):
    ws = _checked(tmp_path)
    _edit(tmp_path, lambda data: data.__setitem__("runtimeOptions", {"cache": True}))
    lines = plan_lines(make_plan(ws, AgainOptions(), dry=False))
    assert ("  Your saved verdicts may be old replies from promptfoo's cache. judgekeeper turns "
            "the cache off when it asks again.") in lines


def test_setting_variables_are_named_in_the_plan(tmp_path, monkeypatch):
    ws = _checked(tmp_path)
    monkeypatch.setenv("OPENAI_TEMPERATURE", "0.9")
    lines = plan_lines(make_plan(ws, AgainOptions(), dry=False))
    assert "  OPENAI_TEMPERATURE is set; it changes your judge." in lines


def test_a_missing_key_is_said(tmp_path):
    ws = _checked(tmp_path)
    lines = plan_lines(make_plan(ws, AgainOptions(), dry=False))
    assert ("  Your judge needs OPENAI_API_KEY. It is not set in your shell or in .env."
            in lines)


def test_answers_no_longer_in_the_results_are_left_out(tmp_path):
    ws = _checked(tmp_path)

    def drop(data):
        data["results"]["results"] = data["results"]["results"][:30]

    _edit(tmp_path, drop)
    p = make_plan(ws, AgainOptions(), dry=False)
    assert p.answers == 30
    assert any("6 answers are left out: they are not in your results files any more" in x
               for x in plan_lines(p))


def test_an_unknown_model_has_no_cost(tmp_path):
    ws = _checked(tmp_path, model="openai:my-finetune")
    lines = plan_lines(make_plan(ws, AgainOptions(), dry=False))
    assert "  Cost unknown for this model (openai:my-finetune)." in lines


# Your own judge command, and a table -------------------------------------------------------

def test_the_plan_for_a_judge_command(tmp_path):
    ws = _checked(tmp_path)
    p = make_plan(ws, AgainOptions(judge_command="python judge.py"), dry=False)
    assert p.status == "own"
    lines = plan_lines(p)
    assert "  Your judge: your command python judge.py" in lines
    assert "  This is your own judge command. This runs `python judge.py` 72 times." in lines
    assert "  Cost unknown: name your command's model with --judge-model." in lines


def test_a_judge_command_with_a_model_has_a_cost(tmp_path):
    ws = _checked(tmp_path)
    p = make_plan(ws, AgainOptions(judge_command="python judge.py", judge_model="gpt-4.1-mini"),
                  dry=False)
    assert p.cost is not None


def test_a_judge_command_that_cant_be_read(tmp_path):
    ws = _checked(tmp_path)
    p = make_plan(ws, AgainOptions(judge_command="python 'judge.py"), dry=False)
    assert p.status == "cant" and "cannot be read as a command" in p.why


def test_a_table_cant_be_asked_again_without_a_command(tmp_path):
    ws = _checked(tmp_path, maker=table_project)
    p = make_plan(ws, AgainOptions(), dry=False)
    assert p.status == "cant"
    assert p.short == "your judge's verdicts are a table"
    lines = plan_lines(p)
    assert any("judgekeeper start --ask-again --judge-command" in x for x in lines)
    assert any("reference.html#bring-your-own-judge" in x for x in lines)


# The spending question -----------------------------------------------------------------------

@pytest.fixture
def plan72(tmp_path):
    return make_plan(_checked(tmp_path), AgainOptions(), dry=False)


@pytest.fixture
def terminal(monkeypatch):
    answers: list[str] = []
    monkeypatch.setattr(start, "_interactive", lambda: True)

    def fake_input(prompt=""):
        print(prompt)
        return answers.pop(0) if answers else ""

    monkeypatch.setattr(builtins, "input", fake_input)
    return answers


def test_the_question_defaults_to_no(plan72, terminal, capsys):
    assert approve(plan72, start.Talk(), allow_calls=None) is False
    assert "Go ahead? [y/N]" in capsys.readouterr().out


def test_yes_at_the_terminal(plan72, terminal):
    terminal.append("y")
    assert approve(plan72, start.Talk(), allow_calls=None) is True


def test_yes_flag_never_approves_spending(plan72, capsys):
    with pytest.raises(start.Stop) as stop:
        approve(plan72, start.Talk(yes=True), allow_calls=None)
    assert stop.value.code == 2
    assert "judgekeeper start --ask-again --allow-calls 72" in capsys.readouterr().out


def test_allow_calls_below_the_count_refuses(plan72, capsys):
    with pytest.raises(start.Stop) as stop:
        approve(plan72, start.Talk(), allow_calls=50)
    assert stop.value.code == 2
    assert "--allow-calls 50 is below the 72 calls planned" in capsys.readouterr().out


def test_allow_calls_at_the_count_approves_without_asking(plan72, capsys):
    assert approve(plan72, start.Talk(), allow_calls=72) is True
    assert "Go ahead?" not in capsys.readouterr().out


def test_over_a_thousand_calls_needs_allow_calls_at_a_terminal_too(tmp_path, terminal, capsys):
    p = make_plan(_checked(tmp_path), AgainOptions(times=5), dry=False)
    p.calls_each = [4] * p.answers  # 36 x 5 x 4 = 720: make it bigger
    p.times = 10
    assert p.calls > 1000
    terminal.append("y")
    with pytest.raises(start.Stop):
        approve(p, start.Talk(), allow_calls=None)
    assert "More than 1,000 calls" in capsys.readouterr().out
    assert approve(p, start.Talk(), allow_calls=p.calls) is True


def test_a_judge_that_cant_be_asked_is_never_approved(tmp_path):
    p = make_plan(_checked(tmp_path, maker=table_project), AgainOptions(), dry=False)
    assert approve(p, start.Talk(), allow_calls=10_000) is False


# The menu and the flags ----------------------------------------------------------------------

def run(capsys, *argv):
    code = main(["start", *map(str, argv)])
    out, err = capsys.readouterr()
    return code, out, err


def test_ask_again_without_a_terminal_shows_the_plan_and_the_flag(tmp_path, capsys,
                                                                   no_processes, monkeypatch):
    _checked(tmp_path)
    _local_promptfoo(tmp_path, no_processes)
    monkeypatch.setenv("OPENAI_API_KEY", "x" * 30)
    code, out, _ = run(capsys, tmp_path, "--ask-again")
    assert code == 2
    assert "Ask your judge again" in out and "36 labeled answers × 2 times" in out
    assert out.rstrip().endswith("To go ahead without a terminal: judgekeeper start "
                                 "--ask-again --allow-calls 72")
    assert "What next?" not in out
    assert all(argv[-1] == "--version" for argv in no_processes.calls)


def test_a_missing_key_stops_before_the_question(tmp_path, capsys, no_processes):
    _checked(tmp_path)
    _local_promptfoo(tmp_path, no_processes)
    code, out, _ = run(capsys, tmp_path, "--ask-again", "--allow-calls", "72")
    assert code == 0
    assert out.rstrip().endswith("Set the key, then run judgekeeper start --ask-again again.")
    assert all(argv[-1] == "--version" for argv in no_processes.calls)


def test_the_menu_line_and_choice(tmp_path, capsys, terminal, no_processes, monkeypatch):
    _checked(tmp_path)
    _local_promptfoo(tmp_path, no_processes)
    monkeypatch.setenv("OPENAI_API_KEY", "x" * 30)
    terminal.append("1")  # then Enter at "Go ahead?": No
    code, out, _ = run(capsys, tmp_path)
    assert code == 0
    assert "  1. Ask your judge again about your 36 labeled answers   (72 calls, about $" in out
    assert "Go ahead? [y/N]" in out
    assert "Your judge was not called; nothing was spent." in out


def test_the_menu_says_why_a_judge_cant_be_asked(tmp_path, capsys, terminal):
    _checked(tmp_path, maker=table_project)
    terminal.append("1")
    code, out, _ = run(capsys, tmp_path)
    assert code == 0
    assert ("  1. Ask your judge again about your 36 labeled answers   (can't: your judge's "
            "verdicts are a table)") in out
    assert "Your judge can't be asked again:" in out
    assert "not switched on yet" not in out


def test_ask_again_without_a_result(tmp_path, capsys):
    promptfoo_project(tmp_path, split(20, 16))
    code, out, _ = run(capsys, tmp_path, "--ask-again")
    assert code == 2 and "There is no result to ask about yet." in out


@pytest.mark.parametrize("times", ["0", "6", "x"])
def test_times_is_one_to_five(tmp_path, capsys, times):
    _checked(tmp_path)
    code, _, _ = run(capsys, tmp_path, "--ask-again", "--times", times)
    assert code == 2


def test_times_in_the_flags(tmp_path, capsys, no_processes):
    _checked(tmp_path)
    _local_promptfoo(tmp_path, no_processes)
    code, out, _ = run(capsys, tmp_path, "--ask-again", "--times", "3")
    assert code == 0 and "36 labeled answers × 3 times = 108 judge calls." in out


def test_judge_command_in_the_flags(tmp_path, capsys):
    _checked(tmp_path, maker=table_project)
    code, out, _ = run(capsys, tmp_path, "--ask-again", "--judge-command", "python judge.py")
    assert code == 2 and "This runs `python judge.py` 72 times." in out
    assert "--allow-calls 72" in out
