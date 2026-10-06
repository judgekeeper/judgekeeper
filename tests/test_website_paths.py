"""The website's paths: the navigation, the short home page, the Guide (start.html), "With a
coding assistant" (assistant.html) and llms.txt.

tests/test_website.py already checks, for every page, that commands parse, links resolve and
nothing loads from another site; tests/test_website_look.py checks the frame, the theme and the
Guide's steps. This file checks that every page carries the same navigation; the home page is
short; the install is inside the project; the output blocks are what the commands print; the
assistant page shows the prompt exactly; and the links in llms.txt point at real files.
"""

from __future__ import annotations

import html
import importlib.util
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from judgekeeper.cli import _parser, main
from tests.website_pages import (
    NAV,
    ROOT,
    WEBSITE,
    Element,
    as_shown,
    commands,
    pages,
    parse,
)

PROMPT = ROOT / "docs" / "assistant-prompt.md"
HOME_MAX_LINES = 211
JARGON = re.compile(r"\b(TPR|TNR|kappa)\b", flags=re.IGNORECASE)
FIGURE = re.compile(r"\d+\.\d+|\d+\s?%")


def _els(page: str | Path) -> list[Element]:
    return list(parse(WEBSITE / page if isinstance(page, str) else page).iter())


def _main(page: str) -> Element:
    return next(el for el in _els(page) if el.tag == "main")


def _by_id(page: str, wanted: str) -> Element:
    return next(el for el in _els(page) if el.attrs.get("id") == wanted)


def _hrefs(el: Element) -> list[str]:
    return [a.attrs.get("href", "") for a in el.iter() if a.tag == "a"]


def _text_outside(el: Element, skip: set[str]) -> str:
    """The text of an element, leaving out everything inside the tags in `skip`."""
    return "".join(c if isinstance(c, str) else "" if c.tag in skip else _text_outside(c, skip)
                   for c in el.children)


def _output(page: str, name: str) -> list[str]:
    (block,) = [el for el in _els(page) if el.attrs.get("data-output") == name]
    assert block.tag == "pre" and "output" in block.classes()
    return [line.rstrip() for line in block.text().strip("\n").splitlines()]


def _load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Navigation

def test_every_page_carries_the_same_navigation():
    for page in pages():
        (nav,) = [el for el in parse(page).iter()
                  if el.tag == "nav" and "site-nav" in el.classes()]
        links = [a for a in nav.iter() if a.tag == "a"]
        assert [(a.attrs["href"], a.text().strip()) for a in links] == NAV, page.name
        current = [a.attrs["href"] for a in links if a.attrs.get("aria-current") == "page"]
        assert current == [page.name] * any(page.name == href for href, _ in NAV), page.name


def test_every_page_in_the_navigation_exists():
    for href, _ in NAV[:-1]:
        assert (WEBSITE / href).is_file(), href
    assert NAV[-1][0].startswith("https://github.com/")


def test_the_frame_script_and_the_tests_agree_on_the_navigation():
    assert _load_script("site_frame").NAV == NAV


def test_the_older_pages_link_back_to_the_guide():
    assert "learn.html" not in [href for href, _ in NAV]
    for page in ("setup.html", "tutorial.html", "learn.html", "own-metric.html",
                 "assistant.html"):
        assert any(h.startswith("start.html") for h in _hrefs(_main(page))), page


# Plain words

@pytest.mark.parametrize("page", ["index.html", "assistant.html"])
def test_no_jargon_outside_quoted_output(page):
    """TPR, TNR and kappa appear on these pages only inside a <pre>: what a program printed,
    or the prompt, which is shown word for word."""
    assert not JARGON.search(_text_outside(_main(page), {"pre"})), page


def test_the_guide_explains_each_term_in_one_line_where_the_result_is():
    step = _by_id("start.html", "result")
    lines = {li.text().split(":")[0].strip().lower(): li.text() for li in step.iter()
             if li.tag == "li" and ":" in li.text()}
    for term in ("tpr", "tnr", "kappa"):
        assert term in lines, term
        assert len(lines[term].split(". ")) <= 2 and len(lines[term]) < 140, lines[term]
    main_text = _text_outside(_main("start.html"), {"pre"})
    first = JARGON.search(main_text).start()
    assert main_text.index("Your result") < first < main_text.index("Improve your judge")


# Home

