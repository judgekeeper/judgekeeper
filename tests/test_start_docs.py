"""`judgekeeper start` in the docs and on the website: the home page's install steps and the
terminal text it shows, the "Use it on your app" page, the reference, the README, the guide,
the skill, and the version.

The terminal text on the website is real: `start_screen` runs `judgekeeper start` on a test
project (212 promptfoo answers, the judge passed 171 and failed 41) in a folder named
support-bot, answering no to the last question. Two things are fixed so the text is the same
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
from judgekeeper.cli import _parser, main, version_lines
from tests.start_projects import promptfoo_project, split
from tests.website_pages import ROOT, WEBSITE, Element, commands, parse

README = ROOT / "README.md"
GUIDE = ROOT / "docs" / "guide.md"
REFERENCE = ROOT / "docs" / "reference.md"
SKILL = ROOT / "skills" / "judgekeeper" / "SKILL.md"
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
    return [line.rstrip() for line in out.strip("\n").splitlines()]


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
    assert "✓ Your eval tool: promptfoo (results.json, saved 2026-10-03 14:12)" in screen
    assert screen[-1] == "Open the labeling page now? [Y/n]"


@pytest.mark.parametrize("page", ["index.html", "start.html"])
def test_the_start_output_on_the_site_is_real(tmp_path, monkeypatch, capsys, utc, page):
    shown = _output(page, "start")
    assert shown, f"{page} shows what judgekeeper start prints"
    screen = start_screen(tmp_path, monkeypatch, capsys)
    for block in shown:
        assert block == screen


def test_the_version_line_on_the_home_page_is_real(monkeypatch):
    class Terminal(io.StringIO):
        encoding = "utf-8"

        def isatty(self):
            return True

    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr("shutil.which", lambda name: "/usr/local/bin/judgekeeper")
    (shown,) = _output("index.html", "version")
    assert shown == version_lines(Terminal())
    assert shown[0] == f"✓ judgekeeper {__version__} is ready"


# The home page ---------------------------------------------------------------------------

HOME_INSTALL = {
    "mac": ["python3 --version",
            "python3 -m pip install -U judgekeeper && python3 -m judgekeeper --version"],
    "win": ["py --version", "py -m pip install -U judgekeeper", "py -m judgekeeper --version"],
}


def test_the_home_page_is_what_it_is_then_install_then_run_it():
    main_el = next(el for el in _els("index.html") if el.tag == "main")
    ids = [el.attrs.get("id") for el in main_el.children
           if isinstance(el, Element) and el.tag == "section"]
    assert ids == [None, "idea", "install", "run"]
    text = (WEBSITE / "index.html").read_text(encoding="utf-8")
    for gone in ("demo", "See it work", "try-question", "screenshot"):
        assert gone not in text.lower(), gone


def test_the_home_page_install_has_two_tabs_and_the_python_check():
    tabs = [el.text() for el in _by_id("index.html", "install-tabs").iter()
            if el.attrs.get("role") == "tab"]
    assert tabs == ["Mac", "Windows"]
    for key, wanted in HOME_INSTALL.items():
        panel = _by_id("index.html", f"panel-{key}")
        assert panel.attrs.get("role") == "tabpanel"
        assert "hidden" not in panel.attrs  # without JavaScript both are shown
        assert _codes(panel) == wanted, key
        flat = _flat(panel)
        assert "You need 3.11 or newer. No Python, or older? Install it from python.org, then " \
               "come back." in flat
        assert "https://www.python.org/downloads/" in [a.attrs.get("href") for a in panel.iter()
                                                       if a.tag == "a"]
    mac = _flat(_by_id("index.html", "panel-mac"))
    assert "externally-managed-environment" in mac
    assert "python3 -m venv .venv && source .venv/bin/activate" in mac


def test_the_home_page_run_it_step():
    run = _by_id("index.html", "run")
    assert _codes(run) == ["cd your-project\njudgekeeper start"]
    assert [argv for _, argv in commands(WEBSITE / "index.html")] == [["start"]]
    assert "start.html" in [a.attrs.get("href") for a in run.iter() if a.tag == "a"]


def test_the_tabs_choose_windows_first_on_windows():
    script = (WEBSITE / "assets" / "site.js").read_text(encoding="utf-8")
    assert re.search(r"navigator\.(userAgentData|platform|userAgent)", script)
    assert "Win" in script and 'aria-controls") === "panel-win"' in script


# Use it on your app ----------------------------------------------------------------------

def test_use_it_on_your_app_is_about_start_with_the_older_paths_at_the_end():
    main_el = next(el for el in _els("start.html") if el.tag == "main")
    ids = [el.attrs.get("id") for el in main_el.children
           if isinstance(el, Element) and el.tag == "section"]
    assert ids == ["start", "reads", "never", "page", "result", "again", "install", "other",
                   "more"]
    reads = _flat(_by_id("start.html", "reads"))
    for tool in ("promptfoo", "DeepEval", "Inspect AI", "MLflow", "input", "output", "verdict"):
        assert tool in reads, tool
    never = _flat(_by_id("start.html", "never"))
    for needed in ("No AI calls", "no API key", "never runs your app", ".env",
                   "promptfoo export"):
        assert needed in never, needed
    again = _flat(_by_id("start.html", "again"))
    for needed in ("Continue?", "Label more", "re-check", "--new", "previous-"):
        assert needed in again, needed
    other = _by_id("start.html", "other")
    assert [h.attrs.get("id") for h in other.iter() if h.tag == "h3"][:4] == [
        "step-collect", "step-label", "step-judge", "step-read"]


# The reference ---------------------------------------------------------------------------

def _start_parser():
    (sub,) = [a for a in _parser()._actions if a.dest == "command"]
    return sub.choices["start"]


def test_the_reference_has_every_start_flag_and_the_saved_files():
    section = _sections(REFERENCE)["start: find your results, label, see the result"]
    flags = [s for a in _start_parser()._actions for s in a.option_strings
             if s.startswith("--") and s != "--help" and a.help != "==SUPPRESS=="]
    assert set(flags) >= {"--tool", "--metric", "--experiment", "--pass-if", "--label-map",
                          "--judge-model", "--yes", "--new", "--no-browser", "--port"}
    for flag in [*flags, "PATH"]:
        assert f"`{flag}" in section, flag
    for name in ("start.json", "pool-judge.jsonl", "pool.jsonl", "labels.csv", "anchors.jsonl",
                 "result.json", "result.html", "history/", "previous-"):
        assert name in section, name
    text = REFERENCE.read_text(encoding="utf-8")
    assert text.index("## start:") < text.index("## init:")


# README, guide, skill --------------------------------------------------------------------

def test_the_readme_makes_start_the_main_path():
    use = _sections(README)["Use it on your own judge"]
    assert "\ncd your-project\njudgekeeper start\n" in use
    assert "\njudgekeeper check results.csv --judge verdict --human label\n" in use
    assert use.index("judgekeeper start") < use.index("judgekeeper check")
    for tool in ("promptfoo", "DeepEval", "Inspect AI", "MLflow"):
        assert tool in use, tool
    assert len(README.read_text(encoding="utf-8").splitlines()) <= 60


def test_the_guide_starts_with_start():
    sections = _sections(GUIDE)
    assert next(iter(sections)) == "Start here"
    assert "judgekeeper start" in sections["Start here"]


def test_the_skill_leaves_labeling_to_the_person():
    text = " ".join(SKILL.read_text(encoding="utf-8").split())
    assert "judgekeeper start --yes --no-browser" in text
    assert "labeling needs the person" in text.lower()
    assert len(SKILL.read_text(encoding="utf-8").splitlines()) < 150


# The version -----------------------------------------------------------------------------

def test_the_version_is_0_2_0_everywhere():
    main_toml = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    plugin = tomllib.loads((ROOT / "packages" / "pytest-judgekeeper" / "pyproject.toml")
                           .read_text(encoding="utf-8"))
    assert __version__ == main_toml["project"]["version"] == plugin["project"]["version"] == \
        "0.2.0"


def test_the_changelog_says_what_0_2_0_adds_and_what_it_does_not_do():
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    entry = " ".join(text[text.index("## 0.2.0"):text.index("## 0.1.3")].split())
    assert "## 0.2.0 (unreleased)" in entry and "## 0.1.4" not in text
    unchanged = "No change to any other command, flag, metric or report field"
    for needed in ("`judgekeeper start`", "`judgekeeper --version`", "no AI calls",
                   "no API key", "never runs your", unchanged, "Removed: `judgekeeper demo`"):
        assert needed in entry, needed
