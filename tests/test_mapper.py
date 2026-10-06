"""The mapper: a results file in a project's own format, its nested paths listed, and a guess
at how to read it (what one answer is, the input, the output, the score or verdict, the
reason, the judge's model). Then readers/mapped.py reads the file with the saved map.

Fixtures are made up (tests/start_projects.py): a history shaped like a homemade DeepEval
setup's (runs -> cases -> A/B -> scores per criterion), the same in another layout
(responses.A, scores.A.<criterion>), a flat JSONL, a CSV with odd column names, and a file
with no answers in it.
"""

from __future__ import annotations

import json

import pytest

from judgekeeper import mapper
from judgekeeper.readers.mapped import CHANGED_SHAPE, read_mapped
from judgekeeper.records import RecordsError
from tests.start_projects import (
    flat_jsonl,
    nested_runs_data,
    nested_runs_project,
    odd_csv,
    own_format_project,
)

# Paths ------------------------------------------------------------------------------------

@pytest.mark.parametrize("text, segments", [
    ("cases[].A.output", [("cases", True), ("A", False), ("output", False)]),
    ('{side}.scores.{judge}.score', [("{side}", False), ("scores", False),
                                     ("{judge}", False), ("score", False)]),
    ('"User Question"', [("User Question", False)]),
    ('runs[].cases[]', [("runs", True), ("cases", True)]),
    ('a."b.c"[]', [("a", False), ("b.c", True)]),
])
def test_paths_are_written_and_read_back(text, segments):
    assert mapper.parse(text) == segments
    assert mapper.write(segments) == text


def test_every_nested_path_is_listed_with_an_example_cut_to_60_characters():
    unit = nested_runs_data(runs=1, cases=2)[0]
    unit["cases"][0]["prompt"] = "x" * 200
    listed = dict(mapper.listing(unit, judges=["Safe wording", "Plain language"]))
    assert listed["run_id"] == '"2026-10-01T10:00"'
    assert listed["cases[].A.output"].startswith('"Answer 0.')
    assert listed["cases[].A.scores.<criterion>.score"] == "0.9"
    assert "cases[].B.scores.<criterion>.reason" in listed
    assert len(listed["cases[].prompt"]) == 60 and listed["cases[].prompt"].endswith("…")
    assert not any("Safe wording" in path for path in listed)


# Guessing --------------------------------------------------------------------------------

def test_the_nested_runs_shape():
    g = mapper.guess(nested_runs_data())
    assert g.each == "cases[]"
    assert (g.id, g.input) == ("id", "prompt")
    assert g.output == "{side}.output" and g.sides == ["A", "B"]
    assert g.score == "{side}.scores.{judge}.score"
    assert g.reason == "{side}.scores.{judge}.reason"
    assert g.judges == ["Safe wording", "Plain language"]
    assert g.kind == "score" and g.pass_mark == 0.5 and g.pass_mark_sure
    assert g.model_key == "judge_model" and g.model == "claude-opus-5"
    assert g.unsure == []


def test_the_other_layout(tmp_path):
    units = mapper.load(own_format_project(tmp_path))
    g = mapper.guess(units)
    assert g.each == "cases[]"
    assert (g.id, g.input) == ("case_id", "prompt")
    assert g.output == "responses.{side}" and g.sides == ["A", "B"]
    assert g.score == "scores.{side}.{judge}.score"
    assert g.reason == "scores.{side}.{judge}.reason"
    assert g.judges == ["safe_wording"]
    assert (g.model_key, g.model) == ("judge", "claude-opus-5")


def test_a_flat_jsonl(tmp_path):
    g = mapper.guess(mapper.load(flat_jsonl(tmp_path / "graded.jsonl")))
    assert g.each == "" and g.sides == [] and g.judges == []
    assert (g.input, g.output, g.score, g.reason) == ("question", "model_answer", "grade",
                                                      "explanation")
    assert g.kind == "verdict" and g.pass_mark is None
    assert g.judge_name() == "grade"
    assert g.unsure == []


def test_a_csv_with_odd_column_names(tmp_path):
    g = mapper.guess(mapper.load(odd_csv(tmp_path / "judged.csv")))
    assert (g.input, g.output) == ('"User Question"', '"Bot Reply"')
    assert (g.score, g.reason) == ('"Judge Score"', '"Judge Reasoning"')
    assert g.kind == "score" and g.pass_mark == 0.5 and g.pass_mark_sure


def test_scores_outside_0_to_1_suggest_a_pass_mark_it_is_not_sure_of(tmp_path):
    path = tmp_path / "graded.jsonl"
    path.write_text("".join(json.dumps({"question": f"q{i}", "answer": f"a{i}",
                                        "score": 1 + i % 5}) + "\n" for i in range(20)),
                    encoding="utf-8")
    g = mapper.guess(mapper.load(path))
    assert g.kind == "score" and g.pass_mark == 3 and not g.pass_mark_sure


def test_names_it_does_not_know_make_an_unsure_guess(tmp_path):
    path = tmp_path / "graded.jsonl"
    path.write_text("".join(json.dumps({"q": f"Question {i}?", "text": f"A longer answer {i}.",
                                        "verdict": "pass"}) + "\n" for i in range(5)),
                    encoding="utf-8")
    g = mapper.guess(mapper.load(path))
    assert g.output == "text"
    assert "output" in g.unsure and "input" in g.unsure