def test_the_home_page_stays_short():
    lines = (WEBSITE / "index.html").read_text(encoding="utf-8").splitlines()
    assert len(lines) <= HOME_MAX_LINES, len(lines)


def test_the_home_page_shows_only_the_install_and_sends_the_rest_to_the_guide():
    """What judgekeeper is, the six steps, install, what you get. No demo and no examples."""
    assert [argv for _, argv in commands(WEBSITE / "index.html")] == [["--version"],
                                                                     ["--version"]]
    assert "start.html#install" in _hrefs(_by_id("index.html", "install"))
    text = (WEBSITE / "index.html").read_text(encoding="utf-8")
    for gone in ("demo", "examples.html", "See it work", "try-question", "Skip the"):
        assert gone not in text, gone


# Install: inside the project, in the project's own environment

ACTIVATE = {"mac": "cd your-project\nsource .venv/bin/activate",
            "win": "cd your-project\n.venv\\Scripts\\activate"}
MAKE_VENV = {"mac": "python3 -m venv .venv", "win": "py -m venv .venv"}
CHECK = {"mac": "python3 --version", "win": "py --version"}
DEV_TOOLS = ["uv add --dev judgekeeper", "poetry add --group dev judgekeeper"]
MODULE_FORM = "python -m judgekeeper --version"
REFUSED = "error: externally-managed-environment"
NO_PIP = "pip: command not found"
NO_PIP_WINDOWS = "'pip' is not recognized as an internal or external command"
PY_PIP = ".venv\\Scripts\\python -m pip install judgekeeper"  # the project's own Python
GUIDE = ROOT / "docs" / "guide.md"
# An install that is not inside a project: the system Python, a shared environment in the
# home folder, or a tool that installs for the whole computer.
OUTSIDE = ("pip3 install judgekeeper", "judgekeeper-env", "uvx judgekeeper", "uv tool install",
           "pipx", "python3 -m pip install -U judgekeeper", "pip install -U judgekeeper",
           "pip install --user", "py -m pip install judgekeeper")


def _panel_commands(page: str, key: str) -> list[str]:
    panel = _by_id(page, f"panel-{key}")
    assert panel.attrs.get("role") == "tabpanel"
    assert "hidden" not in panel.attrs  # without JavaScript both are shown
    return [el.text() for el in panel.iter() if el.tag == "code" and el.parent.tag == "pre"]


def _tab_labels(page: str, box: str = "install-tabs") -> list[str]:
    return [el.text() for el in _by_id(page, box).iter() if el.attrs.get("role") == "tab"]


def _flat(el: Element) -> str:
    return " ".join(el.text().split())


INSTALL = {"mac": "source .venv/bin/activate\npip install judgekeeper\njudgekeeper --version",
           "win": ".venv\\Scripts\\activate\npip install judgekeeper\njudgekeeper --version"}


def _help(step: str) -> dict[str, str]:
    """A step's "Didn't work?" box: what you see -> what to do."""
    (box,) = [d for d in _by_id("start.html", step).iter()
              if d.tag == "details" and "help" in d.classes()]
    terms = [el for el in box.iter() if el.tag in {"dt", "dd"}]
    return {_flat(dt): _flat(dd) for dt, dd in zip(terms[::2], terms[1::2], strict=True)}


def test_the_guide_installs_inside_the_project():
    step = _by_id("start.html", "install")
    assert _tab_labels("start.html") == ["Mac and Linux", "Windows"]
    flat = _flat(step)
    assert "like pytest" in flat and "inside your project" in flat
    assert "not on your computer as a whole" in flat
    for key in ("mac", "win"):
        assert _panel_commands("start.html", key) == [INSTALL[key]], key
    help_box = _help("install")
    whole = " ".join(f"{k} {v}" for k, v in help_box.items())
    for needed in (*CHECK.values(), "python --version", *MAKE_VENV.values(), *DEV_TOOLS,
                   "The term 'pip' is not recognized", PY_PIP, MODULE_FORM, "uv run",
                   "poetry run", "Scripts\\activate.bat", "(.venv)", "Homebrew", "pip3",
                   "Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser",
                   "a higher number"):
        assert needed in whole, needed
    # Each message a beginner can hit is explained once, under its own heading.
    for message in (REFUSED, NO_PIP, NO_PIP_WINDOWS, "installed outside a project",
                    "It is not about judgekeeper"):
        assert whole.count(message) == 1, message
    refused = next(v for k, v in help_box.items() if REFUSED in k)
    assert "not switched on" in refused
    assert "https://www.python.org/downloads/" in _hrefs(step)


