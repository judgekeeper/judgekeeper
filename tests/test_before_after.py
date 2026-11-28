"""Two graded results, compared question by question: helped, made it worse, or can't tell yet.

- The newest results against the last graded results judgekeeper read in the project, or
  (`--before FILE`) against that file. A question is the same when its text hash is.
- fixed: Fail before, Pass now; broke: Pass before, Fail now; the rest the same. The verdict is
  no_grades.change_kind with test=1.
- Exit 1 only on "made it worse". The lines say no answer or question text, and the baseline
  file holds hashes and grades only.
- With no baseline the run is as it was.
No test calls an AI API.
"""

from __future__ import annotations

import csv
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from judgekeeper import no_grades
from judgekeeper.cli import main
from judgekeeper.start_label import StartSession, Workspace
from tests.start_projects import inspect_project, promptfoo_project, split, table_project
from tests.test_front import assert_one_next_at_the_end, before_comparison, flat, next_lines

TAG = " SECRET-7f3a"  # put into every question and answer, so a leak shows
BASELINE = ".judgekeeper/last-graded.json"
GOLDEN = Path(__file__).parent / "fixtures" / "before_after" / "first-run.txt"

HELPED = "Your change helped. A difference this large is unlikely to be a coincidence."
WORSE = "Your change made it worse. A difference this large is unlikely to be a coincidence."
LEANS_WORSE = "Can't tell yet. That leans toward worse."
SAME = "Can't tell yet. Before and after look about the same."
COUNTED = "Counted from the grades in your results, not from your marks."
NEXT_WORSE = "Next: fix what broke or undo your change, then run your eval again."
NO_MATCH = "No question is in both results, so there is nothing to compare."
NO_MATCH_NEXT = ("Next: give each question an id that stays the same from run to run (such as "
                 "an `id` column), then run your eval again.")
RESTARTED = ("Your LLM-as-a-judge setup changed since the last results, so there is nothing to "
             "compare yet. This run is the new starting point.")
OTHER_SETUP = ("The two results were graded by different LLM-as-a-judge setups (the model, rule "
               "or pass mark changed), so judgekeeper does not compare them.")
OTHER_SETUP_NEXT = "Next: compare results graded by the same LLM-as-a-judge setup."
NO_MATCH_IDS_NEXT = ("Next: check that you compare results of the same eval: the two share no "
                     "question id.")
NO_IDS_ONE_SIDE = ("Only one of the two results names its questions by an id, so judgekeeper "
                   "can't tell which questions are the same, and compares nothing.")


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def said(capsys, *argv):
    code = main([str(a) for a in argv])
    out, err = capsys.readouterr()
    return code, out + err


def counts(fixed: int, broke: int, same: int) -> str:
    n = fixed + broke + same
    return (f"On the {n} questions in both results: fixed {fixed}, broke {broke}, "
            f"same {same}.")


def rows_csv(path: Path, rows) -> Path:
    """A CSV of (question, answer, verdict) rows, in the order given."""
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["input", "output", "verdict"])
        for q, a, v in rows:
            w.writerow([q, a, "pass" if v else "fail"])
    return path


def qs(first: int, last: int, verdict, tag: str = ""):
    """Questions `first` to `last` (not including it), each answered once with `verdict`: a
    bool, or a list of them."""
    out = []
    for i in range(first, last):
        v = verdict[i - first] if isinstance(verdict, list) else verdict
        out.append((f"Question {i}?{tag}", f"Answer {i}.{tag}", v))
    return out


def new_lines(out: str) -> list[str]:
    """The counts line and the line that says where they come from, when they are said."""
    return re.findall(r"On the \d+ questions? in both results: fixed \d+, broke \d+, same \d+\.|"
                      + re.escape(COUNTED), flat(out))


# The same flow for every eval tool ---------------------------------------------------------

def _promptfoo(root, verdicts):
    return promptfoo_project(root, verdicts, name="results.json").name


def _inspect(root, verdicts):
    return inspect_project(root, verdicts, name="logs/support.json").relative_to(root).as_posix()


def _table(root, verdicts):
    return table_project(root, verdicts, name="results.csv").name


WRITERS = {"promptfoo": _promptfoo, "inspect": _inspect, "csv": _table}
MADE_WORSE = [False] * 12 + [True] * 28  # 40 questions, 12 broke
ALL_PASS = [True] * 40


@pytest.mark.parametrize("tool", WRITERS)
def test_a_drop_since_the_last_results_says_it_made_it_worse_and_exits_1(here, capsys, tool):
    path = WRITERS[tool](here, ALL_PASS)
    said(capsys, path)
    WRITERS[tool](here, MADE_WORSE)
    code, out = said(capsys, path)
    assert code == 1, out
    assert counts(0, 12, 28) in flat(out)
    assert COUNTED in flat(out)
    assert WORSE in flat(out)
    assert next_lines(out)[-1] == NEXT_WORSE


def test_made_worse_says_the_usual_next_step_then_its_own(here, capsys):
    """Two Next: lines, in this order: the usual step ends the usual output, then the
    comparison ends with its own."""
    path = _table(here, ALL_PASS)
    said(capsys, path)
    _table(here, MADE_WORSE)
    code, out = said(capsys, path)
    assert code == 1, out
    usual = assert_one_next_at_the_end(before_comparison(out))
    assert next_lines(out) == [usual, NEXT_WORSE]
    assert usual != NEXT_WORSE
    assert flat(out).endswith(NEXT_WORSE)


@pytest.mark.parametrize("change", [None, "same"])
def test_with_no_comparison_the_run_ends_on_its_one_next_line(here, capsys, change):
    """The first run, and results saved again unchanged: nothing is compared, so the run ends
    as it always did."""
    path = _table(here, MADE_WORSE)
    if change:
        said(capsys, path)
        _table(here, MADE_WORSE)
    code, out = said(capsys, path)
    assert code == 0, out
    assert before_comparison(out) == out
    assert_one_next_at_the_end(out)


@pytest.mark.parametrize("tool", WRITERS)
def test_a_rise_since_the_last_results_says_it_helped_and_does_not_exit_1(here, capsys, tool):
    path = WRITERS[tool](here, MADE_WORSE)
    said(capsys, path)
    WRITERS[tool](here, ALL_PASS)
    code, out = said(capsys, path)
    assert code != 1, out
    assert counts(12, 0, 28) in flat(out)
    assert HELPED in flat(out)
    assert NEXT_WORSE not in flat(out)


