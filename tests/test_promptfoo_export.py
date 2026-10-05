"""When promptfoo's results are only in its database, `start` offers to run promptfoo's own
`export` command (at a terminal only). The one process function is replaced: no promptfoo."""

from __future__ import annotations

import builtins
import json
from types import SimpleNamespace

import pytest

from judgekeeper import again, start
from judgekeeper.cli import main
from tests.start_projects import promptfoo_data, split

PROMPTFOO = "/usr/local/bin/promptfoo"


def _config(root, description="support bot", prompt="Answer: {{question}}"):
    lines = ([f"description: {description}"] if description else [])
    lines += ["prompts:", f"  - '{prompt}'"]
    (root / "promptfooconfig.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")


@pytest.fixture
def export(monkeypatch):
    """promptfoo on the PATH; `export` writes `data` to the -o file."""
    state = SimpleNamespace(calls=[], data=promptfoo_data(split(20, 16)), code=0, stderr="",
                            installed=True)

    def run_process(argv, cwd, env=None, timeout=None):
        state.calls.append(SimpleNamespace(argv=list(argv), cwd=cwd, env=dict(env or {})))
        if state.code == 0:
            out = cwd / argv[argv.index("-o") + 1]
            out.write_text(json.dumps(state.data), encoding="utf-8")
        return SimpleNamespace(returncode=state.code, stdout="", stderr=state.stderr)

    monkeypatch.setattr(again, "run_process", run_process)
    monkeypatch.setattr(again, "which",
                        lambda name: PROMPTFOO if name == "promptfoo" and state.installed
                        else None)
    return state


@pytest.fixture
def terminal(monkeypatch):
    answers: list[str] = []
    monkeypatch.setattr(start, "_interactive", lambda: True)

    def fake_input(prompt=""):
        print(prompt)
        return answers.pop(0) if answers else "n"

    monkeypatch.setattr(builtins, "input", fake_input)
    return answers


def run(capsys, *argv):
    code = main(["start", *map(str, argv)])
    out, err = capsys.readouterr()
    return code, out, err


QUESTION = ("Run promptfoo export for you? It reads promptfoo's database in your home folder "
            "and writes one file here. No AI call. [Y/n]")


def test_yes_exports_checks_and_carries_on(tmp_path, capsys, export, terminal):
    _config(tmp_path)
    terminal += ["", "n"]  # yes to the export, no to opening the labeling page
    code, out, _ = run(capsys, tmp_path)
    assert code == 0
    assert QUESTION in out
    (call,) = export.calls
    assert call.argv == [PROMPTFOO, "export", "eval", "latest", "-o",
                         ".judgekeeper/promptfoo-latest.json"]
    assert call.cwd == tmp_path.resolve()
    for name in ("PROMPTFOO_DISABLE_TELEMETRY", "PROMPTFOO_DISABLE_UPDATE",
                 "PROMPTFOO_DISABLE_DEBUG_LOG", "PROMPTFOO_DISABLE_ERROR_LOG"):
        assert call.env[name] == "1", name
    assert (tmp_path / "promptfoo-results.json").is_file()
    assert not (tmp_path / ".judgekeeper" / "promptfoo-latest.json").exists()
    assert "Your eval tool: promptfoo (promptfoo-results.json" in out
    assert "36 answers with a verdict" in out


def test_a_run_from_another_project_is_deleted(tmp_path, capsys, export, terminal):
    _config(tmp_path, description="my project")
    terminal += [""]
    code, out, _ = run(capsys, tmp_path)
    assert code == 0
    assert ("That was your last promptfoo run, from another project. Find yours with promptfoo "
            "list evals -n 10, then run promptfoo export eval <id> -o promptfoo-results.json."
            ) in out
    assert not (tmp_path / ".judgekeeper" / "promptfoo-latest.json").exists()
    assert not (tmp_path / "promptfoo-results.json").exists()


def test_other_prompts_also_mean_another_project(tmp_path, capsys, export, terminal):
    _config(tmp_path, description=None, prompt="Reply kindly: {{question}}")
    export.data["config"] = {"prompts": ["Something else: {{x}}"]}
    terminal += [""]
    _, out, _ = run(capsys, tmp_path)
    assert "from another project" in out
    assert not (tmp_path / "promptfoo-results.json").exists()


def test_matching_prompts_carry_on_without_a_description(tmp_path, capsys, export, terminal):
    _config(tmp_path, description=None, prompt="Answer: {{question}}")
    export.data["config"] = {"prompts": ["Answer: {{question}}"]}
    terminal += ["", "n"]
    run(capsys, tmp_path)
    assert (tmp_path / "promptfoo-results.json").is_file()


def test_an_existing_file_is_asked_about(tmp_path, capsys, export, terminal):
    _config(tmp_path)
    (tmp_path / "promptfoo-results.json").write_text("not results", encoding="utf-8")
    terminal += ["", "n"]  # yes to the export, no to replacing the file
    code, out, _ = run(capsys, tmp_path)
    assert code == 0
    assert "promptfoo-results.json is already here. Replace it? [y/N]" in out
    assert (tmp_path / "promptfoo-results.json").read_text() == "not results"
    assert (tmp_path / ".judgekeeper" / "promptfoo-latest.json").is_file()
    assert "judgekeeper start .judgekeeper/promptfoo-latest.json" in out


def test_no_prints_the_commands(tmp_path, capsys, export, terminal):
    _config(tmp_path)
    terminal += ["n"]
    code, out, _ = run(capsys, tmp_path)
    assert code == 0 and export.calls == []
    assert "promptfoo export eval latest -o promptfoo-results.json" in out


def test_never_without_a_terminal(tmp_path, capsys, export):
    _config(tmp_path)
    code, out, _ = run(capsys, tmp_path)
    assert code == 0 and export.calls == []
    assert QUESTION not in out
    assert "promptfoo list evals -n 10" in out


def test_promptfoo_not_installed(tmp_path, capsys, export, terminal):
    _config(tmp_path)
    export.installed = False
    terminal += [""]
    code, out, _ = run(capsys, tmp_path)
    assert code == 0 and export.calls == []
    assert "promptfoo was not found here, so judgekeeper can't run the export for you." in out
    assert "promptfoo list evals -n 10" in out


def test_a_failed_export_says_why(tmp_path, capsys, export, terminal):
    _config(tmp_path)
    export.code, export.stderr = 1, "Error: no evals found\n"
    terminal += [""]
    code, out, _ = run(capsys, tmp_path)
    assert code == 0
    assert "promptfoo export did not work: Error: no evals found" in out
    assert "promptfoo list evals -n 10" in out
