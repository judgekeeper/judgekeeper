"""`--labels [FILE]`: Pass/Fail labels people already have, used as marks.

`--labels FILE` reads them from a CSV, TSV or JSONL file; `--labels` alone uses the human
labels already in the results (promptfoo `human` ratings, MLflow HUMAN assessments, a
table's label column, record() HUMAN lines; never Inspect AI's edited scores). Each label
becomes one stamped line in marks.jsonl ("by": "file"), only for answers the LLM-as-a-judge
graded Pass or Fail, never over a mark already there. No test calls an LLM.
"""

from __future__ import annotations

import csv
import json
import os
import re
from pathlib import Path

import pytest

from judgekeeper import labels, marks, start, start_label
from judgekeeper.cli import main
from judgekeeper.start_label import StartSession, Workspace
from tests.start_projects import (
    answer,
    inspect_data,
    promptfoo_data,
    question,
    records_project,
    split,
    table_project,
)

PAGE = ("--no-browser", "--port", "0", "--yes")
CMD = "judgekeeper --port 0 --no-browser"  # a command as these runs print it


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def run(capsys, *argv) -> tuple[int, str]:
    code = main([*argv, *PAGE])
    out = "".join(capsys.readouterr())
    return code, out


def flat(text: str) -> str:
    return " ".join(text.split())


def write_labels(path: Path, rows: list[dict], columns: list[str] | None = None) -> Path:
    columns = columns or list(rows[0])
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(columns)
        for row in rows:
            w.writerow([row.get(c, "") for c in columns])
    return path


def lines_of(ws: Workspace) -> list[dict]:
    if not ws.marks.is_file():
        return []
    return [json.loads(x) for x in ws.marks.read_text(encoding="utf-8").splitlines()[1:]]


def imported(ws: Workspace) -> dict[str, str]:
    """{answer id: mark} of the lines the import wrote."""
    return {x["id"]: x["mark"] for x in lines_of(ws) if x.get("by") == "file"}


def by_output(ws: Workspace) -> dict[str, str]:
    """{answer text: mark} of the marks that count."""
    rows = {r["id"]: r for r in (json.loads(x) for x in
                                 ws.pool.read_text(encoding="utf-8").splitlines() if x)}
    return {rows[i]["output"]: m for i, m in marks.read(ws.marks).counted().items()}


def table(root: Path, n_pass: int = 20, n_fail: int = 20, **kwargs) -> Path:
    return table_project(root, split(n_pass, n_fail), **kwargs)


def labelled(ids, mark=None) -> list[dict]:
    """Label rows for the table's answers `ids`: the judge's grade (the first 20 pass), or
    `mark`."""
    return [{"answer": answer(i), "label": mark or ("pass" if i < 20 else "fail")}
            for i in ids]


# The Find line without --labels ----------------------------------------------------------

def test_labels_in_the_results_are_named_and_not_used_without_the_flag(here, capsys):
    table(here, extra={"human_label": ["pass"] * 20 + ["fail"] * 20})
    _code, out = run(capsys)
    assert ("Found 40 Pass/Fail labels in your results. To use them as your marks, run: "
            f"{CMD} --labels") in flat(out)
    assert "does not use them" not in out and "Added" not in out
    ws = Workspace(here)
    assert marks.read(ws.marks).counted() == {}


def test_the_find_line_keeps_the_path_in_its_command(here, capsys):
    table(here / "evals", extra={"human_label": ["pass"] * 20 + ["fail"] * 20})
    _, out = run(capsys, "evals")
    assert "run: judgekeeper evals --port 0 --no-browser --labels" in flat(out)


def test_one_label_in_the_results_is_said_in_the_singular(here, capsys):
    table(here, extra={"human_label": ["pass"] + [""] * 39})
    _, out = run(capsys)
    assert "Found 1 Pass/Fail label in your results." in flat(out)


# --labels alone: the labels in the results ----------------------------------------------

def test_a_table_label_column_is_used_with_the_flag(here, capsys):
    table(here, extra={"human_label": ["pass"] * 20 + ["fail"] * 20})
    code, out = run(capsys, "--labels")
    text = flat(out)
    assert "Added 40 marks from your results (20 Pass, 20 Fail)." in text
    assert "Found 40" not in text
    assert "Step 3 of 5: Measure" in text  # 15/15 by the import alone: no page
    ws = Workspace(here)
    assert len(imported(ws)) == 40
    assert {x["from"] for x in lines_of(ws)} == {"results"}
    assert code == 0


def test_promptfoo_human_ratings_are_used(here, capsys):
    data = promptfoo_data(split(20, 20))
    for i, row in enumerate(data["results"]["results"]):
        if i % 2 == 0:  # every other answer rated by a person, as the judge graded it
            human = {"pass": i < 20, "score": 1 if i < 20 else 0, "reason": "",
                     "assertion": {"type": "human"}}
            row["gradingResult"]["componentResults"].append(human)
    (here / "promptfooconfig.yaml").write_text("description: support bot\n", encoding="utf-8")
    (here / "results.json").write_text(json.dumps(data), encoding="utf-8")
    _, out = run(capsys, "--labels")
    assert "Added 20 marks from your results (10 Pass, 10 Fail)." in flat(out)
    ws = Workspace(here)
    assert by_output(ws) == {answer(i): "pass" if i < 20 else "fail" for i in range(0, 40, 2)}


