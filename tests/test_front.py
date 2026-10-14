"""`judgekeeper` with no command: find the eval tool, the results, the judge and its rule, run
the free checks, write .judgekeeper/judge.json, and end with exactly one `Next:` line.

A person and a coding agent both read the output, so it never holds an answer's text. At a
terminal a question is asked inline; without one it is printed in plain words with a `Next:`
line that names the flag answering it, and the exit code is 3.
"""

from __future__ import annotations

import builtins
import json
import re
import shlex
import tomllib

import pytest

from judgekeeper import __version__, front, judge_setup, start
from judgekeeper.cli import main
from judgekeeper.textio import quote_arg
from tests.start_projects import (
    deepeval_project,
    flat_jsonl,
    inspect_project,
    nested_runs_project,
    own_format_project,
    promptfoo_data,
    promptfoo_project,
    records_project,
    split,
    table_project,
)

TAG = " SECRET-7f3a"  # put into every question and answer, so a leak shows


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def terminal(monkeypatch):
    """A person at a terminal: `answers` are typed in order; `asked` keeps every prompt."""
    answers: list[str] = []
    asked: list[str] = []
    monkeypatch.setattr(start, "_interactive", lambda: True)

    def fake_input(prompt=""):
        asked.append(prompt)
        print(prompt)
        if not answers:
            raise AssertionError(f"an unexpected question: {prompt!r}")
        return answers.pop(0)

    monkeypatch.setattr(builtins, "input", fake_input)
    return answers, asked


def run(capsys, *argv):
    code = main([str(a) for a in argv])
    out, err = capsys.readouterr()
    return code, out, err


def next_lines(out: str) -> list[str]:
    """Each Next: paragraph (a Next: line and the lines it wraps onto), as one line."""
    lines = out.splitlines()
    found = []
    for i, line in enumerate(lines):
        if line.startswith("Next:"):
            para = [line]
            for more in lines[i + 1:]:
                if not more.strip() or more.startswith("Next:"):
                    break
                para.append(more)
            found.append(" ".join(para))
    return found


def assert_one_next_at_the_end(out: str) -> str:
    """Exactly one Next: paragraph, and it ends what is said: returned as one line."""
    lines = out.rstrip("\n").splitlines()
    assert len(next_lines(out)) == 1, out
    at = max(i for i, line in enumerate(lines) if line.startswith("Next:"))
    assert all(line.strip() for line in lines[at:]), out
    return next_lines(out)[0]


START = "Next: mark until the page says you have enough, then run `judgekeeper` again."


def flat(out: str) -> str:
    """The output with its wrapping undone."""
    return " ".join(out.split())


# One test per eval tool -----------------------------------------------------------------

def test_promptfoo(here, capsys):
    promptfoo_project(here, split(20, 16))
    code, out, err = run(capsys)
    assert code == 0, out + err
    assert out.splitlines()[:2] == [f"judgekeeper {__version__}", ""]
    assert out.splitlines()[2:10] == [
        "Step 1 of 5: Find", "",
        "Eval tool:   promptfoo",
        "Answers:     36 answers from your app, each graded by your judge",
        "             (read from results.json)",
        "Judge:       openai:gpt-4.1-mini",
        'Judge rule:  "Is polite and correct. Second line of the rubric."', ""]
    assert "Your judge's grades: 20 Pass, 16 Fail." in out
    assert "Free check (no AI call): every answer got a clear Pass or Fail." in out
    assert assert_one_next_at_the_end(out) == START
    assert err == ""


def test_deepeval(here, capsys):
    deepeval_project(here, split(18, 17))
    code, out, _ = run(capsys)
    assert code == 0, out
    assert "Eval tool:   DeepEval" in out
    assert "(read from .deepeval/.latest_run_full.json)" in out and "35 answers" in out
    assert "Judge:       Correctness [GEval], gpt-4.1" in out and "Judge rule:  " in out
    assert "Your judge's grades: 18 Pass, 17 Fail." in out
    assert assert_one_next_at_the_end(out) == START


def test_inspect(here, capsys):
    inspect_project(here, split(16, 16))
    code, out, _ = run(capsys)
    assert code == 0, out
    assert "Eval tool:   Inspect AI" in out and "32 answers" in out
    assert "(read from logs/2026-10-02_support.json)" in out
    assert "Your judge's grades: 16 Pass, 16 Fail." in out
    assert assert_one_next_at_the_end(out) == START


