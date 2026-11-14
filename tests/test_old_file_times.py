"""A results file whose modified time is at or near 1970 (the Nix store sets every file's to 1,
some archive tools write 0) is read like any other. On Windows, local time is unknown that
early: localtime() takes no time before 1970, and Python looks a day back, so turning such a
time into local time raises OSError. The date then stays in UTC, never an error."""

from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest

from judgekeeper import find
from judgekeeper.cli import main
from tests.start_projects import split, table_project
from tests.test_front import flat


class _WindowsTime(datetime):
    """datetime as on Windows: local time near 1970 raises, as localtime() does there."""

    def astimezone(self, tz=None):
        if tz is None and (self if self.tzinfo else self.replace(tzinfo=UTC)).timestamp() < \
                2 * 86400:
            raise OSError(22, "Invalid argument")
        return super().astimezone(tz)


@pytest.fixture(params=[False, True], ids=["here", "as on windows"])
def windows(request, monkeypatch):
    if request.param:
        monkeypatch.setattr(find, "datetime", _WindowsTime)
    return request.param


@pytest.mark.parametrize("stamp", [0, 1, 86399])
def test_a_file_time_near_1970_has_a_date(tmp_path, windows, stamp):
    path = table_project(tmp_path, split(3, 3))
    os.utime(path, (stamp, stamp))
    result = find.Result("table", path, path.name, path.stat().st_size)
    day = result.date()
    assert day.tzinfo is not None
    assert day.astimezone(UTC).timestamp() == stamp


def test_an_older_file_of_another_eval_from_1970_is_named_not_a_crash(tmp_path, capsys,
                                                                      monkeypatch, windows):
    """logs/graded.csv and, at the top, top.csv of other questions dated 1970: the run names
    top.csv as another eval."""
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    top = tmp_path / "w"
    table_project(top / "logs", split(5, 5), tag="a", name="graded.csv")
    old = table_project(top, split(3, 3), tag="b", name="top.csv")
    os.utime(old, (1, 1))
    monkeypatch.chdir(top)
    main(["--no-browser", "--port", "0"])
    out, err = capsys.readouterr()
    main(["--stop"])
    capsys.readouterr()
    said = flat(out + err)
    assert "didn't expect" not in said, said
    assert "Also found top.csv, with other questions." in said, said