def test_inspect_scores_edited_by_a_person_are_not_used(here, capsys):
    """Inspect keeps a person's label only when they change a score: almost all
    disagreements, so they never count as labels found."""
    data = inspect_data(split(20, 20))
    for i in (0, 25):  # the person changed the judge's grade on two answers, as Inspect writes it
        s = data["samples"][i]["scores"]["model_graded_qa"]
        judged = s["value"]
        s["history"] = [{"value": judged, "answer": None, "explanation": s["explanation"],
                         "reason": None, "metadata": {}, "provenance": None},
                        {"value": "I" if judged == "C" else "C", "answer": "UNCHANGED",
                         "explanation": "UNCHANGED", "reason": "UNCHANGED",
                         "metadata": "UNCHANGED",
                         "provenance": {"author": "ana", "reason": "checked",
                                        "timestamp": "2026-10-30T10:00:00Z", "metadata": {}}}]
        s["value"] = s["history"][1]["value"]
    path = here / "logs" / "2026-10-02_support.json"
    path.parent.mkdir()
    path.write_text(json.dumps(data), encoding="utf-8")
    _, out = run(capsys)
    assert "Found" not in out and "--labels" not in out
    ws = Workspace(here)
    assert ws.data()["left_out"]["human_labels_not_used"] == 2  # counted and dropped, as in 1.0
    code, out = run(capsys, "--labels")
    assert code == 3
    assert ("No Pass/Fail labels found in your results. To use labels from a file, run: "
            f"{CMD} --labels <file>") in flat(out)
    assert marks.read(ws.marks).counted() == {}


def test_record_lines_from_a_person_are_used(here, capsys):
    path = records_project(here, split(20, 20))
    with path.open("a", encoding="utf-8") as f:
        for i in (1, 30):
            f.write(json.dumps({"schema_version": 2, "target_id": None, "name": "Safe wording",
                                "annotator_kind": "HUMAN", "label": "fail" if i == 1 else "pass",
                                "score": None, "explanation": None, "run": None,
                                "input": question(i), "output": answer(i), "evaluator": {},
                                "created_at": "2026-10-05T11:00:00Z"}) + "\n")
    _, out = run(capsys, "--labels")
    assert "Added 2 marks from your results (1 Pass, 1 Fail)." in flat(out)
    assert by_output(Workspace(here)) == {answer(1): "fail", answer(30): "pass"}


def test_mlflow_human_assessments_reach_the_answers(mlflow_store):
    from judgekeeper.normalise import Normaliser
    from judgekeeper.readers import read_mlflow

    files = read_mlflow("qa-judge", tracking_uri=mlflow_store)
    judged = [(label, recs) for label, recs in files if label != "human assessments"]
    humans = [r for label, recs in files if label == "human assessments" for r in recs
              if r.annotator_kind == "HUMAN"]
    judged[0][1].extend(humans)
    pool = start.build_pool(judged[:1], "correctness", Normaliser())
    found = labels.in_results(pool)
    assert len(found) == 8
    keys = {a.id for a in pool.answers}
    assert {x.key for x in found} <= keys | set(pool.left)
    assert len({x.key for x in found} & keys) >= 6  # most land on answers with a clear grade
    assert sorted(x.mark for x in found) == ["fail"] * 4 + ["pass"] * 4


def test_no_labels_in_the_results_stops(here, capsys):
    table(here)
    code, out = run(capsys, "--labels")
    assert code == 3
    assert ("No Pass/Fail labels found in your results. To use labels from a file, run: "
            f"{CMD} --labels <file>") in flat(out)
    assert not Workspace(here).marks.is_file()


# --labels FILE ------------------------------------------------------------------------------

def test_a_labels_file_by_answer_alone(here, capsys):
    table(here)
    write_labels(here / "mine.csv", labelled(range(0, 40, 2)))
    _code, out = run(capsys, "--labels", "mine.csv")
    assert "Added 20 marks from mine.csv (10 Pass, 10 Fail)." in flat(out)
    ws = Workspace(here)
    assert by_output(ws) == {answer(i): "pass" if i < 20 else "fail" for i in range(0, 40, 2)}
    assert {x["from"] for x in lines_of(ws)} == {"mine.csv"}
    line = lines_of(ws)[0]
    assert line["by"] == "file" and line["seconds"] is None
    assert re.fullmatch(r"file-[0-9a-f]{8}", line["sitting"])
    assert set(line) == {"id", "mark", "group", "at", "seconds", "sitting", "by", "from"}


def test_a_labels_file_outside_the_project_and_its_folder_never_written(here, tmp_path_factory,
                                                                         capsys):
    table(here)
    away = tmp_path_factory.mktemp("away") / "mine.csv"
    write_labels(away, labelled(range(5, 40)))
    _, out = run(capsys, "--labels", str(away))
    assert "Added 35 marks from mine.csv (15 Pass, 20 Fail)." in flat(out)
    ws = Workspace(here)
    for text in (ws.marks.read_text(encoding="utf-8"), ws.result_json.read_text(encoding="utf-8"),
                 ws.report_html.read_text(encoding="utf-8"), out):
        assert str(away.parent) not in text and str(here) not in text


