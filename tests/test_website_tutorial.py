"""Run the website tutorial end to end, exactly as written on website/tutorial.html.

Each step on the page is a `<pre data-step="N">` with the command and a
`<pre class="output" data-step="N">` with what it prints. This test copies website/tutorial/
to a temporary folder, runs every command in order and checks that the page shows the real
output and exit code. A step marked `data-run="no"` (the labeling page, which waits for a
person) is only parsed, not run.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tests.test_website import _lookup, render
from tests.website_pages import WEBSITE, command_lines, judgekeeper_argv, parse

PAGE = WEBSITE / "tutorial.html"


def _steps() -> list[dict]:
    steps: dict[str, dict] = {}
    for el in parse(PAGE).iter():
        step = el.attrs.get("data-step")
        if el.tag != "pre" or step is None:
            continue
        entry = steps.setdefault(step, {"step": step})
        if "output" in el.classes():
            entry["output"] = el.text()
            entry["exit"] = int(el.attrs.get("data-exit-code", "0"))
        else:
            (line,) = command_lines(el.text())
            entry["line"] = line
            entry["run"] = el.attrs.get("data-run") != "no"
    return list(steps.values())


def _run(line: str, cwd: Path) -> subprocess.CompletedProcess:
    argv = judgekeeper_argv(line)
    assert argv is not None, line
    env = {k: v for k, v in os.environ.items()
           if not k.endswith(("_API_KEY", "_TOKEN", "_SECRET"))}
    for word in shlex.split(line):
        if "=" in word and not word.startswith("-") and word.split("=")[0].isidentifier():
            name, value = word.split("=", 1)
            env[name] = value
        else:
            break
    # What a terminal shows: both streams, in the order they were written.
    env["PYTHONUNBUFFERED"] = "1"
    return subprocess.run([sys.executable, "-m", "judgekeeper.cli", *argv], cwd=cwd, env=env,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                          timeout=120, check=False)


@pytest.fixture(scope="module")
def tutorial(tmp_path_factory):
    work = tmp_path_factory.mktemp("tutorial")
    shutil.copytree(WEBSITE / "tutorial", work, dirs_exist_ok=True)
    results = []
    for step in _steps():
        assert "line" in step, f"step {step['step']} has no command"
        if not step["run"]:
            results.append((step, None))
            continue
        results.append((step, _run(step["line"], work)))
    return work, results


def test_the_tutorial_has_every_step():
    lines = [s["line"] for s in _steps()]
    for needed in ("judgekeeper --version", "judgekeeper check ", "judgekeeper template ",
                   "judgekeeper label ", "judgekeeper import-labels ", "--callable lazy_judge",
                   "--callable careful_judge", "judgekeeper validate ", "judgekeeper gate ",
                   "judgekeeper migrate ", "judgekeeper import promptfoo "):
        assert any(needed in line for line in lines), needed


def test_every_step_prints_what_the_page_shows(tutorial):
    _, results = tutorial
    for step, proc in results:
        if proc is None:
            continue
        assert proc.returncode == step["exit"], (step["line"], proc.stdout)
        assert "output" in step, f"step {step['step']} shows no output"
        shown = [line.rstrip() for line in step["output"].strip("\n").splitlines()]
        real = [line.rstrip() for line in proc.stdout.strip("\n").splitlines()]
        assert shown == real, f"step {step['step']}: {step['line']}"


def _report(work: Path, name: str) -> dict:
    files = {"csv": "reports/csv/report.json",
             "lazy": "reports/lazy/report.json", "careful": "reports/careful/report.json",
             "promptfoo": "reports/promptfoo/report.json",
             "migration": "migration/migration.json",
             "gate-lazy": "gates/lazy/gate.json", "gate-careful": "gates/careful/gate.json"}
    return json.loads((work / files[name]).read_text(encoding="utf-8"))


def test_the_headline_verdicts(tutorial):
    work, _ = tutorial
    lazy, careful = _report(work, "lazy"), _report(work, "careful")
    assert lazy["verdict"]["level"] == "not_trustworthy"
    assert f"{lazy['headline']['tnr_mean']:.2f}" == "0.67"
    assert careful["verdict"]["level"] == "usable"
    flipped = [row for row in careful["noise_floor"]["per_item"] if row["flip_rate"] > 0]
    assert len(flipped) == 1 and flipped[0]["id"] == "q7"
    assert _report(work, "csv")["verdict"]["level"] == "not_trustworthy"
    assert _report(work, "gate-lazy")["status"] == "FAIL"
    assert _report(work, "gate-careful")["status"] == "PASS"
    assert _report(work, "migration")["status"] == "BETTER"


def test_tutorial_numbers_in_the_prose_come_from_the_run(tutorial):
    work, _ = tutorial
    found = [el for el in parse(PAGE).iter() if "data-tutorial" in el.attrs]
    assert len(found) >= 5
    for el in found:
        name, path = el.attrs["data-tutorial"].split(":", 1)
        value = _lookup(_report(work, name), path)
        assert el.text().strip() == render(value, el.attrs.get("data-format", "2f")), el.attrs


def _load(name: str):
    """Import a tutorial judge without writing __pycache__ into website/."""
    spec = importlib.util.spec_from_file_location(name, WEBSITE / "tutorial" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    before, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = before
    return module


def test_the_judges_are_as_described():
    lazy, careful = _load("lazy_judge"), _load("careful_judge")
    sure = {"id": "x", "input": "?", "output": "Saturn is the largest planet."}
    assert lazy.judge(sure) == "pass"
    assert careful.judge(sure)["verdict"] == "fail"
    unsure = {"id": "q7", "input": "How many continents are there?",
              "output": "There are seven continents."}
    assert [careful.judge(unsure)["verdict"] for _ in range(3)] == ["pass", "fail", "pass"]
