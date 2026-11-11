"""Answers with no grades: every answer to one question on the same side of the split, no
reason on an answer kept aside, failed-answers.md written with each mark, the same path on the
page as in the terminal, new answers found after a change, and the Next lines of Step 1, `fix`
and `check`."""

from __future__ import annotations

import csv
import json
import threading

import pytest

from judgekeeper import fix, no_grades, page, reasons, start, start_label
from judgekeeper.textio import is_windows
from tests.test_answers_without_grades import _live, _report, _seen, _session, write_answers
from tests.test_front import assert_one_next_at_the_end, flat, run
from tests.test_label_server import Client

SHOWN_PATH = (".judgekeeper\\fix\\failed-answers.md" if is_windows()  # as the terminal names it
              else ".judgekeeper/fix/failed-answers.md")
FOUND_NEW = ("Found {n} since your last results. Mark them to see what changed. {same} answers "
             "are the same as before and keep their marks.")
QUESTION_NEXT = "Next: paste the prompt above into your coding agent, then run `judgekeeper` again."
FIX_NEXT = ("Next: paste the prompt above into your coding agent. After it changes your AI's "
            "prompt, save your AI's new answers and run `judgekeeper` again.")
ONLY_FAILED = "Reasons are only for answers you failed."


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _ws(here) -> start_label.Workspace:
    return start_label.Workspace(here)


