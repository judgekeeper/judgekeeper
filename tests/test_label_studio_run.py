"""`judgekeeper` on Label Studio exports: people's labels become the marks, a prediction (or any
other check) is what is checked, and `check` says whether the check moved. No test calls an LLM.
"""

from __future__ import annotations

import json
import random
import shutil

import pytest

from judgekeeper import grader_words, marks
from judgekeeper.cli import main
from judgekeeper.records import CODE, LLM
from judgekeeper.start_label import Workspace
from tests.label_studio_projects import (
    EMAIL,
    export,
    task,
    write,
)
from tests.label_studio_projects import FIXTURE_DIR as FIXTURES
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


def words(n: int = 60, seed: int = 1, right: float = 0.85) -> tuple[list[str], list[str]]:
    """What the person said and what the check said, `right` of the time the same."""
    rng = random.Random(seed)
    people = [rng.choice(["Pass", "Fail"]) for _ in range(n)]
    check = [w if rng.random() < right else ("Pass" if w == "Fail" else "Fail") for w in people]
    return people, check


def lines_of(ws: Workspace) -> list[dict]:
    return [json.loads(x) for x in ws.marks.read_text(encoding="utf-8").splitlines()]


# People's labels are the marks ------------------------------------------------------------

def test_the_first_run_uses_the_labels_in_the_export_as_marks(here, capsys):
    people, check = words()
    export(here / "export.json", people, check)
    code, out = run(capsys, *PAGE)
    assert code == 0, out
    assert "Eval tool:       Label Studio" in out
    assert "Added 60 marks from export.json" in out
    head, *rows = lines_of(Workspace(here))
    assert len(rows) == 60
    assert {x["by"] for x in rows} == {"label-studio"}
    assert {x["from"] for x in rows} == {"export.json"}
    assert {x["who"] for x in rows} == {7}
    assert all(x["labeled_at"].startswith("2026-11-1") for x in rows)
    assert all(x["seconds"] is None for x in rows)
    assert head["label_sets"]["export.json"]["labels"] == 60
    assert len(head["label_sets"]["export.json"]["sha256"]) == 64


def test_the_marks_count_as_marks_and_the_result_has_kappa_tpr_tnr(here, capsys):
    people, check = words()
    export(here / "export.json", people, check)
    _, out = run(capsys, *PAGE)
    assert "When you say Pass, it also says Pass" in out
    assert "When you say Fail, it also says Fail" in out
    assert "Kappa" in out
    m = marks.read(Workspace(here).marks)
    assert len(m.counted()) == 60 and marks.imported(m)["from"] == ["export.json"]


def test_a_second_run_adds_no_marks_and_says_nothing_new(here, capsys):
    people, check = words()
    export(here / "export.json", people, check)
    run(capsys, *PAGE)
    _, out = run(capsys, *PAGE)
    assert "Added" not in out
    assert len(lines_of(Workspace(here))) == 61


def test_a_later_import_never_overwrites_a_mark(here, capsys):
    people, check = words()
    path = export(here / "export.json", people, check)
    run(capsys, *PAGE)
    flipped = ["Fail" if w == "Pass" else "Pass" for w in people]
    export(path, flipped, check)
    run(capsys, *PAGE)
    ws = Workspace(here)
    ours = marks.read(ws.marks).counted()
    assert sum(m == "pass" for m in ours.values()) == people.count("Pass")


def test_no_email_or_name_reaches_a_file_judgekeeper_writes(here, capsys):
    people, check = words(20)
    tasks = [task(i, [({"id": 7, "email": EMAIL, "first_name": "Ada", "last_name": "Lovelace"},
                       h)], [("v1", g)]) for i, (h, g) in enumerate(zip(people, check, strict=True))]
    write(here / "export.json", tasks)
    run(capsys, *PAGE)
    for path in (here / ".judgekeeper").rglob("*"):
        if path.is_file() and path.suffix in (".json", ".jsonl", ".html", ".csv"):
            text = path.read_text(encoding="utf-8", errors="replace")
            for word in (EMAIL, "ada.lovelace", "Lovelace"):
                assert word not in text, path.name


