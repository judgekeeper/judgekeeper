# ruff: noqa: F811 - the fixtures come from test_fixed_and_broke
"""A clear answer must be possible: the question prompt asks for about 40 questions, "Can't
tell yet" says what a clear answer needs, the first lines say which path judgekeeper takes,
kept-aside answers never leak, and a changed answer shows no old mark."""
from __future__ import annotations

import csv
import json
import math

from judgekeeper import front, no_grades, targets
from judgekeeper.start_label import Workspace
from tests.start_projects import promptfoo_project, split, table_project
from tests.test_answers_without_grades import _live, _report, _seen, _session, write_answers
from tests.test_fixed_and_broke import _mark, _write, here, project  # noqa: F401 (fixtures)
from tests.test_front import flat, run

NO_GRADES_LINE = ("results.csv has no LLM-as-a-judge grades, so judgekeeper checks your AI's "
                  "answers: you mark each one Pass or Fail.")
NO_GRADES_SWITCH = ("Have an LLM-as-a-judge? Save its Pass or Fail in a verdict column, or run "
                    "it with promptfoo, DeepEval, Inspect AI or MLflow.")
GRADES_LINE = ("{file} has LLM-as-a-judge grades, so judgekeeper checks your LLM-as-a-judge "
               "against your marks.")
TABLE_SWITCH = ("To check your AI's answers instead, use a copy of the file without the verdict "
                "column.")
TOOL_SWITCH = ("To check your AI's answers instead, save them in a CSV file with input and "
               "output columns and no verdict column.")
OLD_MORE = "Mark more questions for a clearer answer."
NEED = ("A clear answer needs at least {need} kept-aside questions to go from Fail to Pass, "
        "with none breaking. About 2 in 3 failed questions get fixed, so that needs about "
        "{target} kept-aside questions that failed before your change; you had {kept}.")
ADD = NEED + " Add about {extra} more questions."
HARDER = ("A clear answer needs at least 7 kept-aside questions to go from Fail to Pass, with "
          "none breaking. About 2 in 3 failed questions get fixed, so that needs about 11 "
          "kept-aside questions that failed before your change; you had 0. Add harder questions, ones your AI may get wrong, and "
          "mark their answers.")
ENOUGH = ("A clear answer needs at least {need} of the {kept} kept-aside questions that failed "
          "before your change to pass, with none breaking.")


# 2. What a clear answer needs ---------------------------------------------------------------

def test_need_comes_from_the_sign_test_for_each_change():
    assert [no_grades.clear_need(t) for t in (1, 2, 3)] == [6, 7, 7]
    assert [no_grades.clear_target(no_grades.clear_need(t)) for t in (1, 2, 3)] == [9, 11, 11]
    for t in (1, 2, 3):
        k = no_grades.clear_need(t)
        assert targets.sign_p(k, 0) < targets.SIGN_LEVEL / t <= targets.sign_p(k - 1, 0)


def test_need_follows_the_level_not_a_constant(monkeypatch):
    monkeypatch.setattr(targets, "SIGN_LEVEL", 0.1)
    assert no_grades.clear_need(1) == 5  # 0.0625 < 0.1


def _c(kind: str = "leans better", **kw) -> dict:
    return {"kept": 10, "fixed": 2, "broke": 0, "same": 8, "kind": kind,
            "clear": kind in ("helped", "worse"), "test": 1, **kw}


def test_too_few_kept_aside_fails_says_how_many_questions_to_add():
    c = _c(kept_fails=4, fails=8, marked=20)  # f = 0.4
    assert no_grades.clear_line(c) == ADD.format(target=9, need=6, kept=4, extra=25)
    assert no_grades.result_line(c) == (no_grades.CHANGE["leans better"] + " "
                                        + ADD.format(target=9, need=6, kept=4, extra=25))


def test_the_extra_is_rounded_up_and_counts_the_round():
    c = _c(kept_fails=0, fails=6, marked=20, test=2)  # target 11, f 0.3: 73.3
    assert no_grades.clear_line(c) == ADD.format(target=11, need=7, kept=0, extra=74)
    assert math.ceil(2 * 11 / 0.3) == 74


def test_enough_kept_aside_fails_says_how_many_must_pass():
    c = _c(kept_fails=9, fails=18, marked=40)
    assert no_grades.clear_line(c) == ENOUGH.format(need=6, kept=9)
    c = _c(kept_fails=11, fails=22, marked=40, test=3)
    assert no_grades.clear_line(c) == ENOUGH.format(need=7, kept=11)


