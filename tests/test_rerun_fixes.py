"""`fix <file>` with kept-aside answers that have no grade, when every graded one is unchanged
or the rule was tested before; `check`'s words for that earlier test; and the line after the
same answers were graded again. No test calls an API: judgekeeper only reads the results files.
"""

from __future__ import annotations

import json
import re

import pytest

from judgekeeper import fix, reasons, targets
from judgekeeper.check import _day
from tests import test_fix as tf
from tests.start_projects import question
from tests.test_regrade_files import (
    _number,
    _row,
    counted,
    kept_aside,
    project,
    regraded,
    run,
    write,
)


@pytest.fixture
def here(tmp_path, monkeypatch):
    root = tmp_path / "returns-bot"
    root.mkdir()
    monkeypatch.chdir(root)
    return root


def _old_grade(answer: str) -> str:
    """The grade the LLM-as-a-judge the marks were made with gave."""
    return _row(_number(answer))["verdict"]


def _as_before(ws, blank, grade: str = "error") -> list[dict]:
    """marked-answers.csv graded again with every grade the old one gave, but `blank` with
    `grade` (the word error, or nothing)."""
    return [r | {"verdict": grade} if r["output"] in blank else r
            for r in regraded(ws, grade=_old_grade)]


# D1: no grade is never "changes nothing" ------------------------------------------------------

@pytest.mark.parametrize("k", [1, 3])
def test_unchanged_grades_with_some_ungraded_are_counted(here, capsys, k):
    """Every graded answer kept aside has its old grade; `k` the old rule had right have none:
    they count as the new rule's mistakes, `k` broken, and the result says so."""
    ws = project(here)
    capsys.readouterr()
    right = [a for a in kept_aside(ws) if _number(a) % 5]  # the old rule had these right
    code, out = run(capsys, "fix", write(here, "new.csv", _as_before(ws, set(right[:k]))))
    assert code == 0, out
    assert "changes nothing" not in out and "same grades" not in out
    assert counted(k, 30) in out
    assert fix.RESULT[targets.fix_verdict(0, k, 30).kind] in out
    assert f"{k} from right to wrong" in out


@pytest.mark.parametrize("grade, why", [("error", " (such as an error)"), ("", "")])
def test_unchanged_grades_with_most_ungraded_are_refused(here, capsys, grade, why):
    """"(such as an error)" only when an answer was an error: a blank grade may be one the eval
    tool counted as done."""
    ws = project(here)
    capsys.readouterr()
    code, out = run(capsys, "fix", write(here, "new.csv",
                                         _as_before(ws, set(kept_aside(ws)[:16]), grade)))
    assert code == 3, out
    assert "changes nothing" not in out
    assert fix.MOSTLY_BLANK.format(k=16, n=30, have="have", why=why) in out
    assert ("such as an error" in out) == bool(why)
    assert fix.read_split(ws).tests == []


@pytest.mark.parametrize("grade, why", [("error", " (such as an error)"), ("", "")])
def test_answers_missing_and_ungraded_say_an_error_only_for_an_error(here, capsys, grade, why):
    """3 answers kept aside are not in the file and 2 are there with no grade."""
    ws = project(here)
    capsys.readouterr()
    kept = kept_aside(ws)
    rows = [r for r in _as_before(ws, set(kept[3:5]), grade) if r["output"] not in kept[:3]]
    code, out = run(capsys, "fix", write(here, "new.csv", rows))
    assert code == 3, out
    assert ("3 are not in the file and 2 have no decision from your LLM-as-a-judge"
            f"{why}. A rule is tested only on all of them") in out
    assert ("such as an error" in out) == bool(why)


# D2: the refusal first, and a replay says where its result came from -------------------------

def _hidden_numbers(ws) -> list[int]:
    split = tf._split(ws)
    pool = {r["id"]: r for r in map(json.loads, ws.pool.read_text(encoding="utf-8").splitlines())}
    return sorted(int(re.search(r"Question (\d+)\?", json.dumps(pool[i]["input"]))[1])
                  for i in split["hidden"])


def _regraded(root, name: str, blank) -> str:
    """The marked answers graded again with NEW_RULE as the person marked them, `blank` with
    no grade (a promptfoo grader error)."""
    path = tf.regraded(root, grade=lambda i: None if i in blank else tf._person(question(i)),
                       name=name)
    return path.name


