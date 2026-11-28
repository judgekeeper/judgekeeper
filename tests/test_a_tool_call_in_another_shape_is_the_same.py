"""A tool call in an agent's steps comes as {id, name, arguments} or as OpenAI's {id, type:
"function", function: {name, arguments}}. The same call in the other shape is the same
answer: its grades changing is a re-grade, and marks made on it still hold. A call with
another name or other arguments is a changed answer."""

import json

import pytest

from judgekeeper import before_after, records
from tests.test_compare_after_check import _flat, _run

N = 80
BROKE_10 = f"On the {N} questions in both results: fixed 0, broke 10,"


def _said(capsys, *argv) -> tuple[int, str]:
    code, out = _run(capsys, *argv, "--no-browser", "--port", "0")
    _run(capsys, "--stop")
    return code, _flat(out)


def _call(i: int, shape: str, tool: str = "lookup_order", text: bool = True, order=None):
    arguments = {"order": i if order is None else order}
    arguments = json.dumps(arguments) if text else arguments
    if shape == "openai":
        return {"id": f"call-{i}", "type": "function",
                "function": {"name": tool, "arguments": arguments}}
    return {"id": f"call-{i}", "name": tool, "arguments": arguments}


def _write(path, shape: str, flips: int = 0, ids: bool = True, text: bool = True,
           change: str | None = None) -> None:
    """80 agent runs, odd ones passing; the first `flips` passing ones fail, their run the
    same unless `change` (another "tool", or other "arguments")."""
    flipped, lines = 0, []
    for i in range(1, N + 1):
        ok = i % 2 == 1
        tool, order = "lookup_order", None
        if ok and flipped < flips:
            ok, flipped = False, flipped + 1
            tool = "lookup_order_v2" if change == "tool" else tool
            order = i + 1000 if change == "arguments" else None
        steps = [{"role": "user", "content": f"Where is order {i}?"},
                 {"role": "assistant", "content": "Looking it up.",
                  "tool_calls": [_call(i, shape, tool, text, order)]},
                 {"role": "tool", "content": f"order {i}: shipped"}]
        line = {"schema_version": 2, "name": "Helpful", "annotator_kind": "LLM",
                "label": "pass" if ok else "fail", "input": f"Where is order {i}?",
                "output": f"Order {i} has shipped and arrives Friday.", "trajectory": steps}
        if ids:
            line["target_id"] = f"run-{i:02d}"
        lines.append(json.dumps(line))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _both_ways(tmp_path, monkeypatch, capsys, base, new):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CI", "true")
    base(tmp_path / "before.jsonl")
    base(tmp_path / "results.jsonl")
    assert _said(capsys, "results.jsonl")[0] == 0
    new(tmp_path / "results.jsonl")
    return _said(capsys, "results.jsonl"), _said(capsys, "results.jsonl", "--before",
                                                   "before.jsonl")


SHAPES = [("flat", "openai", True), ("openai", "flat", True), ("flat", "openai", False),
          ("flat", "flat", True), ("openai", "openai", True)]


@pytest.mark.parametrize("ids", [True, False], ids=["target-id", "no-id"])
@pytest.mark.parametrize("was,now,text", SHAPES,
                         ids=["flat-openai", "openai-flat", "object-openai", "flat-flat",
                              "openai-openai"])
def test_a_call_in_another_shape_graded_otherwise_is_only_grades(tmp_path, monkeypatch, capsys,
                                                                 was, now, text, ids):
    """`text`: a flat call's arguments as JSON text (else as an object), as the file has it;
    an OpenAI call's are always text."""
    plain, before = _both_ways(
        tmp_path, monkeypatch, capsys,
        lambda p: _write(p, was, ids=ids, text=text or was == "openai"),
        lambda p: _write(p, now, flips=10, ids=ids, text=text or now == "openai"))
    assert plain[0] == 0 and before_after.ONLY_GRADES in plain[1], plain[1]
    assert before[0] == 3 and before_after.ONLY_GRADES_BEFORE in before[1], before[1]


def test_a_call_in_another_shape_alone_is_nothing_changed(tmp_path, monkeypatch, capsys):
    """As the same results read again: nothing to compare; --before finds every one the same."""
    plain, before = _both_ways(tmp_path, monkeypatch, capsys,
                               lambda p: _write(p, "flat"), lambda p: _write(p, "openai"))
    assert plain[0] == 0 and "On the" not in plain[1], plain[1]
    assert before[0] == 0 and "fixed 0, broke 0, same 80." in before[1], before[1]


@pytest.mark.parametrize("change", ["tool", "arguments"])
@pytest.mark.parametrize("was,now", [("flat", "openai"), ("flat", "flat")])
def test_another_call_is_a_changed_answer(tmp_path, monkeypatch, capsys, change, was, now):
    plain, before = _both_ways(tmp_path, monkeypatch, capsys, lambda p: _write(p, was),
                               lambda p: _write(p, now, flips=10, change=change))
    for code, out in (plain, before):
        assert code == 1 and BROKE_10 in out, out


def test_marks_on_a_call_hold_in_its_other_shape(tmp_path, monkeypatch, capsys):
    """Marked from labels.csv on flat calls; the same runs in OpenAI's shape: no re-grade to
    tell of, the marks still on the same answers."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CI", "true")
    _write(tmp_path / "results.jsonl", "flat")
    labels = ["id,input,output,label"] + [
        f"run-{i:02d},Where is order {i}?,Order {i} has shipped and arrives Friday.,"
        f"{'pass' if i % 2 or i % 4 == 0 else 'fail'}" for i in range(1, N + 1)]
    (tmp_path / "labels.csv").write_text("\n".join(labels) + "\n", encoding="utf-8")
    assert _said(capsys, "results.jsonl", "--labels", "labels.csv")[0] in (0, 1)
    queue = json.loads((tmp_path / ".judgekeeper" / "start.json").read_text(encoding="utf-8"))["queue"]
    _write(tmp_path / "results.jsonl", "openai")
    _, out = _said(capsys, "results.jsonl")
    assert "were graded again" not in out, out
    from judgekeeper import start

    found = start.find_judge(tmp_path)
    assert {q["id"] for q in queue} <= {a.id for a in found.pool.answers}


def test_the_same_arguments_in_either_shape_give_the_same_id():
    asked, said = "Find the cheapest flight.", "F100."
    for text in (True, False):
        steps = {shape: [{"role": "assistant", "content": "",
                          "tool_calls": [_call(1, shape, text=text)]}]
                 for shape in ("flat", "openai")}
        assert (records.derive_record_id(asked, said, steps["flat"])
                == records.derive_record_id(asked, said, steps["openai"]))