def test_matching_by_id(here, capsys):
    ids = [f"case-{i}" for i in range(40)]
    table(here, extra={"id": ids})
    rows = [{"id": "case-3", "answer": answer(3), "label": "fail"},
            {"id": "case-4", "answer": "Another text.", "label": "fail"}]  # text differs
    write_labels(here / "mine.csv", rows)
    _, out = run(capsys, "--labels", "mine.csv")
    text = flat(out)
    assert "Added 1 mark from mine.csv (0 Pass, 1 Fail)." in text
    assert imported(Workspace(here)) == {"case-3": "fail"}
    assert "Skipped 1 label: 1 doesn't match any answer in your results" in text


def test_the_question_tells_answers_with_the_same_text_apart(here, capsys):
    outputs = ["Same answer."] * 4 + [answer(i) for i in range(4, 40)]
    rows = [[question(i), outputs[i], "pass" if i < 20 else "fail"] for i in range(40)]
    with (here / "results.csv").open("w", encoding="utf-8", newline="") as f:
        csv.writer(f).writerows([["input", "output", "verdict"], *rows])
    write_labels(here / "mine.csv", [
        {"question": question(1), "answer": "Same answer.", "label": "fail"},
        {"question": "", "answer": "Same answer.", "label": "pass"},
        {"question": "", "answer": answer(5), "label": "pass"}])
    _, out = run(capsys, "--labels", "mine.csv")
    text = flat(out)
    assert "Added 2 marks from mine.csv (1 Pass, 1 Fail)." in text
    assert ("Skipped 1 label: 1 matches more than one answer (add a question column to tell "
            "them apart)") in text
    ws = Workspace(here)
    rows_by_id = {json.loads(x)["id"]: json.loads(x)
                  for x in ws.pool.read_text(encoding="utf-8").splitlines()}
    got = {rows_by_id[i]["input"]: m for i, m in imported(ws).items()}
    assert got == {question(1): "fail", question(5): "pass"}


def test_what_is_left_out_is_counted_by_reason(here, capsys):
    verdicts = split(20, 19) + [None]  # the last answer has no clear grade
    table_project(here, verdicts)
    rows = labelled(range(5)) + [
        {"answer": "Not in the results.", "label": "pass"},
        {"answer": "Nor this one.", "label": "fail"},
        {"answer": answer(39), "label": "pass"},  # no clear grade from the judge
        {"answer": answer(6), "label": "pass"}, {"answer": answer(6), "label": "fail"}]
    write_labels(here / "mine.csv", rows)
    _, out = run(capsys, "--labels", "mine.csv")
    assert flat("Added 5 marks from mine.csv (5 Pass, 0 Fail).\n"
                "Skipped 5 labels:\n"
                "  2 don't match any answer in your results (the answer text must be the same)\n"
                "  1 is for an answer your LLM-as-a-judge didn't grade Pass or Fail\n"
                "  2 are for answers labelled both Pass and Fail\n") in flat(out)
    said = out.split("Skipped 5 labels:\n")[1].splitlines()
    assert said[0].startswith("  2 don't") and "  2 are for answers labelled both Pass and Fail" \
        in said


def test_a_label_marks_every_repeat_of_the_same_answer(here, capsys):
    rows = [[question(i), answer(i), "pass" if i < 20 else "fail"] for i in range(40)]
    rows.append([question(0), answer(0), "fail"])  # graded again, the other way
    with (here / "results.csv").open("w", encoding="utf-8", newline="") as f:
        csv.writer(f).writerows([["input", "output", "verdict"], *rows])
    write_labels(here / "mine.csv", labelled([0]))
    _, out = run(capsys, "--labels", "mine.csv")
    assert "Added 2 marks from mine.csv (2 Pass, 0 Fail)." in flat(out)
    ids = imported(Workspace(here))
    assert len(ids) == 2 and {i.split("#")[0] for i in ids} == {next(iter(ids)).split("#")[0]}


def test_text_matches_after_line_endings_spaces_keys_and_guard_quotes(here, capsys):
    key = "sk-proj-" + "x9" * 24
    outputs = [answer(i) for i in range(40)]
    outputs[0] = f"Line one.\nUse {key} here."
    outputs[1] = "=1+1"
    rows = [[question(i), outputs[i], "pass" if i < 20 else "fail"] for i in range(40)]
    with (here / "results.csv").open("w", encoding="utf-8", newline="") as f:
        csv.writer(f).writerows([["input", "output", "verdict"], *rows])
    write_labels(here / "mine.csv", [
        {"answer": f"  Line one.\r\nUse {key} here.  ", "label": "fail"},
        {"answer": "'=1+1", "label": "fail"},
        {"answer": f" {answer(2)}\t", "label": "fail"}])
    _, out = run(capsys, "--labels", "mine.csv")
    assert "Added 3 marks from mine.csv (0 Pass, 3 Fail)." in flat(out)
    assert key not in out


