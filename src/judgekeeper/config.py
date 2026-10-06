"""judgekeeper.toml: one table per command. Unknown tables and keys are errors. The [start]
table (where the judge's results are) is read and checked by settings.py."""

from __future__ import annotations

import tomllib
from dataclasses import fields, replace
from pathlib import Path

from judgekeeper.textio import read_utf8

TABLES = ("attribute", "gate", "migrate", "start")  # [start]: settings.py, from setup


def load_section(path: str | Path, table: str, defaults, error: type[Exception]):
    """Read `[table]` from the TOML file at `path` over the dataclass instance `defaults`.

    Every value must be a number between 0 and 1. Raises `error` on any problem.
    """
    path = Path(path)
    try:
        data = tomllib.loads(read_utf8(path, error))
    except OSError as e:
        raise error(f"cannot read config {path}: {e.strerror}") from None
    except tomllib.TOMLDecodeError as e:
        raise error(f"{path}: invalid TOML: {e}") from None
    unknown = sorted(set(data) - set(TABLES))
    if unknown:
        allowed = ", ".join(f"[{t}]" for t in TABLES)
        raise error(f"{path}: unknown table or key {unknown[0]!r}; allowed: {allowed}")
    section = data.get(table, {})
    if not isinstance(section, dict):
        raise error(f"{path}: {table!r} must be a table")
    names = {f.name for f in fields(defaults)}
    for key, value in section.items():
        if key not in names:
            raise error(
                f"{path}: unknown key {key!r} in [{table}]; allowed: {', '.join(sorted(names))}"
            )
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise error(f"{path}: [{table}] {key} must be a number, got {value!r}")
        if not 0 <= value <= 1:
            raise error(f"{path}: [{table}] {key} must be between 0 and 1, got {value}")
    return replace(defaults, **{k: float(v) for k, v in section.items()})
