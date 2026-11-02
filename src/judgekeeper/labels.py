"""`--labels [FILE]`: Pass/Fail labels people already have, used as their marks.

`--labels FILE` reads them from a CSV, TSV or JSONL file: an answer column (`output` or
`answer`), a label column (`label` or `human_label`), and optionally the question (`input` or
`question`) and an `id`. `--labels` alone uses the labels people gave that are already in the
results (start.Pool.humans). Asked for every time, never automatic.

A label counts only for an answer the LLM-as-a-judge graded Pass or Fail (the queue in
start.json), and for each repeat of it. A file's label finds its answer by id (with the same
answer text), else by the exact answer text (check's normalising: line endings, the space at
both ends, keys hidden, a spreadsheet's guard quote), with the question when one is given. Each
label becomes one line of marks.jsonl (marks.imported_line, "by": "file"); an answer that
already has a mark keeps it. The words are read as grades are (normalise.Normaliser), with the
project's label map; anything else stops before a line is written.

Imported marks are checked against the page's: no coloured verdict until PAGE_MARKS page marks
in each of the LLM-as-a-judge's groups, or none left to mark there (still_needed); then, per
group, Fisher's exact test on the share marked Pass, imported against page marks, and a
warning when p < CHECK_LEVEL in either group (looks_off). Never a stop.
"""

from __future__ import annotations

import math
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

from judgekeeper import marks
from judgekeeper.normalise import Normaliser, UnmappedValue, _numeric
from judgekeeper.redact import scrub
from judgekeeper.textio import ANOTHER_DRIVE, from_here, is_link, plural, runnable

IN_RESULTS = "\0results"  # --labels with no FILE (argparse's const): never a file's name
RESULTS_NAME = "your results"
ANSWER_COLUMNS = ("output", "answer")
QUESTION_COLUMNS = ("input", "question")
LABEL_COLUMNS = ("human_label", "label")  # start.HUMAN_COLUMNS
EXCEL = (".xlsx", ".xlsm", ".xls", ".xlsb", ".ods", ".numbers")
WORDS_SHOWN = 5
WORD_WIDTH = 40  # characters of a word shown
NO_MATCH, NOT_GRADED, MORE_THAN_ONE, BOTH = "no_match", "not_graded", "ambiguous", "both"
SKIPPED = (  # (reason, one, many): said in this order
    (NO_MATCH, "{n} doesn't match any answer in your results (the answer text must be the same)",
     "{n} don't match any answer in your results (the answer text must be the same)"),
    (NOT_GRADED, "{n} is for an answer your LLM-as-a-judge didn't grade Pass or Fail",
     "{n} are for answers your LLM-as-a-judge didn't grade Pass or Fail"),
    (MORE_THAN_ONE, ("{n} matches more than one answer (add a question column to tell them "
                     "apart)"),
     "{n} match more than one answer (add a question column to tell them apart)"),
    (BOTH, "{n} is for an answer labelled both Pass and Fail",
     "{n} are for answers labelled both Pass and Fail"))
ASSUMES = ("{k} of your marks came from {name}. The numbers assume those answers were picked at "
           "random and labelled without looking at your LLM-as-a-judge's grade.")
FOUND = ("Found {n} in your results. To use them as your marks, run: {command}")
# The check of imported marks against page marks (see the top)
PAGE_MARKS = 15  # page marks per group of the LLM-as-a-judge before a verdict, and the check
CHECK_LEVEL = 0.025  # 0.05 split over the two groups
GATE = ("Mark at least {n} more answers on the page to check the marks from {name}. Until "
        "then, it's too early to tell.")
LOOKS_OFF = ("Your marks from {name} don't look like your marks on the page. Of the answers "
             "your LLM-as-a-judge {did}, you passed {x}% of those from {name} and {y}% of "
             "those you marked on the page. The numbers may be off.")
GROUP_DID = {"pass": "passed", "fail": "failed"}


class LabelsStop(Exception):
    """The labels can't be used as they are: `lines` say why; `next_step`, when there is one,
    is the Next: line. Nothing was written."""

    def __init__(self, lines: list[str], next_step: str | None = None):
        super().__init__(" ".join(lines))
        self.lines, self.next_step = lines, next_step


@dataclass(frozen=True)
class Label:
    """One label: its mark, and how it finds its answer: `key`, the answer id the results gave
    it (--labels alone), or a file's `id`, answer (`output`) and question (`input`)."""

    mark: str
    output: object = None
    input: object = None
    id: str | None = None
    key: str | None = None


def _plain(command: Callable[..., str] | None) -> Callable[..., str]:
    return command or (lambda *extra: " ".join(("judgekeeper", *extra)))