def _write(here, rows: list[tuple[str, str]]) -> None:
    with (here / "results.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["input", "output"])
        w.writeheader()
        w.writerows({"input": q, "output": a} for q, a in rows)


def _go(capsys) -> str:
    code, out, err = run(capsys, "--no-browser")
    assert code == 0, out + err
    return out


def _mark_by_answer(here) -> start_label.StartSession:
    """Every answer not marked yet: Fail when its text starts with "Bad", else Pass."""
    page = _session(here)
    for item in page.items:
        if not item["label"]:
            bad = page.raw[item["id"]]["output"].startswith("Bad")
            page.update({"id": item["id"], "label": "fail" if bad else "pass", "seconds": 3})
    return page


def _sides(here) -> dict[str, set[str]]:
    """Each question's text: the sides its answers are on."""
    split = no_grades.read_split(_ws(here))
    page = _session(here)
    out: dict[str, set[str]] = {}
    for ids, side in ((split.seen, "shown"), (split.hidden, "kept")):
        for i in ids:
            out.setdefault(page.raw[i]["input"], set()).add(side)
    return out


def _resave_split(here, split: no_grades.AnswersSplit) -> None:
    d = split.to_json()
    path = _ws(here).dir / "fix" / no_grades.SPLIT_FILE
    path.write_text(json.dumps({**d, "sha256": fix._sum(d)}, indent=2) + "\n", encoding="utf-8")


def _marked(here, capsys, marks: list[str], n: int = 12) -> start_label.StartSession:
    write_answers(here, n)
    _go(capsys)
    page = _session(here)
    for item, m in zip(page.items, marks, strict=False):
        page.update({"id": item["id"], "label": m, "seconds": 3})
    _go(capsys)
    return _session(here)


# 1. One question, one side ---------------------------------------------------------------------

def test_two_answers_to_one_question_land_on_the_same_side(here, capsys):
    _write(here, [x for i in range(12) for x in ((f"Question {i}?", f"Good answer {i}."),
                                                 (f"Question {i}?", f"Bad answer {i}."))])
    _go(capsys)
    _mark_by_answer(here)
    _go(capsys)
    sides = _sides(here)
    assert len(sides) == 12
    assert all(len(s) == 1 for s in sides.values()), sides
    assert {next(iter(s)) for s in sides.values()} == {"shown", "kept"}  # still split
    assert no_grades.BOTH not in no_grades.read_split(_ws(here)).questions.values()


def test_later_answers_follow_their_question_and_new_questions_stay_whole(here, capsys):
    first = [(f"Question {i}?", f"{'Bad' if i % 2 else 'Good'} answer {i}.") for i in range(10)]
    _write(here, first)
    _go(capsys)
    _mark_by_answer(here)
    _go(capsys)
    before = _sides(here)
    later = [(f"Question {i}?", f"{'Good' if i % 2 else 'Bad'} answer {i}, again.")
             for i in range(10)]
    new = [x for i in range(10, 18) for x in ((f"Question {i}?", f"Good answer {i}."),
                                              (f"Question {i}?", f"Bad answer {i}."))]
    _write(here, first + later + new)
    _go(capsys)
    _mark_by_answer(here)
    _go(capsys)
    sides = _sides(here)
    assert all(len(s) == 1 for s in sides.values()), sides
    for q, side in before.items():
        assert sides[q] == side, q


def test_a_question_on_both_sides_in_an_older_file_is_shown_whole(here, capsys):
    rows = [(f"Question {i}?", f"{'Bad' if i % 2 else 'Good'} answer {i}.") for i in range(12)]
    _write(here, rows)
    _go(capsys)
    _mark_by_answer(here)
    _go(capsys)
    _write(here, [*rows, ("Question 0?", "Bad answer 0, again.")])
    _go(capsys)
    page = _mark_by_answer(here)
    _go(capsys)
    split = no_grades.read_split(_ws(here))
    ids = [i for i in page.by_id if page.raw[i]["input"] == "Question 0?"]
    later = next(i for i in ids if "again" in page.raw[i]["output"])
    key = no_grades.question_key("Question 0?")
    if later in split.hidden:  # as an older judgekeeper split it: one answer on each side
        split.hidden.remove(later)
        split.seen.append(later)
    else:
        split.seen.remove(later)
        split.hidden.append(later)
    split.questions[key] = no_grades.BOTH
    _resave_split(here, split)
    _go(capsys)
    split = no_grades.read_split(_ws(here))
    assert set(ids) <= set(split.seen) and not set(ids) & set(split.hidden)
    assert split.questions[key] == no_grades.SHOWN
    assert no_grades.BOTH not in split.questions.values()


def test_a_questions_only_fail_is_never_kept_aside_behind_its_pass(here, capsys, monkeypatch):
    from judgekeeper.table import derive_id

    def answer_id(text: str) -> str:
        return derive_id({"input": "Question 10?", "output": text})

    good, bad = next((f"Good answer {k}.", f"Bad answer {k}.") for k in range(100)
                     if answer_id(f"Good answer {k}.") < answer_id(f"Bad answer {k}."))
    rows = [(f"Question {i}?", f"Good answer {i}.") for i in range(10)]
    _write(here, [*rows, ("Question 10?", good), ("Question 10?", bad)])  # the Pass first by id
    _go(capsys)
    page = _mark_by_answer(here)
    ws = _ws(here)
    fail = next(i for i in page.by_id if page.by_id[i]["label"] == "fail")
    path = ws.dir / "fix" / no_grades.SPLIT_FILE
    for seed in range(80):  # one Fail in all: never kept aside, whatever the seed
        path.unlink(missing_ok=True)
        monkeypatch.setattr(no_grades.secrets, "randbelow", lambda n, s=seed: s)
        split = no_grades.update_split(ws, page)
        assert fail in split.seen, seed


# 2. No reasons on answers kept aside ----------------------------------------------------------

@pytest.fixture
def served(tmp_path):
    write_answers(tmp_path, 14)
    ws = start_label.prepare(start.find_judge(tmp_path, answers=True), say=lambda line: None)
    server = page.page_server(ws, 0)
    thread = threading.Thread(target=server.serve, daemon=True)
    thread.start()
    yield ws, Client(server)
    server.stop()
    thread.join(timeout=5)


def test_a_reason_on_an_answer_kept_aside_is_refused_and_makes_no_button(served):
    ws, client = served
    ids = [i["id"] for i in client.state()["items"]]
    for item, label in zip(ids, ["pass"] * 4 + ["fail"] * 6, strict=False):
        assert client.label(id=item, label=label, seconds=3)[0] == 200
    assert client.request("GET", "/result")[0].status == 200  # the result and the split
    split = no_grades.read_split(ws)
    kept = next(i for i in split.hidden if i in ids[4:10])
    status, body = client.label(id=kept, reasons=[], note="Kept words here")
    assert status == 400 and body["error"] == reasons.NOT_LISTED
    status, body = client.label(id=kept, reasons=[no_grades.offered()[0]])
    assert status == 400 and body["error"] == reasons.NOT_LISTED
    assert reasons.own_chips(ws) == []
    _, html = client.request("GET", "/result")
    assert "Kept words here" not in html.decode("utf-8")
    shown = next(i for i in split.seen if i in ids[4:10])  # an answer shown still takes one
    status, _ = client.label(id=shown, reasons=[], note="Shown words here")
    assert status == 200
    _, html = client.request("GET", "/result")
    assert "Shown words here" in html.decode("utf-8")


def test_a_button_made_on_an_answer_kept_aside_before_is_never_shown(here, capsys):
    page = _marked(here, capsys, ["pass"] * 4 + ["fail"] * 6)
    ws = _ws(here)
    kept = next(i for i in no_grades.read_split(ws).hidden if page.by_id[i]["label"] == "fail")
    reasons.sync_own(ws, kept, "Old kept words", set())  # as an older judgekeeper made it
    no_grades.redraw(ws)
    for html in (_live(here), _report(here)):
        assert "Old kept words" not in html


@pytest.mark.parametrize("made_from", [["a", "b"], {"id": "x"}, 7, None])
def test_a_button_whose_answer_is_not_a_string_is_kept_and_breaks_nothing(here, capsys,
                                                                          made_from):
    _marked(here, capsys, ["pass"] * 4 + ["fail"] * 6)
    ws = _ws(here)
    path = ws.dir / "reasons.json"
    data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    data["own"] = [{"id": "own-1", "text": "Odd words", "from": made_from}]  # edited by hand
    path.write_text(json.dumps(data), encoding="utf-8")
    code, out, err = run(capsys, "--no-browser")
    assert code == 0, out + err
    assert "Odd words" in _live(here)


# 3. failed-answers.md after each mark ------------------------------------------------------------

def _failed_count(here) -> int:
    text = (_ws(here).dir / "fix" / no_grades.FAILED_FILE).read_text(encoding="utf-8")
    return int(text.split("You failed ", 1)[1].split(" ", 1)[0])


def test_a_mark_changed_on_the_page_rewrites_failed_answers_at_once(here, capsys):
    page = _marked(here, capsys, ["pass"] * 6 + ["fail"] * 4)
    split = no_grades.read_split(_ws(here))
    was = _failed_count(here)
    shown_pass = next(i for i in split.seen if page.by_id[i]["label"] == "pass")
    page.update({"id": shown_pass, "label": "fail", "seconds": 3})
    assert _failed_count(here) == was + 1


def test_a_new_fail_on_the_page_is_split_before_it_is_written(here, capsys):
    page = _marked(here, capsys, ["pass"] * 6 + ["fail"] * 4)
    left = [i["id"] for i in page.items if not i["label"]]
    for i in left:
        page.update({"id": i, "label": "fail", "seconds": 3})
    split = no_grades.read_split(_ws(here))
    text = (_ws(here).dir / "fix" / no_grades.FAILED_FILE).read_text(encoding="utf-8")
    for i in left:
        assert i in split.seen or i in split.hidden
        said = page.raw[i]["output"] in text
        assert said == (i in split.seen), i


# 4, 5, 9. The Next lines and the wrapped line ----------------------------------------------------

def test_step_1_after_the_question_prompt_says_to_paste_it(here, capsys):
    code, out, _ = run(capsys)
    assert code == 3
    assert "No answers yet? Paste this into your coding agent" in flat(out)
    assert assert_one_next_at_the_end(out) == QUESTION_NEXT


def test_step_1_without_the_prompt_keeps_its_next_line(here, capsys):
    (here / "requirements.txt").write_text("deepeval\n", encoding="utf-8")
    code, out, _ = run(capsys)
    assert code == 3
    assert assert_one_next_at_the_end(out) == (
        "Next: run your eval once from this folder, then run `judgekeeper` again.")


def test_fix_with_failed_answers_says_to_paste_the_prompt(here, capsys):
    _marked(here, capsys, ["pass"] * 6 + ["fail"] * 4)
    code, out, err = run(capsys, "fix")
    assert code == 3, out + err
    assert assert_one_next_at_the_end(out) == FIX_NEXT


def test_fix_without_failed_answers_keeps_its_next_line(here, capsys):
    _marked(here, capsys, ["pass"] * 10)
    code, out, _ = run(capsys, "fix")
    assert code == 3
    assert assert_one_next_at_the_end(out).startswith(
        "Next: add your LLM-as-a-judge's grades to results.csv")


def test_checks_no_judge_line_wraps_as_fixs_does(here, capsys):
    _marked(here, capsys, ["pass"] * 6 + ["fail"] * 4)
    said = "Your answers have no grades, so there is no LLM-as-a-judge to re-check."
    code, out, _ = run(capsys, "check")
    assert code == 3
    assert said in flat(out)
    assert said not in out.splitlines()  # wrapped, never one long line
    assert max(len(line) for line in out.splitlines()) <= 72


def test_a_reason_on_a_pass_answer_says_reasons_are_for_failed_ones(here, capsys):
    page = _marked(here, capsys, ["pass"] * 6 + ["fail"] * 4)
    split = no_grades.read_split(_ws(here))
    shown_pass = next(i for i in split.seen if page.by_id[i]["label"] == "pass")
    with pytest.raises(ValueError, match=ONLY_FAILED):
        page.update({"id": shown_pass, "note": "Why not"})


# 6. The same path on the page as in the terminal ---------------------------------------------------

def test_the_page_names_failed_answers_from_the_project_folder(here, capsys, tmp_path_factory,
                                                                 monkeypatch):
    _marked(here, capsys, ["pass"] * 6 + ["fail"] * 4)
    elsewhere = tmp_path_factory.mktemp("my folder")
    monkeypatch.chdir(elsewhere)  # the page served from a run somewhere else
    no_grades.redraw(_ws(here))
    for html in (_live(here), _report(here)):
        seen = " ".join(_seen(html).split())
        assert f"Your failed answers are saved in {SHOWN_PATH} ." in seen
        box = html.split('<div class="cmd prompt">', 1)[1].split("</div>", 1)[0]
        assert f"Read {SHOWN_PATH}. It lists" in box
        assert str(here) not in html and "~/" not in html


# 7. New answers after a change ------------------------------------------------------------------

def test_new_answers_since_the_last_results_are_named_once(here, capsys):
    rows = [(f"Question {i}?", f"{'Bad' if i % 2 else 'Good'} answer {i}.") for i in range(12)]
    _write(here, rows)
    assert "since your last results" not in _go(capsys)  # the first answers: nothing before
    _mark_by_answer(here)
    _go(capsys)
    _write(here, [(q, f"New {a}") for q, a in rows[:3]] + rows[3:])
    assert FOUND_NEW.format(n="3 new answers", same=9) in flat(_go(capsys))
    assert "since your last results" not in _go(capsys)  # said once, on the run that found them
    _write(here, [(q, f"Newer {a}") for q, a in rows[:1]]
           + [(q, f"New {a}") for q, a in rows[1:3]] + rows[3:])
    assert FOUND_NEW.format(n="1 new answer", same=9).replace("Mark them", "Mark it") \
        in flat(_go(capsys))


def test_the_same_answers_saved_again_find_nothing_new(here, capsys):
    rows = [(f"Question {i}?", f"{'Bad' if i % 2 else 'Good'} answer {i}.") for i in range(12)]
    _write(here, rows)
    _go(capsys)
    _mark_by_answer(here)
    _go(capsys)
    _write(here, rows)
    assert "since your last results" not in _go(capsys)


def test_the_pop_up_can_show_once_more_for_new_answers(here, capsys):
    rows = [(f"Question {i}?", f"{'Bad' if i % 2 else 'Good'} answer {i}.") for i in range(12)]
    _write(here, rows)
    _go(capsys)
    page = _mark_by_answer(here)
    assert page.pop_up({"ready": True}) is True  # the first result
    assert page.pop_up({"ready": True}) is False
    _go(capsys)
    _write(here, rows)  # the same answers: no new pop-up
    _go(capsys)
    assert _session(here).pop_up({"ready": True}) is False
    _write(here, [(q, f"New {a}") for q, a in rows])
    _go(capsys)
    page = _session(here)
    assert page.pop_up({"ready": True}) is True  # once for the new answers
    assert page.pop_up({"ready": True}) is False
    assert _session(here).pop_up({"ready": True}) is False


def test_an_older_ready_seen_file_brings_no_pop_up_again(here, capsys):
    rows = [(f"Question {i}?", f"{'Bad' if i % 2 else 'Good'} answer {i}.") for i in range(12)]
    _write(here, rows)
    _go(capsys)
    _mark_by_answer(here)
    _go(capsys)
    ws = _ws(here)
    ws.ready_seen.write_text(json.dumps({"at": "2026-11-01T10:00:00Z"}), encoding="utf-8")
    before = ws.dir / "fix" / no_grades.BEFORE_FILE
    if before.is_file():  # a project from before the comparison: no round yet
        before.unlink()
    _go(capsys)
    assert _session(here).pop_up({"ready": True}) is False


def test_answers_taken_out_of_the_file_bring_no_second_pop_up(here, capsys):
    rows = [(f"Question {i}?", f"{'Bad' if i % 2 else 'Good'} answer {i}.") for i in range(12)]
    _write(here, rows)
    _go(capsys)
    page = _mark_by_answer(here)
    assert page.pop_up({"ready": True}) is True
    run(capsys, "--stop")
    _write(here, rows[:11])  # one answer taken out: new results, nothing new in them
    _go(capsys)
    assert _session(here).pop_up({"ready": True}) is False
    (_ws(here).dir / "fix" / no_grades.BEFORE_FILE).write_text("{", encoding="utf-8")
    assert _session(here).pop_up({"ready": True}) is False  # before.json can't be read


# 8. The result page under 10 marks ------------------------------------------------------------

def test_the_result_page_under_ten_marks_says_one_line(here, capsys):
    write_answers(here, 12)
    _go(capsys)
    page = _session(here)
    for item, m in zip(page.items, ["pass", "fail"] * 3, strict=False):
        page.update({"id": item["id"], "label": m, "seconds": 3})
    html = _live(here)
    seen = " ".join(_seen(html).split())
    assert "Mark a few more answers to see your result." in seen
    assert "Mark more answers to get a result." not in seen

