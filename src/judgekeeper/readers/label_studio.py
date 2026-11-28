"""Label Studio: the JSON export of a project (a list of tasks).

Each task has `data` (the keys the labeling screen shows: the question and the answer),
`annotations` (what people chose) and `predictions` (what a model chose). Only `choices`
regions are read, the answers a person picks from a list; a `textarea` named like a reason
is the reason.

- People's labels are HUMAN lines, one per task. One person: their label. Several: the
  one marked `ground_truth`, else the label they all gave; tasks they disagree on are left
  out and counted. A cancelled annotation is no label.
- The grader is a prediction: one grader per `model_version`, the newest read. Its lines
  are CODE lines (judgekeeper does not know what made a prediction) with the version in
  `evaluator["version"]`.
- Of a person, only the number Label Studio gives them (`completed_by`) is kept, never an
  email, a name or any other field of theirs.

All of the file's shape is read in this one module (the `_`-named helpers below), so a
change in Label Studio's export is changed here only.
"""

from __future__ import annotations

from pathlib import Path

from judgekeeper import mapper
from judgekeeper.records import (
    CODE,
    HUMAN,
    Damaged,
    Mark,
    RecordList,
    RecordsError,
    ScoreRecord,
    all_damaged,
    damaged,
    graded_rest,
    load_json,
    read_rows,
)
from judgekeeper.textio import plural, read_utf8

TOOL = "Label Studio"
SOURCE = "label-studio"
SAVE_AGAIN = "Label Studio (Export, then JSON)"
NO_VERSION = "(no version)"
REASON_WORDS = (*mapper.REASON_WORDS, "note", "notes", "comment")
DISAGREED = ("People disagreed on {n} answers; they are left out of this number.",
             "People disagreed on 1 answer; it is left out of this number.")
OTHER_KINDS = "{what} of another kind ({kinds}) {be} left out: judgekeeper reads choices only."
SEVERAL_VERSIONS = ("{file} holds predictions from {n} versions ({names}). judgekeeper checks "
                    "the newest, {newest}. To check another one, run it with --metric VERSION.")


class NeedsMetric(RecordsError):
    """The file has more than one question with choices (`names`), or `asked` (--metric) is
    none of them. `names` are the from_names, in file order."""

    def __init__(self, file: str, names: list[str], asked: str | None = None):
        self.names, self.asked, self.file = names, asked, file
        super().__init__(f"{file} has more than one question with choices: "
                         f"{', '.join(names)}." if asked is None else
                         f"{file} has no question named {asked!r}: the names are "
                         f"{', '.join(names)}.")


class NoAnswerKey(RecordsError):
    """No key of the tasks' `data` holds the answer: `keys` are the names it has (never
    their values)."""

    def __init__(self, file: str, keys: list[str]):
        self.keys, self.file = keys, file
        shown = ", ".join(keys) if keys else "none"
        super().__init__(f"{file}: no key in the tasks' data holds the answer. The keys are: "
                         f"{shown}.")


def read_label_studio(path: str | Path, metric: str | None = None) -> RecordList:
    """The records of the Label Studio export at `path`. `metric`: the question to read (a
    `from_name`) when the file has several, or a prediction's model version to check."""
    path = Path(path)
    if path.suffix.lower() in (".csv", ".tsv"):
        return _read_flat(path, _csv_rows(path), metric)
    data = load_json(path, SAVE_AGAIN)
    if isinstance(data, list) and data and all(_is_flat(x) for x in data[:5]):
        return _read_flat(path, data, metric)
    if not isinstance(data, list):
        raise Damaged(f"{path.name} is not a Label Studio export: judgekeeper reads a list of "
                      "tasks.", f"export your project again as JSON from {SAVE_AGAIN}, then "
                      "run `{command}`.")
    rows = list(enumerate(data, 1))
    tasks = [(n, t) for n, t in rows if _is_task(t)]
    questions = _questions(t for _, t in tasks)
    version = None
    if metric is not None and metric not in questions:
        if metric not in _versions(t for _, t in tasks):
            raise NeedsMetric(path.name, questions, metric)
        version = metric
    control = None
    if questions:
        if len(questions) > 1 and metric not in questions:
            raise NeedsMetric(path.name, questions)
        control = metric if metric in questions else questions[0]
    keys = _keys(tasks)
    if tasks and keys[1] is None:
        raise NoAnswerKey(path.name, keys[2])

    records = RecordList(ids_derived=False, unit="task")
    records.ratings = []  # every person's label on a task two or more people labelled
    chosen = _grader_version(tasks, version)
    stats = _Stats()

    def read_one(t) -> None:
        if not _is_task(t):
            raise TypeError("a task that is not one")
        _read_task(records, t, control, keys, chosen, stats)

    read_rows(records, rows, read_one)
    all_damaged(path, SAVE_AGAIN, records)
    _notes(records, path.name, stats, tasks, version)
    records.prediction_ids = sum(  # predictions saved as their ids only: no grader in the file
        isinstance(p, int) and not isinstance(p, bool)
        for _, t in tasks for p in (t.get("predictions") if isinstance(
            t.get("predictions"), list) else []))
    return records


