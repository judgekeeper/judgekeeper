"""The static website in website/: commands, numbers, metrics, links, assets, weight.

Conventions the pages follow, so these tests can check every figure:

- `data-report="headline.kappa_mean"` with `data-format`: a number from
  docs/examples/llmbar-haiku/report.json. `slices[Natural].kappa_mean` picks a list entry.
- `data-const="judgekeeper.report:MIN_LABELS"`: a constant from the code.
- `data-exit="gate:PASS"`: an exit code from judgekeeper.gate or judgekeeper.attribute.
- `data-tutorial="lazy:headline.tnr_mean"`: a number from the tutorial run, checked in
  test_website_tutorial.py.
- `data-illustration` on a container: made-up numbers, labelled as such on the page.
Any other decimal or percentage in a hand-written page fails test_no_unsourced_numbers.
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from judgekeeper.cli import _parser
from judgekeeper.metrics import agreement, wilson
from tests.website_pages import (
    GENERATED_PAGES,
    ROOT,
    WEBSITE,
    commands,
    hand_written_pages,
    in_output,
    pages,
    parse,
)

REPORT = json.loads((ROOT / "docs/examples/llmbar-haiku/report.json").read_text(encoding="utf-8"))
SOURCE_ATTRS = ("data-report", "data-const", "data-exit", "data-tutorial")


def test_site_has_its_pages():
    for name in ("index.html", "start.html", "assistant.html", "learn.html",
                 "setup.html", "tutorial.html", "own-metric.html", "reference.html", "llms.txt",
                 "assets/style.css", "assets/site.js", "assets/metrics.js", "assets/logo.svg",
                 "assets/social-preview.png"):
        assert (WEBSITE / name).is_file(), name


def test_the_sitemap_lists_every_page():
    sitemap = (WEBSITE / "sitemap.xml").read_text(encoding="utf-8")
    locs = set(re.findall(r"<loc>(.*?)</loc>", sitemap))
    for page in pages():
        name = page.relative_to(WEBSITE).as_posix()
        url = "https://www.judgekeeper.com/" + ("" if name == "index.html" else name)
        assert url in locs, url


# Commands

PLACEHOLDER = re.compile(r"<[a-z]|\[|\||\.\.\.")


def _subcommands() -> set[str]:
    parser = _parser()
    (sub,) = [a for a in parser._actions if a.dest == "command"]
    return set(sub.choices)


def _all_commands():
    for page in pages():
        for line, argv in commands(page):
            # The generated pages come from docs/*.md, whose syntax lines use placeholders
            # such as <tool> and [--metric NAME]; real commands there are checked.
            if page.name in GENERATED_PAGES and PLACEHOLDER.search(line):
                continue
            yield pytest.param(argv, id=f"{page.name}: {line[:70]}")


@pytest.mark.parametrize("argv", list(_all_commands()))
def test_every_command_on_the_site_parses(argv):
    if len(argv) == 1 and argv[0] in _subcommands():
        return  # a mention of a command by name in a sentence, such as `judgekeeper gate`
    parser = _parser()
    try:
        parser.parse_args(argv)
    except SystemExit as e:
        if e.code not in (0, None):  # 0: --version or --help, which print and stop
            pytest.fail(f"`judgekeeper {' '.join(argv)}` does not parse (exit {e.code})")


def test_the_pages_show_commands():
    counts = {p.name: len(commands(p)) for p in hand_written_pages()}
    assert counts["index.html"] == 0  # the home page installs and points on, nothing more
    assert counts["start.html"] >= 5  # the four steps, and other ways to install
    assert counts["learn.html"] >= 12
    assert counts["setup.html"] >= 4
    assert counts["tutorial.html"] >= 10


def test_pytest_options_on_the_site_exist():
    plugin = (ROOT / "src/judgekeeper/pytest_plugin.py").read_text(encoding="utf-8")
    real = set(re.findall(r'addoption\("(--judgekeeper-[a-z-]+)"', plugin))
    shown = set()
    for page in hand_written_pages():
        for el in parse(page).iter():
            if el.tag == "code" and not in_output(el):
                shown |= set(re.findall(r"--judgekeeper-[a-z-]+", el.text()))
    assert shown, "the site shows the pytest plugin"
    assert shown <= real, shown - real


def test_the_setup_page_shows_the_example_workflow_unchanged():
    expected = (ROOT / "docs/examples/workflows/judge-gate.yml").read_text(encoding="utf-8")
    blocks = [el for el in parse(WEBSITE / "setup.html").iter()
              if el.tag == "code" and el.attrs.get("data-file") ==
              "docs/examples/workflows/judge-gate.yml"]
    assert len(blocks) == 1
    assert blocks[0].text().strip() == expected.strip()


# Numbers

def _lookup(data, path: str):
    for part in path.split("."):
        m = re.fullmatch(r"(\w+)\[(.+)\]", part)
        if m:
            key, wanted = m.groups()
            data = next(e for e in data[key] if wanted in e.values())
        else:
            data = data[int(part)] if isinstance(data, list) else data[part]
    return data


def render(value, fmt: str) -> str:
    """How a number is written on the site."""
    if fmt == "2f":
        return f"{value:.2f}"
    if fmt == "1f":
        return f"{value:.1f}"
    if fmt == "pct0":
        return f"{value:.0%}"
    if fmt == "pct1":
        return f"{value:.1%}"
    if fmt == "int":
        return str(int(value))
    if fmt == "split":  # a class share such as 0.8 written as 80/20
        return f"{round(value * 100)}/{round(100 - value * 100)}"
    raise ValueError(f"unknown data-format {fmt!r}")


def _sourced(attr: str):
    for page in hand_written_pages():
        for el in parse(page).iter():
            if attr in el.attrs:
                yield page, el


def test_report_numbers_match_the_committed_report():
    found = list(_sourced("data-report"))
    assert len(found) >= 15
    for page, el in found:
        value = _lookup(REPORT, el.attrs["data-report"])
        fmt = el.attrs.get("data-format", "2f")
        assert el.text().strip() == render(value, fmt), (page.name, el.attrs)


def test_constants_match_the_code():
    found = list(_sourced("data-const"))
    assert found
    for page, el in found:
        module, name = el.attrs["data-const"].split(":")
        value = getattr(importlib.import_module(module), name)
        fmt = el.attrs.get("data-format", "2f")
        assert el.text().strip() == render(value, fmt), (page.name, el.attrs)


def test_exit_codes_match_the_code():
    from judgekeeper import attribute, gate

    tables = {"gate": gate.EXIT_CODES, "attribute": attribute.EXIT_CODES}
    found = list(_sourced("data-exit"))
    statuses = {el.attrs["data-exit"] for _, el in found}
    assert {f"gate:{s}" for s in gate.EXIT_CODES} <= statuses
    assert {f"attribute:{s}" for s in attribute.EXIT_CODES} <= statuses
    for page, el in found:
        table, status = el.attrs["data-exit"].split(":")
        assert el.text().strip() == str(tables[table][status]), (page.name, el.attrs)


NUMBER = re.compile(r"\d+\.\d+|\d+(?:\.\d+)?\s?%")
NAMES = ("Claude Haiku 4.5",)  # product names, not measurements
EXEMPT_TAGS = {"pre", "code", "script", "style", "svg"}


def test_no_unsourced_numbers():
    """A decimal or a percentage in prose must come from a report, the code or a label."""
    bad = []
    for page in hand_written_pages():
        for el in parse(page).iter():
            for child in el.children:
                if not isinstance(child, str):
                    continue
                text = child
                for name in NAMES:
                    text = text.replace(name, "")
                if not NUMBER.search(text):
                    continue
                chain = [el, *el.ancestors()]
                if any(a.tag in EXEMPT_TAGS or "data-illustration" in a.attrs
                       or any(s in a.attrs for s in SOURCE_ATTRS) for a in chain):
                    continue
                bad.append(f"{page.name}: {child.strip()[:80]!r}")
    assert not bad, "\n".join(bad)


def test_illustrations_say_so():
    for page in hand_written_pages():
        for el in parse(page).iter():
            if "data-illustration" in el.attrs:
                assert "illustration" in el.text().lower(), (page.name, el.attrs)


# The JavaScript metrics against judgekeeper.metrics

CASES = [  # (tp, fn, fp, tn): judge vs human counts
    (18, 2, 3, 17), (20, 0, 20, 0), (36, 0, 4, 0), (20, 0, 0, 20), (0, 20, 20, 0),
    (10, 10, 10, 10), (7, 0, 1, 2), (1, 0, 0, 0), (0, 0, 3, 5), (196, 10, 28, 185),
    (5, 15, 0, 20), (0, 0, 0, 1),
]


def _python(tp, fn, fp, tn) -> dict:
    human = ["pass"] * (tp + fn) + ["fail"] * (fp + tn)
    judge = ["pass"] * tp + ["fail"] * fn + ["pass"] * fp + ["fail"] * tn
    a = agreement(human, judge, "pass", "fail")
    tpr_ci, tnr_ci = wilson(tp, tp + fn), wilson(tn, tn + fp)
    return {"kappa": a["kappa"], "tpr": a["tpr"], "tnr": a["tnr"], "accuracy": a["accuracy"],
            "tpr_lo": tpr_ci["lo"], "tpr_hi": tpr_ci["hi"],
            "tnr_lo": tnr_ci["lo"], "tnr_hi": tnr_ci["hi"]}


def test_js_metrics_match_python():
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed (CI has it)")
    script = (
        "const m = require(process.argv[1]);"
        "const cases = JSON.parse(process.argv[2]);"
        "console.log(JSON.stringify(cases.map(([tp, fn, fp, tn]) => {"
        "  const a = m.agreement(tp, fn, fp, tn);"
        "  return {kappa: a.kappa, tpr: a.tpr, tnr: a.tnr, accuracy: a.accuracy,"
        "    tpr_lo: a.tprCi.lo, tpr_hi: a.tprCi.hi, tnr_lo: a.tnrCi.lo, tnr_hi: a.tnrCi.hi};"
        "})));")
    out = subprocess.run([node, "-e", script, str(WEBSITE / "assets/metrics.js"),
                          json.dumps(CASES)], capture_output=True, text=True, check=True)
    for case, js in zip(CASES, json.loads(out.stdout), strict=True):
        py = _python(*case)
        for key, expected in py.items():
            got = js[key]
            if expected is None:
                assert got is None, (case, key, got)
            else:
                assert got == pytest.approx(expected, abs=1e-12), (case, key)


# Assets and links

def _assets():
    return [p for p in WEBSITE.rglob("*") if p.is_file() and "examples" not in
            p.relative_to(WEBSITE).parts and p.suffix in {".html", ".css", ".js", ".svg"}]


IMAGES = {".png", ".jpg", ".jpeg", ".gif", ".webp"}  # pictures: bytes, with no text to read


def _is_external(url: str) -> bool:
    return bool(urlsplit(url).scheme) or url.startswith("//")


def test_no_external_assets_and_no_tracking():
    for page in pages():
        for el in parse(page).iter():
            for attr in ("src", "srcset", "data", "poster"):
                if attr in el.attrs:
                    assert not _is_external(el.attrs[attr]), (page.name, el.tag, el.attrs)
            if el.tag == "link":
                assert not _is_external(el.attrs.get("href", "")), (page.name, el.attrs)
            assert el.tag not in {"form", "iframe", "object", "embed"}, (page.name, el.tag)
    for path in WEBSITE.joinpath("assets").iterdir():
        if path.suffix.lower() in IMAGES:
            continue  # every other file, the SVG logo included, is read as text and checked
        text = path.read_text(encoding="utf-8")
        text = text.replace('xmlns="http://www.w3.org/2000/svg"', "")  # a name, not a request
        assert "http://" not in text and "https://" not in text, path.name
        for banned in ("@import", "document.cookie", "localStorage", "sessionStorage", "fetch(",
                       "XMLHttpRequest", "sendBeacon", "WebSocket"):
            assert banned not in text, (path.name, banned)


def _ids(page: Path) -> set[str]:
    return {el.attrs["id"] for el in parse(page).iter() if "id" in el.attrs}


def test_internal_links_resolve():
    checked = 0
    for page in pages():
        for el in parse(page).iter():
            for attr in ("href", "src"):
                url = el.attrs.get(attr)
                if not url or _is_external(url) or url.startswith("mailto:"):
                    continue
                parts = urlsplit(url)
                assert not parts.path.startswith("/"), f"{page.name}: {url} is not relative"
                target = (page.parent / parts.path).resolve() if parts.path else page
                if target.is_dir():
                    target = target / "index.html"
                assert target.is_file(), f"{page.name}: {url} -> {target}"
                if parts.fragment and target.suffix == ".html":
                    assert parts.fragment in _ids(target), f"{page.name}: {url}"
                checked += 1
    assert checked > 50


def test_the_report_link_works_in_the_local_preview():
    # website/examples is a link to docs/examples, so http.server --directory website serves it.
    assert (WEBSITE / "examples/llmbar-haiku/report.html").is_file()
    assert (WEBSITE / "examples").is_symlink()


def test_the_reference_page_is_current(tmp_path):
    out = tmp_path / "reference.html"
    subprocess.run([sys.executable, str(ROOT / "scripts/render_reference.py"),
                    str(ROOT / "docs/reference.md"), str(out)], check=True, capture_output=True)
    assert out.read_text(encoding="utf-8") == (WEBSITE / "reference.html").read_text(
        encoding="utf-8"), "run: python scripts/render_reference.py"


def test_the_reference_converter_is_small():
    lines = (ROOT / "scripts/render_reference.py").read_text(encoding="utf-8").splitlines()
    assert len(lines) <= 150


def test_page_weight_under_500_kb():
    assert sum(p.stat().st_size for p in _assets()) < 500_000


# Share previews: the picture, title and line shown when a link to the site is pasted in a chat

SITE = "https://www.judgekeeper.com/"
SHARE_TAGS = ["og:type", "og:site_name", "og:title", "og:description", "og:url", "og:image",
              "og:image:width", "og:image:height", "og:image:alt", "twitter:card",
              "twitter:title", "twitter:description", "twitter:image"]
SHARE_ALT = ("judgekeeper: Check your LLM-as-a-judge. See how often it agrees with human labels, "
             "in one command.")
EIGHT_PAGES = {"index.html", "start.html", "assistant.html", "learn.html",
              "reference.html", "setup.html", "tutorial.html", "own-metric.html"}


def _head(page: Path) -> tuple[str, str, list[tuple[str, str, str]]]:
    """The <title>, the meta description and the (attribute, key, content) of each share tag."""
    (head,) = [el for el in parse(page).iter() if el.tag == "head"]
    (title,) = [el.text().strip() for el in head.iter() if el.tag == "title"]
    (description,) = [el.attrs["content"] for el in head.iter()
                      if el.tag == "meta" and el.attrs.get("name") == "description"]
    share = [(attr, el.attrs[attr], el.attrs.get("content", ""))
             for el in head.iter() if el.tag == "meta" for attr in ("property", "name")
             if el.attrs.get(attr, "").startswith(("og:", "twitter:"))]
    return title, description, share


def _png_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n" and data[12:16] == b"IHDR", path.name
    return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")


def test_every_page_has_the_share_preview_tags():
    assert {p.relative_to(WEBSITE).as_posix() for p in pages()} == EIGHT_PAGES
    for page in pages():
        name = page.relative_to(WEBSITE).as_posix()
        title, description, share = _head(page)
        assert [key for _, key, _ in share] == SHARE_TAGS, name  # each one, once
        for attr, key, _ in share:  # Open Graph is read from property=, the X tags from name=
            assert attr == ("property" if key.startswith("og:") else "name"), (name, key)
        tag = {key: content for _, key, content in share}
        assert tag["og:type"] == "website", name
        assert tag["og:site_name"] == "judgekeeper", name
        assert tag["twitter:card"] == "summary_large_image", name
        assert title and tag["og:title"] == title == tag["twitter:title"], name
        assert description and tag["og:description"] == description, name
        assert tag["twitter:description"] == description, name
        assert tag["og:url"] == SITE + ("" if name == "index.html" else name), name
        assert tag["og:image:alt"] == SHARE_ALT, name
        assert tag["og:image"] == tag["twitter:image"], name
        assert tag["og:image"].startswith(SITE), f"{name}: the picture is not on this site"
        image = WEBSITE / tag["og:image"][len(SITE):]
        assert image.is_file() and image.suffix in IMAGES, f"{name}: no {tag['og:image']}"
        assert (tag["og:image:width"], tag["og:image:height"]) == tuple(
            str(n) for n in _png_size(image)), name


def test_the_share_preview_picture_is_a_small_wide_png():
    image = WEBSITE / "assets/social-preview.png"
    assert _png_size(image) == (1280, 640)
    assert image.stat().st_size < 300_000  # some apps show no picture when it is heavier


def test_every_page_carries_the_tags_the_generators_write():
    """One source for the picture's address and alt text: scripts/share_preview.py. The
    generated pages get their tags from it; a hand-written page must carry the same lines."""
    spec = importlib.util.spec_from_file_location("share_preview",
                                                  ROOT / "scripts/share_preview.py")
    share_preview = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(share_preview)
    assert share_preview.IMAGE_ALT == SHARE_ALT
    for page in pages():
        name = page.relative_to(WEBSITE).as_posix()
        title, description, _ = _head(page)
        expected = share_preview.tags(name, title, description)
        assert expected in page.read_text(encoding="utf-8"), (
            f"{name}: its share-preview tags are not what scripts/share_preview.py writes:\n"
            f"{expected}")


# Accessibility and brand

def test_pages_are_accessible_basics():
    for page in pages():
        tree = parse(page)
        els = list(tree.iter())
        html = next(el for el in els if el.tag == "html")
        assert html.attrs.get("lang") == "en", page.name
        assert any(el.tag == "title" and el.text().strip() for el in els), page.name
        assert any(el.tag == "meta" and el.attrs.get("name") == "viewport" for el in els)
        assert sum(el.tag == "h1" for el in els) == 1, page.name
        assert any(el.tag == "main" for el in els), page.name
        assert any(el.tag == "a" and el.attrs.get("href") == "#main" for el in els), page.name
        for el in els:
            if el.tag == "img":
                assert "alt" in el.attrs, (page.name, el.attrs)
            if el.tag == "button":
                assert el.text().strip() or el.attrs.get("aria-label"), (page.name, el.attrs)
            if el.tag == "svg" and el.attrs.get("aria-hidden") != "true":
                assert el.attrs.get("role") == "img" and (
                    el.attrs.get("aria-label") or any(c.tag == "title" for c in el.iter())
                ), (page.name, el.attrs)


def test_css_respects_motion_theme_and_focus():
    css = (WEBSITE / "assets/style.css").read_text(encoding="utf-8")
    assert "prefers-reduced-motion: reduce" in css
    assert "prefers-color-scheme: dark" in css
    assert ":focus-visible" in css
    for colour in ("#1E293B", "#10B981"):
        assert colour.lower() in css.lower(), colour


def test_logo_is_the_split_shield():
    svg = (WEBSITE / "assets/logo.svg").read_text(encoding="utf-8")
    assert "#1E293B" in svg and "#10B981" in svg and "#FFFFFF" in svg.upper()
