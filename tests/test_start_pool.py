"""`judgekeeper start`, choosing and counting: which results to use when there are several,
the pool of answers (repeats merged, unclear verdicts left out), the judge's name, too few
answers, and what happens without a terminal.
"""

from __future__ import annotations

import builtins
import copy
import json

import pytest

from judgekeeper import start, textio
from judgekeeper.cli import main
from judgekeeper.normalise import Normaliser
from judgekeeper.records import HUMAN, LLM, RecordList, ScoreRecord
from tests import keyboard
from tests.start_projects import (
    deepeval_project,
    promptfoo_data,
    promptfoo_project,
    split,
    table_project,
)


@pytest.fixture(autouse=True)
def no_labeling(monkeypatch):
    """These tests stop where labeling starts (tests/test_start_label.py covers the rest)."""
    calls = []

    def run_labeling(found, port, open_browser, say, command="judgekeeper start"):
        calls.append(found)
        say("(labeling page)")
        return 0

    monkeypatch.setattr("judgekeeper.start_label.run_labeling", run_labeling)
    return calls


def run(capsys, *argv, yes=True):
    """`judgekeeper start` without a terminal; with --yes unless `yes` is False, so the run
    goes on to labeling (replaced here) where a person would say yes."""
    argv = [*map(str, argv)] + (["--yes"] if yes and "--yes" not in argv else [])
    code = main(["start", *argv])
    out, err = capsys.readouterr()
    return code, out, err


def ok() -> str:
    return textio.tick()


@pytest.fixture
def terminal(monkeypatch):
    """A person at a terminal: answers come from the list the test fills in."""
    answers: list[str] = []
    monkeypatch.setattr(start, "_interactive", lambda: True)

    def fake_input(prompt=""):
        print(prompt)
        return answers.pop(0) if answers else keyboard.enter()  # then Enter: the default answer

    monkeypatch.setattr(builtins, "input", fake_input)
    return answers


# Choosing --------------------------------------------------------------------------------

def _two_tools(root):
    promptfoo_project(root, split(20, 12))
    table_project(root, split(16, 16), name="scores.csv")


def test_two_tools_found_without_a_terminal_asks_for_a_flag(tmp_path, capsys):
    _two_tools(tmp_path)
    code, out, _ = run(capsys, tmp_path, yes=False)
    assert code == start.EXIT_QUESTION
    assert "Several tools found; choose one with --tool promptfoo or --tool table" in out
    assert "Its decisions" not in out


def test_two_tools_found_asks_which_one(tmp_path, capsys, terminal):
    _two_tools(tmp_path)
    terminal.append("2")
    code, out, _ = run(capsys, tmp_path)
    assert code == 0
    assert "  1. promptfoo (results.json, saved " in out
    assert "  2. a plain table (scores.csv, saved " in out
    assert "Which one? [1-2]" in out
    assert "  Eval tool       a table (scores.csv)" in out


def test_tool_answers_without_asking(tmp_path, capsys):
    _two_tools(tmp_path)
    code, out, _ = run(capsys, tmp_path, "--tool", "promptfoo")
    assert code == 0
    assert "  Results file    results.json (saved" in out
    assert "Its decisions   32 answers" in out


def test_yes_does_not_choose_between_tools(tmp_path, capsys):
    _two_tools(tmp_path)
    code, out, _ = run(capsys, tmp_path, "--yes")
    assert code == start.EXIT_QUESTION and "--tool promptfoo or --tool table" in out


def test_a_tool_that_is_not_there(tmp_path, capsys):
    promptfoo_project(tmp_path, split(20, 12))
    code, out, err = run(capsys, tmp_path, "--tool", "deepeval")
    assert code == 2
    assert "No saved DeepEval results found" in out + err


def _two_metrics(root):
    data = promptfoo_data(split(20, 12), metric="helpfulness")
    for i, row in enumerate(data["results"]["results"]):
        c = copy.deepcopy(row["gradingResult"]["componentResults"][0])
        c["assertion"] = {"type": "llm-rubric", "value": "Has a calm tone.", "metric": "tone"}
        c["pass"] = i % 2 == 0
        row["gradingResult"]["componentResults"].append(c)
    (root / "results.json").write_text(json.dumps(data), encoding="utf-8")


