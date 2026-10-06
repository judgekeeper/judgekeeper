"""The path for coding assistants: docs/assistant-prompt.md (the prompt a person pastes),
docs/assistant.md (the page that shows it) and skills/judgekeeper/SKILL.md (the skill).

The prompt is short, carries the three rules that must never be lost (labels, keys, the call
count), and names only commands the real CLI accepts. The page shows the prompt exactly.
"""

from __future__ import annotations

import html
import importlib.util
import re

import pytest

from judgekeeper.cli import _parser
from tests.website_pages import ROOT, command_lines, judgekeeper_argv

PROMPT = ROOT / "docs" / "assistant-prompt.md"
PAGE = ROOT / "docs" / "assistant.md"
SKILL = ROOT / "skills" / "judgekeeper" / "SKILL.md"
PLACEHOLDER = re.compile(r"<[a-z]|\[--|\.\.\.")  # syntax lines such as import <tool>
FENCE = re.compile(r"^```\w*\n(.*?)^```$", flags=re.DOTALL | re.MULTILINE)
SKILL_DESCRIPTION = (
    "Check whether a project's LLM-as-judge agrees with human labels (TPR, TNR, kappa, "
    "run-to-run noise, position bias) using judgekeeper, and gate CI on it. Use when a project "
    "grades outputs with an LLM judge, eval framework or rubric model and the user asks if the "
    "judge can be trusted, wants human labels, or wants a judge check in CI.")


def _read(path) -> str:
    return path.read_text(encoding="utf-8")


def _flat(text: str) -> str:
    """One line, single spaces, lowercase: a rule may wrap anywhere in the file."""
    return " ".join(text.split()).lower()


def _blocks(markdown: str) -> list[str]:
    return FENCE.findall(markdown)


def _commands(markdown: str) -> list[tuple[str, list[str]]]:
    """(line, argv) for every judgekeeper command: lines in a fenced block, lines indented by
    four spaces, and inline `code` spans. Syntax lines with a placeholder are left out."""
    lines = []
    for block in _blocks(markdown):
        lines += command_lines(block)
    prose = FENCE.sub("", markdown)
    lines += command_lines("\n".join(x for x in prose.splitlines() if x.startswith("    ")))
    lines += re.findall(r"`([^`\n]+)`", prose)
    found = []
    for line in lines:
        argv = judgekeeper_argv(line)
        if argv is not None and not PLACEHOLDER.search(line):
            found.append((line, argv))
    return found


def _check_parses(found: list[tuple[str, list[str]]], where: str) -> None:
    for line, argv in found:
        try:
            _parser().parse_args(argv)
        except SystemExit as e:
            if e.code not in (0, None):  # 0: --version, which prints and stops
                pytest.fail(f"{where} names a command the CLI rejects: {line} (exit {e.code})")


def _subcommands(found: list[tuple[str, list[str]]]) -> set[str]:
    return {argv[0] for _, argv in found if argv}


# The prompt

def test_the_prompt_is_at_most_60_lines():
    text = _read(PROMPT)
    assert text.endswith("\n") and not text.endswith("\n\n")
    assert len(text.splitlines()) <= 60


def test_the_prompt_can_sit_inside_one_code_block():
    assert not any(line.startswith("```") for line in _read(PROMPT).splitlines())


def test_the_prompt_carries_the_label_rule():
    text = _flat(_read(PROMPT))
    assert "never invent, guess or generate a human label" in text
    assert "never let a model fill one in" in text
    assert "127.0.0.1" in text  # the labeling page is local, and the prompt says so


def test_the_prompt_carries_the_key_rule():
    text = _flat(_read(PROMPT))
    assert "environment variables" in text
    assert "never write a key" in text
    assert "ANTHROPIC_API_KEY" in _read(PROMPT)
    # A key starts a word ("sk-ant-..."); --ask-again holds the same letters mid-word.
    assert not re.search(r"(?<![\w-])sk-[A-Za-z0-9]", _read(PROMPT))
    assert re.search(r"(?<![\w-])sk-[A-Za-z0-9]", "export KEY=sk-ant-abc")


