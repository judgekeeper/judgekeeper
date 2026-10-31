"""After `check` takes on a new rule from a file that grades only the marked answers, the other
answers keep the grade of the LLM-as-a-judge before it. Marks made on them later are never
compared with that grade, in `fix`, `fix <file>` or `check`."""

from __future__ import annotations

import json
import re

import pytest

from judgekeeper import fix
from judgekeeper.check import EARLIER as CHECK_EARLIER
from judgekeeper.start_label import StartSession, Workspace
from tests.test_fix import closed
from tests.test_flow_across_runs import _jk, _rubric
from tests.test_front import flat

N = 60
WRONG = set(range(12)) | set(range(30, 42))  # the first rule passes i < 30, wrong on these
FIRST = [i for i in range(N) if 6 <= i < 26 or 36 <= i < 56]  # 12 of its mistakes
LATER = [i for i in range(N) if i not in FIRST]  # 20 with the other 12, marked after it


def person(i: int) -> bool:
    return (i >= 30) if i in WRONG else (i < 30)


def _mark(ws: Workspace, which: list[int]) -> None:
    session = StartSession(ws)
    for item in session.items:
        i = int(re.search(r"Question (\d+)\?", json.dumps(session.raw[item["id"]]["input"]))[1])
        if i in which and not item["label"]:
            session.update({"id": item["id"], "label": "pass" if person(i) else "fail",
                            "seconds": 5})


@pytest.fixture
def adopted(tmp_path, monkeypatch, capsys):
    """V1 marked on FIRST, V2 tested on them and taken on by `check` from a file of the marked
    answers only, then LATER marked: (workspace, capsys)."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "promptfooconfig.yaml").write_text("description: support bot\n",
                                                  encoding="utf-8")
    _rubric(tmp_path, [i < 30 for i in range(N)], "V1 rule.")
    assert _jk(capsys, "--no-browser")[0] == 0
    ws = Workspace(tmp_path)
    closed(ws)
    _mark(ws, FIRST)
    assert _jk(capsys, "fix")[0] == 0
    _rubric(tmp_path, [person(i) for i in range(N)], "V2 rule.", name="v2.json", only=FIRST)
    code, out = _jk(capsys, "fix", "v2.json")
    assert code == 0 and "Result: your new rule is better." in out, out
    assert _jk(capsys, "check", "v2.json")[0] == 0
    assert sorted(ws.data()["earlier_grades"]) == sorted(
        i["id"] for i in StartSession(ws).items if not i["label"])
    _mark(ws, LATER)
    return ws, capsys


def test_the_unchanged_rule_on_marks_made_after_a_check_is_not_better(adopted, tmp_path):
    ws, capsys = adopted
    assert _jk(capsys, "fix")[0] == 0  # the marks made after the check are the new set
    split = fix.read_split(ws)
    assert split.set == 2 and len(split.hidden) == len(LATER)
    _rubric(tmp_path, [person(i) for i in range(N)], "V2 rule.", name="same.json", only=LATER)
    code, out = _jk(capsys, "fix", "same.json")
    said = flat(out)
    assert code == 3 and "better" not in said, out
    assert fix.TOOK.format(k=len(LATER)) in said
    assert "earlier_grades" not in ws.data()  # its grades now
    _rubric(tmp_path, [person(i) != (i == 56) for i in range(N)], "V3 rule.", name="v3.json",
            only=LATER)
    code, out = _jk(capsys, "fix", "v3.json")  # a new rule, tested on the right grades
    assert code == 0, out
    assert "    When you say Pass: agrees on 10 of 10" in out, out
    assert "    When you say Fail: agrees on 10 of 10" in out, out


def test_a_new_rule_leaves_out_the_answers_with_an_earlier_grade(adopted, tmp_path):
    _, capsys = adopted
    _jk(capsys, "fix")
    _rubric(tmp_path, [person(i) for i in range(N)], "V3 rule.", name="v3.json", only=LATER)
    code, out = _jk(capsys, "fix", "v3.json")
    said = flat(out)
    assert code == 3 and "better" not in said, out
    assert fix.EARLIER.format(k=20, n=20, have="have", them="them") in said
    assert said.endswith("Next: " + fix.NEXT_EARLIER.format(
        answers=".judgekeeper/fix/marked-answers.csv", command="judgekeeper fix"))


def test_no_grade_on_an_answer_with_an_earlier_grade_is_left_out_too(adopted, tmp_path):
    """Never counted as the new rule's mistake against another judge's grade: left out with
    the others."""
    _, capsys = adopted
    _jk(capsys, "fix")
    _rubric(tmp_path, [person(i) for i in range(N)], "V3 rule.", name="v3.json", only=LATER)
    data = json.loads((tmp_path / "v3.json").read_text(encoding="utf-8"))
    for row in data["results"]["results"][:5]:
        row["gradingResult"]["componentResults"][0].update(
            {"pass": False, "score": 0, "reason": "API error: 429 rate limited",
             "metadata": {"graderError": True}})
        row["success"] = row["gradingResult"]["pass"] = False
    (tmp_path / "v3.json").write_text(json.dumps(data), encoding="utf-8")
    code, out = _jk(capsys, "fix", "v3.json")
    said = flat(out)
    assert code == 3 and "better" not in said and "mistake" not in said, out
    assert fix.EARLIER.format(k=20, n=20, have="have", them="them") in said
    assert said.endswith("Next: " + fix.NEXT_EARLIER.format(
        answers=".judgekeeper/fix/marked-answers.csv", command="judgekeeper fix"))


def test_check_leaves_earlier_grades_out_of_its_table(adopted, tmp_path):
    _, capsys = adopted
    _rubric(tmp_path, [person(i) for i in range(N)], "V3 rule.", name="all.json")
    code, out = _jk(capsys, "check", "all.json")
    said = flat(out)
    assert code == 0, out
    assert "When you said Pass 20 of 20 20 of 20" in said  # V2 was right on every one it graded
    assert "When you said Fail 20 of 20 20 of 20" in said
    assert CHECK_EARLIER.format(k=20, have="have", them="them") in said


def test_plain_fix_shows_no_mistake_of_an_earlier_judge(adopted):
    ws, capsys = adopted
    _jk(capsys, "fix", "--new")  # every mark seen
    md = (ws.dir / "fix" / "mistakes.md").read_text(encoding="utf-8")
    assert not any(f"Question {i}?" in md for i in LATER)  # the first rule's mistakes
    assert fix.where_wrong(ws)[1] == 0


# The new set's answers are in marked-answers.csv ----------------------------------------------

def test_a_new_set_writes_marked_answers_csv_again(adopted):
    ws, capsys = adopted
    code, out = _jk(capsys, "fix")  # nothing to fix on the marks seen; the new set is made
    split = fix.read_split(ws)
    assert code == 0 and split.set == 2, out
    rows = (ws.dir / "fix" / "marked-answers.csv").read_text(encoding="utf-8")
    assert all(f"Question {i}?" in rows for i in LATER)  # the answers the new set needs
    said = flat(out)
    assert "20 of your marks are kept aside to test your new rule fairly." in said
    assert said.endswith("then run `judgekeeper fix <new results file>`.")
    assert ".judgekeeper/fix/marked-answers.csv" in said[said.rindex("Next:"):]
