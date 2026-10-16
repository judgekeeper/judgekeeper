"""The look of the pages only `judgekeeper start` shows (start_page.py): the review page and the
fix page. Navy only, the heading font embedded, nothing loaded from outside. The pages every
command serves are tested in test_product_pages.py.
"""

from __future__ import annotations

import base64
import re
from pathlib import Path

from judgekeeper import start_page

ROOT = Path(__file__).resolve().parent.parent
PACKAGE_FONTS = ROOT / "src" / "judgekeeper" / "fonts"
SITE_FONTS = ROOT / "website" / "assets" / "fonts"


def _pages() -> dict[str, str]:
    return {"review": start_page.review_page("support bot", "Be kind."),
            "fix": start_page.fix_page("support bot")}


# Fonts and loads ---------------------------------------------------------------------------

def test_the_heading_font_is_embedded_in_every_page_from_the_package_files():
    for name, page in _pages().items():
        for file, weight in start_page.FONTS:
            data = base64.b64encode((PACKAGE_FONTS / file).read_bytes()).decode()
            rule = (f'@font-face {{ font-family: "Bricolage Grotesque"; font-weight: {weight}; '
                    f'font-style: normal; font-display: swap; '
                    f'src: url("data:font/woff2;base64,{data}") format("woff2"); }}')
            assert rule in page, (name, weight)
        assert page.count("@font-face") == 2, name
        assert '--display: "Bricolage Grotesque", system-ui, sans-serif;' in page
        assert '--body: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;' in page
        assert 'ui-monospace, "SF Mono", Menlo, Consolas, monospace' in page


def test_the_package_fonts_are_the_sites_fonts_with_their_licence():
    for file, _ in start_page.FONTS:
        assert (PACKAGE_FONTS / file).read_bytes() == (SITE_FONTS / file).read_bytes()
    licence = (PACKAGE_FONTS / start_page.FONT_LICENCE).read_text(encoding="utf-8")
    assert licence == (SITE_FONTS / start_page.FONT_LICENCE).read_text(encoding="utf-8")
    assert "SIL Open Font License" in licence and "Bricolage" in licence


def test_no_page_loads_anything_from_outside():
    for name, page in _pages().items():
        assert "<link" not in page and "@import" not in page, name
        assert not re.search(r"https?://", page), name
        style = re.search(r"<style>(.*?)</style>", page, re.DOTALL)[1]
        for match in re.finditer(r"url\(([^)]*)\)", style):
            assert match[1].startswith('"data:font/woff2;base64,'), (name, match[1][:40])
        assert ' src="' not in page.replace('src: url("data:', ""), name


def test_the_pages_are_navy_only_and_animate_transform_and_opacity_alone():
    for name, page in _pages().items():
        style = re.search(r"<style>(.*?)</style>", page, re.DOTALL)[1]
        assert "--bg: #0E1525" in style and "--green: #10B981" in style, name
        assert "prefers-color-scheme" not in style, name
        assert "transition: all" not in style, name
        for transition in re.findall(r"transition: ([^;]*);", style):
            for part in transition.split(","):
                assert part.split()[0] in ("transform", "opacity", "background-color",
                                           "none"), (name, part)
        assert "cubic-bezier(.23,1,.32,1)" in style and ":focus-visible" in style, name
        assert "@media (prefers-reduced-motion: reduce)" in style, name
        assert "backdrop-filter: blur(20px)" in style, name
        assert "max-width: 1280px" in style, name


# The review and fix pages ------------------------------------------------------------------

def test_the_review_page_has_the_task_left_and_the_panel_right():
    page = start_page.review_page("support bot", "Be kind.")
    left, right = page.split('<main class="body split">')[1].split('<div class="col">\n  <section')
    assert '<h1 class="h1">See where you disagree</h1>' in left
    assert '<li id="step-a"><i>1</i>Look again</li>' in left
    assert '<div class="q" id="question"></div>' in left and '<div class="a" id="answer"></div>' in left
    assert '<span class="tag" id="about">support bot</span>' in left
    for needed in ('class="panel" id="ask"', 'id="look"', 'id="see" hidden', 'id="said"',
                   'id="judge"', 'id="reason"', 'Your judge\'s rule', "Show all",
                   'id="whybox"', "Why? (optional, helps fix your judge)"):
        assert needed in right, needed
    assert "Back to your result" in page and ".vs { display: grid; grid-template-columns: 1fr 1fr;" in page


def test_a_key_pressed_while_the_next_answer_comes_is_kept():
    # After Enter in the why box the box keeps the focus until the next answer is on
    # screen: a choice key pressed then waits and counts for that answer.
    page = start_page.review_page("support bot", "Be helpful.")
    keys = page.split('document.addEventListener("keydown"')[-1].split("});")[0]
    assert "if (moving) {" in keys and "queued = k;" in keys
    assert keys.index("if (moving)") < keys.index('e.target === $("whybox")')
    assert "if (moving) { return; }\n    moving = true;" in page  # goOn: Enter twice is once
    assert "pos = i; render(); arrived(); return;" in page
    arrived = page.split("function arrived() {")[1].split("}\n")[0]
    assert "moving = false; queued = null;" in arrived
    assert "function stay() { moving = false; queued = null; render(); }" in page


def test_the_fix_page_has_the_lists_left_and_a_panel_that_stays_in_view_right():
    page = start_page.fix_page("support bot")
    left, right = page.split('<main class="body split fix">')[1].split('<div class="col stick">')
    for needed in ("What your judge gets wrong", 'id="aside"', 'id="counts"', "What stands out",
                   'id="lists"', 'id="unclear"', "Your own files are\n  never changed."):
        assert needed in left, needed
    for needed in ("Change the rule", "Your judge's rule today", "Move the pass mark"):
        assert needed in right, needed
    assert ".stick { position: sticky; top: calc(var(--hdr) + 20px);" in page
    assert "support bot" not in page  # the fix page is about the judge, not the app
