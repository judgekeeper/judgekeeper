"""Batches: new eval answers join the marking.

The first pool is batch 1. When `judgekeeper` or `judgekeeper mark` finds newest results of the
same judge holding graded answers not in the pool (by exact question and answer text), those
answers become the next batch (`add`). A batch never removes or replaces an answer: one whose
text changed is a new answer. When the judge changed, that is for `judgekeeper check`, and no
batch is added.

The numbers are stratified by batch (`strata`): a stratum is (batch, the judge's grade it was
picked from), and each marked answer weighs N_stratum / n_stratum. The first batch always
counts; a later one counts only once each of its non-empty strata has marks in proportion to
its size, against the first batch's stratum of the same grade (`need`), or is fully marked
(`counting`), so a large new batch does not widen the ranges after a few marks. Until then it is left out, and the result says so in one line
(`line`). With one batch, every number is the same as with no batches.
"""

from __future__ import annotations

import dataclasses
import json
import math
import secrets
from collections import Counter

from judgekeeper.textio import loads, plural

MIN_MARKS = 5  # marks a stratum as big as the first batch's needs before its batch counts
MOST_MARKS = 15  # the most a stratum of a later batch needs, however big
ADDED = "Your newest results have {n} you haven't seen. {they} added for marking."


def added_line(n: int) -> str:
    """The line said when a batch is added."""
    return ADDED.format(n=plural(n, "answer", "answers"),
                        they="It's" if n == 1 else "They're")


def waiting_line(n: int, changed: bool = False, worse: bool = False) -> str:
    """The line said when the newest results hold `n` new answers that join no batch, as they
    came with changed grades (or a changed judge, `changed`): they join once `judgekeeper
    check` took the change (the Next: line names it); after a "Worse" (`worse`), once the
    judge is the marks' again or a changed one is checked."""
    what = "your changed LLM-as-a-judge" if changed else "changed grades"
    they = "it waits" if n == 1 else "they wait"
    then = ("you go back to your old LLM-as-a-judge or check a changed one" if worse
            else "your changed LLM-as-a-judge is checked")
    return f"{plural(n, 'new answer', 'new answers')} came with {what}, so {they} until {then}."


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


def need(size: int, first: int) -> int:
    """The marks a stratum of `size` answers of a later batch needs before its batch counts:
    MIN_MARKS times its size over the first batch's stratum of the same grade (`first`),
    rounded up, at least 1 and at most MOST_MARKS (MOST_MARKS when the first has none), and
    never more than the stratum holds."""
    want = MOST_MARKS if first <= 0 else min(math.ceil(MIN_MARKS * size / first), MOST_MARKS)
    return min(max(want, 1), size)


def counting(data: dict, labels: dict[str, str], known: tuple | None = None) -> list[int]:
    """The batches that count toward the result, from the marks (`labels`: {id: "pass" or
    "fail"}): the first always; a later one when each of its non-empty strata has the marks
    `need` asks for. `known`: strata(data), when the caller has it."""
    where, sizes = known or strata(data)
    marked = Counter(where[i] for i in labels if i in where)
    first = _first(sizes)
    out = []
    for b in sorted({b for b, _ in sizes}):
        ready = all(marked[(b, g)] >= need(sizes[(b, g)], sizes.get((first, g), 0))
                    for g in ("pass", "fail") if sizes[(b, g)] > 0)
        if b == _first(sizes) or ready:
            out.append(b)
    return out


def counted_labels(data: dict, labels: dict[str, str]) -> dict[str, str]:
    """The marks of the batches that count."""
    batch = of(data)
    keep = set(counting(data, labels))
    return {i: m for i, m in labels.items() if batch.get(i, 1) in keep}


