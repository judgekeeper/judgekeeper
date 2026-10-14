"""The `judgekeeper.record()` snippets in docs/reference.md.

The snippets write the same JSON line as `judgekeeper.record()`, for people who do not want
the import or use another language; judgekeeper reads the records they write, with no
problem in any line.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from judgekeeper import recorder
from judgekeeper.records import problems, read_records
from judgekeeper.textio import jsonl_lines

DOCS = Path(__file__).resolve().parent.parent / "docs"
RECORD_SECTION = "## record(): save your own judge's verdicts with one line\n"


def _section(path: Path, heading: str) -> str:
    text = path.read_text(encoding="utf-8")
    start = text.index(heading)
    end = text.find("\n## ", start + len(heading))
    return text[start:] if end == -1 else text[start:end]


def _blocks(text: str, language: str = "") -> list[str]:
    return re.findall(rf"```{language}\n(.*?)\n```", text, re.DOTALL)


def _snippets() -> dict[str, str]:
    section = _section(DOCS / "reference.md", RECORD_SECTION)
    found = {}
    for language in ("python", "typescript"):
        found[language] = [b for b in _blocks(section, language) if "jk_record" in b
                           or "jkRecord" in b]
    assert [len(v) for v in found.values()] == [1, 1], found
    return {k: v[0] for k, v in found.items()}


SNIPPETS = _snippets()


def check(folder) -> list[tuple]:
    """Every line in the folder is a record with no problem; (name, label, score) of each."""
    read = []
    for path in sorted(folder.glob("*.jsonl")):
        for line in jsonl_lines(path.read_text(encoding="utf-8")):
            if line.strip():
                assert problems(json.loads(line)) == []
        read += [(r.name, r.label, r.score) for r in read_records(path)]
    return read


# The snippets ----------------------------------------------------------------------------

def test_the_python_snippet_writes_records_that_pass_the_check(tmp_path):
    script = tmp_path / "eval.py"
    script.write_text(SNIPPETS["python"] + """

jk_record("Do you ship to Canada?", "Yes, in 5 days.", verdict="pass", name="Safe wording",
          reason="Clear.", judge="claude-opus-5", rule="Be polite.")
jk_record("Why was I charged twice?", "Your problem.", verdict=False, name="Safe wording")
jk_record({"question": "q"}, "a", score=0.3, name="Safe wording")
""", encoding="utf-8")
    subprocess.run([sys.executable, "-I", str(script)], cwd=tmp_path, check=True)
    folder = tmp_path / ".judgekeeper" / "records"
    assert len(list(folder.glob("Safe-wording-*.jsonl"))) == 1
    assert check(folder) == [("Safe wording", "pass", None), ("Safe wording", "fail", None),
                             ("Safe wording", None, 0.3)]  # a score with no pass mark


def test_the_python_snippet_never_raises(tmp_path):
    (tmp_path / ".judgekeeper").write_text("not a folder", encoding="utf-8")
    script = tmp_path / "eval.py"
    script.write_text(SNIPPETS["python"] + '\njk_record("q", "a", verdict="pass")\n'
                      'print("still running")\n', encoding="utf-8")
    out = subprocess.run([sys.executable, "-I", str(script)], cwd=tmp_path, check=True,
                         capture_output=True, text=True).stdout
    assert out == "still running\n"


def _node_runs_typescript() -> bool:
    node = shutil.which("node")
    if node is None:
        return False
    version = subprocess.run([node, "--version"], capture_output=True, text=True,
                             check=True).stdout
    major, minor = (int(x) for x in re.match(r"v(\d+)\.(\d+)", version).groups())
    # Node.js strips TypeScript types by default from 22.18 and 23.6 on
    return major >= 24 or (major, minor) >= (23, 6) or (22, 18) <= (major, minor) < (23, 0)


# CI's test job installs Node.js 22 and sets JUDGEKEEPER_NEEDS_NODE: there it must run.
@pytest.mark.skipif(not _node_runs_typescript() and not os.environ.get("JUDGEKEEPER_NEEDS_NODE"),
                    reason="needs Node.js 22.18 or later")
def test_the_typescript_snippet_writes_records_that_pass_the_check(tmp_path):
    script = tmp_path / "eval.ts"
    script.write_text(SNIPPETS["typescript"] + """

jkRecord("Do you ship to Canada?", "Yes, in 5 days.",
         { verdict: "pass", name: "Safe wording", reason: "Clear.", judge: "gpt-4.1" });