@pytest.mark.parametrize("tool", WRITERS)
def test_a_few_fails_lean_worse_and_do_not_exit_1(here, capsys, tool):
    path = WRITERS[tool](here, ALL_PASS)
    said(capsys, path)
    WRITERS[tool](here, [False] * 3 + [True] * 37)
    code, out = said(capsys, path)
    assert code == 0, out
    assert counts(0, 3, 37) in flat(out)
    assert LEANS_WORSE in flat(out)
    assert WORSE not in flat(out) and NEXT_WORSE not in flat(out)


@pytest.mark.parametrize("tool", WRITERS)
def test_as_many_fixed_as_broke_is_the_same(here, capsys, tool):
    before = [False, False] + [True] * 38
    after = [True, True, False, False] + [True] * 36
    path = WRITERS[tool](here, before)
    said(capsys, path)
    WRITERS[tool](here, after)
    code, out = said(capsys, path)
    assert code == 0, out
    assert counts(2, 2, 36) in flat(out)
    assert SAME in flat(out)


@pytest.mark.parametrize("tool", WRITERS)
def test_questions_in_only_one_run_are_left_out_for_every_tool(here, capsys, tool):
    path = WRITERS[tool](here, ALL_PASS)
    said(capsys, path)
    WRITERS[tool](here, MADE_WORSE + [True] * 4)  # questions 40 to 43 are new
    code, out = said(capsys, path)
    assert code == 1, out
    assert counts(0, 12, 28) in flat(out)
    assert "4 questions are in only one of the two results and are left out." in flat(out)


@pytest.mark.parametrize("tool", WRITERS)
def test_fewer_than_five_in_both_never_exit_1_for_every_tool(here, capsys, tool):
    path = WRITERS[tool](here, [True] * 4)
    said(capsys, path)
    WRITERS[tool](here, [False] * 4 + [True] * 36)  # all 4 in both broke
    code, out = said(capsys, path)
    assert code != 1, out
    assert counts(0, 4, 0) in flat(out)
    assert LEANS_WORSE in flat(out) and WORSE not in flat(out)


def _promptfoo_repeats(root, verdicts, again):
    """promptfoo with `--repeat`: each test asked again, graded `again`."""
    from tests.start_projects import promptfoo_data

    data = promptfoo_data(verdicts)
    rows = data["results"]["results"]
    rows += [json.loads(json.dumps(r)) | {"id": f"again-{n}"} for n, r in enumerate(rows)]
    for r, v in zip(rows[len(verdicts):], again, strict=True):
        r["success"] = r["gradingResult"]["pass"] = v
        r["gradingResult"]["componentResults"][0].update({"pass": v, "score": 1 if v else 0})
    promptfoo_project(root, [])  # the config beside it
    (root / "results.json").write_text(json.dumps(data), encoding="utf-8")
    return "results.json"


def _inspect_repeats(root, verdicts, again):
    """Inspect AI with `--epochs 2`: each sample again in epoch 2, graded `again`."""
    from tests.start_projects import inspect_data

    data = inspect_data(verdicts)
    more = []
    for s, v in zip(data["samples"], again, strict=True):
        s2 = json.loads(json.dumps(s))
        s2["epoch"] = 2
        s2["scores"]["model_graded_qa"]["value"] = "C" if v else "I"
        more.append(s2)
    data["samples"] += more
    path = root / "logs" / "support.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return "logs/support.json"


@pytest.mark.parametrize("repeats", [_promptfoo_repeats, _inspect_repeats])
def test_repeats_follow_the_rule_of_the_marks(here, capsys, repeats):
    """Question 0 failed once and passes twice now: fixed. Questions 1 to 12 passed twice and
    fail once now: broke. Question 13 failed twice and passes once now: not fixed."""
    before = [False] + [True] * 12 + [False] + [True] * 26
    before_again = [True] * 13 + [False] + [True] * 26
    now = [True] * 14 + [True] * 26
    now_again = [True] + [False] * 12 + [False] + [True] * 26
    path = repeats(here, before, before_again)
    said(capsys, path)
    repeats(here, now, now_again)
    code, out = said(capsys, path)
    assert counts(1, 12, 27) in flat(out), out
    assert code == 1


def test_the_verdict_is_change_kind_with_one_test(here, capsys):
    """The line is no_grades.CHANGE's, word for word, at the sign test change_kind makes."""
    for fixed, broke, same in [(0, 12, 28), (12, 0, 28), (0, 3, 37), (3, 3, 34), (2, 6, 32)]:
        before = [False] * fixed + [True] * (broke + same)
        after = [True] * fixed + [False] * broke + [True] * same
        folder = here / f"k{fixed}-{broke}"
        folder.mkdir()
        path = table_project(folder, before, name="results.csv").name
        main([str(folder / path)])
        capsys.readouterr()
        table_project(folder, after, name="results.csv")
        code, out = said(capsys, folder / path)
        kind = no_grades.change_kind(fixed, broke, fixed + broke + same, test=1)
        assert no_grades.CHANGE[kind] in flat(out), out
        assert (code == 1) == (kind == "worse")


# What is compared ----------------------------------------------------------------------------

def test_with_fewer_than_five_questions_in_both_it_never_exits_1(here, capsys):
    """With --before: so few shared questions in place would be another eval."""
    rows_csv(here / "before.csv", qs(0, 30, True))
    rows_csv(here / "results.csv", qs(26, 56, False))  # questions 26 to 29 are in both
    code, out = said(capsys, "results.csv", "--before", "before.csv")
    assert code != 1, out
    assert counts(0, 4, 0) in flat(out)
    assert LEANS_WORSE in flat(out)
    assert WORSE not in flat(out)


def test_questions_in_only_one_results_are_counted_once_in_a_line_and_left_out(here, capsys):
    path = rows_csv(here / "results.csv", qs(0, 40, True))
    said(capsys, path)
    rows_csv(path, qs(10, 50, True))  # 30 in both, 10 only before, 10 only now
    code, out = said(capsys, path)
    assert code == 0, out
    assert counts(0, 0, 30) in flat(out)
    assert "20 questions are in only one of the two results and are left out." in flat(out)


def test_no_line_about_questions_in_one_results_when_there_are_none(here, capsys):
    path = _table(here, ALL_PASS)
    said(capsys, path)
    _table(here, MADE_WORSE)
    _, out = said(capsys, path)
    assert "only one of the two results" not in flat(out)


