"""`judgekeeper` on results saved in a project's own format (own_map.py).

It finds a file that looks like an LLM-as-a-judge's results, shows how it reads it (paths only,
never a value), asks only what the file cannot tell, and keeps the map in judgekeeper.toml after
one yes. Nothing is written to the project before that yes (only judgekeeper's own folder), and
the user's code is never edited. `start` then reads judgekeeper.toml first.
"""

from __future__ import annotations

import builtins
import json
import os
import subprocess
import sys
import time
import tomllib
from pathlib import Path

import pytest

from judgekeeper import background, start
from judgekeeper.cli import main
from judgekeeper.textio import quote_arg
from tests.start_projects import (
    answer,
    flat_jsonl,
    nested_runs_project,
    promptfoo_project,
    question,
    split,
)
from tests.test_front import next_lines


@pytest.fixture(autouse=True)
def in_its_folder(tmp_path, monkeypatch):
    """Each test runs from its own folder: a results file given by path keeps .judgekeeper/
    in the folder the command runs from."""
    monkeypatch.chdir(tmp_path)


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
    assert "Which LLM-as-a-judge do you want to check?" in out
    assert "Leave them out?" in asked[3]
    assert "judgekeeper.toml" in asked[4]
    assert "history/evals.jsonl looks like your LLM-as-a-judge's results in a format of its own" in out
    assert "cases[].A.output" in out and 'cases[].A.scores."Safe wording".score' in out
    assert "Question " not in out and "Answer " not in out  # paths, never values
    assert "Eval tool:       your own format" in out
    assert "Answers:         42 answers" in out
    assert "File:            history/evals.jsonl, 3 lines" in out
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


def test_then_judgekeeper_reads_it_without_a_question(tmp_path, capsys, terminal):
    answers, asked = terminal
    nested_runs_project(tmp_path, rule_rows=0)
    answers += ["", "", "1", ""]
    check(capsys, tmp_path)
    before = len(asked)
    fresh(tmp_path)
    code, out = check(capsys, tmp_path)
    assert code == 0 and len(asked) == before
    assert ("judgekeeper has read from your file: question prompt answer A.output and "
            "B.output") in " ".join(out.split())
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
    assert "Nothing was saved: judgekeeper reads" in out
    assert next_lines(out)[-1] == "Next: run `judgekeeper` again and answer yes."


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
    assert "LLM-as-a-judge:  Plain language, " in out


# Questions only when needed -------------------------------------------------------------

