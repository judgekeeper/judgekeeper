"""Another eval beside the results read: what is printed for it works. The first run names it
with a folder of its own, not a command that would stop, and each stop ends with a Next line."""

from __future__ import annotations

import pytest

from tests.start_projects import split, table_project
from tests.test_front import flat, next_lines, run

PAGE = ("--no-browser", "--port", "0")
LINE = ("Also found a.csv, with other questions. To check it, put it in a folder of its own and "
        "run `judgekeeper` there.")
SHARES = ("a.csv shares few questions with the results you marked (b.csv), so it looks like "
          "another eval.")
NEXT = "Next: put a.csv in a folder of its own, then run `judgekeeper` there."


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    return tmp_path


def _two_evals(root) -> None:
    import os
    import time

    table_project(root, split(20, 16), name="a.csv", tag="one eval")
    table_project(root, split(20, 16), name="b.csv", tag="another eval")
    os.utime(root / "a.csv", (time.time() - 3600,) * 2)


def test_the_first_run_names_another_eval_with_a_folder_of_its_own(here, capsys):
    _two_evals(here)
    code, out, err = run(capsys, *PAGE)
    run(capsys, "--stop")
    assert code == 0, out + err
    assert LINE in flat(out), out
    assert "judgekeeper a.csv" not in flat(out), out


def test_the_same_eval_keeps_its_command_and_that_command_works(here, capsys):
    import os
    import time

    table_project(here, split(20, 16), name="a.csv")
    table_project(here, split(20, 16), name="b.csv")
    os.utime(here / "a.csv", (time.time() - 3600,) * 2)
    code, out, _ = run(capsys, *PAGE)
    run(capsys, "--stop")
    assert code == 0
    assert ("Also found a.csv. To check it, run `judgekeeper a.csv --port 0 --no-browser`."
            in flat(out)), out
    assert run(capsys, "a.csv", *PAGE)[0] == 0
    run(capsys, "--stop")


def test_several_files_are_said_each_the_way_that_works(here, capsys):
    import os
    import time

    table_project(here, split(20, 16), name="a.csv", tag="one eval")
    table_project(here, split(20, 16), name="c.csv", tag="third eval")
    table_project(here, split(20, 16), name="b.csv", tag="another eval")
    table_project(here, split(20, 16), name="d.csv", tag="another eval")
    for k, name in enumerate(("a.csv", "c.csv", "d.csv")):
        os.utime(here / name, (time.time() - 3600 * (k + 1),) * 2)
    code, out, _ = run(capsys, *PAGE)
    run(capsys, "--stop")
    assert code == 0
    said = flat(out)
    assert "Also found d.csv. To check it, run `judgekeeper d.csv --port 0 --no-browser`." in said
    assert ("Also found a.csv and c.csv, with other questions. To check one, put it in a folder "
            "of its own and run `judgekeeper` there.") in said, out


@pytest.mark.parametrize("command", [[], ["mark"], ["check"], ["fix"]])
def test_naming_another_eval_stops_with_a_next_line(here, capsys, command):
    _two_evals(here)
    run(capsys, *PAGE)
    run(capsys, "--stop")
    code, out, err = run(capsys, *command, "a.csv", *(() if command[:1] in (["check"], ["fix"])
                                                      else PAGE))
    run(capsys, "--stop")
    assert code == 3, out + err
    assert SHARES in flat(out + err), out + err
    assert [" ".join(line.split()) for line in next_lines(out + err)] == [NEXT], out + err