def test_the_prompt_carries_the_call_count_rule():
    text = _flat(_read(PROMPT))
    assert re.search(r"number of judge calls[^.]* before|before[^.]* number of judge calls", text)
    assert "wait for my yes" in text


def test_the_prompt_says_the_page_opens_only_with_the_token_link():
    """The link changes on every start and carries a token, so the human needs the exact one
    the command printed: from their own terminal, or handed over by the assistant."""
    step = _flat(_read(PROMPT))
    step = step[step.index("4. open the labeling page"):step.index("5. tell me the result")]
    assert "prints a link that includes a token" in step
    assert "the page opens only with that full link" in step
    assert "the link changes each time the command starts" in step
    assert "in my own terminal" in step and "the exact link it printed" in step


def test_the_prompt_asks_what_pass_means_before_labeling():
    """With a judge already in the project, the labels must follow the human's rule, not the
    judge's: the human says the rule before the labeling page opens."""
    text = _flat(_read(PROMPT))
    assert "say in one sentence what pass means before i label" in text
    assert "not the judge's" in text
    assert text.index("what pass means before i label") < text.index(
        "`judgekeeper start --yes --no-browser`")


def test_the_prompt_starts_with_the_install():
    text = _read(PROMPT)
    assert "pip install judgekeeper" in text
    assert text.index("pip install judgekeeper") < text.index("`judgekeeper --version`")
    assert "judgekeeper demo" not in text


def test_the_prompt_follows_todays_path():
    """Install inside the project, start to see what it found, setup or record() when it finds
    nothing, the person labels, then the result and what comes next."""
    text = _read(PROMPT)
    flat = _flat(text)
    found = _commands(text)
    assert {"start", "setup", "record"} <= _subcommands(found)
    starts = [argv for _, argv in found if argv[:1] == ["start"]]
    for flags in (["--yes", "--no-browser"], ["--review"], ["--ask-again"],
                  ["--try-new-judge"]):
        assert ["start", *flags] in starts, flags
    assert flat.index("`judgekeeper start`") < flat.index("`judgekeeper setup`") < flat.index(
        "`judgekeeper start --yes --no-browser`")
    assert "show me its questions instead of answering them for me" in flat
    assert "there is no judge" in flat
    assert "stop and ask" in flat
    assert "never pass `--allow-calls`" in flat and "i answer that question myself" in flat
    # The older commands only as a short note at the end, never as steps.
    advanced = flat[flat.index("advanced, only if i ask"):]
    assert "tutorial.html" in advanced
    for name in ("label", "judge", "validate"):
        assert f"`judgekeeper {name} " not in text, name


def test_the_prompt_reports_in_plain_words_and_never_agreement_alone():
    flat = _flat(_read(PROMPT))
    assert "plain sentence" in flat
    assert flat.index("plain sentence") < flat.index("kappa")
    for word in ("tpr", "tnr", "kappa", "flag"):
        assert word in flat, word
    assert re.search(r"never [^.]*(agreement|accuracy)[^.]* (alone|on its own)", flat)


def test_every_command_in_the_prompt_parses():
    found = _commands(_read(PROMPT))
    assert len(found) >= 7
    _check_parses(found, "docs/assistant-prompt.md")


# The page

def test_the_page_embeds_the_prompt_verbatim_in_one_code_block():
    prompt = _read(PROMPT)
    holding = [block for block in _blocks(_read(PAGE)) if block == prompt]
    assert len(holding) == 1, "docs/assistant.md shows docs/assistant-prompt.md exactly, once"


def test_the_page_has_its_four_parts_in_order():
    heads = re.findall(r"^## (.+)$", FENCE.sub("", _read(PAGE)), flags=re.MULTILINE)
    assert len(heads) == 4
    for head, needle in zip(heads, ("skill", "prompt", "What happens next", "Works with"),
                            strict=True):
        assert needle in head, head


