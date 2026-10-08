"""The MLflow tests raise no warning from judgekeeper's own code.

MLflow 3.16 deprecates `search_traces(experiment_ids=...)` with a FutureWarning attributed to
the caller. This runs tests/test_import_mlflow.py in a fresh pytest with warnings from
judgekeeper's modules and the fixture script (loaded as `make_mlflow_store`) turned into errors.
"""

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
# An ini-style filter: its module field is a regex matched from the start of the module name.
OWN_WARNINGS_ARE_ERRORS = r"error::Warning:(judgekeeper(\.|$)|make_mlflow_store$)"


def test_mlflow_tests_raise_no_warning_from_judgekeeper():
    pytest.importorskip("mlflow")
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
         "tests/test_import_mlflow.py", "-o", f"filterwarnings={OWN_WARNINGS_ARE_ERRORS}"],
        cwd=ROOT, capture_output=True, text=True, timeout=600, check=False)
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-2000:]
    assert " passed" in result.stdout and "skipped" not in result.stdout


def test_scope_uses_locations_when_search_traces_takes_it():
    from judgekeeper.readers.mlflow_store import _trace_scope

    def new(experiment_ids=None, max_results=None, page_token=None, locations=None):
        pass

    def old(experiment_ids=None, max_results=None, page_token=None):
        pass

    assert _trace_scope(new, "7") == {"locations": ["7"]}
    assert _trace_scope(old, "7") == {"experiment_ids": ["7"]}
