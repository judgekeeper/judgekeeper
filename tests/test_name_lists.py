"""Lists of LLM-as-a-judge names: quoted for the shell, and never a flood.

A results file can name any metric, and as many as it likes. A name pasted from the line that
says to choose one must run nothing, and 50,000 names must not push the `Next:` line off the
screen.
"""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import time

import pytest

from judgekeeper.cli import main
from tests.start_projects import inspect_data, promptfoo_data, split
from tests.test_front import next_lines

EVIL = "x'; touch PWN-metric; echo '"


def _metrics(root, names, rows=None) -> None:
    """A promptfoo results file whose rows (default: every row) are also graded by a judge
    for each of `names`."""
    data = promptfoo_data(split(20, 16), metric="Correct")
    for i, row in enumerate(data["results"]["results"]):
        if rows is not None and i not in rows:
            continue
        base = row["gradingResult"]["componentResults"][0]
        for name in names:
            c = copy.deepcopy(base)
            c["assertion"] = {**c["assertion"], "metric": name}
            row["gradingResult"]["componentResults"].append(c)
    (root / "results.json").write_text(json.dumps(data), encoding="utf-8")


def _run(capsys, *argv):
    code = main([*argv, "--no-browser"])
    out, err = capsys.readouterr()
    return code, out + err


@pytest.mark.skipif(sys.platform == "win32", reason="pasted into sh")
def test_a_metric_name_pasted_from_the_choose_line_runs_nothing(tmp_path, monkeypatch, capsys):
    _metrics(tmp_path, [EVIL])
    monkeypatch.chdir(tmp_path)
    code, out = _run(capsys)
    assert code == 3
    line = next_lines(out)[-1]
    names = line.split("check (", 1)[1].rsplit("), then run", 1)[0]
    pasted = subprocess.run(["sh", "-c", f"printf '%s\\n' {names}"], cwd=tmp_path,
                            capture_output=True, text=True, check=False)
    assert not (tmp_path / "PWN-metric").exists()
    assert EVIL in pasted.stdout.splitlines(), (line, pasted.stdout)


def test_50000_metric_names_never_flood_the_terminal(tmp_path, monkeypatch, capsys):
    _metrics(tmp_path, [f"m{i}" for i in range(50_000)], rows={0})
    monkeypatch.chdir(tmp_path)
    code, out = _run(capsys)
    assert code == 3
    lines = out.rstrip("\n").splitlines()
    assert len(lines) <= 30, out
    assert "and 49,981 more" in out  # Correct and m0 to m49999, 20 shown
    assert next_lines(out)[-1] == next_lines(out)[0]  # one Next: line, at the end
    at = max(i for i, x in enumerate(lines) if x.startswith("Next:"))
    assert all(x.strip() for x in lines[at:])


def test_an_unknown_metric_lists_at_most_20_names(tmp_path, monkeypatch, capsys):
    _metrics(tmp_path, [f"m{i}" for i in range(5_000)], rows={0})
    monkeypatch.chdir(tmp_path)
    code, out = _run(capsys, "--metric", "nope")
    assert code == 2
    error = next(x for x in out.splitlines() if x.startswith("error: no LLM-as-a-judge named"))
    assert error.count("'m") <= 20 and "and 4,981 more" in error, error


def test_10000_inspect_score_keys_are_quick_and_short(tmp_path, monkeypatch, capsys):
    data = inspect_data([True, False])
    for sample in data["samples"]:
        sample["scores"]["model_graded_qa"]["value"] = {f"k{i}": "C" for i in range(10_000)}
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "a.json").write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    started = time.monotonic()
    code, out = _run(capsys)
    assert time.monotonic() - started < 2
    assert code == 3
    assert len(out.splitlines()) <= 30, out
    assert "and 9,980 more" in out


def test_on_windows_the_names_read_alike_in_double_quotes(tmp_path, monkeypatch, capsys):
    """cmd.exe and PowerShell read double quotes; a plain name gets them too."""
    _metrics(tmp_path, ["Answer Relevancy"])
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "platform", "win32")
    code, out = _run(capsys)
    assert code == 3
    assert '("Answer Relevancy", "Correct")' in next_lines(out)[-1], out
