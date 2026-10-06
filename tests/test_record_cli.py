"""`judgekeeper record --snippet python|typescript` and `judgekeeper record --agent-prompt`.

The snippets write the same JSON line as `judgekeeper.record()`, for people who do not want
the import or use another language; the records they write pass `import records --check`.
The agent prompt asks the user's coding agent to add one `record()` call where the judge
runs, touch nothing else, show the diff and wait for a yes, then check the records.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys

import pytest

from judgekeeper import recorder
from judgekeeper.cli import main


def run(capsys, *argv):
    code = main(["record", *argv])
    out, err = capsys.readouterr()
    return code, out, err


def check(capsys, folder):
    code = main(["import", "records", str(folder), "--check"])
    return code, capsys.readouterr().out


# The snippets ----------------------------------------------------------------------------

def test_the_python_snippet_is_printed(capsys):
    code, out, _ = run(capsys, "--snippet", "python")
    assert code == 0
    assert out == recorder.SNIPPETS["python"] + "\n"
    assert len(recorder.SNIPPETS["python"].splitlines()) <= 17


def test_the_typescript_snippet_is_printed(capsys):
    code, out, _ = run(capsys, "--snippet", "typescript")
    assert code == 0
    assert out == recorder.SNIPPETS["typescript"] + "\n"


def test_the_python_snippet_writes_records_that_pass_the_check(tmp_path, capsys):
    script = tmp_path / "eval.py"
    script.write_text(recorder.SNIPPETS["python"] + """

jk_record("Do you ship to Canada?", "Yes, in 5 days.", verdict="pass", name="Safe wording",
          reason="Clear.", judge="claude-opus-5", rule="Be polite.")
jk_record("Why was I charged twice?", "Your problem.", verdict=False, name="Safe wording")
jk_record({"question": "q"}, "a", score=0.3, name="Safe wording")
""", encoding="utf-8")
    subprocess.run([sys.executable, "-I", str(script)], cwd=tmp_path, check=True)
    folder = tmp_path / ".judgekeeper" / "records"
    assert len(list(folder.glob("Safe-wording-*.jsonl"))) == 1
    code, out = check(capsys, folder)
    assert 'Judge "Safe wording": 1 pass, 1 fail, 1 score with no pass mark' in out
    assert code == 0


def test_the_python_snippet_never_raises(tmp_path):
    (tmp_path / ".judgekeeper").write_text("not a folder", encoding="utf-8")
    script = tmp_path / "eval.py"
    script.write_text(recorder.SNIPPETS["python"] + '\njk_record("q", "a", verdict="pass")\n'
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
def test_the_typescript_snippet_writes_records_that_pass_the_check(tmp_path, capsys):
    script = tmp_path / "eval.ts"
    script.write_text(recorder.SNIPPETS["typescript"] + """

jkRecord("Do you ship to Canada?", "Yes, in 5 days.",
         { verdict: "pass", name: "Safe wording", reason: "Clear.", judge: "gpt-4.1" });
jkRecord("Why was I charged twice?", "Your problem.", { verdict: "fail", name: "Safe wording" });
""", encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.startswith("NODE_")}
    subprocess.run(["node", str(script)], cwd=tmp_path, check=True, env=env,
                   capture_output=True)
    folder = tmp_path / ".judgekeeper" / "records"
    assert len(list(folder.glob("Safe-wording-*.jsonl"))) == 1
    code, out = check(capsys, folder)
    assert 'Judge "Safe wording": 1 pass, 1 fail.' in out
    assert code == 0


def test_the_snippets_write_the_same_fields():
    for name in ("schema_version", "annotator_kind", "label", "score", "explanation",
                 "evaluator", "created_at", ".judgekeeper", "records"):
        for language in ("python", "typescript"):
            assert name in recorder.SNIPPETS[language], (language, name)


def test_the_snippets_say_where_to_run_them():
    for text in recorder.SNIPPETS.values():
        assert "project" in text.splitlines()[0] or "project" in text.splitlines()[1]


# The agent prompt ------------------------------------------------------------------------

def test_the_agent_prompt_is_printed(capsys):
    code, out, _ = run(capsys, "--agent-prompt")
    assert code == 0
    assert out == recorder.AGENT_PROMPT + "\n"


def test_the_agent_prompt_says_what_to_do_and_what_not_to():
    text = " ".join(recorder.AGENT_PROMPT.split())
    for words in ("where this project's LLM judge produces each score or verdict",
                  "judgekeeper.record(", "input", "output", "pass_mark", "reason", "judge=",
                  "rule=", "name=", "verdict=", "Touch nothing else",
                  "can never change what the program does",
                  "Show me the diff and wait for my yes before saving",
                  "judgekeeper import records .judgekeeper/records --check",
                  "this project's own Python environment", "JUDGEKEEPER_RECORD=0"):
        assert words in text, words


def test_the_agent_prompt_installs_inside_the_project_only():
    for outside in ("pipx", "uv tool", "uvx", "pip3 install", "--user", "-g "):
        assert outside not in recorder.AGENT_PROMPT


def test_record_needs_one_of_its_flags(capsys):
    code, _, err = run(capsys)
    assert code == 2
    assert "--snippet" in err and "--agent-prompt" in err
    assert main(["record", "--snippet", "rust"]) == 2


def test_the_reference_shows_the_same_snippets_and_the_commands():
    from pathlib import Path

    text = (Path(__file__).resolve().parent.parent / "docs" / "reference.md").read_text(
        encoding="utf-8")
    for language, snippet in recorder.SNIPPETS.items():
        assert f"```{language}\n{snippet}\n```" in text, language
    for command in ("judgekeeper record --snippet python",
                    "judgekeeper record --snippet typescript",
                    "judgekeeper record --agent-prompt", "JUDGEKEEPER_RECORD=0"):
        assert command in text