def test_the_page_shows_the_skill_install_and_the_fallback():
    text = _read(PAGE)
    assert "npx skills add judgekeeper/judgekeeper" in text
    part = text[text.index("## "):text.index("## ", text.index("## ") + 3)]
    assert "private today" not in text
    assert "Paste the prompt below" in part


def test_the_page_says_what_the_human_does_and_what_is_out_of_scope():
    text = FENCE.sub("", _read(PAGE))
    flat = _flat(text)
    assert "the labels" in flat
    for name in ("Claude Code", "Codex", "Cursor"):
        assert name in text, name
    works_with = text[text.index("## Works with"):]
    (line,) = [x for x in works_with.splitlines() if "browser" in x]
    assert "chat" in line.lower() and "out of scope" in line.lower()


def test_the_page_is_in_plain_words():
    text = FENCE.sub("", _read(PAGE))
    for word in ("TPR", "TNR", "kappa"):
        assert word not in text, f"{word} belongs in the guide, not on this page"
    figure = r"(?<![\d.])\d+\.\d+(?![\d.])|\d+\s?%"  # 127.0.0.1 is not a figure
    assert not re.search(figure, text), "no figures on this page"


def test_every_command_on_the_page_parses():
    page = _read(PAGE).replace(_read(PROMPT), "")  # the prompt is checked on its own
    found = _commands(page)
    assert "judgekeeper demo" not in page
    _check_parses(found, "docs/assistant.md")


def test_the_renderer_keeps_the_prompt_whole():
    """The page uses only the Markdown scripts/render_reference.py reads, so the website page
    made from it shows the prompt in one <pre> block."""
    spec = importlib.util.spec_from_file_location(
        "render_reference", ROOT / "scripts" / "render_reference.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    rendered = module.render(_read(PAGE))
    prompt = _read(PROMPT).rstrip("\n")
    assert f"<pre><code>{html.escape(prompt, quote=False)}</code></pre>" in rendered
    assert rendered.count("<h2") == 4


# The skill

def _skill_body() -> str:
    return _read(SKILL).split("\n---\n", 1)[1]


def test_the_skill_keeps_its_description():
    head = _read(SKILL).split("\n---\n", 1)[0]
    assert f"description: {SKILL_DESCRIPTION}" in head.splitlines()


def test_the_skill_installs_first_and_names_no_demo():
    body = _skill_body()
    assert "`judgekeeper --version`" in body
    assert body.index("`judgekeeper --version`") < body.index("## 1.")
    assert "judgekeeper demo" not in body


def test_the_skill_reports_in_plain_words():
    flat = _flat(_skill_body())
    assert "plain sentence" in flat
    step = flat[flat.index("## 4."):flat.index("## 5.")]
    assert step.index("plain sentence") < step.index("kappa")


def test_the_skill_sends_the_human_to_the_labeling_page():
    body = _skill_body()
    step = body[body.index("## 2."):body.index("## 3.")]
    assert "judgekeeper label items.jsonl" in step
    assert "127.0.0.1" in step
    assert step.index("judgekeeper label ") < step.index("judgekeeper template ")
    assert "Stop." in step


def test_the_skill_says_the_page_opens_only_with_the_token_link():
    body = _skill_body()
    step = _flat(body[body.index("## 2."):body.index("## 3.")])
    assert "prints a link that includes a token" in step
    assert "the page opens only with that full link" in step
    assert "the exact link it printed" in step


def test_the_skill_asks_what_pass_means_before_labeling():
    flat = _flat(_skill_body())
    assert "say in one sentence what pass means before they label" in flat
    assert "not the judge's" in flat
    assert flat.index("what pass means before they label") < flat.index("judgekeeper label ")


def test_the_skill_says_what_the_callable_receives():
    body = _skill_body()
    step = _flat(body[body.index("## 3."):body.index("## 4.")])
    assert "one item as a dict with `id`, `input` and `output`" in step


def test_every_command_in_the_skill_parses():
    found = _commands(_skill_body())
    assert len(found) >= 15
    _check_parses(found, "skills/judgekeeper/SKILL.md")
