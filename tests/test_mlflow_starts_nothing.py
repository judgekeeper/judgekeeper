"""Reading an MLflow store starts no other program. MLflow's own library asks Python for the
platform it runs on as it loads, and Python asks the programs `uname` and `file`; judgekeeper
gives Python the answers first (mlflow_store.quiet), so nothing is started.

Each read runs in a fresh Python process watched by an audit hook: MLflow loads only once per
process, so a test in this one would not see it.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys

import pytest

from judgekeeper.readers import mlflow_store
from tests.test_start_mlflow_stores import made  # noqa: F401 - the stores, made once

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

WATCH = r"""
import json, os, sys
started = []

def hook(event, args):
    if event == "subprocess.Popen":
        argv = args[1] if isinstance(args[1], (list, tuple)) else [args[1] or args[0]]
        started.append(os.path.basename(str(argv[0])))
    elif event in ("os.system", "os.exec", "os.posix_spawn", "os.spawn", "os.startfile",
                   "os.fork", "os.forkpty"):
        started.append(event)

sys.addaudithook(hook)
from judgekeeper import start
found = start.find_judge(sys.argv[2])
with open(sys.argv[1], "w", encoding="utf-8") as f:
    json.dump({"started": started, "tool": found.tool, "store": found.store,
               "answers": len(found.pool.answers)}, f)
"""


@pytest.mark.parametrize("store", ["mlflow.db", "mlruns"])
def test_an_mlflow_read_starts_no_program(store, made, tmp_path):  # noqa: F811
    project = tmp_path / "docs-qa"
    project.mkdir()
    copy = shutil.copy2 if store == "mlflow.db" else shutil.copytree
    copy(made / store, project / store)
    script, seen = tmp_path / "watch.py", tmp_path / "seen.json"
    script.write_text(WATCH, encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.startswith("MLFLOW_")}
    env["PYTHONPATH"] = os.path.join(ROOT, "src")
    done = subprocess.run([sys.executable, str(script), str(seen), "."], cwd=project, env=env,
                          capture_output=True, text=True, timeout=300,
                          stdin=subprocess.DEVNULL, check=False)
    assert done.returncode == 0, done.stdout + done.stderr
    read = json.loads(seen.read_text(encoding="utf-8"))
    assert read["tool"] == "mlflow" and read["store"] == store and read["answers"] == 4, read
    assert read["started"] == [], read


def test_the_platform_answers_are_put_back_after_mlflow():
    before = (platform.platform, platform.processor, platform.architecture)
    with mlflow_store.quiet():
        assert platform.processor is not before[1]
        assert platform.architecture()[0] in ("32bit", "64bit")
    assert (platform.platform, platform.processor, platform.architecture) == before