jkRecord("Why was I charged twice?", "Your problem.", { verdict: "fail", name: "Safe wording" });
""", encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.startswith("NODE_")}
    subprocess.run(["node", str(script)], cwd=tmp_path, check=True, env=env,
                   capture_output=True)
    folder = tmp_path / ".judgekeeper" / "records"
    assert len(list(folder.glob("Safe-wording-*.jsonl"))) == 1
    assert check(folder) == [("Safe wording", "pass", None), ("Safe wording", "fail", None)]


def test_the_snippets_write_the_same_fields():
    for name in ("schema_version", "annotator_kind", "label", "score", "explanation",
                 "evaluator", "created_at", ".judgekeeper", "records"):
        for language in ("python", "typescript"):
            assert name in SNIPPETS[language], (language, name)


def test_the_python_snippet_fits_on_a_screen():
    assert len(SNIPPETS["python"].splitlines()) <= 36


def test_the_snippets_say_where_to_run_them():
    for text in SNIPPETS.values():
        assert "project" in text.splitlines()[0] or "project" in text.splitlines()[1]


# The agent prompt ------------------------------------------------------------------------

# The snippets take record()'s arguments and write what it writes ----------------------------

CALLS = [
    {"input": "Do you ship to Canada?", "output": "Yes, in 5 days.", "score": 0.82,
     "pass_mark": 0.7, "reason": "Clear.", "judge": "claude-opus-5", "rule": "Be polite.",
     "name": "Safe wording", "temperature": 0, "id": "q01A", "metadata": {"topic": "shipping"}},
    {"input": {"question": "q"}, "output": "a", "score": 0.3, "pass_mark": 0.5,
     "name": "Safe wording"},
    {"input": "q2", "output": "a2", "verdict": False, "name": "Safe wording", "id": 7},
    {"input": "q3", "output": "a3", "verdict": " PASS ", "name": "Safe wording"},
    {"input": "q4", "output": "a4", "verdict": "maybe", "name": "Safe wording",
     "metadata": {"pass_mark": 0.9}, "pass_mark": 0.5},
    {"input": "q5", "output": "a5", "score": 0.4, "name": "Safe wording"},
]


def _lines(folder):
    files = sorted(folder.glob("*.jsonl"))
    assert len(files) == 1, files
    rows = [json.loads(line) for line in files[0].read_text(encoding="utf-8").splitlines()]
    for row in rows:
        assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", row.pop("created_at"))
    return files[0].name.rsplit("-", 1)[0], rows


def _by_record(tmp_path, monkeypatch):
    here = tmp_path / "record"
    here.mkdir()
    monkeypatch.chdir(here)
    recorder._reset()
    for call in CALLS:
        recorder.record(**call)
    return _lines(here / ".judgekeeper" / "records")


def test_the_python_snippet_takes_the_arguments_of_record():
    import inspect

    space = {}
    exec(SNIPPETS["python"], space)  # noqa: S102 - our own snippet
    assert list(inspect.signature(space["jk_record"]).parameters) == list(
        inspect.signature(recorder.record).parameters)


def test_the_python_snippet_writes_what_record_writes(tmp_path, monkeypatch):
    expected = _by_record(tmp_path, monkeypatch)
    here = tmp_path / "snippet"
    here.mkdir()
    script = here / "eval.py"
    script.write_text(SNIPPETS["python"] + "\n\nCALLS = " + repr(CALLS) +
                      "\nfor call in CALLS:\n    jk_record(**call)\n", encoding="utf-8")
    subprocess.run([sys.executable, "-I", str(script)], cwd=here, check=True)
    assert _lines(here / ".judgekeeper" / "records") == expected


@pytest.mark.skipif(not _node_runs_typescript() and not os.environ.get("JUDGEKEEPER_NEEDS_NODE"),
                    reason="needs Node.js 22.18 or later")
def test_the_typescript_snippet_writes_what_record_writes(tmp_path, monkeypatch):
    expected = _by_record(tmp_path, monkeypatch)
    here = tmp_path / "snippet"
    here.mkdir()
    calls = "\n".join(
        f"jkRecord({json.dumps(c['input'])}, {json.dumps(c['output'])}, "
        f"{json.dumps({k: v for k, v in c.items() if k not in ('input', 'output')})});"
        for c in CALLS)
    (here / "eval.ts").write_text(SNIPPETS["typescript"] + "\n\n" + calls + "\n",
                                  encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.startswith("NODE_")}
    subprocess.run(["node", "eval.ts"], cwd=here, check=True, env=env, capture_output=True)
    name, rows = _lines(here / ".judgekeeper" / "records")
    assert (name, rows) == expected
