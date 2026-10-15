"""`judgekeeper start` in the docs and on the website: the terminal text the site shows, the
Guide (start.html), the reference, the README and the version.

The terminal text on the website is real: `start_screen` runs `judgekeeper start` on a test
project (212 promptfoo answers, the judge passed 171 and failed 41) in a folder named
support-bot, up to its last question. Two things are fixed so the text is the same
on every machine: the time zone (UTC) and the folder's place, shown as /Users/me/support-bot.
"""

from __future__ import annotations

import builtins
import io
import re
import sys
import time
import tomllib

import pytest

from judgekeeper import __version__, start
from judgekeeper.cli import main, version_lines
from tests.start_projects import promptfoo_project, split
from tests.website_pages import ROOT, WEBSITE, Element, parse

README = ROOT / "README.md"
REFERENCE = ROOT / "docs" / "reference.md"
SHOWN_PROJECT = "/Users/me/support-bot"


@pytest.fixture
def utc(monkeypatch):
    if not hasattr(time, "tzset"):
        pytest.skip("the time zone cannot be set here")
    monkeypatch.setenv("TZ", "UTC")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


def start_screen(tmp_path, monkeypatch, capsys) -> list[str]:
    project = tmp_path / "support-bot"
    promptfoo_project(project, split(171, 41), rubric="is polite and correct")
    monkeypatch.chdir(project)
    monkeypatch.setattr(start, "_interactive", lambda: True)
    monkeypatch.setattr(builtins, "input", lambda prompt="": print(prompt) or "n")
    capsys.readouterr()
    assert main(["start"]) == 0
    out = capsys.readouterr().out.replace(str(project.resolve()), SHOWN_PROJECT)
    lines = [line.rstrip() for line in out.strip("\n").splitlines()]
    return lines[:lines.index("Open it now? [Y/n]") + 1]  # up to the question


def _els(page: str) -> list[Element]:
    return list(parse(WEBSITE / page).iter())


def _by_id(page: str, wanted: str) -> Element:
    return next(el for el in _els(page) if el.attrs.get("id") == wanted)


def _output(page: str, name: str) -> list[list[str]]:
    blocks = [el for el in _els(page) if el.attrs.get("data-output") == name]
    for block in blocks:
        assert block.tag == "pre" and "output" in block.classes()
    return [[line.rstrip() for line in b.text().strip("\n").splitlines()] for b in blocks]


def _codes(el: Element) -> list[str]:
    return [c.text() for c in el.iter() if c.tag == "code" and c.parent.tag == "pre"
            and "output" not in c.parent.classes()]


def _flat(el: Element) -> str:
    return " ".join(el.text().split())


def _sections(path) -> dict[str, str]:
    parts = re.split(r"^## ", path.read_text(encoding="utf-8"), flags=re.MULTILINE)
    return {part.splitlines()[0].strip(): part for part in parts[1:]}


# The terminal text on the website --------------------------------------------------------

def test_the_screen_shows_what_was_found_then_asks_to_open_the_page(tmp_path, monkeypatch, capsys, utc):
    screen = start_screen(tmp_path, monkeypatch, capsys)
    assert screen[0] == f"Looking in {SHOWN_PROJECT} ..."
    assert "judgekeeper found your LLM-as-a-judge:" in screen
    assert "  Results file    results.json (saved 3 Oct 2026, 14:12)" in screen
    assert screen[-1] == "Open it now? [Y/n]"


@pytest.mark.parametrize("page", ["start.html"])
def test_the_start_output_on_the_site_is_real(tmp_path, monkeypatch, capsys, utc, page):
    shown = _output(page, "start")
    assert shown, f"{page} shows what judgekeeper start prints"
    screen = start_screen(tmp_path, monkeypatch, capsys)
    for block in shown:
        assert block == screen


@pytest.mark.parametrize("page", ["index.html", "start.html"])
def test_the_version_line_on_the_site_is_real(monkeypatch, page):
    class Terminal(io.StringIO):
        encoding = "utf-8"

        def isatty(self):
            return True

    monkeypatch.setattr(sys, "platform", "darwin")
    # Installed inside a project, as the page shows: a virtual environment is active.
    monkeypatch.setenv("VIRTUAL_ENV", "/Users/me/support-bot/.venv")
    monkeypatch.setattr("shutil.which", lambda name: "/usr/local/bin/judgekeeper")
    (shown,) = _output(page, "version")
    assert shown == version_lines(Terminal())
    assert shown[0] == f"✓ judgekeeper {__version__} is ready"


# The home page and the Guide ---------------------------------------------------------------

def test_the_home_page_has_no_demo_but_its_hero_and_sends_people_to_the_guide():
    text = (WEBSITE / "index.html").read_text(encoding="utf-8")
    for gone in ("See it work", "try-question", "screenshot"):
        assert gone not in text.lower(), gone
    hero = text[text.index('<section class="hero">'):text.index("</section>")]
    assert "demo" not in text.replace(hero, "").lower()  # one small card with sample answers
    hrefs = [a.attrs.get("href") for a in _els("index.html") if a.tag == "a"]
    assert hrefs.count("start.html") >= 2  # the hero's button and the footer


def test_the_tabs_choose_windows_first_on_windows():
    script = (WEBSITE / "assets" / "site.js").read_text(encoding="utf-8")
    assert re.search(r"navigator\.(userAgentData|platform|userAgent)", script)
    assert "Win" in script and 'aria-controls") === "panel-win"' in script