def test_the_home_page_install_has_two_tabs_and_the_python_line():
    assert _tab_labels("index.html") == ["Mac and Linux", "Windows"]
    for key in ("mac", "win"):
        activate = ACTIVATE[key]
        assert _panel_commands("index.html", key) == [
            f"{activate}\npip install judgekeeper\njudgekeeper --version"], key
    section = _by_id("index.html", "install")
    flat = _flat(section)
    assert "You need Python 3.11 or newer." in flat
    assert "project's own Python environment" in flat and "never onto the whole computer" in flat
    assert "https://www.python.org/downloads/" in _hrefs(section)
    for needed in DEV_TOOLS:
        assert needed in flat, needed


def test_a_link_can_open_the_install_on_either_tab():
    script = (WEBSITE / "assets" / "site.js").read_text(encoding="utf-8")
    assert '"#install-mac": "panel-mac"' in script and '"#install-win": "panel-win"' in script
    assert "scrollIntoView" in script


def _install_sources() -> list:
    docs = sorted((ROOT / "docs").rglob("*.md"))
    return [*pages(), *docs, ROOT / "README.md", ROOT / "skills" / "judgekeeper" / "SKILL.md",
            ROOT / "packages" / "pytest-judgekeeper" / "README.md", WEBSITE / "llms.txt"]


def test_nothing_shows_an_install_outside_a_project():
    for source in _install_sources():
        text = source.read_text(encoding="utf-8")
        for gone in OUTSIDE:
            assert gone not in text, (source.relative_to(ROOT).as_posix(), gone)


def test_the_site_names_no_installer_it_does_not_use_and_no_unsafe_flag():
    sources = [*pages(), GUIDE, ROOT / "README.md"]
    for source in sources:
        text = source.read_text(encoding="utf-8")
        for gone in ("astral.sh/uv/install", "uv tool install", "brew install uv", "winget",
                     "break-system-packages"):
            assert gone not in text, (source.name, gone)


def test_the_python_version_on_the_site_is_the_one_the_package_needs():
    import tomllib

    needs = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"][
        "requires-python"]
    assert needs == ">=3.11"
    assert "Python 3.11 or newer" in _flat(_main("start.html"))
    assert "You need Python 3.11 or newer." in _flat(_main("index.html"))
    assert "`Python 3.11` or a higher number" in GUIDE.read_text(encoding="utf-8")


def test_the_guide_and_the_readme_show_the_same_install():
    text = GUIDE.read_text(encoding="utf-8")
    section = text[text.index("### Install\n"):text.index("See a real report without installing")]
    for line in (*CHECK.values(), *MAKE_VENV.values(), "pip install judgekeeper", *DEV_TOOLS,
                 "judgekeeper --version", MODULE_FORM, PY_PIP):
        assert f"`{line}`" in section, line
    for key in ("mac", "win"):
        assert f"```\n{ACTIVATE[key]}\n```" in section, key
    for needed in (f"`{REFUSED}`", f"`{NO_PIP}`", f"`{NO_PIP_WINDOWS}`", "`python --version`",
                   "https://www.python.org/downloads/", "like pytest", "never on your computer",
                   "It is not about judgekeeper", "(.venv)", "installed outside a project",
                   "Scripts\\activate.bat"):
        assert needed in section, needed
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    install = readme[readme.index("## Install"):readme.index("## Use it")]
    assert "\nsource .venv/bin/activate\npip install judgekeeper\njudgekeeper --version\n" in install
    for needed in ("in your project folder", "like pytest", ".venv\\Scripts\\activate",
                   "python3 -m venv .venv", *DEV_TOOLS):
        assert needed in install, needed
    assert "](https://www.judgekeeper.com/start.html#install)" in readme


# Use it on your app

