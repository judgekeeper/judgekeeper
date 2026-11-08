"""With exact numbers (an LLM-as-a-judge that gave every answer one grade), there is no range to
narrow: too early to tell says so without "narrow the ranges"."""

from __future__ import annotations

from judgekeeper import start_label
from tests.start_projects import answer
from tests.test_labels_import import flat, here, run, table, write_labels  # noqa: F401


def test_too_early_with_exact_numbers_does_not_ask_to_narrow_ranges(here, capsys):  # noqa: F811
    table(here, 30, 0)  # it passed all 30
    write_labels(here / "labels.csv", [{"answer": answer(i), "label": "fail" if i < 2 else "pass"}
                                       for i in range(10)])
    _, out = run(capsys, "--labels", "labels.csv")
    said = flat(out)
    assert "too early to tell" in said.lower(), said
    assert "100%" in said and "0%" in said, said
    assert start_label.NARROW not in said, said
    assert "Mark at least" in said, said  # the marks-from-a-file gate stays
    page = flat((here / ".judgekeeper" / "report.html").read_text(encoding="utf-8"))
    assert "too early to tell" in page.lower() and start_label.NARROW not in page