def test_people_who_disagree_are_left_out_and_counted(here, capsys):
    tasks = [task(i, [(7, "Pass"), (8, "Pass" if i % 2 else "Fail")], [("v1", "Pass")])
             for i in range(1, 31)]
    write(here / "export.json", tasks)
    _, out = run(capsys, *PAGE)
    assert "People disagreed on 15 answers; they are left out of this number." in flat(out)
    assert len(lines_of(Workspace(here))) == 1 + 15


# The check is not always an LLM-as-a-judge ------------------------------------------------

def test_a_check_that_is_not_an_llm_is_said_as_your_check(here, capsys):
    people, check = words()
    export(here / "export.json", people, check)
    _, out = run(capsys, *PAGE)
    assert "LLM-as-a-judge" not in out
    assert "your check" in out.lower()
    assert "Check:           verdict, predictions of judge-v1" in out
    assert "How often your check agrees with you" in out


def test_words_for_an_llm_as_a_judge_are_the_text_as_it_is():
    grader_words.use(LLM)
    line = "Your LLM-as-a-judge passed 3 answers. An LLM-as-a-judge's rule, your old LLM-as-a-judge."
    assert grader_words.swap(line) == line
    grader_words.use(CODE)
    try:
        assert grader_words.swap(line) == ("Your check passed 3 answers. A check's rule, your old "
                                           "check.")
    finally:
        grader_words.use(LLM)


def test_an_export_with_ids_for_predictions_has_no_check_to_measure(here, capsys):
    shutil.copy(FIXTURES / "answers_JSON.json", here / "export.json")
    code, out = run(capsys, *PAGE)
    assert code == 3, out  # the stop of every results file that holds no check to measure
    text = flat(out)
    assert "predictions are saved as ids only" in text
    assert "Next: export it again with the predictions in full" in text
    assert "--labels export.json" in text
    assert not (here / ".judgekeeper" / "marks.jsonl").exists()


def test_a_csv_export_is_never_read_as_a_judge(here, capsys):
    shutil.copy(FIXTURES / "answers_CSV.csv", here / "labels.csv")
    code, out = run(capsys, *PAGE)
    assert code == 3, out
    text = flat(out)
    assert "Eval tool:" not in text or "Label Studio" in text
    assert "holds your people's labels, but it holds no predictions" in text
    assert "has grades" not in text


def test_two_questions_stop_with_the_names_and_metric(here, capsys):
    people, check = words(10)
    tasks = []
    for i, (h, g) in enumerate(zip(people, check, strict=True)):
        t = task(i, [(7, h)], [("v1", g)])
        for part in (t["annotations"][0], t["predictions"][0]):
            part["result"].append({"from_name": "tone", "to_name": "answer", "type": "choices",
                                   "value": {"choices": ["Pass"]}})
        tasks.append(t)
    write(here / "export.json", tasks)
    code, out = run(capsys, *PAGE)
    assert code == 2, out
    text = flat(out)
    assert "more than one question with choices: 'verdict', 'tone'" in text
    assert "--metric verdict" in text
    code, out = run(capsys, *PAGE, "--metric", "tone")
    assert "Eval tool:       Label Studio" in out


def test_no_key_for_the_answer_names_the_keys_never_the_values(here, capsys):
    t = task(1, [(7, "Pass")], [("v1", "Pass")], data={"text": "PRIVATE-WORDS", "lang": "en"})
    write(here / "export.json", [t])
    code, out = run(capsys, *PAGE)
    assert code == 2, out
    assert "The keys are: text, lang." in flat(out)
    assert "PRIVATE-WORDS" not in out
    assert "Next:" in out