def test_a_table_says_which_columns_were_read(here, capsys):
    table_project(here, split(15, 15), model="claude-haiku-4-5")
    code, out, _ = run(capsys)
    assert code == 0, out
    assert "Eval tool:   your own CSV file" in out and "(read from results.csv)" in out
    assert "Read the columns input, output, verdict and model." in out
    assert "Judge:       claude-haiku-4-5" in out
    assert "Judge rule:  not in your results" in out
    assert "The first 3 rows" not in out
    assert assert_one_next_at_the_end(out) == START


def test_records(here, capsys):
    records_project(here, split(16, 16))
    code, out, _ = run(capsys)
    assert code == 0, out
    assert "Eval tool:   judgekeeper.record() in your code" in out
    assert "(read from .judgekeeper/records/, 1 file)" in out and "32 answers" in out
    assert "Judge:       claude-opus-5" in out and 'Judge rule:  "Be polite."' in out
    assert assert_one_next_at_the_end(out) == START


def test_own_format_with_yes_saves_the_map_and_reads_it(here, capsys):
    flat_jsonl(here / "evals" / "graded.jsonl")
    code, out, _ = run(capsys, "--yes")
    assert code == 0, out
    assert "Eval tool:   your own format" in out and "36 answers" in out
    assert "(read from evals/graded.jsonl)" in out
    assert "  input:           question" in out  # which parts were read: paths only
    assert "Saved judgekeeper.toml" in out
    saved = tomllib.loads((here / "judgekeeper.toml").read_text(encoding="utf-8"))["start"]
    assert saved["source"] == "map" and saved["file"] == "evals/graded.jsonl"
    assert assert_one_next_at_the_end(out) == START


def test_a_path_is_repeated_in_the_next_line(tmp_path, capsys):
    promptfoo_project(tmp_path / "proj", split(20, 16))
    code, out, _ = run(capsys, tmp_path / "proj")
    assert code == 0
    assert assert_one_next_at_the_end(out) == START.replace(
        "`judgekeeper`", f"`judgekeeper {quote_arg(tmp_path / 'proj')}`")


def test_a_long_rule_is_one_line_cut_short(here, capsys):
    rule = "Be kind. " * 60
    promptfoo_project(here, split(20, 16), rubric=rule)
    _, out, _ = run(capsys)
    lines = out.splitlines()
    at = next(i for i, x in enumerate(lines) if x.startswith("Judge rule:  "))
    quoted = lines[at][lines[at].index('"') + 1:lines[at].rindex('"')]
    assert len(quoted) <= front.RULE_SHOWN and quoted.endswith("…")
    assert lines[at + 1] == "             (shortened; full rule in promptfooconfig.yaml)"


# The free checks ------------------------------------------------------------------------

def test_answers_with_no_real_verdict_are_left_out_and_listed(here, capsys):
    promptfoo_project(here, [*split(18, 16), None, None, None])
    code, out, _ = run(capsys)
    assert code == 0, out
    assert "37 answers from your app" in out
    assert "Your judge's grades: 18 Pass, 16 Fail." in out
    block = flat(out[out.index("Free check (no AI call):"):out.index("Next:")])
    assert "Free check (no AI call): your judge made no real decision on 3 of 37 answers" \
        in block
    assert "left out" in block
    assert "The list is in .judgekeeper/judge-check.csv." in block
    rows = (here / ".judgekeeper" / "judge-check.csv").read_text(encoding="utf-8").splitlines()
    assert len(rows) == 1 + 3


def test_judge_json_has_every_field(here, capsys):
    promptfoo_project(here, split(20, 16))
    run(capsys)
    data = json.loads((here / ".judgekeeper" / "judge.json").read_text(encoding="utf-8"))
    assert set(data) == {"setup", "setup_hash", "first_seen", "judgekeeper_version", "metric"}
    setup = data["setup"]
    assert setup["tool"] == "promptfoo"
    assert "tool_version" in setup and "version_from" in setup
    assert setup["models"] == ["openai:gpt-4.1-mini"] and setup["kind"] == "one call"
    assert setup["rule_hash"].startswith("sha256:")
    assert "pass_mark" in setup and "prompt_hash" in setup and "temperature" in setup
    assert data["setup_hash"].startswith("sha256:")
    assert data["judgekeeper_version"] == __version__
    assert data["first_seen"].endswith("Z")