def test_several_judges_without_a_terminal_ask_for_a_flag(tmp_path, capsys):
    _two_metrics(tmp_path)
    code, out, _ = run(capsys, tmp_path, yes=False)
    assert code == start.EXIT_QUESTION
    assert "Several judges found; choose one with --metric helpfulness or --metric tone" in out


def test_several_judges_ask_which_one_with_their_counts(tmp_path, capsys, terminal):
    _two_metrics(tmp_path)
    terminal.append("2")
    code, out, _ = run(capsys, tmp_path)
    assert code == 0
    assert "  1. helpfulness (32 answers)" in out
    assert "  2. tone (32 answers)" in out
    assert '  What it checks  tone: "Has a calm tone."' in out
    assert "  Judge model     openai:gpt-4.1-mini" in out
    assert "  Its decisions   32 answers: 16 passed, 16 failed" in out


def test_metric_answers_without_asking(tmp_path, capsys):
    _two_metrics(tmp_path)
    code, out, _ = run(capsys, tmp_path, "--metric", "helpfulness")
    assert code == 0
    assert '  What it checks  helpfulness: "Is polite and correct."' in out


def test_an_unknown_metric_lists_the_names(tmp_path, capsys):
    _two_metrics(tmp_path)
    code, _, err = run(capsys, tmp_path, "--metric", "speed")
    assert code == 2
    assert "no judge named 'speed'; judges are: 'helpfulness', 'tone'" in err


def test_a_bad_answer_asks_again(tmp_path, capsys, terminal):
    _two_tools(tmp_path)
    terminal.extend(["7", "x", "1"])
    code, out, _ = run(capsys, tmp_path)
    assert code == 0
    assert "  Results file    results.json (saved" in out


def test_older_files_are_added_only_for_the_same_judge(tmp_path, capsys):
    runs = tmp_path / "runs"
    deepeval_project(runs, split(6, 4), name="test_run_20261003_090000.json", start=0)
    deepeval_project(runs, split(15, 10), name="test_run_20261002_090000.json", start=10)
    deepeval_project(runs, split(15, 10), name="test_run_20261001_090000.json", start=35,
                     model="gpt-4o")
    code, out, _ = run(capsys, tmp_path)
    assert code == 0
    assert "  Results file    runs/test_run_20261003_090000.json (saved 3 Oct 2026, 09:00)" in out
    assert ("  Fewer than 30 answers in the newest results, so older results from the same "
            "judge were added: runs/test_run_20261002_090000.json") in out
    assert "test_run_20261001_090000.json" not in out
    assert "  Its decisions   35 answers: 21 passed, 14 failed" in out


def test_the_newest_file_wins_when_older_results_are_added(tmp_path, capsys, no_labeling):
    """The newest results left answer 0 out (its grader errored); older results added to reach
    30 have a real decision for it. The newest file wins: answer 0 stays left out."""
    from tests.test_judge_check import promptfoo_with_problems

    newest = promptfoo_with_problems(split(6, 4), errors=[0])
    newest["metadata"] = {"evaluationCreatedAt": "2026-10-04T09:00:00.000Z"}
    (tmp_path / "promptfooconfig.yaml").write_text("description: support bot\n",
                                                   encoding="utf-8")
    (tmp_path / "results.json").write_text(json.dumps(newest), encoding="utf-8")
    older = promptfoo_data(split(15, 10), created="2026-10-03T09:00:00.000Z")
    (tmp_path / "older.json").write_text(json.dumps(older), encoding="utf-8")
    code, out, _ = run(capsys, tmp_path)
    assert code == 0
    assert "older results from the same judge were added: older.json" in out
    (found,) = no_labeling
    (left,) = found.pool.left
    assert found.pool.left[left][0] == "error"
    assert left not in {a.id for a in found.pool.answers}
    assert len(found.pool.answers) == 24  # 9 from the newest, 15 more from the older one


def test_older_files_stop_once_there_are_thirty(tmp_path, capsys):
    runs = tmp_path / "runs"
    deepeval_project(runs, split(6, 4), name="test_run_20261003_090000.json", start=0)
    deepeval_project(runs, split(15, 10), name="test_run_20261002_090000.json", start=10)
    deepeval_project(runs, split(15, 10), name="test_run_20261001_090000.json", start=35)
    code, out, _ = run(capsys, tmp_path)
    assert code == 0
    assert "test_run_20261001_090000.json" not in out
    assert "Its decisions   35 answers" in out