def test_use_it_on_your_app_has_four_steps_each_with_something_to_run_or_make():
    (steps,) = [el for el in _by_id("start.html", "other").iter()
                if el.tag == "ol" and "steps" in el.classes()]
    items = [li for li in steps.children if isinstance(li, Element)]
    heads = [next(h for h in li.iter() if h.tag == "h4").text() for li in items]
    assert len(heads) == 4
    for head, needle in zip(heads, ("Collect", "Label", "judge", "Read"), strict=True):
        assert needle in head, head
    for li in items:
        shown = [el for el in li.iter() if el.tag == "pre"]
        assert shown, li.text()[:60]
        assert "What you see" in li.text() or "What the file looks like" in li.text()
    used = {argv[0] for _, argv in commands(WEBSITE / "start.html") if argv}
    assert {"label", "check", "judge", "validate", "import-labels"} <= used
    step_commands = [el.text() for el in steps.iter() if el.tag == "code"
                     and el.parent.tag == "pre" and "output" not in el.parent.classes()]
    assert step_commands[:2] == ["judgekeeper label items.csv --out labels.csv",
                                 "judgekeeper check results.csv --judge verdict --human label"]


def test_use_it_on_your_app_shows_the_real_file_and_the_real_output(tmp_path, monkeypatch, capsys):
    (sample,) = [el for el in _els("start.html") if el.attrs.get("data-file") == "tutorial/items.csv"]
    real = (WEBSITE / "tutorial" / "items.csv").read_text(encoding="utf-8").splitlines()
    assert sample.text().strip("\n").splitlines() == real[:int(sample.attrs["data-rows"])]
    shutil.copy(WEBSITE / "tutorial" / "results.csv", tmp_path / "results.csv")
    monkeypatch.chdir(tmp_path)
    capsys.readouterr()
    assert main(["check", "results.csv", "--judge", "verdict", "--human", "label"]) == 0
    printed = as_shown(capsys.readouterr().out)
    assert _output("start.html", "check") == printed.strip("\n").splitlines()


# With a coding assistant

def test_the_assistant_page_is_rendered_and_current(tmp_path):
    out = tmp_path / "assistant.html"
    subprocess.run([sys.executable, str(ROOT / "scripts/render_reference.py"),
                    str(ROOT / "docs/assistant.md"), str(out)], check=True, capture_output=True)
    assert out.read_text(encoding="utf-8") == (WEBSITE / "assistant.html").read_text(
        encoding="utf-8"), "run: python scripts/render_reference.py"


def test_the_assistant_page_shows_the_prompt_exactly_in_one_block_with_a_copy_button():
    prompt = PROMPT.read_text(encoding="utf-8").rstrip("\n")
    page = (WEBSITE / "assistant.html").read_text(encoding="utf-8")
    block = f"<pre><code>{html.escape(prompt, quote=False)}</code></pre>"
    assert page.count(block) == 1
    assert f'<div class="code">{block}</div>' in page  # .code is what site.js adds Copy to
    holding = [el for el in _els("assistant.html") if el.tag == "pre" and el.text() == prompt]
    assert len(holding) == 1 and "code" in holding[0].parent.classes()
    scripts = [el.attrs.get("src") for el in _els("assistant.html") if el.tag == "script"]
    assert scripts == ["assets/theme.js", "assets/site.js"]
    js = (WEBSITE / "assets" / "site.js").read_text(encoding="utf-8")
    assert '$all(".code pre")' in js and "navigator.clipboard.writeText" in js


# llms.txt and the sitemap

def _llms_links() -> list[tuple[str, str, str]]:
    text = (WEBSITE / "llms.txt").read_text(encoding="utf-8")
    assert text.startswith("# judgekeeper\n")
    found = []
    for line in text.splitlines():
        links = re.findall(r"\[([^\]]+)\]\(([^)\s]+)\)", line)
        if links:
            assert line.startswith("- ") and len(links) == 1, f"one link per line: {line}"
            found.append((*links[0], line))
    return found


def test_llms_txt_lists_the_pages_and_the_prompt_and_every_link_resolves():
    site, raw = "https://www.judgekeeper.com/", "https://raw.githubusercontent.com/judgekeeper/judgekeeper/main/"
    targets = []
    for _, url, line in _llms_links():
        assert ": " in line.split(")", 1)[1], f"a link and what it is: {line}"
        if url.startswith(site):
            target = WEBSITE / (url[len(site):] or "index.html")
        else:
            assert url.startswith(raw), url
            target = ROOT / url[len(raw):]
        assert target.is_file(), url
        targets.append(target)
    assert len(targets) == len(set(targets))
    for page in pages():
        assert page in targets, page.name
    assert PROMPT in targets


def test_the_sitemap_lists_the_main_pages():
    locs = set(re.findall(r"<loc>(.*?)</loc>", (WEBSITE / "sitemap.xml").read_text(
        encoding="utf-8")))
    for page in ("start.html", "assistant.html", "own-metric.html"):
        assert f"https://www.judgekeeper.com/{page}" in locs, page


