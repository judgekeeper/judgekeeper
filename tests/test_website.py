"""The static website in website/: commands, numbers, metrics, links, assets, weight.

Conventions the pages follow, so these tests can check every figure:

- `data-report="headline.kappa_mean"` with `data-format`: a number from
  docs/examples/llmbar-haiku/report.json. `slices[Natural].kappa_mean` picks a list entry.
- `data-const="judgekeeper.targets:RELIABLE"`: a constant from the code.
- `data-realcheck="summary.25+25.tpr_tnr.mean"` with `data-format`: a number from
  docs/examples/real-data-check/report.json.
- `data-coverage="corrected/levels/0.96/min_cell"`: a number from
  docs/examples/coverage/coverage.json (its keys hold dots, so the path uses slashes).
- `data-example` on a container: made-up numbers, and the container says it is an example.
- `data-ratio="7/10"`: a percentage worked out from the two numbers in the same sentence.
Any other decimal or percentage in a hand-written page fails test_no_unsourced_numbers.
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from judgekeeper.cli import _front_parser, _parser, parse_args
from tests.website_pages import (
    GENERATED_PAGES,
    ROOT,
    WEBSITE,
    commands,
    hand_written_pages,
    pages,
    parse,
)

REPORT = json.loads((ROOT / "docs/examples/llmbar-haiku/report.json").read_text(encoding="utf-8"))
REALCHECK = json.loads((ROOT / "docs/examples/real-data-check/report.json").read_text(
    encoding="utf-8"))
COVERAGE = json.loads((ROOT / "docs/examples/coverage/coverage.json").read_text(encoding="utf-8"))
SOURCE_ATTRS = ("data-report", "data-const", "data-realcheck", "data-coverage")


def test_site_has_its_pages():
    for name in ("index.html", "start.html", "learn.html", "check.html", "privacy.html",
                 "reference.html", "errors/404.html", "llms.txt", "assets/style.css",
                 "assets/site.js", "assets/freecheck.js", "assets/logo.svg",
                 "assets/social-preview.png"):
        assert (WEBSITE / name).is_file(), name
    for gone in ("docs.html", "setup.html", "assets/theme.js", "assets/metrics.js",
                 "assets/freecheck.css"):
        assert not (WEBSITE / gone).exists(), gone


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
        return  # a mention of a command by name in a sentence, such as `judgekeeper fix`
    try:
        parse_args(argv)
    except SystemExit as e:
        if e.code not in (0, None):  # 0: --version or --help, which print and stop
            pytest.fail(f"`judgekeeper {' '.join(argv)}` does not parse (exit {e.code})")


def test_the_pages_show_commands():
    counts = {p.name: len(commands(p)) for p in hand_written_pages()}
    assert counts["index.html"] == 0  # Home is about judgekeeper; setup lives on the Guide
    assert counts["start.html"] >= 6  # the install, then a command for each step
    assert counts["check.html"] == 1  # uvx judgekeeper, under the result


def _options() -> set[str]:
    """Every flag of today's CLI: `judgekeeper` alone, and each command's."""
    parser = _parser()
    (sub,) = [a for a in parser._actions if a.dest == "command"]
    found = set()
    for p in (_front_parser(), parser, *sub.choices.values()):
        for action in p._actions:
            found |= {s for s in action.option_strings if s.startswith("--")}
    return found


# Flags of the eval tools whose commands the Reference shows (promptfoo, Inspect AI)
OTHER_FLAGS = {"--output-file", "--grader", "--repeat", "--log-format", "--no-log-samples"}


def _every_text(page: Path) -> str:
    """Everything on a page a visitor can read or copy, terminal screens included, in the
    page's order."""
    def walk(el) -> str:
        return "".join(c if isinstance(c, str) else "" if c.tag in {"script", "style"}
                       else " " + walk(c) + " " for c in el.children)
    return walk(parse(page))


@pytest.mark.parametrize("page", [*pages(), WEBSITE / "errors/404.html"], ids=lambda p: p.name)
def test_no_page_names_a_removed_command_or_flag(page):
    from judgekeeper.cli import REMOVED

    text = _every_text(page)
    for name in REMOVED:
        assert not re.search(rf"(?<!from )\bjudgekeeper {name}\b", text), name
    named = {m for m in re.findall(r"(?<![\w-])--[a-z][a-z-]*", text)}
    assert named <= _options() | OTHER_FLAGS, sorted(named - _options() - OTHER_FLAGS)


def test_the_flag_rule_finds_a_removed_flag(tmp_path):
    page = tmp_path / "page.html"
    page.write_text("<p>Run <code>judgekeeper --review</code>.</p>", encoding="utf-8")
    named = set(re.findall(r"(?<![\w-])--[a-z][a-z-]*", _every_text(page)))
    assert named == {"--review"} and not named <= _options()


# Numbers

def _lookup(data, path: str, sep: str = "."):
    for part in path.split(sep):
        m = re.fullmatch(r"(\w+)\[(.+)\]", part)
        if m:
            key, wanted = m.groups()
            data = next(e for e in data[key] if wanted in e.values())
        else:
            data = data[int(part)] if isinstance(data, list) else data[part]
    return data


