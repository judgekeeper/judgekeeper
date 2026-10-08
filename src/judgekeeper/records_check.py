"""`judgekeeper import records FILE --check`: what judgekeeper reads in a records file, in
plain words, without writing anything.

For each file: the number of records and the format version, the pass/fail split per judge
(with the same --pass-if and --label-map an import would use) with the pass mark used, the
judge's model and the ids, the human labels, the first 3 records (with their ids), the fields
kept without being known, a warning for a newer format version or a
record over 1 MB, and every problem with its line number. A file is usable when it has no
problem and at least one judge verdict reads as pass or fail. Several files end with how
`start` reads them (SEVERAL). Exit 0 when every file is usable, 2 when one is not.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from judgekeeper.anchors import SINGLE
from judgekeeper.metrics import ERROR
from judgekeeper.normalise import (
    PASS_IF_EXAMPLE,
    Normaliser,
    UnmappedValue,
    label_map_hint,
    parse_label_map,
)
from judgekeeper.records import (
    BIG,
    CODE,
    EVALUATOR_KEYS,
    HUMAN,
    LLM,
    ScoreRecord,
    _verdict_value,
    check_map,
    file_warnings,
    parse_map,
    problems,
    record_dict,
    source_rows,
)

EXIT_OK = 0
EXIT_USAGE = 2
SHOWN = 3  # records shown in plain words
SEVERAL = ("judgekeeper start reads the files of the same judge together, as one set: an answer "
           "saved in more than one file counts once, with the verdict from the newest file.")
TEXT_WIDTH = 80


@dataclass
class Checked:
    path: Path
    records: list[tuple[int, ScoreRecord]] = field(default_factory=list)
    problems: list[tuple[int, str]] = field(default_factory=list)
    unknown: dict[str, list[int]] = field(default_factory=dict)  # field: line numbers
    warnings: list[str] = field(default_factory=list)


def check_file(path: str | Path, column_map=None) -> Checked:
    """Read every line of a records file, keeping each problem instead of stopping."""
    path = Path(path)
    rows, cells = source_rows(path)
    mapping = parse_map(column_map)
    check_map(mapping, rows, path)
    checked = Checked(path)
    unknown: dict[str, list[int]] = defaultdict(list)
    n_big = 0
    for n, row, size in rows:
        if isinstance(row, str):
            checked.problems.append((n, row))
            continue
        d, found = record_dict(row, mapping, cells)
        found += problems(d)
        if found:
            checked.problems += [(n, p) for p in found]
            continue
        record = ScoreRecord.from_dict(d)
        for name in record.extra:
            unknown[name].append(n)
        for key in record.evaluator:
            if key not in EVALUATOR_KEYS:
                unknown[f"evaluator.{key}"].append(n)
        n_big += size > BIG
        checked.records.append((n, record))
    checked.unknown = dict(unknown)
    checked.warnings = file_warnings(path.name, [r for _, r in checked.records], n_big)
    return checked


def _plural(n: int, one: str, many: str | None = None) -> str:
    return f"{n} {one if n == 1 else many or one + 's'}"


def _lines_of(numbers: list[int]) -> str:
    if len(numbers) == 1:
        return f"line {numbers[0]}"
    shown = ", ".join(str(n) for n in numbers[:SHOWN])
    more = f" and {len(numbers) - SHOWN} more" if len(numbers) > SHOWN else ""
    return f"lines {shown}{more}"


def _short(value) -> str:
    if not isinstance(value, str):
        value = json.dumps(value, ensure_ascii=False)
    text = " ".join(value.split())
    return text[:TEXT_WIDTH - 1] + "…" if len(text) > TEXT_WIDTH else text


def _number(x: float) -> str:
    return f"{x:g}"


def _pass_mark(record: ScoreRecord):
    mark = (record.metadata or {}).get("pass_mark")
    return mark if isinstance(mark, int | float) and not isinstance(mark, bool) else None


def _said(record: ScoreRecord) -> str:
    who = {LLM: record.name, HUMAN: "A person", CODE: f"A code check ({record.name})"}[
        record.annotator_kind]
    verb = "labeled it" if record.annotator_kind == HUMAN else "said"
    if record.label is not None:
        parts = [f"score {_number(record.score)}"] if record.score is not None else []
        if record.score is not None and _pass_mark(record) is not None:
            parts.append(f"pass mark {_number(_pass_mark(record))}")
        score = f" ({', '.join(parts)})" if parts else ""
        return f"{who} {verb} {record.label}{score}."
    if record.score is not None:
        return f"{who} gave a score of {_number(record.score)}."
    return f"{who} gave no verdict."


def _agent_words(record: ScoreRecord) -> str | None:
    parts = []
    if record.trajectory:
        parts.append(_plural(len(record.trajectory), "agent step"))
    o = record.outcome
    if o:
        check = o.get("source") or "outcome check"
        if isinstance(o.get("passed"), bool):
            parts.append(f"{check}: {'passed' if o['passed'] else 'failed'}")
        else:
            parts.append(f"{check}: score {_number(o['score'])}")
    if record.app_version:
        parts.append(f"app version {record.app_version}")
    if not parts:
        return None
    text = "; ".join(parts) + "."
    return text[0].upper() + text[1:]


def _shown(n: int, record: ScoreRecord) -> list[str]:
    where = f"line {n} (id {record.target_id})" if record.target_id else f"line {n}"
    out = [f"    {where}: {_said(record)}"]
    for word, value in (("Input", record.input), ("Output", record.output),
                        ("Reason", record.explanation)):
        if value is not None:
            out.append(f"      {word}: {_short(value)}")
    agent = _agent_words(record)
    if agent:
        out.append(f"      {agent}")
    return out


def _and(items: list[str]) -> str:
    return items[0] if len(items) == 1 else f"{', '.join(items[:-1])} and {items[-1]}"


def _about_judge(records: list[ScoreRecord], pass_if: str | None) -> str:
    """The pass mark used, the judge's model and the ids, in one line."""
    marks = sorted({m for r in records if (m := _pass_mark(r)) is not None})
    if marks:
        mark = f"Pass mark{'s' if len(marks) > 1 else ''}: {_and([_number(m) for m in marks])}."
    elif pass_if:
        mark = f"Pass mark: --pass-if {pass_if}."
    elif any(r.label is None and r.score is not None for r in records):
        mark = "Pass mark: none."
    else:
        mark = "Pass mark: none (the verdicts are pass or fail)."
    models = sorted({str(r.evaluator["model"]) for r in records if r.evaluator.get("model")})
    if models:
        model = f"Judge's model{'s' if len(models) > 1 else ''}: {_and(models)}."
    else:
        model = "Judge's model: not in the records."
    ids = [str(r.target_id) for r in records if r.target_id]
    unique = list(dict.fromkeys(ids))
    if not ids:
        named = "Ids: none (judgekeeper makes one from each input and output)."
    else:
        shown = ", ".join(unique[:SHOWN]) + (", …" if len(unique) > SHOWN else "")
        within = "" if len(ids) == len(unique) and len(ids) == len(records) else (
            f" in {_plural(len(ids), 'record')} with an id")
        named = f"Ids: {len(unique)} unique{within} ({shown})."
    return f"    {mark} {model} {named}"


