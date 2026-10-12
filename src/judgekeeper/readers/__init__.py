"""Readers: files other tools already write, in; ScoreRecords out.

Every file reader is a pure function `read_<tool>(path, **options) -> list[ScoreRecord]` (a
RecordList, which also carries what the reader learned about the file). Platform readers
(MLflow, Langfuse) read a store or an API instead of a path and return [(run label,
RecordList)]. This package is the only place that knows about any framework.
"""

from __future__ import annotations

from judgekeeper.readers.deepeval import read_deepeval
from judgekeeper.readers.inspect_logs import read_inspect
from judgekeeper.readers.langfuse_api import read_langfuse
from judgekeeper.readers.mlflow_store import read_mlflow
from judgekeeper.readers.promptfoo import read_promptfoo
from judgekeeper.records import read_records

READERS = {"promptfoo": read_promptfoo, "deepeval": read_deepeval, "inspect": read_inspect,
           "records": read_records}
PLATFORM_READERS = {"mlflow": read_mlflow, "langfuse": read_langfuse}
TOOLS = (*READERS, *PLATFORM_READERS)

__all__ = ["PLATFORM_READERS", "READERS", "TOOLS",
           "read_deepeval", "read_inspect", "read_langfuse", "read_mlflow", "read_promptfoo",
           "read_records"]