def shown_name(source: str) -> str:
    """How a label's "from" is said: "your results", or the file's base name."""
    return RESULTS_NAME if source == marks.FROM_RESULTS else source


def names(sources) -> str:
    """"a.csv", "a.csv and b.csv", "a.csv, b.csv and c.csv"."""
    said = [shown_name(s) for s in sources]
    return said[0] if len(said) == 1 else f"{', '.join(said[:-1])} and {said[-1]}"


def assumes_line(imported: dict | None) -> str | None:
    """The one line said wherever a result counts imported marks (marks.imported)."""
    if not imported or not imported.get("marks"):
        return None
    return ASSUMES.format(k=imported["marks"], name=names(imported.get("from") or ["a file"]))


def found_line(n: int, command: str) -> str:
    """The Find line when the results hold human labels and --labels was not given."""
    return FOUND.format(n=plural(n, "Pass/Fail label", "Pass/Fail labels"), command=command)


# The file ----------------------------------------------------------------------------------

def check_file(given: str, command: Callable[..., str] | None = None,
               command_in: Callable[..., str] | None = None) -> Path:
    """The labels file named `given`, before anything is found or written: a LabelsStop for a
    folder, an Excel file, a missing file, a link, or something that is not a file. The file
    is named by its base name, a folder from here; a Next line gives the path from here
    (textio.from_here). `command_in(folder, *extra)`: the command run on that folder."""
    from judgekeeper import find

    command = _plain(command)
    name = Path(given).name or given
    if not given.strip():
        raise LabelsStop([f"Give the labels file: {command('--labels', '<file>')}"])
    path = Path(given)
    try:
        folder = path.is_dir() and not is_link(path)
    except OSError:
        folder = False
    if folder:
        where = from_here(given, labels=False)
        lines = [(f"{name if where in ANOTHER_DRIVE else where} is a folder. Give the labels "
                  f"file instead: {command('--labels', '<file>')}")]
        if find.is_project(path) or _has_results(path):
            at = runnable(given, labels=False)  # `~/` outside the quotes; never %USERPROFILE%
            lines.append(f"To check that folder, put it first: "
                         f"{command_at(command, at, command_in)}")
        raise LabelsStop(lines)
    if path.suffix.lower() in EXCEL:
        csv_name = runnable(str(path.with_suffix(".csv")) if str(path.parent) != "."
                            else f"{path.stem}.csv", labels=True)
        raise LabelsStop([(f"judgekeeper can't read Excel files. Save {name} as CSV, then run: "
                           f"{command('--labels', csv_name)}")])
    if is_link(path):
        kind = "folder" if os.path.isdir(path) else "file"
        raise LabelsStop([(f"{name} is a link to another {kind}. judgekeeper does not read "
                           "labels through links. Give the file itself.")])
    if not path.exists():
        raise LabelsStop([(f"Can't find {name}. Check the name and folder, then run: "
                           f"{command('--labels', '<file>')}")])
    if not path.is_file():
        from judgekeeper.textio import not_a_file_message

        raise LabelsStop([not_a_file_message(path, "device or pipe")])
    return path


def command_at(command: Callable[..., str], folder: str,
               command_in: Callable[..., str] | None = None) -> str:
    """`judgekeeper [mark] FOLDER --labels <file>`: the folder as the project, where the
    command takes its path (`command_in`; without it, after the first word). `folder` is
    ready for the shell (textio.runnable)."""
    if command_in:
        return command_in(folder, "--labels", "<file>")
    words = command("--labels", "<file>").split(" ")
    return " ".join((words[0], folder, *words[1:]))


def _has_results(folder: Path) -> bool:
    from judgekeeper import find

    try:
        return any(find.search(folder).results.values())
    except (OSError, ValueError):
        return False


def _used(column) -> bool:
    """A column read_file may use: an id, question, answer or label."""
    return str(column).strip().lower() in (*ANSWER_COLUMNS, *QUESTION_COLUMNS, *LABEL_COLUMNS,
                                           "id")


def _column(columns, wanted: tuple[str, ...]) -> str | None:
    """The first column named one of `wanted`, case and the space at both ends ignored."""
    plain = {str(c).strip().lower(): c for c in reversed(list(columns))}
    return next((plain[w] for w in wanted if w in plain), None)


