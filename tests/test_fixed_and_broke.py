"""Answers with no grades, marked, then new answers to the same questions marked: what changed
since the last answers, question by question. Fixed (Fail, then Pass), broke (Pass, then Fail)
and same are counted on the questions kept aside only, and the sign test says whether the
change helped, as `fix` says it of a new rule."""

from __future__ import annotations

import csv
import json
import os
import re
from html import unescape

import pytest

from judgekeeper import fix, no_grades, start_label
from judgekeeper.targets import SIGN_LEVEL, sign_p
from tests.test_answers_without_grades import _live, _report, _seen, _session
from tests.test_front import flat, run

HELPED = "Your change helped. A difference this large is unlikely to be a coincidence."
WORSE = "Your change made it worse. A difference this large is unlikely to be a coincidence."
LEANS_BETTER = ("Can't tell yet. That leans toward better, but a split this small could easily "
                "be a coincidence.")
LEANS_WORSE = "Can't tell yet. That leans toward worse."
SAME = "Can't tell yet. Before and after look about the same."


def more(need: int, kept: int, extra: int) -> str:
    """What a clear answer needs, after "Can't tell yet" (no_grades.clear_line)."""
    return (f"A clear answer needs at least {need} kept-aside questions to go from Fail to Pass, "
            f"with none breaking. {kept} of yours failed, so add about {extra} more questions.")


WAIT = "Mark the new answers to see what changed."
NO_KEPT = "No question kept aside has a new answer, so your change can't be tested yet."
NEW_SET = ("You have tested 3 changes on these questions kept aside, so they no longer give a "
           "fair test. Add about 10 new questions and mark their answers; half of them are kept "
           "aside as a new test.")


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _ws(here) -> start_label.Workspace:
    return start_label.Workspace(here)


def _q(i: int) -> str:
    return f"What is question {i}?"


def _index(text: str) -> int:
    return int(re.search(r"\d+", text)[0])


