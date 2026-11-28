"""`judgekeeper steps a` run from the folder above `a`: `--stop` from that folder closes the
page it opened, as for the answers page, and every line names the files where they are, as
seen from where the command ran. Synthetic runs only; no test calls an AI."""

from __future__ import annotations

import json

import pytest

from judgekeeper.cli import main
from judgekeeper.label import is_open

FLAGS = "--port 0 --no-browser"


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _runs(folder, n=4):
    folder.mkdir(exist_ok=True)
    rows = [{"id": f"r{i}", "task": f"Task {i}",
             "steps": [{"role": "user", "content": f"Ask {i}"},
                       {"role": "assistant", "content": f"Do {i}"}]} for i in range(n)]
    (folder / "runs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows),
                                       encoding="utf-8")


def _out(capsys, *argv):
    code = main(list(argv))
    out, _ = capsys.readouterr()
    return code, " ".join(out.split())


def _opened(here, capsys, folder="a"):
    _runs(here / folder)
    code, out = _out(capsys, "steps", folder, "--port", "0", "--no-browser")
    assert code == 0 and is_open(here / folder / ".judgekeeper"), out
    return out


@pytest.mark.parametrize("argv", [("steps", "--stop"), ("--stop",)])
def test_stop_from_the_folder_above_closes_the_page(here, capsys, argv):
    _opened(here, capsys)
    code, out = _out(capsys, *argv)
    assert code == 0 and "Closed the marking page." in out, out
    assert "No marking page is open." not in out, out
    assert not is_open(here / "a" / ".judgekeeper"), out
    assert f"Next: run `judgekeeper steps a {FLAGS}` when you want to continue." in out, out


def test_stop_from_inside_names_the_runs_from_there(here, capsys, monkeypatch):
    _opened(here, capsys)
    monkeypatch.chdir(here / "a")
    code, out = _out(capsys, "steps", "--stop")
    assert code == 0 and "Closed the marking page." in out, out
    assert f"Next: run `judgekeeper steps runs.jsonl {FLAGS}` when you want to continue." in out
    assert "steps a " not in out, out


def test_stop_with_no_page_below_says_none_is_open(here, capsys):
    _runs(here / "a")
    code, out = _out(capsys, "steps", "--stop")
    assert code == 0 and "No marking page is open." in out, out


def test_the_written_files_are_named_where_they_are(here, capsys):
    out = _opened(here, capsys)
    assert ("Wrote 4 runs for Label Studio to a/.judgekeeper/steps/label-these.json and the "
            "labelling setup to a/.judgekeeper/steps/label-config.xml.") in out, out
    assert " .judgekeeper/steps/" not in out, out
    main(["steps", "a", "--stop"])


def test_from_inside_they_are_named_as_before(here, capsys, monkeypatch):
    _runs(here / "a")
    monkeypatch.chdir(here / "a")
    code, out = _out(capsys, "steps", "runs.jsonl", "--port", "0", "--no-browser")
    assert code == 0, out
    assert ("Wrote 4 runs for Label Studio to .judgekeeper/steps/label-these.json and the "
            "labelling setup to .judgekeeper/steps/label-config.xml.") in out, out
    main(["steps", "--stop"])


def test_with_pages_open_in_two_folders_below_it_says_where(here, capsys):
    _opened(here, capsys, "a")
    _opened(here, capsys, "b")
    code, out = _out(capsys, "steps", "--stop")
    assert code == 3 and "Marking pages are open in a/ and b/." in out, out
    assert is_open(here / "a" / ".judgekeeper") and is_open(here / "b" / ".judgekeeper"), out
    main(["steps", "a", "--stop"])
    main(["steps", "b", "--stop"])


def test_a_project_with_marks_of_its_own_never_closes_one_below(here, capsys):
    _runs(here)
    (here / ".judgekeeper" / "steps").mkdir(parents=True)
    (here / ".judgekeeper" / "steps" / "marks.jsonl").write_text("", encoding="utf-8")
    _opened(here, capsys, "a")
    _, out = _out(capsys, "steps", "--stop")
    assert "No marking page is open." in out and is_open(here / "a" / ".judgekeeper"), out
    main(["steps", "a", "--stop"])
