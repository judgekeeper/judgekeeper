"""The own-format guess never invents a judge. A part is a judge's verdict only when its name
says so (score, verdict, grade, label, ...) and its values are verdict-like for most answers:
pass/fail, true/false, yes/no, correct/incorrect, or numbers from 0 to 1 or on a fixed scale.
Free text, ids and a number with no such name are never verdicts. A judge's settings (its
pass mark, criteria text, a run id) are never read as an answer's parts. A reading that is
unsure (a part told by its values alone, or one answer from a file that holds a list of
many) is never accepted by --yes: the person checks it at a terminal.
"""

from __future__ import annotations

import csv
import json
import tomllib

import pytest

from judgekeeper import mapper, own_format
from judgekeeper.cli import main
from tests.start_projects import answer, question


def _run_lines(judges=("answer_quality",), n=60) -> list[dict]:
    """One run per line: run -> cases -> answer -> scores per judge, the judge's settings
    (its pass mark and its criteria's text) at the run level."""
    cases = [{"case_id": f"c{i}", "question": question(i),
              "answer": {"text": answer(i), "scores": {
                  j: {"score": 0.9 if i % 3 else 0.2, "reason": f"reason {i}"}
                  for j in judges}}} for i in range(n)]
    return [{"run_id": "run-1", "started_at": "2026-10-13T10:00:00+00:00",
             "judge": {"model": "claude-haiku-4-5", "pass_mark": 0.5,
                       "criteria": {j: "Is the answer correct and polite?" for j in judges}},
             "cases": cases}]


def _write_jsonl(path, lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(x) + "\n" for x in lines), encoding="utf-8")
    return path


def _write_csv(path, rows):
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    return path


# What one answer is, never the judge's settings ---------------------------------------------

@pytest.mark.parametrize("judge", ["answer_quality", "helpful", "question_match"])
def test_a_judge_named_like_an_answer_keeps_cases_as_the_answers(judge):
    g = mapper.guess(_run_lines((judge,)))
    assert g.each == "cases[]"
    assert (g.input, g.output) == ("question", "answer.text")
    assert g.score == "answer.scores.{judge}.score" and g.judges == [judge]
    assert (g.pass_mark, g.pass_mark_key) == (0.5, "judge.pass_mark")
    assert not g.unsure and g.doubt is None


def test_settings_are_never_an_answers_parts():
    unit = {"run_id": "run-1", "judge": {"pass_mark": 0.5,
                                         "criteria": {"answer_ok": "Is the answer right?"}},
            "question": "q", "reply_text": "a long answer here", "verdict": "pass"}
    g = mapper.guess([unit])
    assert g.input != "run_id" and "judge" not in g.input
    assert "judge" not in g.output and g.score == "verdict"


def test_one_answer_from_a_file_that_holds_a_list_of_many_is_doubted():
    unit = {"question": "q", "answer": "a", "verdict": "pass",
            "history": [{"step": i, "note": f"n{i}"} for i in range(60)]}
    g = mapper.guess([unit])
    assert g.each == ""
    assert g.doubt == ("judgekeeper read 1 answer, but the file holds a list of 60 items "
                       "(history); check the mapping")


# What a verdict is ------------------------------------------------------------------------

def test_a_survey_csv_has_no_judge(tmp_path):
    rows = [{"No": str(i + 1), "Question": question(i), "Dr Answer": answer(i), "": ""}
            for i in range(30)]
    path = _write_csv(tmp_path / "ready_to_eval.csv", rows)
    with pytest.raises(mapper.MapError, match="no judge verdicts were found in it"):
        mapper.guess(mapper.load(path))
    assert own_format.search(tmp_path) is None  # never named as judge results


@pytest.mark.parametrize("extra", [
    {"k": 3},  # a number with no verdict name
    {"score": "The answer is mostly right but misses the second step of the fix."},
    {"label_id": 7, "eval_id": 12},  # ids
    {"score": "Paris"},  # short text, not a verdict
])
def test_no_verdict_like_part_is_no_judge(extra):
    units = [{"question": question(i), "answer": answer(i), **extra} for i in range(20)]
    with pytest.raises(mapper.MapError, match="no judge verdicts were found in it"):
        mapper.guess(units)


