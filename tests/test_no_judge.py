"""Results files with no LLM judge in them: checks that are rules in code (promptfoo's
`contains`, DeepEval's Exact Match, a run with no scorer), and promptfoo's table output, which
keeps only each test's overall pass. A file with no judge is left out with one line; only when
no file has a judge is it said, once. A test's overall pass is never a judge's verdict."""

from __future__ import annotations

import json

import pytest

from judgekeeper import find
from tests.start_projects import deepeval_data, inspect_data, promptfoo_data, split
from tests.test_front import run


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _code_only(data):
    for row in data["results"]["results"]:
        for c in row["gradingResult"]["componentResults"]:
            c["assertion"] = {"type": "contains", "value": "refund"}
    return data


def _flat(text: str) -> str:
    return " ".join(text.split())


def test_a_promptfoo_file_with_no_judge_is_left_out(here, capsys):
    _write(here / "judged.json", promptfoo_data(split(16, 16),
                                                created="2026-10-01T10:00:00.000Z"))
    _write(here / "smoke.json", _code_only(promptfoo_data(split(5, 5),
                                                          created="2026-10-05T10:00:00.000Z")))
    code, out, err = run(capsys, "--no-browser")
    assert "smoke.json is left out: no LLM judge in it." in _flat(out)
    assert "Answers:     32 answers" in out
    assert code == 0, out + err


def test_many_files_with_no_judge_are_said_once(here, capsys):
    for i in range(12):
        _write(here / f"smoke-{i:02}.json", _code_only(promptfoo_data(
            split(5, 5), created=f"2026-10-{i + 1:02}T10:00:00.000Z")))
    code, out, err = run(capsys, "--no-browser")
    text = _flat(out + err)
    assert text.count("decisions from an LLM-as-a-judge") == 1, text
    assert ("None of your 12 promptfoo results files holds decisions from an LLM-as-a-judge. "
            "These checks are rules in code, not an LLM-as-a-judge. judgekeeper checks an "
            "LLM-as-a-judge.") in text
    assert "left out" not in text
    assert "Next: add an LLM-as-a-judge to your eval and run it once, then run `judgekeeper " in text
    assert code == 3


def test_one_file_with_no_judge_says_so(here, capsys):
    _write(here / "results.json", _code_only(promptfoo_data(split(5, 5))))
    code, out, err = run(capsys, "--no-browser")
    assert ("results.json holds no decisions from an LLM-as-a-judge. These checks are rules "
            "in code, not an LLM-as-a-judge.") in _flat(out + err)
    assert code == 3


def test_deepeval_metrics_with_no_model_are_rules_in_code(here, capsys):
    _write(here / ".deepeval" / ".latest_run_full.json",
           deepeval_data(split(10, 10), model=None))
    code, out, err = run(capsys, "--no-browser")
    text = _flat(out + err)
    assert ("These metrics are rules in code, not an LLM-as-a-judge. judgekeeper checks an "
            "LLM-as-a-judge.") in text
    assert "Your judge" not in text and "Step 2 of 5" not in text
    assert code == 3


def test_deepeval_picks_the_metric_with_a_model(here, capsys):
    data = deepeval_data(split(16, 16))
    for case in data["testCases"]:
        rule = dict(case["metricsData"][0], name="Exact Match", evaluationModel=None)
        case["metricsData"].append(rule)
    _write(here / ".deepeval" / ".latest_run_full.json", data)
    code, out, err = run(capsys, "--no-browser")
    assert "Exact Match" not in out, out
    assert code == 0, out + err


def test_inspect_logs_with_no_scorer_say_so_once(here, capsys):
    for day in (1, 2):
        data = inspect_data(split(5, 5))
        data["eval"]["scorers"] = []
        for s in data["samples"]:
            s.pop("scores", None)
        _write(here / "logs" / f"2026-10-0{day}_exact.json", data)
    code, out, err = run(capsys, "--no-browser")
    assert ("None of your 2 Inspect logs holds decisions from an LLM-as-a-judge."
            in _flat(out + err))
    assert code == 3


TABLE = {"head": {"prompts": [{"raw": "Answer: {{question}}"}], "vars": ["question"]},
         "body": [{"outputs": [{"pass": True, "text": "Yes."}], "vars": ["Is it open?"],
                   "test": {"vars": {"question": "Is it open?"}}}]}


def test_promptfoos_table_output_is_named_never_read(here, capsys):
    _write(here / "promptfooconfig.yaml", {"description": "x"})
    _write(here / "table.json", TABLE)
    code, out, err = run(capsys, "--no-browser")
    text = _flat(out + err)
    assert ("table.json is promptfoo's table output, which doesn't keep the judge's own "
            "decisions.") in text
    assert "`promptfoo eval -o results.json`" in text
    assert "own format" not in text and "Step 2 of 5" not in text
    assert code == 2


def test_promptfoos_table_output_given_as_the_path(here, capsys):
    _write(here / "table.json", TABLE)
    assert find.classify_file(here / "table.json") is None
    code, out, err = run(capsys, "table.json", "--no-browser")
    assert ("table.json is promptfoo's table output, which doesn't keep the judge's own "
            "decisions.") in _flat(out + err)
    assert code == 2


def test_table_output_next_to_full_results_is_left_out(here, capsys):
    _write(here / "table.json", TABLE)
    _write(here / "results.json", promptfoo_data(split(16, 16)))
    code, out, err = run(capsys, "--no-browser")
    assert "table.json is promptfoo's table output" in _flat(out)
    assert "Answers:     32 answers" in out
    assert code == 0, out + err
