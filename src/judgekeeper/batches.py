"""Batches: new eval answers join the marking.

The first pool is batch 1. When `judgekeeper` or `judgekeeper mark` finds newest results of the
same judge that hold graded answers not in the pool (by their exact question and answer text),
those answers become the next batch (`add`): pool.jsonl, start.json's queue and
pool-judge.jsonl get them, each pool line and queue entry with its `batch` (a line with none is
batch 1), and the marking page offers them first, half the judge passed and half it failed,
then any older batch's unmarked answers. A batch never removes or replaces an answer: one whose
text changed is a new answer. When the judge changed, that is `judgekeeper check`'s, and no
batch is added.

The numbers are stratified by batch (`strata`): each answer's stratum is (its batch, the group
it was picked from: the judge's grade then), and each marked answer weighs N_stratum /
n_stratum (weighted.stratified, weighted.general_strata). The first batch always counts; a
later one counts toward the result only when each of its non-empty strata has MIN_MARKS marks
or every answer in it marked (`counting`). A batch that doesn't count yet is left out, and the
result says so in one line (`line`); report.html and history.jsonl keep which batches counted
(`about`). With one batch, every number is the one judgekeeper gave before batches.
"""

from __future__ import annotations

import dataclasses
import json
import secrets
from collections import Counter

from judgekeeper.textio import plural

MIN_MARKS = 5  # marks in each stratum of a batch before it counts (or every answer in it)
ADDED = "Your newest results have {n} you haven't seen. {they} added for marking."


def added_line(n: int) -> str:
    """The line said when a batch is added."""
    return ADDED.format(n=plural(n, "answer", "answers"),
                        they="It's" if n == 1 else "They're")


def of(data: dict) -> dict[str, int]:
    """{answer id: its batch} from start.json's queue."""
    return {q["id"]: _batch(q) for q in data.get("queue") or []}


def _batch(q: dict) -> int:
    try:
        return int(q.get("batch") or 1)
    except (TypeError, ValueError):
        return 1


def strata(data: dict) -> tuple[dict[str, tuple[int, str]], dict[tuple[int, str], int]]:
    """({answer id: its stratum}, {stratum: how many answers of the pool it holds}), strata in
    order: by batch, the judge's passes before its fails. A stratum is (batch, the group the
    answer was picked from): after a re-check, the group it had then (start.json's
    `picked`). With one batch the sizes are the pool's counts as saved."""
    picked = data.get("picked") or {}
    groups = picked.get("groups") or {}
    where = {q["id"]: (_batch(q), groups.get(q["id"], q["group"]))
             for q in data.get("queue") or []}
    numbers = sorted({b for b, _ in where.values()}) or [1]
    if numbers == [1]:
        pool = picked.get("pool") or data.get("pool") or {}
        return where, {(1, g): int(pool.get(g) or 0) for g in ("pass", "fail")}
    counted = Counter(where.values())
    return where, {(b, g): counted[(b, g)] for b in numbers for g in ("pass", "fail")}


def _first(sizes: dict) -> int:
    return min((b for b, _ in sizes), default=1)


def counting(data: dict, labels: dict[str, str]) -> list[int]:
    """The batches that count toward the result, from the marks (`labels`: {id: "pass" or
    "fail"}): the first always; a later one when each of its non-empty strata has MIN_MARKS
    marks or every answer in it marked."""
    where, sizes = strata(data)
    marked = Counter(where[i] for i in labels if i in where)
    out = []
    for b in sorted({b for b, _ in sizes}):
        ready = all(marked[(b, g)] >= min(MIN_MARKS, sizes[(b, g)])
                    for g in ("pass", "fail") if sizes[(b, g)] > 0)
        if b == _first(sizes) or ready:
            out.append(b)
    return out


def counted_labels(data: dict, labels: dict[str, str]) -> dict[str, str]:
    """The marks of the batches that count."""
    batch = of(data)
    keep = set(counting(data, labels))
    return {i: m for i, m in labels.items() if batch.get(i, 1) in keep}


def counted_strata(data: dict, labels: dict[str, str]) -> list[tuple[int, str, int, int, int]]:
    """(batch, group, pool size, marked, marked Pass) for each stratum of the batches that
    count, in order (weighted.stratified)."""
    where, sizes = strata(data)
    keep = set(counting(data, labels))
    marked: Counter = Counter()
    passed: Counter = Counter()
    for i, m in labels.items():
        if i in where:
            marked[where[i]] += 1
            passed[where[i]] += m == "pass"
    return [(b, g, n, marked[(b, g)], passed[(b, g)]) for (b, g), n in sizes.items()
            if b in keep]


