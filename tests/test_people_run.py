"""`judgekeeper` on a Label Studio export where several people labelled the same answers: how
much they agree with each other, next to the check against each of them, in the terminal and in
result.json; and the time and replaced labels kept on every imported mark. No test calls an
LLM."""

from __future__ import annotations

import json
import random

import pytest

from judgekeeper import people
from judgekeeper.cli import main
from judgekeeper.start_label import Workspace
from tests.label_studio_projects import FIXTURE_DIR as FIXTURES
from tests.label_studio_projects import choice, task, write

PAGE = ("--no-browser", "--port", "0", "--yes")


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    yield tmp_path
    main(["--stop"])


def run(capsys, *argv) -> tuple[int, str]:
    capsys.readouterr()
    code = main([*argv])
    return code, "".join(capsys.readouterr())


def flat(text: str) -> str:
    return " ".join(text.split())


def lines_of(ws: Workspace) -> list[dict]:
    return [json.loads(x) for x in ws.marks.read_text(encoding="utf-8").splitlines()]


def result_of(ws: Workspace) -> dict:
    return json.loads(ws.result_json.read_text(encoding="utf-8"))


def panel(path, n: int = 60, people_ids=(7, 8), flip: float = 0.2, seed: int = 3,
          check_right: float = 0.85) -> list[dict]:
    """`n` answers each labelled by every person in `people_ids` (the second, third ... turn
    the first's word round `flip` of the time) and graded by one check."""
    rng = random.Random(seed)
    tasks = []
    for i in range(n):
        base = rng.choice(["Pass", "Fail"])
        words = [base] + [("Pass" if base == "Fail" else "Fail") if rng.random() < flip
                          else base for _ in people_ids[1:]]
        grade = base if rng.random() < check_right else ("Pass" if base == "Fail" else "Fail")
        tasks.append(task(i, list(zip(people_ids, words, strict=True)), [("judge-v1", grade)],
                          data={"question": f"Question {i}?", "answer": f"Answer {i}."}))
    write(path, tasks)
    return tasks


# The numbers ------------------------------------------------------------------------------

def test_two_people_get_kappa_a_range_and_the_check_against_each(here, capsys):
    panel(here / "export.json")
    code, out = run(capsys, *PAGE)
    assert code == 0, out
    text = flat(out)
    assert "Your people agree with each other: kappa " in text
    assert " (between " in text and "on 60 answers labelled by more than one person." in text
    assert ("A check can't be expected to agree with your people more than they agree with "
            "each other.") in text
    assert "Answers labelled by each person: user 7 (60), user 8 (60)." in text
    assert "Your check against user 7, on 60 answers: kappa " in text
    assert "Your check against user 8, on 60 answers: kappa " in text


def test_the_numbers_are_saved_in_result_json(here, capsys):
    panel(here / "export.json")
    run(capsys, *PAGE)
    block = result_of(Workspace(here))["people"]
    assert block["measure"] == "kappa" and block["people"] == 2 and block["shared"] == 60
    assert block["enough"] is True and block["value"] is not None
    lo, hi = block["interval"]
    assert lo <= block["value"] <= hi
    assert block["per_person"] == {"7": 60, "8": 60}
    assert set(block["vs_check"]) == {"7", "8"}
    assert block["seed"] == people.SEED


def test_the_people_numbers_use_every_answer_even_those_people_disagreed_on(here, capsys):
    tasks = panel(here / "export.json", flip=0.5, seed=5)
    _, out = run(capsys, *PAGE)
    ws = Workspace(here)
    disagreed = sum(len({a["result"][0]["value"]["choices"][0] for a in t["annotations"]}) > 1
                    for t in tasks)
    assert disagreed > 0
    marked = len(lines_of(ws)) - 1
    assert marked == 60 - disagreed  # the marks leave them out ...
    # ... the agreement between people does not (said before any result too)
    assert "on 60 answers labelled by more than one person." in flat(out)


def test_three_people_get_krippendorffs_alpha(here, capsys):
    panel(here / "export.json", people_ids=(7, 8, 9))
    _, out = run(capsys, *PAGE)
    assert "Your people agree with each other: Krippendorff's alpha " in flat(out)
    assert result_of(Workspace(here))["people"]["measure"] == "alpha"