def test_the_rule_hash_follows_the_rule(here, capsys):
    promptfoo_project(here, split(20, 16), rubric="Be polite.")
    first = judge_setup.of(start.find_judge(here))
    promptfoo_project(here, split(20, 16), rubric="Be polite and short.")
    second = judge_setup.of(start.find_judge(here))
    assert first["rule_hash"] != second["rule_hash"]


def test_the_tool_version_is_read_when_the_results_say_it(here, capsys):
    data = promptfoo_data(split(20, 16))
    data["metadata"]["promptfooVersion"] = "0.123.1"
    (here / "results.json").write_text(json.dumps(data), encoding="utf-8")
    run(capsys)
    saved = json.loads((here / ".judgekeeper" / "judge.json").read_text(encoding="utf-8"))
    assert saved["setup"]["tool_version"] == "0.123.1"
    assert saved["setup"]["version_from"] == "results"


def test_too_few_answers_needs_the_person(here, capsys):
    promptfoo_project(here, split(6, 4))
    code, out, _ = run(capsys)
    assert code == 3
    assert "You have 10 answers" in out
    line = assert_one_next_at_the_end(out)
    assert line.endswith("or mark these 10 now with `judgekeeper mark`.")
    assert "--yes" not in line and "judgekeeper start" not in line


# No answer text, ever ----------------------------------------------------------------------

MAKERS = {
    "promptfoo": lambda root: promptfoo_project(root, [*split(18, 16), None], tag=TAG),
    "deepeval": lambda root: deepeval_project(root, split(18, 17), tag=TAG),
    "inspect": lambda root: inspect_project(root, [*split(16, 16), "P"], tag=TAG),
    "table": lambda root: table_project(root, [*split(15, 15), "maybe"], tag=TAG),
    "records": lambda root: records_project(root, split(16, 16), tag=TAG),
    "few": lambda root: promptfoo_project(root, split(3, 3), tag=TAG),
}


@pytest.mark.parametrize("tool", MAKERS)
def test_no_answer_text_in_the_output(here, capsys, tool):
    MAKERS[tool](here)
    _, out, err = run(capsys)
    assert "SECRET-7f3a" not in out + err
    assert "Question 1?" not in out + err and "Answer 1." not in out + err


def test_no_answer_text_from_an_own_format_file(here, capsys):
    nested_runs_project(here, rule_rows=0)
    _, out, err = run(capsys, "--yes", "--metric", "Safe wording")
    assert "Question " not in out + err and "Answer " not in out + err


def test_empty_answers_passed_are_counted_without_their_text(here, capsys):
    promptfoo_project(here, split(18, 16), outputs=["", *[f"text{i}{TAG}" for i in range(33)]])
    code, out, _ = run(capsys)
    assert code == 0
    assert "Free check (no AI call): your judge passed 1 empty answer." in flat(out)
    assert "SECRET-7f3a" not in out


# Questions without a terminal: plain question, a Next: line with the flag, exit 3 ------------

def test_several_tools(here, capsys):
    promptfoo_project(here, split(20, 16))
    records_project(here, split(16, 16))
    code, out, _ = run(capsys)
    assert code == 3
    assert "Saved results from more than one eval tool:" in out
    assert assert_one_next_at_the_end(out) == (
        "Next: choose which eval tool's results to check (records, promptfoo), then run "
        "`judgekeeper --tool NAME`.")
    assert not (here / ".judgekeeper" / "judge.json").exists()
    code, out, _ = run(capsys, "--tool", "promptfoo")
    assert code == 0
    assert assert_one_next_at_the_end(out) == START.replace(
        "`judgekeeper`", "`judgekeeper --tool promptfoo`")


def test_several_judges(here, capsys):
    records_project(here, split(16, 16), name="helpfulness")
    records_project(here, split(16, 16), name="safety", pid=4102)
    code, out, _ = run(capsys)
    assert code == 3
    assert assert_one_next_at_the_end(out) == (
        "Next: choose which judge to check (helpfulness, safety), then run "
        "`judgekeeper --metric NAME`.")
    code, out, _ = run(capsys, "--metric", "safety")
    assert code == 0, out
    assert "Judge:       safety, claude-opus-5" in out


