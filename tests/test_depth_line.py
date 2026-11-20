"""The line said when nothing is found says exactly how far judgekeeper looked: the folder
itself and up to 4 folders down, a CSV, TSV or JSONL file up to 1 folder down; the docs say the
same."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.start_projects import split, table_project
from tests.test_services_in_one_repo import _run, repo  # noqa: F401

LOOKED = ("No eval results found in this folder (d2p). judgekeeper looked in this folder and "
          "up to 4 folders down (CSV, TSV and JSONL files: up to 1 folder down).")
LEFT_OUT = ("No eval results found where judgekeeper looks: d2p and up to 4 folders down from it "
            "(CSV, TSV and JSONL files: up to 1 folder down). It left out:")
DOCS = Path(__file__).resolve().parents[1] / "docs"


@pytest.mark.parametrize("kind", ["csv", "jsonl"])
def test_a_file_two_folders_down_is_named_with_how_far_it_looked(repo, capsys, monkeypatch,  # noqa: F811
                                                                  kind):
    d2p = repo / "d2p"
    (d2p / "a" / "b").mkdir(parents=True)
    (d2p / "pyproject.toml").write_text("", encoding="utf-8")
    if kind == "csv":
        table_project(d2p / "a" / "b", split(8, 4), tag="d")
    else:
        rows = [{"input": f"Q{i}?", "output": f"A{i}.", "verdict": "pass" if i % 3 else "fail"}
                for i in range(12)]
        (d2p / "a" / "b" / "results.jsonl").write_text(
            "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    code, said = _run(capsys, monkeypatch, d2p)
    assert code == 3 and LEFT_OUT in said and f"a/b/results.{kind} (2 folders down)" in said, said


def test_nothing_found_says_how_far_it_looked(repo, capsys, monkeypatch):  # noqa: F811
    d2p = repo / "d2p"
    (d2p / "a" / "b").mkdir(parents=True)
    (d2p / "pyproject.toml").write_text("", encoding="utf-8")
    code, said = _run(capsys, monkeypatch, d2p)
    assert code == 3 and LOOKED in said, said


def test_a_file_one_folder_down_is_read(repo, capsys, monkeypatch):  # noqa: F811
    d2p = repo / "d2p"
    (d2p / "a").mkdir(parents=True)
    (d2p / "pyproject.toml").write_text("", encoding="utf-8")
    table_project(d2p / "a", split(8, 4), tag="d")
    said = _run(capsys, monkeypatch, d2p)[1]
    assert "File: a/results.csv" in said, said


def test_the_docs_say_the_same():
    tools = (DOCS / "eval-tools.md").read_text(encoding="utf-8")
    ref = (DOCS / "reference.md").read_text(encoding="utf-8")
    assert ("In your project folder and up to four folders down (a CSV, TSV or JSONL file: in "
            "the folder or up to one folder down).") in tools
    assert ("It looks only in your project folder and up to four folders down (a CSV, TSV or "
            "JSONL file: in the folder or up to one folder down);") in ref
    assert "A CSV, TSV or JSONL file in the project folder or up to one folder down, with" in ref
    for text in (tools, ref):
        assert "folders deep" not in text
