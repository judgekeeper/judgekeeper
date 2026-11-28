"""How a file is read is not how it is graded: a table whose output column was renamed (read
with a saved map from then on) is graded by the same LLM-as-a-judge. Its answers compare as
before, the same texts under a new column name. A rename with 10 real regressions read as
"Your LLM-as-a-judge setup changed ... new starting point", exit 0."""

import csv

from judgekeeper import before_after
from tests.test_compare_after_check import _flat, _run

N = 40
FLIP = [i for i in range(N) if i % 2][:10]  # 10 passing answers


def _said(capsys, *argv) -> tuple[int, str]:
    code, out = _run(capsys, *argv, "--no-browser", "--port", "0")
    _run(capsys, "--stop")
    return code, _flat(out)


def _table(here, column: str = "output", broke: bool = False, regraded: bool = False) -> None:
    """id,input,<column>,app_version,verdict. `broke`: the FLIP answers are new and fail;
    `regraded`: they keep their text and fail."""
    with (here / "results.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "input", column, "app_version", "verdict"])
        for i in range(N):
            flip = (broke or regraded) and i in FLIP
            w.writerow([f"q-{i:02}", f"Question {i}?",
                        f"Answer {i}." + (" Guessed." if broke and flip else ""), "1.0",
                        "fail" if flip or i % 2 == 0 else "pass"])


def test_a_renamed_output_column_with_regressions_is_compared(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CI", "true")
    _table(tmp_path)
    assert _said(capsys)[0] == 0
    _table(tmp_path, "response", broke=True)
    code, out = _said(capsys, "--yes")
    assert code == 1 and "On the 40 questions in both results: fixed 0, broke 10," in out, out
    assert before_after.RESTARTED not in out, out


def test_a_renamed_output_column_with_only_grades_changed_is_only_grades(tmp_path,
                                                                           monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CI", "true")
    _table(tmp_path)
    assert _said(capsys)[0] == 0
    _table(tmp_path, "response", regraded=True)
    code, out = _said(capsys, "--yes")
    assert code == 0 and before_after.ONLY_GRADES in out, out


def test_marks_made_before_a_rename_still_count(tmp_path, monkeypatch, capsys):
    """The marks made on the answers read by column names are the same answers' marks once a
    column is renamed: the same result, never "Your marks are for another LLM-as-a-judge"."""
    import json

    from judgekeeper.start_label import StartSession, Workspace

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CI", raising=False)
    _table(tmp_path)
    _said(capsys)
    ws = Workspace(tmp_path)
    pool = {json.loads(line)["id"]: json.loads(line)["output"]
            for line in ws.pool.read_text(encoding="utf-8").splitlines() if line.strip()}
    session = StartSession(ws)
    for item in session.items:  # odd answers right, even ones wrong: the LLM-as-a-judge agrees
        i = int(pool[item["id"]].split()[1].rstrip("."))
        session.update({"id": item["id"], "label": "pass" if i % 2 else "fail", "seconds": 5})
    code, before = _said(capsys)
    agreed = "You and your LLM-as-a-judge agreed on all 40 answers."
    assert agreed in before, before
    _table(tmp_path, "response")
    code2, after = _said(capsys, "--yes")
    assert "Your marks are for another" not in after, after
    assert code2 == code and agreed in after, after
