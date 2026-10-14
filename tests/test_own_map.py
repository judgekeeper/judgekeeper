"""`judgekeeper` on results saved in a project's own format (own_map.py).

It finds a file that looks like a judge's results, shows how it reads it (paths only, never a
value), asks only what the file cannot tell, and keeps the map in judgekeeper.toml after one
yes. Nothing is written to the project before that yes (only judgekeeper's own folder), and
the user's code is never edited. `start` then reads judgekeeper.toml first.
"""

from __future__ import annotations

import builtins
import json
import tomllib

import pytest

from judgekeeper import background, start
from judgekeeper.cli import main
from judgekeeper.readers.mapped import CHANGED_SHAPE
from judgekeeper.textio import quote_arg
from tests.start_projects import (
    flat_jsonl,
    nested_runs_project,
    promptfoo_project,
    records_project,
    split,
)
from tests.test_front import next_lines


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

    def run_labeling(found, port, open_browser, say, command="judgekeeper start"):
        calls.append(found)
        say("(labeling page)")
        return 0

    monkeypatch.setattr("judgekeeper.start_label.run_labeling", run_labeling)
    return calls


def check(capsys, *argv):
    code = main([str(a) for a in argv])
    out, err = capsys.readouterr()
    return code, out + err


def snapshot(root):
    """Every file of the project, except judgekeeper's own folder."""
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*")
            if p.is_file() and ".judgekeeper" not in p.relative_to(root).parts}


def saved(root) -> dict:
    return tomllib.loads((root / "judgekeeper.toml").read_text(encoding="utf-8"))["start"]


# Runs, cases, A and B, at a terminal ---------------------------------------------------------

def test_nested_runs_asks_four_questions_and_one_yes(tmp_path, capsys, terminal):
    answers, asked = terminal
    nested_runs_project(tmp_path, runs=3, cases=8, rule_rows=1)
    answers += ["", "", "1", "", ""]  # right; each on its own; Safe wording; rules out; yes
    code, out = check(capsys, tmp_path)
    assert code == 0, out
    assert len(asked) == 5
    assert "Is this how judgekeeper should read " in asked[0]
    assert "Count each as its own answer?" in asked[1]
    assert "Which judge do you want to check?" in out
    assert "Leave them out?" in asked[3]
    assert "judgekeeper.toml" in asked[4]
    assert "history/evals.jsonl looks like your judge's results in a format of its own" in out
    assert "cases[].A.output" in out and "cases[].A.scores.<criterion>.score" in out
    assert "Question " not in out and "Answer " not in out  # paths, never values
    assert "Eval tool:   your own format" in out
    assert "42 answers from your app" in out
    assert "(read from history/evals.jsonl, 3 lines)" in out
    assert "The marking page is open in your browser." in out


def fresh(root):
    """Close the page `judgekeeper` opened and clear .judgekeeper/ (judgekeeper.toml stays),
    so `start` begins anew."""
    import shutil

    background.stop(root / ".judgekeeper")
    shutil.rmtree(root / ".judgekeeper")


def test_nested_runs_files_after_the_yes(tmp_path, capsys, terminal):
    answers, _ = terminal
    nested_runs_project(tmp_path, runs=3, cases=8, rule_rows=1)
    answers += ["", "", "1", "", ""]
    check(capsys, tmp_path)
    table = saved(tmp_path)
    assert table["source"] == "map"
    assert table["file"] == "history/evals.jsonl"
    assert table["judge"] == "Safe wording"
    assert table["pass_mark"] == 0.5
    assert table["map"]["each"] == "cases[]"
    assert table["map"]["sides"] == ["A", "B"]
    assert table["map"]["leave_out"] is True
    assert not (tmp_path / ".gitignore").exists()  # .judgekeeper/ has its own
    assert (tmp_path / "requirements-dev.txt").read_text(encoding="utf-8") == "pytest\n"