def _judge_line(name: str, records: list[ScoreRecord], norm: Normaliser) -> tuple[str, int]:
    """('Judge "name": 3 pass, 1 fail, ...', how many read as pass or fail)."""
    counts: Counter = Counter()
    unmapped = []
    for r in records:
        value = _verdict_value(r, norm.pass_if)
        try:
            verdict = norm(value).verdict
        except UnmappedValue as e:
            if isinstance(e.value, int | float) and not isinstance(e.value, bool):
                counts["score"] += 1
            else:
                counts["unmapped"] += 1
                if e.value not in unmapped:
                    unmapped.append(e.value)
            continue
        counts["none" if verdict == ERROR else verdict] += 1
    parts = [f"{counts['pass']} pass", f"{counts['fail']} fail"]
    if counts["none"]:
        parts.append(f"{counts['none']} with no verdict")
    if counts["score"]:
        parts.append(f"{_plural(counts['score'], 'score')} with no pass mark (add "
                     f"{PASS_IF_EXAMPLE})")
    if counts["unmapped"]:
        words = [str(v) for v in unmapped]
        parts.append(f"{_plural(counts['unmapped'], 'value')} judgekeeper cannot map "
                     f"({', '.join(repr(w) for w in words[:5])}; add "
                     f"{label_map_hint(words)})")
    return f'  Judge "{name}": {", ".join(parts)}.', counts["pass"] + counts["fail"]


