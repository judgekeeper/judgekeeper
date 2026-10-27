"""Inputs far bigger than real ones: every reader stops at table.MAX_ROWS answers, a table
holds at most table.MAX_COLUMNS columns, Find's check of a stray table has a byte budget, and
the line that says a file was cut short names it as safely as every other line."""

from __future__ import annotations

import sys

import pytest

from judgekeeper import redact, table

KEY = "sk-proj-" + "Ab3" * 15


# The cap line names the file safely ------------------------------------------------------------

def test_the_cap_line_says_the_file_name_without_escapes_or_keys(tmp_path, monkeypatch, capsys):
    if sys.platform == "win32":
        pytest.skip("Windows file names can't hold control characters")
    monkeypatch.setattr(table, "MAX_ROWS", 3)
    name = f"res\x1b]8;;https:x.example\x07ults\x1b[2J\u202e {KEY}.csv"
    path = tmp_path / name
    path.write_text("input,output,verdict\n" + "".join(f"q{i},a{i},pass\n" for i in range(5)),
                    encoding="utf-8")
    assert len(table.read_table(path)) == 3
    err = capsys.readouterr().err
    assert "Read the first 3 answers of " in err, err
    assert "\x1b" not in err and "\x07" not in err and "\u202e" not in err, repr(err)
    assert KEY not in err and redact.REDACTED in err, err
