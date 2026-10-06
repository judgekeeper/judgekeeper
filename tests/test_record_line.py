"""`judgekeeper.record()`: one line where the user's own judge runs saves its verdict.

It writes one record (records format version 2, annotator_kind LLM) per call to
`.judgekeeper/records/<name>-<date>-<process id>.jsonl` under the project root, one file per
process. It never breaks the user's program: any error is caught, one warning goes to the
`judgekeeper` logger once per process, and it returns nothing. `JUDGEKEEPER_RECORD=0` turns
it off. Standard library only, and `import judgekeeper` stays light.
"""

from __future__ import annotations

import ast
import json
import logging
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

import judgekeeper
from judgekeeper import recorder
from judgekeeper.records import SCHEMA_VERSION, problems, read_records

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def project(tmp_path, monkeypatch):
    """A project folder (it has a pyproject.toml) as the current folder, recording on."""
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'app'\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("JUDGEKEEPER_RECORD", raising=False)
    recorder._reset()
    yield tmp_path
    recorder._reset()


def files(root):
    folder = root / ".judgekeeper" / "records"
    return sorted(folder.glob("*.jsonl")) if folder.is_dir() else []


def lines(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def only_record(root):
    (path,) = files(root)
    (line,) = lines(path)
    return line


# What one call writes ------------------------------------------------------------------

def test_one_call_writes_one_version_2_record(project):
    assert judgekeeper.record(input="Do you ship to Canada?", output="Yes, in 5 days.",
                              score=0.82, pass_mark=0.5, reason="Clear and correct.",
                              judge="claude-opus-5", rule="Pass when the reply is polite.",
                              name="Safe wording", temperature=0, id="q7",
                              metadata={"run_id": "nightly-41"}) is None
    line = only_record(project)
    assert line["schema_version"] == SCHEMA_VERSION == 2
    assert line["annotator_kind"] == "LLM"
    assert line["name"] == "Safe wording"
    assert line["target_id"] == "q7"
    assert (line["input"], line["output"]) == ("Do you ship to Canada?", "Yes, in 5 days.")
    assert (line["label"], line["score"]) == ("pass", 0.82)
    assert line["explanation"] == "Clear and correct."
    assert line["evaluator"] == {"model": "claude-opus-5", "temperature": 0,
                                 "rule": "Pass when the reply is polite."}
    assert line["metadata"] == {"run_id": "nightly-41", "pass_mark": 0.5}
    assert line["created_at"].endswith("Z")
    assert problems(line) == []


def test_the_file_is_named_after_the_judge_the_date_and_the_process(project):
    judgekeeper.record("q", "a", verdict="pass", name="Safe wording / tone")
    (path,) = files(project)
    name, pid = path.stem.rsplit("-", 1)
    assert pid == str(os.getpid())
    assert name.startswith("Safe-wording-tone-")
    assert len(name.rsplit("-", 3)[-3]) == 4  # the year of YYYY-MM-DD
    judgekeeper.record("q", "a", verdict="pass")
    assert any(p.name.startswith("judge-") for p in files(project))


def test_the_records_read_back_and_pass_the_check(project, capsys):
    from judgekeeper.cli import main

    judgekeeper.record("q1", "a1", verdict="pass", name="tone")
    judgekeeper.record("q2", "a2", verdict="fail", name="tone")
    records = read_records(files(project)[0])
    assert [r.label for r in records] == ["pass", "fail"]
    assert all(r.target_id for r in records)  # derived from input and output
    assert main(["import", "records", ".judgekeeper/records", "--check"]) == 0
    assert 'Judge "tone": 1 pass, 1 fail.' in capsys.readouterr().out


@pytest.mark.parametrize("verdict, label", [("pass", "pass"), ("fail", "fail"), (True, "pass"),
                                            (False, "fail"), (" PASS ", "pass"),
                                            ("Fail", "fail")])
def test_both_verdict_forms(project, verdict, label):
    judgekeeper.record("q", "a", verdict=verdict)
    assert only_record(project)["label"] == label


@pytest.mark.parametrize("score, label", [(0.5, "pass"), (0.49, "fail"), (1, "pass"),
                                          (0, "fail")])
def test_a_score_and_a_pass_mark_give_the_verdict(project, score, label):
    judgekeeper.record("q", "a", score=score, pass_mark=0.5)
    line = only_record(project)
    assert (line["label"], line["score"]) == (label, score)


def test_a_verdict_wins_over_score_and_pass_mark(project):
    judgekeeper.record("q", "a", verdict="fail", score=0.9, pass_mark=0.5)
    line = only_record(project)
    assert (line["label"], line["score"]) == ("fail", 0.9)


def test_a_score_without_a_pass_mark_is_kept_without_a_verdict(project):
    judgekeeper.record("q", "a", score=0.7)
    line = only_record(project)
    assert line["label"] is None and line["score"] == 0.7
    assert "pass_mark" not in (line.get("metadata") or {})


def test_any_json_value_as_input_and_output(project):
    judgekeeper.record({"question": "q", "history": ["hi"]}, ["a", {"k": 1}], verdict=True)
    line = only_record(project)
    assert line["input"] == {"question": "q", "history": ["hi"]}
    assert line["output"] == ["a", {"k": 1}]


def test_odd_objects_are_written_as_text(project):
    class Answer:
        def __str__(self):
            return "an answer object"

    judgekeeper.record(Answer(), {1, 2}, verdict="pass", metadata={"when": object})
    line = only_record(project)
    assert line["input"] == "an answer object"
    assert line["output"] == "{1, 2}"
    assert problems(line) == []


# It never breaks the user's program -----------------------------------------------------

class Broken:
    def __str__(self):
        raise RuntimeError("no text for you")


@pytest.mark.parametrize("call", [
    lambda: judgekeeper.record(Broken(), "a", verdict="pass"),
    lambda: judgekeeper.record("q", "a", score="high", pass_mark=0.5),
    lambda: judgekeeper.record("q", "a", score=0.5, pass_mark="half"),
    lambda: judgekeeper.record("q", "a", verdict="pass", metadata="not a dict"),
    lambda: judgekeeper.record("q", "a", verdict="pass", name=Broken()),
])
def test_no_error_escapes(project, call):
    assert call() is None


def test_an_unwritable_folder_never_raises_and_warns_once(project, caplog):
    (project / ".judgekeeper").write_text("a file where the folder should be", encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="judgekeeper"):
        assert judgekeeper.record("q", "a", verdict="pass") is None
        assert judgekeeper.record("q2", "a2", verdict="fail") is None
    warnings = [r for r in caplog.records if r.name == "judgekeeper"]
    assert len(warnings) == 1
    assert "judgekeeper.record()" in warnings[0].getMessage()
    assert "goes on" in warnings[0].getMessage()


def test_the_off_switch(project, monkeypatch):
    for off in ("0", "false", "off", "no", "OFF"):
        monkeypatch.setenv("JUDGEKEEPER_RECORD", off)
        judgekeeper.record("q", "a", verdict="pass")
    assert files(project) == []
    monkeypatch.setenv("JUDGEKEEPER_RECORD", "1")
    judgekeeper.record("q", "a", verdict="pass")
    assert len(files(project)) == 1


# Files, processes and threads -----------------------------------------------------------

def test_one_file_per_judge_name_in_one_process(project):
    for i in range(3):
        judgekeeper.record(f"q{i}", "a", verdict="pass", name="tone")
    judgekeeper.record("q", "a", verdict="pass", name="facts")
    by_name = {p.name.split("-")[0]: len(lines(p)) for p in files(project)}
    assert by_name == {"tone": 3, "facts": 1}


SCRIPT = """
import judgekeeper
for i in range(5):
    judgekeeper.record(f"question {i}", f"answer {i}", verdict=i % 2 == 0, name="tone")
"""


def test_two_processes_write_two_files(project):
    script = project / "eval.py"
    script.write_text(SCRIPT, encoding="utf-8")
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    env.pop("JUDGEKEEPER_RECORD", None)
    for _ in range(2):
        subprocess.run([sys.executable, str(script)], cwd=project, env=env, check=True)
    written = files(project)
    assert len(written) == 2
    assert [len(lines(p)) for p in written] == [5, 5]


def test_many_threads_write_whole_lines(project):
    def work(n):
        for i in range(50):
            judgekeeper.record(f"q{n}-{i}", "a" * 500, verdict="pass", name="tone")

    threads = [threading.Thread(target=work, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    (path,) = files(project)
    written = lines(path)  # every line is whole JSON
    assert len(written) == 400


# Where the project is -------------------------------------------------------------------

@pytest.mark.parametrize("marker", ["judgekeeper.toml", "pyproject.toml", "setup.py", ".git",
                                    "requirements-dev.txt"])
def test_records_go_to_the_nearest_project_root(tmp_path, monkeypatch, marker):
    root = tmp_path / "app"
    deeper = root / "evals" / "nightly"
    deeper.mkdir(parents=True)
    if marker == ".git":
        (root / ".git").mkdir()
    else:
        (root / marker).write_text("", encoding="utf-8")
    monkeypatch.chdir(deeper)
    monkeypatch.delenv("JUDGEKEEPER_RECORD", raising=False)
    recorder._reset()
    judgekeeper.record("q", "a", verdict="pass")
    recorder._reset()
    assert len(files(root)) == 1
    assert not (deeper / ".judgekeeper").exists()


def test_without_a_project_root_the_current_folder(tmp_path, monkeypatch):
    """The search stops below the home folder: home is never a project root."""
    (tmp_path / ".git").mkdir()  # a home folder kept in Git, as some people do
    here = tmp_path / "loose"
    here.mkdir()
    monkeypatch.chdir(here)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.delenv("JUDGEKEEPER_RECORD", raising=False)
    recorder._reset()
    judgekeeper.record("q", "a", verdict="pass")
    recorder._reset()
    assert len(files(here)) == 1


# Light, and standard library only -------------------------------------------------------

def test_the_recorder_imports_only_the_standard_library():
    tree = ast.parse((ROOT / "src" / "judgekeeper" / "recorder.py").read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            names.add(node.module.split(".")[0])
    names.discard("__future__")
    assert names <= set(sys.stdlib_module_names), names - set(sys.stdlib_module_names)


def test_importing_judgekeeper_and_recording_stays_light(tmp_path):
    code = ("import sys, judgekeeper; judgekeeper.record('q', 'a', verdict='pass'); "
            "print(sorted(m for m in sys.modules if m.startswith('judgekeeper')))")
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src"), "JUDGEKEEPER_RECORD": "0"}
    out = subprocess.run([sys.executable, "-c", code], cwd=tmp_path, env=env, check=True,
                         capture_output=True, text=True).stdout
    assert out.strip() == "['judgekeeper', 'judgekeeper.recorder']"


def test_record_is_in_the_package_api():
    assert "record" in judgekeeper.__all__
    from judgekeeper import record

    assert record is recorder.record
