"""An LLM-as-a-judge picked at a terminal ("Which one?") is kept for the rest of the run: the
printed commands and the page's flags carry it as --metric, a later question does not ask it
again, and `judgekeeper mark` repeats it as its flag."""

from __future__ import annotations

import copy
import json

import pytest

from judgekeeper.textio import quote_arg
from tests.start_projects import deepeval_data, inspect_data, split
from tests.test_front import next_lines, run, terminal  # noqa: F401

CHOSEN = "Relevancy [GEval]"
METRIC = f"--metric {quote_arg(CHOSEN)}"
SEVERAL = "These results hold more than one LLM-as-a-judge:"


@pytest.fixture
def two_metrics(tmp_path, monkeypatch):
    """18 DeepEval answers (too few: the run prints its commands), each graded by
    Correctness [GEval] and Relevancy [GEval]."""
    monkeypatch.chdir(tmp_path)
    data = deepeval_data(split(9, 9))
    for case in data["testCases"]:
        other = copy.deepcopy(case["metricsData"][0])
        other["name"] = CHOSEN
        case["metricsData"].append(other)
    (tmp_path / ".deepeval").mkdir()
    (tmp_path / ".deepeval" / ".latest_run_full.json").write_text(json.dumps(data),
                                                                  encoding="utf-8")
    return tmp_path


def test_a_run_prints_the_metric_picked_in_its_commands(two_metrics, capsys,
                                                        terminal):  # noqa: F811
    answers, _ = terminal
    answers += ["2", "n"]  # Relevancy [GEval]; save in judgekeeper.toml? no
    code, out, _ = run(capsys, "--no-browser", "--port", "0")
    assert code == 3, out  # 18 answers: too few
    assert f"LLM-as-a-judge:  {CHOSEN}" in out, out
    (last,) = next_lines(out)[-1:]
    assert f"`judgekeeper mark {METRIC} --port 0 --no-browser`" in last, last
    assert f"run `judgekeeper {METRIC} --port 0 --no-browser` again" in last, last


def test_once_judgekeeper_toml_keeps_the_metric_the_commands_need_not_say_it(
        two_metrics, capsys, terminal):  # noqa: F811
    answers, _ = terminal
    answers += ["2", ""]  # Relevancy [GEval]; save in judgekeeper.toml? yes
    code, out, _ = run(capsys, "--no-browser", "--port", "0")
    assert code == 3, out
    assert CHOSEN in (two_metrics / "judgekeeper.toml").read_text(encoding="utf-8")
    last = next_lines(out)[-1]
    assert "--metric" not in last, last
    assert "run `judgekeeper --port 0 --no-browser` again" in last, last


def test_mark_repeats_the_metric_picked_as_its_flag(two_metrics, capsys, pages,
                                                    terminal):  # noqa: F811
    answers, _ = terminal
    answers += ["2"]
    code, out, _ = run(capsys, "mark", "--no-browser", "--port", "0")
    assert code == 3, out
    assert f"run `judgekeeper mark {METRIC} --port 0 --no-browser`" in next_lines(out)[-1], out
    started, _ = pages
    assert started[-1]["flags"].get("metric") == CHOSEN, started


def test_a_later_question_does_not_ask_for_the_metric_again(tmp_path, monkeypatch, capsys,
                                                            terminal, pages):  # noqa: F811
    """Inspect partial credit (P): its answer makes judgekeeper read the results again."""
    monkeypatch.chdir(tmp_path)
    data = inspect_data([*split(13, 13), "P", "P", "P", "P"])
    for sample in data["samples"]:
        sample["scores"]["fact_check"] = copy.deepcopy(sample["scores"]["model_graded_qa"])
    scorer = copy.deepcopy(data["eval"]["scorers"][0])
    scorer["name"] = "fact_check"
    data["eval"]["scorers"].append(scorer)
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "2026-10-02_support.json").write_text(json.dumps(data),
                                                               encoding="utf-8")
    answers, _ = terminal
    answers += ["2", "1", "n"]  # model_graded_qa; partial credit is Pass; save? no
    code, out, _ = run(capsys, "--no-browser", "--port", "0")
    assert out.count(SEVERAL) == 1, out
    assert code == 0, out
    assert not answers, answers
    started, _ = pages
    assert started[-1]["flags"].get("metric") == "model_graded_qa", started
