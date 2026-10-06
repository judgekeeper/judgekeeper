"""`judgekeeper setup`: set a project up in one step, with one yes for every file change.

It finds what there is (an eval tool's results, judgekeeper.record() files, or a results
file in the project's own format), maps an own-format file asking only what it cannot tell,
shows 3 answers as judgekeeper will read them, then lists every file change under one
question: judgekeeper.toml, the .gitignore line, the dev-requirements line. Nothing is
written before the yes, and the user's code is never edited. `start` then reads
judgekeeper.toml first.
"""

from __future__ import annotations

import builtins
import json
import tomllib

import pytest

from judgekeeper import own_format, recorder, setup_project, start
from judgekeeper.cli import main
from judgekeeper.config import load_section
from judgekeeper.gate import GateConfig
from tests.start_projects import (
    flat_jsonl,
    nested_runs_project,
    promptfoo_project,
    records_project,
    split,
)


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


@pytest.fixture(autouse=True)
def no_labeling(monkeypatch):
    calls = []

    def run_labeling(found, port, open_browser, say):
        calls.append(found)
        say("(labeling page)")
        return 0

    monkeypatch.setattr("judgekeeper.start_label.run_labeling", run_labeling)
    return calls


def setup(capsys, *argv):
    code = main(["setup", *map(str, argv)])
    out, err = capsys.readouterr()
    return code, out + err


def snapshot(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*")
            if p.is_file()}


# Runs, cases, A and B, at a terminal ---------------------------------------------------------

def test_nested_runs_asks_three_questions_and_one_yes(tmp_path, capsys, terminal):
    answers, asked = terminal
    nested_runs_project(tmp_path, runs=3, cases=8, rule_rows=1)
    answers += ["", "1", "", ""]  # each answer on its own; Safe wording; leave rules out; yes
    code, out = setup(capsys, tmp_path)
    assert code == 0, out
    assert len(asked) == 4
    assert "Count each as its own answer?" in asked[0]
    assert "Which judge do you want to check?" in out
    assert "Leave them out?" in asked[2]
    assert asked[3].strip() == "[Y/n]"
    # what it found and how it reads it
    assert "history/evals.jsonl looks like your judge's results in a format of its own" in out
    assert "cases[].A.output" in out and "cases[].A.scores.<criterion>.score" in out
    assert "Three answers as judgekeeper will read them:" in out
    assert "Safe wording: 0.9, pass (pass mark 0.5)" in out
    # the one question lists every change
    for bullet in ("save judgekeeper.toml (where your judge's results are and how to read them)",
                   "add .judgekeeper/ to .gitignore (your answers stay off Git)",
                   "add judgekeeper to requirements-dev.txt"):
        assert f"  • {bullet}" in out
    assert out.index("Three answers") < out.index("Set up judgekeeper in this project?")
    assert "Next: judgekeeper start" in out