def test_nothing_failed_before_asks_for_harder_questions():
    c = _c("same", kept_fails=0, fails=0, marked=30, test=2)  # a second change, after 30/30
    assert no_grades.clear_line(c) == HARDER
    assert no_grades.result_line(c) == no_grades.CHANGE["same"] + " " + HARDER


def test_every_cant_tell_yet_says_what_a_clear_answer_needs():
    for kind in ("leans better", "leans worse", "same"):
        for fails, kept in ((0, 0), (8, 0), (8, 4)):
            line = no_grades.result_line(_c(kind, kept_fails=kept, fails=fails, marked=20))
            assert line.startswith(no_grades.CHANGE[kind] + " A clear answer needs at least")


def test_a_clear_result_says_no_more():
    for kind in ("helped", "worse"):
        c = _c(kind, kept_fails=4, fails=8, marked=20)
        assert no_grades.result_line(c) == no_grades.CHANGE[kind]


def test_the_old_line_is_gone():
    assert not hasattr(no_grades, "MARK_MORE")


def test_the_terminal_and_page_say_it_with_the_numbers_of_the_project(project):
    project.first(fails=set(range(8)), n=20)  # 8 Fails of 20: 4 kept aside
    kept = project.kept("fail")
    assert len(kept) == 4
    said = project.again({i: "pass" for i in kept[:2]})  # 2 fixed, none broke
    line = ADD.format(target=9, need=6, kept=4, extra=25)
    assert no_grades.CHANGE["leans better"] + " " + line in said
    assert OLD_MORE not in said
    for html in (_report(project.here), _live(project.here)):
        seen = " ".join(_seen(html).split()).replace("&#x27;", "'").replace("&#39;", "'")
        assert line in seen and OLD_MORE not in seen


def test_kept_aside_fails_count_the_ones_whose_answer_did_not_change(project):
    project.first(fails=set(range(8)), n=20)
    kept = project.kept("fail")
    project.again({kept[0]: "pass"})  # only one kept-aside question answered again
    c = json.loads(project.here.joinpath(".judgekeeper", "result.json").read_text(
        encoding="utf-8"))["since"]
    assert (c["kept_fails"], c["fails"], c["marked"]) == (4, 8, 20)


def test_a_clear_change_says_no_more(project):
    project.first(fails=set(range(12)), n=20)
    said = project.again({i: "pass" for i in project.kept("fail")})  # 6 fixed
    assert no_grades.CHANGE["helped"] in said and "A clear answer needs" not in said


def test_new_questions_are_kept_aside_about_half_of_their_fails(project):
    """The share `extra` is worked out with: half of the new questions' Fails kept aside."""
    project.first(fails=set(range(8)), n=20)
    new = range(20, 45)  # 25 new questions, 10 of them Fails (f 0.4)
    marks = {i: "fail" if i % 5 in (0, 2) else "pass" for i in new}
    for i in new:
        project.outs[i] = f"First answer {i}."
    _write(project.here, project.outs)
    project.run()
    _mark(project.here, marks)
    project.marks |= marks
    project.run()
    kept_new = [i for i in project.kept("fail") if i >= 20]
    assert len(kept_new) == 5  # 10 new Fails: 5 kept aside
    assert len(project.kept("fail")) == 9  # the target for a first change


# 1. The question prompt ------------------------------------------------------------------------

def test_the_question_prompt_asks_for_about_40_questions_a_table_and_a_yes():
    lines = front.QUESTIONS_PROMPT.format(program="judgekeeper").splitlines()
    assert lines == [
        ("Read this project and list what its AI is meant to do (its prompt and the tasks it "
         "handles)."),
        ("Write about 40 test questions the way its real users would ask them: cover every task, "
         "and make about half of them hard (missing details, out of scope, against the AI's own "
         "rules, a wrong premise, or more than one step). No near-duplicates."),
        ("Show me the questions as a numbered table (question, the task it tests, normal or "
         "hard) and wait for my yes. I may edit or drop any."),
        ("Then run the AI on each question and save the questions and answers in results.csv, "
         "with two columns: input (the question) and output (the answer). Do not grade the "
         "answers. Then run judgekeeper.")]


# 3. Which path, and how to switch ------------------------------------------------------------

def _after_block(out: str) -> list[str]:
    """The paragraphs after the Find block's last row, each as one line."""
    rest = out.split("judgekeeper has read from your file:", 1)[1]
    paras = [" ".join(p.split()) for p in rest.split("\n\n")]
    return paras[1:]