def test_a_question_with_several_answers_follows_the_rule_of_the_marks(here, capsys):
    """no_grades._fixed and _broke: fixed is a Fail before and all Pass now; broke is all Pass
    before and a Fail now."""
    before = [  # question 0 passed once, 1 failed once and passed once, 2 and 3 passed
        ("Question 0?", "a", True), ("Question 1?", "a", False), ("Question 1?", "b", True),
        ("Question 2?", "a", True), ("Question 3?", "a", True)]
    before += qs(4, 40, True)
    after = [  # 0 now passes and fails: broke; 1 passes both: fixed; 2 fails: broke; 3 as before
        ("Question 0?", "a2", True), ("Question 0?", "b2", False),
        ("Question 1?", "a2", True), ("Question 1?", "b2", True),
        ("Question 2?", "a2", False), ("Question 3?", "a", True)]
    after += qs(4, 40, True)
    path = rows_csv(here / "results.csv", before)
    said(capsys, path)
    rows_csv(path, after)
    code, out = said(capsys, path)
    assert counts(1, 2, 37) in flat(out), out
    assert code != 1


def test_a_question_asked_twice_with_the_same_grade_is_one_question(here, capsys):
    before = qs(0, 40, True) + [("Question 0?", "again", True)]
    after = qs(0, 40, False) + [("Question 0?", "again", False)]
    path = rows_csv(here / "results.csv", before)
    said(capsys, path)
    rows_csv(path, after)
    code, out = said(capsys, path)
    assert code == 1, out
    assert counts(0, 40, 0) in flat(out)


def test_amounts_with_thousands_separators_are_compared(here, capsys):
    """A CSV whose questions and answers hold amounts like "$50,000 = $200,000" is read and
    compared like any other."""
    def money(verdicts):
        return [(f"Is ${i},000 x 4 = ${4 * i},000?", f"Yes: ${i},000 = ${4 * i},000 / 4.", v)
                for i, v in enumerate(verdicts, 50)]

    path = rows_csv(here / "results.csv", money(ALL_PASS))
    said(capsys, path)
    rows_csv(path, money(MADE_WORSE))
    code, out = said(capsys, path)
    assert code == 1, out
    assert counts(0, 12, 28) in flat(out)
    assert "$50,000" not in out


def test_a_question_is_the_same_when_only_its_spaces_differ(here, capsys):
    """no_grades.question_key: runs of spaces and line breaks read as one space."""
    rows_csv(here / "before.csv", qs(0, 40, True))
    rows_csv(here / "results.csv", [(q.replace(" ", "  "), a, False) for q, a, _ in qs(0, 40, True)])
    code, out = said(capsys, "results.csv", "--before", "before.csv")
    assert code == 1, out
    assert counts(0, 40, 0) in flat(out)


def ids_csv(path: Path, rows) -> Path:
    """A CSV of (id, question, answer, verdict) rows."""
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "input", "output", "verdict"])
        for i, q, a, v in rows:
            w.writerow([i, q, a, "pass" if v else "fail"])
    return path


def test_a_question_is_its_test_case_id_when_the_results_have_one(here, capsys):
    """The id column, not the text: a new prompt written into each question is still the same
    test case."""
    path = ids_csv(here / "results.csv",
                   [(f"case-{i}", f"Prompt v1. Question {i}?", f"Answer {i}.", True)
                    for i in range(40)])
    said(capsys, path)
    ids_csv(path, [(f"case-{i}", f"Prompt v2. Question {i}?", f"Answer {i}.", i >= 12)
                   for i in range(40)])
    code, out = said(capsys, path)
    assert code == 1, out
    assert counts(0, 12, 28) in flat(out)
    text = (here / BASELINE).read_text(encoding="utf-8")
    assert "case-" not in text and "Prompt" not in text


def test_two_test_cases_with_the_same_text_are_two_questions(here, capsys):
    rows = [(f"case-{i}", f"Question {i // 2}?", f"Answer {i}.", True) for i in range(40)]
    path = ids_csv(here / "results.csv", rows)
    said(capsys, path)
    ids_csv(path, [(i, q, a, n % 2 == 0) for n, (i, q, a, _) in enumerate(rows)])
    code, out = said(capsys, path)
    assert counts(0, 20, 20) in flat(out), out
    assert code == 1


def _no_question_in_both(here, capsys):
    """judgekeeper.record() files written again with other test cases: the same eval by its
    tool, no question kept."""
    path = _records(here, ALL_PASS)
    said(capsys, path)
    _records(here, MADE_WORSE, ids="other-")
    return said(capsys, path)


def test_results_with_no_question_in_both_say_so_in_one_line_and_no_verdict(here, capsys):
    code, out = _no_question_in_both(here, capsys)
    assert NO_MATCH in flat(out), out
    assert code == 3
    assert "only one of the two results" not in flat(out)
    assert "On the" not in flat(out).replace("On the page", "")
    assert not any(line in flat(out) for line in no_grades.CHANGE.values())
    assert COUNTED not in out


def test_no_question_in_both_needs_you_so_a_pipeline_stops(here, capsys):
    """A bot broken so badly that no question is the same must not pass a gate: exit 3."""
    code, out = _no_question_in_both(here, capsys)
    assert code == 3, out
    assert flat(out).endswith(f"{NO_MATCH} {NO_MATCH_IDS_NEXT}")  # both name their samples


