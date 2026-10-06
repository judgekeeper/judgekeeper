"""The `[start]` table of judgekeeper.toml: where a project's judge results are and how to
read them. `judgekeeper setup` writes it; `judgekeeper start` reads it first. Nothing secret.

    [start]
    source = "map"                 # or the eval tool start reads as it is: records,
    file = "history/evals.jsonl"   # promptfoo, deepeval, inspect, mlflow, table
    judge = "Safe wording"         # the judge to check; "*": every judge, one at a time
    pass_mark = 0.5
    model = "claude-opus-5"        # only when the results do not say which model judged

    [start.map]                    # how to read the file (see mapper.py)
    each = "cases[]"
    ...

Python reads TOML but cannot write it, so the table is written by hand: `merged` replaces
the `[start]` and `[start.*]` tables of an existing file, or adds them at the end, and keeps
every other line as it was, in the file's own line endings (\r\n on Windows). It checks
the result with tomllib: when anything else would change (an unusual shape), it raises
SettingsError instead.
"""

from __future__ import annotations

import json
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from judgekeeper.textio import line_ending, read_utf8, write_keeping

FILE = "judgekeeper.toml"
TOOLS = ("records", "promptfoo", "deepeval", "inspect", "mlflow", "table")
MAP_KEYS = {"each": str, "id": str, "input": str, "output": str, "sides": list, "score": str,
            "reason": str, "kind": str, "judges": list, "model_key": str, "leave_out": bool}
HEADER = ("# judgekeeper start reads this first: where your judge's results are and how to read\n"
          "# them. Written by judgekeeper setup (run it again to change it); nothing secret.\n")
_TABLE = re.compile(r"^\s*\[\s*([^\[\]]+?)\s*\]\s*(#.*)?$")


class SettingsError(Exception):
    """judgekeeper.toml's [start] table cannot be read or written; the message says why."""


@dataclass
class StartSettings:
    source: str
    file: str | None = None
    judge: str | None = None
    pass_mark: float | None = None
    model: str | None = None
    map: dict = field(default_factory=dict)

    def describe(self) -> str:
        """In a few words, for people."""
        if self.source == "map":
            judge = "" if self.judge in (None, "*") else f", the judge {self.judge}"
            return f"{self.file}, read with the map you set up{judge}"
        judge = "" if self.judge in (None, "*") else f", the judge {self.judge}"
        return f"the results of {self.source}{judge}"


def load(root: str | Path) -> StartSettings | None:
    """The [start] table of `root`/judgekeeper.toml, or None when there is none."""
    path = Path(root) / FILE
    if not path.is_file():
        return None
    try:
        data = tomllib.loads(read_utf8(path, SettingsError))
    except tomllib.TOMLDecodeError as e:
        raise SettingsError(f"{FILE}: invalid TOML: {e}") from None
    table = data.get("start")
    if table is None:
        return None
    if not isinstance(table, dict):
        raise SettingsError(f"{FILE}: start must be a table")
    known = {"source", "file", "judge", "pass_mark", "model", "map"}
    unknown = sorted(set(table) - known)
    if unknown:
        raise SettingsError(f"{FILE}: unknown key {unknown[0]!r} in [start]; allowed: "
                            f"{', '.join(sorted(known))}")
    source = table.get("source")
    if source != "map" and source not in TOOLS:
        raise SettingsError(f"{FILE}: [start] source must be map or one of {', '.join(TOOLS)}")
    for key in ("file", "judge", "model"):
        if key in table and not isinstance(table[key], str):
            raise SettingsError(f"{FILE}: [start] {key} must be text")
    mark = table.get("pass_mark")
    if mark is not None and (isinstance(mark, bool) or not isinstance(mark, int | float)):
        raise SettingsError(f"{FILE}: [start] pass_mark must be a number")
    m = table.get("map", {})
    if source == "map":
        if not table.get("file"):
            raise SettingsError(f"{FILE}: [start] needs file when source is map")
        for key in ("each", "input", "output", "score"):
            if key not in m:
                raise SettingsError(f"{FILE}: [start.map] needs {key}")
    for key, value in m.items():
        if key not in MAP_KEYS:
            raise SettingsError(f"{FILE}: unknown key {key!r} in [start.map]")
        if not isinstance(value, MAP_KEYS[key]):
            raise SettingsError(f"{FILE}: [start.map] {key} has the wrong type")
    return StartSettings(source=source, file=table.get("file"), judge=table.get("judge"),
                         pass_mark=mark, model=table.get("model"), map=dict(m))


def _value(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int | float):
        return repr(v)
    if isinstance(v, list):
        return "[" + ", ".join(_value(x) for x in v) + "]"
    return json.dumps(str(v), ensure_ascii=False)  # a JSON string is a TOML basic string


def render(s: StartSettings) -> str:
    """The [start] (and [start.map]) tables as TOML text."""
    lines = ["[start]"]
    for key in ("source", "file", "judge", "pass_mark", "model"):
        value = getattr(s, key)
        if value is not None:
            lines.append(f"{key} = {_value(value)}")
    if s.map:
        lines += ["", "[start.map]"]
        lines += [f"{key} = {_value(s.map[key])}" for key in MAP_KEYS if s.map.get(key)
                  not in (None, [])]
    return "\n".join(lines) + "\n"


def _is_start(header: str) -> bool:
    name = header.replace(" ", "")
    return name == "start" or name.startswith("start.")


def merged(text: str | None, s: StartSettings) -> str:
    """`text` (judgekeeper.toml as it is, or None) with its [start] tables replaced by `s`,
    or added at the end. SettingsError when the file's shape is unusual."""
    block = render(s)
    if not text:
        return HEADER + block
    eol = line_ending(text)
    block = block.replace("\n", eol)
    kept, inside = [], False
    for line in text.splitlines(keepends=True):
        m = _TABLE.match(line)
        if m:
            inside = _is_start(m.group(1))
        if not inside:
            kept.append(line)
    body = "".join(kept).rstrip("\r\n")
    new = (body + eol + eol if body else "") + block
    try:
        before, after = tomllib.loads(text), tomllib.loads(new)
    except tomllib.TOMLDecodeError as e:
        raise SettingsError(f"{FILE}: invalid TOML: {e}") from None
    before.pop("start", None)
    if {k: v for k, v in after.items() if k != "start"} != before:
        raise SettingsError(f"{FILE} has a shape judgekeeper does not edit")
    return new


def save(root: str | Path, s: StartSettings) -> None:
    path = Path(root) / FILE
    text = read_utf8(path, SettingsError) if path.is_file() else None
    write_keeping(path, merged(text, s))


__all__ = ["FILE", "SettingsError", "StartSettings", "load", "merged", "render", "save"]