def test_code_lines_in_records_are_a_check_when_no_llm_judge_is_there(here, capsys):
    lines = []
    for i in range(40):
        for kind, label in (("CODE", "pass" if i % 3 else "fail"), ("HUMAN", "pass" if i % 2 else "fail")):
            lines.append({"target_id": f"c{i}", "name": "rule", "annotator_kind": kind,
                          "label": label, "input": question(i), "output": answer(i)})
    folder = here / ".judgekeeper" / "records"
    folder.mkdir(parents=True)
    (folder / "r.jsonl").write_text("\n".join(json.dumps(x) for x in lines) + "\n",
                                    encoding="utf-8")
    code, out = run(capsys, *PAGE)
    assert code == 0, out
    assert "LLM-as-a-judge" not in out
    assert "Check:           rule, a rule or score in your code" in out


# --labels with a Label Studio export -------------------------------------------------------

def graded_table(root, n: int = 40, seed: int = 3):
    rng = random.Random(seed)
    verdicts = [rng.random() < .5 for _ in range(n)]
    table_project(root, verdicts, model="gpt-4.1-mini")
    return verdicts


def labels_for(path, verdicts, n_wrong: int = 5):
    """A Label Studio export of the people's words for the table's answers: the first `n_wrong`
    disagree with the judge."""
    tasks = [task(i, [(7, ("Pass" if v else "Fail") if i >= n_wrong else
                          ("Fail" if v else "Pass"))], [],
                  data={"input": question(i), "output": answer(i)})
             for i, v in enumerate(verdicts)]
    return write(path, tasks)


def test_labels_from_an_export_join_another_tools_results(here, capsys):
    verdicts = graded_table(here)
    labels_for(here / "people.json", verdicts)
    code, out = run(capsys, *PAGE, "--labels", "people.json")
    assert code == 0, out
    assert "Added 40 marks from people.json (" in out
    rows = lines_of(Workspace(here))[1:]
    assert {x["by"] for x in rows} == {"label-studio"} and {x["who"] for x in rows} == {7}
    assert "LLM-as-a-judge" in out  # the judge is an LLM here: its words are the old words


def flat_export(path, verdicts, people=(2, 3)):
    """A JSON_MIN or CSV export (a row per annotation) of the answers of graded_table: every
    third answer is labelled by two people who disagree; the rest by one."""
    import csv

    rows = []
    for i, v in enumerate(verdicts):
        word = "Pass" if v else "Fail"
        who = people if i % 3 == 0 else people[:1]
        for n, person in enumerate(who):
            said = word if n == 0 else ("Fail" if word == "Pass" else "Pass")
            rows.append({"input": question(i), "output": answer(i), "id": 100 + i,
                         "verdict": said, "annotator": person, "annotation_id": len(rows) + 1,
                         "created_at": f"2026-11-22T05:19:{10 + n}.000000Z",
                         "updated_at": "2026-11-22T05:20:00.000000Z", "lead_time": 3.0})
    if path.suffix == ".csv":
        with path.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=sorted(rows[0]), quoting=csv.QUOTE_NONNUMERIC)
            w.writeheader()
            w.writerows({k: (str(v) if k == "annotator" else v) for k, v in r.items()}
                        for r in rows)
    else:
        path.write_text(json.dumps(rows, indent=1), encoding="utf-8")
    return len({i for i in range(len(verdicts)) if i % 3 == 0})


@pytest.mark.parametrize("name", ["people.json", "people.csv"])
def test_the_flat_exports_work_with_labels_too(here, capsys, name):
    verdicts = graded_table(here, 40)
    disagreed = flat_export(here / name, verdicts)
    code, out = run(capsys, "results.csv", *PAGE, "--labels", name)
    assert code == 0, out
    text = flat(out)
    assert f"People disagreed on {disagreed} answers; they are left out of this number." in text
    assert f"Added {40 - disagreed} marks from {name}" in text
    assert {x["by"] for x in lines_of(Workspace(here))[1:]} == {"label-studio"}


