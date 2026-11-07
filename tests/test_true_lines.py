"""Lines that have to stay true on the less common paths."""

from __future__ import annotations

from judgekeeper import report_page, start_label


def test_a_one_grade_judge_with_every_answer_marked_the_same_needs_a_new_answer_the_other_way():
    lines = start_label.all_marked_lines({"correct": 40, "wrong": 0}, "judgekeeper mark",
                                         {"pass": 40, "fail": 0})
    assert lines[0] == ("You've marked every answer: 40 Pass, 0 Fail. Your result comes once you "
                        "mark a new answer Fail.")
    lines = start_label.all_marked_lines({"correct": 0, "wrong": 40}, "judgekeeper mark",
                                         {"pass": 0, "fail": 40})
    assert lines[0] == ("You've marked every answer: 0 Pass, 40 Fail. Your result comes once you "
                        "mark a new answer Pass.")


def test_a_judge_with_both_grades_still_needs_marks_of_each_kind():
    lines = start_label.all_marked_lines({"correct": 30, "wrong": 10}, "judgekeeper mark",
                                         {"pass": 25, "fail": 15})
    assert lines[0] == "You've marked every answer: 30 Pass, 10 Fail. A result needs at least 15 of each."
    assert start_label.all_marked_lines({"correct": 30, "wrong": 10}, "judgekeeper mark") == lines


def test_more_details_escapes_what_a_saved_result_holds():
    r = {"kappa": 0.5, "kappa_interval": [0.5, 0.5], "left": 3, "counted_left": 0,
         "batches": {"waiting": 2, "counted": [1], "of": 2, "answers": "<meta http-equiv=refresh>"}}
    page = report_page._details(r)
    assert "<meta" not in page and "&lt;meta" in page