class _Stats:
    def __init__(self) -> None:
        self.disagreed = 0
        self.other: dict[str, int] = {}


def _is_task(t) -> bool:
    return (isinstance(t, dict) and isinstance(t.get("data"), dict)
            and (isinstance(t.get("annotations"), list) or isinstance(t.get("predictions"), list)))


# Which question, which keys, which version ----------------------------------------------

def _regions(parts):
    """Each region of each annotation or prediction in `parts` (the dicts)."""
    for part in parts if isinstance(parts, list) else []:
        if isinstance(part, dict):
            for region in part.get("result") if isinstance(part.get("result"), list) else []:
                if isinstance(region, dict):
                    yield region


def _questions(tasks) -> list[str]:
    """The `from_name` of every choices region in the file, in the order first met."""
    names: dict[str, None] = {}
    for t in tasks:
        for region in (*_regions(t.get("annotations")), *_regions(t.get("predictions"))):
            if region.get("type") == "choices" and isinstance(region.get("from_name"), str):
                names.setdefault(region["from_name"])
    return list(names)


def _versions(tasks) -> list[str]:
    seen: dict[str, None] = {}
    for t in tasks:
        for p in t.get("predictions") if isinstance(t.get("predictions"), list) else []:
            if isinstance(p, dict):
                seen.setdefault(_version_of(p))
    return list(seen)


def _version_of(prediction: dict) -> str:
    v = prediction.get("model_version")
    return str(v) if isinstance(v, str | int | float) and not isinstance(v, bool) and \
        str(v).strip() else NO_VERSION


def _grader_version(tasks, wanted: str | None) -> str | None:
    """The model version whose predictions are the grader: `wanted`, else the newest (the
    latest `created_at` among its predictions, then the highest prediction id, then the last
    met)."""
    if wanted is not None:
        return wanted
    best: dict[str, tuple] = {}
    for order, (_, t) in enumerate(tasks):
        for p in t.get("predictions") if isinstance(t.get("predictions"), list) else []:
            if isinstance(p, dict):
                key = (str(p.get("created_at") or ""), p.get("id") if isinstance(
                    p.get("id"), int) else 0, order)
                v = _version_of(p)
                best[v] = max(best.get(v, key), key)
    return max(best, key=best.__getitem__) if best else None


def _keys(tasks) -> tuple[str | None, str | None, list[str]]:
    """(the data key of the question or None, the key of the answer or None, every key)."""
    every: dict[str, None] = {}
    for _, t in tasks:
        for k in t["data"]:
            every.setdefault(str(k))
    names = list(every)

    def answer(k: str) -> bool:
        return (mapper._is(k, mapper.OUTPUT_WORDS) and not mapper._is(k, mapper.REFERENCE_WORDS)
                and not mapper._is(k, mapper.INPUT_WORDS)
                and mapper._last_word(k) not in mapper.ABOUT_WORDS)

    def question(k: str) -> bool:
        return (mapper._is(k, mapper.INPUT_WORDS) and not mapper._is(k, mapper.NOT_QUESTION_WORDS)
                and not mapper._is(k, mapper.REFERENCE_WORDS) and not answer(k))

    output = next((k for k in names if answer(k)), None)
    asked = ([k for k in names if question(k) and mapper._is(k, mapper.QUESTION_WORDS)]
             or [k for k in names if question(k)])
    return (asked[0] if asked else None), output, names


