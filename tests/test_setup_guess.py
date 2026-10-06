"""`judgekeeper setup` on a homemade results file that states its own pass mark and judge
model at the run level and holds two criteria per answer (tests/start_projects.py,
coach_project: the shape of a real homemade judge's history, with made-up text).

The guess reads the pass mark and the judge's model wherever the file keeps them (the run
or the item) and says where; it lists every criterion as a judge; and at a terminal the
person is asked whether the guess is right. After No they say which part is wrong and
correct only that part; the coding-agent prompt comes only when none of the parts fit.
"""

from __future__ import annotations

import builtins
import json
import tomllib

import pytest

from judgekeeper import mapper, own_format, start
from judgekeeper.cli import main
from judgekeeper.readers.mapped import read_mapped
from tests.start_projects import coach_project, coach_runs_data


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


def setup(capsys, *argv):
    code = main(["setup", *map(str, argv)])
    out, err = capsys.readouterr()
    return code, out + err


def saved(root) -> dict:
    return tomllib.loads((root / "judgekeeper.toml").read_text(encoding="utf-8"))["start"]


# The guess ----------------------------------------------------------------------------------

def test_every_criterion_is_a_judge():
    g = mapper.guess(coach_runs_data())
    assert g.each == "cases[]" and g.sides == ["A", "B"]
    assert g.judges == ["safe_wording", "helpful"]
    assert g.score == "answers.{side}.scores.{judge}.score"
    assert g.reason == "answers.{side}.scores.{judge}.reason"
    assert not g.unsure


def test_the_pass_mark_and_the_judge_model_come_from_the_run():
    g = mapper.guess(coach_runs_data(pass_mark=0.7))
    assert (g.pass_mark, g.pass_mark_key) == (0.7, "judge.pass_mark")
    assert (g.model_key, g.model) == ("judge.model", "claude-sonnet-5")  # not app.model


def test_a_pass_mark_on_each_item_is_read_too():
    units = [{"question": f"q{i}", "answer": f"a{i}", "score": 1 + i % 5, "threshold": 4}
             for i in range(40)]
    g = mapper.guess(units)
    assert (g.pass_mark, g.pass_mark_key, g.pass_mark_sure) == (4, "threshold", True)


@pytest.mark.parametrize("key", ["pass_mark", "passMark", "threshold", "pass_threshold",
                                 "passing_score"])
def test_pass_mark_names(key):
    units = [{"settings": {key: 0.8}, "rows": [{"question": "q", "answer": "a", "score": 0.9}]}]
    assert mapper.guess(units).pass_mark == 0.8


def test_an_app_model_alone_is_not_the_judge_model():
    units = [{"app": {"model": "x"}, "cases": [{"question": "q", "answer": "a",
                                                "score": 0.9}]}]
    assert mapper.guess(units).model_key is None


def test_what_it_holds_shows_one_criterion_placeholder_for_both():
    g = mapper.guess(coach_runs_data())
    paths = [p for p, _ in mapper.listing(coach_runs_data()[0], g.judges)]
    assert "judge.criteria.<criterion>" in paths
    assert "cases[].answers.A.scores.<criterion>.score" in paths
    assert not any("helpful" in p or "safe_wording" in p for p in paths)


def test_the_reader_uses_the_pass_mark_of_each_run(tmp_path):
    path = tmp_path / "evals.jsonl"
    lines = coach_runs_data(runs=1, pass_mark=0.7) + coach_runs_data(runs=1, pass_mark=0.5)
    path.write_text("".join(json.dumps(x) + "\n" for x in lines), encoding="utf-8")
    m = {**mapper.guess(lines).to_map(), "judge": "safe_wording", "pass_mark": 0.7}
    (_, new), (_, old) = read_mapped(path, m)
    assert [r.label for r in new].count("pass") == 40  # run 2 says 0.5: 0.9 and 0.6 pass
    assert [r.label for r in old].count("pass") == 20  # run 1 says 0.7: only 0.9 passes
    assert all(r.evaluator == {"model": "claude-sonnet-5"} for r in new + old)


# The conversation ---------------------------------------------------------------------------

def test_how_it_reads_says_where_the_pass_mark_and_model_come_from(tmp_path, capsys):
    coach_project(tmp_path)
    code, out = setup(capsys, tmp_path / "history" / "evals.jsonl", "--yes", "--metric", "all")
    assert code == 0
    assert ("  score:           answers.<side>.scores.<criterion>.score (judges: safe_wording, "
            "helpful)") in out
    assert "  judge's model:   judge.model (claude-sonnet-5)" in out
    assert "  pass mark:       0.7 (judge.pass_mark in the file)" in out
    assert "safe_wording: 0.9, pass (pass mark 0.7)" in out
    s = saved(tmp_path)
    assert s["pass_mark"] == 0.7 and s["judge"] == "*"
    assert s["map"]["judges"] == ["safe_wording", "helpful"]
    assert s["map"]["model_key"] == "judge.model" and s["map"]["pass_mark_key"] == \
        "judge.pass_mark"


