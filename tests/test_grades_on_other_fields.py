"""Every other field a reader reads beside the question and the answer can drive the grade: a
table's context or reference column, a records file's own fields, a promptfoo test's vars,
prompt and asserts, an Inspect sample's target or metadata, a Label Studio task's other data.
Each counts with the answer, so an agent change there under the same answer is compared, never
"Only the grades changed". The grade, its score and reason, the LLM-as-a-judge's setup, and
what changes on every run (ids, times, durations, costs, token counts) don't count."""

import csv
import json

import pytest

from judgekeeper import before_after
from tests.start_projects import inspect_data, promptfoo_data
from tests.test_compare_after_check import _flat, _run

N = 40
VERDICTS = [i % 4 != 0 for i in range(N)]  # 30 pass, 10 fail
FLIP = [i for i, v in enumerate(VERDICTS) if v][:10]  # 10 passing ones that fail now
BROKE_10 = f"On the {N} questions in both results: fixed 0, broke 10,"


def _said(capsys, *argv) -> tuple[int, str]:
    code, out = _run(capsys, *argv, "--no-browser", "--port", "0")
    _run(capsys, "--stop")
    return code, _flat(out)


def _verdict(i: int, changed: bool) -> bool:
    return VERDICTS[i] and not (changed and i in FLIP)


def _other(i: int, changed: bool, agent: bool) -> str:
    return "doc B, new retriever" if changed and agent and i in FLIP else "doc A"


def _csv(here, changed: bool, agent: bool = True, run: int = 0) -> str:
    """id,input,output,context,reference,latency_ms,created_at,model,verdict: the context of
    the FLIP rows is new when `agent`; latency and created_at change on every run."""
    with (here / "results.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "input", "output", "context", "reference", "latency_ms",
                    "created_at", "model", "verdict"])
        for i in range(N):
            w.writerow([f"q-{i:02}", f"Question {i}?", f"Answer {i}.",
                        _other(i, changed, agent), f"Expected {i}.", 100 + run * 7 + i,
                        f"2026-11-0{1 + run}T10:00:{i:02}Z", "judge-a",
                        "pass" if _verdict(i, changed) else "fail"])
    return "results.csv"


def _records(here, changed: bool, agent: bool = True, run: int = 0) -> str:
    """A records file with a field of its own (context) and metadata beside the grade."""
    path = here / "records.jsonl"
    with path.open("w", encoding="utf-8") as f:
        for i in range(N):
            f.write(json.dumps({
                "schema_version": 2, "target_id": f"q-{i:02}", "name": "correct",
                "annotator_kind": "LLM", "label": "pass" if _verdict(i, changed) else "fail",
                "input": f"Question {i}?", "output": f"Answer {i}.",
                "context": _other(i, changed, agent),
                "metadata": {"reference": f"Expected {i}.", "trace_id": f"t-{run}-{i}"},
                "evaluator": {"model": "judge-a"},
                "created_at": f"2026-11-0{1 + run}T10:00:00Z"}) + "\n")
    return path.name


def _promptfoo(here, changed: bool, agent: bool = True, run: int = 0, part: str = "vars"
               ) -> str:
    """promptfoo rows whose `part` is new for the FLIP rows when `agent`: a var beside the
    question, the prompt template, or a factuality assertion's reference answer."""
    data = promptfoo_data([_verdict(i, changed) for i in range(N)])
    for i, row in enumerate(data["results"]["results"]):
        other = _other(i, changed, agent)
        row["latencyMs"] = 100 + run * 7 + i
        if part == "vars":
            row["vars"] = row["testCase"]["vars"] = {**row["vars"], "context": other}
        elif part == "prompt":
            row["prompt"] = {"raw": f"Answer from {other}: {row['vars']['question']}",
                             "label": "Answer: {{question}}"}
        else:
            for c in row["gradingResult"]["componentResults"]:
                c["assertion"] = {"type": "factuality", "value": other}
    path = here / "output.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path.name


def _inspect(here, changed: bool, agent: bool = True, run: int = 0, part: str = "target"
             ) -> str:
    """An Inspect AI log whose samples' `part` (target or metadata) is new for the FLIP ones."""
    data = inspect_data([_verdict(i, changed) for i in range(N)])
    for i, s in enumerate(data["samples"]):
        other = _other(i, changed, agent)
        s["total_time"] = 1.5 + run + i
        if part == "target":
            s["target"] = other
        else:
            s["metadata"] = {"context": other}
    path = here / "logs" / "support.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return "logs"


