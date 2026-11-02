"""`fix` and `check` open no page: --port or --no-browser given to them is said plainly, with
the command to run instead (the rest of it kept), not argparse's "unrecognized arguments"."""

from __future__ import annotations

import pytest

from judgekeeper.cli import main
from tests.test_front import assert_one_next_at_the_end


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.mark.parametrize("argv, rest", [
    (["fix", "--port", "9581", "--no-browser"], "fix"),
    (["fix", "--new", "--no-browser"], "fix --new"),
    (["--no-browser", "fix", "new.json"], "fix new.json"),
    (["check", "--port=9000", "new results.json"], "check 'new results.json'"),
    (["check", "--port", "9000"], "check")])
def test_a_page_flag_on_fix_or_check_is_said_plainly(here, capsys, argv, rest):
    assert main(argv) == 2
    out = capsys.readouterr()
    command = rest.split()[0]
    said = out.out + out.err
    assert "unrecognized" not in said and "usage:" not in said
    assert (f"`{command}` opens no page, so it takes no --port or --no-browser."
            in said.splitlines()), said
    assert assert_one_next_at_the_end(said) == f"Next: run `judgekeeper {rest}`."
    assert list(here.iterdir()) == []
