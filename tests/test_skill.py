"""skills/judgekeeper/SKILL.md: the file coding agents load. It must parse, stay short, and
name only commands and flags that exist."""

import re
import shlex
from pathlib import Path

import pytest

from judgekeeper.cli import _parser

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / "skills" / "judgekeeper" / "SKILL.md"


def _split(text: str) -> tuple[dict, str]:
    lines = text.splitlines()
    assert lines[0] == "---", "SKILL.md starts with YAML frontmatter"
    end = lines.index("---", 1)
    meta = {}
    for line in lines[1:end]:
        key, _, value = line.partition(":")
        meta[key.strip()] = value.strip()
    return meta, "\n".join(lines[end + 1:])


def _command_lines(body: str) -> list[str]:
    """Every `judgekeeper ...` in a code block or an inline code span."""
    found = []
    in_block = False
    for line in body.splitlines():
        if line.strip().startswith("```"):
            in_block = not in_block
            continue
        if in_block and line.strip().startswith("judgekeeper "):
            found.append(line.strip())
    found += [m for m in re.findall(r"`([^`]+)`", body) if m.startswith("judgekeeper ")]
    return found


def test_frontmatter():
    meta, body = _split(SKILL.read_text(encoding="utf-8"))
    assert set(meta) == {"name", "description"}
    assert meta["name"] == "judgekeeper"
    assert 50 < len(meta["description"]) <= 1024
    assert body.strip()


def test_under_150_lines():
    assert len(SKILL.read_text(encoding="utf-8").splitlines()) < 150


def test_rules():
    text = SKILL.read_text(encoding="utf-8")
    assert "API keys come only from environment variables" in text
    assert "Never invent" in text and "human labels" in text
    for word in ("TPR", "TNR", "kappa"):
        assert word in text


def test_steps_in_order():
    text = SKILL.read_text(encoding="utf-8")
    heads = re.findall(r"^## (\d)\.", text, flags=re.MULTILINE)
    assert heads == ["1", "2", "3", "4", "5"]


def test_every_command_exists_in_the_cli():
    _, body = _split(SKILL.read_text(encoding="utf-8"))
    lines = [line for line in _command_lines(body) if "<" not in line]
    commands = {shlex.split(line)[1] for line in lines}
    assert {"init", "template", "label", "import-labels", "check", "judge", "validate",
            "import", "baseline", "gate"} <= commands
    parser = _parser()
    for line in lines:
        argv = shlex.split(line)[1:]
        try:
            parser.parse_args(argv)
        except SystemExit as e:  # pragma: no cover - the message is the failure
            if e.code in (0, None):  # --version prints and stops
                continue
            pytest.fail(f"SKILL.md names a command the CLI rejects: {line} (exit {e.code})")


def test_import_tools_exist():
    from judgekeeper.cli import _parser

    sub = next(a for a in _parser()._actions if a.dest == "command")
    tools = next(a for a in sub.choices["import"]._actions if a.dest == "tool").choices
    text = SKILL.read_text(encoding="utf-8")
    for tool in re.findall(r"judgekeeper import ([a-z]+)", text):
        assert tool in tools
    for tool in ("promptfoo", "deepeval", "inspect", "mlflow", "langfuse"):
        assert f"judgekeeper import {tool}" in text


def test_pytest_options_exist():
    plugin = (ROOT / "src" / "judgekeeper" / "pytest_plugin.py").read_text(encoding="utf-8")
    text = SKILL.read_text(encoding="utf-8")
    for option in set(re.findall(r"--judgekeeper-[a-z-]+", text)):
        assert f'"{option}"' in plugin
    assert "judgekeeper_gate" in text and "pytest.mark.judgekeeper" in text


def test_readme_links_the_skill():
    assert "skills/judgekeeper/SKILL.md" in (ROOT / "README.md").read_text(encoding="utf-8")


def test_the_three_doors_in_order_and_record_only_after_a_yes():
    text = SKILL.read_text(encoding="utf-8")
    doors = [text.index(d) for d in ("(1) `judgekeeper setup`", "(2) one `judgekeeper.record()`",
                                     "(3) a table")]
    assert doors == sorted(doors)
    assert "add a `judgekeeper.record()` line only after their yes on the diff" in text
