"""`judgekeeper`, choosing and counting: which results to use when there are several,
the pool of answers (repeats merged, unclear verdicts left out), the judge's name, too few
answers, and what happens without a terminal.
"""

from __future__ import annotations

import builtins
import copy
import json

from judgekeeper import start
from judgekeeper.cli import main
from judgekeeper.normalise import Normaliser
from judgekeeper.records import HUMAN, LLM, RecordList, ScoreRecord
from tests.start_projects import (
    promptfoo_data,
    promptfoo_project,
    split,
)


def run(capsys, *argv, yes=True):
    """`judgekeeper` without a terminal; with --yes unless `yes` is False, so the run goes
    on to the marking page where a person would say yes."""
    argv = [*map(str, argv)] + (["--yes"] if yes and "--yes" not in argv else [])
    code = main([*argv])
    out, err = capsys.readouterr()
    return code, out, err


# Choosing --------------------------------------------------------------------------------


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


def test_an_unknown_metric_lists_the_names(tmp_path, capsys):
    _two_metrics(tmp_path)
    code, _, err = run(capsys, tmp_path, "--metric", "speed")
    assert code == 2
    assert "no judge named 'speed'; judges are: 'helpfulness', 'tone'" in err


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


# The judge's name ------------------------------------------------------------------------


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


# Too few answers -------------------------------------------------------------------------
# (tests/test_start_messages.py has the command for each tool and the few-fails note)


# Without a terminal ----------------------------------------------------------------------


def test_without_a_terminal_nothing_is_asked(tmp_path, capsys, monkeypatch):
    promptfoo_project(tmp_path, split(20, 2))

    def no_input(prompt=""):
        raise AssertionError("asked without a terminal")

    monkeypatch.setattr(builtins, "input", no_input)
    code, _, _ = run(capsys, tmp_path, yes=False)
    assert code == start.EXIT_QUESTION