def test_before_with_no_question_in_both_needs_you(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    rows_csv(tmp_path / "main-results.csv", qs(0, 40, True))
    rows_csv(tmp_path / "results.csv", qs(100, 140, False))
    code, out = said(capsys, "results.csv", "--before", "main-results.csv")
    assert code == 3, out
    assert NO_MATCH in flat(out)
    assert next_lines(out)[-1] == NO_MATCH_NEXT


# A question is its own test-case id, for every format that keeps one ------------------------

def _deepeval(root, verdicts, tag=""):
    from tests.start_projects import deepeval_project

    return deepeval_project(root, verdicts, tag=tag).relative_to(root).as_posix()


def _records(root, verdicts, tag="", ids="case-"):
    """A file as judgekeeper.record() writes it, with the caller's own target_id."""
    folder = root / ".judgekeeper" / "records"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "Safe-wording-2026-10-05-4101.jsonl"
    with path.open("w", encoding="utf-8") as f:
        for i, v in enumerate(verdicts):
            f.write(json.dumps({
                "schema_version": 2, "target_id": f"{ids}{i}", "name": "Safe wording",
                "annotator_kind": "LLM", "label": "pass" if v else "fail", "score": None,
                "explanation": f"reason {i}", "run": None,
                "input": f"System: be kind.{tag} Question {i}?", "output": f"Answer {i}.",
                "evaluator": {"model": "claude-opus-5", "rule": "Be polite."},
                "created_at": "2026-10-05T10:00:00Z"}) + "\n")
    return "."  # found in the project, not given by path


def _inspect_named(root, verdicts, tag=""):
    """An Inspect AI log whose samples have ids of their own, not plain numbers."""
    from tests.start_projects import inspect_data

    data = inspect_data(verdicts, tag=tag)
    for i, s in enumerate(data["samples"]):
        s["id"] = f"sample-{i}"
    path = root / "logs" / "support.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return "logs/support.json"


OWN_IDS = {  # each keeps its own id while the prompt written into every question changes
    "promptfoo": lambda root, v, tag="": promptfoo_project(root, v, tag=tag).name,
    "inspect": lambda root, v, tag="": _inspect_named(root, v, tag),
    "deepeval": _deepeval,
    "records": _records,
}


@pytest.mark.parametrize("tool", OWN_IDS)
def test_a_new_prompt_in_every_question_still_meets_the_same_test_cases(here, capsys, tool):
    path = OWN_IDS[tool](here, ALL_PASS)
    said(capsys, path)
    OWN_IDS[tool](here, MADE_WORSE, tag=" Prompt v2.")
    code, out = said(capsys, path)
    assert code == 1, out
    assert counts(0, 12, 28) in flat(out)
    assert NO_MATCH not in flat(out)


def test_inspect_samples_with_no_id_are_matched_by_their_text(here, capsys):
    """Inspect AI's reader writes "None" for a sample with no id: those are not one case."""
    from tests.start_projects import inspect_data

    def write(verdicts):
        data = inspect_data(verdicts)
        for s in data["samples"]:
            s["id"] = None
        path = here / "logs" / "support.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")
        return "logs/support.json"

    path = write(ALL_PASS)
    said(capsys, path)
    write(MADE_WORSE)
    code, out = said(capsys, path)
    assert counts(0, 12, 28) in flat(out), out
    assert code == 1


def test_marks_stay_on_their_answers_for_a_file_with_its_own_ids(here, capsys):
    """Only the question's key uses the test-case id: an Inspect answer's id is still made
    from its text, so the marks made on the page stay attached to the same answers."""
    path = OWN_IDS["inspect"](here, split(30, 10))
    said(capsys, path)
    session = StartSession(Workspace(here))
    marked = {item["id"] for item in session.items[:3]}
    for item_id in marked:
        session.update({"id": item_id, "label": "pass", "seconds": 5})
    said(capsys, path)
    again = StartSession(Workspace(here))
    assert set(again.marked()) == marked
    assert not marked & {str(i) for i in range(40)}  # not the sample ids


# The same eval when its test cases keep their ids ---------------------------------------------

ANOTHER_EVAL = "looks like another eval"


def _ids_csv(root, verdicts, tag=""):
    return ids_csv(root / "results.csv", [(f"case-{i}", f"Question {i}?{tag}", f"Answer {i}.",
                                           v) for i, v in enumerate(verdicts)]).name


def _other_promptfoo(root, verdicts):
    """A promptfoo file of another eval: other tests, with other descriptions."""
    from tests.start_projects import promptfoo_data

    data = promptfoo_data(verdicts, tag=" Other eval.")
    for i, row in enumerate(data["results"]["results"]):
        row["testCase"]["description"] = f"other {i}"
        row["vars"] = row["testCase"]["vars"] = {"question": f"Other thing {i}?"}
    (root / "results.json").write_text(json.dumps(data), encoding="utf-8")


def _other_csv(root, verdicts):
    ids_csv(root / "results.csv", [(f"other-{i}", f"Other thing {i}?", f"Answer {i}.", v)
                                   for i, v in enumerate(verdicts)])


BY_ID = {"csv": _ids_csv, **OWN_IDS}


@pytest.mark.parametrize("tool", BY_ID)
def test_kept_ids_with_a_new_prompt_are_the_same_eval(here, capsys, tool):
    """The same text put before every question, the ids kept: the newest results of this
    eval, so its changed answers are added for marking and the run ends on one comparison."""
    path = BY_ID[tool](here, ALL_PASS)
    said(capsys, path)
    BY_ID[tool](here, MADE_WORSE, tag=" Prompt v2.")
    code, out = said(capsys, path)
    assert code == 1, out
    assert ANOTHER_EVAL not in flat(out) and "folder of its own" not in flat(out)
    assert counts(0, 12, 28) in flat(out)
    assert flat(out).count(WORSE) == 1
    assert next_lines(out)[-1] == NEXT_WORSE


@pytest.mark.parametrize("tool", ["csv", "promptfoo", "inspect"])
def test_kept_ids_add_the_changed_answers_for_marking(here, capsys, tool):
    path = BY_ID[tool](here, ALL_PASS)
    said(capsys, path)
    BY_ID[tool](here, ALL_PASS, tag=" Prompt v2.")
    code, out = said(capsys, path)
    assert ANOTHER_EVAL not in flat(out), out
    assert "Your newest results have 40 answers you haven't seen. They're added for marking." \
        in flat(out)
    assert code != 1


OTHER = {"csv": (_ids_csv, _other_csv), "promptfoo": (OWN_IDS["promptfoo"], _other_promptfoo)}


@pytest.mark.parametrize("tool", OTHER)
def test_a_file_of_another_eval_with_other_ids_is_still_another_eval(here, capsys, tool):
    first, other = OTHER[tool]
    path = first(here, ALL_PASS)
    said(capsys, path)
    other(here, MADE_WORSE)
    code, out = said(capsys, path)
    assert ANOTHER_EVAL in flat(out), out
    assert code == 3


# Ids that are plain numbers: row numbers, Inspect AI's own numbering -----------------------------

NUMBERED_IDS = ("The questions changed and their ids are plain numbers, so judgekeeper can't "
                "tell they are the same questions.")


def _numbered(root, verdicts, tag=""):
    return ids_csv(root / "results.csv", [(str(i + 1), f"Question {i}?{tag}", f"Answer {i}.", v)
                                          for i, v in enumerate(verdicts)]).name