def _write(here, outs: dict[int, str], asked: dict[int, str] | None = None) -> None:
    with (here / "results.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["input", "output"])
        w.writeheader()
        for i in sorted(outs):
            w.writerow({"input": (asked or {}).get(i, _q(i)), "output": outs[i]})


def _mark(here, by: dict[int, str]) -> start_label.StartSession:
    """The answers not marked yet, marked as `by` says for their question."""
    page = _session(here)
    for item in page.items:
        m = by.get(_index(page.raw[item["id"]]["input"]))
        if m and not item["label"]:
            page.update({"id": item["id"], "label": m, "seconds": 3})
    return page


class Project:
    """A project with no grades: `first` marks one answer to each question, `again` gives new
    answers to some questions and marks them."""

    def __init__(self, here, capsys):
        self.here, self.capsys, self.outs, self.marks, self.round = here, capsys, {}, {}, 0

    def run(self) -> str:
        code, out, err = run(self.capsys, "--no-browser")
        assert code == 0, out + err
        return flat(out)

    def first(self, fails: set[int], n: int = 10) -> str:
        self.outs = {i: f"First answer {i}." for i in range(n)}
        self.marks = {i: "fail" if i in fails else "pass" for i in range(n)}
        _write(self.here, self.outs)
        self.run()
        _mark(self.here, self.marks)
        return self.run()

    def side(self) -> dict[int, str]:
        """Each question's side now: "kept" or "shown"."""
        split, page = no_grades.read_split(_ws(self.here)), _session(self.here)
        out = {}
        for i in split.hidden:
            out[_index(page.raw[i]["input"])] = "kept"
        for i in split.seen:
            out[_index(page.raw[i]["input"])] = "shown"
        return out

    def kept(self, mark: str | None = None) -> list[int]:
        return sorted(i for i, s in self.side().items() if s == "kept"
                      and mark in (None, self.marks[i]))

    def shown(self, mark: str | None = None) -> list[int]:
        return sorted(i for i, s in self.side().items() if s == "shown"
                      and mark in (None, self.marks[i]))

    def again(self, new: dict[int, str | None], marked: bool = True) -> str:
        """New answers to the questions in `new`, each then marked as it says (None: left
        unmarked); the others keep their answer. The run after it."""
        self.round += 1
        for i in new:
            self.outs[i] = f"Answer {i}, take {self.round + 1}."
        _write(self.here, self.outs)
        self.run()
        if marked:
            _mark(self.here, {i: m for i, m in new.items() if m})
            self.marks |= {i: m for i, m in new.items() if m}
        return self.run()


@pytest.fixture
def project(here, capsys, pages):
    return Project(here, capsys)


def _result(here) -> dict:
    return json.loads(_ws(here).result_json.read_text(encoding="utf-8"))


def _before(here):
    return _ws(here).dir / "fix" / no_grades.BEFORE_FILE


def _counts_line(n: int, fixed: int, broke: int, same: int) -> str:
    return (f"On the {n} question{'' if n == 1 else 's'} kept aside: fixed {fixed}, "
            f"broke {broke}, same {same}.")


# What is compared, and the counts ---------------------------------------------------------

def test_new_answers_to_the_same_questions_count_fixed_broke_and_same(project):
    project.first(fails=set(range(12)), n=20)  # 12 Fails, 8 Passes: 10 kept aside
    kept_fails, kept_passes = project.kept("fail"), project.kept("pass")
    assert len(kept_fails) == 6 and len(kept_passes) == 4
    new = {i: "pass" for i in kept_fails[:3]} | {i: "fail" for i in kept_fails[3:]}
    new |= {i: "pass" for i in kept_passes}
    said = project.again(new)
    assert _counts_line(10, 3, 0, 7) in said
    assert LEANS_BETTER + " " + more(6, 6, 10) in said  # 3 and 0: not clear; 6 of 9 kept
    since = _result(project.here)["since"]
    assert (since["kept"], since["fixed"], since["broke"], since["same"]) == (10, 3, 0, 7)
    seen = _seen(_report(project.here))
    assert "Since your last answers" in seen
    assert ("Counted on the 10 questions kept aside, not the ones your fix was written from."
            in " ".join(seen.split()))


def test_the_earlier_mark_is_read_from_marks_jsonl_once_its_answer_left_the_pool(project):
    project.first(fails={0, 1, 2, 3, 4, 5}, n=12)
    ws = _ws(project.here)
    before = {_index(r["input"]): r["id"] for r in map(json.loads, ws.pool.read_text(
        encoding="utf-8").splitlines())}
    kept = project.kept()
    fixed = [i for i in kept if project.marks[i] == "fail"]
    broke = [i for i in kept if project.marks[i] == "pass"][:1]
    said = project.again({i: "pass" for i in fixed} | {i: "fail" for i in broke})
    pool = ws.pool.read_text(encoding="utf-8")
    marks_file = ws.marks.read_text(encoding="utf-8")
    for i in fixed + broke:
        assert before[i] not in pool  # a new results file was saved: the old answer is gone
        assert before[i] in marks_file  # its mark stays, read from there
    assert _counts_line(len(fixed + broke), len(fixed), len(broke), 0) in said


def test_only_the_questions_kept_aside_are_counted(project):
    project.first(fails={0, 1, 2, 3, 4, 5}, n=12)
    new = {i: "pass" for i in project.shown("fail")}  # every shown Fail fixed
    new |= {i: project.marks[i] for i in project.kept()}  # new answers, the same marks
    said = project.again(new)
    n = len(project.kept())
    assert _counts_line(n, 0, 0, n) in said
    assert SAME + " " + more(6, 3, 24) in said
    assert HELPED not in said


def test_a_change_to_shown_questions_only_says_it_cant_be_tested_yet(project):
    project.first(fails={0, 1, 2, 3, 4, 5}, n=12)
    shown_pass = project.shown("pass")[0]
    said = project.again({i: "pass" for i in project.shown("fail")} | {shown_pass: "fail"})
    assert NO_KEPT in said  # the kept-aside answers came back word for word
    assert "questions kept aside:" not in said and "Can't tell yet" not in said
    assert _result(project.here)["since"]["kept"] == 0
    assert no_grades.read_split(_ws(project.here)).tests == []  # no change tested
    html = _report(project.here)
    since = html.split('id="since-h"', 1)[1].split("</section>", 1)[0]
    assert NO_KEPT in unescape(since)
    assert 'class="cell"' not in since and "Counted on" not in since
    assert "Answers that broke" in html  # the shown questions still list
    assert f"Answer {shown_pass}, take 2." in html.split("Answers that broke", 1)[1]


def test_fewer_than_five_kept_aside_compared_is_never_clear(project):
    project.first(fails=set(range(8)), n=10)  # 8 Fails, 2 Passes: 4 Fails kept aside
    kept = project.kept("fail")
    assert len(kept) == 4
    said = project.again({i: "pass" for i in kept})
    assert _counts_line(4, 4, 0, 0) in said
    assert LEANS_BETTER + " " + more(6, 4, 13) in said


def test_a_big_enough_split_says_the_change_helped(project):
    project.first(fails=set(range(12)), n=20)
    said = project.again({i: "pass" for i in project.kept("fail")})  # 6 fixed, none broke
    assert _counts_line(6, 6, 0, 0) in said
    assert HELPED in said and "A clear answer needs" not in said


def test_the_same_answer_text_is_not_compared(project):
    project.first(fails={0, 1, 2, 3}, n=10)
    kept = project.kept()
    said = project.again({kept[0]: "pass" if project.marks[kept[0]] == "fail" else "fail"})
    assert _counts_line(1, *((1, 0) if project.marks[kept[0]] == "pass" else (0, 1)), 0) \
        in said
    assert _result(project.here)["since"]["kept"] == 1  # the others: the same text


def test_a_rerun_with_the_same_answers_compares_nothing(project):
    project.first(fails={0, 1, 2, 3}, n=10)
    said = project.again({})
    assert "questions kept aside" not in said and "Since your last answers" not in _seen(
        _report(project.here))
    assert "since" not in _result(project.here)


def test_a_question_asked_twice_in_the_file_is_left_out(project):
    project.first(fails={0, 1, 2, 3}, n=12)
    kept = project.kept()
    twice = kept[0]
    for i in kept:
        project.outs[i] = f"Answer {i}, again."
    with (project.here / "results.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["input", "output"])
        for i in sorted(project.outs):
            w.writerow([_q(i), project.outs[i]])
        w.writerow([_q(twice), "Another answer."])  # the same question, a second answer
    project.run()
    _mark(project.here, {i: project.marks[i] for i in project.outs})
    project.run()
    assert _result(project.here)["since"]["kept"] == len(kept) - 1


def test_a_question_with_spaces_added_is_the_same_question(project):
    project.first(fails={0, 1, 2, 3}, n=10)
    kept_fail = project.kept("fail")[0]
    project.outs[kept_fail] = "A new answer."
    _write(project.here, project.outs, asked={kept_fail: f"  What is question  {kept_fail}? \n"})
    project.run()
    _mark(project.here, {kept_fail: "pass"})
    said = project.run()
    assert _counts_line(1, 1, 0, 0) in said


def test_new_answers_not_marked_yet_show_no_counts(project):
    project.first(fails={0, 1, 2, 3}, n=12)
    kept = project.kept()
    said = project.again({kept[0]: None, kept[1]: None}, marked=False)  # 10 still marked
    assert WAIT in said
    assert "questions kept aside:" not in said
    assert _result(project.here)["since"] == {"waiting": True}
    seen = " ".join(_seen(_report(project.here)).split())
    assert WAIT in seen and "Fixed" not in seen


def test_counts_wait_for_every_changed_question_shown_ones_too(project):
    project.first(fails={0, 1, 2, 3}, n=12)
    kept, shown = project.kept(), project.shown()
    project.again({i: "pass" for i in kept} | {shown[0]: None})
    assert _result(project.here)["since"] == {"waiting": True}
    _mark(project.here, {shown[0]: "pass"})
    said = project.run()
    assert WAIT not in said and f"On the {len(kept)} questions kept aside" in said


def _resave(here) -> None:
    """results.csv saved again as it is: a newer modified time, the same answers."""
    path = here / "results.csv"
    st = path.stat()
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))


