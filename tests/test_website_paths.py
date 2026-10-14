"""The website's paths: the navigation, the short home page, the Guide (start.html) and
llms.txt.

tests/test_website.py already checks, for every page, that commands parse, links resolve and
nothing loads from another site; tests/test_website_look.py checks the frame, the theme and the
Guide's steps. This file checks that every page carries the same navigation; the home page is
short; the install is inside the project; the output blocks are what the commands print; and
the links in llms.txt point at real files.
"""

from __future__ import annotations

import importlib.util
import re
import tomllib
from pathlib import Path

import pytest

from tests.website_pages import (
    NAV,
    ROOT,
    WEBSITE,
    Element,
    commands,
    pages,
    parse,
)

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
    for page in ("setup.html", "learn.html"):
        assert any(h.startswith("start.html") for h in _hrefs(_main(page))), page


# Plain words

@pytest.mark.parametrize("page", ["index.html"])
def test_no_jargon_outside_quoted_output(page):
    """TPR, TNR and kappa appear on these pages only inside a <pre>: what a program printed. The one exception is kappa in the home page's
    real check, which says what kappa is in the same paragraph."""
    main = _main(page)
    check = [el for el in main.iter() if el.attrs.get("id") == "check"]
    for section in check:
        section.parent.children.remove(section)
    assert not JARGON.search(_text_outside(main, {"pre"})), page
    for section in check:
        text = " ".join(_text_outside(section, set()).split())
        assert re.findall(r"\b(TPR|TNR)\b", text) == []
        assert "Kappa is how well it agrees with people once lucky guesses are taken away; " \
            "1 is perfect." in text


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
    """What judgekeeper is, the six steps, install, what you get. No examples, and the only
    demo is the small labeling card in the hero, with sample answers."""
    assert [argv for _, argv in commands(WEBSITE / "index.html")] == [["--version"],
                                                                     ["--version"]]
    assert "start.html#install" in _hrefs(_by_id("index.html", "install"))
    text = (WEBSITE / "index.html").read_text(encoding="utf-8")
    for gone in ("examples.html", "See it work", "try-question", "Skip the"):
        assert gone not in text, gone
    hero = text[text.index('<section class="hero">'):text.index("</section>")]
    assert "demo" not in text.replace(hero, "")


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
OUTSIDE = ("pip3 install judgekeeper", "judgekeeper-env", "uv tool install",
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
    for message in (REFUSED, NO_PIP, NO_PIP_WINDOWS, "It is not about judgekeeper"):
        assert whole.count(message) == 1, message
    refused = next(v for k, v in help_box.items() if REFUSED in k)
    assert "not switched on" in refused
    assert "https://www.python.org/downloads/" in _hrefs(step)


def test_making_the_environment_is_shown_outside_the_fold_and_linux_has_its_own_help():
    step = _by_id("start.html", "install")
    shown = " ".join(_flat(el) for el in step.iter() if el.tag == "p"
                     and not any(a.tag == "details" for a in el.ancestors()))
    for needed in (*CHECK.values(), *MAKE_VENV.values(), "No .venv yet?"):
        assert needed in shown, needed
    whole = " ".join(f"{k} {v}" for k, v in _help("install").items())
    assert "On Linux, get Python 3.11 or newer from your package manager" in whole
    assert "ensurepip is not available" in whole and "python3.12-venv" in whole
    guide = " ".join(GUIDE.read_text(encoding="utf-8").split())
    for needed in ("on Linux, get Python 3.11 or newer from your package manager",
                   "ensurepip is not available", "python3.12-venv"):
        assert needed in guide, needed


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
    return [*pages(), *docs, ROOT / "README.md", WEBSITE / "llms.txt"]


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


def test_the_guide_shows_the_install():
    text = GUIDE.read_text(encoding="utf-8")
    section = text[text.index("### Install\n"):text.index("See a real report without installing")]
    for line in (*CHECK.values(), *MAKE_VENV.values(), "pip install judgekeeper", *DEV_TOOLS,
                 "judgekeeper --version", MODULE_FORM, PY_PIP):
        assert f"`{line}`" in section, line
    for key in ("mac", "win"):
        assert f"```\n{ACTIVATE[key]}\n```" in section, key
    for needed in (f"`{REFUSED}`", f"`{NO_PIP}`", f"`{NO_PIP_WINDOWS}`", "`python --version`",
                   "https://www.python.org/downloads/", "like pytest", "never on your computer",
                   "It is not about judgekeeper", "(.venv)", "Scripts\\activate.bat"):
        assert needed in section, needed


OLD_PYTHON = ("Could not find a version that satisfies the requirement judgekeeper "
              "(from versions: none)")  # what pip says when the environment's Python is older
REMAKE = "python3.12 -m venv .venv"
UV_OLDER_PYTHONS = "uv add --dev \"judgekeeper; python_version >= '3.11'\""
UV_RUN = "uv run judgekeeper start"


def _install_texts() -> dict[str, str]:
    """The Guide's install step (start.html) and guide.md's."""
    guide = GUIDE.read_text(encoding="utf-8")
    return {"start.html": _flat(_by_id("start.html", "install")),
            "guide.md": guide[guide.rindex("\n## ", 0, guide.index("### Install\n")):guide.index(
                "See a real report without installing")]}


def test_the_python_version_is_next_to_the_first_install_command():
    for name, text in _install_texts().items():
        flat = " ".join(text.split())
        assert "Python 3.11 or newer" in flat, name
        first = flat.index("pip install judgekeeper")
        assert flat.index("Python 3.11 or newer") < first + 400, name


def test_didnt_work_explains_an_older_python_and_a_project_that_allows_one():
    help_box = _help("install")
    (older,) = [v for k, v in help_box.items() if OLD_PYTHON in k]
    assert "needs Python 3.11 or newer" in older and "delete" in older and REMAKE in older
    (dev,) = [v for k, v in help_box.items() if "uv or Poetry" in k]
    assert UV_OLDER_PYTHONS in dev and UV_RUN in dev
    guide = " ".join(GUIDE.read_text(encoding="utf-8").split())
    for needed in (OLD_PYTHON, "needs Python 3.11 or newer", REMAKE, UV_OLDER_PYTHONS, UV_RUN):
        assert needed in guide, needed


def test_the_uv_line_shows_how_to_run_it():
    for name, text in _install_texts().items():
        assert UV_RUN in " ".join(text.split()), name


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


def test_llms_txt_lists_the_pages_and_every_link_resolves():
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


def test_the_sitemap_lists_the_main_pages():
    locs = set(re.findall(r"<loc>(.*?)</loc>", (WEBSITE / "sitemap.xml").read_text(
        encoding="utf-8")))
    for page in ("start.html", "setup.html"):
        assert f"https://www.judgekeeper.com/{page}" in locs, page


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


# The Docs page: one list of every page, and the places on GitHub the site does not show

def test_the_docs_page_links_every_page_and_the_places_on_github():
    hrefs = _hrefs(_main("docs.html"))
    for page in pages():
        if page.name not in {"docs.html", "index.html"}:
            assert page.name in hrefs, page.name
    blob = "https://github.com/judgekeeper/judgekeeper/blob/main/"
    for tool in ("promptfoo", "deepeval", "inspect", "mlflow"):
        assert f"{blob}docs/integrations/{tool}.md" in hrefs, tool
        assert (ROOT / "docs" / "integrations" / f"{tool}.md").is_file(), tool
    for needed in (f"{blob}CHANGELOG.md", f"{blob}SECURITY.md",
                   "https://pypi.org/project/judgekeeper/",
                   "https://github.com/judgekeeper/judgekeeper/issues/new/choose",
                   "https://github.com/judgekeeper/judgekeeper/security/advisories/new"):
        assert needed in hrefs, needed
    for path in ("CHANGELOG.md", "SECURITY.md"):
        assert (ROOT / path).is_file(), path


def test_the_docs_page_names_the_version_of_the_package():
    version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"][
        "version"]
    assert f"These docs are for judgekeeper {version}." in _flat(_main("docs.html"))