@pytest.mark.parametrize("ci", [False, True])
def test_numbered_ids_with_a_new_prompt_say_so_and_compare_nothing(here, capsys, monkeypatch,
                                                                    ci):
    if ci:
        monkeypatch.setenv("CI", "true")
    path = _numbered(here, ALL_PASS)
    said(capsys, path)
    pool = (here / ".judgekeeper" / "pool.jsonl").read_text(encoding="utf-8")
    _numbered(here, MADE_WORSE, tag=" Prompt v2.")
    code, out = said(capsys, path)
    assert code == 3, out
    assert NUMBERED_IDS in flat(out)
    assert next_lines(out) == [("Next: run `judgekeeper results.csv --before FILE`, with your "
                               "earlier results as FILE, to compare them, or put results.csv in a "
                               "folder of its own to mark it.")]
    assert new_lines(out) == [] and WORSE not in flat(out) and NO_MATCH not in flat(out)
    assert (here / ".judgekeeper" / "pool.jsonl").read_text(encoding="utf-8") == pool


def test_an_unrelated_eval_with_numbered_ids_is_never_pooled(here, capsys):
    path = _numbered(here, ALL_PASS)
    said(capsys, path)
    pool = (here / ".judgekeeper" / "pool.jsonl").read_text(encoding="utf-8")
    ids_csv(here / "results.csv", [(str(i + 1), f"Other thing {i}?", f"Other answer {i}.", True)
                                   for i in range(40)])
    code, out = said(capsys, path)
    assert ANOTHER_EVAL in flat(out), out
    assert "added for marking" not in flat(out) and new_lines(out) == []
    assert code == 3
    assert (here / ".judgekeeper" / "pool.jsonl").read_text(encoding="utf-8") == pool


def test_before_matches_numbered_ids(tmp_path, monkeypatch, capsys):
    """The person chose both files: a plain-number id is the same question there."""
    monkeypatch.chdir(tmp_path)
    ids_csv(tmp_path / "main-results.csv",
            [(str(i + 1), f"Question {i}?", f"Answer {i}.", True) for i in range(40)])
    ids_csv(tmp_path / "results.csv", [(str(i + 1), f"Prompt v2. Question {i}?", f"Answer {i}.",
                                        v) for i, v in enumerate(MADE_WORSE)])
    code, out = said(capsys, "results.csv", "--before", "main-results.csv")
    assert counts(0, 12, 28) in flat(out), out
    assert code == 1


def test_an_inspect_log_rewritten_in_place_with_other_questions_is_not_pooled(here, capsys):
    """A log given by its path in a folder below: the file read now is checked for another
    eval too, so its answers never join the marked ones."""
    from tests.start_projects import inspect_data

    path = inspect_project(here, ALL_PASS, name="logs/support.json").relative_to(here).as_posix()
    said(capsys, path)
    pool = (here / ".judgekeeper" / "pool.jsonl").read_text(encoding="utf-8")
    data = inspect_data(MADE_WORSE)  # the same sample numbers, 0 to 39
    for i, s in enumerate(data["samples"]):
        s["input"] = f"Other thing {i}?"
        s["output"]["completion"] = f"Other answer {i}."
    (here / path).write_text(json.dumps(data), encoding="utf-8")
    code, out = said(capsys, path)
    assert ANOTHER_EVAL in flat(out), out
    assert NUMBERED_IDS in flat(out)
    assert "added for marking" not in flat(out) and new_lines(out) == []
    assert code == 3
    assert (here / ".judgekeeper" / "pool.jsonl").read_text(encoding="utf-8") == pool


def test_a_few_ids_kept_with_other_text_is_still_another_eval(here, capsys):
    path = _ids_csv(here, ALL_PASS)
    said(capsys, path)
    ids_csv(here / "results.csv", [(f"case-{i}" if i < 5 else f"new-{i}", f"Other thing {i}?",
                                    f"Answer {i}.", True) for i in range(40)])
    code, out = said(capsys, path)
    assert ANOTHER_EVAL in flat(out), out
    assert code == 3


# The baseline ---------------------------------------------------------------------------------

def test_the_first_graded_run_compares_nothing(here, capsys):
    path = _table(here, MADE_WORSE)
    code, out = said(capsys, path)
    assert code == 0, out
    assert new_lines(out) == []
    assert NEXT_WORSE not in out


def test_the_same_results_read_again_say_the_same_thing(here, capsys):
    """The baseline is the results before these, so a second run on them is no new baseline:
    the gate says the same each time."""
    path = _table(here, ALL_PASS)
    said(capsys, path)
    _table(here, MADE_WORSE)
    first = said(capsys, path)
    again = said(capsys, path)
    assert first[0] == again[0] == 1
    assert new_lines(first[1]) == new_lines(again[1])
    assert counts(0, 12, 28) in flat(again[1])


def test_results_saved_again_unchanged_are_not_compared_with_themselves(here, capsys):
    path = _table(here, MADE_WORSE)
    said(capsys, path)
    _table(here, MADE_WORSE)
    code, out = said(capsys, path)
    assert code == 0, out
    assert new_lines(out) == []


def test_the_baseline_holds_hashes_and_grades_never_text(here, capsys):
    path = _table(here, ALL_PASS)
    table_project(here, ALL_PASS, name="results.csv", tag=TAG)
    said(capsys, path)
    table_project(here, MADE_WORSE, name="results.csv", tag=TAG)
    said(capsys, path)
    text = (here / BASELINE).read_text(encoding="utf-8")
    assert "SECRET" not in text and "Question" not in text and "Answer" not in text
    data = json.loads(text)
    grades = {g for side in ("before", "now") for v in data[side]["questions"].values()
              for g in v}
    assert grades == {"pass", "fail"}
    assert all(re.fullmatch(r"[0-9a-f]+", k) for k in data["now"]["questions"])


def test_no_question_or_answer_text_is_printed(here, capsys):
    table_project(here, ALL_PASS, name="results.csv", tag=TAG)
    said(capsys, "results.csv")
    table_project(here, MADE_WORSE, name="results.csv", tag=TAG)
    code, out = said(capsys, "results.csv")
    assert code == 1
    assert "SECRET" not in out and "Question " not in out and "Answer " not in out


def test_the_baseline_is_never_written_through_a_link(here, capsys):
    path = _table(here, ALL_PASS)
    said(capsys, path)
    target = here / "elsewhere.json"
    target.write_text("{}", encoding="utf-8")
    baseline = here / BASELINE
    baseline.unlink(missing_ok=True)
    try:
        baseline.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("no symbolic links here")
    _table(here, MADE_WORSE)
    said(capsys, path)
    assert target.read_text(encoding="utf-8") == "{}"


def test_another_llm_as_a_judge_is_not_compared_with_the_last_one(here, capsys):
    """Its grades say nothing about a change to your AI: the baseline starts again, on this
    run and the next."""
    path = table_project(here, ALL_PASS, name="results.csv", verdict_column="verdict")
    said(capsys, path)
    table_project(here, MADE_WORSE, name="results.csv", verdict_column="correct")
    for _ in range(2):
        code, out = said(capsys, path)
        assert code != 1, out
        assert new_lines(out) == [] and WORSE not in flat(out)