def test_a_rule_tested_before_is_refused_when_most_are_ungraded(here, capsys):
    ws = tf.project(here)
    tf.run(capsys)
    hidden = _hidden_numbers(ws)
    n = len(hidden)
    first = _regraded(here, "first.json", set(hidden[:2]))
    assert tf.run(capsys, first)[0] == 0
    code, out = tf.run(capsys, _regraded(here, "most.json", set(hidden[: n // 2 + 1])))
    flat = " ".join(out.split())
    assert code == 3, out
    assert "You tested this LLM-as-a-judge before" not in flat
    assert fix.MOSTLY_BLANK.format(k=n // 2 + 1, n=n, have="have", why="") in flat
    day = _day(tf._split(ws)["tests"][-1]["time"])
    code, out = tf.run(capsys, _regraded(here, "again.json", set(hidden[:4])))
    flat = " ".join(out.split())
    assert code == 0, out
    assert "You tested this LLM-as-a-judge before" in flat
    assert (f"This file leaves 4 of the {n} ungraded; the result above is from first.json "
            f"on {day}.") in flat
    code, out = tf.run(capsys, _regraded(here, "full.json", set()))
    flat = " ".join(out.split())
    assert code == 0, out
    assert (f"full.json has the same rule as first.json ({day}), so the result above is the "
            f"same.") in flat
    assert "ungraded" not in flat
    code, out = tf.run(capsys, "first.json")  # the file the result came from: no other name
    assert code == 0 and (f"This file leaves 2 of the {n} ungraded; the result above is from "
                          f"first.json on {day}.") in " ".join(out.split())


def test_a_table_with_the_grades_of_an_earlier_file_names_both(here, capsys):
    """A result reused for another file says which file is given now and that its grades match
    the earlier one, not that "the result above is from" a file the person did not name."""
    ws = project(here)
    capsys.readouterr()
    rows = regraded(ws, grade=_old_grade)
    rows = [r | {"verdict": "fail" if r["verdict"] == "pass" else "pass"}
            if r["output"] in kept_aside(ws)[:3] else r for r in rows]
    assert run(capsys, "fix", write(here, "nomodel-rule2.csv", rows))[0] == 0
    day = _day(json.loads((ws.dir / "fix" / "split.json").read_text(encoding="utf-8"))
               ["tests"][-1]["time"])
    code, out = run(capsys, "fix", write(here, "regrade-rule2.csv", rows))
    assert code == 0, out
    assert "You tested this LLM-as-a-judge before" in out
    assert (f"regrade-rule2.csv has the same grades as nomodel-rule2.csv ({day}), so the "
            f"result above is the same.") in out
    assert "The result above is from" not in out


# D3: check names the earlier result in fix's own words ----------------------------------------

def test_check_names_an_earlier_result_in_fixs_words(here, capsys):
    """A rule that only breaks 3 answers kept aside: fix says it leans toward worse, and check
    says the same of it, never "looks worse"."""
    ws = tf.project(here)
    tf.run(capsys)
    hidden = _hidden_numbers(ws)
    marks = fix.Marks(ws)
    old = {i: marks.judge[i] for i in marks.judge}
    pool = {r["id"]: r for r in map(json.loads, ws.pool.read_text(encoding="utf-8").splitlines())}
    by_number = {int(re.search(r"Question (\d+)\?", json.dumps(pool[i]["input"]))[1]): i
                 for i in old}
    right = [k for k in hidden if old[by_number[k]] == marks.person[by_number[k]]][:3]
    grades = [(old[by_number[i]] == "pass") != (i in right) for i in range(tf.N)]
    new = tf._results(here, "Worse rule.", grades, name="worse.json")
    _, out = tf.run(capsys, new.name)
    assert "Result: can't tell yet. That leans toward worse." in " ".join(out.split()), out
    new.unlink()
    tf._results(here, "Worse rule.", grades)  # the rule put in, the eval run
    capsys.readouterr()
    tf.main(["check"])
    out = " ".join(capsys.readouterr().out.split())
    day = _day(tf._split(ws)["tests"][-1]["time"])
    assert (f"This is the rule you tested with `judgekeeper fix` on {day} (can't tell yet, "
            "leans toward worse).") in out


@pytest.mark.parametrize("kind", list(fix.RESULT))
def test_each_earlier_result_word_is_fixs_own(kind):
    words = fix.RESULT_WORDS[kind]
    said = fix.RESULT[kind].lower()
    assert all(w in said for w in re.findall(r"[a-z']+", words)), (kind, words)


# suggestions.md: the part marked is answer text, fenced ---------------------------------------

def test_the_part_marked_is_fenced_in_suggestions_md():
    rows = [{"id": "a0", "judge": "pass", "final": "fail", "output": "We refund twice now.",
             "reasons": [], "words": {}, "parts": [], "spans": [[3, 15]], "why": ""}]
    md = reasons.suggestions_md(rows)
    assert "- The part you marked:\n<<<MARKED PART\nrefund twice\nMARKED PART>>>" in md
    outside = re.sub(r"<<<([A-Z][A-Z' 0-9-]*)\n.*?\n\1>>>", "", md, flags=re.DOTALL)
    assert "twice" not in outside