def test_then_start_reads_judgekeeper_toml(tmp_path, capsys, terminal, no_labeling):
    answers, _ = terminal
    nested_runs_project(tmp_path, runs=3, cases=8, rule_rows=1)
    answers += ["", "", "1", "", ""]
    check(capsys, tmp_path)
    fresh(tmp_path)
    answers += [""]  # start: open the labeling page? yes
    code = main(["start", str(tmp_path)])
    out = capsys.readouterr().out
    assert code == 0
    assert "  Eval tool       your own format (read as judgekeeper.toml says)" in out
    assert "  Judge model     claude-opus-5" in out
    (found,) = no_labeling
    assert found.tool == "mapped" and len(found.pool.answers) == 42  # 48 less 6 rule-made


def test_then_judgekeeper_reads_it_without_a_question(tmp_path, capsys, terminal):
    answers, asked = terminal
    nested_runs_project(tmp_path, rule_rows=0)
    answers += ["", "", "1", ""]
    check(capsys, tmp_path)
    before = len(asked)
    fresh(tmp_path)
    code, out = check(capsys, tmp_path)
    assert code == 0 and len(asked) == before
    assert "Read as judgekeeper.toml says: input prompt, answer <side>.output" in " ".join(
        out.split())
    code, out = check(capsys, tmp_path)  # marking started: straight to marking
    assert code == 0 and len(asked) == before
    assert "Step 2 of 5: Mark" in out


def test_nothing_is_written_before_the_yes(tmp_path, capsys, terminal):
    answers, _ = terminal
    nested_runs_project(tmp_path)
    before = snapshot(tmp_path)
    answers += ["", "", "1", "", "n"]
    code, out = check(capsys, tmp_path)
    assert code == 0
    assert snapshot(tmp_path) == before
    assert "Nothing was saved." in out
    assert next_lines(out)[-1].startswith("Next: nothing.")


def test_one_side_when_each_is_not_its_own_answer(tmp_path, capsys, terminal):
    answers, _ = terminal
    nested_runs_project(tmp_path, rule_rows=0)
    answers += ["", "n", "2", "2", ""]  # right; not each; side B; Plain language; yes
    code, out = check(capsys, tmp_path)
    assert code == 3  # 24 answers: too few for a first result, and said so
    assert "You have 24 answers" in out
    assert saved(tmp_path)["map"]["sides"] == ["B"]
    assert saved(tmp_path)["judge"] == "Plain language"


def test_all_judges_one_at_a_time(tmp_path, capsys, terminal):
    answers, _ = terminal
    nested_runs_project(tmp_path, rule_rows=0)
    answers += ["", "", "3", "1", ""]  # right; each; all; Plain language for now; save
    code, out = check(capsys, tmp_path)
    assert code == 0, out
    assert saved(tmp_path)["judge"] == "*"
    assert "Judge:       Plain language, " in out


# Questions only when needed -------------------------------------------------------------

def test_a_flat_file_with_one_judge_asks_only_whether_it_is_right_and_the_yes(
        tmp_path, capsys, terminal):
    answers, asked = terminal
    flat_jsonl(tmp_path / "evals" / "graded.jsonl")
    answers += ["", ""]
    code, _ = check(capsys, tmp_path)
    assert code == 0 and len(asked) == 2 and "Is this how judgekeeper should read " in asked[0]


def test_a_guess_none_of_whose_parts_fit_asks_for_a_converter(tmp_path, capsys, terminal):
    answers, asked = terminal
    path = tmp_path / "out" / "graded.jsonl"
    path.parent.mkdir()
    path.write_text("".join(json.dumps({"q": f"Question {i}?", "text": f"An answer {i}.",
                                        "verdict": "pass" if i % 2 else "fail"}) + "\n"
                            for i in range(36)), encoding="utf-8")
    answers += ["n", "9"]  # not right; none of the parts fit
    code, out = check(capsys, path)
    assert code == 3
    assert "Is this how judgekeeper should read " in asked[0]
    last = next_lines(out)[-1]
    assert last.startswith("Next: turn graded.jsonl into a CSV")
    assert "id, input, output, verdict (pass or fail) and reason" in last
    assert not (tmp_path / "judgekeeper.toml").exists()


