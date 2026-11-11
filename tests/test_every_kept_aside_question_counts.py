"""What changed since the last answers is counted per question kept aside, every one of them:
a question asked more than once is one question (Fail if any copy failed), and a question
whose answer did not change keeps its mark and counts as the same. Fixed: any Fail before,
all Pass now. Broke: all Pass before, any Fail now. Else the same."""

from __future__ import annotations

import csv
import json

import pytest

from judgekeeper import no_grades, start_label
from tests.test_answers_without_grades import _session
from tests.test_front import flat, run


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _q(i: int) -> str:
    return f"What is question {i}?"


class Rows:
    """Answers, each (question number, answer text), marked by their text."""

    def __init__(self, here, capsys):
        self.here, self.capsys, self.rows, self.marks = here, capsys, [], {}

    def write(self) -> None:
        with (self.here / "results.csv").open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["input", "output"])
            w.writeheader()
            w.writerows({"input": _q(q), "output": a} for q, a in self.rows)

    def run(self) -> str:
        code, out, err = run(self.capsys, "--no-browser")
        assert code == 0, out + err
        return flat(out)

    def mark(self) -> None:
        page = _session(self.here)
        for item in page.items:
            m = self.marks.get(page.raw[item["id"]]["output"])
            if m and not item["label"]:
                page.update({"id": item["id"], "label": m, "seconds": 3})

    def round(self, rows: list[tuple[int, str, str]]) -> str:
        """The results now: (question, answer, its mark) each; the answers marked, then run."""
        self.rows = [(q, a) for q, a, _ in rows]
        self.marks |= {a: m for _, a, m in rows}
        self.write()
        self.run()
        self.mark()
        return self.run()

    def kept(self) -> set[int]:
        split, page = no_grades.read_split(start_label.Workspace(self.here)), _session(self.here)
        return {int(page.raw[i]["input"].split()[-1].rstrip("?")) for i in split.hidden}

    def since(self) -> dict:
        ws = start_label.Workspace(self.here)
        return json.loads(ws.result_json.read_text(encoding="utf-8"))["since"]


@pytest.fixture
def rows(here, capsys, pages):
    return Rows(here, capsys)


def _first(n: int = 20, fails: frozenset = frozenset(range(8)), twice=()) -> list:
    out = [(i, f"First answer {i}.", "fail" if i in fails else "pass") for i in range(n)]
    for q, marks in twice:  # a question asked twice: one more copy, marked so
        out = [r for r in out if r[0] != q]
        out += [(q, f"First answer {q}, copy {c}.", m) for c, m in enumerate(marks)]
    return out


def test_a_question_asked_twice_counts_once_by_its_fail(rows):
    first = _first(twice=[(q, ("pass", "fail")) for q in range(0, 20, 2)])
    rows.round(first)
    sky = min(q for q in rows.kept() if q % 2 == 0)  # {Pass, Fail}: a Fail before
    again = [(q, a.replace("First", "Second"), m) for q, a, m in first]
    again = [(q, a, "fail" if q == sky else m) for q, a, m in again]  # {Fail, Fail}
    rows.round(again)
    since = rows.since()
    assert since["kept"] == len(rows.kept())
    assert since["broke"] == 0 and since["fixed"] == 0  # Fail before, Fail after: the same


def test_all_pass_then_one_copy_failing_is_broke(rows):
    first = _first(twice=[(q, ("pass", "pass")) for q in range(10, 20)])
    rows.round(first)
    q = min(q for q in rows.kept() if q >= 10)  # {Pass, Pass}
    again = [(i, a.replace("First", "Second"), m) for i, a, m in first]
    copies = [r for r in again if r[0] == q]
    again = [r for r in again if r[0] != q] + [copies[0], (q, copies[1][1], "fail")]
    rows.round(again)
    since = rows.since()
    assert since["broke"] == 1 and since["kept"] == len(rows.kept())


def test_an_unchanged_kept_aside_answer_counts_as_the_same(rows):
    first = _first()
    said = rows.round(first)
    kept = sorted(rows.kept())
    unchanged = kept[0]
    again = [(q, a if q == unchanged else a.replace("First", "Second"), m)
             for q, a, m in first]
    said = rows.round(again)
    since = rows.since()
    assert since["kept"] == len(kept)
    assert since["fixed"] + since["broke"] + since["same"] == len(kept)
    assert f"On the {len(kept)} questions kept aside:" in said, said
    assert (f"Counted on the {len(kept)} questions kept aside"
            in " ".join(_report(rows.here).split()))


def _report(here) -> str:
    from tests.test_answers_without_grades import _seen

    return _seen(start_label.Workspace(here).report_html.read_text(encoding="utf-8"))
