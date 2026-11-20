"""A `.` typed as the PATH stays in every command printed: `judgekeeper .` makes this folder the
project, and a plain `judgekeeper` in it may read the folder above."""

from __future__ import annotations

from judgekeeper import project
from tests.test_answers_without_grades import write_answers
from tests.test_front import flat, next_lines, run


def _bot_below_results(tmp_path, monkeypatch):
    """A project with graded results, and below it a folder with code and no answers yet."""
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    top = tmp_path / "shop"
    (top / ".git").mkdir(parents=True)
    write_answers(top, 40, grades=["pass", "fail"] * 20)
    bot = top / "bot"
    bot.mkdir()
    (bot / "bot.py").write_text("", encoding="utf-8")
    monkeypatch.chdir(bot)
    project.forget()
    return bot


def test_the_next_line_after_no_answers_yet_keeps_the_dot(tmp_path, capsys, monkeypatch):
    _bot_below_results(tmp_path, monkeypatch)
    code, out, err = run(capsys, ".", "--no-browser", "--port", "0")
    assert code == 3 and "No answers yet?" in flat(out), out + err
    assert next_lines(out) == [("Next: paste the prompt above into your coding agent, then run "
                                "`judgekeeper . --port 0 --no-browser` again.")], out


def test_mark_with_a_dot_keeps_it_too(tmp_path, capsys, monkeypatch):
    _bot_below_results(tmp_path, monkeypatch)
    code, out, err = run(capsys, "mark", ".", "--no-browser", "--port", "0")
    assert code == 3, out + err
    assert all("judgekeeper mark . --port 0 --no-browser" in line or "`" not in line
               for line in next_lines(out)), out


def test_no_dot_typed_gives_none(tmp_path, capsys, monkeypatch):
    bot = _bot_below_results(tmp_path, monkeypatch)
    (bot / "bot.py").unlink()  # a plain folder: the run reads the results above
    code, out, err = run(capsys, "--no-browser", "--port", "0")
    assert code in (0, 3), out + err
    assert " . " not in " ".join(next_lines(out)), out + err