def test_a_file_with_no_answers_cannot_be_mapped(tmp_path):
    path = tmp_path / "scores.jsonl"
    path.write_text("".join(json.dumps({"question": f"q{i}", "score": 0.5}) + "\n"
                            for i in range(5)), encoding="utf-8")
    with pytest.raises(mapper.MapError, match="no answers"):
        mapper.guess(mapper.load(path))


def test_a_file_with_no_scores_cannot_be_mapped(tmp_path):
    path = tmp_path / "answers.jsonl"
    path.write_text("".join(json.dumps({"question": f"q{i}", "answer": "a"}) + "\n"
                            for i in range(5)), encoding="utf-8")
    with pytest.raises(mapper.MapError, match="no score or verdict"):
        mapper.guess(mapper.load(path))


def test_rows_with_an_error_or_a_rule_made_score_are_counted():
    g = mapper.guess(nested_runs_data(runs=3, cases=8, rule_rows=2))
    assert mapper.left_out(nested_runs_data(runs=3, cases=8, rule_rows=2), g, ["Safe wording"]) == 12
    assert mapper.left_out(nested_runs_data(runs=3, cases=8, rule_rows=2), g,
                           ["Plain language"]) == 0


# Reading with the map ---------------------------------------------------------------------

def _map(g, **over):
    return {**g.to_map(), "judge": "Safe wording", "pass_mark": 0.5, **over}


def test_the_mapped_reader_makes_records_newest_run_first(tmp_path):
    path = nested_runs_project(tmp_path, runs=3, cases=8, rule_rows=0)
    g = mapper.guess(mapper.load(path))
    runs = read_mapped(path, _map(g))
    assert [label for label, _ in runs] == ["evals.jsonl line 3", "evals.jsonl line 2",
                                            "evals.jsonl line 1"]
    newest_label, _ = read_mapped(path, _map(g), label="history/evals.jsonl")[0]
    assert newest_label == "history/evals.jsonl line 3"
    newest = runs[0][1]
    assert len(newest) == 16  # 8 cases x A and B
    r = newest[0]
    assert (r.name, r.target_id, r.annotator_kind) == ("Safe wording", "c0:A", "LLM")
    assert r.input == "Question 0? (run 2)" and r.output == "Answer 0. (A, run 2)"
    assert (r.score, r.label) == (0.9, "pass")
    assert newest[1].label == "fail"  # c0:B
    assert r.evaluator == {"model": "claude-opus-5"}
    assert r.explanation.startswith("Safe wording: fine")


def test_all_judges_one_at_a_time(tmp_path):
    path = nested_runs_project(tmp_path, runs=1, cases=4, rule_rows=0)
    g = mapper.guess(mapper.load(path))
    (_, records), = read_mapped(path, _map(g, judge="*"))
    assert sorted({r.name for r in records}) == ["Plain language", "Safe wording"]
    assert len(records) == 16


def test_one_side_only(tmp_path):
    path = nested_runs_project(tmp_path, runs=1, cases=4, rule_rows=0)
    g = mapper.guess(mapper.load(path))
    (_, records), = read_mapped(path, _map(g, sides=["B"]))
    assert [r.target_id for r in records] == ["c0:B", "c1:B", "c2:B", "c3:B"]


def test_rule_made_scores_can_be_left_out(tmp_path):
    path = nested_runs_project(tmp_path, runs=1, cases=8, rule_rows=2)
    g = mapper.guess(mapper.load(path))
    (_, kept), = read_mapped(path, _map(g, leave_out=True))
    (_, every), = read_mapped(path, _map(g, leave_out=False))
    assert (len(kept), len(every)) == (12, 16)


def test_a_verdict_file_and_a_csv_read_too(tmp_path):
    path = flat_jsonl(tmp_path / "graded.jsonl", n=6)
    g = mapper.guess(mapper.load(path))
    (_, records), = read_mapped(path, {**g.to_map(), "judge": None, "pass_mark": None})
    assert [r.label for r in records] == ["FAIL", "PASS", "PASS", "FAIL", "PASS", "PASS"]
    assert records[0].name == "grade" and records[0].target_id is not None
    path = odd_csv(tmp_path / "judged.csv", n=4)
    g = mapper.guess(mapper.load(path))
    (_, records), = read_mapped(path, {**g.to_map(), "judge": None, "pass_mark": 0.5})
    assert [(r.score, r.label) for r in records] == [(0.3, "fail"), (0.8, "pass"),
                                                     (0.3, "fail"), (0.8, "pass")]


def test_a_changed_shape_says_to_run_setup_again(tmp_path):
    path = nested_runs_project(tmp_path, runs=2, cases=2, rule_rows=0)
    m = _map(mapper.guess(mapper.load(path)))
    lines = [json.loads(line) for line in path.read_text().splitlines()]
    for line in lines:
        line["items"] = line.pop("cases")
    path.write_text("".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8")
    with pytest.raises(RecordsError) as e:
        read_mapped(path, m)
    assert str(e.value) == CHANGED_SHAPE
    assert CHANGED_SHAPE == "Your results file changed shape. Run judgekeeper setup again."
