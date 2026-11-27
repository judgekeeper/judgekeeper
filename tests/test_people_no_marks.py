"""People who never agree on one label (no ground truth, nobody all alike): no marks come of
the export, but how much they agree is the point, and is said and saved all the same."""

from __future__ import annotations

import json
import random

import pytest

from judgekeeper.cli import main
from judgekeeper.start_label import Workspace
from tests.label_studio_projects import task, write
from tests.start_projects import answer, question, table_project

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


def split_panel(path, n: int = 40, people=(7, 8, 9), with_predictions: bool = False) -> None:
    """Every answer is labelled by every person and no two answers' people all agree: the first
    two always differ, the rest follow one of them."""
    rng = random.Random(6)
    tasks = []
    for i in range(n):
        first = rng.choice(["Pass", "Fail"])
        other = "Fail" if first == "Pass" else "Pass"
        words = [first, other] + [rng.choice([first, other]) for _ in people[2:]]
        tasks.append(task(i, list(zip(people, words, strict=True)),
                          [("judge-v1", first)] if with_predictions else [],
                          data={"input": question(i), "output": answer(i)}))
    write(path, tasks)


def graded(here, n: int = 40) -> None:
    rng = random.Random(1)
    table_project(here, [rng.random() < .5 for _ in range(n)], model="gpt-4.1-mini")


def test_people_who_never_agree_still_get_their_numbers(here, capsys):
    graded(here)
    split_panel(here / "people.json")
    code, out = run(capsys, *PAGE, "--labels", "people.json")
    text = flat(out)
    assert "The people marking agree with each other: Krippendorff's alpha " in text
    assert "on 40 answers labelled by more than one person." in text
    assert "A check can't be expected to agree with the people marking more than they agree " \
           "with each other." in text
    assert "Answers labelled by each person: user 7 (40), user 8 (40), user 9 (40)." in text
    for who in (7, 8, 9):
        assert f"Your check against user {who}, on 40 answers: kappa " in text
    assert code == 3  # the existing stop: there are no marks to go on with


def test_the_stop_and_its_words_are_the_ones_it_had(here, capsys):
    graded(here)
    split_panel(here / "people.json")
    _, out = run(capsys, *PAGE, "--labels", "people.json")
    text = flat(out)
    assert "No labels in people.json." in text
    assert "People disagreed on 40 answers; they are left out of this number." in text
    assert text.index("The people marking agree") < text.index("No labels in people.json.")


def test_the_numbers_are_saved_in_result_json_without_any_mark(here, capsys):
    graded(here)
    split_panel(here / "people.json")
    run(capsys, *PAGE, "--labels", "people.json")
    ws = Workspace(here)
    block = json.loads(ws.result_json.read_text(encoding="utf-8"))["people"]
    assert block["measure"] == "alpha" and block["shared"] == 40 and block["enough"] is True
    assert set(block["vs_check"]) == {"7", "8", "9"}
    assert not any(json.loads(x).get("mark") for x in
                   (ws.marks.read_text(encoding="utf-8").splitlines()[1:] if ws.marks.is_file()
                    else []))


def test_a_second_run_says_the_same(here, capsys):
    graded(here)
    split_panel(here / "people.json")
    run(capsys, *PAGE, "--labels", "people.json")
    code, again = run(capsys, *PAGE, "--labels", "people.json")
    assert code == 3
    assert "The people marking agree with each other: Krippendorff's alpha " in flat(again)
    assert "No labels in people.json." in flat(again)


def test_two_people_who_always_differ_get_kappa(here, capsys):
    graded(here)
    split_panel(here / "people.json", people=(7, 8))
    _, out = run(capsys, *PAGE, "--labels", "people.json")
    assert "The people marking agree with each other: kappa " in flat(out)


def test_when_the_export_is_the_results_too(here, capsys):
    """One Label Studio export with predictions for the check and nobody agreeing."""
    split_panel(here / "export.json", with_predictions=True)
    code, out = run(capsys, *PAGE)
    text = flat(out)
    assert "The people marking agree with each other: Krippendorff's alpha " in text
    assert "People disagreed on 40 answers" in text
    assert code == 0  # no marks yet: the marking page, as it was


def test_people_who_agree_on_some_have_marks_and_the_same_numbers_as_before(here, capsys):
    graded(here)
    tasks = [task(i, [(7, "Pass"), (8, "Pass" if i % 2 else "Fail")],
                  data={"input": question(i), "output": answer(i)}) for i in range(40)]
    write(here / "people.json", tasks)
    code, out = run(capsys, *PAGE, "--labels", "people.json")
    assert "Added 20 marks from people.json" in out
    assert "The people marking agree with each other: kappa " in flat(out)
    assert code in (0, 3)