def test_the_newest_file_alone_when_it_has_thirty(tmp_path, capsys):
    runs = tmp_path / "runs"
    deepeval_project(runs, split(20, 12), name="test_run_20261003_090000.json", start=0)
    deepeval_project(runs, split(15, 10), name="test_run_20261002_090000.json", start=40)
    code, out, _ = run(capsys, tmp_path)
    assert code == 0
    assert "older results" not in out
    assert "Its decisions   32 answers" in out


# The pool --------------------------------------------------------------------------------

def _rec(i, label, run=1, output=None, kind=LLM, name="judge", model="m1"):
    return ScoreRecord(target_id=f"x{i}", name=name, annotator_kind=kind, label=label, run=run,
                       input=f"q{i}", output=output or f"a{i}",
                       evaluator={"model": model} if kind == LLM else {})


def _pool(files, label_map=None):
    return start.build_pool(files, "judge", Normaliser(label_map=label_map))


def test_repeats_of_one_answer_count_once_with_the_majority():
    newest = RecordList([_rec(0, "pass"), _rec(0, "fail", run=2), _rec(0, "fail", run=3),
                         _rec(1, "pass"), _rec(1, "fail", run=2),  # a tie goes to fail
                         _rec(2, "pass")])
    pool = _pool([("new.json", newest)])
    verdicts = {a.input: a.verdict for a in pool.answers}
    assert verdicts == {"q0": "fail", "q1": "fail", "q2": "pass"}
    assert pool.n_merged == 3
    assert (pool.n_pass, pool.n_fail) == (1, 2)


def test_the_newest_file_wins_for_an_answer_in_several():
    newest = RecordList([_rec(0, "fail")])
    older = RecordList([_rec(0, "pass"), _rec(0, "pass", run=2), _rec(1, "pass")])
    pool = _pool([("new.json", newest), ("old.json", older)])
    verdicts = {a.input: (a.verdict, a.source) for a in pool.answers}
    assert verdicts == {"q0": ("fail", "new.json"), "q1": ("pass", "old.json")}
    assert pool.n_merged == 2


def test_the_same_question_with_a_different_answer_is_another_answer():
    pool = _pool([("r.json", RecordList([_rec(0, "pass"), _rec(0, "fail", output="other")]))])
    assert len(pool.answers) == 2 and pool.n_merged == 0


def test_unclear_verdicts_are_left_out_and_counted():
    recs = RecordList([_rec(0, None), _rec(1, ""), _rec(2, "maybe"), _rec(3, "maybe"),
                       _rec(4, "pass"), _rec(5, "fail")])
    pool = _pool([("r.json", recs)])
    assert [a.input for a in pool.answers] == ["q4", "q5"]
    assert pool.n_unclear == 2  # no decision; the unmapped words stop start instead
    assert pool.unmapped == ["maybe"]


def test_a_label_map_makes_a_verdict_clear():
    pool = _pool([("r.json", RecordList([_rec(0, "maybe")]))], label_map="maybe=fail")
    assert pool.n_fail == 1 and pool.n_unclear == 0


def test_other_judges_and_human_labels_are_not_in_the_pool():
    recs = RecordList([_rec(0, "pass"), _rec(0, "fail", name="tone"),
                       _rec(0, "fail", kind=HUMAN), _rec(1, "pass", kind=HUMAN)])
    pool = _pool([("r.json", recs)])
    assert len(pool.answers) == 1
    assert pool.n_human == 2


def test_the_pool_keeps_each_judgment_with_its_fingerprint():
    pool = _pool([("r.json", RecordList([_rec(0, "pass", model="judge-model")]))])
    (a,) = pool.answers
    assert a.fingerprint.model == "judge-model"
    assert a.id and a.output == "a0"


def test_empty_verdicts_are_said_in_one_line(tmp_path, capsys):
    table_project(tmp_path, split(20, 12) + [None, None])
    code, out, _ = run(capsys, tmp_path)
    assert code == 0
    assert ("Your judge made no real decision on 2 of 34 answers: 2 empty decisions." in out)
    assert "Its decisions   32 answers" in out


def test_a_verdict_it_cannot_map_stops_with_the_flag_to_add(tmp_path, capsys):
    table_project(tmp_path, split(20, 12) + ["maybe"])
    code, out, err = run(capsys, tmp_path)
    assert code == 2
    assert ('--label-map "maybe=pass" or --label-map "maybe=fail", whichever it means'
            in out + err)
    assert "Your judge failed" not in out