def test_an_answer_carried_over_from_the_last_results_is_not_compared_again(project):
    project.first(fails={0, 1, 2, 3, 4, 5}, n=12)
    q, shown_pass = project.kept("fail")[0], project.shown("pass")[0]
    project.again({q: "pass", shown_pass: "fail"})  # fixed and broke with these answers
    assert "Answers that broke" in _report(project.here)
    others = [i for i in project.kept() if i != q]
    project.again({i: project.marks[i] for i in others})  # the next results: q's answer as it was
    since = _result(project.here)["since"]
    assert (since["kept"], since["fixed"], since["broke"]) == (len(others), 0, 0)
    assert "Answers that broke" not in _report(project.here)


def test_a_question_with_spaces_added_and_the_same_answer_is_never_compared(project):
    project.first(fails={0, 1, 2, 3, 4, 5}, n=12)
    q = project.kept("fail")[0]
    project.again({q: "pass"})
    assert _result(project.here)["since"]["fixed"] == 1
    _write(project.here, project.outs, asked={q: f"What is  question {q}? "})
    project.run()
    unmarked = _result(project.here).get("since")
    _mark(project.here, {q: "pass"})
    project.run()
    assert unmarked is None and _result(project.here).get("since") is None


def test_the_same_answers_saved_again_keep_the_comparison_and_add_no_test(project):
    project.first(fails={0, 1, 2, 3, 4, 5}, n=12)
    project.again({i: "pass" for i in project.kept("fail")})
    since = _result(project.here)["since"]
    _resave(project.here)  # rewritten with the same answers: nothing new happened
    project.run()
    assert _result(project.here)["since"] == since
    assert len(no_grades.read_split(_ws(project.here)).tests) == 1


