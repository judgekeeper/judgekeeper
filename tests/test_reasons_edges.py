"""The reasons and the screens around them: an own button
renamed on every answer, reasons for the other side, a mark changed and changed back, overlapping marked parts, the mark command said three times, a
program that sends no `seconds`, the old pre-commit line, and Ctrl-C under `python -m`. Every
fixture here is made up.
"""

from __future__ import annotations

import subprocess
import sys

from judgekeeper import label, marks, reasons, start_label, textio
from tests.test_fix import N, project
from tests.test_fix import run as run_fix
from tests.test_front import assert_one_next_at_the_end
from tests.test_reasons import _ready, _run, _say, here, served  # noqa: F401

# Editing one answer's "Other…" box never renames the button on another answer ----------

def test_editing_a_note_keeps_the_button_another_answer_tapped(here, capsys):  # noqa: F811
    ws, passes, _, _ = _ready(here)
    _say(ws, passes[0], reasons=[], note="too long for a chat reply")
    button = reasons.own_chips(ws)[0]["id"]
    _say(ws, passes[1], reasons=[button])
    _say(ws, passes[0], reasons=[], note="too wordy")
    texts = {c["id"]: c["text"] for c in reasons.own_chips(ws)}
    assert texts[button] == "too long for a chat reply"
    assert sorted(texts.values()) == ["too long for a chat reply", "too wordy"]
    _, out = run_fix(capsys)
    flat = " ".join(out.split())
    assert "“too long for a chat reply” (1)" in flat and "“too wordy” (1)" in flat, flat
    assert "“too wordy” (2)" not in flat


# A reason asked only on the other side is refused ----------------------------------------

def test_a_reason_for_the_other_side_is_refused(here, served):  # noqa: F811
    ws, passes, fails, _ = _ready(here)
    client = served(ws)
    status, body = client.label(id=fails[0], reasons=["wrong_fact"])  # you Pass, judge Fail
    assert status == 400 and "wrong_fact" in body["error"]
    status, body = client.label(id=passes[0], reasons=["short_ok"])  # you Fail, judge Pass
    assert status == 400 and "short_ok" in body["error"]
    assert "reasons" not in marks.read(ws.marks).last[fails[0]]
    assert "reasons" not in marks.read(ws.marks).last[passes[0]]
    status, _ = client.label(id=fails[0], reasons=["short_ok", "rule_silent"])
    assert status == 200


# A mark changed and changed back is not "changed after seeing the grades" ---------------

def test_a_mark_changed_and_changed_back_is_not_counted(here):  # noqa: F811
    ws, passes, fails, _ = _ready(here)  # the person failed passes[0] and passed fails[0]
    _say(ws, passes[0], label="pass", seconds=4)
    _say(ws, passes[0], label="fail", seconds=4)  # back to the first mark
    _say(ws, fails[0], label="fail", seconds=4)
    made = marks.made(marks.read(ws.marks))
    assert made["after_result"] == 1
    assert "You changed 1 mark after seeing your LLM-as-a-judge's grades." in start_label.made_lines(made)


# Overlapping marked parts are joined in suggestions.md -----------------------------------

def test_overlapping_marked_parts_are_joined_in_suggestions_md():
    text = "ZQOUT16 Fact sixteen is correct."
    row = {"id": "a1", "judge": "pass", "final": "fail", "output": text, "reasons": [],
           "words": {}, "parts": [], "spans": [[2, 5], [3, 9], [10, 12]], "why": ""}
    md = reasons.suggestions_md([row])
    assert f"The part you marked: “{text[2:9]}”" in md
    assert f"The part you marked: “{text[10:12]}”" in md
    assert md.count("The part you marked:") == 2


# With the page closed, Measure names the mark command once ------------------------------

def test_measure_with_the_page_closed_names_the_mark_command_once(here, capsys, pages,  # noqa: F811
                                                                  no_browser):
    project(here, marked=N - 4)  # a result with disagreements, answers left, the page closed
    for _ in range(2):  # the second time with the reasons asked on the result page
        code, out = _run(capsys)
        assert code == 0, out
        assert "You and your LLM-as-a-judge disagreed on" in out, out
        assert " ".join(out.split()).count("`judgekeeper mark`") == 1, out
        assert_one_next_at_the_end(out)


