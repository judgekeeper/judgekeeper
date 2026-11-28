"""A results file named on the command line is the one later plain runs read, also once the
marking started on another (the reference: "Later runs remember a file you name"). After a
take-on, `judgekeeper results.csv` goes back to the LLM-as-a-judge the marks were made on;
the next plain run read the newest file, new-results.csv, again: it said "Only the grades
changed" a second time, and asked to check the LLM-as-a-judge already checked."""

import os
import time

import pytest

from judgekeeper import before_after
from tests.test_compare_after_check import _checked, _flat, _run


def _said(capsys, *argv) -> tuple[int, str]:
    code, out = _run(capsys, *argv, "--no-browser", "--port", "0")
    _run(capsys, "--stop")
    return code, _flat(out)


@pytest.mark.parametrize("ids", [True, False], ids=["by-id", "by-text"])
def test_the_file_named_after_a_take_on_is_read_by_later_runs(tmp_path, monkeypatch, capsys,
                                                               ids):
    _checked(tmp_path, monkeypatch, capsys, ids)  # check took on new-results.csv
    later = time.time() + 60
    os.utime(tmp_path / "new-results.csv", (later, later))  # the newest results here
    monkeypatch.setenv("CI", "true")
    assert _said(capsys)[0] == 0
    code, out = _said(capsys, "results.csv")
    assert code == 0, out
    code, out = _said(capsys)
    assert code == 0, out
    assert before_after.ONLY_GRADES not in out and "got a different grade" not in out, out
    assert "Next: run `judgekeeper check`" not in out, out
    assert "new-results.csv" not in out, out