def test_a_judge_name_with_spaces_is_quoted(here, capsys):
    records_project(here, split(16, 16), name="Safe wording")
    records_project(here, split(16, 16), name="Plain language", pid=4102)
    code, out, _ = run(capsys)
    assert code == 3
    assert "(\"Plain language\", \"Safe wording\")" in next_lines(out)[0] or \
        "('Plain language', 'Safe wording')" in next_lines(out)[0]


def test_scores_need_a_pass_mark(here, capsys):
    table_project(here, ["0.9"] * 16 + ["0.2"] * 16)
    code, out, _ = run(capsys)
    assert code == 3
    assert "scores" in out
    line = assert_one_next_at_the_end(out)
    assert line.startswith("Next: decide which score counts as a pass")
    assert "`judgekeeper --pass-if \"score>=N\"`" in line
    code, out, _ = run(capsys, "--pass-if", "score>=0.5")
    assert code == 0, out
    assert "Your judge's grades: 16 Pass, 16 Fail." in out
    assert "Pass mark:   score 0.5 or more" in out


def test_words_need_a_label_map(here, capsys):
    table_project(here, ["good"] * 16 + ["bad"] * 16)
    code, out, _ = run(capsys)
    assert code == 3
    line = assert_one_next_at_the_end(out)
    assert "which of these mean Pass and which mean Fail (bad, good)" in line
    assert "--label-map" in line
    code, out, _ = run(capsys, "--label-map", "good=pass,bad=fail")
    assert code == 0, out


def test_inspect_partial_credit(here, capsys):
    inspect_project(here, [*split(16, 16), "P", "P"])
    code, out, _ = run(capsys)
    assert code == 3
    line = assert_one_next_at_the_end(out)
    assert "partial credit" in out and "--label-map P=pass" in line
    code, _, _ = run(capsys, "--label-map", "P=fail")
    assert code == 0


def test_an_own_format_needs_the_persons_yes_before_judgekeeper_toml(here, capsys):
    flat_jsonl(here / "evals" / "graded.jsonl")
    code, out, _ = run(capsys)
    assert code == 3
    assert not (here / "judgekeeper.toml").exists()
    assert "  1. Save how to read evals/graded.jsonl in judgekeeper.toml?" in out
    assert "`judgekeeper --yes`" in assert_one_next_at_the_end(out)
    code, out, _ = run(capsys, "--yes")
    assert code == 0 and (here / "judgekeeper.toml").is_file()


def test_own_format_questions_take_their_flag(here, capsys):
    nested_runs_project(here, rule_rows=0)  # two answers per case, two judges
    code, out, _ = run(capsys)
    assert code == 3
    line = assert_one_next_at_the_end(out)
    assert "which judge to check" in line and "`judgekeeper --metric NAME`" in line
    code, out, _ = run(capsys, "--metric", "Safe wording")
    assert code == 3
    assert f"`judgekeeper --metric {quote_arg('Safe wording')} --yes`" in \
        assert_one_next_at_the_end(out)
    code, out, _ = run(capsys, "--metric", "Safe wording", "--yes")
    assert code == 0, out
    saved = tomllib.loads((here / "judgekeeper.toml").read_text(encoding="utf-8"))["start"]
    assert saved["judge"] == "Safe wording" and saved["map"]["sides"] == ["A", "B"]


@pytest.fixture
def confirmed(monkeypatch):
    """Every yes/no question `judgekeeper` asks, in order."""
    asked: list[str] = []
    real = front.FrontTalk.confirm

    def spy(self, question, *args, **kwargs):
        asked.append(question)
        return real(self, question, *args, **kwargs)

    monkeypatch.setattr(front.FrontTalk, "confirm", spy)
    return asked


def files(root) -> dict:
    return {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}


@pytest.mark.parametrize("make", [
    lambda root: nested_runs_project(root),
    lambda root: own_format_project(root, cases=40),
    lambda root: promptfoo_project(root, split(20, 16), description="another bot")])