WRITE = {
    "csv-context": _csv,
    "records-own-field": _records,
    "promptfoo-vars": _promptfoo,
    "promptfoo-prompt": lambda here, *a, **k: _promptfoo(here, *a, part="prompt", **k),
    "inspect-target": _inspect,
    "inspect-metadata": lambda here, *a, **k: _inspect(here, *a, part="metadata", **k),
}


@pytest.mark.parametrize("kind", WRITE)
def test_another_field_changed_under_the_same_answer_is_compared(tmp_path, monkeypatch, capsys,
                                                                 kind):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CI", "true")
    name = WRITE[kind](tmp_path, False)
    assert _said(capsys, name)[0] == 0
    WRITE[kind](tmp_path, True, run=1)
    code, out = _said(capsys, name)
    assert code == 1 and BROKE_10 in out, out
    assert before_after.ONLY_GRADES not in out, out


@pytest.mark.parametrize("kind", WRITE)
def test_only_grades_changed_beside_what_changes_every_run_is_only_grades(tmp_path, monkeypatch,
                                                                          capsys, kind):
    """A guard: the other fields stayed the same; ids, times, latencies changed."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CI", "true")
    name = WRITE[kind](tmp_path, False)
    assert _said(capsys, name)[0] == 0
    WRITE[kind](tmp_path, True, agent=False, run=1)
    code, out = _said(capsys, name)
    assert code == 0 and before_after.ONLY_GRADES in out, out


def test_a_new_reference_answer_in_a_promptfoo_assertion_is_another_setup(tmp_path,
                                                                         monkeypatch, capsys):
    """A model-graded assertion's value (a factuality reference, a rubric) is the
    LLM-as-a-judge's own rule: a new one is another setup, never "Only the grades changed"."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CI", "true")
    name = _promptfoo(tmp_path, False, part="asserts")
    assert _said(capsys, name)[0] == 0
    _promptfoo(tmp_path, True, run=1, part="asserts")
    code, out = _said(capsys, name)
    assert code == 0 and before_after.ONLY_GRADES not in out, out
    assert "setup changed since the last results" in out, out


def test_a_label_studio_task_with_other_data_is_another_answer(tmp_path):
    """Label Studio: the task's data beside the question and the answer is hashed."""
    from judgekeeper.readers import label_studio

    def sums(context: str) -> set:
        tasks = [{"id": i, "data": {"question": f"Q{i}?", "answer": f"A{i}.",
                                    "context": context},
                  "predictions": [{"model_version": "judge-a", "result": [
                      {"from_name": "verdict", "to_name": "answer", "type": "choices",
                       "value": {"choices": ["Pass"]}}]}],
                  "annotations": []} for i in range(3)]
        path = tmp_path / f"export-{context[-1]}.json"
        path.write_text(json.dumps(tasks), encoding="utf-8")
        return {r.mark.graded_fields for r in label_studio.read_label_studio(path)}

    assert None not in sums("doc A") and sums("doc A") != sums("doc B")


def test_a_mapped_item_with_other_fields_is_another_answer(tmp_path):
    """A file read with a saved map: the item's other fields count, every judge's score and
    reason and the fields that change on every run don't."""
    from judgekeeper.readers.mapped import read_mapped

    m = {"each": "", "id": "id", "input": "question", "output": "answer", "sides": None,
         "score": "scores.{judge}", "reason": "reasons.{judge}", "kind": "score",
         "judges": ["a", "b"], "judge": "a", "pass_mark": 0.5, "model_key": None}

    def sums(context: str, b: float = 0.9, seconds: int = 1) -> set:
        path = tmp_path / f"r-{context[-1]}-{b}-{seconds}.jsonl"
        path.write_text("".join(json.dumps({
            "id": f"q{i}", "question": f"Q{i}?", "answer": f"A{i}.", "context": context,
            "scores": {"a": 0.9, "b": b}, "reasons": {"a": "ok", "b": "fine"},
            "latency_seconds": seconds}) + "\n" for i in range(3)), encoding="utf-8")
        return {r.mark.graded_fields for _, recs in read_mapped(path, m) for r in recs}

    assert None not in sums("doc A") and sums("doc A") != sums("doc B")
    assert sums("doc A") == sums("doc A", b=0.1, seconds=9)  # another judge's grade, a time