def test_another_llm_as_a_judge_kept_out_is_not_compared_either(here, capsys, monkeypatch):
    """Answered no to starting over: the old marks stay, and nothing is compared."""
    path = _table(here, ALL_PASS)
    said(capsys, path)
    session = StartSession(Workspace(here))
    for item in session.items[:3]:
        session.update({"id": item["id"], "label": "pass", "seconds": 5})
    table_project(here, MADE_WORSE, name="results.csv", verdict_column="correct")
    monkeypatch.setattr("judgekeeper.front.FrontTalk.confirm", lambda self, *a, **k: False)
    code, out = said(capsys, path)
    assert "Nothing was moved." in flat(out), out
    assert code != 1, out
    assert new_lines(out) == [] and WORSE not in flat(out)


def _scores(path: Path, values) -> Path:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["input", "output", "score"])
        for i, s in enumerate(values):
            w.writerow([f"Question {i}?", f"Answer {i}.", s])
    return path


def test_a_new_pass_mark_is_not_compared_with_the_last_one(here, capsys):
    """The same answers read with another pass mark: the grades moved because the
    LLM-as-a-judge's setup did, not your AI."""
    path = _scores(here / "results.csv", [0.55] * 12 + [0.9] * 28)
    said(capsys, path, "--pass-if", "score>=0.5", "--no-browser", "--port", "0")
    main(["--stop"])
    capsys.readouterr()
    for _ in range(2):
        code, out = said(capsys, path, "--pass-if", "score>=0.6", "--no-browser", "--port", "0")
        main(["--stop"])
        assert code != 1, out
        assert new_lines(out) == [] and WORSE not in flat(out)


def test_another_judge_model_is_not_compared_with_the_last_one(here, capsys):
    path = table_project(here, ALL_PASS, name="results.csv", model="judge-a")
    said(capsys, path)
    table_project(here, MADE_WORSE, name="results.csv", model="judge-b")
    code, out = said(capsys, path)
    assert code != 1, out
    assert new_lines(out) == [] and WORSE not in flat(out)


@pytest.mark.parametrize("change", ["model", "pass mark"])
def test_a_changed_setup_says_this_run_is_the_new_starting_point(here, capsys, change):
    """Said where the comparison would be, with no Next of its own, once."""
    flags = ["--no-browser", "--port", "0"]
    if change == "model":
        path = table_project(here, ALL_PASS, name="results.csv", model="judge-a")
        said(capsys, path, *flags)
        table_project(here, MADE_WORSE, name="results.csv", model="judge-b")
    else:
        path = _scores(here / "results.csv", [0.55] * 12 + [0.9] * 28)
        said(capsys, path, "--pass-if", "score>=0.5", *flags)
        flags += ["--pass-if", "score>=0.6"]
    main(["--stop"])
    capsys.readouterr()
    code, out = said(capsys, path, *flags)
    main(["--stop"])
    assert flat(out).endswith(RESTARTED), out
    assert code != 1
    code, out = said(capsys, path, *flags)
    main(["--stop"])
    assert RESTARTED not in flat(out), out


def test_a_baseline_changed_by_hand_is_not_used(here, capsys):
    path = _table(here, ALL_PASS)
    said(capsys, path)
    _table(here, MADE_WORSE)
    said(capsys, path)
    data = json.loads((here / BASELINE).read_text(encoding="utf-8"))
    key = next(iter(data["before"]["questions"]))
    data["before"]["questions"][key] = ["fail"]  # no new checksum
    (here / BASELINE).write_text(json.dumps(data), encoding="utf-8")
    code, out = said(capsys, path)
    assert code != 1, out
    assert new_lines(out) == []


# --before FILE ---------------------------------------------------------------------------------

def test_before_compares_with_that_file_and_exits_1_on_a_drop(tmp_path, monkeypatch, capsys):
    """The CI form: a new project folder, the results from main beside the new ones."""
    monkeypatch.chdir(tmp_path)
    rows_csv(tmp_path / "main-results.csv", qs(0, 40, True))
    rows_csv(tmp_path / "results.csv", qs(0, 40, [False] * 12 + [True] * 28))
    code, out = said(capsys, "results.csv", "--before", "main-results.csv")
    assert code == 1, out
    assert counts(0, 12, 28) in flat(out)
    assert WORSE in flat(out)
    assert next_lines(out)[-1] == NEXT_WORSE


def test_before_a_rise_exits_0(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    rows_csv(tmp_path / "main-results.csv", qs(0, 40, [False] * 12 + [True] * 28))
    rows_csv(tmp_path / "results.csv", qs(0, 40, True))
    code, out = said(capsys, "results.csv", "--before", "main-results.csv")
    assert code == 0, out
    assert HELPED in flat(out)


def test_before_takes_the_place_of_the_last_results_read(here, capsys):
    """The last results read here were worse than the file; the file is what is compared."""
    path = _table(here, ALL_PASS)
    said(capsys, path)
    other = rows_csv(here / "other.csv", qs(0, 40, [False] * 12 + [True] * 28))
    code, out = said(capsys, path, "--before", other)
    assert code != 1, out
    assert counts(12, 0, 28) in flat(out)
    assert HELPED in flat(out)


def test_before_reads_with_the_same_judge_of_these_results(tmp_path, monkeypatch, capsys):
    """A column of scores read with --pass-if reads the file before it the same way."""
    monkeypatch.chdir(tmp_path)

    def scores(path, values):
        with path.open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["input", "output", "score"])
            for i, s in enumerate(values):
                w.writerow([f"Question {i}?", f"Answer {i}.", s])

    scores(tmp_path / "main.csv", [0.9] * 40)
    scores(tmp_path / "results.csv", [0.3] * 12 + [0.9] * 28)
    code, out = said(capsys, "results.csv", "--before", "main.csv", "--pass-if", "score>=0.5")
    assert code == 1, out
    assert counts(0, 12, 28) in flat(out)


def test_before_refuses_results_graded_by_another_rule(tmp_path, monkeypatch, capsys):
    """Only the promptfoo llm-rubric changed: the grades moved with the rule, not your AI."""
    monkeypatch.chdir(tmp_path)
    promptfoo_project(tmp_path, ALL_PASS, name="main-results.json", rubric="Is short.")
    promptfoo_project(tmp_path, MADE_WORSE, name="results.json")
    code, out = said(capsys, "results.json", "--before", "main-results.json")
    assert code == 3, out
    assert OTHER_SETUP in flat(out)
    assert next_lines(out)[-1] == OTHER_SETUP_NEXT
    assert WORSE not in flat(out) and new_lines(out) == []


