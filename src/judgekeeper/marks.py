""".judgekeeper/marks.jsonl: the person's marks, one stamped line per click on the page.

The first line is a header: the LLM-as-a-judge as it was when marking started (tool, model,
rule hash, pass mark, fingerprint), the pool sizes (`weighted` corrects for picking half from
each of the judge's groups) and the results files. Then one line per click: {"id", "mark":
"pass" | "fail" | "skip" | null, "group", "at", "seconds", "sitting", "by": "page"}, plus a
few optional fields. `at` is the server's UTC time; null clears a mark (undo).

A reason line (reasons.py) carries the same mark and changes only the reasons, so the mark
keeps its own time. The last line for an answer wins. A line without its stamps (`by`, `at`,
`sitting`), or one that can't be read, is not counted, and the result says how many. The file
holds no answer or input text: that stays in pool.jsonl. Lines are only ever added, never
through a link.
"""

from __future__ import annotations

import json
import math
import os
import secrets
import statistics
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from judgekeeper import __version__
from judgekeeper.fingerprint import utc_now
from judgekeeper.textio import (
    hard_linked,
    is_link,
    jsonl_lines,
    link_in,
    open_private,
    write_replacing,
)

FILE = "marks.jsonl"
VERSION = 1
MARKS = ("pass", "fail", "skip", None)
MAX_SECONDS = 3600
BY = "page"
STAMPS = ("by", "at", "sitting")
PRINTED = "printed"
BROWSER_ENV = "browser-env"  # the page was opened by the program named in BROWSER
LINKS = (PRINTED, BROWSER_ENV)


class MarksError(OSError):
    """A mark can't be written: the folder or the file is a link."""


def header(*, judge: dict, pool: dict, results: list) -> dict:
    return {"marks": VERSION, "created_at": utc_now(), "judgekeeper_version": __version__,
            "judge": judge, "pool": {"pass": pool["pass"], "fail": pool["fail"]},
            "results": list(results)}


def new_sitting() -> str:
    return secrets.token_hex(8)


