"""Lines around a run that stops or ends: a check given page flags says the version first, as
every run does; after a first run with answers and no grades, the project below it named is
a paragraph of its own; the Next line after a result keeps the page flags of the run, as every
command for this project does."""

from __future__ import annotations

from judgekeeper import start
from tests.start_projects import split, table_project
from tests.test_answers_without_grades import here, mark, write_answers  # noqa: F401
from tests.test_front import run


def test_check_with_page_flags_says_the_version_first(here, capsys):  # noqa: F811
    code, out, err = run(capsys, "check", "--port", "8814", "--no-browser")
    assert code == start.EXIT_USAGE, out + err
    assert out.splitlines()[0].startswith("judgekeeper "), (out, err)
    assert "opens no page" in err, err


def test_a_project_below_named_on_a_first_run_is_a_paragraph_of_its_own(here, capsys,  # noqa: F811
                                                                        pages):
    write_answers(here, 12, name="answers")
    table_project(here / "proj", split(6, 6), tag="p")
    (here / "proj" / "pyproject.toml").write_text("[project]\nname = 'p'\n", encoding="utf-8")
    code, out, _ = run(capsys, "--no-browser", "--port", "0")
    assert code == 0, out
    lines = out.splitlines()
    at = lines.index("Step 1 of 4: Read (mark your answers)")
    assert lines[at - 1] == "" and "proj" in "".join(lines[:at]), out


def test_the_next_line_after_a_result_keeps_the_page_flags(here, capsys, pages):  # noqa: F811
    write_answers(here, 12)
    assert run(capsys, "--no-browser", "--port", "0")[0] in (0, 3)
    mark(here, ["pass"] * 12)
    code, out, err = run(capsys, "--no-browser", "--port", "0")
    said = " ".join((out + err).split())
    assert code == 0 and "You passed" in said, said
    step = said.rsplit("Next: ", 1)[1]
    assert "`judgekeeper --no-browser --port 0`" in step or \
        "`judgekeeper --port 0 --no-browser`" in step, said
