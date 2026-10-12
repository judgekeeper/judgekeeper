"""Adding judgekeeper to a project's dev requirements: the first of pyproject.toml's dev group
or dev extra, requirements-dev.txt, requirements-dev.in; only when judgekeeper is not listed
anywhere; never the main requirements. The file keeps its own line endings, and a
pyproject.toml whose shape judgekeeper does not edit is left alone with a message.

Kept for turning on automatic checks, which put judgekeeper in the dev requirements so the
project's own environment has it.
"""

from __future__ import annotations

import copy
import re
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from judgekeeper.textio import line_ending, read_utf8, write_keeping

NOT_LISTED = ("judgekeeper is not listed in your project's requirements; add it so teammates "
              "get it")


class RequirementsError(Exception):
    """A requirements file cannot be read (not UTF-8)."""


@dataclass
class Change:
    text: str  # the line in the list
    apply: Callable[[], None] | None  # None: nothing to change, only something to know
    done: str = ""


_LISTED_TOML = re.compile(r"""["']judgekeeper\s*(?:["'\[<>=!~;@ ])""", re.IGNORECASE)
_LISTED_LINE = re.compile(r"^\s*judgekeeper\s*(?:[\[<>=!~;@#]|$)", re.IGNORECASE)
_HEADER = re.compile(r"^\s*\[\s*([^\[\]]+?)\s*\]\s*(#.*)?$")
_DEV = re.compile(r"^(\s*)dev\s*=\s*\[")
FORMS = (("the dev group in pyproject.toml", ("dependency-groups", "dev"), "dependency-groups"),
         ("the dev extra in pyproject.toml", ("project", "optional-dependencies", "dev"),
          "project.optional-dependencies"))


def _listed(root: Path) -> bool:
    files = [root / "pyproject.toml", *sorted(root.glob("requirements*.txt")),
             *sorted(root.glob("requirements*.in"))]
    for path in files:
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if path.suffix == ".toml":
            if _LISTED_TOML.search(text):
                return True
        elif any(_LISTED_LINE.match(line) for line in text.splitlines()):
            return True
    return False


def _nested(data: dict, keys: tuple):
    for key in keys:
        if not isinstance(data, dict) or key not in data:
            return None
        data = data[key]
    return data


def _added(text: str, header: str) -> str | None:
    """pyproject.toml's text with "judgekeeper" added to the `dev = [...]` list of the table
    `header`, or None when the list is not where or how judgekeeper edits it."""
    eol = line_ending(text)  # new lines end as the file's lines do
    lines = text.splitlines(keepends=True)
    start = next((i for i, line in enumerate(lines)
                  if (m := _HEADER.match(line)) and m.group(1).replace(" ", "") == header),
                 None)
    if start is None:
        return None
    end = next((i for i in range(start + 1, len(lines)) if _HEADER.match(lines[i])), len(lines))
    at = next((i for i in range(start + 1, end) if _DEV.match(lines[i])), None)
    if at is None:
        return None
    line = lines[at]
    if "#" in line:
        return None
    if "]" in line:  # one line: dev = ["pytest"]
        close = line.rindex("]")
        inside = line[line.index("[") + 1:close].strip()
        item = '"judgekeeper"' if not inside else (
            ' "judgekeeper"' if inside.endswith(",") else ', "judgekeeper"')
        lines[at] = line[:close].rstrip() + item + line[close:] if inside else \
            line[:close] + item + line[close:]
        return "".join(lines)
    close = next((i for i in range(at + 1, end) if lines[i].strip().startswith("]")), None)
    if close is None:
        return None
    items = [i for i in range(at + 1, close) if lines[i].strip()]
    if any("#" in lines[i] for i in items):
        return None
    if not items:
        lines.insert(close, f'    "judgekeeper",{eol}')
        return "".join(lines)
    last = items[-1]
    indent = lines[last][:len(lines[last]) - len(lines[last].lstrip())]
    trailing = lines[last].rstrip().endswith(",")
    if not trailing:
        lines[last] = lines[last].rstrip("\r\n") + "," + eol
    lines.insert(last + 1, f'{indent}"judgekeeper"{"," if trailing else ""}{eol}')
    return "".join(lines)


def requirements_change(root: Path) -> Change | None:
    """Adding judgekeeper to the first dev requirements form the project has. None when it is
    listed already; a Change with nothing to apply when there is no form to add it to."""
    if _listed(root):
        return None
    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        text = read_utf8(pyproject, RequirementsError)
        try:
            data = tomllib.loads(text)
        except tomllib.TOMLDecodeError:
            data = {}
        for where, keys, header in FORMS:
            old = _nested(data, keys)
            if not isinstance(old, list):
                continue
            new = _added(text, header)
            want = copy.deepcopy(data)
            _nested(want, keys[:-1])[keys[-1]] = [*old, "judgekeeper"]
            try:
                ok = new is not None and tomllib.loads(new) == want
            except tomllib.TOMLDecodeError:
                ok = False
            if not ok:
                return Change(f"judgekeeper is not listed in your project's requirements, and "
                              f"{where} has a shape judgekeeper does not edit: add it to "
                              f"{where} yourself", None)
            return Change(f"add judgekeeper to {where}",
                          lambda new=new: write_keeping(pyproject, new),
                          f"Added judgekeeper to {where}")
    for name in ("requirements-dev.txt", "requirements-dev.in"):
        path = root / name
        if path.is_file():
            text = read_utf8(path, RequirementsError)

            def apply(path=path, text=text):  # in the file's own line endings
                eol = line_ending(text)
                before = text if not text or text.endswith("\n") else text + eol
                write_keeping(path, before + "judgekeeper" + eol)

            return Change(f"add judgekeeper to {name}", apply, f"Added judgekeeper to {name}")
    return Change(NOT_LISTED, None)


__all__ = ["Change", "RequirementsError", "requirements_change"]