def test_an_answer_that_comes_back_to_an_earlier_text_is_compared(project):
    project.first(fails={0, 1, 2, 3, 4, 5}, n=12)
    q = project.kept("fail")[0]
    project.again({q: "pass"})  # Fail, then Pass
    project.outs[q] = f"First answer {q}."  # the first answer again: its Fail mark is kept
    _write(project.here, project.outs)
    said = project.run()
    assert _counts_line(1, 0, 1, 0) in said


# The result: the sign test, divided per change tested -------------------------------------

@pytest.mark.parametrize("fixed, broke, same, line", [
    (6, 0, 4, HELPED), (0, 6, 4, WORSE), (3, 0, 7, LEANS_BETTER), (2, 1, 7, LEANS_BETTER),
    (1, 1, 8, SAME), (0, 0, 10, SAME), (1, 2, 7, LEANS_WORSE)])
def test_the_sign_test_decides(fixed, broke, same, line):
    kind = no_grades.change_kind(fixed, broke, fixed + broke + same, test=1)
    assert no_grades.CHANGE[kind] == line
    clear = sign_p(fixed, broke) < SIGN_LEVEL
    assert no_grades.since_lines({"kept": fixed + broke + same, "fixed": fixed, "broke": broke,
                                  "same": same, "kind": kind, "clear": clear, "test": 1,
                                  "kept_fails": 4, "fails": 8, "marked": 20})[1] \
        == line + ("" if clear else " " + more(6, 4, 25))


def test_a_second_and_third_change_divide_the_level_then_ask_for_new_questions(project):
    project.first(fails=set(range(12)), n=20)
    kept = project.kept("fail")
    assert HELPED in project.again({i: "pass" for i in kept})  # 6 and 0, under 0.05
    said = project.again({i: "fail" for i in kept})  # 0 and 6: 0.031 is not under 0.05 / 2
    assert _counts_line(6, 0, 6, 0) in said
    assert LEANS_WORSE + " " + more(7, 0, 74) in said  # the 6 shown Fails of 20 failed
    assert NEW_SET not in said
    said = project.again({i: "pass" for i in kept})  # 6 and 0: not under 0.05 / 3
    assert LEANS_BETTER + " " + more(7, 6, 17) in said  # 12 of 20 failed, 6 kept aside
    assert NEW_SET in said
    tests = no_grades.read_split(_ws(project.here)).tests
    assert len(tests) == fix.MAX_RULES == 3
    again = project.run()  # the same answers: no new test
    assert len(no_grades.read_split(_ws(project.here)).tests) == 3 and NEW_SET in again