def test_a_flat_export_in_the_project_is_never_the_results_to_check(here, capsys):
    verdicts = graded_table(here, 40)
    flat_export(here / "people.csv", verdicts)
    code, out = run(capsys, *PAGE, "--labels", "people.csv")
    assert code == 0, out
    assert "Eval tool:       your own CSV file" in out
    assert "more than one eval tool" not in out


def test_labels_from_an_export_with_several_questions_need_the_one_named_like_the_grade(
        here, capsys):
    verdicts = graded_table(here, 40)
    tasks = []
    for i, v in enumerate(verdicts):
        t = task(i, [(7, "Pass" if v else "Fail")], [], data={"input": question(i),
                                                              "output": answer(i)})
        t["annotations"][0]["result"][0]["from_name"] = "quality"
        t["annotations"][0]["result"].append(
            {"from_name": "tone", "to_name": "answer", "type": "choices",
             "value": {"choices": ["Polite"]}})
        tasks.append(t)
    write(here / "people.json", tasks)
    code, out = run(capsys, *PAGE, "--labels", "people.json")
    assert code != 0, out
    assert "more than one question with choices" in flat(out)


# Did your check move -----------------------------------------------------------------------

def _started(here, capsys, right: float = 0.9):
    people, check = words(60, right=right)
    export(here / "export.json", people, check)
    run(capsys, *PAGE)
    main(["--stop"])
    return people, check


def test_check_says_the_check_moved_when_it_agrees_less(here, capsys):
    people, check = _started(here, capsys)
    wrong = ["Pass" if w == "Fail" else "Fail" for w in people]
    export(here / "new.json", people, wrong[:30] + check[30:], version="judge-v2")
    code, out = run(capsys, "check", "new.json")
    assert code == 1, out
    assert ("Your check moved: on the 60 answers your people labelled, it agrees with them "
            "less than before.") in flat(out)


def test_check_says_the_check_did_not_move(here, capsys):
    people, check = _started(here, capsys)
    export(here / "new.json", people, check, version="judge-v2")
    code, out = run(capsys, "check", "new.json")
    assert code == 0, out
    assert ("Your check did not move on the 60 answers your people labelled. If your scores "
            "changed, look at your app's answers first.") in flat(out)


def _g(n: int, old: int, new: int) -> dict:
    """The groups of a re-check of `n` marks of each kind where `old` of them were right
    before and `new` now."""
    from judgekeeper import check

    return check.groups(
        {f"a{i}": "pass" for i in range(n)} | {f"b{i}": "fail" for i in range(n)},
        {f"a{i}": "pass" if i < old else "fail" for i in range(n)}
        | {f"b{i}": "fail" if i < old else "pass" for i in range(n)},
        {f"a{i}": "pass" if i < new else "fail" for i in range(n)}
        | {f"b{i}": "fail" if i < new else "pass" for i in range(n)})


def test_the_moved_line_needs_fifteen_labels_of_each_kind():
    from judgekeeper import check

    assert check.moved_line(_g(14, 14, 3), None) is None
    assert check.moved_line(_g(20, 20, 2), None).startswith("Your check moved: on the 40 answers")
    assert check.moved_line(_g(20, 20, 20), None).startswith("Your check did not move on the 40")


def test_the_moved_line_says_too_early_when_the_labels_cannot_rule_a_drop_out():
    from judgekeeper import check

    assert check.moved_line(_g(20, 20, 18), None) == (
        "Too early to tell whether your check moved. These 40 labels can't rule out a drop of "
        "up to 27 points.")
    assert check.moved_line(_g(20, 20, 18), 31).endswith("up to 31 points.")


def test_the_moved_line_stays_quiet_when_agreement_rose():
    from judgekeeper import check

    assert check.moved_line(_g(30, 5, 28), None) is None
