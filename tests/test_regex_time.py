"""No text makes a regex take long: a name of backslashes in a config, spaces after a verdict
marker in a reason, and whitespace round a number in a records file each take a few
milliseconds, however long they are (a regex with two ways to match the same text takes time
that grows with the square of its length)."""

from __future__ import annotations

import time

import pytest

from judgekeeper import judge_check, keys, records


def _quick(read, text):
    start = time.perf_counter()
    found = read(text)
    assert time.perf_counter() - start < 0.05
    return found


@pytest.mark.parametrize("end", ["", "x", '"', '" x'])
def test_a_name_of_60_kb_of_backslashes_is_read_at_once(end):
    assert _quick(keys._credentials_in, 'env:\n  "' + "\\" * 60_000 + end) == {}


@pytest.mark.parametrize("end", ["", "x", "maybe"])
def test_32_kb_of_spaces_after_a_verdict_marker_is_read_at_once(end):
    assert _quick(judge_check.stated_decisions, "verdict:" + " " * 32_000 + end) == []


@pytest.mark.parametrize(("text", "number"), [
    (" " * 20_000 + "1" + " " * 20_000, True),
    (" " * 20_000 + "1" + " " * 20_000 + "x", False),
    ("\t\n " * 13_000 + "x", False),
    (" " * 40_000, True),
])
def test_40_kb_of_whitespace_round_a_number_is_read_at_once(text, number):
    assert _quick(records._is_number, text) is number


@pytest.mark.parametrize("line", ["A_TOKEN:" + "\t" * 20_000 + "x",
                                  "A_TOKEN: |" + " " * 20_000 + "x"])
def test_a_long_line_after_a_credential_name_is_read_at_once(line):
    assert list(_quick(keys._credentials_in, line)) == ["A_TOKEN"]  # found, to be hidden


@pytest.mark.parametrize("text", ["\n" * 20_000 + "x", "A=1\n" + " \n" * 10_000])
def test_a_dotenv_file_of_blank_lines_is_read_at_once(tmp_path, text):
    path = tmp_path / ".env"
    path.write_text(text, encoding="utf-8")
    names = _quick(keys.names_in, path)
    assert names == ({"A"} if text.startswith("A=") else set())


def test_a_pass_if_of_spaces_is_read_at_once():
    from judgekeeper.normalise import NormaliseError, parse_pass_if

    start = time.perf_counter()
    with pytest.raises(NormaliseError):
        parse_pass_if(" " * 20_000 + "x")
    assert time.perf_counter() - start < 0.05
    assert parse_pass_if("  score >= 0.5 ").threshold == 0.5


def test_a_long_deepeval_model_name_is_read_at_once():
    from judgekeeper.readers.deepeval import provider_of

    assert _quick(provider_of, "gpt" + " " * 20_000 + "x") == "openai"
    assert provider_of("claude-sonnet-5-5 (Anthropic) ") == "anthropic"


@pytest.mark.parametrize("end", ["", "x"])  # x: a rule edited by hand in start.json
def test_a_long_pass_mark_is_written_at_once(end):
    from judgekeeper.start_fix import where_lines

    rule = "score>=" + "1" * 2_000 + end
    lines = _quick(lambda r: where_lines({"source": "pass_if", "rule": r}, 0.5), rule)
    assert lines == [f'Use --pass-if "{"score>=0.5" if not end else rule}".']


def test_20_kb_of_spaces_is_wrapped_at_once():
    from judgekeeper.textio import wrap

    assert " ".join(_quick(wrap, "a" + " " * 20_000 + "b")).split() == ["a", "b"]