def test_a_file_it_cannot_map_asks_for_a_converter(tmp_path, capsys):
    path = tmp_path / "scores.jsonl"
    path.write_text("".join(json.dumps({"question": f"q{i}", "score": 0.5}) + "\n"
                            for i in range(5)), encoding="utf-8")
    code, out = check(capsys, path)
    assert code == 3
    assert "judgekeeper cannot read scores.jsonl by itself: " in out and "no answers" in out
    assert "into a CSV with the columns" in next_lines(out)[-1]
    assert not (tmp_path / "judgekeeper.toml").exists()


def test_scores_outside_0_to_1_ask_for_the_pass_mark(tmp_path, capsys, terminal):
    answers, asked = terminal
    path = tmp_path / "graded.jsonl"
    path.write_text("".join(json.dumps({"question": f"q{i}", "answer": f"a{i}",
                                        "score": 1 + i % 5}) + "\n" for i in range(40)),
                    encoding="utf-8")
    answers += ["", "4", ""]
    code, _ = check(capsys, path)
    assert code == 0 and "Pass when the score is at least" in asked[1]
    assert saved(tmp_path)["pass_mark"] == 4


def test_without_a_terminal_the_pass_mark_is_a_flag(tmp_path, capsys):
    path = tmp_path / "graded.jsonl"
    path.write_text("".join(json.dumps({"question": f"q{i}", "answer": f"a{i}",
                                        "score": 1 + i % 5}) + "\n" for i in range(40)),
                    encoding="utf-8")
    code, out = check(capsys, path, "--yes")
    assert code == 3
    assert next_lines(out)[-1] == (
        "Next: decide which score counts as a pass, then run "
        f"`judgekeeper {quote_arg(path)} --pass-if \"score>=N\"`.")
    code, out = check(capsys, path, "--yes", "--pass-if", "score>=4")
    assert code == 0, out
    assert saved(tmp_path)["pass_mark"] == 4
    code, _ = check(capsys, path, "--yes", "--pass-if", "score<4")
    assert code == 2


# Without a terminal ----------------------------------------------------------------------

def test_without_a_terminal_it_stops_at_the_question_before_saving(tmp_path, capsys):
    flat_jsonl(tmp_path / "evals" / "graded.jsonl")
    before = snapshot(tmp_path)
    code, out = check(capsys, tmp_path)
    assert code == 3
    assert "Save how to read evals/graded.jsonl in judgekeeper.toml?" in out
    assert f"or `judgekeeper {quote_arg(tmp_path)} --yes` to say yes." in next_lines(out)[-1]
    assert snapshot(tmp_path) == before


def test_yes_answers_it(tmp_path, capsys):
    flat_jsonl(tmp_path / "evals" / "graded.jsonl")
    code, _ = check(capsys, tmp_path, "--yes")
    assert code == 0 and (tmp_path / "judgekeeper.toml").is_file()


def test_several_judges_without_a_terminal_need_metric(tmp_path, capsys):
    nested_runs_project(tmp_path, rule_rows=0)
    code, out = check(capsys, tmp_path, "--yes")
    assert code == 3 and "--metric" in next_lines(out)[-1]
    assert not (tmp_path / "judgekeeper.toml").exists()
    code, out = check(capsys, tmp_path, "--yes", "--metric", "Plain language")
    assert code == 0
    assert "judge = \"Plain language\"" in (tmp_path / "judgekeeper.toml").read_text(
        encoding="utf-8")


def test_a_judge_it_does_not_know_is_a_usage_error(tmp_path, capsys):
    nested_runs_project(tmp_path, rule_rows=0)
    code, out = check(capsys, tmp_path, "--yes", "--metric", "nope")
    assert code == 2 and "no judge named 'nope'" in out


def test_without_a_terminal_each_answer_question_takes_yes(tmp_path, capsys, monkeypatch):
    from tests.start_projects import own_format_project

    monkeypatch.chdir(tmp_path)
    own_format_project(tmp_path)  # each case has two answers, A and B
    code, out = check(capsys)
    assert code == 3, out
    assert ("1. Each item has 2 answers (A and B). Count each as its own answer?"
            in " ".join(out.split()))
    assert next_lines(out)[-1] == (
        "Next: run `judgekeeper` in a terminal to answer, or `judgekeeper --yes` to say yes "
        "to all.")


# Eval tools and records are read as they are ----------------------------------------------