def test_before_refuses_results_graded_by_another_model(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    table_project(tmp_path, ALL_PASS, name="main-results.csv", model="judge-a")
    table_project(tmp_path, MADE_WORSE, name="results.csv", model="judge-b")
    code, out = said(capsys, "results.csv", "--before", "main-results.csv")
    assert code == 3, out
    assert OTHER_SETUP in flat(out) and new_lines(out) == []


def test_before_compares_when_one_side_names_no_judge(tmp_path, monkeypatch, capsys):
    """No judge information on one side: nothing to tell them apart by, compared as before."""
    monkeypatch.chdir(tmp_path)
    table_project(tmp_path, ALL_PASS, name="main-results.csv")
    table_project(tmp_path, MADE_WORSE, name="results.csv", model="judge-b")
    code, out = said(capsys, "results.csv", "--before", "main-results.csv")
    assert code == 1, out
    assert OTHER_SETUP not in flat(out)
    assert counts(0, 12, 28) in flat(out)


def test_before_on_results_with_ids_that_share_none_says_to_check_the_eval(
        tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    ids_csv(tmp_path / "main-results.csv",
            [(f"case-{i}", f"Question {i}?", f"Answer {i}.", True) for i in range(40)])
    ids_csv(tmp_path / "results.csv",
            [(f"other-{i}", f"Other {i}?", f"Answer {i}.", False) for i in range(40)])
    code, out = said(capsys, "results.csv", "--before", "main-results.csv")
    assert code == 3, out
    assert NO_MATCH in flat(out)
    assert next_lines(out)[-1] == NO_MATCH_IDS_NEXT
    assert "Give each question an id" not in flat(out)


def _ids_then_none(tmp_path, monkeypatch, capsys, first_ids: bool):
    """The same 40 questions read twice: once with an id column, once without (or the other
    way round), as after grading marked-answers.csv again with no id column."""
    monkeypatch.chdir(tmp_path)
    rows = [(f"q-{i}", f"Question {i}?", f"Answer {i}.", i % 3 != 0) for i in range(40)]
    plain = [(q, a, not v) for _, q, a, v in rows]

    def write(with_ids: bool) -> None:
        if with_ids:
            ids_csv(tmp_path / "results.csv", rows)
        else:
            rows_csv(tmp_path / "results.csv", plain)
    write(first_ids)
    said(capsys, "results.csv", "--no-browser", "--port", "0")
    said(capsys, "--stop")
    write(not first_ids)
    out = said(capsys, "results.csv", "--no-browser", "--port", "0")
    said(capsys, "--stop")
    return out


@pytest.mark.parametrize("first_ids", [True, False], ids=["ids-then-none", "none-then-ids"])
def test_results_with_ids_on_one_side_only_say_one_line_and_keep_the_runs_exit(
        tmp_path, monkeypatch, capsys, first_ids):
    monkeypatch.delenv("CI", raising=False)
    code, out = _ids_then_none(tmp_path, monkeypatch, capsys, first_ids)
    assert code == 0, out  # the run's own: its Next: line is the last thing said
    assert NO_IDS_ONE_SIDE in flat(out), out
    assert NO_MATCH not in flat(out) and NO_MATCH_NEXT not in flat(out), out
    assert len(next_lines(out)) == 1, out  # the run's own, then the one line, last
    assert flat(out).endswith(NO_IDS_ONE_SIDE), out
    assert_one_next_at_the_end(before_comparison(out))


def test_results_with_ids_on_one_side_only_still_stop_a_pipeline(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CI", "true")
    code, out = _ids_then_none(tmp_path, monkeypatch, capsys, True)
    assert code == 3, out  # a gate never passes on nothing compared
    assert next_lines(out)[-1] == NO_MATCH_NEXT


# --before's grades are read with the same rules as the results' ---------------------------------

def _graded_csv(path: Path, grades) -> Path:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["input", "output", "verdict"])
        for i, g in enumerate(grades):
            w.writerow([f"Question {i}?", f"Answer {i}.", g])
    return path


def test_before_with_grade_words_it_cannot_tell_stops_as_the_results_do(
        tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    _graded_csv(tmp_path / "main-results.csv", ["good"] * 20 + ["bad"] * 20)
    _graded_csv(tmp_path / "results.csv", ["pass"] * 40)
    code, out = said(capsys, "results.csv", "--before", "main-results.csv")
    assert code == 3, out
    assert ("judgekeeper can't tell which of the LLM-as-a-judge's decisions in "
            "main-results.csv mean Pass and which mean Fail: bad, good.") in flat(out)
    assert "--label-map" in next_lines(out)[-1] and "--before main-results.csv" in \
        next_lines(out)[-1]
    assert NO_MATCH not in flat(out) and new_lines(out) == []


def test_before_reads_grade_words_with_the_label_map_given(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    _graded_csv(tmp_path / "main-results.csv", ["good"] * 40)
    _graded_csv(tmp_path / "results.csv", ["bad"] * 12 + ["good"] * 28)
    code, out = said(capsys, "results.csv", "--before", "main-results.csv",
                     "--label-map", "good=pass,bad=fail")
    assert counts(0, 12, 28) in flat(out), out
    assert code == 1


@pytest.mark.parametrize("n, line", [
    (10, "10 questions have no Pass or Fail grade in one of the results and are left out."),
    (1, "1 question has no Pass or Fail grade in one of the results and is left out.")])
def test_questions_with_no_grade_on_one_side_are_left_out_on_a_line_of_their_own(
        tmp_path, monkeypatch, capsys, n, line):
    monkeypatch.chdir(tmp_path)
    _graded_csv(tmp_path / "main-results.csv", ["pass"] * (40 - n) + ["error"] * n)
    _graded_csv(tmp_path / "results.csv", ["pass"] * 40)
    code, out = said(capsys, "results.csv", "--before", "main-results.csv")
    assert line in flat(out), out
    assert "only one of the two results" not in flat(out)
    assert counts(0, 0, 40 - n) in flat(out)
    assert code == 0


# With --before or in CI the comparison sets the exit code ---------------------------------------

SMALL = 25  # under the answers a first result needs: the usual run asks for marks (exit 3)


def test_before_on_small_results_exits_with_the_comparison(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    rows_csv(tmp_path / "before.csv", qs(0, SMALL, True))
    rows_csv(tmp_path / "results.csv", qs(0, SMALL, [False] + [True] * (SMALL - 1)))
    code, out = said(capsys, "results.csv", "--before", "before.csv")
    assert counts(0, 1, SMALL - 1) in flat(out), out
    assert code == 0


def test_in_ci_small_results_exit_with_the_comparison(here, capsys, monkeypatch):
    monkeypatch.setenv("CI", "true")
    path = rows_csv(here / "results.csv", qs(0, SMALL, True))
    said(capsys, path)
    rows_csv(path, qs(0, SMALL, [False] + [True] * (SMALL - 1)))
    code, out = said(capsys, path)
    assert counts(0, 1, SMALL - 1) in flat(out), out
    assert code == 0
    rows_csv(path, qs(0, SMALL, [False] * 12 + [True] * (SMALL - 12)))
    code, out = said(capsys, path)
    assert WORSE in flat(out), out
    assert code == 1


def test_a_person_with_no_before_keeps_the_usual_exit_code(here, capsys):
    """The run stops at a question (another eval): 3, as it was, whatever the comparison."""
    path = _ids_csv(here, ALL_PASS)
    said(capsys, path)
    _other_csv(here, ALL_PASS)
    code, out = said(capsys, path)
    assert ANOTHER_EVAL in flat(out), out
    assert code == 3


@pytest.mark.parametrize("bad", ["missing.csv", "garbage.csv"])
def test_before_with_a_file_it_cannot_read_is_a_usage_error_with_a_next_line(
        tmp_path, monkeypatch, capsys, bad):
    monkeypatch.chdir(tmp_path)
    rows_csv(tmp_path / "results.csv", qs(0, 40, True))
    (tmp_path / "garbage.csv").write_text("this is not\na results file\n", encoding="utf-8")
    code, out = said(capsys, "results.csv", "--before", bad)
    assert code == 2, out
    assert "unrecognized" not in out  # the flag is known: it is the file that can't be read
    assert len(next_lines(out)) == 1 and "--help" not in out
    assert bad in out
    assert "Question" not in out and "a results file\n" not in out  # no row of either file


def test_before_is_not_a_flag_of_the_other_commands(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    for command in ("mark", "check", "fix"):
        code, out = said(capsys, command, "--before", "x.csv")
        assert code == 2 and "unrecognized arguments: --before" in out, out


def test_help_names_before(capsys):
    assert main(["--help"]) == 0
    assert "--before FILE" in capsys.readouterr().out


# MLflow ---------------------------------------------------------------------------------------

STORE = r"""
import json, os, sys
os.environ["MLFLOW_ALLOW_FILE_STORE"] = "true"
os.environ["MLFLOW_DISABLE_AGENT_HINT"] = "1"
import mlflow
from mlflow.entities import AssessmentSource

folder, verdicts = sys.argv[1], json.loads(sys.argv[2])
mlflow.set_tracking_uri(folder)
mlflow.set_experiment("support")
judge = AssessmentSource(source_type="LLM_JUDGE", source_id="openai:/gpt-4.1")

@mlflow.trace(name="app")
def app(question):
    return f"answer to {question}"

for i, verdict in enumerate(verdicts):
    app(f"question {i}")
    mlflow.flush_trace_async_logging()
    trace_id = mlflow.get_last_active_trace_id()
    mlflow.log_feedback(trace_id=trace_id, name="helpful", value=verdict, source=judge)
"""


def _store(folder: Path, verdicts) -> Path:
    pytest.importorskip("mlflow")
    folder.parent.mkdir(parents=True, exist_ok=True)
    script = folder.parent / f"make-{folder.name}.py"
    script.write_text(STORE, encoding="utf-8")
    subprocess.run([sys.executable, str(script), str(folder), json.dumps(verdicts)], check=True,
                   cwd=folder.parent, capture_output=True)
    script.unlink()
    return folder


@pytest.fixture(scope="module")
def stores(tmp_path_factory):
    root = tmp_path_factory.mktemp("stores")
    return {"good": _store(root / "good" / "mlruns", [True] * 20),
            "bad": _store(root / "bad" / "mlruns", [False] * 8 + [True] * 12),
            "few": _store(root / "few" / "mlruns", [False] * 3 + [True] * 17),
            "mixed": _store(root / "mixed" / "mlruns", [True] * 3 + [False] * 3 + [True] * 14)}


def test_mlflow_a_few_fails_lean_worse_and_do_not_exit_1(stores, monkeypatch, capsys):
    monkeypatch.chdir(stores["few"].parent)
    code, out = said(capsys, stores["few"], "--before", stores["good"])
    assert code != 1, out
    assert counts(0, 3, 17) in flat(out)
    assert LEANS_WORSE in flat(out)


def test_mlflow_as_many_fixed_as_broke_is_the_same(stores, monkeypatch, capsys):
    monkeypatch.chdir(stores["mixed"].parent)
    code, out = said(capsys, stores["mixed"], "--before", stores["few"])
    assert code != 1, out
    assert counts(3, 3, 14) in flat(out)
    assert SAME in flat(out)


def test_mlflow_a_drop_against_a_store_before_says_it_made_it_worse(stores, monkeypatch, capsys):
    monkeypatch.chdir(stores["bad"].parent)
    code, out = said(capsys, stores["bad"], "--before", stores["good"])
    assert code == 1, out
    assert counts(0, 8, 12) in flat(out)
    assert WORSE in flat(out)


def test_mlflow_a_rise_against_a_store_before_says_it_helped(stores, monkeypatch, capsys):
    monkeypatch.chdir(stores["good"].parent)
    code, out = said(capsys, stores["good"], "--before", stores["bad"])
    assert code != 1, out
    assert counts(8, 0, 12) in flat(out)
    assert HELPED in flat(out)


# What did not change -------------------------------------------------------------------------

def _normal(out: str) -> str:
    from judgekeeper import __version__

    out = out.replace(f"judgekeeper {__version__}\n", "judgekeeper 1.2.0\n", 1)
    return re.sub(r"http://127\.0\.0\.1:\d+/\?token=\S+", "<link>", out)


def test_a_first_run_on_graded_results_says_what_it_said_before(here, capsys):
    """The golden: with no baseline, this feature says nothing and changes nothing."""
    table_project(here, split(30, 10), name="results.csv")
    code, out = said(capsys, "results.csv")
    assert code == 0
    assert _normal(out) == GOLDEN.read_text(encoding="utf-8")