def about(data: dict, labels: dict[str, str]) -> dict | None:
    """Which batches the result is on, as report.html and history.jsonl keep it: {"counted",
    "of", "answers" (in the batches counted), "waiting" (answers in the others)}; None with
    one batch."""
    _, sizes = strata(data)
    numbers = sorted({b for b, _ in sizes})
    if len(numbers) < 2:
        return None
    counted = counting(data, labels)
    answers = sum(n for (b, _), n in sizes.items() if b in counted)
    return {"counted": counted, "of": len(numbers), "answers": answers,
            "waiting": sum(sizes.values()) - answers}


def line(batches: dict | None) -> str | None:
    """The line that says a batch is left out of the result: "This result is on 2 of 3
    batches (140 answers). 15 newer answers need a few marks first."; None when every batch
    counts."""
    if not batches or not batches.get("waiting"):
        return None
    waiting = batches["waiting"]
    need = "needs" if waiting == 1 else "need"
    return (f"This result is on {len(batches['counted'])} of {batches['of']} batches "
            f"({plural(batches['answers'], 'answer', 'answers')}). "
            f"{plural(waiting, 'newer answer', 'newer answers')} {need} a few marks first.")


def _text(question, answer) -> str:
    return json.dumps([question, answer], sort_keys=True, ensure_ascii=False)


def new_answers(ws, found) -> list:
    """The graded answers in the newest results (`found`) that the pool does not hold, by their
    exact question and answer text (scrubbed, as pool.jsonl keeps them), each once."""
    from judgekeeper.redact import scrub_value
    from judgekeeper.textio import jsonl_lines

    newest = set(found.used) if found.tool in ("records", "mapped") else {found.used[0]}
    seen = set()
    for raw in jsonl_lines(ws.pool.read_text(encoding="utf-8")):
        if raw.strip():
            row = json.loads(raw)
            seen.add(_text(row.get("input"), row.get("output")))
    out = []
    for a in found.pool.answers:
        key = _text(scrub_value(a.input), scrub_value(a.output))
        if a.source in newest and a.verdict in ("pass", "fail") and key not in seen:
            seen.add(key)
            out.append(a)
    return out


def add(ws, found) -> int:
    """Add the new graded answers in the newest results (`found`, the same judge as the marks)
    as the next batch, in front of the pool: its queue a seeded shuffle as the first batch's
    (start_label.build_queue). Returns how many were added."""
    from judgekeeper.anchors import canonical_hash
    from judgekeeper.fingerprint import JudgeFingerprint, utc_now
    from judgekeeper.judgments import read_run, write_run
    from judgekeeper.start_label import _scrubbed, _write_json, build_queue, judge_record
    from judgekeeper.textio import jsonl_lines, write_replacing

    if not ws.start.is_file() or not ws.pool.is_file():
        return 0
    data = ws.data()
    new = new_answers(ws, found)
    if not new:
        return 0
    batch = max(of(data).values(), default=1) + 1
    old_rows = [json.loads(x) for x in jsonl_lines(ws.pool.read_text(encoding="utf-8"))
                if x.strip()]
    taken = {r["id"] for r in old_rows}
    named = []
    for a in new:  # an id an older answer with other text has (a table's own ids) is renamed
        i, k = a.id, 2
        while i in taken:
            i, k = f"{a.id}~{k}", k + 1
        taken.add(i)
        named.append(dataclasses.replace(a, id=i))
    seed = secrets.randbelow(2**31)
    queue = [{**q, "batch": batch} for q in build_queue(named, seed)]
    by_id = {a.id: a for a in named}
    rows = _scrubbed([{"id": q["id"], "input": by_id[q["id"]].input,
                       "output": by_id[q["id"]].output, **by_id[q["id"]].agent, "batch": batch}
                      for q in queue])
    pool = rows + old_rows
    write_replacing(ws.pool, "".join(json.dumps(p, ensure_ascii=False) + "\n" for p in pool))
    pool_sha = canonical_hash(pool)
    head, records = read_run(ws.pool_judge)
    lines = [judge_record(by_id[q["id"]], found) for q in queue] + list(records.values())
    write_run(ws.pool_judge, head.get("run", 1), pool_sha,
              JudgeFingerprint.from_dict(found.fingerprint), lines, source=head.get("source"),
              normaliser=head.get("normaliser"))
    queue += data.get("queue") or []
    kinds = [q["group"] for q in queue]
    added = data.get("batches") or [{"batch": 1, "results_files": data.get("results_files"),
                                     "added_at": data.get("started_at"),
                                     "seed": data.get("seed")}]
    added.append({"batch": batch, "results_files": list(found.used), "added_at": utc_now(),
                  "seed": seed, "answers": len(named)})
    data.update(queue=queue, batches=added, pool_sha256=pool_sha, updated_at=utc_now(),
                pool={**(data.get("pool") or {}), "answers": len(queue),
                      "pass": kinds.count("pass"), "fail": kinds.count("fail")})
    _write_json(ws.start, data)
    return len(named)