# One task ----------------------------------------------------------------------------------

def _read_task(records: RecordList, t: dict, control: str | None, keys, version: str | None,
               stats: _Stats) -> None:
    ask, answer, _ = keys
    data = t["data"]
    question = data.get(ask) if ask else None
    output = data.get(answer)
    target = t.get("id")
    target_id = str(target) if isinstance(target, str | int) and not isinstance(target, bool) \
        and str(target).strip() else None
    if target_id is None:
        raise TypeError("a task with no id")
    common = {"target_id": target_id, "name": control or "verdict", "input": question,
              "output": output,
              "mark": Mark(graded_fields=graded_rest(data, {ask, answer}))}  # the task's other data

    for kind, label in _predictions(t, control, version):
        records.append(ScoreRecord(
            annotator_kind=CODE, label=label[0], created_at=label[1],
            evaluator={"version": kind}, **common))
    found = _annotations(t, control, stats)
    chosen = _human(found, stats)
    if chosen is not None:
        who, word, at, reason, extra = chosen
        records.append(ScoreRecord(
            annotator_kind=HUMAN, label=word, created_at=at, explanation=reason,
            metadata={**({"who": who} if who is not None else {}), **extra}, **common))
    for who, word, at in _ratings(found):
        records.ratings.append(ScoreRecord(
            annotator_kind=HUMAN, label=word, created_at=at, metadata={"who": who}, **common))


def _choice(part: dict, control: str | None, stats: _Stats | None = None) -> str | None:
    """The word a part (an annotation or a prediction) chose on `control`; None when it chose
    none. Regions that are not choices are counted (`stats`) unless they are a reason."""
    word = None
    for region in _regions([part]):
        kind = region.get("type")
        if kind == "choices" and region.get("from_name") == control:
            picked = (region.get("value") or {}).get("choices") if isinstance(
                region.get("value"), dict) else None
            if isinstance(picked, list) and len(picked) == 1 and isinstance(picked[0], str) \
                    and picked[0].strip():
                word = picked[0]
        elif stats is not None and kind not in ("choices", "textarea") and isinstance(kind, str):
            stats.other[kind] = stats.other.get(kind, 0) + 1
    return word


def _reason(part: dict) -> str | None:
    for region in _regions([part]):
        if region.get("type") == "textarea" and isinstance(region.get("from_name"), str) \
                and mapper._is(region["from_name"], REASON_WORDS):
            value = region.get("value")
            text = value.get("text") if isinstance(value, dict) else None
            if isinstance(text, str):
                text = [text]
            if isinstance(text, list):
                joined = " ".join(x.strip() for x in text if isinstance(x, str) and x.strip())
                if joined:
                    return joined
    return None


def _person(annotation: dict):
    """The number Label Studio gives the person (`completed_by`), never more; None when it
    gives none (an object with no `id`, text)."""
    who = annotation.get("completed_by")
    if isinstance(who, dict):
        who = who.get("id")
    return who if isinstance(who, int) and not isinstance(who, bool) else None


def _predictions(t: dict, control: str | None, version: str | None):
    """(version, (word, time)) of each prediction of the grader's version on this task."""
    for p in t.get("predictions") if isinstance(t.get("predictions"), list) else []:
        if not isinstance(p, dict) or _version_of(p) != version:
            continue
        word = _choice(p, control)
        if word is not None:
            at = p.get("created_at")
            yield version, (word, at if isinstance(at, str) else None)