def test_nested_runs_files_after_the_yes(tmp_path, capsys, terminal):
    answers, _ = terminal
    nested_runs_project(tmp_path, runs=3, cases=8, rule_rows=1)
    answers += ["", "1", "", ""]
    setup(capsys, tmp_path)
    settings = tomllib.loads((tmp_path / "judgekeeper.toml").read_text(encoding="utf-8"))
    start_table = settings["start"]
    assert start_table["source"] == "map"
    assert start_table["file"] == "history/evals.jsonl"
    assert start_table["judge"] == "Safe wording"
    assert start_table["pass_mark"] == 0.5
    assert start_table["map"]["each"] == "cases[]"
    assert start_table["map"]["sides"] == ["A", "B"]
    assert start_table["map"]["leave_out"] is True
    gitignore = (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert ".judgekeeper/*" in gitignore and "!.judgekeeper/baseline.json" in gitignore
    assert (tmp_path / "requirements-dev.txt").read_text(encoding="utf-8") == \
        "pytest\njudgekeeper\n"
    assert (tmp_path / "requirements.txt").read_text(encoding="utf-8") == \
        "deepeval==4.2.8\nanthropic\n"  # never the main requirements


def test_then_start_reads_judgekeeper_toml(tmp_path, capsys, terminal, no_labeling):
    answers, _ = terminal
    nested_runs_project(tmp_path, runs=3, cases=8, rule_rows=1)
    answers += ["", "1", "", ""]
    setup(capsys, tmp_path)
    answers += [""]  # start: open the labeling page? yes
    code = main(["start", str(tmp_path)])
    out = capsys.readouterr().out
    assert code == 0
    assert "Your judge's results: history/evals.jsonl, read as judgekeeper.toml says" in out
    assert "Your judge: Safe wording with claude-opus-5" in out
    (found,) = no_labeling
    assert found.tool == "mapped" and len(found.pool.answers) == 42  # 48 less 6 rule-made


def test_nothing_is_written_before_the_yes(tmp_path, capsys, terminal):
    answers, _ = terminal
    nested_runs_project(tmp_path)
    before = snapshot(tmp_path)
    answers += ["", "1", "", "n"]
    code, out = setup(capsys, tmp_path)
    assert code == 0
    assert snapshot(tmp_path) == before
    assert "Nothing was changed." in out


def test_one_side_when_each_is_not_its_own_answer(tmp_path, capsys, terminal):
    answers, _ = terminal
    nested_runs_project(tmp_path, rule_rows=0)
    answers += ["n", "2", "2", ""]  # not each; side B; Plain language; yes
    code, _ = setup(capsys, tmp_path)
    assert code == 0
    settings = tomllib.loads((tmp_path / "judgekeeper.toml").read_text(encoding="utf-8"))
    assert settings["start"]["map"]["sides"] == ["B"]
    assert settings["start"]["judge"] == "Plain language"


def test_all_judges_one_at_a_time(tmp_path, capsys, terminal):
    answers, _ = terminal
    nested_runs_project(tmp_path, rule_rows=0)
    answers += ["", "3", ""]
    setup(capsys, tmp_path)
    settings = tomllib.loads((tmp_path / "judgekeeper.toml").read_text(encoding="utf-8"))
    assert settings["start"]["judge"] == "*"


# Questions only when needed -------------------------------------------------------------

def test_a_flat_file_with_one_judge_asks_only_the_yes(tmp_path, capsys, terminal):
    answers, asked = terminal
    (tmp_path / ".git").mkdir()
    flat_jsonl(tmp_path / "evals" / "graded.jsonl")
    answers += [""]
    code, out = setup(capsys, tmp_path)
    assert code == 0 and len(asked) == 1
    assert "judgekeeper is not listed in your project's requirements; add it so teammates " \
           "get it" in out


def test_a_guess_it_is_not_sure_of_asks_one_confirm_line(tmp_path, capsys, terminal):
    answers, asked = terminal
    path = tmp_path / "out" / "graded.jsonl"
    path.parent.mkdir()
    path.write_text("".join(json.dumps({"q": f"Question {i}?", "text": f"An answer {i}.",
                                        "verdict": "pass" if i % 2 else "fail"}) + "\n"
                            for i in range(36)), encoding="utf-8")
    answers += ["n"]
    code, out = setup(capsys, path)
    assert code == 2  # nothing set up
    assert "Is this right?" in asked[0]
    assert own_format.AGENT_PROMPT in out  # the guesses were wrong: the converter prompt
    assert recorder.AGENT_PROMPT not in out
    assert "judgekeeper record --agent-prompt" in out
    assert not (tmp_path / "judgekeeper.toml").exists()


def test_a_file_it_cannot_map_offers_the_agent_prompt(tmp_path, capsys, terminal):
    """At a terminal, and still no question: there is nothing to ask about."""
    path = tmp_path / "scores.jsonl"
    path.write_text("".join(json.dumps({"question": f"q{i}", "score": 0.5}) + "\n"
                            for i in range(5)), encoding="utf-8")
    code, out = setup(capsys, path)
    assert code == 2
    assert "no answers" in out
    assert own_format.AGENT_PROMPT in out
    assert not (tmp_path / "judgekeeper.toml").exists()


def test_scores_outside_0_to_1_ask_for_the_pass_mark(tmp_path, capsys, terminal):
    answers, asked = terminal
    path = tmp_path / "graded.jsonl"
    path.write_text("".join(json.dumps({"question": f"q{i}", "answer": f"a{i}",
                                        "score": 1 + i % 5}) + "\n" for i in range(40)),
                    encoding="utf-8")
    answers += ["4", ""]
    code, _ = setup(capsys, path)
    assert code == 0 and "Pass when the score is at least" in asked[0]
    settings = tomllib.loads((tmp_path / "judgekeeper.toml").read_text(encoding="utf-8"))
    assert settings["start"]["pass_mark"] == 4


# Without a terminal ----------------------------------------------------------------------

def test_without_a_terminal_it_prints_the_list_and_exits_2(tmp_path, capsys):
    flat_jsonl(tmp_path / "evals" / "graded.jsonl")
    before = snapshot(tmp_path)
    code, out = setup(capsys, tmp_path)
    assert code == 2
    assert "Set up judgekeeper in this project?" in out and "  • save judgekeeper.toml" in out
    assert "judgekeeper setup --yes" in out
    assert snapshot(tmp_path) == before


def test_yes_answers_it(tmp_path, capsys):
    flat_jsonl(tmp_path / "evals" / "graded.jsonl")
    code, _ = setup(capsys, tmp_path, "--yes")
    assert code == 0 and (tmp_path / "judgekeeper.toml").is_file()


def test_several_judges_without_a_terminal_need_metric(tmp_path, capsys):
    nested_runs_project(tmp_path, rule_rows=0)
    code, out = setup(capsys, tmp_path, "--yes")
    assert code == 2 and "--metric" in out
    assert not (tmp_path / "judgekeeper.toml").exists()
    code, out = setup(capsys, tmp_path, "--yes", "--metric", "Plain language")
    assert code == 0
    assert "judge = \"Plain language\"" in (tmp_path / "judgekeeper.toml").read_text()


# Eval tools and records ------------------------------------------------------------------

def test_an_eval_tool_is_read_as_it_is(tmp_path, capsys):
    promptfoo_project(tmp_path, split(20, 16))
    code, out = setup(capsys, tmp_path, "--yes")
    assert code == 0
    assert "judgekeeper start reads them as they are" in out
    settings = tomllib.loads((tmp_path / "judgekeeper.toml").read_text(encoding="utf-8"))
    assert settings["start"]["source"] == "promptfoo"


def test_records_are_read_as_they_are(tmp_path, capsys):
    records_project(tmp_path, split(20, 16))
    code, out = setup(capsys, tmp_path, "--yes")
    assert code == 0 and "judgekeeper start reads them as they are" in out
    settings = tomllib.loads((tmp_path / "judgekeeper.toml").read_text(encoding="utf-8"))
    assert settings["start"]["source"] == "records"


def test_the_saved_tool_is_used_without_asking(tmp_path, capsys, no_labeling):
    promptfoo_project(tmp_path, split(20, 16))
    records_project(tmp_path, split(20, 16))
    (tmp_path / "judgekeeper.toml").write_text('[start]\nsource = "promptfoo"\n',
                                                encoding="utf-8")
    code = main(["start", str(tmp_path), "--yes"])
    capsys.readouterr()
    assert code == 0 and no_labeling[0].tool == "promptfoo"


def test_nothing_found_shows_the_three_doors(tmp_path, capsys):
    (tmp_path / "requirements.txt").write_text("deepeval\n", encoding="utf-8")
    code, out = setup(capsys, tmp_path, "--yes")
    assert code == 2
    assert "judgekeeper record --agent-prompt" in out
    assert "judgekeeper setup path/to/results.jsonl" in out
    assert not (tmp_path / "judgekeeper.toml").exists()


# Running it again ------------------------------------------------------------------------

def test_setup_again_offers_to_change_it(tmp_path, capsys, terminal):
    answers, asked = terminal
    flat_jsonl(tmp_path / "evals" / "graded.jsonl")
    answers += [""]
    setup(capsys, tmp_path)
    first = (tmp_path / "judgekeeper.toml").read_text(encoding="utf-8")
    answers += [""]  # set it up again? No (the default)
    code, out = setup(capsys, tmp_path)
    assert code == 0
    assert "judgekeeper.toml already says where your judge's results are" in out
    assert "Set it up again?" in asked[-1] and "[y/N]" in asked[-1]
    assert (tmp_path / "judgekeeper.toml").read_text(encoding="utf-8") == first


def test_setup_again_replaces_only_its_own_table(tmp_path, capsys, terminal):
    answers, _ = terminal
    flat_jsonl(tmp_path / "evals" / "graded.jsonl")
    (tmp_path / "judgekeeper.toml").write_text(
        "# my thresholds\n[gate]\nkappa_min = 0.7\n\n[start]\nsource = \"promptfoo\"\n",
        encoding="utf-8")
    answers += ["y", ""]
    code, out = setup(capsys, tmp_path)
    assert code == 0
    text = (tmp_path / "judgekeeper.toml").read_text(encoding="utf-8")
    data = tomllib.loads(text)
    assert data["gate"] == {"kappa_min": 0.7} and "# my thresholds" in text
    assert data["start"]["source"] == "map"
    assert "  • change the [start] table in judgekeeper.toml" in out
    assert load_section(tmp_path / "judgekeeper.toml", "gate", GateConfig(), ValueError
                        ).kappa_min == 0.7  # gate still reads the file


def test_a_changed_shape_says_to_run_setup_again(tmp_path, capsys, terminal):
    answers, _ = terminal
    path = nested_runs_project(tmp_path, rule_rows=0)
    answers += ["", "1", ""]
    setup(capsys, tmp_path)
    path.write_text(path.read_text().replace('"cases"', '"items"'), encoding="utf-8")
    code = main(["start", str(tmp_path), "--yes"])
    out = capsys.readouterr()
    assert code == 2
    assert "Your results file changed shape. Run judgekeeper setup again." in out.out + out.err


# The .gitignore line and the requirements line -------------------------------------------

def test_gitignore_only_in_a_git_repo_and_never_twice(tmp_path):
    assert setup_project.gitignore_change(tmp_path) is None  # not a Git repo
    (tmp_path / ".git").mkdir()
    change = setup_project.gitignore_change(tmp_path)
    change.apply()
    first = (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert first.startswith("# judgekeeper:")
    assert setup_project.gitignore_change(tmp_path) is None
    (tmp_path / ".gitignore").write_text("node_modules\n.judgekeeper/\n", encoding="utf-8")
    assert setup_project.gitignore_change(tmp_path) is None


def test_gitignore_keeps_what_is_there(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".gitignore").write_text("node_modules", encoding="utf-8")  # no last newline
    setup_project.gitignore_change(tmp_path).apply()
    lines = (tmp_path / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert lines[0] == "node_modules" and ".judgekeeper/*" in lines


PYPROJECT_GROUPS = '''[project]
name = "app"
dependencies = ["httpx"]

[dependency-groups]
dev = [
    "pytest>=8",
    "ruff"
]
'''


@pytest.mark.parametrize("files, where, check", [
    ({"pyproject.toml": PYPROJECT_GROUPS}, "the dev group in pyproject.toml",
     lambda d: d["dependency-groups"]["dev"] == ["pytest>=8", "ruff", "judgekeeper"]),
    ({"pyproject.toml": '[project]\nname = "app"\n\n[dependency-groups]\ndev = ["pytest"]\n'},
     "the dev group in pyproject.toml",
     lambda d: d["dependency-groups"]["dev"] == ["pytest", "judgekeeper"]),
    ({"pyproject.toml": '[project]\nname = "app"\n\n[project.optional-dependencies]\n'
                        'dev = [\n  "pytest",\n]\n'},
     "the dev extra in pyproject.toml",
     lambda d: d["project"]["optional-dependencies"]["dev"] == ["pytest", "judgekeeper"]),
    ({"requirements-dev.txt": "pytest\n"}, "requirements-dev.txt", None),
    ({"requirements-dev.in": "pytest"}, "requirements-dev.in", None),
])
def test_each_requirements_form_is_edited_once(tmp_path, files, where, check):
    for name, text in files.items():
        (tmp_path / name).write_text(text, encoding="utf-8")
    change = setup_project.requirements_change(tmp_path)
    assert change.text == f"add judgekeeper to {where}"
    change.apply()
    name = next(iter(files))
    text = (tmp_path / name).read_text(encoding="utf-8")
    if check:
        assert check(tomllib.loads(text))
    else:
        assert text.splitlines()[-1] == "judgekeeper"
    again = setup_project.requirements_change(tmp_path)
    assert again is None  # listed now


def test_the_first_requirements_form_that_exists_wins(tmp_path):
    (tmp_path / "pyproject.toml").write_text(PYPROJECT_GROUPS, encoding="utf-8")
    (tmp_path / "requirements-dev.txt").write_text("pytest\n", encoding="utf-8")
    assert "pyproject.toml" in setup_project.requirements_change(tmp_path).text


def test_already_listed_anywhere_is_not_added(tmp_path):
    (tmp_path / "requirements.txt").write_text("judgekeeper==0.2.0\n", encoding="utf-8")
    (tmp_path / "requirements-dev.txt").write_text("pytest\n", encoding="utf-8")
    assert setup_project.requirements_change(tmp_path) is None


def test_a_dev_list_with_an_include_group_still_gets_the_line(tmp_path):
    text = ('[project]\nname = "app"\n\n[dependency-groups]\n'
            'dev = ["pytest", {include-group = "lint"}]\nlint = ["ruff"]\n')
    (tmp_path / "pyproject.toml").write_text(text, encoding="utf-8")
    setup_project.requirements_change(tmp_path).apply()
    data = tomllib.loads((tmp_path / "pyproject.toml").read_text(encoding="utf-8"))
    assert data["dependency-groups"]["dev"] == ["pytest", {"include-group": "lint"},
                                                "judgekeeper"]


def test_an_unusual_pyproject_is_skipped_with_a_message(tmp_path):
    text = 'dependency-groups = { dev = ["pytest"] }\n\n[project]\nname = "app"\n'
    assert tomllib.loads(text)["dependency-groups"]["dev"] == ["pytest"]
    (tmp_path / "pyproject.toml").write_text(text, encoding="utf-8")
    change = setup_project.requirements_change(tmp_path)
    assert change.apply is None
    assert "add it to the dev group in pyproject.toml yourself" in change.text
    assert (tmp_path / "pyproject.toml").read_text(encoding="utf-8") == text


def test_no_dev_requirements_file_changes_nothing(tmp_path):
    (tmp_path / "requirements.txt").write_text("httpx\n", encoding="utf-8")
    change = setup_project.requirements_change(tmp_path)
    assert change.apply is None
    assert change.text == ("judgekeeper is not listed in your project's requirements; add it "
                           "so teammates get it")