def test_scores_with_no_pass_mark_stop_with_pass_if(tmp_path, capsys):
    table_project(tmp_path, ["0.9"] * 20 + ["0.1"] * 12)
    code, out, err = run(capsys, tmp_path)
    assert code == 2
    assert "--pass-if" in out + err and "0.9=pass" not in out + err


def test_label_map_and_pass_if_work_as_in_import(tmp_path, capsys):
    table_project(tmp_path, ["good"] * 20 + ["bad"] * 12)
    code, out, _ = run(capsys, tmp_path, "--label-map", "good=pass,bad=fail")
    assert code == 0 and "32 answers: 20 passed, 12 failed" in out
    table_project(tmp_path, ["0.9"] * 20 + ["0.2"] * 12)
    code, out, _ = run(capsys, tmp_path, "--pass-if", "score>=0.5")
    assert code == 0 and "32 answers: 20 passed, 12 failed" in out


def test_merged_repeats_are_said(tmp_path, capsys):
    data = promptfoo_data(split(20, 12))
    rows = data["results"]["results"]
    rows += copy.deepcopy(rows[:5])  # promptfoo --repeat: the same answers again
    (tmp_path / "results.json").write_text(json.dumps(data), encoding="utf-8")
    code, out, _ = run(capsys, tmp_path)
    assert code == 0
    assert "5 repeats of the same answer were merged." in out
    assert "Its decisions   32 answers" in out


def test_pairwise_items_are_refused(tmp_path, capsys):
    path = tmp_path / "pairs.csv"
    rows = ["input,output_a,output_b,verdict"] + [f"q{i},a{i},b{i},A" for i in range(40)]
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    code, out, err = run(capsys, path)
    assert code == 2
    assert ("These are A/B comparisons. judgekeeper start handles pass/fail answers for now; "
            "see judgekeeper import.") in out + err


def test_human_labels_in_the_source_are_not_used(tmp_path, capsys):
    data = promptfoo_data(split(20, 12))
    for row in data["results"]["results"][:4]:
        row["gradingResult"]["componentResults"].append(
            {"pass": True, "score": 1, "reason": "Manual result", "assertion": {"type": "human"}})
    (tmp_path / "results.json").write_text(json.dumps(data), encoding="utf-8")
    code, out, _ = run(capsys, tmp_path)
    assert code == 0
    assert ("results.json also holds 4 human labels. judgekeeper start does not use them: you "
            "mark the answers yourself.") in out


# The judge's name ------------------------------------------------------------------------

def test_the_default_grader_is_named_as_such(tmp_path, capsys):
    promptfoo_project(tmp_path, split(20, 12), model=None)
    code, out, _ = run(capsys, tmp_path)
    assert code == 0
    assert "  Judge model     not named in the results (add --judge-model NAME)" in out


def test_judge_model_fills_a_missing_model(tmp_path, capsys):
    promptfoo_project(tmp_path, split(20, 12), model=None)
    code, out, _ = run(capsys, tmp_path, "--judge-model", "gpt-4.1-mini")
    assert code == 0
    assert "  Judge model     gpt-4.1-mini (as you told me)" in out


def test_judge_model_is_recorded_as_given_by_you(tmp_path):
    promptfoo_project(tmp_path, split(20, 12), model=None)
    found = start.find_judge(tmp_path, judge_model="gpt-4.1-mini")
    assert found.fingerprint["model"] == "gpt-4.1-mini"
    assert found.fingerprint["model_source"] == "given by you"


def test_judge_model_is_refused_when_the_file_names_a_model(tmp_path, capsys):
    promptfoo_project(tmp_path, split(20, 12))
    code, _, err = run(capsys, tmp_path, "--judge-model", "gpt-4.1-mini")
    assert code == 2
    assert ("results.json already names the judge's model (openai:gpt-4.1-mini): drop "
            "--judge-model") in err


def test_a_long_rubric_is_cut_at_a_word_within_seventy_characters(tmp_path, capsys):
    rubric = "The answer is polite, correct, complete and cites the refund policy by name."
    promptfoo_project(tmp_path, split(20, 12), rubric=rubric)
    code, out, _ = run(capsys, tmp_path)
    assert code == 0
    shown = "The answer is polite, correct, complete and cites the refund policy…"
    assert f'  What it checks  "{shown}"' in out


