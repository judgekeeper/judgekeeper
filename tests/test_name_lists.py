"""Lists of LLM-as-a-judge names: quoted for the shell, and never a flood.

A results file can name any metric, and as many as it likes. A name pasted from the line that
says to choose one must run nothing, and 50,000 names must not push the `Next:` line off the
screen.
"""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import time

import pytest

from judgekeeper.cli import main
from tests.start_projects import inspect_data, promptfoo_data, split
from tests.test_front import next_lines

EVIL = "x'; touch PWN-metric; echo '"


def _metrics(root, names, rows=None) -> None:
    """A promptfoo results file whose rows (default: every row) are also graded by a judge
    for each of `names`."""
    data = promptfoo_data(split(20, 16), metric="Correct")
    for i, row in enumerate(data["results"]["results"]):
        if rows is not None and i not in rows:
            continue
        base = row["gradingResult"]["componentResults"][0]
        for name in names:
            c = copy.deepcopy(base)
            c["assertion"] = {**c["assertion"], "metric": name}
            row["gradingResult"]["componentResults"].append(c)
    (root / "results.json").write_text(json.dumps(data), encoding="utf-8")


def _run(capsys, *argv):
    code = main([*argv, "--no-browser"])
    out, err = capsys.readouterr()
    return code, out + err


@pytest.mark.skipif(sys.platform == "win32", reason="pasted into sh")
def test_a_metric_name_pasted_from_the_choose_line_runs_nothing(tmp_path, monkeypatch, capsys):
    _metrics(tmp_path, [EVIL])
    monkeypatch.chdir(tmp_path)
    code, out = _run(capsys)
    assert code == 3
    line = next_lines(out)[-1]
    names = line.split("check (", 1)[1].rsplit("), then run", 1)[0]
    pasted = subprocess.run(["sh", "-c", f"printf '%s\\n' {names}"], cwd=tmp_path,
                            capture_output=True, text=True, check=False)
    assert not (tmp_path / "PWN-metric").exists()
    assert EVIL in pasted.stdout.splitlines(), (line, pasted.stdout)


def test_50000_metric_names_never_flood_the_terminal(tmp_path, monkeypatch, capsys):
    _metrics(tmp_path, [f"m{i}" for i in range(50_000)], rows={0})
    monkeypatch.chdir(tmp_path)
    code, out = _run(capsys)
    assert code == 3
    lines = out.rstrip("\n").splitlines()
    assert len(lines) <= 30, out
    assert "and 49,981 more" in out  # Correct and m0 to m49999, 20 shown
    assert next_lines(out)[-1] == next_lines(out)[0]  # one Next: line, at the end
    at = max(i for i, x in enumerate(lines) if x.startswith("Next:"))
    assert all(x.strip() for x in lines[at:])


def test_an_unknown_metric_lists_at_most_20_names(tmp_path, monkeypatch, capsys):
    _metrics(tmp_path, [f"m{i}" for i in range(5_000)], rows={0})
    monkeypatch.chdir(tmp_path)
    code, out = _run(capsys, "--metric", "nope")
    assert code == 2
    error = next(x for x in out.splitlines() if x.startswith("error: no LLM-as-a-judge named"))
    assert error.count("'m") <= 20 and "and 4,981 more" in error, error


def test_10000_inspect_score_keys_are_quick_and_short(tmp_path, monkeypatch, capsys):
    """One sample: reading each sample's keys takes its own time, which this doesn't test."""
    data = inspect_data([True])
    for sample in data["samples"]:
        sample["scores"]["model_graded_qa"]["value"] = {f"k{i}": "C" for i in range(10_000)}
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "a.json").write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    started = time.monotonic()
    code, out = _run(capsys)
    assert time.monotonic() - started < 2
    assert code == 3
    assert len(out.splitlines()) <= 30, out
    assert "and 9,980 more" in out


def test_on_windows_the_names_read_alike_in_double_quotes(tmp_path, monkeypatch, capsys):
    """cmd.exe and PowerShell read double quotes; a plain name gets them too."""
    _metrics(tmp_path, ["Answer Relevancy"])
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "platform", "win32")
    code, out = _run(capsys)
    assert code == 3
    assert '("Answer Relevancy", "Correct")' in next_lines(out)[-1], out