def render(value, fmt: str) -> str:
    """How a number is written on the site."""
    if fmt == "str":  # a name such as the version
        return str(value)
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
    if fmt == "count":
        return f"{int(value):,}"
    if fmt == "per100":  # a share such as 0.946 written as 94.6 (times in 100)
        return f"{value * 100:.1f}"
    if fmt == "split":  # a class share such as 0.8 written as 80/20
        return f"{round(value * 100)}/{round(100 - value * 100)}"
    raise ValueError(f"unknown data-format {fmt!r}")


def _sourced(attr: str):
    for page in hand_written_pages():
        for el in parse(page).iter():
            if attr in el.attrs:
                yield page, el


def test_report_numbers_match_the_committed_report():
    for page, el in _sourced("data-report"):
        value = _lookup(REPORT, el.attrs["data-report"])
        fmt = el.attrs.get("data-format", "2f")
        assert el.text().strip() == render(value, fmt), (page.name, el.attrs)


def test_real_data_numbers_match_the_committed_report():
    for page, el in _sourced("data-realcheck"):
        value = _lookup(REALCHECK, el.attrs["data-realcheck"])
        fmt = el.attrs.get("data-format", "2f")
        assert el.text().strip() == render(value, fmt), (page.name, el.attrs)


def test_coverage_numbers_match_the_committed_grid():
    found = list(_sourced("data-coverage"))
    level = str(COVERAGE["corrected"]["chosen_level"])
    for page, el in found:
        path = el.attrs["data-coverage"]
        assert path.startswith(f"corrected/levels/{level}/"), (page.name, path)
        value = _lookup(COVERAGE, path, sep="/")
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


NUMBER = re.compile(r"\d+\.\d+|\d+(?:\.\d+)?\s?%")
NAMES = ("Python 3.11", "judgekeeper 1.0", "in 1.0")  # names, not measurements
EXEMPT_TAGS = {"pre", "code", "script", "style", "svg", "template"}
EXAMPLE_ATTRS = ("data-example", "data-ratio")


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
                if any(a.tag in EXEMPT_TAGS
                       or any(s in a.attrs for s in (*SOURCE_ATTRS, *EXAMPLE_ATTRS))
                       for a in chain):
                    continue
                bad.append(f"{page.name}: {child.strip()[:80]!r}")
    assert not bad, "\n".join(bad)


def test_examples_say_so_and_ratios_add_up():
    examples = ratios = 0
    for page in hand_written_pages():
        for el in parse(page).iter():
            if "data-example" in el.attrs:
                assert "example" in el.text().lower(), (page.name, el.attrs)
                examples += 1
            if "data-ratio" in el.attrs:
                k, n = (int(x) for x in el.attrs["data-ratio"].split("/"))
                assert el.text().strip() == render(k / n, "pct0"), (page.name, el.attrs)
                sentence = el.parent.text()
                assert f"{n} times" in sentence and f"{k} heads" in sentence, sentence
                ratios += 1
    assert examples >= 3 and ratios == 1  # the range, the re-check table, the kept-aside marks


def test_the_number_rule_finds_a_number_with_no_source(tmp_path, monkeypatch):
    page = tmp_path / "page.html"
    page.write_text('<p>It agrees <b>87%</b> of the time.</p><p data-example>An example: '
                    '61%.</p><pre>about 57%</pre>', encoding="utf-8")
    monkeypatch.setattr(sys.modules[__name__], "hand_written_pages", lambda: [page])
    with pytest.raises(AssertionError, match="87%"):
        test_no_unsourced_numbers()


# Assets and links

def _assets():
    return [p for p in WEBSITE.rglob("*") if p.is_file() and "examples" not in
            p.relative_to(WEBSITE).parts and p.suffix in {".html", ".css", ".js", ".svg"}]


IMAGES = {".png", ".jpg", ".jpeg", ".gif", ".webp"}  # pictures: bytes, with no text to read
# The fonts and their licence texts: no page reads the licences, and fonts are bytes.
FONTS = WEBSITE / "assets" / "fonts"


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
    for path in WEBSITE.joinpath("assets").rglob("*"):
        if path.is_dir() or path.suffix.lower() in IMAGES or path.parent == FONTS:
            continue  # every other file, the SVG logo included, is read as text and checked
        text = path.read_text(encoding="utf-8")
        text = text.replace('xmlns="http://www.w3.org/2000/svg"', "")  # a name, not a request
        assert "http://" not in text and "https://" not in text, path.name
        for banned in ("@import", "document.cookie", "localStorage", "sessionStorage", "fetch(",
                       "XMLHttpRequest", "sendBeacon", "WebSocket", "indexedDB"):
            assert banned not in text, (path.name, banned)
    assert {p.suffix for p in FONTS.iterdir()} == {".woff2", ".txt"}


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
    rendered = out.read_text(encoding="utf-8")
    page = (WEBSITE / "reference.html").read_text(encoding="utf-8")
    assert rendered == page, "run: python scripts/render_reference.py"