def read_file(path: Path, given: str, label_map: dict | None = None,
              command: Callable[..., str] | None = None) -> list[Label]:
    """The labels in the file at `path` (named `given` on the command line). A LabelsStop when
    it can't be read as labels, lacks the columns, or holds a number or a word that isn't Pass
    or Fail. A blank label is left out without a word."""
    from judgekeeper import find
    from judgekeeper.table import TableError, open_quote, read_kept

    name = path.name
    if path.suffix.lower() not in find.TABLE_SUFFIXES:
        raise LabelsStop([(f"judgekeeper reads labels from a CSV, TSV or JSONL file; {name} is "
                           "none of these.")])
    try:
        line = open_quote(path) if path.suffix.lower() in (".csv", ".tsv") else None
        if line is not None:
            raise LabelsStop([(f"{name} has a quote that never closes (line {line}). Fix it, "
                               "then run judgekeeper again.")])
        rows = read_kept(path, _used)  # every row (the size question guards), its cells
        # used only: a big notes column is never held
    except TableError as e:
        raise LabelsStop([scrub(str(e))]) from None
    if not rows:
        raise LabelsStop([f"{name} has no labels."])
    columns = list(dict.fromkeys(c for row in rows for c in row))
    out_col, label_col = _column(columns, ANSWER_COLUMNS), _column(columns, LABEL_COLUMNS)
    if out_col is None or label_col is None:
        raise LabelsStop([(f"{name} needs an answer column (output or answer) and a label column "
                           "(label or human_label).")])
    in_col, id_col = _column(columns, QUESTION_COLUMNS), _column(columns, ("id",))
    values = [row.get(label_col) for row in rows]
    read = read_marks(values, label_map, name, given, command)
    out = []
    for row, mark in zip(rows, read, strict=True):
        if mark is None:
            continue
        given_id = row.get(id_col) if id_col else None
        out.append(Label(mark=mark, output=_scrubbed(row.get(out_col)),
                         input=_scrubbed(row.get(in_col)) if in_col else None,
                         id=None if _blank(given_id) else str(given_id)))
    return out


def _scrubbed(value):
    """`value` with any key hidden, as the pool keeps its text (start_label._scrubbed)."""
    from judgekeeper.start_label import _scrubbed as scrubbed

    return scrubbed(value)


def _blank(value) -> bool:
    return value is None or isinstance(value, str) and not value.strip()


def read_marks(values: list, label_map: dict | None, name: str, given: str | None,
               command: Callable[..., str] | None = None) -> list[str | None]:
    """Each value as "pass" or "fail" (None when blank), read with `label_map` (the
    defaults: pass/fail, true/false, yes/no, correct/incorrect, right/wrong, 1/0). A number
    (other than 1/0) or any other word: a LabelsStop that names up to WORDS_SHOWN of the words
    and the command with --label-map."""
    norm = Normaliser(label_map=None)
    norm.label_map = {**norm.label_map, **(label_map or {})}
    out: list[str | None] = []
    numbers, words = False, []
    for value in values:
        if _blank(value):
            out.append(None)
            continue
        try:
            verdict = norm(value).verdict
        except UnmappedValue:
            verdict = None
        if verdict in ("pass", "fail"):
            out.append(verdict)
            continue
        out.append(None)
        if verdict is None and _numeric(value) and not isinstance(value, bool):
            numbers = True
        else:
            words.append(value)
    if numbers:
        raise LabelsStop(["Labels must be Pass or Fail, not numbers."])
    if words:
        shown = sorted({_word(w) for w in words})[:WORDS_SHOWN]
        command = _plain(command)
        where = (("--labels",) if given is None else ("--labels", runnable(given, labels=True)))
        raise LabelsStop([(f"Some labels in {shown_name(name) if given is None else name} aren't "
                           f"Pass or Fail: {', '.join(shown)}.")],
                         "say what each one means, then run: "
                         f"{command(*where, '--label-map', chr(34) + 'WORD=pass,WORD=fail' + chr(34))}")
    return out


def _word(value) -> str:
    text = " ".join(scrub(str(value)).split())
    return text if len(text) <= WORD_WIDTH else text[:WORD_WIDTH - 1] + "…"


# The labels in the results ---------------------------------------------------------------

def in_results(pool, metric: str | None = None,
               command: Callable[..., str] | None = None) -> list[Label]:
    """The human labels in the results (start.Pool.humans), one per answer and name: on an
    answer that has some named like the judge (`metric`), only those. A LabelsStop when there
    are none, or for a word that isn't Pass or Fail."""
    humans = list(pool.humans)
    if not humans:
        raise LabelsStop([("No Pass/Fail labels found in your results. To use labels from a "
                           f"file, run: {_plain(command)('--labels', '<file>')}")])
    if metric is not None:
        named = {key for key, _, name in humans if name == metric}
        humans = [h for h in humans if h[0] not in named or h[2] == metric]
    read = read_marks([value for _, value, _ in humans], pool.label_map, RESULTS_NAME, None,
                      command)
    return [Label(mark=mark, key=key) for (key, _, _), mark in zip(humans, read, strict=True)
            if mark is not None]