def test_after_three_changes_the_set_is_retired_and_new_questions_make_a_new_one(project):
    project.first(fails=set(range(12)), n=20)
    kept = project.kept("fail")
    for m in ("pass", "fail", "pass"):
        project.again({i: m for i in kept})
    said = project.again({i: "fail" for i in kept})  # a fourth change: not tested
    assert NEW_SET in said and "questions kept aside:" not in said
    split = no_grades.read_split(_ws(project.here))
    assert split.hidden == [] and split.fresh == {"want": fix.FRESH}
    text = (_ws(project.here).dir / "fix" / "failed-answers.md").read_text(encoding="utf-8")
    assert all(f"Answer {i}, take" in text for i in kept)  # every question is shown now
    # 9 new questions: not yet a set, and none of them shown
    for i in range(20, 29):
        project.outs[i] = f"First answer {i}."
    _write(project.here, project.outs)
    project.run()
    _mark(project.here, {i: "fail" for i in range(20, 29)})
    said = project.run()
    text = (_ws(project.here).dir / "fix" / "failed-answers.md").read_text(encoding="utf-8")
    assert all(f"First answer {i}." not in text for i in range(20, 29))
    assert NEW_SET in said
    project.outs[29] = "First answer 29."
    _write(project.here, project.outs)
    project.run()
    _mark(project.here, {29: "pass"})
    said = project.run()
    split = no_grades.read_split(_ws(project.here))
    assert split.set == 2 and split.fresh is None and split.tests == []
    page = _session(project.here)
    hidden = {_index(page.raw[i]["input"]) for i in split.hidden}
    assert hidden and hidden <= set(range(20, 30))
    assert len([i for i in hidden if i < 29]) == 5  # half of the 9 Fails, rounded up
    assert NEW_SET not in said


# The page ---------------------------------------------------------------------------------

def test_the_page_shows_the_three_cells_and_the_answers_that_broke(project):
    project.first(fails={0, 1, 2, 3, 4, 5}, n=12)
    kept_fail, kept_pass = project.kept("fail"), project.kept("pass")
    shown_pass = project.shown("pass")
    new = {i: "pass" for i in kept_fail} | {i: "fail" for i in kept_pass[:1]}
    new |= {shown_pass[0]: "fail"}
    project.again(new)
    for html in (_report(project.here), _live(project.here)):
        seen = " ".join(_seen(html).split())
        assert seen.index("Since your last answers") < seen.index("Answers you failed")
        assert "Fixed" in seen and "Broke" in seen and "Same" in seen
        assert '<span class="w-pass">3</span>' in html and '<span class="w-fail">1</span>' in html
        assert "Answers that broke" in seen
        broke = html.split("Answers that broke", 1)[1].split("</section>", 1)[0]
        assert f"Answer {shown_pass[0]}, take 2." in broke  # the new answer
        assert f"First answer {shown_pass[0]}." not in broke
        assert f"Answer {kept_pass[0]}, take 2." not in html  # kept aside: never shown
    r = _result(project.here)
    assert r["labels"] == {"correct": 12 - 6 + 3 - 2, "wrong": 6 - 3 + 2}  # the newest answers


def test_no_answer_that_broke_lists_none(project):
    project.first(fails={0, 1, 2, 3, 4, 5}, n=12)
    project.again({i: "pass" for i in project.kept("fail")})
    assert "Answers that broke" not in _report(project.here)


def test_the_headline_and_the_failed_answers_are_the_newest_answers(project):
    project.first(fails={0, 1, 2, 3, 4, 5}, n=12)
    shown_fail = project.shown("fail")
    said = project.again({i: "pass" for i in shown_fail[:2]})
    assert "You passed 8 of 12 answers." in said
    text = (_ws(project.here).dir / "fix" / "failed-answers.md").read_text(encoding="utf-8")
    assert all(f"First answer {i}." not in text for i in shown_fail[:2])
    assert f"First answer {shown_fail[2]}." in text
    assert "You passed 8 of 12 answers." in " ".join(_seen(_report(project.here)).split())