def test_the_converter_formats_links_and_bold_that_hold_code():
    spec = importlib.util.spec_from_file_location(
        "render_reference", ROOT / "scripts" / "render_reference.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.inline("**`a.toml` first.** See [`b`](reference.md#x) and `[c](d)`.") == (
        '<strong><code>a.toml</code> first.</strong> See '
        '<a href="reference.html#x"><code>b</code></a> and <code>[c](d)</code>.')
    # pages on the site stay on the site; other docs and example folders open on GitHub
    assert module.link("reference.md#y") == "reference.html#y"
    assert module.link("reference.md") == "reference.html"
    assert module.link("records.schema.json").startswith("https://github.com/")
    assert module.link("examples/coverage/").endswith("/tree/main/docs/examples/coverage/")
    assert module.link("examples/coverage/items.csv") == "examples/coverage/items.csv"


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
SITE_PAGES = {"index.html", "start.html", "learn.html", "reference.html", "check.html",
              "privacy.html"}


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
    assert {p.relative_to(WEBSITE).as_posix() for p in pages()} == SITE_PAGES
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


def test_css_respects_motion_and_focus_and_is_dark_only():
    css = (WEBSITE / "assets/style.css").read_text(encoding="utf-8")
    assert "prefers-reduced-motion: reduce" in css
    assert "prefers-color-scheme" not in css and "data-theme" not in css
    assert ":focus-visible" in css
    assert "#10b981" in css.lower()


def test_logo_is_the_split_shield():
    svg = (WEBSITE / "assets/logo.svg").read_text(encoding="utf-8")
    assert "#1E293B" in svg and "#10B981" in svg and "#FFFFFF" in svg.upper()


# The free check in the browser: nothing leaves the page ------------------------------------

CHECK = WEBSITE / "check.html"
CADDYFILE = (ROOT / "deploy/railway/Caddyfile").read_text(encoding="utf-8")
CHECK_POLICY = ("default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
                "connect-src 'none'; base-uri 'none'; form-action 'none'")
SITE_POLICY = re.search(r'Content-Security-Policy "([^"]+)"', CADDYFILE)[1]


def test_the_check_page_loads_its_script_and_has_no_inline_script():
    els = list(parse(CHECK).iter())
    scripts = [el.attrs.get("src") for el in els if el.tag == "script"]
    assert re.fullmatch(r"assets/site\.js\?v=\d+", scripts[0])  # the version: site_frame.py
    assert scripts[1:] == ["assets/freecheck.js"]
    assert all(not el.text().strip() for el in els if el.tag == "script")
    ids = {el.attrs.get("id") for el in els}
    assert {"fc-drop", "fc-file", "fc-result", "fc-next"} <= ids  # what freecheck.js uses
    (file_input,) = [el for el in els if el.tag == "input"]
    assert file_input.attrs["type"] == "file"


def test_the_check_page_blocks_every_connection_in_its_own_policy():
    (meta,) = [el for el in parse(CHECK).iter() if el.tag == "meta"
               and el.attrs.get("http-equiv") == "Content-Security-Policy"]
    assert meta.attrs["content"] == CHECK_POLICY
    # fonts too come only from the site: default-src 'self', and no font-src opens it wider
    assert "font-src" not in CHECK_POLICY and "default-src 'self'" in CHECK_POLICY


def test_caddy_sends_the_check_page_the_stricter_policy():
    assert "@check path /check /check.html" in CADDYFILE
    (rule,) = re.findall(r'header @check >Content-Security-Policy "([^"]+)"', CADDYFILE)
    assert rule == CHECK_POLICY + "; frame-ancestors 'none'"
    # everything the site's policy allows or forbids, and no connection at all on top
    for part in SITE_POLICY.split("; "):
        assert part in rule, part
    assert "connect-src 'none'" not in SITE_POLICY


def test_home_links_to_the_check_page_twice():
    links = [el for el in parse(WEBSITE / "index.html").iter()
             if el.tag == "a" and el.attrs.get("href") == "check.html"]
    assert [" ".join(a.text().split()) for a in links] == ["Check in your browser"] * 2
    assert "https://www.judgekeeper.com/check.html" in (WEBSITE / "sitemap.xml").read_text(
        encoding="utf-8")
    assert "(https://www.judgekeeper.com/check.html)" in (WEBSITE / "llms.txt").read_text(
        encoding="utf-8")


def test_the_check_page_says_what_it_reads_and_that_the_file_stays():
    text = " ".join(parse(CHECK).text().split())
    for words in ("Check your LLM-as-a-judge",
                  "Drop the results file your eval tool saved. It stays on your computer.",
                  "Drop your results file here, or click to choose one.",
                  "promptfoo · DeepEval · CSV · JSONL",
                  ("This shows whether your judge gives real Pass or Fail grades, not whether it "
                  "agrees with you. To see that, run uvx judgekeeper in your project and mark "
                  "some answers.")):
        assert words in text, words
