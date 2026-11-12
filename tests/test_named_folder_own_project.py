"""A folder named as the PATH is always the project: inside a project with marks, a named
folder with no answers never takes the outer project's marks; it gets the "No answers yet?"
prompt."""

from __future__ import annotations

from judgekeeper import project
from tests.test_fixed_and_broke import Project, here  # noqa: F401
from tests.test_fixed_and_broke import project as with_marks  # noqa: F401
from tests.test_front import flat, run


def test_a_named_folder_with_code_only_gets_the_prompt(with_marks, monkeypatch):  # noqa: F811
    with_marks.first(fails={0, 1, 2}, n=12)
    inner = with_marks.here / "notes" / "noanswers-proj"
    inner.mkdir(parents=True)
    (inner / "bot.py").write_text("", encoding="utf-8")
    project.forget()
    code, out, err = run(with_marks.capsys, "notes/noanswers-proj", "--no-browser", "--port",
                         "0")
    said = flat(out + err)
    assert code == 3 and "No answers yet?" in said, said
    assert "marks are saved" not in said and "12 marks" not in said, said
    assert not (inner / ".judgekeeper").exists()


def test_a_named_folder_with_its_own_marks_still_says_they_are_kept(with_marks):  # noqa: F811
    with_marks.first(fails={0, 1, 2}, n=12)
    (with_marks.here / "results.csv").unlink()
    project.forget()
    code, out, err = run(with_marks.capsys, ".", "--no-browser", "--port", "0")
    assert code == 3, out + err
    assert "Your 12 marks are saved in .judgekeeper/" in flat(out + err), out + err
