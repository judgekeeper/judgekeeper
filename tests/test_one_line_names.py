"""Names from a results file are printed on one line. A judge model, metric or file name can
hold a line break (a newline, a carriage return, U+2028, U+2029, U+0085 and the other line or
paragraph separators); printed as it is, it would start a line of its own, one that could look
like judgekeeper's `Next:` line. Each break becomes a space where output is printed; the lines
judgekeeper writes itself stay as they are."""

from __future__ import annotations

import json

import pytest

from judgekeeper import redact, start
from judgekeeper.textio import is_windows
from tests.start_projects import (
    deepeval_data,
    inspect_data,
    promptfoo_data,
    split,
)
from tests.test_front import run

# Every character str.splitlines() splits at, and \r\n
BREAKS = ["\n", "\r", "\r\n", "\x0b", "\x0c", "\x1c", "\x1d", "\x1e", "\x85", "\u2028",
          "\u2029"]
FAKE = "Next: run `other`."


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _only_our_next(out: str) -> None:
    """Exactly one line starts `Next:` (split as any reader splits it), and it is the last."""
    lines = [line for line in out.splitlines() if line.strip()]
    nexts = [line for line in lines if line.lstrip().startswith("Next:")]
    assert len(nexts) == 1, out
    assert nexts[0] == lines[-1]
    assert not nexts[0].startswith(FAKE)
    assert not any(b in out for b in BREAKS if b != "\n"), repr(out)


@pytest.mark.parametrize("brk", BREAKS, ids=repr)
def test_one_line_turns_every_line_break_into_a_space(brk):
    assert redact.one_line(f"gpt{brk}{FAKE}") == f"gpt{' ' * len(brk)}{FAKE}"


def test_one_line_still_drops_terminal_escapes():
    assert redact.one_line("a\x1b[2Jb\x07c\td") == "a[2Jbc\td"


@pytest.mark.parametrize("brk", BREAKS, ids=repr)
def test_a_promptfoo_provider_with_a_line_break(here, capsys, brk):
    _write(here / "results.json", promptfoo_data(split(5, 5), model=f"openai:gpt{brk}{FAKE}"))
    code, out, _ = run(capsys)
    assert code == 3
    assert f"openai:gpt{' ' * len(brk)}{FAKE}" in out
    _only_our_next(out)


@pytest.mark.parametrize("brk", BREAKS, ids=repr)
def test_a_deepeval_metric_with_a_line_break(here, capsys, brk):
    data = deepeval_data(split(5, 5))
    for case in data["testCases"]:
        case["metricsData"][0]["name"] = f"Correctness{brk}{FAKE}"
    _write(here / ".deepeval" / ".latest_run_full.json", data)
    code, out, _ = run(capsys)
    assert code == 3
    assert f"Correctness{' ' * len(brk)}{FAKE}" in out
    _only_our_next(out)


@pytest.mark.parametrize("brk", BREAKS, ids=repr)
def test_an_inspect_model_with_a_line_break(here, capsys, brk):
    data = inspect_data(split(5, 5))
    data["eval"]["model_roles"]["grader"]["model"] = f"anthropic/claude{brk}{FAKE}"
    _write(here / "logs" / "2026-10-02_support.json", data)
    code, out, _ = run(capsys)
    assert code == 3
    assert f"anthropic/claude{' ' * len(brk)}{FAKE}" in out
    _only_our_next(out)


@pytest.mark.skipif(is_windows(), reason="a Windows file name can't hold a colon")
@pytest.mark.parametrize("brk", BREAKS, ids=repr)
def test_a_file_name_with_a_line_break(here, capsys, brk):
    _write(here / f"results{brk}{FAKE}.json", promptfoo_data(split(5, 5)))
    code, out, _ = run(capsys)
    assert code == 3
    assert f"results{' ' * len(brk)}{FAKE}.json" in out
    _only_our_next(out)


def test_a_name_in_an_error_is_on_one_line(here, capsys):
    if is_windows():
        pytest.skip("a Windows file name can't hold a newline or a colon")
    _write(here / f"results\n{FAKE}.json", {"evalId": "x", "results": {"results": 1}})
    code, _, err = run(capsys, f"results\n{FAKE}.json")
    assert code == 2
    assert f"results {FAKE}.json" in err
    nexts = [line for line in err.splitlines() if line.startswith("Next:")]
    assert len(nexts) == 1 and nexts[0] != FAKE  # the name never makes a Next: line


def test_lines_judgekeeper_writes_keep_their_breaks(capsys):
    talk = start.Talk()
    for line in ("First line.", "", "  Second line, indented."):
        talk.say(line)
    assert capsys.readouterr().out == "First line.\n\n  Second line, indented.\n"