def _annotations(t: dict, control: str | None, stats: _Stats) -> list[dict]:
    """The task's labels from people, the latest of each person (by `created_at`): each
    {"who", "word", "at", "reason", "truth", "seconds", "annotation", "earlier"}, `earlier`
    the labels of that person this one replaced, oldest first. A cancelled annotation and one
    with no choice are no label."""
    latest: dict = {}
    for n, a in enumerate(t.get("annotations") if isinstance(t.get("annotations"), list) else []):
        if not isinstance(a, dict):
            continue
        word = _choice(a, control, stats)
        if a.get("was_cancelled") is True or word is None:
            continue
        who = _person(a)
        key = ("person", who) if who is not None else ("annotation", n)
        at = a.get("created_at") if isinstance(a.get("created_at"), str) else None
        mine = {"who": who, "word": word, "at": at, "reason": _reason(a),
                "truth": a.get("ground_truth") is True, "seconds": _seconds(a.get("lead_time")),
                "annotation": _annotation_id(a.get("id")), "earlier": []}
        old = latest.get(key)
        if old is None:
            latest[key] = mine
        elif (at or "") >= (old["at"] or ""):
            mine["earlier"] = [*old["earlier"], _brief(old)]
            latest[key] = mine
        else:  # a label read after a later one: the earlier of the two
            old["earlier"] = sorted([*old["earlier"], _brief(mine)], key=lambda e: e["at"] or "")
    return list(latest.values())


def _brief(label: dict) -> dict:
    return {k: label[k] for k in ("word", "at", "seconds", "annotation")}


def _seconds(value):
    """The time a person took, as Label Studio saved it (`lead_time`); None when it is not a
    number of seconds."""
    ok = isinstance(value, int | float) and not isinstance(value, bool)
    return value if ok and value >= 0 else None  # a NaN is not >= 0


def _annotation_id(value):
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _extra(label: dict) -> dict:
    """What a person's label keeps beside the number Label Studio gives them: the time they
    took, the annotation, and the labels of theirs it replaced."""
    out = {key: label[key] for key in ("seconds", "annotation") if label[key] is not None}
    if label["earlier"]:
        out["earlier"] = label["earlier"]
    return out


def _human(found: list[dict], stats: _Stats):
    """(who, word, time, reason, extra) of the task's one label from people, or None: one
    person's; of several, the `ground_truth` one, else the one they all gave; otherwise none
    (counted)."""
    if not found:
        return None
    if len(found) > 1:
        truth = [x for x in found if x["truth"]]
        if len(truth) == 1:
            found = truth
        elif len({x["word"].strip().lower() for x in found}) > 1:
            stats.disagreed += 1
            return None
    x = found[0]
    return x["who"], x["word"], x["at"], x["reason"], _extra(x)


def _ratings(found: list[dict]) -> list[tuple]:
    """(who, word, time) of each person's label on a task two or more people labelled: all of
    them, the ones they disagree on too (the agreement between people is worked out from
    these)."""
    named = [x for x in found if x["who"] is not None]
    if len({x["who"] for x in named}) < 2:
        return []
    return [(x["who"], x["word"], x["at"]) for x in named]


# What the file said ----------------------------------------------------------------------

def _notes(records: RecordList, file: str, stats: _Stats, tasks, asked: str | None) -> None:
    if stats.disagreed:
        many, one = DISAGREED
        records.notes.append(one if stats.disagreed == 1 else many.format(n=stats.disagreed))
    if stats.other:
        n = sum(stats.other.values())
        records.notes.append(OTHER_KINDS.format(
            what=plural(n, "label"), kinds=", ".join(sorted(stats.other)),
            be="is" if n == 1 else "are"))
    versions = _versions(t for _, t in tasks)
    if asked is None and len(versions) > 1:
        used = next((r.evaluator["version"] for r in records if r.annotator_kind == CODE), None)
        records.notes.append(SEVERAL_VERSIONS.format(
            file=file, n=len(versions), names=", ".join(versions), newest=used))


# The flat exports (JSON_MIN, CSV): one row per annotation ---------------------------------

FLAT_COLUMNS = ("annotator", "annotation_id")
KNOWN_COLUMNS = ("id", "annotator", "annotation_id", "created_at", "updated_at", "lead_time")


def is_flat_columns(columns) -> bool:
    """Whether `columns` are those of a JSON_MIN or CSV export: the columns that tell a
    person's label from a grader's verdict."""
    names = {str(c).strip() for c in columns}
    return all(c in names for c in FLAT_COLUMNS)


def _is_flat(row) -> bool:
    return isinstance(row, dict) and is_flat_columns(row) and "data" not in row


