"""A results file in a project's own format, read with the map `judgekeeper` saved in
judgekeeper.toml after the person's yes (see mapper.py for the paths).

One judged answer per item, side and judge: a record with the item's input, the side's
output, the judge's name, and the verdict: a score with its pass/fail from the pass mark, or
a verdict value as written (pass/fail, true/false, or what --label-map maps). The judge's
model comes from the map's `model_key` (a path, in the item or around it) or from the
settings; the pass mark from `pass_mark_key` (where the file states it, so each run's own)
or from the settings.

When the items are inside a unit (a JSONL line holding a list of cases: often one eval run),
each unit is its own RecordList, newest (last) first, so `start` uses the newest run first, as
it does for any other tool's files. When each line or row is itself one item (a flat file),
the whole file is one RecordList.

A map that no longer fits the file (the items, an input or an answer missing) is an error
with one plain message: CHANGED_SHAPE.
"""

from __future__ import annotations

from pathlib import Path

from judgekeeper import mapper
from judgekeeper.records import (
    LLM,
    RecordList,
    RecordsError,
    ScoreRecord,
    derive_record_id,
    read_rows,
)

CHANGED_SHAPE = ("Your results file changed shape. Remove the [start] table from "
                 "judgekeeper.toml, then run {program} again to read it anew.")


def read_mapped(path: str | Path, m: dict, label: str | None = None
                ) -> list[tuple[str, RecordList]]:
    """[(label, records)] for each unit of the file, newest first.

    `m` is the map (each, id, input, output, sides, score, reason, kind, judges, model_key)
    plus the settings: `judge` (a name, "*" for every judge, or None when the file has one),
    `pass_mark`, `model` (the judge's model when the file does not say it), and `leave_out`
    (leave out answers with an error or a score made by a rule)."""
    path = Path(path)
    label = label or path.name
    skipped: list[int] = []  # lines that are not JSON
    try:
        units = mapper.load_numbered(path, skipped)
    except mapper.MapError as e:
        raise RecordsError(str(e)) from None
    flat = not m["each"]
    many = not flat and (path.suffix.lower() in (".jsonl", ".ndjson") or len(units) > 1)
    unnamed = mapper.parse(m["score"])[-1][0]
    out = []
    for n, unit in units:
        records = RecordList(ids_derived=not m.get("id"), unit="line" if flat else "item")

        def read_item(found: tuple[dict, list], records=records) -> None:
            item, up = found
            if not isinstance(item, dict):
                raise TypeError("an item that is not an object")
            try:
                question = mapper.get(item, m["input"])
                model = _model(item, up, m)
                mark = {**m, "pass_mark": _pass_mark(item, up, m)}
                for side in m.get("sides") or [None]:
                    answer = mapper.get(item, m["output"], side)
                    for judge in mapper.judges_read(m):
                        records += _records(item, side, judge, question, answer, model, mark,
                                            unnamed)
            except mapper.Missing:  # in a flat file, one row; else the map no longer fits
                if not flat:
                    raise
                raise KeyError("a field the map reads") from None

        if flat and not isinstance(unit, dict):  # one answer per line: this one is damaged
            records.left_out.append(n)
        try:
            found = mapper.items(unit, m["each"])
            read_rows(records, [(n, x) for x in found] if flat else enumerate(found, 1),
                      read_item)
        except mapper.Missing:
            raise _changed_shape() from None
        out.append((f"{label} line {n}" if many else label, records))
    if flat:
        records = RecordList((r for _, recs in out for r in recs), ids_derived=not m.get("id"),
                             unit="line")
        records.left_out = sorted(skipped + [x for _, recs in out for x in recs.left_out])
        if records.left_out and not records:
            raise _changed_shape()
        return [(label, records)]
    out.reverse()
    return out


def _changed_shape() -> RecordsError:
    from judgekeeper.textio import program

    return RecordsError(CHANGED_SHAPE.format(program=program()))


def _records(item, side, judge, question, answer, model, m, unnamed) -> list[ScoreRecord]:
    try:
        value = mapper.get(item, m["score"], side, judge)
    except mapper.Missing:
        value = None
    reason = None
    if m.get("reason"):
        try:
            reason = mapper.get(item, m["reason"], side, judge)
        except mapper.Missing:
            reason = None
    if m.get("leave_out") and mapper.made_by_a_rule(value, reason):
        return []
    score, verdict = None, None
    if m.get("kind", "score") == "score":
        score = mapper.number(value)
        if score is not None and m.get("pass_mark") is not None:
            verdict = "pass" if score >= m["pass_mark"] else "fail"
    else:
        verdict = value
    item_id = None
    if m.get("id"):
        try:
            item_id = str(mapper.get(item, m["id"]))
        except mapper.Missing:
            item_id = None
    if item_id is not None and side is not None:
        item_id = f"{item_id}:{side}"
    return [ScoreRecord(
        target_id=item_id or derive_record_id(question, answer),
        name=judge if judge is not None else unnamed, annotator_kind=LLM, label=verdict,
        score=float(score) if score is not None else None,
        explanation=None if reason is None else str(reason), input=question, output=answer,
        evaluator={"model": model} if model else {},
        metadata={"pass_mark": m["pass_mark"]} if verdict is not None and score is not None
        else {})]


def _model(item: dict, up: list, m: dict) -> str | None:
    key = m.get("model_key")
    if key:
        value = mapper.value_around(item, up, key)
        if isinstance(value, str) and value.strip():
            return value
    return m.get("model")


def _pass_mark(item: dict, up: list, m: dict):
    """The pass mark the file states for this item or its run (pass_mark_key), else the
    saved one."""
    key = m.get("pass_mark_key")
    if key:
        value = mapper.number(mapper.value_around(item, up, key))
        if value is not None:
            return value
    return m.get("pass_mark")


__all__ = ["CHANGED_SHAPE", "read_mapped"]
