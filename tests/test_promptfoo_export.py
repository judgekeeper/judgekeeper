"""When promptfoo's results are only in its database, `start` offers to run promptfoo's own
`export` command (at a terminal only, Enter is No). The one process function is replaced: no
promptfoo, except a fake project promptfoo that leaves a file when it runs."""

from __future__ import annotations

import builtins
import json
import sys
from types import SimpleNamespace

import pytest

from judgekeeper import again, start, start_export
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
                            installed=True, ran_config=False)

    def run_process(argv, cwd, env=None, timeout=None):
        state.calls.append(SimpleNamespace(argv=list(argv), cwd=cwd, env=dict(env or {})))
        if (cwd / "promptfooconfig.js").is_file():  # promptfoo loads it from where it runs
            state.ran_config = True
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
    code = main([*map(str, argv)])
    out, err = capsys.readouterr()
    return code, out, err


def test_a_run_from_another_project_is_deleted(tmp_path, capsys, export, terminal):
    _config(tmp_path, description="my project")
    terminal += ["y"]
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
    terminal += ["y"]
    _, out, _ = run(capsys, tmp_path)
    assert "from another project" in out
    assert not (tmp_path / "promptfoo-results.json").exists()


def test_matching_prompts_carry_on_without_a_description(tmp_path, capsys, export, terminal):
    _config(tmp_path, description=None, prompt="Answer: {{question}}")
    export.data["config"] = {"prompts": ["Answer: {{question}}"]}
    terminal += ["y", "n"]
    run(capsys, tmp_path)
    assert (tmp_path / "promptfoo-results.json").is_file()


def test_the_export_runs_no_config_from_the_project(tmp_path, capsys, export, terminal):
    """A promptfoo on the PATH loads a promptfooconfig.js from where it runs: the export runs
    in a temp folder of its own, and its file still lands in the project."""
    (tmp_path / "evals").mkdir()
    _config(tmp_path / "evals", description=None)
    (tmp_path / "promptfooconfig.js").write_text(
        "module.exports = {prompts: ['Answer: {{question}}']};\n", encoding="utf-8")
    export.data["config"] = {"prompts": ["Answer: {{question}}"]}
    terminal += ["y", "n"]
    run(capsys, tmp_path)
    assert export.ran_config is False
    [call] = export.calls
    assert not call.cwd.exists() and not call.cwd.is_relative_to(tmp_path)
    assert (tmp_path / "promptfoo-results.json").is_file()


@pytest.mark.parametrize("described", [True, False], ids=["description", "prompts"])
def test_a_config_in_a_subfolder_keeps_the_projects_own_run(tmp_path, capsys, export, terminal,
                                                             described):
    """The run is checked against the config Find found, wherever it is (evals/ here)."""
    (tmp_path / "evals").mkdir()
    _config(tmp_path / "evals", description="support bot" if described else None)
    export.data["config"] = ({"description": "support bot"} if described
                             else {"prompts": ["Answer: {{question}}"]})
    terminal += ["y", "n"]
    _, out, _ = run(capsys, tmp_path)
    assert "from another project" not in out
    assert (tmp_path / "promptfoo-results.json").is_file()


def test_a_run_unlike_the_config_in_a_subfolder_is_not_kept(tmp_path, capsys, export, terminal):
    (tmp_path / "evals").mkdir()
    _config(tmp_path / "evals", description=None)
    export.data["config"] = {"prompts": ["Something else: {{x}}"]}
    terminal += ["y"]
    _, out, _ = run(capsys, tmp_path)
    assert ("That was your last promptfoo run, from another project. Find yours with promptfoo "
            "list evals -n 10, then run promptfoo export eval <id> -o promptfoo-results.json."
            ) in out
    assert not (tmp_path / "promptfoo-results.json").exists()
    assert not (tmp_path / ".judgekeeper" / "promptfoo-latest.json").exists()


def test_with_no_config_found_no_run_is_this_projects(tmp_path):
    data = {"config": {"prompts": ["Answer: {{question}}"]}}
    assert start_export._this_project(None, data) is False
    assert start_export._this_project(tmp_path / "promptfooconfig.yaml", data) is False


def _marking_promptfoo(root):
    """The project's own promptfoo, as a folder could ship it: it leaves `ran-promptfoo`."""
    folder = root / "node_modules" / ".bin"
    folder.mkdir(parents=True)
    ran = root / "ran-promptfoo"
    (folder / "promptfoo").write_text(f"#!/bin/sh\necho ran > '{ran}'\nexit 1\n",
                                      encoding="utf-8")
    (folder / "promptfoo").chmod(0o755)
    (folder / "promptfoo.cmd").write_text(f'@echo ran> "{ran}"\r\n@exit /b 1\r\n',
                                          encoding="utf-8")
    return root / "ran-promptfoo"


def test_only_a_yes_runs_the_projects_promptfoo(tmp_path, capsys, monkeypatch):
    _config(tmp_path)
    ran = _marking_promptfoo(tmp_path)
    monkeypatch.setattr(again, "which", lambda name: None)
    run(capsys, tmp_path)  # no terminal
    run(capsys, tmp_path, "--yes")
    assert not ran.exists()

    monkeypatch.setattr(start, "_interactive", lambda: True)
    asked = []
    monkeypatch.setattr(builtins, "input", lambda prompt="": asked.append(prompt) or "")
    _, out, _ = run(capsys, tmp_path)  # Enter
    assert not ran.exists(), out
    assert "promptfoo export eval latest -o promptfoo-results.json" in " ".join(out.split())
    question = next(q for q in asked if "promptfoo" in q)
    assert question == ("Run this project's promptfoo (node_modules/.bin/promptfoo"
                        f"{'.cmd' if sys.platform == 'win32' else ''}) to export your latest "
                        "results? It runs code from this folder, like running its tests. "
                        "No AI call. [y/N] ")

    monkeypatch.setattr(builtins, "input", lambda prompt="": "y")
    run(capsys, tmp_path)
    assert ran.exists()


def test_a_promptfoo_on_the_path_is_named_too(tmp_path, capsys, export, terminal):
    _config(tmp_path)
    terminal += ["n"]
    _, out, _ = run(capsys, tmp_path)
    assert (f"Run promptfoo ({PROMPTFOO}) to export your latest results? It reads promptfoo's "
            "database in your home folder and writes one file here. No AI call. [y/N]") in out
    assert export.calls == []
