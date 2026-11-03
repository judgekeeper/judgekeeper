"""Notes reference.md keeps: the label map is the project's one map, a result can go back to
too early, and which pool the "how many marks" figures are for."""

from __future__ import annotations

from pathlib import Path

REFERENCE = (Path(__file__).parent.parent / "docs" / "reference.md").read_text(encoding="utf-8")


def _flat(text: str) -> str:
    return " ".join(text.split())


def test_the_label_map_given_with_labels_also_reads_the_grades():
    assert ("A map given with `--labels` is this same map: it is saved for the project and "
            "also reads your LLM-as-a-judge's grades") in _flat(REFERENCE)


def test_a_result_can_go_back_to_too_early():
    assert ("As you mark, the result can go back from good enough to too early, and come back "
            "again; the latest result is the one that counts.") in _flat(REFERENCE)


def test_the_marks_figures_say_which_pool_they_are_for():
    fixing = _flat(REFERENCE[REFERENCE.index("**How many marks:**"):])
    assert ("These figures are for an LLM-as-a-judge that passes half or 80% of the answers. "
            "One that passes more of them needs more marks for the same answer.") in fixing
    # the Guide's line on how many marks moved here, split in two sentences
    assert ("A rule that fixes 9 in 10 of your LLM-as-a-judge's mistakes or a quarter of them, "
            "and breaks at most 2 in 100 right answers, usually gets a clear answer from about "
            "80 marks.") in fixing
    assert ("A rule that breaks 5 in 100 right answers gets a clear answer from about 160 "
            "marks, whether it fixes 1 in 10 of the mistakes or a quarter of them.") in fixing
