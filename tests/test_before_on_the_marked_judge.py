"""A --before after a take-on, on two files graded by the LLM-as-a-judge the marks were made
on: the comparison is all it says. Its grades are not the taken-on LLM-as-a-judge's graded
again, so there is no "got a different grade", no new answers that "wait until your changed
LLM-as-a-judge is checked", and no Next to check it: that check has nothing to do."""

import csv
import os
import re
import shutil

import pytest

from judgekeeper import before_after
from tests.test_compare_after_check import _checked, _flat, _run

BROKE = 8


def _said(capsys, *argv) -> tuple[int, str]:
    code, out = _run(capsys, *argv, "--no-browser", "--port", "0")
    _run(capsys, "--stop")
    return code, _flat(out)


@pytest.mark.parametrize("ids,models", [(True, None), (False, None),
                                         (True, ("judge-old", "judge-new"))],
                         ids=["by-id", "by-text", "named-models"])
def test_a_before_on_the_marked_judges_results_only_compares(tmp_path, monkeypatch, capsys,
                                                             ids, models):
    """`models`: each file names its LLM-as-a-judge (judge_model): results.csv the one the
    marks were made with, new-results.csv the one taken on."""
    _checked(tmp_path, monkeypatch, capsys, ids, models=models)  # took on new-results.csv
    monkeypatch.setenv("CI", "true")
    main = (tmp_path / "results.csv").read_text(encoding="utf-8")
    (tmp_path / "main-results.csv").write_text(main, encoding="utf-8")
    with (tmp_path / "main-results.csv").open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    broke = 0
    for row in rows:  # right answers it passed: new wrong text, and they fail now
        if broke < BROKE and row["verdict"] == "pass":
            a, b = (int(x) for x in row["input"].rstrip("?").split()[2::2])
            if int(row["output"].split()[-1].rstrip(".")) == a + b:
                row["output"] = f"The total of {a} and {b} is maybe {a + b + 2}."
                row["verdict"] = "fail"
                broke += 1
    assert broke == BROKE
    with (tmp_path / "results.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    later = (tmp_path / "new-results.csv").stat().st_mtime + 60  # changed after the check
    os.utime(tmp_path / "results.csv", (later, later))
    kept = {n: (tmp_path / ".judgekeeper" / n).read_bytes() for n in ("pool.jsonl", "marks.jsonl")}
    code, out = _said(capsys, "results.csv", "--before", "main-results.csv")
    assert kept == {n: (tmp_path / ".judgekeeper" / n).read_bytes() for n in kept}  # nothing moved
    assert code == 1 and f"fixed 0, broke {BROKE}," in out, out
    assert "wait until" not in out and "got a different grade" not in out, out
    assert "re-check your changed LLM-as-a-judge" not in out, out
    assert "changed since your marks" not in out, out
    assert "check results.csv" not in out, out  # its LLM-as-a-judge is the one marked with
    # the broken answers are new: not added under the judge taken on, and said so once
    assert out.count(f"{BROKE} new answers in results.csv are not added for marking") == 1, out
    assert "Next: nothing to do." in out, out  # the project's: a --before moves nothing


@pytest.mark.parametrize("models", [None, ("judge-old", "judge-new")], ids=["unnamed", "named"])
def test_naming_the_marked_judges_file_right_after_a_take_on_is_one_story(
        tmp_path, monkeypatch, capsys, models):
    """Right after a check took on new-results.csv, `judgekeeper results.csv` goes back to the
    LLM-as-a-judge the marks were made with: that is the story, never also "Your
    LLM-as-a-judge setup changed since the last results"."""
    _checked(tmp_path, monkeypatch, capsys, True, models=models)
    monkeypatch.setenv("CI", "true")
    code, out = _said(capsys, "results.csv")
    assert code == 0 and "back to the one you marked with" in out, out
    assert before_after.RESTARTED not in out, out
    assert "changed since your marks" not in out, out


def _numbers(out: str) -> list[str]:
    """The result's own numbers: the verdict, the disagreements and the two counts."""
    found = re.findall(r"Result: [^.]*\.|disagreed on \d+ of \d+ answers|You (?:passed|failed) "
                       r"\d+ answers\. Of those, your LLM-as-a-judge passed \d+ and failed \d+",
                       out)
    assert len(found) == 4, out
    return found


@pytest.mark.parametrize("ids,models", [(True, None), (False, None),
                                         (True, ("judge-old", "judge-new"))],
                         ids=["by-id", "by-text", "named-models"])
def test_a_before_after_a_take_on_measures_the_file_it_names(tmp_path, monkeypatch, capsys,
                                                             ids, models):
    """After a check took on new-results.csv, `results.csv --before main-results.csv` gives
    results.csv's own result (its grades against the marks), as a plain run on it does, and
    the project still uses the LLM-as-a-judge taken on: start.json is not changed."""
    here = tmp_path / "p"
    here.mkdir()
    _checked(here, monkeypatch, capsys, ids, models=models)  # took on new-results.csv
    monkeypatch.setenv("CI", "true")
    shutil.copy(here / "results.csv", here / "main-results.csv")
    plain = tmp_path / "plain"
    shutil.copytree(here, plain)
    kept = {n: (here / ".judgekeeper" / n).read_bytes()
            for n in ("start.json", "judge.json", "result.json")}
    code, out = _said(capsys, "results.csv", "--before", "main-results.csv")
    assert kept == {n: (here / ".judgekeeper" / n).read_bytes() for n in kept}, out
    assert code == 0 and "fixed 0, broke 0, same" in out, out
    assert "about results.csv" in out, out  # whose numbers they are
    monkeypatch.chdir(plain)
    _, alone = _said(capsys, "results.csv")
    assert "back to the one you marked with" in alone and "needs work" in alone, alone
    assert _numbers(out) == _numbers(alone), (out, alone)
