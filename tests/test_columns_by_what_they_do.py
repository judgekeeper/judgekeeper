"""An extra column (or field) beside the answer counts by what it does, never by its name alone:
- what the LLM-as-a-judge writes (its explanation, reason, score) is left out;
- clear telemetry (a latency, a timestamp, a request id, a cost, token counts) is left out;
- any other column that changed on every answer while the answers stayed the same is per-run
  noise: left out, and said in one line;
- a column that changed on only some answers is the agent's: compared.
A pure re-grade read as "Your change made it worse"; a booking agent's wrong `date` on 10 rows
(the text the same, 10 now fail) read as "Only the grades changed"."""

import copy
import csv
import json

import pytest

from judgekeeper import before_after
from tests.start_projects import promptfoo_data
from tests.test_compare_after_check import _flat, _run

N = 80
BROKE_10 = f"On the {N} questions in both results: fixed 0, broke 10,"
JUDGE = ["confidence", "critique", "eval_reason", "evaluation", "explanation", "feedback",
         "grade_reason", "grader_notes", "judge_cost", "judge_explanation", "judge_latency_ms",
         "judge_output", "judge_reason", "judge_score", "rationale", "reason",
         "reasoning_judge", "score", "graded_at", "judge_reasoning", "eval_comment",
         "grade_level", "llmJudgeScore", "EvalReason"]
TELEMETRY = ["cost", "created_at", "duration_ms", "latency", "latency_ms", "request_id",
             "run_id", "timestamp", "tokens", "total_tokens", "trace_id", "completion_tokens",
             "cost_usd", "elapsed", "elapsed_s", "eval_id", "evaluated_at",
             "grader_model_version", "input_tokens", "judge_tokens", "output_tokens", "price",
             "prompt_tokens", "timestamp_utc", "ts", "updated_at"]
EVERY_ROW = ["date", "duration", "seconds", "time", "session",  # told by what they do
             "notes", "reasoning", "comments"]  # an agent's or a judge's: not by the name
CONTENT = ["agent_model", "category", "context", "documents", "expected_output", "messages",
           "metadata", "plan", "reference", "retrieved_docs", "sources", "sql", "steps",
           "system_prompt", "tags", "tool_calls", "tools_used", "trajectory", "date",
           "duration", "seconds", "time", "notes", "reasoning", "comments",
           # a judge's word inside another word is not the judge's
           "retrieval_context", "retrievalContext", "retrieval", "upgrade_path", "downgrade",
           "scoreboard", "evalue", "regrade_policy"]


def _said(capsys, *argv) -> tuple[int, str]:
    code, out = _run(capsys, *argv, "--no-browser", "--port", "0")
    _run(capsys, "--stop")
    return code, _flat(out)


def _rows(column: str, mode: str, ids: bool) -> list[dict]:
    """80 rows: question, answer, grade and `column`. `noise`: `column` new on every row and
    the first 10 passing ones fail; `content`: those 10 get a new `column` and fail."""
    rows, flipped = [], 0
    for i in range(1, N + 1):
        verdict, value = "pass" if i % 3 else "fail", f"value one for {i}"
        if mode == "noise":
            value = f"value two for {i}"
        if verdict == "pass" and flipped < 10 and mode in ("noise", "content"):
            verdict, flipped = "fail", flipped + 1
            if mode == "content":
                value = f"CHANGED value for {i}"
        rows.append({**({"id": f"q{i:03d}"} if ids else {}),
                     "input": f"Question {i}: what is {i}+{i}?", "output": f"It is {2 * i}.",
                     "verdict": verdict, column: value})
    return rows


def _table(path, column: str, mode: str, ids: bool = True, sep: str = ",") -> None:
    rows = _rows(column, mode, ids)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), delimiter=sep)
        w.writeheader()
        w.writerows(rows)


