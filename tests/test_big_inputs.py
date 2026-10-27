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


# Every reader stops at MAX_ROWS answers --------------------------------------------------------

def _said_once(capsys, file: str) -> None:
    err = capsys.readouterr().err
    assert err.count(f"Read the first 3 answers of {file}; the rest are left out.") == 1, err


def test_a_promptfoo_file_is_read_to_the_cap(tmp_path, monkeypatch, capsys):
    from judgekeeper.readers.promptfoo import read_promptfoo
    from tests.start_projects import promptfoo_project

    monkeypatch.setattr(table, "MAX_ROWS", 3)
    path = promptfoo_project(tmp_path, [True, False, True, True, False])
    assert len({r.target_id for r in read_promptfoo(path)}) == 3
    _said_once(capsys, "results.json")


def test_a_deepeval_run_is_read_to_the_cap(tmp_path, monkeypatch, capsys):
    from judgekeeper.readers.deepeval import read_deepeval
    from tests.start_projects import deepeval_project

    monkeypatch.setattr(table, "MAX_ROWS", 3)
    path = deepeval_project(tmp_path, [True, False, True, True, False], name="run.json")
    assert len(read_deepeval(path)) == 3
    _said_once(capsys, "run.json")


@pytest.mark.parametrize("name", ["graded.jsonl", "graded.json", "graded.csv"])
def test_a_file_read_with_a_saved_map_is_read_to_the_cap(tmp_path, monkeypatch, capsys, name):
    import json

    from judgekeeper import mapper
    from judgekeeper.readers.mapped import read_mapped
    from tests.start_projects import flat_jsonl

    monkeypatch.setattr(table, "MAX_ROWS", 3)
    path = flat_jsonl(tmp_path / "graded.jsonl", n=5)
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    path = tmp_path / name
    if name.endswith(".json"):
        path.write_text(json.dumps(rows), encoding="utf-8")
    elif name.endswith(".csv"):
        path.write_text("question,model_answer,grade,explanation\n" + "".join(
            f"{r['question']},{r['model_answer']},{r['grade']},{r['explanation']}\n"
            for r in rows), encoding="utf-8")
    g = mapper.guess(mapper.load(path))
    (_, records), = read_mapped(path, {**g.to_map(), "judge": None, "pass_mark": None})
    assert len(records) == 3
    _said_once(capsys, name)


def test_the_records_folder_is_read_to_the_cap_in_all(tmp_path, monkeypatch, capsys):
    from judgekeeper import find, start
    from tests.start_projects import records_project

    monkeypatch.setattr(table, "MAX_ROWS", 3)
    newer = records_project(tmp_path, [True, False], pid=2, day="2026-10-06")
    older = records_project(tmp_path, [True, True], pid=1, start=2)
    third = records_project(tmp_path, [False, True], pid=0, day="2026-10-04", start=4)
    results = [find.Result("records", p, f".judgekeeper/records/{p.name}", 0)
               for p in (newer, older, third)]
    loaded = start._read_records(start.Talk(), results)
    assert [len(x.records) for x in loaded] == [2, 1]
    out = " ".join(capsys.readouterr().out.split())
    assert out.count("Read the newest 3 records in .judgekeeper/records/; the older ones are "
                     "left out.") == 1, out


# A table holds at most MAX_COLUMNS columns -----------------------------------------------------

def _wide(path, columns: int):
    head = ["input", "output", "verdict"] + [f"c{i}" for i in range(columns - 3)]
    path.write_text(",".join(head) + "\n" + "q,a,pass" + "," * (columns - 3) + "\n",
                    encoding="utf-8")
    return path


def test_a_table_wider_than_the_cap_is_refused_plainly(tmp_path, monkeypatch):
    import json

    from judgekeeper import mapper, records

    monkeypatch.setattr(table, "MAX_COLUMNS", 10)
    assert len(table.read_table(_wide(tmp_path / "ok.csv", 10))) == 1
    wide = _wide(tmp_path / "wide.csv", 11)
    said = "wide.csv has 11 columns; judgekeeper reads tables of up to 10."
    with pytest.raises(table.TableError, match=said):
        table.read_table(wide)
    with pytest.raises(records.RecordsError, match=said):
        records.source_rows(wide)
    with pytest.raises(mapper.MapError, match=said):
        mapper.load_numbered(wide)
    jsonl = tmp_path / "wide.jsonl"
    jsonl.write_text(json.dumps({"input": "q", "output": "a", "verdict": "pass",
                                 **{f"c{i}": "" for i in range(8)}}) + "\n", encoding="utf-8")
    with pytest.raises(table.TableError, match="wide.jsonl has 11 columns"):
        table.read_table(jsonl)
    (_, row, _), = records.source_rows(jsonl)[0]
    assert row == "has 11 fields; judgekeeper reads up to 10", row


def test_find_says_a_table_wider_than_the_cap_is_left_out(tmp_path, monkeypatch):
    from judgekeeper import find
    from tests.start_projects import promptfoo_project

    monkeypatch.setattr(table, "MAX_COLUMNS", 10)
    promptfoo_project(tmp_path, [True, False])
    _wide(tmp_path / "data.csv", 11)
    search = find.search(tmp_path)
    assert list(search.results) == ["promptfoo"]
    assert [(rel, why) for rel, why, *_ in search.bad_tables] == [
        ("data.csv", "has 11 columns (judgekeeper reads up to 10)")]


# Find reads a table whole only when it is small ------------------------------------------------

def test_find_checks_only_tables_within_its_byte_budget(tmp_path, monkeypatch):
    from judgekeeper import find

    checked = []
    real = table.problem
    monkeypatch.setattr(table, "problem", lambda path: checked.append(path.name) or real(path))
    rows = "".join(f"q{i},a{i},pass\n" for i in range(50))
    (tmp_path / "small.csv").write_text("input,output,verdict\n" + rows, encoding="utf-8")
    (tmp_path / "big.csv").write_text("input,output,verdict\n" + rows * 4, encoding="utf-8")
    monkeypatch.setattr(find, "CHECK_BYTES", (tmp_path / "small.csv").stat().st_size + 1)
    search = find.search(tmp_path)
    assert checked == ["small.csv"], checked
    assert sorted(r.rel for r in search.results["table"]) == ["big.csv", "small.csv"]