def test_column_names_in_any_case_and_other_columns_ignored(here, capsys):
    table(here)
    rows = [{" Output ": answer(i), "HUMAN_LABEL": "Pass", "Notes": "x", "Input": question(i)}
            for i in range(3)]
    write_labels(here / "mine.csv", rows)
    _, out = run(capsys, "--labels", "mine.csv")
    assert "Added 3 marks from mine.csv (3 Pass, 0 Fail)." in flat(out)


def test_a_jsonl_labels_file(here, capsys):
    table(here)
    (here / "mine.jsonl").write_text("".join(
        json.dumps({"answer": answer(i), "label": i < 20}) + "\n" for i in (0, 25)),
        encoding="utf-8")
    _, out = run(capsys, "--labels", "mine.jsonl")
    assert "Added 2 marks from mine.jsonl (1 Pass, 1 Fail)." in flat(out)


def test_the_template_judgekeeper_writes_qualifies(here, capsys):
    from judgekeeper.anchors import SINGLE
    from judgekeeper.table import TEMPLATE_COLUMNS

    table(here)
    rows = [{"id": "", "input": question(i), "output": answer(i), "human_label": "fail",
             "notes": ""} for i in (21, 22)]
    write_labels(here / "mine.csv", rows, list(TEMPLATE_COLUMNS[SINGLE]))
    _, out = run(capsys, "--labels", "mine.csv")
    assert "Added 2 marks from mine.csv (0 Pass, 2 Fail)." in flat(out)


# Stops: nothing written --------------------------------------------------------------------

def _nothing_written(ws: Workspace) -> None:
    assert not ws.marks.is_file() or imported(ws) == {}


def test_an_excel_file_is_refused(here, capsys):
    table(here)
    (here / "mine.xlsx").write_bytes(b"PK\x03\x04")
    code, out = run(capsys, "--labels", "mine.xlsx")
    assert code == 3
    assert ("judgekeeper can't read Excel files. Save mine.xlsx as CSV, then run: "
            f"{CMD} --labels mine.csv") in flat(out)
    _nothing_written(Workspace(here))


def test_a_missing_file(here, capsys):
    table(here)
    code, out = run(capsys, "--labels", "nope.csv")
    assert code == 3
    assert ("Can't find nope.csv. Check the name and folder, then run: "
            f"{CMD} --labels <file>") in flat(out)
    _nothing_written(Workspace(here))


def test_a_linked_file_is_refused(here, capsys):
    table(here)
    write_labels(here / "real.csv", labelled(range(3)))
    try:
        os.symlink(here / "real.csv", here / "mine.csv")
    except (OSError, NotImplementedError):
        pytest.skip("no symlinks here")
    code, out = run(capsys, "--labels", "mine.csv")
    assert code == 3 and "link" in out
    _nothing_written(Workspace(here))


def test_a_folder_as_the_labels_file_says_to_put_the_path_first(here, capsys):
    table(here / "evals")
    code, out = run(capsys, "--labels", "evals")
    assert code == 3
    text = flat(out)
    assert f"evals is a folder. Give the labels file instead: {CMD} --labels <file>" in text
    assert ("To check that folder, put it first: judgekeeper evals --port 0 --no-browser "
            "--labels <file>") in text
    assert not (here / ".judgekeeper").exists() and not (here / "evals" / ".judgekeeper").exists()


def test_a_plain_folder_as_the_labels_file_has_no_path_hint(here, capsys):
    table(here)
    (here / "empty").mkdir()
    code, out = run(capsys, "--labels", "empty")
    assert code == 3 and "empty is a folder." in flat(out)
    assert "put it first" not in out


def test_a_file_without_the_columns_is_refused(here, capsys):
    table(here)
    write_labels(here / "mine.csv", [{"text": answer(0), "label": "pass"}])
    code, out = run(capsys, "--labels", "mine.csv")
    assert code == 3
    assert ("mine.csv needs an answer column (output or answer) and a label column (label or "
            "human_label).") in flat(out)
    _nothing_written(Workspace(here))


def test_unknown_words_stop_before_anything_is_written(here, capsys):
    table(here)
    rows = labelled(range(3)) + [{"answer": answer(3), "label": w}
                                 for w in ("maybe", "good", "n/a")]
    write_labels(here / "mine.csv", rows)
    code, out = run(capsys, "--labels", "mine.csv")
    assert code == 3
    text = flat(out)
    assert "Some labels in mine.csv aren't Pass or Fail: good, maybe, n/a." in text
    assert (f'Next: say what each one means, then run: {CMD} --labels mine.csv --label-map '
            '"WORD=pass,WORD=fail"') in text
    _nothing_written(Workspace(here))


def test_at_most_five_unknown_words_are_named(here, capsys):
    table(here)
    write_labels(here / "mine.csv", [{"answer": answer(i), "label": f"w{i}"} for i in range(8)])
    _, out = run(capsys, "--labels", "mine.csv")
    assert "aren't Pass or Fail: w0, w1, w2, w3, w4." in flat(out)


def test_numbers_are_refused(here, capsys):
    table(here)
    write_labels(here / "mine.csv", [{"answer": answer(0), "label": "0.7"},
                                     {"answer": answer(1), "label": "1"}])
    code, out = run(capsys, "--labels", "mine.csv")
    assert code == 3 and "Labels must be Pass or Fail, not numbers." in flat(out)
    _nothing_written(Workspace(here))