def test_under_ten_answers_with_two_people_says_so_and_gives_no_number(here, capsys):
    panel(here / "export.json", n=60)
    tasks = json.loads((here / "export.json").read_text(encoding="utf-8"))
    for t in tasks[9:]:  # only nine answers keep a second person
        t["annotations"] = t["annotations"][:1]
    write(here / "export.json", tasks)
    _, out = run(capsys, *PAGE)
    text = flat(out)
    assert ("Fewer than 10 answers were labelled by more than one person, so judgekeeper "
            "can't say how much your people agree.") in text
    assert "Your people agree with each other" not in text
    block = result_of(Workspace(here))["people"]
    assert block["enough"] is False and block["value"] is None and block["shared"] == 9


def test_one_person_has_no_people_numbers(here, capsys):
    panel(here / "export.json", people_ids=(7,))
    _, out = run(capsys, *PAGE)
    assert "Your people agree" not in out and "labelled by each person" not in out
    assert "people" not in result_of(Workspace(here))


def test_a_second_run_says_the_same_again(here, capsys):
    panel(here / "export.json")
    _, first = run(capsys, *PAGE)
    _, second = run(capsys, *PAGE)
    pick = [x for x in flat(first).split(". ") if x.startswith("Your people agree")]
    assert pick and all(x in flat(second) for x in pick)


def test_people_files_hold_numbers_only_never_a_name(here, capsys):
    email = "ada.lovelace@example.com"
    tasks = panel(here / "export.json")
    for t in tasks:
        for a in t["annotations"]:
            a["completed_by"] = {"id": a["completed_by"], "email": email, "first_name": "Ada"}
    write(here / "export.json", tasks)
    run(capsys, *PAGE)
    for path in (here / ".judgekeeper").rglob("*"):
        if path.is_file() and path.suffix in (".json", ".jsonl", ".html"):
            text = path.read_text(encoding="utf-8", errors="replace")
            assert email not in text and "Ada" not in text, path.name


def test_the_labels_of_a_label_studio_file_beside_other_results(here, capsys):
    """--labels with an export, the grades in a table of another tool."""
    from tests.start_projects import answer, question, table_project

    rng = random.Random(1)
    base = [rng.choice(["Pass", "Fail"]) for _ in range(30)]
    table_project(here, [w == "Pass" for w in base], model="gpt-4.1-mini")
    tasks = [task(i, [(7, w), (8, w if i % 5 else ("Fail" if w == "Pass" else "Pass"))],
                  data={"input": question(i), "output": answer(i)})
             for i, w in enumerate(base)]
    write(here / "labels.json", tasks)
    code, out = run(capsys, *PAGE, "--labels", "labels.json")
    assert code == 0, out
    assert "Your people agree with each other: kappa " in flat(out)
    assert "on 30 answers labelled by more than one person." in flat(out)
    assert "Your check against user 7, on 30 answers" in flat(out)


# Time, and a label a person replaced ------------------------------------------------------

def test_seconds_come_from_the_time_a_person_took(here, capsys):
    panel(here / "export.json", people_ids=(7,))
    run(capsys, *PAGE)
    rows = lines_of(Workspace(here))[1:]
    assert {x["seconds"] for x in rows} == {12.5}
    assert all(x["annotation"] for x in rows)


def test_a_replaced_label_stays_in_the_file_and_the_newest_is_marked_as_replacing_it(
        here, capsys):
    tasks = [task(i, [(7, "Pass"), (7, "Fail" if i == 0 else "Pass")], [("judge-v1", "Pass")],
                  data={"question": f"Question {i}?", "answer": f"Answer {i}."})
             for i in range(40)]
    write(here / "export.json", tasks)
    run(capsys, *PAGE)
    rows = lines_of(Workspace(here))[1:]
    new = next(x for x in rows if x["mark"] == "fail")
    first = [x for x in rows if x["id"] == new["id"]]
    assert len(rows) == 80 and len(first) == 2
    old = first[0]
    assert first[1] is new
    assert old["mark"] == "pass" and "supersedes" not in old
    assert new["mark"] == "fail" and new["supersedes"] == old["annotation"]
    assert new["seconds"] == 13.5 and old["seconds"] == 12.5
    assert new["who"] == 7 and new["by"] == "label-studio"


def test_a_label_replaced_by_the_same_word_still_says_so(here, capsys):
    tasks = [task(i, [(7, "Pass"), (7, "Pass")], [("judge-v1", "Pass")]) for i in range(40)]
    write(here / "export.json", tasks)
    run(capsys, *PAGE)
    rows = lines_of(Workspace(here))[1:]
    assert sum("supersedes" in x for x in rows) == 40