def test_following_each_next_line_shows_every_question_before_yes(here, capsys, confirmed,
                                                                   make):
    """--yes answers only the questions printed in the last run, and a run that ends with
    questions writes nothing."""
    make(here)
    argv: list[str] = []
    out, answered = "", 0
    for _ in range(6):
        shown, before = out, files(here)
        confirmed.clear()
        code, out, _ = run(capsys, *argv)
        if "--yes" in argv:
            for question in confirmed:
                assert " ".join(question.split()) in flat(shown), question
            answered += len(confirmed)
        line = assert_one_next_at_the_end(out)
        if code == 0:
            break
        assert code == 3, out
        assert files(here) == before, out
        commands = re.findall(r"`(judgekeeper [^`]*)`", line)  # say yes when asked
        command = next((c for c in commands if "--yes" in c), commands[0])
        argv = ["Safe wording" if a == "NAME" else a for a in shlex.split(command)[1:]]
    assert code == 0 and answered, out
    assert line == START


def test_the_questions_are_listed_together_after_the_checks(here, capsys):
    nested_runs_project(here)
    code, out, _ = run(capsys, "--metric", "Safe wording")
    assert code == 3
    assert "(read from history/evals.jsonl, 3 lines)" in out  # the counts the questions lead to
    assert "42 answers from your app" in out
    heading = front.QUESTIONS.format(which="these 3 questions")
    listed = flat(out[out.index(heading):])
    assert out.index("Free check") < out.index(heading)
    assert "1. Each item has 2 answers (A and B). Count each as its own answer?" in listed
    assert "2. 6 answers have an error or a score made by a rule" in listed
    assert "3. Save how to read history/evals.jsonl in judgekeeper.toml?" in listed
    command = f"judgekeeper --metric {quote_arg('Safe wording')}"
    assert assert_one_next_at_the_end(out) == (
        f"Next: run `{command}` in a terminal to answer, or `{command} --yes` to say yes to "
        "all.")
    assert not (here / ".judgekeeper").exists() and not (here / "judgekeeper.toml").exists()


@pytest.mark.parametrize("make", [
    lambda root: nested_runs_project(root),  # which judge
    lambda root: (promptfoo_project(root, split(20, 16)),  # which tool
                  records_project(root, split(16, 16))),
    lambda root: table_project(root, ["0.9"] * 16 + ["0.2"] * 16)])  # which pass mark
def test_a_choice_question_never_carries_yes(here, capsys, make):
    make(here)
    code, out, _ = run(capsys, "--yes")
    assert code == 3
    line = assert_one_next_at_the_end(out)
    assert "`judgekeeper " in line and "--yes" not in line


def test_promptfoo_results_from_another_project(here, capsys):
    promptfoo_project(here, split(20, 16), description="another bot")
    code, out, _ = run(capsys)
    assert code == 3
    assert "looks like it is from another project" in out
    assert "`judgekeeper --yes`" in assert_one_next_at_the_end(out)
    code, _, _ = run(capsys, "--yes")
    assert code == 0


# At a terminal: the same questions, asked inline ------------------------------------------

def test_at_a_terminal_the_tool_is_asked_and_saved_after_yes(here, capsys, terminal):
    answers, asked = terminal
    promptfoo_project(here, split(20, 16))
    records_project(here, split(16, 16))
    answers += ["2", ""]  # promptfoo; save? yes
    code, out, _ = run(capsys)
    assert code == 0, out
    assert "Saved results from more than one eval tool:" in out
    assert "judgekeeper.toml" in asked[-1]
    saved = tomllib.loads((here / "judgekeeper.toml").read_text(encoding="utf-8"))["start"]
    assert saved["source"] == "promptfoo"
    assert next_lines(out) == [START]
    code, out, _ = run(capsys)  # asked once: now read from judgekeeper.toml
    assert code == 0 and "Step 2 of 5: Mark" in out and "Saved results from" not in out


def test_at_a_terminal_no_keeps_judgekeeper_toml_away(here, capsys, terminal):
    answers, _ = terminal
    records_project(here, split(16, 16), name="helpfulness")
    records_project(here, split(16, 16), name="safety", pid=4102)
    answers += ["2", "n"]
    code, out, _ = run(capsys)
    assert code == 0, out
    assert not (here / "judgekeeper.toml").exists()
    assert assert_one_next_at_the_end(out) == START.replace(
        "`judgekeeper`", "`judgekeeper --metric safety`")


