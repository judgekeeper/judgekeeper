"""skills/judgekeeper/SKILL.md: the file coding agents load. It must parse, stay short, name
only commands and flags that exist, and say the rules: the agent runs `judgekeeper` and follows
each `Next:` line; only the person marks; the agent never touches `.judgekeeper/`, the page,
its link or its token. Nothing about steps that come back later (start, review, fix)."""

import re
import shlex
from pathlib import Path

import pytest

from judgekeeper import __version__
from judgekeeper.cli import parse_args

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / "skills" / "judgekeeper" / "SKILL.md"


def _split(text: str) -> tuple[dict, str]:
    lines = text.splitlines()
    assert lines[0] == "---", "SKILL.md starts with YAML frontmatter"
    end = lines.index("---", 1)
    meta = {}
    for line in lines[1:end]:
        key, _, value = line.partition(":")
        meta[key.strip()] = value.strip().removeprefix('"').removesuffix('"')
    return meta, "\n".join(lines[end + 1:])


def _body() -> str:
    return " ".join(_split(SKILL.read_text(encoding="utf-8"))[1].split())


def _commands(body: str) -> list[list[str]]:
    """Every `judgekeeper ...` or `uvx judgekeeper ...` in a code span, as its arguments."""
    spans = re.findall(r"`(?:uvx )?judgekeeper(?:@[\w.]+)?((?: [^`]*)?)`", body)
    return [shlex.split(span) for span in spans]


def test_frontmatter():
    meta, body = _split(SKILL.read_text(encoding="utf-8"))
    # Only the standard Agent Skills fields, so Claude Code, Cursor and Codex all load it.
    assert {"name", "description"} <= set(meta) <= {"name", "description", "license"}
    assert meta["name"] == "judgekeeper"
    assert 50 < len(meta["description"]) <= 1024
    assert body.strip()


DESCRIPTION = ("Check how often your LLM-as-a-judge agrees with people: you mark some answers, "
               "judgekeeper compares, and then keeps checking it. Use when a project grades "
               "outputs with an LLM judge (any model, including open-source ones run locally "
               "with Ollama or vLLM) in promptfoo, DeepEval, Inspect, MLflow or its own code, "
               "and the user wants to check or keep checking that judge.")


def test_the_description_says_what_it_does_in_plain_words_first():
    yaml = pytest.importorskip("yaml")
    text = SKILL.read_text(encoding="utf-8")
    meta = yaml.safe_load(text.split("---")[1])  # as an agent's YAML parser reads it
    assert meta["description"] == DESCRIPTION
    shown = meta["description"][:150]  # what the `/` menu shows the person
    for word in ("TPR", "TNR", "kappa"):
        assert word not in shown, word
    assert "Ollama" in meta["description"]


def test_under_60_lines():
    assert len(SKILL.read_text(encoding="utf-8").splitlines()) < 60


def test_it_starts_with_uvx_and_follows_each_next_line():
    body = _body()
    uvx = f"`uvx judgekeeper@{__version__}`"
    assert uvx in body
    assert "(or `judgekeeper` if installed)" in body
    assert "follow each `Next:` line" in body
    assert "Run it again the same way you started it." in body
    assert body.index(uvx) < body.index("## Rules")


def test_only_the_person_marks_and_the_agent_keeps_out_of_the_page():
    body = _body()
    for rule in ("Only the person marks.", "Never mark answers",
                 "never write or edit anything in `.judgekeeper/`",
                 "never send requests to the marking page", "never look for its link or token",
                 "Never read the answers' text"):
        assert rule in body, rule


def test_questions_are_asked_word_for_word_and_yes_is_theirs():
    body = _body()
    assert "Ask the person every question judgekeeper prints, word for word" in body
    assert "pass `--yes` only after their yes" in body


def test_the_result_is_tpr_tnr_and_kappa_with_ranges_and_the_drop():
    body = _body()
    assert "Report TPR, TNR and kappa together" in body
    assert "ranges" in body and '"this set can see a drop of' in body
    assert "Never report raw agreement on its own." in body


def test_only_the_person_turns_on_automatic_checks():
    body = _body()
    for rule in ('never click "Turn on"', "never write `checks.json`",
                 "run `judgekeeper check --off` when the person asks"):
        assert rule in body, rule


def test_keys_stay_in_environment_variables():
    body = _body()
    assert "Keys only in environment variables" in body
    assert "never print or write one" in body


def test_every_command_exists_in_the_cli():
    named = _commands(_body())
    assert [] in named and ["mark"] in named and ["check", "--off"] in named
    for argv in named:
        try:
            args = parse_args(argv)
        except SystemExit as e:
            if e.code in (0, None):  # --help prints and stops
                continue
            pytest.fail(f"SKILL.md names a command the CLI rejects: {argv} (exit {e.code})")
        assert args.command in (None, "mark") or argv == ["check", "--off"], argv


def test_nothing_about_steps_that_come_later():
    body = _body()
    for later in (r"\bstart\b", r"\breview", r"\bfix", r"Langfuse", r"--ask-again",
                  r"--try-new-judge", r"record\(\)"):
        assert not re.search(later, body, flags=re.IGNORECASE), later


def test_the_removed_commands_are_not_named():
    body = _body()
    for name in ("init", "judge", "validate", "baseline", "gate", "migrate", "import", "setup"):
        assert f"judgekeeper {name} " not in body and f"`judgekeeper {name}`" not in body, name


def test_no_link_to_the_website_while_it_is_offline():
    assert "judgekeeper.com" not in SKILL.read_text(encoding="utf-8")


def test_readme_links_the_skill():
    assert "skills/judgekeeper/SKILL.md" in (ROOT / "README.md").read_text(encoding="utf-8")
