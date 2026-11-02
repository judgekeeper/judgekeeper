""""Words found in many of your LLM-as-a-judge's mistakes" names a word only when it is in at
least 3 mistakes and in at least 1 in 10 of them: 4 of 366 is not many."""

from __future__ import annotations

import pytest

from judgekeeper import fix


def _rows(with_word: int, mistakes: int, agreed: int = 400) -> list[dict]:
    wrong = [{"judge": "pass", "final": "fail",
              "output": "Please pick a size." if n < with_word else "A plain answer."}
             for n in range(mistakes)]
    right = [{"judge": "pass", "final": "pass", "output": "A plain answer."}
             for _ in range(agreed)]
    return wrong + right


def _words_line(rows: list[dict]) -> str | None:
    return next((line for line in fix.pattern_lines(rows) if line.startswith("Words found")),
                None)


@pytest.mark.parametrize("with_word, mistakes", [(3, 7), (3, 30), (37, 366)])
def test_a_word_in_one_in_ten_mistakes_or_more_is_named(with_word, mistakes):
    line = _words_line(_rows(with_word, mistakes))
    assert line and f"pick ({with_word})" in line, line


@pytest.mark.parametrize("with_word, mistakes", [(4, 366), (3, 31), (2, 7)])
def test_a_word_in_fewer_is_not_named(with_word, mistakes):
    assert _words_line(_rows(with_word, mistakes)) is None