def test_nothing_matching_stops(here, capsys):
    table(here)
    write_labels(here / "mine.csv", [{"answer": "Nothing like it.", "label": "pass"}])
    code, out = run(capsys, "--labels", "mine.csv")
    assert code == 3
    assert ("No labels in mine.csv match your results. Check that the answer text is exactly "
            "the same.") in flat(out)
    _nothing_written(Workspace(here))


# Words ------------------------------------------------------------------------------------

def test_the_default_words_and_blank_labels(here, capsys):
    table(here)
    rows = [{"answer": answer(0), "label": "Yes"}, {"answer": answer(1), "label": "correct"},
            {"answer": answer(25), "label": "FALSE"}, {"answer": answer(26), "label": "0"},
            {"answer": answer(2), "label": "  "}]
    write_labels(here / "mine.csv", rows)
    _, out = run(capsys, "--labels", "mine.csv")
    assert "Added 4 marks from mine.csv (2 Pass, 2 Fail)." in flat(out)
    assert "Skipped" not in out


def test_the_label_map_reads_other_words(here, capsys):
    table(here)
    write_labels(here / "mine.csv", [{"answer": answer(0), "label": "good"},
                                     {"answer": answer(25), "label": "bad"}])
    _, out = run(capsys, "--labels", "mine.csv", "--label-map", "good=pass,bad=fail")
    assert "Added 2 marks from mine.csv (1 Pass, 1 Fail)." in flat(out)


# Again, and over the page's marks -------------------------------------------------------------

def test_the_same_import_twice_changes_nothing(here, capsys):
    table(here)
    write_labels(here / "mine.csv", labelled(range(10)))
    run(capsys, "--labels", "mine.csv")
    ws = Workspace(here)
    before = ws.marks.read_bytes()
    _code, out = run(capsys, "--labels", "mine.csv")
    assert ws.marks.read_bytes() == before
    assert "Added 0 marks from mine.csv (0 Pass, 0 Fail)." in flat(out)
    assert "--labels" not in out.split("Added")[1]  # never in a Next line


def test_a_mark_made_on_the_page_is_kept(here, capsys):
    table(here)
    run(capsys)
    ws = Workspace(here)
    first = ws.data()["queue"][0]
    session = StartSession(ws)
    session.update({"id": first["id"], "label": "fail" if first["group"] == "pass" else "pass",
                    "seconds": 6})
    row = json.loads(next(x for x in ws.pool.read_text(encoding="utf-8").splitlines()
                          if json.loads(x)["id"] == first["id"]))
    write_labels(here / "mine.csv", [{"answer": row["output"], "label": first["group"]},
                                     {"answer": answer(10), "label": "pass"}])
    _, out = run(capsys, "--labels", "mine.csv")
    text = flat(out)
    assert "Added 1 mark from mine.csv (1 Pass, 0 Fail)." in text
    assert "Kept your earlier mark on 1 answer that mine.csv labels differently." in text
    assert marks.read(ws.marks).counted()[first["id"]] != first["group"]


def test_a_mark_changed_on_the_page_after_an_import_wins(here, capsys):
    table(here)
    write_labels(here / "mine.csv", labelled([0]))
    run(capsys, "--labels", "mine.csv")
    ws = Workspace(here)
    [(item, _)] = imported(ws).items()
    StartSession(ws).update({"id": item, "label": "fail", "seconds": 4})
    assert marks.read(ws.marks).counted()[item] == "fail"
    run(capsys, "--labels", "mine.csv")
    assert marks.read(ws.marks).counted()[item] == "fail"


def test_without_the_flag_no_pool_row_marks_an_answer(here, capsys):
    """label.py seeds a session's labels from a pool row's human_label: pool.jsonl never holds
    one, so the page shows nothing marked before the person asks."""
    table(here, extra={"human_label": ["pass"] * 20 + ["fail"] * 20})
    run(capsys)
    ws = Workspace(here)
    rows = [json.loads(x) for x in ws.pool.read_text(encoding="utf-8").splitlines()]
    assert rows and all("human_label" not in r and "label" not in r for r in rows)
    assert StartSession(ws).marked() == {}


# The numbers -------------------------------------------------------------------------------

def _marked_like_this(root: Path, how: str, capsys) -> dict:
    """A 60-answer table, 18 Pass and 16 Fail marks with 4 disagreements, made through the
    import or through the page (StartSession.update), and its result.json."""
    table(root, 30, 30)
    marks_wanted = {i: "pass" for i in range(18)} | {i: "fail" for i in range(30, 46)}
    marks_wanted |= {1: "fail", 2: "fail", 31: "pass", 32: "pass"}
    if how == "file":
        write_labels(root / "mine.csv", [{"answer": answer(i), "label": m}
                                         for i, m in marks_wanted.items()])
        run(capsys, str(root), "--labels", str(root / "mine.csv"))
    else:
        run(capsys, str(root))
        ws = Workspace(root)
        rows = {json.loads(x)["output"]: json.loads(x)["id"]
                for x in ws.pool.read_text(encoding="utf-8").splitlines()}
        session = StartSession(ws)
        for i, m in marks_wanted.items():
            session.update({"id": rows[answer(i)], "label": m, "seconds": 5})
        run(capsys, str(root))
    return json.loads(Workspace(root).result_json.read_text(encoding="utf-8"))