def _csv_rows(path: Path) -> list[dict]:
    import csv
    import io

    text = read_utf8(path, RecordsError)
    delimiter = "\t" if path.suffix.lower() == ".tsv" else ","
    try:
        return [dict(r) for r in csv.DictReader(io.StringIO(text, newline=""),
                                                delimiter=delimiter)]
    except csv.Error:
        raise damaged(path, SAVE_AGAIN, "is damaged (judgekeeper can't read it as a table)") \
            from None


def _read_flat(path: Path, rows: list, metric: str | None) -> RecordList:
    """People's labels from a flat export: a row per annotation, `id` the task, the data keys,
    the question's `from_name` as a column and a textarea column named like a reason. Rows
    with the same `id` are the people of one task (`ground_truth` and a cancelled annotation
    are not in these files: people who disagree are left out)."""
    rows = [(n, r) for n, r in enumerate(rows, 1)]
    good = [(n, r) for n, r in rows if isinstance(r, dict) and r.get("id") not in (None, "")]
    columns = list(dict.fromkeys(str(k) for _, r in good for k in r))
    keys = _keys([(n, {"data": {k: v for k, v in r.items() if k not in KNOWN_COLUMNS}})
                  for n, r in good])
    if good and keys[1] is None:
        raise NoAnswerKey(path.name, [c for c in columns if c not in KNOWN_COLUMNS])
    ask, answer, _ = keys
    reasons = [c for c in columns if mapper._is(c, REASON_WORDS)]
    questions = [c for c in columns if c not in KNOWN_COLUMNS and c not in (ask, answer)
                 and c not in reasons]
    if not questions:
        raise damaged(path, SAVE_AGAIN, "has no column with the labels")
    if len(questions) > 1 and metric not in questions:
        raise NeedsMetric(path.name, questions, metric)
    control = metric if metric in questions else questions[0]

    records = RecordList(ids_derived=False, unit="row")
    by_task: dict[str, dict] = {}
    order: list[str] = []
    for n, row in good:
        word = row.get(control)
        if not isinstance(word, str) or not word.strip():
            continue
        task_id = str(row["id"]).strip()
        who = _int(row.get("annotator"))
        at = row.get("created_at") if isinstance(row.get("created_at"), str) else None
        reason = next((str(row[c]).strip() for c in reasons
                       if isinstance(row.get(c), str) and row[c].strip()), None)
        if task_id not in by_task:
            order.append(task_id)
            by_task[task_id] = {"question": row.get(ask) if ask else None,
                                "output": row.get(answer), "people": {}}
        key = who if who is not None else ("row", n)
        mine = {"who": who, "word": word, "at": at, "reason": reason, "truth": False,
                "seconds": _seconds(_number(row.get("lead_time"))),
                "annotation": _int(row.get("annotation_id")), "earlier": []}
        old = by_task[task_id]["people"].get(key)
        if old is None:
            by_task[task_id]["people"][key] = mine
        elif (at or "") >= (old["at"] or ""):
            mine["earlier"] = [*old["earlier"], _brief(old)]
            by_task[task_id]["people"][key] = mine
        else:
            old["earlier"] = sorted([*old["earlier"], _brief(mine)], key=lambda e: e["at"] or "")
    records.ratings = []
    disagreed = 0
    for task_id in order:
        task = by_task[task_id]
        found = list(task["people"].values())
        common = {"target_id": task_id, "name": control, "annotator_kind": HUMAN,
                  "input": task["question"], "output": task["output"]}
        for who, word, at in _ratings(found):
            records.ratings.append(ScoreRecord(label=word, created_at=at,
                                               metadata={"who": who}, **common))
        if len({x["word"].strip().lower() for x in found}) > 1:
            disagreed += 1
            continue
        x = found[0]
        records.append(ScoreRecord(
            label=x["word"], created_at=x["at"], explanation=x["reason"],
            metadata={**({"who": x["who"]} if x["who"] is not None else {}), **_extra(x)},
            **common))
    if disagreed:
        many, one = DISAGREED
        records.notes.append(one if disagreed == 1 else many.format(n=disagreed))
    return records


def _int(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _number(value):
    """A number from a JSON number or a CSV cell; None when it is neither."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return value
    try:
        return float(value) if isinstance(value, str) and value.strip() else None
    except ValueError:
        return None