def test_at_a_terminal_the_pass_mark_is_asked(here, capsys, terminal):
    answers, asked = terminal
    table_project(here, ["0.9"] * 16 + ["0.2"] * 16)
    answers += ["0.5"]
    code, out, _ = run(capsys)
    assert code == 0, out
    assert "Pass when the score is at least" in asked[0]
    assert "--pass-if" in next_lines(out)[0]


def test_at_a_terminal_an_own_format_is_mapped_and_saved(here, capsys, terminal):
    answers, asked = terminal
    nested_runs_project(here, rule_rows=1)
    answers += ["", "", "1", "", ""]  # right; each its own; Safe wording; rules out; save
    code, out, _ = run(capsys)
    assert code == 0, out
    assert ("Is this how judgekeeper should read history/evals.jsonl (the lines under \"How judgekeeper "
            "reads it\")?") in asked[0]
    assert "judgekeeper.toml" in asked[-1]
    saved = tomllib.loads((here / "judgekeeper.toml").read_text(encoding="utf-8"))["start"]
    assert saved["judge"] == "Safe wording" and saved["map"]["leave_out"] is True
    assert "Question " not in out and "Answer " not in out
    assert next_lines(out) == [START]


# Nothing found, and the MLflow leftovers --------------------------------------------------

def test_nothing_found_names_the_folder_not_its_path(here, capsys):
    code, out, _ = run(capsys)
    assert code == 3
    assert f"No eval results found in this folder ({here.name})." in out
    assert str(here) not in out
    assert assert_one_next_at_the_end(out) == (
        "Next: run your eval once from this folder, then run `judgekeeper` again. If your "
        "results are in another folder, run `judgekeeper` from there.")


def test_nothing_found_names_the_eval_tool_in_the_project(here, capsys):
    (here / "requirements.txt").write_text("deepeval\n", encoding="utf-8")
    code, out, _ = run(capsys)
    assert code == 3
    assert "Found DeepEval in this folder (requirements.txt), but no saved results yet." in \
        flat(out)
    assert assert_one_next_at_the_end(out) == (
        "Next: run your eval once from this folder, then run `judgekeeper` again.")


def test_promptfoo_config_without_results_points_at_the_export(here, capsys):
    (here / "promptfooconfig.yaml").write_text("description: x\n", encoding="utf-8")
    code, out, _ = run(capsys)
    assert code == 3
    line = assert_one_next_at_the_end(out)
    assert "promptfoo export eval latest -o promptfoo-results.json" in line


def test_a_tracking_server_says_what_works_instead(here, capsys):
    code, out, _ = run(capsys, "--tracking-uri", "http://127.0.0.1:5000")
    assert code == 3
    assert "tracking server" in out
    assert "mlflow.db" in out and "mlruns/" in out
    line = assert_one_next_at_the_end(out)
    assert "--tracking-uri" in line


def test_a_tracking_server_points_at_a_local_store_when_there_is_one(here, capsys):
    (here / "mlflow.db").write_bytes(b"")
    code, out, _ = run(capsys, "--tracking-uri", "https://mlflow.example.com")
    assert code == 3
    assert "`judgekeeper mlflow.db`" in assert_one_next_at_the_end(out)


# Usage --------------------------------------------------------------------------------------

def test_a_missing_path_is_a_usage_error(here, capsys):
    code, _, err = run(capsys, here / "nope")
    assert code == 2 and "not found" in err


def test_a_wrong_tool_name_is_a_usage_error(here, capsys):
    code, _, _ = run(capsys, "--tool", "nope")
    assert code == 2


def test_the_question_exit_code_is_3():
    assert front.EXIT_NEEDS_YOU == 3


def test_setup_is_removed(here, capsys):
    code, out, err = run(capsys, "setup")
    assert code == 2 and out == ""
    assert err == "judgekeeper setup was removed. Run judgekeeper in your project.\n"


def test_help_lists_the_flags_and_mark(capsys):
    code, out, _ = run(capsys, "--help")
    assert code == 0
    for flag in ("--tool", "--metric", "--experiment", "--tracking-uri", "--pass-if",
                 "--label-map", "--judge-model", "--fields", "--yes"):
        assert flag in out
    assert "mark" in out and "setup" not in out
