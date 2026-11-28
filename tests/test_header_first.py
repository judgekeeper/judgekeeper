"""Piped or captured into one stream (`2>&1 | cat`, a coding agent reading both), the output
still starts with the "judgekeeper <version>" line: stdout is flushed before anything goes to
stderr, so an error and its Next: line come after the header, as in a terminal."""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from judgekeeper import __version__


def _both(cwd, *argv) -> list[str]:
    env = {**os.environ, "NO_COLOR": "1"}
    env.pop("BROWSER", None)
    done = subprocess.run([sys.executable, "-m", "judgekeeper", *argv], cwd=cwd, env=env,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=120,
                          stdin=subprocess.DEVNULL, check=False)
    return [x for x in done.stdout.decode("utf-8").splitlines() if x.strip()]


@pytest.fixture
def runs(tmp_path):
    rows = [{"id": f"r{i}", "steps": [{"role": "user", "content": f"Ask {i}"}]}
            for i in range(2)]
    (tmp_path / "runs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows),
                                         encoding="utf-8")
    return tmp_path


def test_a_steps_error_comes_after_the_header(runs):
    lines = _both(runs, "steps", "runs.jsonl", "--reviewer", "nope.jsonl", "--no-browser",
                  "--port", "0")
    assert lines[0] == f"judgekeeper {__version__}", lines
    assert lines[1].startswith("error: "), lines


def test_a_flag_check_refuses_comes_after_the_header(tmp_path):
    lines = _both(tmp_path, "check", "--port", "0")
    assert lines[0] == f"judgekeeper {__version__}", lines
    assert lines[-1].startswith("Next: "), lines
