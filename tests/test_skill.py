"""skills/judgekeeper/SKILL.md: the file coding agents load. It must parse, stay short, name
only commands and flags that exist, and walk the same path as the Guide: `judgekeeper start`,
`setup` or the `record()` line when nothing is found, the person's labels, the result, then
review, ask again or try a new judge, where the person answers the spending question."""

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
    assert {"start", "setup", "init", "import", "baseline", "gate"} <= commands
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


def _body() -> str:
    return " ".join(_split(SKILL.read_text(encoding="utf-8"))[1].split())


def test_the_steps_follow_start():
    body = _body()
    body = body[body.index("## Install"):]
    order = ["`judgekeeper --version`", "`judgekeeper start`", "`judgekeeper setup`",
             "what pass means", "`judgekeeper start --yes --no-browser`", "plain sentence",
             "`judgekeeper start --review`", "`judgekeeper start --ask-again`",
             "`judgekeeper start --try-new-judge`", "`Go ahead? [y/N]`",
             "judgekeeper baseline set"]
    at = [body.index(x) for x in order]
    assert at == sorted(at), [x for x, a in zip(order, at, strict=True)]


def test_it_names_start_setup_and_record():
    body = _body()
    for needed in ("judgekeeper start", "judgekeeper setup", "judgekeeper.record()",
                   "www.judgekeeper.com/assistant.html#add-the-record-line"):
        assert needed in body, needed


def test_the_person_labels_and_answers_the_spending_question():
    body = _body()
    assert "the person does the labeling" in body and "you never label" in body
    assert "the person answers `Go ahead? [y/N]` themselves" in body
    steps = body[body.index("## 4."):]
    assert "never pass `--allow-calls`" in steps


def test_the_older_commands_are_one_advanced_note():
    body = _body()
    note = body.index("Advanced, only if the person asks:")
    for older in ("judgekeeper label ", "judgekeeper import-labels", "judgekeeper judge ",
                  "judgekeeper validate", "judgekeeper check "):
        assert older not in body[:note], older
    assert "judge, validate, check, import" in body[note:]


def test_it_never_shows_an_install_outside_a_project():
    body = _body()
    for outside in ("pipx", "uv tool", "uvx", "pip3 install", "--user", "-g ",
                    "py -m pip install judgekeeper"):
        assert outside not in body, outside
    assert "with the project's virtual environment active, `pip install judgekeeper`" in body