def test_the_page_is_closed_when_stop_misses_it_once(here, monkeypatch):  # noqa: F811
    from judgekeeper import front

    missed = []
    real = front.is_open

    def slow_once(folder):
        if not missed:
            missed.append(folder)
            return False  # as when the page takes longer than PROBE_TIMEOUT to answer
        return real(folder)
    monkeypatch.setattr(front, "is_open", slow_once)
    ws = project(here, marked=N - 4)
    assert missed and label.read_lock(ws.dir) is None


# Marks posted without `seconds`: the time between them still shows a program ----------

def _posted(path, gap: int, n: int = 60) -> None:
    marks.begin(path, {"marks": marks.VERSION})
    for k in range(n):
        line = marks.stamp(f"q{k}", "pass", "pass", None, "s1")
        line["at"] = f"2026-10-21T10:{k * gap // 60:02d}:{k * gap % 60:02d}Z"
        marks.append(path, line)


def test_marks_posted_fast_without_seconds_look_like_a_program(tmp_path):
    _posted(tmp_path / "marks.jsonl", gap=0)
    lines = start_label.made_lines(marks.made(marks.read(tmp_path / "marks.jsonl")))
    assert any("This looks like a program, not a person." in line for line in lines), lines


def test_marks_posted_slowly_without_seconds_are_not_called_a_program(tmp_path):
    _posted(tmp_path / "marks.jsonl", gap=5)
    lines = start_label.made_lines(marks.made(marks.read(tmp_path / "marks.jsonl")))
    assert not any("under a second" in line for line in lines), lines


# The old pre-commit line: not when commented out, with any spaces -----------------------

def test_the_old_hook_line_skips_comments_and_allows_any_spaces(tmp_path):
    hooks = tmp_path / ".git" / "hooks"
    hooks.mkdir(parents=True)
    for text, said in (("#!/bin/sh\n# judgekeeper check --fast (old)\n", False),
                       ("#!/bin/sh\n  #judgekeeper check --fast\n", False),
                       ("#!/bin/sh\njudgekeeper  check   --fast\n", True),
                       ("#!/bin/sh\nuvx judgekeeper check --fast || exit 1\n", True),
                       ("#!/bin/sh\njudgekeeper check\n", False)):
        (hooks / "pre-commit").write_text(text, encoding="utf-8")
        assert (textio.old_hook(tmp_path) == textio.OLD_HOOK) is said, text


# `python -m judgekeeper`: Ctrl-C while the commands load exits 130 ---------------------

def test_ctrl_c_while_the_commands_load_exits_130_under_python_m(tmp_path):
    """A Ctrl-C raised inside code run from a string (as namedtuple and dataclass build their
    classes while modules load) leaves Python's "end by the signal" flag set even when it is
    caught, and `python -m` obeys that flag: the run must still end with 130."""
    (tmp_path / "jk_interrupted.py").write_text(
        "import builtins, sys\n"
        "real = builtins.__import__\n"
        "def load(name, *args, **kwargs):\n"
        "    if name == 'judgekeeper.cli':\n"
        "        exec('raise KeyboardInterrupt')\n"
        "    return real(name, *args, **kwargs)\n"
        "builtins.__import__ = load\n"
        "from judgekeeper.__main__ import main\n"
        "sys.exit(main(['--no-browser']))\n", encoding="utf-8")
    done = subprocess.run([sys.executable, "-m", "jk_interrupted"], capture_output=True,
                          check=False, text=True, timeout=60, stdin=subprocess.DEVNULL, cwd=tmp_path)
    assert done.returncode == 130, (done.returncode, done.stdout, done.stderr)
    assert done.stdout.splitlines()[-2:] == ["Stopped.", "Next: run `judgekeeper` to carry on."]
    assert "Traceback" not in done.stdout + done.stderr