def test_start_then_reads_both_judges_with_the_files_pass_mark(tmp_path, capsys):
    coach_project(tmp_path)
    setup(capsys, tmp_path / "history" / "evals.jsonl", "--yes", "--metric", "all")
    found = start.find_judge(tmp_path, metric="helpful")
    assert found.metrics == ["helpful", "safe_wording"]
    assert (found.pool.n_pass, found.pool.n_fail) == (20, 40)
    assert found.judge == "helpful with claude-sonnet-5"


def test_a_model_given_with_the_flag_shows_in_the_guess(tmp_path, capsys):
    units = [{"question": f"q{i}", "answer": f"a{i}", "score": 0.9} for i in range(30)]
    path = tmp_path / "graded.jsonl"
    path.write_text("".join(json.dumps(u) + "\n" for u in units), encoding="utf-8")
    code, out = setup(capsys, path, "--yes", "--judge-model", "gpt-4.1")
    assert code == 0
    assert "  judge's model:   gpt-4.1 (given with --judge-model)" in out


def test_at_a_terminal_it_asks_whether_the_guess_is_right(tmp_path, capsys, terminal):
    answers, asked = terminal
    coach_project(tmp_path)
    answers += ["", "", "1", ""]  # right; each its own answer; safe_wording; yes
    code, _ = setup(capsys, tmp_path / "history" / "evals.jsonl")
    assert code == 0 and asked[0].startswith("Is this right?")
    assert saved(tmp_path)["judge"] == "safe_wording"


def test_after_no_correct_the_pass_mark(tmp_path, capsys, terminal):
    answers, _ = terminal
    coach_project(tmp_path)
    answers += ["n", "8", "0.5", "", "", "1", ""]
    code, out = setup(capsys, tmp_path / "history" / "evals.jsonl")
    assert code == 0
    assert "Which part is wrong?" in out
    for n, part in enumerate(("what one answer is", "the input", "the answer", "the score",
                              "the reason", "the id", "the judge's model", "the pass mark",
                              "none of these fit"), 1):
        assert f"  {n}. {part}" in out
    assert "  pass mark:       0.5 (given by you)" in out
    assert out.count("How judgekeeper reads it:") == 2
    assert out.index("(given by you)") < out.index("Three answers as judgekeeper will read")
    assert "safe_wording: 0.6, pass (pass mark 0.5)" in out
    assert saved(tmp_path)["pass_mark"] == 0.5
    assert "pass_mark_key" not in saved(tmp_path)["map"]
    assert own_format.AGENT_PROMPT not in out


def test_after_no_correct_the_judge_model(tmp_path, capsys, terminal):
    answers, _ = terminal
    coach_project(tmp_path)
    answers += ["n", "7"]
    code, out = setup_with_choice(capsys, answers, tmp_path, "app.model")
    assert code == 0
    assert "Which path holds the judge's model?" in out
    assert saved(tmp_path)["map"]["model_key"] == "app.model"


def test_after_no_none_of_these_fit_gives_the_agent_prompt(tmp_path, capsys, terminal):
    answers, _ = terminal
    coach_project(tmp_path)
    answers += ["n", "9"]
    code, out = setup(capsys, tmp_path / "history" / "evals.jsonl")
    assert code == start.EXIT_USAGE
    assert own_format.AGENT_PROMPT in out
    assert not (tmp_path / "judgekeeper.toml").exists()


def test_after_no_correct_the_input(tmp_path, capsys, terminal):
    answers, _ = terminal
    coach_project(tmp_path)
    answers += ["n", "2"]
    code, _ = setup_with_choice(capsys, answers, tmp_path, "topic")
    assert code == 0
    assert saved(tmp_path)["map"]["input"] == "topic"


def setup_with_choice(capsys, answers, root, path_text, then=("", "", "1", "")):
    """Run setup, answering the path list with the number of `path_text`."""
    import re

    original = builtins.input
    state = {"chosen": False}

    def answer(prompt=""):
        if not state["chosen"] and not answers:
            state["chosen"] = True
            listed = capsys.readouterr().out
            print(listed)
            n = re.search(rf"  (\d+)\. {re.escape(path_text)} ", listed)[1]
            answers.extend(then)
            return n
        return original(prompt)

    builtins.input = answer
    try:
        return setup(capsys, root / "history" / "evals.jsonl")
    finally:
        builtins.input = original
