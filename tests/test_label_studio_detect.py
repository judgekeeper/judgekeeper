"""A Label Studio export is found by its first bytes, but Label Studio writes a task's
`annotations` before its `data`: with many people on a task `data` starts far into the file,
and the export must still be told from any other list."""

from __future__ import annotations

import json
import random

import pytest

from judgekeeper import find
from judgekeeper.cli import main
from judgekeeper.start_label import Workspace
from tests.label_studio_projects import annotation, choice

PAGE = ("--no-browser", "--port", "0", "--yes")


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    yield tmp_path
    main(["--stop"])


def crowded_task(i: int, people: int, words) -> dict:
    """A task in the key order Label Studio writes: `annotations` before `data`."""
    reason = {"from_name": "reason", "to_name": "answer", "type": "textarea",
              "value": {"text": ["The answer is clear and it says what to do next. " * 6]}}
    return {
        "id": 100 + i,
        "annotations": [annotation(1000 * (i + 1) + n, 2 + n, [choice(words(n)), reason],
                                   at=f"2026-11-10T10:{n % 60:02d}:00.000000Z")
                        for n in range(people)],
        "drafts": [],
        "predictions": [],
        "data": {"question": f"Question {i}?", "answer": f"Answer {i}."},
        "meta": {}, "total_annotations": people}


def export(path, n_tasks: int = 3, people: int = 150, words=lambda n: "Pass"):
    path.write_text(json.dumps([crowded_task(i, people, words) for i in range(n_tasks)],
                               indent=2), encoding="utf-8")
    return path


def test_the_fixture_puts_data_far_past_the_head(tmp_path):
    path = export(tmp_path / "labels.json")
    assert path.read_bytes().index(b'"data"') > find.HEAD_BYTES * 1.2


def test_data_far_into_the_first_task_is_still_label_studio(tmp_path):
    path = export(tmp_path / "labels.json")
    assert find.classify_file(path) == "label-studio"


def test_the_head_alone_is_still_not_enough_for_sniff_json(tmp_path):
    path = export(tmp_path / "labels.json")
    assert find.sniff_json(path.read_bytes()[:find.HEAD_BYTES]) is None
    assert find.sniff_json(find._head(path)) is None  # sniff_file reads on from it
    assert find.sniff_file(path) == "label-studio"


def test_a_folder_search_finds_it_too(tmp_path):
    export(tmp_path / "labels.json")
    found = find.search(tmp_path)
    assert [r.path.name for r in found.results.get("label-studio", [])] == ["labels.json"]


def test_it_reads_on_only_as_far_as_the_first_data_key(tmp_path):
    path = export(tmp_path / "labels.json", n_tasks=4)
    got = len(find._json_head(path))
    assert find.HEAD_BYTES < got < path.stat().st_size / 2  # past the head, not the whole file


def test_a_list_that_never_has_data_is_not_label_studio(tmp_path):
    rows = [{"annotations": [{"id": n} for n in range(3000)], "total_annotations": 3000}]
    path = tmp_path / "other.json"
    path.write_text(json.dumps(rows), encoding="utf-8")
    assert find.sniff_file(path) is None


def test_it_gives_up_past_the_cap(tmp_path, monkeypatch):
    path = export(tmp_path / "labels.json")
    monkeypatch.setattr(find, "SNIFF_BYTES", find.HEAD_BYTES * 2)  # data starts past 2 heads
    assert find.sniff_file(path) is None


def test_a_small_export_is_as_before(tmp_path):
    path = tmp_path / "labels.json"
    path.write_text(json.dumps([{"id": 1, "annotations": [], "predictions": [],
                                 "data": {"question": "Q", "answer": "A"}}]), encoding="utf-8")
    assert find.sniff_file(path) == "label-studio"


def test_labels_with_data_far_into_the_file_are_read_by_a_run(here, capsys):
    """--labels with 150 people on every answer, so each task's data starts far into the file."""
    from tests.start_projects import answer, question, table_project

    rng = random.Random(4)
    verdicts = [rng.random() < .5 for _ in range(40)]
    table_project(here, verdicts, model="gpt-4.1-mini")
    tasks = [crowded_task(i, 150, lambda n, v=v: "Pass" if v else "Fail")
             for i, v in enumerate(verdicts)]
    for i, t in enumerate(tasks):
        t["data"] = {"input": question(i), "output": answer(i)}
    (here / "export.json").write_text(json.dumps(tasks), encoding="utf-8")
    capsys.readouterr()
    code = main([*PAGE, "--labels", "export.json"])
    out = "".join(capsys.readouterr())
    assert code == 0, out
    assert "is not a labels file" not in out and "Added 40 marks from export.json" in out
    assert Workspace(here).marks.is_file()