def test_the_terminal_says_counts_comparison_reasons_then_the_prompt(project):
    project.first(fails={0, 1, 2, 3, 4, 5}, n=12)
    page = _session(project.here)
    shown = set(no_grades.read_split(_ws(project.here)).seen)
    for item in page.items:
        if item["label"] == "fail" and item["id"] in shown:  # none on those kept aside
            page.update({"id": item["id"], "reasons": ["wrong_fact"]})
    said = project.again({i: "pass" for i in project.kept("fail")})
    at = [said.index(x) for x in ("You passed", "questions kept aside:", "Can't tell yet",
                                  "Your reasons:", "Paste this into your coding agent")]
    assert at == sorted(at)


# before.json ------------------------------------------------------------------------------

def test_before_json_is_private_holds_ids_and_hashes_only(project):
    project.first(fails={0, 1, 2, 3}, n=10)
    project.again({i: "pass" for i in project.kept()})
    path = _before(project.here)
    text = path.read_text(encoding="utf-8")
    assert "question" not in text.lower().replace('"questions"', "")
    assert "answer " not in text.lower() and "First" not in text
    if os.name != "nt":
        assert path.stat().st_mode & 0o077 == 0
        assert path.parent.stat().st_mode & 0o077 == 0


def test_a_link_in_place_of_before_json_is_refused(project, tmp_path_factory):
    if os.name == "nt":
        pytest.skip("links need admin rights on Windows")
    project.first(fails={0, 1, 2, 3}, n=10)
    target = tmp_path_factory.mktemp("elsewhere") / "before.json"
    target.write_text("{}", encoding="utf-8")
    path = _before(project.here)
    path.unlink()
    path.symlink_to(target)
    _write(project.here, {**project.outs, 0: "A new answer."})
    _, out, err = run(project.capsys, "--no-browser")  # nothing in .judgekeeper/ is a link
    assert "Traceback" not in out + err and "is a link" in out + err
    assert target.read_text(encoding="utf-8") == "{}"
    page = _session(project.here)
    item = page.items[0]
    with pytest.raises(OSError):  # marking stops too (a changed mark: a line to write)
        page.update({"id": item["id"], "label": "fail" if item["label"] == "pass" else "pass",
                     "seconds": 3})
    assert target.read_text(encoding="utf-8") == "{}"


def test_a_damaged_before_json_compares_nothing_and_says_no_error(project):
    project.first(fails={0, 1, 2, 3}, n=10)
    path = _before(project.here)
    path.write_text(path.read_text(encoding="utf-8").replace('"', "'", 2), encoding="utf-8")
    said = project.again({i: "pass" for i in project.kept()})
    assert "questions kept aside" not in said and "before.json" not in said


def test_a_project_without_before_json_compares_from_the_answers_it_has(project):
    project.first(fails={0, 1, 2, 3}, n=10)
    kept = project.kept()
    project.outs[kept[0]] = "A new answer."
    _write(project.here, project.outs)
    project.run()  # the earlier answer is gone from the pool now
    _before(project.here).unlink()  # as a project from before this version
    _mark(project.here, {kept[0]: "pass" if project.marks[kept[0]] == "fail" else "fail"})
    project.marks[kept[0]] = "pass" if project.marks[kept[0]] == "fail" else "fail"
    said = project.run()
    assert "kept aside:" not in said and "before.json" not in said
    flip = "pass" if project.marks[kept[0]] == "fail" else "fail"
    said = project.again({kept[0]: flip})  # compared with the answer marked just now
    assert _counts_line(1, *((1, 0) if flip == "pass" else (0, 1)), 0) in said


def test_the_last_answers_are_kept_before_new_ones_replace_them(project):
    project.first(fails={0, 1, 2, 3}, n=10)
    _before(project.here).unlink()  # made again from the answers there when new ones come
    fails = project.kept("fail")
    said = project.again({i: "pass" for i in fails})
    assert _counts_line(len(fails), len(fails), 0, 0) in said


def test_an_llm_as_a_judge_project_gets_no_comparison(here, capsys, pages):
    from tests.test_front import promptfoo_project, split

    promptfoo_project(here, split(20, 16))
    run(capsys)
    assert not (_ws(here).dir / "fix" / no_grades.BEFORE_FILE).exists()
