"""A results file judgekeeper can't read, in a project named from the folder above
(`judgekeeper q`), is named from the folder the command runs in, in the error and in the
Next line. No page opens: the page is served in a thread (conftest's pages)."""

from __future__ import annotations

from tests.start_projects import split, table_project
from tests.test_services_in_one_repo import _run


def _project(tmp_path, monkeypatch, text: str):
    """top/ (32 graded of its own) with q/ (a project) whose results.csv holds `text`."""
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    top = tmp_path / "repo" / "top"
    (tmp_path / "repo" / ".git").mkdir(parents=True)
    table_project(top, split(16, 16), tag="top")
    q = top / "q"
    q.mkdir()
    (q / "pyproject.toml").write_text("[project]\nname = 'q'\n", encoding="utf-8")
    (q / "results.csv").write_text(text, encoding="utf-8")
    return top


def test_an_empty_file_in_a_project_named_from_above_is_named_from_here(tmp_path, capsys,
                                                                        monkeypatch):
    top = _project(tmp_path, monkeypatch, "")
    code, said = _run(capsys, monkeypatch, top, "q")
    assert code == 2, said
    assert "error: q/results.csv is empty, so judgekeeper can't read it." in said, said
    assert "Next: save your results to q/results.csv, then run `judgekeeper q" in said, said


def test_an_empty_file_is_named_as_it_is_in_its_own_folder(tmp_path, capsys, monkeypatch):
    top = _project(tmp_path, monkeypatch, "")
    code, said = _run(capsys, monkeypatch, top / "q")
    assert code == 2, said
    assert "error: results.csv is empty, so judgekeeper can't read it." in said, said
    assert "Next: save your results to results.csv, then run" in said, said


def test_a_title_row_in_a_project_named_from_above_is_named_from_here(tmp_path, capsys,
                                                                      monkeypatch):
    rows = "".join(f"Question {i}?,Answer {i}.,pass\n" for i in range(32))
    top = _project(tmp_path, monkeypatch, "Support bot eval\ninput,output,verdict\n" + rows)
    said = _run(capsys, monkeypatch, top, "q")[1]
    assert "q/results.csv: Row 2 looks like the header." in said, said
    assert "Next: delete row 1 of q/results.csv, then run `judgekeeper q" in said, said