# Matching ---------------------------------------------------------------------------------

@dataclass
class Plan:
    """What the labels give: {answer id: mark} in queue order, and the labels left out by
    reason (SKIPPED)."""

    marks: dict[str, str] = field(default_factory=dict)
    skipped: dict[str, int] = field(default_factory=dict)
    matched: int = 0  # labels that found an answer

    def skip(self, reason: str, n: int = 1) -> None:
        self.skipped[reason] = self.skipped.get(reason, 0) + n


def _base(answer_id: str) -> str:
    """An answer's id without its repeat number (start.build_pool's `key#n`)."""
    head, _, n = answer_id.rpartition("#")
    return head if head and n.isdigit() else answer_id


def match(found_labels: list[Label], pool_rows: dict, queue: list[dict],
          left: dict | None = None) -> Plan:
    """Which answers of the queue the labels are for (_match), each text made ready for
    matching once (check.texts_once)."""
    from judgekeeper.check import texts_once

    with texts_once():
        return _match(found_labels, pool_rows, queue, left)


def _match(found_labels: list[Label], pool_rows: dict, queue: list[dict],
           left: dict | None = None) -> Plan:
    """Which answers of the queue (`pool_rows`: pool.jsonl by id) the labels are for. `left`:
    the answers the judge gave no clear grade (start.Pool.left: id -> (kind, record)), to tell
    those from answers not in the results."""
    from judgekeeper.check import _candidates, _index, _text

    order = [q["id"] for q in queue if q["id"] in pool_rows]
    answers = [SimpleNamespace(id=i, input=pool_rows[i].get("input"),
                               output=pool_rows[i].get("output")) for i in order]
    by_base: dict[str, list] = {}
    by_text: dict[str, list] = {}
    for a in answers:
        by_base.setdefault(_base(a.id), []).append(a)
        by_text.setdefault(_text(a.output), []).append(a)
    index = _index(answers)
    left = left or {}
    left_keys = set(left)
    left_text = {_text(r.output) for _, r in left.values()}

    wanted: dict[str, set[str]] = {}
    targets_of: list[tuple[Label, list[str]]] = []
    plan = Plan()
    for label in found_labels:
        hits: list = []
        if label.key is not None:  # from the results: its answer's own id
            hits = by_base.get(label.key, [])
            if not hits:
                plan.skip(NOT_GRADED if label.key in left_keys else NO_MATCH)
                continue
        else:
            text = _text(label.output)
            if label.id is not None:
                from judgekeeper.table import sheet_id

                hits = [a for a in by_base.get(sheet_id(label.id), [])
                        if not text or _text(a.output) == text]  # an empty cell: not given
            if not hits and not _blank(label.input):
                hits = _candidates(index, {"input": label.input, "output": label.output})
            elif not hits:
                hits = by_text.get(text, []) if text else []
                if len({_text(a.input) for a in hits}) > 1:
                    plan.skip(MORE_THAN_ONE)
                    continue
            if not hits:
                plan.skip(NOT_GRADED if text and text in left_text else NO_MATCH)
                continue
        plan.matched += 1
        ids = list(dict.fromkeys(a.id for a in hits))
        targets_of.append((label, ids))
        for i in ids:
            wanted.setdefault(i, set()).add(label.mark)
    both = {i for i, m in wanted.items() if len(m) > 1}
    for label, ids in targets_of:
        if both & set(ids):
            plan.skip(BOTH)
    plan.marks = {i: next(iter(wanted[i])) for i in order if i in wanted and i not in both}
    return plan


# Writing ----------------------------------------------------------------------------------

@dataclass
class Added:
    marks: int = 0
    passed: int = 0
    failed: int = 0
    kept: int = 0  # answers whose earlier, different mark was kept
    same: int = 0  # answers already marked as the label says


def add(ws, plan: Plan, source: str) -> Added:
    """The plan's marks as lines of marks.jsonl (one import, one sitting), only for answers
    with no mark that counts; an answer marked otherwise keeps its mark (counted in `kept`)."""
    from judgekeeper.start_label import begin_marks

    groups = {q["id"]: q["group"] for q in ws.data()["queue"]}
    if not ws.marks.is_file():
        begin_marks(ws)
    have = marks.read(ws.marks).counted()
    sitting = marks.new_import()
    lines, out = [], Added()
    for answer_id, mark in plan.marks.items():
        if answer_id in have:
            out.kept += have[answer_id] != mark
            out.same += have[answer_id] == mark
            continue
        lines.append(marks.imported_line(answer_id, mark, groups.get(answer_id), sitting,
                                         source))
        out.marks += 1
        out.passed += mark == "pass"
        out.failed += mark == "fail"
    marks.append_all(ws.marks, lines)
    return out