def test_an_eval_tool_is_read_as_it_is(tmp_path, capsys):
    promptfoo_project(tmp_path, split(20, 16))
    code, _ = check(capsys, tmp_path, "--yes")
    assert code == 0
    assert not (tmp_path / "judgekeeper.toml").exists()  # nothing was asked


def test_the_saved_tool_is_used_without_asking(tmp_path, capsys, no_labeling):
    promptfoo_project(tmp_path, split(20, 16))
    records_project(tmp_path, split(20, 16))
    (tmp_path / "judgekeeper.toml").write_text('[start]\nsource = "promptfoo"\n',
                                                encoding="utf-8")
    code, out = check(capsys, tmp_path)
    assert code == 0 and "Eval tool:   promptfoo" in out
    fresh(tmp_path)
    code = main(["start", str(tmp_path), "--yes"])
    capsys.readouterr()
    assert code == 0 and no_labeling[0].tool == "promptfoo"


# judgekeeper.toml ------------------------------------------------------------------------

def test_saving_replaces_only_its_own_table(tmp_path, capsys):
    flat_jsonl(tmp_path / "evals" / "graded.jsonl")
    (tmp_path / "judgekeeper.toml").write_text(
        "# my thresholds\n[gate]\nkappa_min = 0.7\n", encoding="utf-8")
    code, out = check(capsys, tmp_path, "--yes")
    assert code == 0, out
    text = (tmp_path / "judgekeeper.toml").read_text(encoding="utf-8")
    data = tomllib.loads(text)
    assert data["gate"] == {"kappa_min": 0.7} and "# my thresholds" in text
    assert data["start"]["source"] == "map"


def test_a_shape_judgekeeper_does_not_edit_is_left_alone(tmp_path, capsys):
    flat_jsonl(tmp_path / "evals" / "graded.jsonl")
    odd = "start = 1\n"  # a key named start, not a table: judgekeeper does not rewrite it
    (tmp_path / "judgekeeper.toml").write_text(odd, encoding="utf-8")
    code, out = check(capsys, tmp_path, "--yes")
    assert code == 2 and "judgekeeper.toml" in out
    assert (tmp_path / "judgekeeper.toml").read_text(encoding="utf-8") == odd


def test_a_changed_shape_says_how_to_map_it_again(tmp_path, capsys, terminal):
    answers, _ = terminal
    path = nested_runs_project(tmp_path, rule_rows=0)
    answers += ["", "", "1", ""]
    check(capsys, tmp_path)
    fresh(tmp_path)
    path.write_text(path.read_text(encoding="utf-8").replace('"cases"', '"items"'),
                    encoding="utf-8")
    code, out = check(capsys, "start", tmp_path, "--yes")
    assert code == 2
    assert CHANGED_SHAPE.format(program="judgekeeper") in out
    assert "judgekeeper setup" not in CHANGED_SHAPE


@pytest.mark.parametrize("line_end", [b"\r\n", b"\n"])
def test_judgekeeper_toml_keeps_its_line_endings_and_stays_valid(tmp_path, capsys, line_end):
    path = tmp_path / "judgekeeper.toml"
    path.write_bytes(b"# my thresholds" + line_end + b"[gate]" + line_end + b"kappa_min = 0.7"
                     + line_end)
    flat_jsonl(tmp_path / "evals" / "graded.jsonl")
    assert main([str(tmp_path), "--yes"]) == 0, capsys.readouterr().out
    data = path.read_bytes()
    assert b"\r\r" not in data
    if line_end == b"\r\n":
        assert b"\n" not in data.replace(b"\r\n", b"")
    else:
        assert b"\r" not in data
    parsed = tomllib.loads(data.decode("utf-8"))
    assert parsed["gate"] == {"kappa_min": 0.7} and parsed["start"]["source"] == "map"


def test_a_new_judgekeeper_toml_uses_plain_newlines(tmp_path, capsys):
    flat_jsonl(tmp_path / "evals" / "graded.jsonl")
    assert main([str(tmp_path), "--yes"]) == 0, capsys.readouterr().out
    assert b"\r" not in (tmp_path / "judgekeeper.toml").read_bytes()