def test_a_flat_file_with_one_judge_asks_one_question(
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
    assert last.startswith("Next: turn out/graded.jsonl into a CSV")  # named from the project
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


def test_a_quote_that_never_closes_is_a_file_it_cant_read(tmp_path, capsys):
    path = tmp_path / "scores.csv"
    path.write_text('q_text,model_reply,judge_score\n"q0,a0,0.5\nq1,a1,0.5\n', encoding="utf-8")
    code, out = check(capsys, path)
    assert code == 2, out  # reference.md: a file it can't read
    assert next_lines(out)[-1].startswith("Next: close the quote on line 2 of scores.csv")


def test_a_file_not_saved_as_utf8_is_a_file_it_cant_read(tmp_path, capsys):
    path = tmp_path / "scores.jsonl"
    path.write_bytes(b'{"question": "caf\xe9", "reply": "a", "score": 0.5}\n')
    code, out = check(capsys, path)
    assert code == 2, out
    assert next_lines(out)[-1].startswith("Next: save scores.jsonl as UTF-8")


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
    code, out = check(capsys, path, "--yes", "--pass-if", "score<4")  # a lower score passes
    assert code == 0, out
    assert saved(tmp_path)["pass_mark"] == 4 and saved(tmp_path)["pass_op"] == "<"


# Without a terminal ----------------------------------------------------------------------

def test_without_a_terminal_it_stops_at_the_question_before_saving(tmp_path, capsys):
    flat_jsonl(tmp_path / "evals" / "graded.jsonl")
    before = snapshot(tmp_path)
    code, out = check(capsys, tmp_path)
    assert code == 3
    assert "Save how to read evals/graded.jsonl in judgekeeper.toml?" in out
    assert f"or `judgekeeper {quote_arg(tmp_path)} --yes` to say yes." in next_lines(out)[-1]
    assert snapshot(tmp_path) == before


def test_a_response_time_column_is_not_counted_as_answers(tmp_path, capsys):
    path = tmp_path / "graded.jsonl"
    path.write_text("".join(json.dumps({
        "question": f"When does shop {i} open?", "response": f"Shop {i} opens at 9.",
        "response_time": f"0.{i}s", "verdict": "pass" if i % 3 else "fail"}) + "\n"
        for i in range(8)), encoding="utf-8")
    _, out = check(capsys, path, "--yes")  # then too few answers for a first result
    assert "  answer:          response\n" in out and "Answers:         8 answers" in out
    assert saved(tmp_path)["map"]["output"] == "response"


def test_without_a_terminal_two_answer_columns_not_a_and_b_stop(tmp_path, capsys):
    path = tmp_path / "graded.jsonl"
    path.write_text("".join(json.dumps({"question": f"q{i}", "answer": f"An answer {i}.",
                                        "response": f"A response {i}.", "verdict": "pass"})
                            + "\n" for i in range(8)), encoding="utf-8")
    code, out = check(capsys, path, "--yes")
    assert code == 3, out
    assert not (tmp_path / "judgekeeper.toml").exists()


@pytest.mark.skipif(sys.platform == "win32" or getattr(os, "geteuid", lambda: 1)() == 0,
                    reason="chmod 000 keeps a file from its owner only on POSIX, not root")
@pytest.mark.parametrize("name", ["notes.json", "notes.jsonl", "notes.csv"])
def test_a_file_it_may_not_read_is_skipped(tmp_path, capsys, name):
    flat_jsonl(tmp_path / "evals" / "graded.jsonl")
    unreadable = tmp_path / "evals" / name
    unreadable.write_text('{"question": "q", "answer": "a", "verdict": "pass"}\n',
                          encoding="utf-8")
    os.utime(unreadable, (time.time() + 60,) * 2)  # newer: looked at first
    unreadable.chmod(0)
    try:
        code, out = check(capsys, tmp_path, "--yes")
    finally:
        unreadable.chmod(0o600)
    assert code == 0, out
    assert "evals/graded.jsonl" in out and "permission" not in out


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
    assert code == 2 and "no LLM-as-a-judge named 'nope'" in out


def test_without_a_terminal_each_answer_question_takes_yes(tmp_path, capsys, monkeypatch):
    from tests.start_projects import own_format_project

    monkeypatch.chdir(tmp_path)
    own_format_project(tmp_path)  # each case has two answers, A and B
    code, out = check(capsys)
    assert code == 3, out
    assert ("1. Each item has 2 answers (A and B). Count each as its own answer?"
            in " ".join(out.split()))
    assert "answers, each graded by your LLM-as-a-judge" not in out  # counted after the answer
    assert next_lines(out)[-1] == (
        "Next: run `judgekeeper` in a terminal to answer, or `judgekeeper --yes` to say yes "
        "to all.")


# Eval tools and records are read as they are ----------------------------------------------

def test_an_eval_tool_is_read_as_it_is(tmp_path, capsys):
    promptfoo_project(tmp_path, split(20, 16))
    code, _ = check(capsys, tmp_path, "--yes")
    assert code == 0
    assert not (tmp_path / "judgekeeper.toml").exists()  # nothing was asked


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


def test_yes_answers_when_the_input_is_the_empty_device(tmp_path):
    """`--yes` with input from the empty device (`< NUL` on Windows, `< /dev/null` elsewhere):
    no person types there, so judgekeeper answers its question and keeps the map."""
    flat_jsonl(tmp_path / "evals" / "graded.jsonl")
    run = [sys.executable, "-m", "judgekeeper"]
    try:
        done = subprocess.run([*run, str(tmp_path), "--yes", "--no-browser", "--port", "0"],
                              cwd=tmp_path, stdin=subprocess.DEVNULL, capture_output=True,
                              text=True, encoding="utf-8", timeout=120, check=False)
    finally:
        subprocess.run([*run, "--stop"], cwd=tmp_path, stdin=subprocess.DEVNULL,
                       capture_output=True, timeout=60, check=False)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "[Y/n]" not in done.stdout
    toml = tomllib.loads((tmp_path / "judgekeeper.toml").read_text(encoding="utf-8"))
    assert toml["start"]["source"] == "map"


def test_on_windows_input_that_is_not_a_console_is_not_a_terminal(monkeypatch):
    """Windows says the NUL device is a terminal (isatty); only a console is one there. When
    judgekeeper cannot ask Windows, it is not one either."""

    class Nul:
        def isatty(self):
            return True

        def fileno(self):
            raise OSError("not a console")

    monkeypatch.setattr(sys, "stdin", Nul())
    monkeypatch.setattr(sys, "platform", "win32")
    assert start._interactive() is False
    monkeypatch.setattr(sys, "platform", "linux")
    assert start._interactive() is True


# One JSON document ----------------------------------------------------------------------------

def _one_document(root, errors: int = 0, rule: int = 0, n: int = 30, grader: str | None = None,
                  passed=None) -> Path:
    """results.json: one JSON document over many lines, an item per answer; the first
    `errors` items have no grade, the next `rule` were graded by a rule. `grader` names the
    judge's model in judge.grader; `passed` gives the grades (else every third fails)."""
    items = [{"prompt": question(i), "reply": answer(i),
              "passed": None if i < errors else passed[i] if passed else i % 3 != 0,
              "why": "Rule: too short" if errors <= i < errors + rule else f"because {i}"}
             for i in range(n)]
    judge = {"name": "helpful", **({"grader": grader} if grader else {})}
    path = root / "results.json"
    path.write_text(json.dumps({"run_name": "run-1", "judge": judge, "items": items},
                               indent=2), encoding="utf-8")
    return path


def test_a_json_document_is_not_counted_in_lines(tmp_path, capsys, terminal):
    answers, _ = terminal
    _one_document(tmp_path)
    answers += ["", ""]
    code, out = check(capsys, tmp_path)
    assert code == 0, out
    assert ("results.json looks like your LLM-as-a-judge's results in a format of its own.\n"
            "What it holds:") in out


def test_a_model_not_in_the_file_says_how_to_give_it(tmp_path, capsys, terminal):
    answers, _ = terminal
    _one_document(tmp_path)
    answers += ["", ""]
    _, out = check(capsys, tmp_path)
    assert "  model:           not in the file (add --judge-model NAME)\n" in out


def test_a_model_the_file_names_is_offered_saved_and_in_the_fingerprint(tmp_path, capsys,
                                                                          terminal):
    answers, asked = terminal
    _one_document(tmp_path, grader="claude-haiku-5-5")
    answers += ["", ""]  # right; save
    code, out = check(capsys, tmp_path)
    assert code == 0, out
    assert "  model:           judge.grader (claude-haiku-5-5)\n" in out
    assert "judgekeeper.toml" in asked[1]
    assert saved(tmp_path)["map"]["model_key"] == "judge.grader"
    jk = tmp_path / ".judgekeeper"
    fp = json.loads((jk / "start.json").read_text(encoding="utf-8"))["fingerprint"]
    assert fp["model"] == "claude-haiku-5-5"
    pool = (jk / "pool-judge.jsonl").read_text(encoding="utf-8")
    lines = [json.loads(x) for x in pool.splitlines()]
    judgments = [x for x in lines if "verdict" in x]
    assert judgments and all(x["fingerprint"]["model"] == "claude-haiku-5-5"
                             for x in judgments)


def test_the_judge_model_flag_beats_the_file(tmp_path, capsys, terminal):
    answers, _ = terminal
    _one_document(tmp_path, grader="claude-haiku-5-5")
    answers += ["", ""]
    code, out = check(capsys, tmp_path, "--judge-model", "gpt-5-mini")
    assert code == 0, out
    assert "  model:           gpt-5-mini (given with --judge-model)\n" in out
    read = out.split("judgekeeper has read from your file:\n", 1)[1].split("\n\n", 1)[0]
    assert "judge.grader" not in read, read  # the field is not what this run used
    assert "gpt-5-mini (given with --judge-model)" in read, read
    start_json = tmp_path / ".judgekeeper" / "start.json"
    assert json.loads(start_json.read_text(encoding="utf-8"))["fingerprint"]["model"] == \
        "gpt-5-mini"
    # the file's model is still read on later runs: the flag wins for its own run only
    assert saved(tmp_path)["map"]["model_key"] == "judge.grader"
    assert "model" not in saved(tmp_path)


def test_the_judge_model_flag_beats_a_saved_model_key(tmp_path, capsys, terminal):
    answers, _ = terminal
    _one_document(tmp_path, grader="claude-haiku-5-5")
    answers += ["", ""]
    assert check(capsys, tmp_path)[0] == 0
    assert saved(tmp_path)["map"]["model_key"] == "judge.grader"
    assert start.find_judge(tmp_path).fingerprint["model"] == "claude-haiku-5-5"
    found = start.find_judge(tmp_path, judge_model="gpt-5-mini")
    assert (found.fingerprint["model"], found.fingerprint["model_source"]) == (
        "gpt-5-mini", start.GIVEN_BY_YOU)


MARKED = [True] * 25 + [False] * 25
LENIENT = MARKED[:25] + [True] * 9 + [False] * 16  # passes 9 of the answers the person failed


def _mark_every_answer(root, found) -> None:
    """The person marks every queued answer as the LLM-as-a-judge graded it."""
    from judgekeeper import judge_setup, start_label

    ws = start_label.Workspace(root)
    judge_setup.save(ws, judge_setup.of(found), found.metric)
    session = start_label.StartSession(ws)
    for q in ws.data()["queue"]:
        session.update({"id": q["id"], "label": q["group"], "seconds": 5})


def test_check_names_a_model_change_in_the_file(tmp_path, capsys, terminal):
    """Marked with judge.grader claude-haiku-5-5; regraded by claude-haiku-4-5: check names
    the model change."""
    answers, _ = terminal
    _one_document(tmp_path, n=50, grader="claude-haiku-5-5", passed=MARKED)
    answers += ["", ""]
    assert check(capsys, tmp_path)[0] == 0
    _mark_every_answer(tmp_path, start.find_judge(tmp_path))
    assert check(capsys, "check")[0] == 0
    _one_document(tmp_path, n=50, grader="claude-haiku-4-5", passed=LENIENT)
    _, out = check(capsys, "check")
    assert ("Your LLM-as-a-judge's model changed: claude-haiku-5-5 -> claude-haiku-4-5"
            in " ".join(out.split())), out


def test_after_the_judge_model_flag_the_file_names_the_model_again(tmp_path, capsys,
                                                                   terminal):
    """First run with --judge-model; a later run without it reads judge.grader, and a check
    after the file's model changes names the change."""
    answers, _ = terminal
    _one_document(tmp_path, n=50, grader="claude-haiku-5-5", passed=MARKED)
    answers += ["", ""]
    assert check(capsys, tmp_path, "--judge-model", "gpt-5-mini")[0] == 0
    assert saved(tmp_path)["map"]["model_key"] == "judge.grader"
    _mark_every_answer(tmp_path, start.find_judge(tmp_path, judge_model="gpt-5-mini"))
    found = start.find_judge(tmp_path)
    assert (found.fingerprint["model"], found.fingerprint.get("model_source")) == (
        "claude-haiku-5-5", None)
    _one_document(tmp_path, n=50, grader="claude-haiku-4-5", passed=LENIENT)
    _, out = check(capsys, "check")
    assert "Your LLM-as-a-judge's model changed: gpt-5-mini -> claude-haiku-4-5" in \
        " ".join(out.split()), out


def test_a_no_to_saving_says_once_that_nothing_was_saved(tmp_path, capsys, terminal):
    answers, _ = terminal
    _one_document(tmp_path)
    answers += ["", "n"]
    code, out = check(capsys, tmp_path)
    assert code == 0, out
    assert not (tmp_path / "judgekeeper.toml").exists()
    flat = " ".join(out.split())
    assert ("Nothing was saved: judgekeeper reads results.json only once judgekeeper.toml says "
            "how.") in flat and flat.count("Nothing was saved") == 1
    assert next_lines(out) == ["Next: run `judgekeeper` again and answer yes."]


def test_answers_with_no_grade_are_not_asked_about(tmp_path, capsys, terminal):
    """An error is no decision whatever the answer: never asked whether to leave it out."""
    answers, asked = terminal
    _one_document(tmp_path, errors=3, n=40)
    answers += ["", ""]
    code, out = check(capsys, tmp_path)
    assert code == 0, out
    assert not any("Leave them out?" in q for q in asked)
    assert "made no real decision on 3 of 40 answers: 3 empty decisions. They are left out " \
        "here." in " ".join(out.split())


def test_a_no_to_leaving_rule_scores_out_counts_them(tmp_path, capsys, terminal):
    answers, asked = terminal
    _one_document(tmp_path, rule=3)
    answers += ["", "n", ""]
    code, out = check(capsys, tmp_path)
    assert code == 0, out
    assert ('3 answers have a score made by a rule (a reason starting "Rule"), not by your '
            "LLM-as-a-judge. Leave them out?") in asked[1]
    assert "left out here" not in out
    assert "passed 20 answers and failed 10." in " ".join(out.split())