def said(added: Added, plan: Plan, source: str) -> list[str]:
    """What the import says: the marks added, the labels skipped and why, and the earlier
    marks kept. Indented lines start with two spaces."""
    name = shown_name(source)
    if not added.marks and not added.kept and added.same:  # "Added 0 marks" would say nothing
        out = [f"Nothing new: the labels in {name} are already your marks."]
    else:
        out = [(f"Added {plural(added.marks, 'mark', 'marks')} from {name} ({added.passed} "
                f"Pass, {added.failed} Fail).")]
    n = sum(plan.skipped.values())
    if n:
        out.append(f"Skipped {plural(n, 'label', 'labels')}:")
        for reason, one, many in SKIPPED:
            k = plan.skipped.get(reason, 0)
            if k:
                out.append("  " + (one if k == 1 else many).format(n=k))
    if added.kept:
        out.append(f"Kept your earlier mark on {plural(added.kept, 'answer', 'answers')} that "
                   f"{name} labels differently.")
    return out


def nothing_matched(source: str) -> LabelsStop:
    return LabelsStop([(f"No labels in {shown_name(source)} match your results. Check that the "
                        "answer text is the same, word for word.")])


# Imported marks against page marks -----------------------------------------------------------

def by_group(m: marks.Marks, ids, groups: dict[str, str]) -> dict:
    """{group: {"file": [Pass, Fail], "page": [Pass, Fail]}}: the marks that count among `ids`,
    per group of the LLM-as-a-judge (`groups`: answer id to its group), by how each was made
    (its last line: an imported answer marked again on the page is a page mark)."""
    out = {g: {"file": [0, 0], "page": [0, 0]} for g in ("pass", "fail")}
    for i, mark in m.counted().items():
        g = groups.get(i)
        if (ids is not None and i not in ids) or g not in out:
            continue
        by = "file" if m.last[i].get("by") == marks.BY_FILE else "page"
        out[g][by][0 if mark == "pass" else 1] += 1
    return out


def still_needed(page: dict[str, int], left: dict[str, int]) -> int:
    """How many more page marks a coloured verdict needs: per group, up to PAGE_MARKS, never
    more than the answers left to mark there (none left: nothing needed)."""
    return sum(min(max(PAGE_MARKS - page.get(g, 0), 0), left.get(g, 0)) for g in ("pass", "fail"))


def gate_line(n: int, imported: dict | None) -> str | None:
    if not n or not imported:
        return None
    return GATE.format(n=n, name=names(imported.get("from") or ["a file"]))


def fisher_p(a: int, b: int, c: int, d: int) -> float:
    """Fisher's exact test, two-sided, on the table [[a, b], [c, d]]: the chance of a table
    with the same margins at most as likely as this one."""
    row, col, n = a + b, a + c, a + b + c + d
    if not row or not col or row == n or col == n:
        return 1.0

    def chance(x: int) -> float:
        return math.comb(col, x) * math.comb(n - col, row - x) / math.comb(n, row)

    seen = chance(a)
    return min(1.0, sum(p for x in range(max(0, row + col - n), min(row, col) + 1)
                        if (p := chance(x)) <= seen * (1 + 1e-7)))


def looks_off(counts: dict) -> dict | None:
    """The group where imported and page marks differ most ({"group", "file": % marked Pass of
    the imported, "page": of the page marks}) when p < CHECK_LEVEL there; None otherwise, or
    while a group has under PAGE_MARKS page marks."""
    if any(sum(counts[g]["page"]) < PAGE_MARKS for g in ("pass", "fail")):
        return None
    found = None
    for g in ("pass", "fail"):
        (fp, ff), (pp, pf) = counts[g]["file"], counts[g]["page"]
        p = fisher_p(fp, ff, pp, pf)
        if p < CHECK_LEVEL and (found is None or p < found[0]):
            found = (p, {"group": g, "file": round(100 * fp / (fp + ff)),
                         "page": round(100 * pp / (pp + pf))})
    return found and found[1]


def looks_off_line(off: dict | None, imported: dict | None) -> str | None:
    if not off or not imported:
        return None
    name = names(imported.get("from") or ["a file"])
    return LOOKS_OFF.format(name=name, did=GROUP_DID[off["group"]], x=off["file"],
                            y=off["page"])