@pytest.fixture
def terminal(monkeypatch):
    """A person at a terminal who types `answers` in order."""
    from judgekeeper import start

    answers: list[str] = []
    monkeypatch.setattr(start, "_interactive", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt="": answers.pop(0))
    return answers


@pytest.mark.parametrize("flag", [None, "PATH"])
def test_a_choice_that_is_not_a_name_shows_and_takes_every_option(terminal, capsys, flag):
    from judgekeeper.start import Talk

    terminal.append("26")
    options = [f"part {i}" for i in range(1, 27)]
    assert Talk().choose("Which path holds the score?", options, "", flag=flag,
                         values=options) == 25
    out = capsys.readouterr().out
    assert "  26. part 26" in out and "more" not in out


def _judges(n: int, most: str = "zzz"):
    """An own-format guess with `n` LLM-as-a-judge names, `most` used on every line and each
    other on one line."""
    from judgekeeper import mapper

    names = [f"j{i:02}" for i in range(n - 1)] + [most]
    units = [{"q": "q", "a": "a", "s": {most: 1, names[i]: 1}} for i in range(n - 1)]
    return units, mapper.Guess(each="", input="q", output="a", score="s.{judge}",
                               judges=names)


def test_all_one_at_a_time_stays_a_choice_beside_26_judges(terminal, capsys):
    from judgekeeper import own_map
    from judgekeeper.start import Talk

    units, g = _judges(26)
    terminal.append("21")
    assert own_map._choose_judge(Talk(), units, g, None) == "*"
    out = capsys.readouterr().out
    assert "  21. All, one at a time" in out and "and 6 more" in out, out


def test_the_most_used_judge_is_among_the_20_shown(terminal, capsys):
    from judgekeeper import own_map
    from judgekeeper.start import Talk

    units, g = _judges(26)
    terminal.append("1")
    assert own_map._choose_judge(Talk(), units, g, None) == "zzz"
    assert "  1. zzz (25 answers)" in capsys.readouterr().out


def test_the_most_used_metric_is_among_the_20_shown(tmp_path, monkeypatch, capsys):
    _metrics(tmp_path, [f"m{i}" for i in range(30)], rows={0})
    _metrics_add(tmp_path, "zzz")
    monkeypatch.chdir(tmp_path)
    code, out = _run(capsys)
    assert code == 3
    listed = out.split("and 11 more")[0]
    assert "  zzz (" in listed, out


def _metrics_add(root, name) -> None:
    """`name` also grades every row of results.json."""
    data = json.loads((root / "results.json").read_text(encoding="utf-8"))
    for row in data["results"]["results"]:
        c = copy.deepcopy(row["gradingResult"]["componentResults"][0])
        c["assertion"] = {**c["assertion"], "metric": name}
        row["gradingResult"]["componentResults"].append(c)
    (root / "results.json").write_text(json.dumps(data), encoding="utf-8")


def test_own_format_judge_lists_say_at_most_20_names():
    from judgekeeper import own_map
    from judgekeeper.start import StartError, Talk

    units, g = _judges(30)
    grade = next(x for x in own_map.how_lines(g) if "LLM-as-a-judge names" in x)
    assert "and 10 more" in grade and "j25" not in grade, grade
    with pytest.raises(StartError) as e:
        own_map._choose_judge(Talk(), units, g, "nope")
    assert "and 10 more" in str(e.value) and str(e.value).count("'j") <= 20, e.value


def test_a_long_list_of_folders_names_at_most_20_commands(tmp_path, capsys):
    from judgekeeper.front import FrontTalk
    from judgekeeper.start import Stop

    talk = FrontTalk(yes=False, path=tmp_path, options={})
    folders = [f"evals/run{i:02}" for i in range(30)]
    with pytest.raises(Stop):
        talk.choose("DeepEval results in more than one folder:", folders, "", flag="PATH",
                    values=folders, what="which DeepEval results to check")
    line = next_lines(capsys.readouterr().out)[-1]
    assert "run19" in line and "run20" not in line and "and 10 more" in line, line