def counted_strata(data: dict, labels: dict[str, str],
                   known: tuple | None = None) -> list[tuple[int, str, int, int, int]]:
    """(batch, group, pool size, marked, marked Pass) for each stratum of the batches that
    count, in order (weighted.stratified). `known`: strata(data), when the caller has it."""
    where, sizes = known or strata(data)
    keep = set(counting(data, labels, (where, sizes)))
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
    need = "needs a mark" if waiting == 1 else "need a few marks"
    return (f"This result is on {len(batches['counted'])} of {batches['of']} batches "
            f"({plural(batches['answers'], 'answer', 'answers')}). "
            f"{plural(waiting, 'newer answer', 'newer answers')} {need} first.")


def results_key(found) -> str:
    """The newest results (`found`) as start.json's `results_seen` keeps them: their files and
    each answer's grade. Once said ("Your eval ran again") or added as a batch, the same
    results are not said again."""
    import hashlib

    grades = sorted((str(a.id), str(a.verdict)) for a in found.pool.answers)
    text = json.dumps([list(map(str, found.used)), grades], ensure_ascii=False)
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def seen(ws, found) -> None:
    """start.json keeps that the newest results (`found`) were said (results_key)."""
    from judgekeeper.start_label import _write_json

    data = ws.data()
    data["results_seen"] = results_key(found)
    _write_json(ws.start, data)


def _text(question, answer) -> str:
    return json.dumps([question, answer], sort_keys=True, ensure_ascii=False)


POOL_DAMAGED = ("judgekeeper can't read .judgekeeper/pool.jsonl, so the answers there can't "
                "be marked.")
START_OVER = "run `{program} --new` to start over: your marks move to .judgekeeper/previous-<date>/"


def new_answers(ws, found) -> list:
    """The graded answers in the newest results (`found`) that the pool does not hold, by their
    exact question and answer text (scrubbed, as pool.jsonl keeps them), each once. An answer
    asked as a pool row's question is that row's, as check.lookup finds it: grading
    marked-answers.csv again (promptfoo's vars then hold the answer too) adds none. A damaged
    pool.jsonl is a StartError (POOL_DAMAGED)."""
    from judgekeeper.check import _marked_question, _questions
    from judgekeeper.check import _text as answer_text
    from judgekeeper.redact import scrub_value
    from judgekeeper.start import StartError
    from judgekeeper.textio import jsonl_lines, program

    newest = set(found.used) if found.tool in ("records", "mapped") else {found.used[0]}
    queued = {q["id"] for q in ws.data().get("queue") or []}
    seen = set()
    marked = set()  # (answer text, question text) of each pool row, as check.lookup finds it
    for raw in jsonl_lines(ws.pool.read_text(encoding="utf-8")):
        if raw.strip():
            try:
                row = loads(raw)
                if row["id"] not in queued:  # of a batch whose adding stopped: new again
                    continue
                seen.add(_text(row.get("input"), row.get("output")))
                text = answer_text(row.get("output"))
                marked |= {(text, q) for q in _marked_question(row.get("input"), row.get("output"))}
            except (ValueError, AttributeError, KeyError, TypeError):  # damaged, or not an object
                raise StartError(POOL_DAMAGED,
                                 next_step=START_OVER.format(program=program())) from None
    out = []
    for a in found.pool.answers:
        key = _text(scrub_value(a.input), scrub_value(a.output))
        if a.source not in newest or a.verdict not in ("pass", "fail") or key in seen:
            continue
        text = answer_text(a.output)
        if any((text, q) in marked for q in _questions(a.input)):
            continue
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
    # the pool rows and grades of a batch whose adding stopped half way go: it is added again
    queued = {q["id"] for q in data.get("queue") or []}
    old_rows = [r for x in jsonl_lines(ws.pool.read_text(encoding="utf-8"))
                if x.strip() and (r := loads(x))["id"] in queued]
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
    lines = ([judge_record(by_id[q["id"]], found) for q in queue]
             + [r for i, r in records.items() if i in queued])
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
                results_seen=results_key(found),
                pool={**(data.get("pool") or {}), "answers": len(queue),
                      "pass": kinds.count("pass"), "fail": kinds.count("fail")})
    _write_json(ws.start, data)
    return len(named)