def test_a_model_not_recorded_by_another_tool(tmp_path, capsys):
    table_project(tmp_path, split(20, 12))
    code, out, _ = run(capsys, tmp_path, "--judge-model", "claude-haiku-4-5")
    assert code == 0
    assert "  Judge model     claude-haiku-4-5 (as you told me)" in out


# Too few answers -------------------------------------------------------------------------
# (tests/test_start_messages.py has the command for each tool and the few-fails note)

def test_too_few_prints_the_promptfoo_command_and_asks(tmp_path, capsys, terminal):
    promptfoo_project(tmp_path, split(20, 2))
    terminal.append("")
    code, out, _ = run(capsys, tmp_path)
    assert code == 0
    assert "  Its decisions   22 answers: 20 passed, 2 failed" in out
    assert "You have 22 answers. judgekeeper needs at least 30 to show a result." in out
    assert (f"Make more answers with your own eval, then run judgekeeper start "
            f"{textio.quote_arg(tmp_path)} again:") in out
    assert ("  Add more tests to promptfooconfig.yaml, then run: promptfoo eval -o "
            "results.json") in out
    assert "  Running your eval again makes model calls, so it costs money." in out
    assert "Mark the 22 you have anyway? The result will have wide ranges. [y/N]" in out
    assert "Next: in your browser" not in out


def test_too_few_and_yes_at_the_question_goes_on(tmp_path, capsys, terminal):
    promptfoo_project(tmp_path, split(20, 2))
    terminal.append("y")
    code, out, _ = run(capsys, tmp_path)
    assert code == 0
    assert "Next: in your browser, mark each answer Pass or Fail." in out


def test_too_few_deepeval_adds_the_results_folder_tip(tmp_path, capsys):
    deepeval_project(tmp_path, split(10, 5))
    _, out, _ = run(capsys, tmp_path, yes=False)
    assert ("  Tip: set DEEPEVAL_RESULTS_FOLDER so DeepEval keeps every run, not only the "
            "latest.") in out


def test_a_group_under_five_with_thirty_answers_goes_on(tmp_path, capsys):
    promptfoo_project(tmp_path, split(28, 4))
    code, out, _ = run(capsys, tmp_path)
    assert code == 0
    assert "Its decisions   32 answers: 28 passed, 4 failed" in out
    assert "Your judge failed only 4 of 32 answers." in out
    assert "needs at least" not in out


def test_a_group_under_fifteen_says_so_and_goes_on(tmp_path, capsys):
    promptfoo_project(tmp_path, split(30, 9))
    code, out, _ = run(capsys, tmp_path)
    assert code == 0
    assert ("Your judge failed only 9 of 39 answers. That may mean it passes too much: your "
            "marks will show it.") in out
    assert "Next: in your browser, mark each answer Pass or Fail." in out


def test_a_pass_group_under_fifteen_says_so_too(tmp_path, capsys):
    promptfoo_project(tmp_path, split(12, 30))
    code, out, _ = run(capsys, tmp_path)
    assert code == 0
    assert "Your judge passed only 12 of 42 answers. That may mean it fails too much" in out


# Without a terminal ----------------------------------------------------------------------

def test_without_a_terminal_too_few_stops_with_the_flag(tmp_path, capsys):
    promptfoo_project(tmp_path, split(20, 2))
    code, out, _ = run(capsys, tmp_path, yes=False)
    assert code == start.EXIT_QUESTION
    assert (f"Mark the 22 you have anyway? Run judgekeeper start {textio.quote_arg(tmp_path)} "
            "--yes to say yes.") in out


def test_yes_takes_the_default_answer(tmp_path, capsys):
    promptfoo_project(tmp_path, split(20, 2))
    code, out, _ = run(capsys, tmp_path, "--yes")
    assert code == 0
    assert "Next: in your browser, mark each answer Pass or Fail." in out


def test_without_a_terminal_nothing_is_asked(tmp_path, capsys, monkeypatch):
    promptfoo_project(tmp_path, split(20, 2))

    def no_input(prompt=""):
        raise AssertionError("asked without a terminal")

    monkeypatch.setattr(builtins, "input", no_input)
    code, _, _ = run(capsys, tmp_path, yes=False)
    assert code == start.EXIT_QUESTION
