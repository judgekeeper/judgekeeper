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


@pytest.fixture(autouse=True)
def no_labeling(monkeypatch):
    calls = []

    def run_labeling(found, port, open_browser, say, command="judgekeeper start"):
        calls.append(found)
        say("(labeling page)")
        return 0

    monkeypatch.setattr(start_label, "run_labeling", run_labeling)
    return calls


def run(capsys, *argv):
    code = main(["start", *map(str, argv), "--yes"])
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


def test_a_cell_longer_than_131072_characters_is_read(tmp_path, capsys):
    _csv(tmp_path / "results.csv", _rows(long_output="x" * 140_000))  # a RAG context, say
    code, out = run(capsys, tmp_path)
    assert code == 0 and "  Its decisions   32 answers: 16 passed, 16 failed" in out, out


def test_a_jsonl_table_with_a_first_line_over_64_kb_is_a_table(tmp_path, capsys):
    rows = _rows(long_output="y" * 70_000)
    (tmp_path / "results.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    assert find.classify_file(tmp_path / "results.jsonl") == "table"
    code, out = run(capsys, tmp_path)
    assert code == 0 and "  Eval tool       a table (results.jsonl)" in out, out


def test_a_log_that_cant_be_read_never_hides_a_good_one(tmp_path, capsys):
    logs = tmp_path / "logs"
    logs.mkdir()
    good = logs / "2026-10-01_support.json"
    good.write_text(json.dumps(inspect_data(split(16, 16))), encoding="utf-8")
    cut = logs / "2026-10-02_support.json"
    cut.write_text(json.dumps(inspect_data(split(16, 16)))[:500], encoding="utf-8")
    os.utime(cut, (good.stat().st_atime + 60, good.stat().st_mtime + 60))
    code, out = run(capsys, tmp_path)
    assert code == 0, out
    assert "is left out." in out and "  Its decisions   32 answers" in out


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


def test_a_utf16_export_gets_the_save_as_utf8_advice(tmp_path, capsys):
    text = "input,output,verdict\n" + "".join(f"q{i},a{i},pass\n" for i in range(4))
    (tmp_path / "results.csv").write_bytes(text.encode("utf-16"))
    code, out = run(capsys, tmp_path / "results.csv")
    assert code == 2
    assert 'results.csv is not saved as UTF-8 text, so it cannot be read. In Excel' in out
    code, out = run(capsys, tmp_path)  # the folder search says it too
    assert "results.csv is not saved as UTF-8 text" in out


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


@pytest.mark.parametrize("values, said", [
    (["✓", "✗"], ("judgekeeper can't tell which of these values mean Pass and Fail: ✓, ✗. "
                  'Map them with --label-map "✓=pass,✗=fail", whichever each one means.')),
    (["0.9", "0.1"], ("Your judge's decisions are numbers (0.9, 0.1): say which scores pass "
                      'with --pass-if, e.g. --pass-if "score>=0.5"')),
])
def test_decisions_it_cant_read_are_said_plainly(tmp_path, capsys, values, said):
    rows = [{"input": f"q{i}", "output": f"a{i}", "verdict": values[i % 2]} for i in range(32)]
    _csv(tmp_path / "results.csv", rows)
    code, out = run(capsys, tmp_path)
    assert code == 2 and said in out, out
    assert "Its decisions" not in out and "verdict values" not in out