# Pre-publication review: what a reader who installed from PyPI can actually run

DOCS = ROOT / "docs"
RUNNER_PAGES = (WEBSITE / "setup.html", WEBSITE / "learn.html", DOCS / "reference.md",
                DOCS / "guide.md")


@pytest.mark.parametrize("path", RUNNER_PAGES, ids=lambda p: p.name)
def test_judge_commands_use_the_rule_file_init_writes_and_show_init_first(path):
    """prompts/pairwise.md is a file of this repository, not of the
    package: someone who ran `pip install judgekeeper` does not have them."""
    text = html.unescape(path.read_text(encoding="utf-8"))
    assert "--prompt prompts/single.md" not in text
    assert "--prompt prompts/pairwise.md" not in text
    first_use = text.index("--prompt prompts/judge.md")
    assert 0 <= text.index("judgekeeper init") < first_use


@pytest.mark.parametrize("path", [WEBSITE / "setup.html", DOCS / "reference.md",
                                  DOCS / "guide.md"], ids=lambda p: p.name)
def test_the_anthropic_extra_is_shown_where_the_runner_is_introduced(path):
    text = html.unescape(path.read_text(encoding="utf-8"))
    install = 'pip install "judgekeeper[anthropic]"'
    assert install in text and 'judgekeeper[openai]' in text
    extras = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"][
        "optional-dependencies"]
    assert {"anthropic", "openai"} <= set(extras)
    # before the first command that uses the runner
    assert text.index(install) < text.index("judgekeeper judge anchors.jsonl --runner anthropic")


def test_the_setup_page_has_the_laptop_steps_for_mac_and_for_windows():
    box = _by_id("setup.html", "key-tabs")
    assert [el.text() for el in box.iter() if el.attrs.get("role") == "tab"] == ["Mac", "Windows"]
    mac, win = _flat(_by_id("setup.html", "panel-key-mac")), _flat(_by_id("setup.html",
                                                                         "panel-key-win"))
    assert "export ANTHROPIC_API_KEY=" in mac and "${ANTHROPIC_API_KEY:+set}" in mac
    # Windows: this window only, saved for the account, and a check that does not print it.
    assert "$Env:ANTHROPIC_API_KEY = " in win
    assert '[Environment]::SetEnvironmentVariable("ANTHROPIC_API_KEY", ' in win
    assert '"User")' in win and "Read-Host" in win
    assert 'if ($Env:ANTHROPIC_API_KEY) { "set" }' in win
    assert "PowerShell" in win and "export ANTHROPIC_API_KEY" not in win
    # Neither tab shows a command that would print the key.
    for panel in (mac, win):
        assert "echo $ANTHROPIC_API_KEY" not in panel and "printenv" not in panel


def test_the_reference_states_the_verdict_rule_as_the_code_applies_it():
    from judgekeeper import report as rules

    text = (DOCS / "reference.md").read_text(encoding="utf-8")
    gate, care, kappa = f"{rules.RATE_GATE:.2f}", f"{rules.RATE_CARE:.2f}", rules.KAPPA_GATE
    assert f"| TPR or TNR below {gate}, or kappa below {kappa} | \"not trustworthy as a gate\" |" in text
    assert (f"| otherwise, TPR or TNR below {care} | \"usable with care\" |") in text
    assert "TPR and TNR between" not in text  # the code takes the lower of the two rates


def test_the_tutorial_is_described_by_what_it_covers_not_as_every_command():
    parser = _parser()
    (sub,) = [a for a in parser._actions if a.dest == "command"]
    shown = {argv[0] for _, argv in commands(WEBSITE / "tutorial.html") if argv}
    missing = set(sub.choices) - shown
    assert missing, "the tutorial now shows every command: this test can go"
    tutorial = (WEBSITE / "tutorial.html").read_text(encoding="utf-8")
    llms = (WEBSITE / "llms.txt").read_text(encoding="utf-8")
    line = next(x for x in llms.splitlines()
                if x.startswith("- [Advanced commands, step by step]"))
    for text in (tutorial[:tutorial.index('<h2 id="setup">')], line):
        assert not re.search(r"every (judgekeeper )?command", text, flags=re.IGNORECASE), text[:80]
    assert "main commands" in line and "main judgekeeper commands" in tutorial
