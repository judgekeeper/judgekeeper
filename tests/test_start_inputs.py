"""Inputs `start` reads: a very long cell, a long first JSONL line, a log that can't be read
next to one that can, a header with no rows, a UTF-16 export, a results file in another
folder, and decision values judgekeeper can't read as Pass or Fail."""

from __future__ import annotations

import csv
import json
import os
import sys
import types

import pytest

from judgekeeper import find, start, start_label
from judgekeeper.cli import main
from tests.start_projects import inspect_data, split, table_project


def run(capsys, *argv):
    code = main([*map(str, argv), "--yes"])
    out, err = capsys.readouterr()
    return code, out + err


def _rows(n_pass=16, n_fail=16, long_output=""):
    rows = [{"input": f"Question {i}?", "output": f"Answer {i}.{long_output if i == 0 else ''}",
             "verdict": "pass" if i < n_pass else "fail"} for i in range(n_pass + n_fail)]
    return rows


def _csv(path, rows):
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def test_an_eval_log_cut_short_is_one_plain_line(tmp_path, capsys, monkeypatch):
    def read_eval_log(path):
        raise ValueError("EOCD not found")

    log = types.ModuleType("inspect_ai.log")
    log.read_eval_log = read_eval_log
    monkeypatch.setitem(sys.modules, "inspect_ai", types.ModuleType("inspect_ai"))
    monkeypatch.setitem(sys.modules, "inspect_ai.log", log)
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "2026-10-02_support.eval").write_bytes(b"PK\x03\x04 cut")
    code, out = run(capsys, tmp_path / "logs" / "2026-10-02_support.eval")
    assert code == 2, out
    assert ("2026-10-02_support.eval can't be read: it may be cut short, or not an Inspect AI "
            "log. Save it again from Inspect AI.") in out
    assert "Traceback" not in out and "EOCD" not in out


def test_a_header_with_no_rows_says_so(tmp_path, capsys):
    (tmp_path / "results.csv").write_text("input,output,verdict\n", encoding="utf-8")
    code, out = run(capsys, tmp_path / "results.csv")
    assert code == 2 and "results.csv has no rows" in out


def test_a_results_file_elsewhere_names_where_it_saved(tmp_path, capsys, monkeypatch):
    table_project(tmp_path / "elsewhere", split(16, 16))
    (tmp_path / "here").mkdir()
    monkeypatch.chdir(tmp_path / "here")
    ws = start_label.prepare(start.find_judge("../elsewhere/results.csv"), say=print)
    out = capsys.readouterr().out
    assert "Saved in ../elsewhere/.judgekeeper/. It holds your answers' text" in out
    assert start_label.shown_folder(ws) == "../elsewhere/.judgekeeper"
    monkeypatch.chdir(tmp_path / "elsewhere")
    assert start_label.shown_folder(ws) == ".judgekeeper"



def test_a_folder_far_away_is_named_from_here_never_in_full(tmp_path, monkeypatch):
    table_project(tmp_path / "evals", split(16, 16))
    ws = start_label.prepare(start.find_judge(tmp_path / "evals" / "results.csv"), say=print)
    deep = tmp_path / "a" / "b" / "c" / "d"
    deep.mkdir(parents=True)
    monkeypatch.chdir(deep)
    shown = start_label.shown_folder(ws)
    assert shown == "../../../../evals/.judgekeeper"
    assert str(tmp_path) not in shown and tmp_path.as_posix() not in shown


def test_a_folder_on_another_drive_is_named_by_its_name(tmp_path, monkeypatch):
    table_project(tmp_path / "evals", split(16, 16))
    ws = start_label.prepare(start.find_judge(tmp_path / "evals" / "results.csv"), say=print)
    monkeypatch.chdir(tmp_path)

    def other_drive(path, start=None):
        raise ValueError("path is on mount 'D:', start on mount 'C:'")

    monkeypatch.setattr(start_label.os.path, "relpath", other_drive)
    assert start_label.shown_folder(ws) == ".judgekeeper"

@pytest.mark.parametrize("eval_part", ["x", None, [1, 2]])
def test_an_inspect_log_with_a_damaged_eval_part_is_named_as_inspect(tmp_path, capsys,
                                                                      eval_part):
    data = inspect_data(split(10, 10))
    data["eval"] = eval_part
    (tmp_path / "logs").mkdir()
    log = tmp_path / "logs" / "2026-10-13T10-00-00+00-00_quiz_T.json"
    log.write_text(json.dumps(data), encoding="utf-8")
    assert find.classify_file(log) == "inspect"
    code, out = run(capsys, tmp_path)
    assert code == 2, out
    assert ("2026-10-13T10-00-00+00-00_quiz_T.json can't be read: its eval part is damaged. "
            "Save it again from Inspect AI.") in " ".join(out.split())
    assert "promptfoo" not in out


def test_a_damaged_eval_part_is_named_when_inspect_is_installed(tmp_path, capsys,
                                                                monkeypatch):
    def read_eval_log(path):
        raise ValueError("1 validation error for EvalLog")

    log = types.ModuleType("inspect_ai.log")
    log.read_eval_log = read_eval_log
    monkeypatch.setitem(sys.modules, "inspect_ai", types.ModuleType("inspect_ai"))
    monkeypatch.setitem(sys.modules, "inspect_ai.log", log)
    data = inspect_data(split(10, 10))
    data["eval"] = "x"
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "2026-10-13_quiz.json").write_text(json.dumps(data), encoding="utf-8")
    code, out = run(capsys, tmp_path)
    assert code == 2 and "its eval part is damaged" in out, out
    assert "validation" not in out


def test_an_empty_promptfoo_results_file_is_named_not_exported(tmp_path, capsys):
    (tmp_path / "promptfooconfig.yaml").write_text("description: x\n", encoding="utf-8")
    (tmp_path / "results.json").write_bytes(b"")
    code, out = run(capsys, tmp_path)
    assert code == 2, out
    assert "results.json is empty, so judgekeeper can't read it." in out
    assert "`promptfoo eval -o results.json`" in out and "latest" not in out
    assert "no saved results file" not in out.lower() and "own database" not in out


@pytest.mark.skipif(sys.platform == "win32" or os.geteuid() == 0,
                    reason="file permissions: POSIX, not as root")
def test_a_results_file_that_cant_be_read_says_permission_denied(tmp_path, capsys):
    (tmp_path / "promptfooconfig.yaml").write_text("description: x\n", encoding="utf-8")
    results = tmp_path / "results.json"
    results.write_text("{}", encoding="utf-8")
    results.chmod(0)
    try:
        code, out = run(capsys, tmp_path)
    finally:
        results.chmod(0o600)
    assert code == 2, out
    assert "results.json can't be read: permission denied." in out
    assert "give your user permission to read results.json" in out


def test_an_empty_results_file_next_to_good_results_is_left_out(tmp_path, capsys):
    _csv(tmp_path / "results.csv", _rows())
    (tmp_path / "eval_output.json").write_bytes(b"")
    (tmp_path / "notes.json").write_bytes(b"")  # not results by its name: not said
    code, out = run(capsys, tmp_path)
    assert code == 0, out
    assert "eval_output.json is empty, so it was left out." in out
    assert "notes.json" not in out