def test_no_supersedes_when_nothing_was_replaced(here, capsys):
    panel(here / "export.json")
    run(capsys, *PAGE)
    assert not any("supersedes" in x for x in lines_of(Workspace(here))[1:])


def test_the_real_export_with_several_people_reads_and_runs(here, capsys):
    """The fixture of a real Label Studio export (made-up data): four tasks, two people."""
    (here / "export.json").write_text(
        (FIXTURES / "several-people.json").read_text(encoding="utf-8"), encoding="utf-8")
    code, out = run(capsys, *PAGE)
    assert code in (0, 3), out
    block = result_of(Workspace(here)).get("people") if Workspace(here).result_json.is_file() \
        else None
    assert block is None or block["enough"] is False


def test_choice_helper_still_builds_what_label_studio_writes():
    assert choice("Pass")["value"] == {"choices": ["Pass"]}


# Ask only the few ---------------------------------------------------------------------------

def mostly_unlabelled(path, labelled: int = 12, n: int = 60) -> None:
    rng = random.Random(2)
    tasks = []
    for i in range(n):
        grade = rng.choice(["Pass", "Fail"])
        tasks.append(task(i, [(7, grade)] if i < labelled else [], [("judge-v1", grade)],
                          data={"question": f"Question {i}?", "answer": f"Answer {i}."}))
    write(path, tasks)


def asked(here, name: str):
    return json.loads((here / ".judgekeeper" / "ask" / name).read_text(encoding="utf-8"))


def test_too_few_labels_write_the_files_to_label_next(here, capsys):
    mostly_unlabelled(here / "export.json")
    code, out = run(capsys, *PAGE)
    assert code == 0, out
    folder = here / ".judgekeeper" / "ask"
    assert sorted(p.name for p in folder.iterdir()) == [
        "label-config.xml", "label-these.json", "picks.json"]
    tasks = asked(here, "label-these.json")
    assert len(tasks) == 30  # ROUGH of each kind
    assert all(set(t) == {"data"} and set(t["data"]) == {"id", "input", "output"} for t in tasks)
    assert ("Import .judgekeeper/ask/label-these.json into Label Studio, label them, export, "
            "and run judgekeeper again.") in flat(out)
    assert "mark answers on the page until" in flat(out)  # the marking page: as it was


def test_the_picks_are_unmarked_answers_in_the_marking_pages_order(here, capsys):
    mostly_unlabelled(here / "export.json")
    run(capsys, *PAGE)
    ws = Workspace(here)
    marked = {x["id"] for x in lines_of(ws)[1:]}
    queue = [q["id"] for q in ws.data()["queue"] if q["id"] not in marked]
    assert [x["id"] for x in asked(here, "picks.json")] == queue[:30]
    assert [t["data"]["id"] for t in asked(here, "label-these.json")] == queue[:30]


def test_each_pick_keeps_its_chance_over_its_group(here, capsys):
    mostly_unlabelled(here / "export.json")
    run(capsys, *PAGE)
    pool = Workspace(here).data()["pool"]
    picks = asked(here, "picks.json")
    for group in ("pass", "fail"):
        mine = [x for x in picks if x["group"] == group]
        assert mine and {x["chance"] for x in mine} == {len(mine) / pool[group]}


def test_nothing_that_tells_the_grade_reaches_the_import_file(here, capsys):
    mostly_unlabelled(here / "export.json")
    run(capsys, *PAGE)
    text = (here / ".judgekeeper" / "ask" / "label-these.json").read_text(encoding="utf-8")
    for word in ("judge-v1", "prediction", "verdict", "group", "chance", "grade"):
        assert word not in text


def test_the_files_are_written_again_as_labels_come_back(here, capsys):
    mostly_unlabelled(here / "export.json", labelled=12)
    run(capsys, *PAGE)
    mostly_unlabelled(here / "export.json", labelled=20)
    run(capsys, *PAGE)
    again = asked(here, "label-these.json")
    assert len(again) == 30
    assert {t["data"]["id"] for t in again}.isdisjoint(
        {x["id"] for x in lines_of(Workspace(here))[1:]})


def test_enough_labels_write_no_ask_files(here, capsys):
    panel(here / "export.json", people_ids=(7,))
    run(capsys, *PAGE)
    assert not (here / ".judgekeeper" / "ask").exists()


def test_labels_from_no_label_studio_write_no_ask_files(here, capsys):
    from tests.start_projects import table_project

    table_project(here, [i % 2 == 0 for i in range(40)], model="gpt-4.1-mini")
    run(capsys, *PAGE)
    assert not (here / ".judgekeeper" / "ask").exists()