NUMBERS = ("tpr", "tnr", "kappa", "tpr_interval", "tnr_interval", "kappa_interval", "labels",
           "groups", "check", "verdict_level", "disagreements", "left", "smallest_drop")


def test_imported_marks_give_the_same_numbers_as_page_marks(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    by_file = _marked_like_this(tmp_path / "file", "file", capsys)
    by_page = _marked_like_this(tmp_path / "page", "page", capsys)
    for key in NUMBERS:
        assert by_file.get(key) == by_page.get(key), key
    assert by_file["imported"] == {"marks": 34, "pass": 18, "fail": 16, "from": ["mine.csv"]}
    assert "imported" not in by_page


# How the marks were made ------------------------------------------------------------------

def test_made_leaves_imported_marks_out_of_visits_and_timing(here, capsys):
    table(here)
    write_labels(here / "mine.csv", labelled(range(0, 40, 2)))
    run(capsys, "--labels", "mine.csv")
    ws = Workspace(here)
    m = marks.read(ws.marks)
    made = marks.made(m)
    assert made["marks"] == 20 and made["sittings"] == 0 and made["seconds"] is None
    assert made["under_second"] == 0
    assert start_label.made_lines(made, marks.imported(m)) == [
        "Your marks: 20 (10 Pass, 10 Fail), all from mine.csv."]
    session = StartSession(ws)
    item = next(q["id"] for q in ws.data()["queue"] if q["id"] not in imported(ws))
    session.update({"id": item, "label": "pass", "seconds": 0.2})
    m = marks.read(ws.marks)
    made = marks.made(m)
    assert made["sittings"] == 1 and made["under_second"] == 1
    assert start_label.made_lines(made, marks.imported(m))[0] == (
        "Your marks: 21 (11 Pass, 10 Fail): 20 from mine.csv, 1 marked on the page.")


def test_an_import_never_looks_like_a_program(here, capsys):
    table(here)
    write_labels(here / "mine.csv", labelled(range(40)))
    _, out = run(capsys, "--labels", "mine.csv")
    assert "under a second" not in out and "program" not in out


def test_page_marks_are_said_in_visits():
    made = {"marks": 32, "pass": 16, "fail": 16, "sittings": 1, "seconds": 9,
            "under_second": 0, "not_counted": 0}
    assert start_label.made_lines(made)[0] == (
        "Your marks: 32 (16 Pass, 16 Fail), marked on the page over 1 visit, about 9 seconds "
        "each.")
    made.update(sittings=3, seconds=None)
    assert start_label.made_lines(made)[0] == (
        "Your marks: 32 (16 Pass, 16 Fail), marked on the page over 3 visits.")


def test_a_line_neither_page_nor_file_is_still_not_counted(tmp_path):
    path = tmp_path / "marks.jsonl"
    marks.begin(path, {"marks": 1})
    marks.append(path, {"id": "a", "mark": "pass", "group": "pass", "at": "2026-10-31T00:00:00Z",
                        "seconds": None, "sitting": "x", "by": "script"})
    marks.append(path, marks.imported_line("b", "fail", "fail", "file-0123abcd", "mine.csv"))
    m = marks.read(path)
    assert m.counted() == {"b": "fail"} and m.not_counted == 1


# The assumption line -------------------------------------------------------------------------

ASSUMES = ("{k} of your marks came from {name}. The numbers assume those answers were picked at "
      "random and labelled without looking at your LLM-as-a-judge's grade.")


def test_the_assumption_is_said_wherever_the_result_is(here, capsys):
    table(here)
    write_labels(here / "mine.csv", labelled(range(40)))
    _, out = run(capsys, "--labels", "mine.csv")
    line = ASSUMES.format(k=40, name="mine.csv")
    assert line in flat(out)
    ws = Workspace(here)
    report = flat(re.sub(r"<[^>]+>", "", ws.report_html.read_text(encoding="utf-8")))
    assert line in report.replace("&#x27;", "'").replace("&#39;", "'")
    r = json.loads(ws.result_json.read_text(encoding="utf-8"))
    assert r["imported"] == {"marks": 40, "pass": 20, "fail": 20, "from": ["mine.csv"]}
    live = flat(re.sub(r"<[^>]+>", "", start_label.result_html(r, "/?token=t")))
    assert line in live.replace("&#x27;", "'").replace("&#39;", "'")


def test_the_assumption_names_your_results_and_two_files(here, capsys):
    table(here, extra={"human_label": ["pass"] * 15 + [""] * 25})
    run(capsys, "--labels")
    write_labels(here / "a.csv", labelled(range(20, 40)))
    _, out = run(capsys, "--labels", "a.csv")
    assert ASSUMES.format(k=35, name="your results and a.csv") in flat(out)


def test_no_assumption_line_without_imported_marks(here, capsys):
    table(here)
    run(capsys)
    ws = Workspace(here)
    session = StartSession(ws)
    for q in ws.data()["queue"]:
        session.update({"id": q["id"], "label": q["group"], "seconds": 5})
    _, out = run(capsys)
    assert "came from" not in out
    assert "imported" not in json.loads(ws.result_json.read_text(encoding="utf-8"))


# fix, check, and topping up on the page ---------------------------------------------------

def test_fix_and_check_run_on_marks_partly_imported(here, capsys):
    table(here, 30, 30)
    write_labels(here / "mine.csv", labelled(range(10)) +
                 [{"answer": answer(i), "label": "fail"} for i in range(30, 40)])
    run(capsys, "--labels", "mine.csv")
    ws = Workspace(here)
    session = StartSession(ws)
    done = set(marks.read(ws.marks).counted())
    for q in ws.data()["queue"]:
        if q["id"] not in done:
            session.update({"id": q["id"], "label": q["group"], "seconds": 5})
    code, out = run(capsys)
    assert code == 0 and "Traceback" not in out
    assert main(["fix"]) in (0, 3)
    out = "".join(capsys.readouterr())
    assert "Traceback" not in out and (ws.dir / "fix" / "split.json").is_file()
    assert main(["fix", "--new"]) in (0, 3)
    assert "Traceback" not in "".join(capsys.readouterr())
    assert main(["check"]) in (0, 3)
    assert "Traceback" not in "".join(capsys.readouterr())


def test_the_page_goes_on_from_the_first_answer_not_marked(here, capsys):
    table(here)
    run(capsys)  # the queue as the page shows it
    ws = Workspace(here)
    queue = ws.data()["queue"]
    rows = {json.loads(x)["id"]: json.loads(x)
            for x in ws.pool.read_text(encoding="utf-8").splitlines()}
    write_labels(here / "mine.csv", [{"answer": rows[q["id"]]["output"], "label": q["group"]}
                                     for q in queue[:5]])
    _, out = run(capsys, "mark", "--labels", "mine.csv")
    assert "Added 5 marks from mine.csv" in flat(out)
    session = StartSession(ws)
    state = session.state()
    assert state["items"][state["start"]]["id"] == queue[5]["id"]
    assert state["counts"]["correct"] + state["counts"]["wrong"] == 5


def test_mark_takes_the_flag_and_fix_and_check_do_not(here, capsys):
    from judgekeeper.cli import parse_args

    assert parse_args(["mark", "--labels", "x.csv"]).labels == "x.csv"
    assert parse_args(["--labels"]).labels == labels.IN_RESULTS
    assert parse_args(["evals", "--labels"]).path == "evals"
    assert parse_args([]).labels is None
    for command in ("fix", "check"):
        with pytest.raises(SystemExit):
            parse_args([command, "--labels"])


def test_the_flag_is_never_repeated_in_a_command(here, capsys):
    assert "labels" not in {name for name, _ in start.REPEATED}
    table(here)
    write_labels(here / "mine.csv", labelled(range(5)))
    _, out = run(capsys, "--labels", "mine.csv")
    assert "Next:" in out and "--labels" not in out.split("Next:")[-1]



# Found in the first round of end-to-end tests ----------------------------------------------

def test_an_id_with_an_empty_answer_cell_matches_by_id(here, capsys):
    ids = [f"case-{i}" for i in range(40)]
    table(here, extra={"id": ids})
    rows = [{"id": "case-10", "answer": "", "label": "pass"},
            {"id": "case-30", "answer": "", "label": "fail"},
            {"id": "case-99", "answer": "", "label": "pass"}]  # no such id
    write_labels(here / "mine.csv", rows)
    _, out = run(capsys, "--labels", "mine.csv")
    text = flat(out)
    assert "Added 2 marks from mine.csv (1 Pass, 1 Fail)." in text
    assert imported(Workspace(here)) == {"case-10": "pass", "case-30": "fail"}
    assert "Skipped 1 label: 1 doesn't match any answer in your results" in text


def test_a_big_labels_file_keeps_the_flag_in_its_next_line(here, capsys, monkeypatch):
    from judgekeeper import find

    results = table(here)
    rows = labelled(range(5)) + [{"answer": f"filler {n}", "label": "pass", "notes": "x" * 400}
                                 for n in range(20)]
    write_labels(here / "mine.csv", rows, ["answer", "label", "notes"])
    monkeypatch.setattr(find, "MAX_BYTES", results.stat().st_size + 1)  # the labels file only
    code = main(["--labels", "mine.csv", "--no-browser", "--port", "0"])  # no --yes
    out = flat("".join(capsys.readouterr()))
    assert code in (0, 3) and "mine.csv is " in out  # asked, or no terminal
    command = f"{CMD} --labels mine.csv --yes"
    assert f"Next: to read mine.csv anyway, run `{command}`." in out
    assert main(command.split()[1:]) in (0, 3)  # run as printed: the labels come in
    assert "Added 5 marks from mine.csv" in flat("".join(capsys.readouterr()))


def test_an_open_page_shows_marks_imported_since_it_opened(here, capsys):
    table(here, extra={"human_label": ["pass"] * 10 + [""] * 20 + ["fail"] * 10})
    run(capsys)
    ws = Workspace(here)
    page = StartSession(ws)  # the page, open before the import
    assert page.state()["counts"] == {"correct": 0, "wrong": 0, "skipped": 0}
    run(capsys, "--labels")
    state = page.state()
    assert state["counts"]["correct"] + state["counts"]["wrong"] == 20
    first = state["items"][state["start"]]
    assert first["label"] is None and first["id"] not in imported(ws)


def test_a_labels_file_over_the_row_limit_is_read_whole(here, capsys, monkeypatch):
    from judgekeeper import table as table_mod

    table(here)
    monkeypatch.setattr(table_mod, "MAX_ROWS", 50)
    rows = [{"answer": f"filler {n}", "label": "pass"} for n in range(60)]
    write_labels(here / "mine.csv", rows + labelled(range(5)))
    _, out = run(capsys, "--labels", "mine.csv")
    text = flat(out)
    assert "Added 5 marks from mine.csv (5 Pass, 0 Fail)." in text
    assert "60 don't match any answer" in text


@pytest.mark.parametrize("content", ["output,label\n", ""])
def test_a_labels_file_with_no_rows(here, capsys, content):
    table(here)
    (here / "mine.csv").write_text(content, encoding="utf-8")
    code, out = run(capsys, "--labels", "mine.csv")
    assert code == 3
    assert "mine.csv has no labels." in flat(out)
    assert "needs an answer column" not in out
    _nothing_written(Workspace(here))


def test_an_empty_labels_name(here, capsys):
    table(here)
    code, out = run(capsys, "--labels", "")
    text = flat(out)
    assert code == 3
    assert f"Give the labels file: {CMD} --labels <file>" in text
    assert "is a folder" not in text and "put it first" not in text
    _nothing_written(Workspace(here))


@pytest.mark.parametrize(("second", "said"), [
    ("{bad json", "bad.jsonl: line 2: invalid JSON"),
    ("[1, 2]", "bad.jsonl: line 2: each line must be a JSON object")])
def test_jsonl_label_errors_name_the_file_alone(here, capsys, second, said):
    table(here)
    path = here / "bad.jsonl"
    path.write_text(json.dumps({"answer": answer(0), "label": "pass"}) + "\n" + second + "\n",
                    encoding="utf-8")
    code, out = run(capsys, "--labels", str(path))
    assert code == 3
    assert said in flat(out)
    assert str(here) not in out and "Expecting" not in out and "(" not in flat(out).split(said)[1][:2]
    _nothing_written(Workspace(here))


def test_the_same_import_twice_says_nothing_is_new(here, capsys):
    table(here)
    write_labels(here / "mine.csv", labelled(range(10)))
    run(capsys, "--labels", "mine.csv")
    _, out = run(capsys, "--labels", "mine.csv")
    assert ("Added 0 marks from mine.csv (0 Pass, 0 Fail). Nothing new: the labels in mine.csv "
            "are already your marks.") in flat(out)
    write_labels(here / "more.csv", labelled(range(10, 12)))
    _, out = run(capsys, "--labels", "more.csv")
    assert "Nothing new" not in out


def test_a_labels_stop_has_no_excel_note_about_another_file(here, capsys):
    table(here)
    (here / "labels.xlsx").write_bytes(b"PK\x03\x04")
    write_labels(here / "nolabel.csv", [{"text": answer(0), "label": "pass"}])
    code, out = run(capsys, "--labels", "nolabel.csv")
    assert code == 3 and "nolabel.csv needs an answer column" in flat(out)
    assert "Excel" not in out
    write_labels(here / "mine.csv", labelled(range(3)))
    _, out = run(capsys, "--labels", "mine.csv")  # read: the note is said as before
    assert "labels.xlsx is an Excel file: save it as CSV UTF-8 to use it." in flat(out)


def test_new_answers_with_labels_get_the_find_line(here, capsys):
    table(here)
    run(capsys)
    table_project(here, split(20, 20) + split(5, 5),  # 10 new answers, each labelled
                  extra={"human_label": [""] * 40 + ["pass"] * 5 + ["fail"] * 5})
    _, out = run(capsys)
    text = flat(out)
    assert "Your newest results have 10 answers you haven't seen." in text
    assert ("Found 10 Pass/Fail labels in your results. To use them as your marks, run: "
            f"{CMD} --labels") in text


def test_labels_for_another_question_are_not_used(here, capsys):
    path = records_project(here, split(20, 20))
    with path.open("a", encoding="utf-8") as f:
        for i, name in ((1, "Tone"), (2, "Tone"), (30, "Safe wording")):
            f.write(json.dumps({"schema_version": 2, "target_id": None, "name": name,
                                "annotator_kind": "HUMAN", "label": "fail",
                                "score": None, "explanation": None, "run": None,
                                "input": question(i), "output": answer(i), "evaluator": {},
                                "created_at": "2026-10-05T11:00:00Z"}) + "\n")
    _, out = run(capsys)
    assert "Found 1 Pass/Fail label in your results." in flat(out)
    _, out = run(capsys, "--labels")
    assert "Added 1 mark from your results (0 Pass, 1 Fail)." in flat(out)
    assert by_output(Workspace(here)) == {answer(30): "fail"}