def _both_ways(tmp_path, monkeypatch, capsys, write, name: str):
    """The plain run after the first results, then --before on the two files."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CI", "true")
    write(tmp_path / f"base.{name.rsplit('.', 1)[1]}", "base")
    write(tmp_path / name, "base")
    assert _said(capsys, name)[0] == 0
    write(tmp_path / name, "new")
    plain = _said(capsys, name)
    before = _said(capsys, name, "--before", f"base.{name.rsplit('.', 1)[1]}")
    return plain, before


def _only_grades(plain, before) -> None:
    assert plain[0] == 0 and before_after.ONLY_GRADES in plain[1], plain[1]
    assert before[0] == 3 and before_after.ONLY_GRADES_BEFORE in before[1], before[1]


def _broke_10(plain, before) -> None:
    for code, out in (plain, before):
        assert code == 1 and BROKE_10 in out, out


def _left_out(out: str, column: str) -> bool:
    return f"Left out of the comparison: `{column}`, which changed on every answer" in out


@pytest.mark.parametrize("column", JUDGE + TELEMETRY)
def test_a_column_the_judge_or_the_run_writes_is_left_out(tmp_path, monkeypatch, capsys,
                                                          column):
    def write(path, side):
        _table(path, column, "noise" if side == "new" else "base")

    plain, before = _both_ways(tmp_path, monkeypatch, capsys, write, "results.csv")
    _only_grades(plain, before)
    assert not _left_out(plain[1], column), plain[1]  # known by its name: nothing to say


@pytest.mark.parametrize("column", EVERY_ROW)
def test_a_column_changed_on_every_answer_is_left_out_and_said(tmp_path, monkeypatch, capsys,
                                                               column):
    def write(path, side):
        _table(path, column, "noise" if side == "new" else "base")

    plain, before = _both_ways(tmp_path, monkeypatch, capsys, write, "results.csv")
    _only_grades(plain, before)
    for _, out in (plain, before):
        assert _left_out(out, column), out


@pytest.mark.parametrize("ids", [True, False], ids=["by-id", "by-text"])
@pytest.mark.parametrize("column", CONTENT)
def test_a_column_changed_on_some_answers_is_compared(tmp_path, monkeypatch, capsys, column,
                                                      ids):
    def write(path, side):
        _table(path, column, "content" if side == "new" else "base", ids)

    _broke_10(*_both_ways(tmp_path, monkeypatch, capsys, write, "results.csv"))


@pytest.mark.parametrize("column,mode", [("judge_reason", "noise"), ("context", "content")])
def test_a_tsv_counts_its_columns_the_same_way(tmp_path, monkeypatch, capsys, column, mode):
    def write(path, side):
        _table(path, column, mode if side == "new" else "base", sep="\t")

    plain, before = _both_ways(tmp_path, monkeypatch, capsys, write, "results.tsv")
    (_only_grades if mode == "noise" else _broke_10)(plain, before)


def test_a_context_changed_only_in_its_spaces_and_line_ends_is_the_same(tmp_path, monkeypatch,
                                                                        capsys):
    """As the answer's own text: spaces at the ends and Windows line ends don't count."""
    def write(path, side):
        rows = _rows("context", "noise" if side == "new" else "base", True)
        for r in rows:
            r["context"] = f"value one for {r['id']}" + ("  \r\n" if side == "new" else "")
        with path.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)

    _only_grades(*_both_ways(tmp_path, monkeypatch, capsys, write, "results.csv"))


def _jsonl(path, rows) -> None:
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def test_a_jsonl_of_its_own_leaves_out_the_judges_reason(tmp_path, monkeypatch, capsys):
    def write(path, side):
        rows = _rows("judge_reason", "noise" if side == "new" else "base", True)
        _jsonl(path, rows)

    _only_grades(*_both_ways(tmp_path, monkeypatch, capsys, write, "results.jsonl"))


@pytest.mark.parametrize("shape", ["tool-args", "context-dict"])
def test_a_jsonl_field_changed_deep_on_some_answers_is_compared(tmp_path, monkeypatch, capsys,
                                                                shape):
    """A tool call's argument (an `id` among them) or a document's body, new on 10 rows."""
    def write(path, side):
        rows = _rows("x", "content" if side == "new" else "base", True)
        for i, r in enumerate(rows):
            changed = r.pop("x").startswith("CHANGED")
            if shape == "tool-args":
                r["tool_calls"] = [{"name": "calc", "args": {"id": i, "b": i + changed}}]
            else:
                r["context"] = {"doc": {"title": f"Sums {i}", "body": "y" if changed else "x"}}
        _jsonl(path, rows)

    _broke_10(*_both_ways(tmp_path, monkeypatch, capsys, write, "results.jsonl"))


def test_what_the_judge_wrote_in_records_metadata_is_left_out(tmp_path, monkeypatch, capsys):
    def write(path, side):
        rows = _rows("x", "noise" if side == "new" else "base", True)
        _jsonl(path, [{"schema_version": 2, "target_id": r["id"], "name": "Correct",
                       "annotator_kind": "LLM", "label": r["verdict"], "input": r["input"],
                       "output": r["output"], "explanation": "e",
                       "metadata": {"judge_reason": f"{side} {r['x']}",
                                    "grader_notes": f"{side} notes {r['x']}"}} for r in rows])

    _only_grades(*_both_ways(tmp_path, monkeypatch, capsys, write, "results.jsonl"))


PF_META = ["cost", "created_at", "finishReason", "latency_ms", "latencyMs", "request_id",
           "requestId", "sessionId", "timestamp", "traceId", "http"]


@pytest.mark.parametrize("key", PF_META)
def test_promptfoo_response_metadata_a_run_writes_is_left_out(tmp_path, monkeypatch, capsys,
                                                              key):
    """The same tool calls; the transport headers (metadata.http) or a key the run writes
    new on every row, and 10 grades flipped."""
    verdicts = [i % 3 != 0 for i in range(N)]
    flip = [i for i, v in enumerate(verdicts) if v][:10]

    def write(path, side):
        new = side == "new"
        data = promptfoo_data([v and not (new and i in flip) for i, v in enumerate(verdicts)])
        for i, row in enumerate(data["results"]["results"]):
            meta = {"toolCalls": [{"name": "lookup_order", "args": {"id": i}}]}
            stamp = f"{side}-{i}"
            meta[key] = ({"status": 200, "headers": {"date": stamp, "x-request-id": stamp}}
                         if key == "http" else stamp)
            row["response"] = copy.deepcopy(row["response"]) | {"metadata": meta}
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")

    _only_grades(*_both_ways(tmp_path, monkeypatch, capsys, write, "output.json"))


@pytest.mark.parametrize("var", ["retrieval_context", "retrievalContext"])
def test_promptfoo_vars_changed_on_some_answers_are_compared(tmp_path, monkeypatch, capsys,
                                                             var):
    """The documents a RAG test retrieved, new on the 10 rows that now fail."""
    verdicts = [i % 3 != 0 for i in range(N)]
    flip = [i for i, v in enumerate(verdicts) if v][:10]

    def write(path, side):
        new = side == "new"
        data = promptfoo_data([v and not (new and i in flip) for i, v in enumerate(verdicts)])
        for i, row in enumerate(data["results"]["results"]):
            docs = f"Doc {i}: {'other' if new and i in flip else 'policy'} text."
            for at in (row["vars"], row["testCase"]["vars"]):
                at[var] = docs
        path.write_text(json.dumps(data), encoding="utf-8")

    _broke_10(*_both_ways(tmp_path, monkeypatch, capsys, write, "output.json"))

