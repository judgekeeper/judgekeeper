"""Results over find.MAX_BYTES (200 MB) are not read without a yes, whether the search found
them or they were named on the command line. A found one is listed with the command that reads
it anyway; a named one asks at a terminal, and without one stops before anything is read, with
the same command. `--yes` reads it. MAX_BYTES is made small here: no test writes 200 MB."""

from __future__ import annotations

import pytest

from judgekeeper import find
from tests.start_projects import split, table_project
from tests.test_front import assert_one_next_at_the_end, flat, run, terminal  # noqa: F401

ANYWAY = "Next: to read results.csv anyway, run `judgekeeper results.csv --yes`."


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(find, "MAX_BYTES", 1000)  # the results file below is 1,202 bytes
    table_project(tmp_path, split(20, 20))
    return tmp_path


def _read(out: str) -> bool:
    return "Answers:     40 answers" in out


def test_a_found_file_over_the_cap_is_listed_with_the_command_that_reads_it(here, capsys):
    code, out, _ = run(capsys)
    assert code == 3 and not _read(out), out
    assert ("results.csv is 0 MB. Run judgekeeper results.csv --yes to read it anyway."
            in flat(out))
    assert assert_one_next_at_the_end(out) == ANYWAY


def test_a_named_file_over_the_cap_stops_before_it_is_read(here, capsys, monkeypatch):
    from judgekeeper import start

    read = []
    monkeypatch.setattr(start, "read_table", lambda *a, **k: read.append(a))
    code, out, _ = run(capsys, "results.csv")
    assert code == 3 and not read, out
    assert "results.csv is 0 MB." in out
    assert assert_one_next_at_the_end(out) == ANYWAY


def test_the_command_it_says_reads_the_file(here, capsys):
    code, out, _ = run(capsys, "results.csv", "--yes")
    assert code == 0 and _read(out), out


def test_at_a_terminal_it_asks_and_a_yes_reads_it(here, capsys, terminal):  # noqa: F811
    answers, asked = terminal
    answers.append("y")
    code, out, _ = run(capsys, "results.csv")
    assert asked[0] == "results.csv is 0 MB. Read it anyway? [y/N] "
    assert code == 0 and _read(out), out


def test_at_a_terminal_a_no_leaves_it_unread(here, capsys, terminal):  # noqa: F811
    answers, _ = terminal
    answers.append("n")
    code, out, _ = run(capsys, "results.csv")
    assert code == 3 and not _read(out), out
    assert "results.csv was left alone." in flat(out)
    assert assert_one_next_at_the_end(out) == ANYWAY


def test_a_named_file_under_the_cap_is_read_without_a_question(here, capsys, monkeypatch):
    monkeypatch.setattr(find, "MAX_BYTES", 2000)
    code, out, _ = run(capsys, "results.csv")
    assert code == 0 and _read(out) and "anyway" not in out, out


def test_mark_says_the_same_and_stops_without_a_terminal(here, capsys):
    code, out, _ = run(capsys, "mark", "results.csv")
    assert code == 3 and "Answers:" not in out, out
    assert "results.csv is 0 MB." in out
    assert assert_one_next_at_the_end(out) == (
        "Next: to read results.csv anyway, run `judgekeeper mark results.csv --yes`.")


def test_a_re_read_with_nothing_asked_reads_the_file_already_chosen(here):
    # check and fix read the results the marks were made on again: the yes was said then
    from judgekeeper import start

    found = start.find_judge(here / "results.csv")
    assert found.used == ["results.csv"]

