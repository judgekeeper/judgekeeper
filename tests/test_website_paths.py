"""The website's paths: the menu on every page, llms.txt and the sitemap, the install on the
Guide, and the terminal screens.

tests/test_website.py already checks, for every page, that commands parse, links resolve and
nothing loads from another site; tests/test_website_look.py checks the frame, the look and the
parts of each page; tests/test_website_screens.py checks each screen against what judgekeeper
prints. This file checks that every page carries the same menu; the install is inside the
project; the Home page shows the screens and the Guide none; and the links in llms.txt point
at real files.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

from judgekeeper import __version__
from tests.website_pages import NAV, ROOT, WEBSITE, Element, pages, parse

PAGES = ["index.html", "start.html", "check.html", "privacy.html"]


def _els(page: str | Path) -> list[Element]:
    return list(parse(WEBSITE / page if isinstance(page, str) else page).iter())


def _main(page: str) -> Element:
    return next(el for el in _els(page) if el.tag == "main")


def _by_id(page: str, wanted: str) -> Element:
    return next(el for el in _els(page) if el.attrs.get("id") == wanted)


def _flat(el: Element) -> str:
    return " ".join(el.text().split())


# The menu

def test_every_page_carries_the_same_menu():
    for page in pages():
        (nav,) = [el for el in parse(page).iter()
                  if el.tag == "nav" and "menu-l" in el.classes()]
        links = [a for a in nav.iter() if a.tag == "a"]
        assert [(a.attrs["href"], a.text().strip()) for a in links] == NAV, page.name
        current = [a.attrs["href"] for a in links if a.attrs.get("aria-current") == "page"]
        assert current == [page.name] * any(page.name == href for href, _ in NAV), page.name


def test_the_site_is_these_pages():
    assert sorted(p.relative_to(WEBSITE).as_posix() for p in pages()) == sorted(PAGES)
    for href, _ in NAV:
        assert (WEBSITE / href).is_file(), href


def test_the_guide_keeps_the_places_judgekeeper_links_to():
    """judgekeeper prints judgekeeper.com/start.html#install and #own-format; the redirects
    point at #keys and #own-format (tests/test_website_errors.py)."""
    ids = {el.attrs.get("id") for el in _els("start.html")}
    assert {"install", "keys", "own-format"} <= ids


# Install: inside the project

OUTSIDE = ("pip3 install judgekeeper", "judgekeeper-env", "uv tool install",
           "pipx", "python3 -m pip install -U judgekeeper", "pip install -U judgekeeper",
           "pip install --user", "py -m pip install judgekeeper")


def _install_sources() -> list:
    docs = sorted((ROOT / "docs").rglob("*.md"))
    return [*pages(), *docs, ROOT / "README.md", WEBSITE / "llms.txt"]


def test_nothing_shows_an_install_outside_a_project():
    for source in _install_sources():
        text = source.read_text(encoding="utf-8")
        for gone in OUTSIDE:
            assert gone not in text, (source.relative_to(ROOT).as_posix(), gone)


def test_the_site_names_no_installer_it_does_not_use_and_no_unsafe_flag():
    for source in [*pages(), ROOT / "README.md"]:
        text = source.read_text(encoding="utf-8")
        for gone in ("astral.sh/uv/install", "uv tool install", "brew install uv", "winget",
                     "break-system-packages"):
            assert gone not in text, (source.name, gone)


def test_the_guide_installs_in_the_project_with_the_python_the_package_needs():
    needs = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"][
        "requires-python"]
    assert needs == ">=3.11"
    install = _flat(_by_id("start.html", "install"))
    assert "In your project folder, run uvx judgekeeper" in install
    assert ("No uv? Run pip install judgekeeper, then judgekeeper. Needs Python 3.11 or newer, "
            "on macOS, Linux or Windows.") in install
    hrefs = [a.attrs.get("href") for a in _by_id("start.html", "install").iter() if a.tag == "a"]
    assert hrefs == ["https://docs.astral.sh/uv/"]  # the license is in the footer


# The terminal screens

def _screens() -> dict[str, str]:
    """The screens the Home page's terminal types, by step."""
    return {el.attrs["data-screen"]: el.text().strip("\n") for el in _els("index.html")
            if el.tag == "template"}


@pytest.mark.version_number  # each screen shows the version line
def test_the_home_terminal_has_a_screen_for_each_step_and_the_fix_test():
    screens = _screens()
    assert list(screens) == ["find", "mark", "measure", "fix", "fix_test", "check"]
    for name, text in screens.items():
        lines = text.splitlines()
        command = "judgekeeper fix" if name.startswith("fix") else \
            "judgekeeper check" if name == "check" else "judgekeeper"
        assert lines[:2] == [f"$ {command}", f"judgekeeper {__version__}"], name
        assert lines[-1] and not lines[-1].startswith(" "), name
    # Without JavaScript the terminal shows the first screen.
    assert _by_id("index.html", "t-out").text().strip("\n") == screens["find"]


def test_the_guide_shows_no_screens():
    """Home shows what each step looks like; the Guide says how to do it."""
    assert not [el for el in _els("start.html") if el.tag in {"pre", "template"}
                and {"term-out", "output"} & el.classes()]


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
    site = "https://www.judgekeeper.com/"
    raw = "https://raw.githubusercontent.com/judgekeeper/judgekeeper/main/"
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


def test_the_sitemap_and_llms_txt_list_the_pages_in_the_menus_order():
    site = "https://www.judgekeeper.com/"
    order = [site + ("" if p == "index.html" else p) for p in
             ["index.html", "start.html", "check.html", "privacy.html"]]
    locs = re.findall(r"<loc>(.*?)</loc>", (WEBSITE / "sitemap.xml").read_text(encoding="utf-8"))
    assert [u for u in locs if u in order] == order
    for gone in ("docs.html", "setup.html"):
        assert not [u for u in locs if gone in u], gone
    assert [url for _, url, _ in _llms_links() if url.startswith(site)] == order