@pytest.mark.parametrize("values, kind", [
    (["pass", "fail"], "verdict"), (["PASS", "FAIL"], "verdict"), ([True, False], "verdict"),
    (["yes", "no"], "verdict"), (["correct", "incorrect"], "verdict"),
    ([0.9, 0.2], "score"), ([1, 5], "score"), ([0, 100], "score"), (["0.9", "0.1"], "score"),
])
def test_verdict_like_values_are_a_judge(values, kind):
    units = [{"question": question(i), "answer": answer(i), "verdict": values[i % 2]}
             for i in range(20)]
    g = mapper.guess(units)
    assert g.score == "verdict" and g.kind == kind


def test_a_score_column_with_mostly_free_text_is_no_judge():
    units = [{"question": question(i), "answer": answer(i),
              "grade": "pass" if i < 3 else f"see the notes for case {i}"} for i in range(20)]
    with pytest.raises(mapper.MapError, match="no judge verdicts"):
        mapper.guess(units)


def test_judge_score_columns_beside_answer_columns_are_read(tmp_path):
    rows = [{"No": str(i + 1), "Question": question(i), "Dr Answer": answer(i),
             "LLM_JUDGE_GPT_score": ("0.9", "0.7", "0.2")[i % 3],
             "LLM_JUDGE_GPT_reasoning": f"reason {i}"} for i in range(30)]
    g = mapper.guess(mapper.load(_write_csv(tmp_path / "judged.csv", rows)))
    assert g.score == "LLM_JUDGE_GPT_score" and g.kind == "score"


def test_the_apps_model_alone_is_not_the_judges():
    units = [{"question": question(i), "answer": answer(i), "model": "gpt-4.1-mini",
              "verdict": "pass"} for i in range(20)]
    assert mapper.guess(units).model_key is None


def test_a_judge_file_at_the_project_root_is_found(tmp_path):
    _write_jsonl(tmp_path / "judge_results.jsonl", [
        {"question": question(i), "answer": answer(i), "verdict": "pass"} for i in range(20)])
    found = own_format.search(tmp_path)
    assert found is not None and found.rel == "judge_results.jsonl"


# --yes never accepts an unsure reading ------------------------------------------------------

def _front(capsys, *argv):
    code = main([str(a) for a in argv])
    out, err = capsys.readouterr()
    return code, " ".join((out + err).split())


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_an_unsure_reading_is_not_saved_by_yes(here, capsys):
    _write_jsonl(here / "graded.jsonl", [
        {"q": question(i), "text": f"A longer answer {i}.", "verdict": "pass" if i % 2 else
         "fail"} for i in range(40)])
    code, out = _front(capsys, "graded.jsonl", "--no-browser", "--yes")
    assert "judgekeeper isn't sure how to read graded.jsonl" in out
    assert "--yes`" not in out.split("Next:")[-1]
    assert not (here / "judgekeeper.toml").exists()
    assert code == 3


def test_a_doubted_reading_is_not_saved_by_yes(here, capsys):
    unit = {"question": "q", "answer": "a", "verdict": "pass",
            "history": [{"step": i, "note": f"n{i}"} for i in range(60)]}
    (here / "run.json").write_text(json.dumps(unit), encoding="utf-8")
    code, out = _front(capsys, "run.json", "--no-browser", "--yes")
    assert ("judgekeeper read 1 answer, but the file holds a list of 60 items (history); "
            "check the mapping") in out
    assert not (here / "judgekeeper.toml").exists()
    assert code == 3


def test_a_sure_reading_is_still_saved_by_yes(here, capsys):
    _write_jsonl(here / "history" / "evals.jsonl", _run_lines())
    _, out = _front(capsys, "--no-browser", "--yes")
    saved = tomllib.loads((here / "judgekeeper.toml").read_text(encoding="utf-8"))["start"]
    assert saved["map"]["each"] == "cases[]"
    assert "Answers: 60 answers" in out  # out is flattened


def test_only_judge_columns_are_judges_in_a_wide_csv(tmp_path):
    rows = [{"No": str(i + 1), "Question": question(i), "Dr Answer": answer(i),
             "LLM_JUDGE_Qwen_score": ("0.9", "0.7", "0.2")[i % 3],
             "LLM_JUDGE_Qwen_reasoning": f"reason {i}",
             "LLM_JUDGE_GPT_score": ("0.8", "0.1")[i % 2],
             "LLM_JUDGE_GPT_reasoning": f"why {i}"} for i in range(30)]
    g = mapper.guess(mapper.load(_write_csv(tmp_path / "judged.csv", rows)))
    assert g.judges == ["LLM_JUDGE_Qwen_score", "LLM_JUDGE_GPT_score"]
    assert g.kind == "score" and g.reason is None
