"""What a run says after new answers come: how many are new to mark, and how many are the same
as before and keep their mark; `mark` says when new answers are waiting; the prompt for a
coding agent says "with my reasons" only when there are reasons."""

from __future__ import annotations

from judgekeeper import no_grades, start_label
from tests.test_fixed_and_broke import Project, _mark, _write, here, project  # noqa: F401
from tests.test_front import flat, run


def test_one_answer_the_same_keeps_its_mark_and_is_not_new(project):  # noqa: F811
    project.first(fails={0, 1, 2}, n=12)
    for i in range(1, 12):  # every answer new but one
        project.outs[i] = f"Answer {i}, take 2."
    _write(project.here, project.outs)
    said = project.run()
    assert ("Found 11 new answers since your last results. Mark them to see what changed. "
            "1 answer is the same as before and keeps its mark.") in said, said


def test_an_answer_back_to_an_older_text_keeps_its_mark_and_is_not_new(project):  # noqa: F811
    project.first(fails={0, 1, 2}, n=12)
    project.again({i: "pass" for i in range(12)})  # every answer new, all marked
    for i in range(12):
        project.outs[i] = f"Answer {i}, take 3."
    project.outs[0] = "First answer 0."  # word for word the first answer: marked then
    _write(project.here, project.outs)
    said = project.run()
    assert ("Found 11 new answers since your last results. Mark them to see what changed. "
            "1 answer is the same as before and keeps its mark.") in said, said


def test_mark_them_comes_right_after_the_new_answers_it_points_at(project):  # noqa: F811
    project.first(fails={0, 1, 2}, n=12)
    for i in range(3):
        project.outs[i] = f"Answer {i}, take 2."
    _write(project.here, project.outs)
    said = project.run()
    at = [said.find(s) for s in ("Found 3 new answers since your last results.",
                                 "Mark them to see what changed.",
                                 "9 answers are the same as before and keep their marks.")]
    assert -1 not in at and at == sorted(at), said


def test_mark_says_new_answers_are_waiting(project):  # noqa: F811
    project.first(fails={0, 1, 2}, n=12)
    for i in range(3):
        project.outs[i] = f"Answer {i}, take 2."
    _write(project.here, project.outs)
    project.run()
    code, out, err = run(project.capsys, "mark", "--no-browser")
    said = flat(out)
    assert code == 0, out + err
    assert "3 new answers are waiting to be marked." in said, said


def test_the_prompt_says_with_my_reasons_only_with_reasons(project):  # noqa: F811
    said = project.first(fails={0, 1, 2, 3}, n=12)
    assert "I marked Fail, with my reasons." not in said
    assert "It lists answers my AI gave that I marked Fail.\n" in no_grades.fix_prompt(
        start_label.Workspace(project.here)) + "\n"
    ws = start_label.Workspace(project.here)
    page = start_label.StartSession(ws)
    shown = [i for i in page.items if i["label"] == "fail"
             and i["id"] not in no_grades.kept_aside(ws)]
    page.update({"id": shown[0]["id"], "reasons": ["wrong_fact"]})
    said = project.run()
    assert "It lists answers my AI gave that I marked Fail, with my reasons." in said