def _seconds(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or math.isnan(value):
        raise ValueError("seconds must be a number")
    kept = min(max(float(value), 0.0), MAX_SECONDS)
    return int(kept) if kept == int(kept) else round(kept, 2)


def stamp(item_id: str, mark: str | None, group: str | None, seconds, sitting: str,
          note: str | None = None, link: str | None = None, why: dict | None = None,
          after_result: bool = False) -> dict:
    """One click as a line of marks.jsonl; `link` is PRINTED for a page whose link was printed
    where a coding agent could read it, BROWSER_ENV for a page the program named in BROWSER
    opened; `why`: a reason line's fields (reasons.check)."""
    if mark not in MARKS:
        raise ValueError("mark must be pass, fail, skip or null")
    line = {"id": item_id, "mark": mark, "group": group, "at": utc_now(),
            "seconds": _seconds(seconds), "sitting": sitting, "by": BY}
    if note is not None:
        line["note"] = note
    if link is not None:
        line["link"] = link
    if after_result:
        line["after_result"] = True
    if why is not None:
        line.update(why)
    return line


def _line(data: dict) -> str:
    """One JSON line; U+2028 and U+2029 escaped, so no reader splits it."""
    return (json.dumps(data, ensure_ascii=False).replace("\u2028", "\\u2028")
            .replace("\u2029", "\\u2029") + "\n")


def _refused(link: Path, hard: bool = False) -> MarksError:
    """The MarksError that names `link` (`hard`: a file with a second name), from this folder
    when it is inside it, in the words start_label.refuse_links uses."""
    try:
        shown = os.path.relpath(link)
    except ValueError:  # Windows: on another drive
        shown = str(link)
    if shown.startswith(".."):
        shown = str(link)
    what = ("is linked to another file" if hard else
            f"is a link to another {'folder' if os.path.isdir(link) else 'file'}")
    return MarksError(f"{shown} {what}. judgekeeper does not write through links. Remove it, "
                      "then try again.")


def refuse_links_in(folder: Path) -> None:
    """A MarksError when `folder`, or anything in it, is a link."""
    link = link_in(folder)
    if link is not None:
        raise _refused(link)


def refuse_link(path: Path) -> None:
    """A MarksError when the file `path` is a link, or hard linked (a file with a second name
    elsewhere would be written there too)."""
    if os.path.islink(path) or hard_linked(path):
        raise _refused(path, hard=not os.path.islink(path))


WORKSPACE = ".judgekeeper"  # start_label.FOLDER


def _refuse_links(path: Path) -> None:
    """A MarksError when `path`, its folder or a file in it is a link, or `path` is hard
    linked; and when any folder between the project's .judgekeeper/ (itself included) and
    `path` is one: a link at .judgekeeper/fix would take a write to fix/runs/x elsewhere."""
    path = Path(path)
    above = path.parent.parents
    top = next((i for i, folder in enumerate(above) if folder.name == WORKSPACE), None)
    for folder in reversed(above[:top + 1] if top is not None else ()):
        if is_link(folder):
            raise _refused(folder)
    refuse_links_in(path.parent)
    refuse_link(path)


def begin(path: str | Path, head: dict) -> None:
    """Start a new marks file with its header (a file already there is replaced)."""
    path = Path(path)
    _refuse_links(path)
    write_replacing(path, _line(head))


def append(path: str | Path, data: dict) -> None:
    """Add one line to a JSONL file in .judgekeeper/ (marks.jsonl, history.jsonl)."""
    path = Path(path)
    _refuse_links(path)
    with open_private(path, "a", encoding="utf-8", newline="\n") as f:
        f.write(_line(data))


@dataclass
class Marks:
    header: dict | None = None
    last: dict[str, dict] = field(default_factory=dict)  # answer id -> its last stamped line
    not_counted: int = 0  # lines without their stamps, or that can't be read
    after_result: set[str] = field(default_factory=set)  # changed after the grades were shown
    gap: dict[str, float] = field(default_factory=dict)  # answer id -> seconds since the mark
    # before it in the same sitting, by `at`: the timing when the page sent no `seconds`

    def counted(self) -> dict[str, str]:
        """{answer id: "pass" or "fail"}: the marks that count."""
        return {i: x["mark"] for i, x in self.last.items() if x["mark"] in ("pass", "fail")}


def _stamped(x) -> bool:
    return (isinstance(x, dict) and isinstance(x.get("id"), str) and "mark" in x
            and x["mark"] in MARKS and x.get("by") == BY
            and all(isinstance(x.get(k), str) and x[k] for k in STAMPS))


def _with_reasons(before: dict | None, x: dict) -> dict:
    """An answer's line after `x`: a reason line with the same mark changes only the reasons;
    a line with the same mark keeps them; a new mark drops them."""
    from judgekeeper.reasons import FIELDS

    if before is None or before["mark"] != x["mark"]:
        return x
    if "reasons" in x:
        kept = {k: v for k, v in before.items() if k not in FIELDS}
        return {**kept, **{k: x[k] for k in FIELDS if k in x}}
    if any(k in x for k in FIELDS):
        return x
    return {**x, **{k: before[k] for k in FIELDS if k in before}}


def read(path: str | Path) -> Marks:
    """The marks in `path` (none when it is missing)."""
    path = Path(path)
    out = Marks()
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return out
    was: dict[str, str | None] = {}  # answer id -> its mark before the first change after
    last_at: dict[str, datetime] = {}  # sitting -> the time of its last mark
    for n, raw in enumerate(jsonl_lines(text)):
        if not raw.strip():
            continue
        try:
            x = json.loads(raw)
        except ValueError:
            out.not_counted += 1
            continue
        if n == 0 and isinstance(x, dict) and x.get("marks") == VERSION:
            out.header = x
        elif _stamped(x):
            before = out.last.get(x["id"])
            if x.get("after_result") is True and x["id"] not in was:
                was[x["id"]] = before and before["mark"]
            out.last[x["id"]] = _with_reasons(before, x)
            if "reasons" not in x:  # a mark, not a reason line
                _timed(out, x, last_at)
        else:
            out.not_counted += 1
    # changed after the grades were shown, and not back to the mark it had then
    out.after_result = {i for i, mark in was.items() if out.last[i]["mark"] != mark}
    return out


def _timed(out: Marks, x: dict, last_at: dict) -> None:
    try:
        at = datetime.strptime(x["at"], "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return
    if x["sitting"] in last_at and at >= last_at[x["sitting"]]:
        out.gap[x["id"]] = (at - last_at[x["sitting"]]).total_seconds()
    else:
        out.gap.pop(x["id"], None)
    last_at[x["sitting"]] = at


def made(m: Marks, ids=None) -> dict:
    """How the marks that count (of the answers `ids`, default all) were made: how many, how
    many Pass and Fail, in how many sittings, the middle value of their seconds (None when no
    mark has one), how many took under a second (by `seconds`, else by the time since the
    mark before), the lines not counted, how many were made through a printed link or a page
    the program named in BROWSER opened, how many the person wasn't sure about
    (reasons.UNSURE), and how many were changed after the judge's grades were shown."""
    from judgekeeper.reasons import UNSURE

    lines = [m.last[i] for i in m.counted() if ids is None or i in ids]
    seconds = [x["seconds"] for x in lines if isinstance(x.get("seconds"), (int, float))]
    timed = seconds + [m.gap[x["id"]] for x in lines  # no `seconds`: the time between marks
                       if not isinstance(x.get("seconds"), (int, float)) and x["id"] in m.gap]
    return {"marks": len(lines), "pass": sum(x["mark"] == "pass" for x in lines),
            "fail": sum(x["mark"] == "fail" for x in lines),
            "sittings": len({x["sitting"] for x in lines}),
            "seconds": round(statistics.median(seconds)) if seconds else None,
            "under_second": sum(s < 1 for s in timed), "not_counted": m.not_counted,
            "printed": sum(x.get("link") == PRINTED for x in lines),
            "browser_env": sum(x.get("link") == BROWSER_ENV for x in lines),
            "unsure": sum(UNSURE in (x.get("reasons") or []) for x in lines),
            "after_result": sum(x["id"] in m.after_result for x in lines)}


def not_counted_line(n: int) -> str | None:
    if not n:
        return None
    if n == 1:
        return f"1 line in {FILE} was not made on the page and is not counted."
    return f"{n} lines in {FILE} were not made on the page and are not counted."
