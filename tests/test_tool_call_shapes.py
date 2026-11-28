"""A tool call in an agent's steps comes in two shapes: {id, name, arguments}, or OpenAI's
{id, type: "function", function: {name, arguments}}. The records reader (a v2 `trajectory`)
and the steps reader (`judgekeeper steps runs.jsonl`) take both, by one rule
(records.tool_call), and the same call gives a record the same id in either shape."""

from __future__ import annotations

import hashlib
import json

import pytest

from judgekeeper import records, steps
from judgekeeper.anchors import canonical_json
from judgekeeper.cli import main

FLAT = {"id": "c1", "name": "search", "arguments": {"city": 0}}
OPENAI = {"id": "c1", "type": "function",
          "function": {"name": "search", "arguments": "{\"city\": 0}"}}
SHAPES = ("{id, name, arguments} or OpenAI's {id, type: \"function\", function: {name, "
          "arguments}}")
NEITHER = [
    {"id": "c1", "arguments": {}},  # no name
    {"id": "c1", "type": "custom", "function": {"name": "search", "arguments": "{}"}},
    {"id": "c1", "type": "function", "function": {"arguments": "{}"}},  # no name in function
    {"id": "c1", "function": {"name": "", "arguments": "{}"}},
    "search",
]


def _trajectory(call) -> list:
    return [{"role": "user", "content": "Find the cheapest flight to city 0."},
            {"role": "assistant", "content": "", "tool_calls": [call]},
            {"role": "tool", "tool_call_id": "c1", "content": "F100 $120"},
            {"role": "assistant", "content": "The cheapest flight is F100."}]


def _row(n: int, call) -> dict:
    return {"schema_version": 2, "target_id": f"run-{n:03}", "name": "task-success",
            "annotator_kind": "LLM", "label": "pass" if n % 2 else "fail",
            "input": f"Find the cheapest flight number {n}.", "output": "F100.",
            "trajectory": _trajectory(call)}


def _write(tmp_path, call, n=6):
    path = tmp_path / "results.jsonl"
    path.write_text("".join(json.dumps(_row(i, call)) + "\n" for i in range(1, n + 1)),
                    encoding="utf-8")
    return path


# The rule ------------------------------------------------------------------------------------

def test_both_shapes_are_the_same_call():
    assert records.tool_call(FLAT) == ("c1", "search", {"city": 0})
    assert records.tool_call(OPENAI) == ("c1", "search", "{\"city\": 0}")
    no_type = {"id": "c1", "function": {"name": "search", "arguments": "{}"}}
    assert records.tool_call(no_type) == ("c1", "search", "{}")


@pytest.mark.parametrize("call", NEITHER)
def test_a_call_of_neither_shape_is_none(call):
    assert records.tool_call(call) is None


# The records reader ---------------------------------------------------------------------------

def test_a_trajectory_with_openai_tool_calls_is_read(tmp_path):
    got = records.read_records(_write(tmp_path, OPENAI), bad_lines_ok=True)
    assert len(got) == 6 and not got.left_out
    assert got[0].trajectory[1]["tool_calls"] == [OPENAI]  # kept as the file has it


def test_a_whole_file_of_openai_tool_calls_is_read_by_the_plain_run(tmp_path, monkeypatch,
                                                                    capsys):
    _write(tmp_path, OPENAI, n=40)
    monkeypatch.chdir(tmp_path)
    code = main(["results.jsonl", "--no-browser", "--port", "0"])
    said = " ".join(capsys.readouterr().out.split())
    assert code == 0, said
    assert "damaged" not in said


@pytest.mark.parametrize("call", NEITHER)
def test_a_call_of_neither_shape_names_the_field_and_both_shapes(tmp_path, call):
    with pytest.raises(records.RecordsError) as e:
        records.read_records(_write(tmp_path, call))
    assert f"line 1: trajectory step 2, tool call 1 must be {SHAPES}" in str(e.value)


def test_a_file_whose_every_line_is_damaged_says_why_the_first_one_is(tmp_path):
    with pytest.raises(records.Damaged) as e:
        records.read_records(_write(tmp_path, NEITHER[0]), bad_lines_ok=True)
    said = str(e.value)
    assert "each of its 6 lines has a damaged field" in said
    assert f"(line 1: trajectory step 2, tool call 1 must be {SHAPES})" in said


def test_lines_left_out_say_why_the_first_one_is(tmp_path):
    path = _write(tmp_path, FLAT)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(_row(7, NEITHER[1])) + "\n")
    got = records.read_records(path, bad_lines_ok=True)
    assert got.left_out == [7]
    note = records.left_out_note(got, "results.jsonl")
    assert note.endswith(f"(line 7: trajectory step 2, tool call 1 must be {SHAPES}).")


# The answer's id --------------------------------------------------------------------------------

def test_the_same_call_in_either_shape_gives_the_answer_the_same_id():
    asked, said = "Find the cheapest flight.", "F100."
    assert (records.derive_record_id(asked, said, _trajectory(FLAT))
            == records.derive_record_id(asked, said, _trajectory(OPENAI)))


def test_an_id_from_the_flat_shape_is_what_it_was():
    """Marks are kept by these ids: a file already read keeps its answers' ids."""
    asked, said = "Find the cheapest flight.", "F100."
    for traj in (_trajectory(FLAT),
                 _trajectory({"id": "c1", "name": "search", "arguments": "{\"city\": 0}"})):
        then = canonical_json({"input": asked, "output": said, "trajectory": traj})
        assert records.derive_record_id(asked, said, traj) == hashlib.sha256(
            then.encode("utf-8")).hexdigest()[:records.ID_LENGTH]


# The steps reader -------------------------------------------------------------------------------

def _runs(tmp_path, call):
    path = tmp_path / "runs.jsonl"
    path.write_text(json.dumps({"id": "r1", "steps": _trajectory(call)}) + "\n",
                    encoding="utf-8")
    return path


@pytest.mark.parametrize("call", [FLAT, OPENAI])
def test_the_steps_reader_shows_both_shapes_alike(tmp_path, call):
    (run,) = steps.read_runs(_runs(tmp_path, call))
    assert run.steps[1]["content"] == 'Tool call: search({"city": 0})'


@pytest.mark.parametrize("call", NEITHER)
def test_the_steps_reader_refuses_what_the_records_reader_does(tmp_path, call):
    with pytest.raises(steps.StepsError) as e:
        steps.read_runs(_runs(tmp_path, call))
    assert str(e.value) == (f"Step 2 on line 1 of runs.jsonl: tool call 1 must be {SHAPES}.")