def test_a_file_with_no_grades_says_so_once_after_the_find_block(here, capsys):
    write_answers(here, 12)
    code, out, err = run(capsys, "--no-browser")
    assert code == 0, out + err
    assert _after_block(out)[:1] == [NO_GRADES_LINE + " " + NO_GRADES_SWITCH]
    assert flat(out).count(NO_GRADES_LINE) == 1


def test_a_later_run_with_no_grades_says_it_first_under_the_step(here, capsys):
    write_answers(here, 12)
    run(capsys, "--no-browser")
    for argv in (["--no-browser"], ["mark", "--no-browser"]):
        code, out, err = run(capsys, *argv)
        assert code == 0, out + err
        paras = [" ".join(p.split()) for p in out.split("\n\n")]
        step = next(n for n, p in enumerate(paras) if p.startswith("Step "))
        assert paras[step + 1] == NO_GRADES_LINE + " " + NO_GRADES_SWITCH, out
        assert flat(out).count(NO_GRADES_LINE) == 1


def test_a_graded_table_says_so_once_after_the_find_block(here, capsys):
    table_project(here, split(15, 15))
    code, out, err = run(capsys)
    assert code == 0, out + err
    line = GRADES_LINE.format(file="results.csv")
    assert _after_block(out)[:1] == [line + " " + TABLE_SWITCH]
    assert flat(out).count(line) == 1


def test_a_graded_eval_tool_file_gets_the_csv_switch_line(here, capsys):
    promptfoo_project(here, split(20, 16))
    code, out, err = run(capsys)
    assert code == 0, out + err
    line = GRADES_LINE.format(file="results.json")
    assert _after_block(out)[:1] == [line + " " + TOOL_SWITCH]
    assert TABLE_SWITCH not in flat(out)


def test_a_later_graded_run_says_it_first_under_the_step(here, capsys):
    table_project(here, split(15, 15))
    run(capsys)
    code, out, err = run(capsys, "--no-browser")
    assert code == 0, out + err
    paras = [" ".join(p.split()) for p in out.split("\n\n")]
    step = next(n for n, p in enumerate(paras) if p.startswith("Step "))
    assert paras[step + 1] == GRADES_LINE.format(file="results.csv") + " " + TABLE_SWITCH, out


# 4. Kept-aside answers never leak -------------------------------------------------------------

def test_no_kept_aside_question_or_answer_reaches_the_person(here, capsys):
    words = [f"zq{chr(97 + i)}marker" for i in range(20)]  # one unique word per row
    rows = [{"input": f"Question {i} {words[i]}ask?", "output": f"Answer {i} {words[i]}say."}
            for i in range(20)]
    with (here / "results.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["input", "output"])
        w.writeheader()
        w.writerows(rows)
    run(capsys, "--no-browser")
    page = _session(here)
    for n, item in enumerate(page.items):
        page.update({"id": item["id"], "label": "fail" if n % 2 else "pass", "seconds": 3})
    out = run(capsys, "--no-browser")[1]
    split_ = no_grades.read_split(Workspace(here))
    kept = [w for w in words if any(w in page.raw[i]["input"] for i in split_.hidden)]
    shown = [w for w in words if any(w in page.raw[i]["input"] for i in split_.seen)]
    assert kept and shown
    fix_out = run(capsys, "fix")[1]
    failed = (here / ".judgekeeper" / "fix" / "failed-answers.md").read_text(encoding="utf-8")
    places = {"terminal": out, "fix": fix_out, "failed-answers.md": failed,
              "report": _report(here), "live": _live(here)}
    for name, text in places.items():
        leaked = [w for w in kept if w in text]
        assert not leaked, (name, leaked)
    assert any(w in failed for w in shown)  # the shown Fails are there


# 5. A changed answer shows no old mark ---------------------------------------------------------

def test_a_new_answer_comes_to_the_page_with_no_mark(project, tmp_path_factory, monkeypatch):
    project.first(fails={0, 1, 2, 3}, n=10)
    project.again({i: None for i in range(10)}, marked=False)  # every answer new, unmarked
    new = [x for x in _session(project.here).state()["items"] if "take 2" in json.dumps(x)]
    assert len(new) == 10
    for item in new:
        assert not item["label"] and not item.get("note")
        text = json.dumps(item)
        assert '"pass"' not in text and '"fail"' not in text
        assert "First answer" not in text  # nothing of the answer before it
    fresh = tmp_path_factory.mktemp("fresh")  # a first run's page: nothing marked before
    monkeypatch.chdir(fresh)
    write_answers(fresh, 12)
    run(project.capsys, "--no-browser")
    unmarked = {k for x in _session(fresh).state()["items"] for k in x}
    assert {k for x in new for k in x} <= unmarked
