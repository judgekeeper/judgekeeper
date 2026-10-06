"""Readers: files other tools already write, in; ScoreRecords out.

Every file reader is a pure function `read_<tool>(path, **options) -> list[ScoreRecord]` (a
RecordList, which also carries what the reader learned about the file). Platform readers
(MLflow, Langfuse) read a store or an API instead of a path and return [(run label,
RecordList)]. This package is the only place that knows about any framework; `import_results`
hands the records to `records.records_to_report`, which runs the report pipeline.
"""

from __future__ import annotations

import glob
from pathlib import Path

from judgekeeper.readers.deepeval import read_deepeval
from judgekeeper.readers.inspect_logs import read_inspect
from judgekeeper.readers.langfuse_api import read_langfuse
from judgekeeper.readers.mlflow_store import read_mlflow
from judgekeeper.readers.promptfoo import read_promptfoo
from judgekeeper.records import RecordsError, read_records, records_to_report

READERS = {"promptfoo": read_promptfoo, "deepeval": read_deepeval, "inspect": read_inspect,
           "records": read_records}
PLATFORM_READERS = {"mlflow": read_mlflow, "langfuse": read_langfuse}
TOOLS = (*READERS, *PLATFORM_READERS)

# What a directory means for each tool: the file patterns to read, first match wins.
_DIR_PATTERNS = {
    "promptfoo": (("*.json",),),
    "deepeval": (("test_run_*.json",), (".latest_run_full.json",),
                 (".deepeval/.latest_run_full.json",)),
    "inspect": (("*.eval", "*.json"),),
    "records": (("*.jsonl", "*.csv", "*.tsv"),),
}
_SKIP = {"logs.json"}  # Inspect's log-directory listing, not a log


def expand_paths(tool: str, paths) -> list[Path]:
    """Files from paths that are files, directories or globs, in order, without repeats."""
    if isinstance(paths, str | Path):
        paths = [paths]
    files: list[Path] = []
    for p in paths:
        text = str(p)
        if any(ch in text for ch in "*?["):
            found = [Path(x) for x in sorted(glob.glob(text)) if Path(x).is_file()]
            if not found:
                raise RecordsError(f"no files match {text}")
        elif Path(text).is_dir():
            found = []
            for patterns in _DIR_PATTERNS[tool]:
                found = sorted(f for pat in patterns for f in Path(text).glob(pat)
                               if f.is_file() and f.name not in _SKIP)
                if found:
                    break
            if not found:
                wanted = " or ".join(" ".join(ps) for ps in _DIR_PATTERNS[tool])
                raise RecordsError(f"no {tool} files ({wanted}) in {text}")
        elif Path(text).is_file():
            found = [Path(text)]
        else:
            raise RecordsError(f"file not found: {text}")
        files += [f for f in found if f not in files]
    if not files:
        raise RecordsError("no input files")
    return files


def import_results(tool: str, paths=(), metric: str | None = None, labels=None,
                   pass_if: str | None = None, label_map=None, runs_by_order: bool = False,
                   id_var: str | None = None, column_map=None, out=None, anchors_out=None,
                   source: dict | None = None) -> dict:
    """Read results another tool wrote and return the judgekeeper report (report.json).

    `tool` is promptfoo, deepeval, inspect or records. `paths` are files, directories or
    globs; several files (or several runs in one file) become separate runs. `metric` picks
    the judge when the files hold several. `labels` is a table with id and human_label
    columns, which wins over human labels in the files. `pass_if` and `label_map` work as in
    `check`. `id_var` (promptfoo) names the var that holds the item id; `column_map`
    (records) renames source columns, e.g. "target_id=trace_id,label=value". Files go under
    `out` (a temporary directory if None).

    `tool` mlflow or langfuse reads a platform instead of `paths`: `source` holds the
    reader's options (see read_mlflow, read_langfuse). For Langfuse, `metric` defaults to the
    judge score's name. `anchors_out` (platform readers) also writes every labeled item as a
    frozen anchor set for `judgekeeper judge`.
    """
    if tool in PLATFORM_READERS:
        if paths:
            raise RecordsError(f"`import {tool}` reads the platform, not files: drop the "
                               f"path(s) {', '.join(map(str, paths))}")
        if id_var is not None or column_map:
            raise RecordsError("--id-var and --map apply to file readers only")
        options = dict(source or {})
        if tool == "langfuse":
            metric = metric or options.get("judge_score")
            files = [read_langfuse(**options)]
        else:
            files = read_mlflow(**options, metric=metric)
        return records_to_report(files, kind=tool, metric=metric, labels=labels,
                                 pass_if=pass_if, label_map=label_map,
                                 runs_by_order=runs_by_order, out=out, anchors_out=anchors_out)
    if tool not in READERS:
        raise RecordsError(f"unknown tool {tool!r}; one of {', '.join(TOOLS)}")
    if anchors_out is not None:
        raise RecordsError("--anchors-out applies to `import mlflow` and `import langfuse`")
    if source:
        raise RecordsError(f"{', '.join(sorted(source))} apply to the platform readers only")
    if not paths:
        raise RecordsError(f"`import {tool}` needs at least one path")
    if id_var is not None and tool != "promptfoo":
        raise RecordsError("--id-var applies to promptfoo only")
    if column_map and tool != "records":
        raise RecordsError("--map applies to `import records` only")
    options = {"promptfoo": {"id_var": id_var}, "records": {"column_map": column_map}}
    files = [(f.name, READERS[tool](f, **options.get(tool, {})))
             for f in expand_paths(tool, paths)]
    return records_to_report(files, kind=tool, metric=metric, labels=labels, pass_if=pass_if,
                             label_map=label_map, runs_by_order=runs_by_order, out=out)


__all__ = ["PLATFORM_READERS", "READERS", "TOOLS", "expand_paths", "import_results",
           "read_deepeval", "read_inspect", "read_langfuse", "read_mlflow", "read_promptfoo",
           "read_records"]