def test_the_guide_is_six_steps_then_the_details():
    main_el = next(el for el in _els("start.html") if el.tag == "main")
    steps = [el.attrs.get("id") for el in main_el.children
             if isinstance(el, Element) and el.tag == "section" and "stop" in el.classes()]
    assert steps == ["install", "connect", "start", "label", "result", "improve"]
    details = _by_id("start.html", "details")
    assert details.parent.tag == "main"
    ids = [el.attrs.get("id") for el in details.children
           if isinstance(el, Element) and el.tag == "section"]
    assert ids == ["reads", "never", "review", "fix", "ask-again", "new-judge", "again", "commands",
                   "own-format"]
    assert _codes(_by_id("start.html", "start")) == ["judgekeeper start"]
    reads = _flat(_by_id("start.html", "reads"))
    for tool in ("promptfoo", "DeepEval", "Inspect AI", "MLflow", "input", "output", "verdict"):
        assert tool in reads, tool
    never = _flat(_by_id("start.html", "never"))
    for needed in ("No AI calls unless you say yes",
                   "your own judge runs through your own tool",
                   "never sees your key, it only checks its name", "never runs your app",
                   ".env", "promptfoo export"):
        assert needed in never, needed
    for section, needed in (("review", ("--review", "judge-mistakes.csv", "Not sure",
                                        "first marks stay the main result")),
                            ("fix", ("--fix", "kept aside", "never edits your files",
                                     "where the new rule goes", "can't rewrite a rule well")),
                            ("ask-again", ("--ask-again", "Go ahead? [y/N]", "by name only",
                                           "--judge-command", "Your app is not run")),
                            ("new-judge", ("--try-new-judge", "10 Pass and 10 Fail",
                                           "look better on them", "--new",
                                           "never your new outputs"))):
        flat = _flat(_by_id("start.html", section))
        for words in needed:
            assert words in flat, (section, words)
    again = _flat(_by_id("start.html", "again"))
    for needed in ("Continue?", "Mark more answers", "ask your judge again", "re-check",
                   "Your judge changed", "--new", "previous-"):
        assert needed in again, needed


# README, guide, skill --------------------------------------------------------------------

def test_the_readme_makes_uvx_the_main_path():
    use = _sections(README)["Use it on your own judge"]
    assert f"\ncd your-project\nuvx judgekeeper@{__version__}\n" in use
    for tool in ("promptfoo", "DeepEval", "Inspect AI", "MLflow"):
        assert tool in use, tool
    assert len(README.read_text(encoding="utf-8").splitlines()) <= 80


# The version -----------------------------------------------------------------------------

def test_the_version_is_1_0_0b1_everywhere():
    main_toml = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert __version__ == main_toml["project"]["version"] == "1.0.0b2"


# Results in your own format, and after the first result ----------------------------------

def test_the_own_format_section_shows_the_table_and_the_agent_prompt():
    from judgekeeper.own_format import AGENT_PROMPT

    section = _by_id("start.html", "own-format")
    flat = _flat(section)
    for needed in ("id", "input", "output", "verdict", "reason",
                   "judge_model", "one CSV per judge or criterion", "the first 3 rows",
                   "judgekeeper start --agent-prompt"):
        assert needed in flat, needed
    (prompt,) = [el for el in section.iter() if el.attrs.get("id") == "agent-prompt"]
    assert prompt.tag == "code" and prompt.parent.tag == "pre"
    assert "code" in prompt.parent.parent.classes()  # so it gets a copy button
    assert prompt.text() == AGENT_PROMPT
    assert "#own-format" in [a.attrs.get("href") for a in _by_id("start.html", "reads").iter()
                             if a.tag == "a"]


def test_the_reference_explains_the_own_format():
    reference = " ".join(REFERENCE.read_text(encoding="utf-8").split())
    for needed in ("judge_model", "first 3 rows", "judgekeeper.toml"):
        assert needed in reference, needed
    assert "calling a metric's `measure()` directly saves nothing" in reference


def test_the_own_format_section_shows_the_three_doors_in_order():
    section = _by_id("start.html", "own-format")
    heads = [el.attrs.get("id") for el in section.iter() if el.tag == "h4"]
    assert heads == ["door-setup", "door-record", "door-agent", "records-format"]
    flat = _flat(section)
    for needed in ("judgekeeper setup", "asks once before it changes any file",
                   "It never edits your code", "judgekeeper.record(",
                   "JUDGEKEEPER_RECORD=0"):
        assert needed in flat, needed
    hrefs = [a.attrs.get("href") for a in section.iter() if a.tag == "a"]
    assert "reference.html#records-format" in hrefs
    assert "reference.html#record-save-your-own-judges-verdicts-with-one-line" in hrefs
    assert "https://github.com/judgekeeper/judgekeeper/blob/main/docs/records.schema.json" in \
        hrefs


def test_see_your_result_shows_once_there_are_enough_marks():
    """The page shows the button only once there are enough marks of each kind."""
    step = _flat(_by_id("start.html", "result"))
    reference = " ".join(REFERENCE.read_text(encoding="utf-8").split())
    for text in (step, reference):
        assert "See your result" in text
        assert "any time" not in text.split("See your result", 1)[1][:80]
    assert "once you have marked enough answers of each kind" in step
    assert "appears once there are enough marks of each kind" in reference