def lines(checked: Checked, pass_if: str | None = None,
          label_map: str | None = None) -> tuple[list[str], bool]:
    """(what to print, whether the file is usable)."""
    records = [r for _, r in checked.records]
    newest = max((r.schema_version for r in records), default=1)
    head = f"{checked.path.name}: {_plural(len(records), 'record')}"
    out = [f"{head}, records format version {newest}." if records else f"{head}."]
    out += [f"  warning: {w}" for w in checked.warnings]

    norm = Normaliser(SINGLE, pass_if=pass_if, label_map=parse_label_map(label_map))
    judges: dict[str, list[ScoreRecord]] = defaultdict(list)
    for r in records:
        if r.annotator_kind == LLM:
            judges[r.name].append(r)
    readable = 0
    for name, judged in judges.items():
        line, n = _judge_line(name, judged, norm)
        out += [line, _about_judge(judged, pass_if)]
        readable += n
    humans = [r for r in records if r.annotator_kind == HUMAN]
    if humans:
        human_norm = Normaliser(SINGLE, label_map=parse_label_map(label_map))
        verdicts = Counter()
        for r in humans:
            try:
                verdicts[human_norm(_verdict_value(r, None)).verdict] += 1
            except UnmappedValue:
                verdicts["other"] += 1
        out.append(f"  Human labels: {len(humans)} ({verdicts['pass']} pass, "
                   f"{verdicts['fail']} fail).")
    else:
        out.append("  Human labels: none.")
    n_code = sum(r.annotator_kind == CODE for r in records)
    if n_code:
        out.append(f"  {_plural(n_code, 'code check')}: not a judge, left out.")

    if checked.records:
        out.append(f"  The first {min(SHOWN, len(records))} records:")
        for n, record in checked.records[:SHOWN]:
            out += _shown(n, record)
    if checked.unknown:
        known = ", ".join(f"{name} ({_lines_of(numbers)})"
                          for name, numbers in checked.unknown.items())
        out.append(f"  Kept {_plural(len(checked.unknown), 'field')} judgekeeper does not "
                   f"know: {known}.")

    if checked.problems:
        out.append(f"  {_plural(len(checked.problems), 'problem')}:")
        out += [f"    line {n}: {text}" for n, text in checked.problems]
        out.append("  judgekeeper cannot read this file until these are fixed.")
        return out, False
    if not records:
        out.append("  judgekeeper cannot read this file: it holds no records.")
        return out, False
    if not judges:
        out.append("  judgekeeper cannot read this file: it holds no judge records "
                   "(annotator_kind LLM, the default).")
        return out, False
    if not readable:
        out.append("  judgekeeper cannot use this file yet: no judge verdict reads as pass or "
                   "fail.")
        return out, False
    out.append("  judgekeeper can read this file.")
    return out, True


def run(paths, column_map=None, pass_if: str | None = None, label_map: str | None = None,
        say=print) -> int:
    """Check every file in `paths` (files, directories or globs); the exit code."""
    from judgekeeper.readers import expand_paths

    usable = True
    files = expand_paths("records", paths)
    for n, path in enumerate(files):
        if n:
            say("")
        text, ok = lines(check_file(path, column_map), pass_if, label_map)
        for line in text:
            say(line)
        usable = usable and ok
    if len(files) > 1:
        say("")
        say(SEVERAL)
    return EXIT_OK if usable else EXIT_USAGE
