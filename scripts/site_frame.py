"""The frame every page shares: the lines in <head> that load the look, the menu and the footer.

Written here, once. Every page carries the same blocks, and tests/test_website_look.py
compares every page with them. After a change here, run this script: it rewrites the blocks in
the pages. Standard library only.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

WEBSITE = Path(__file__).resolve().parent.parent / "website"
GITHUB = "https://github.com/judgekeeper/judgekeeper"
NAV = [("index.html", "Home"), ("start.html", "Guide")]
LEGAL = [(f"{GITHUB}/blob/main/docs/reference.md", "Full reference"), ("privacy.html", "Privacy"),
         (f"{GITHUB}/blob/main/TRADEMARKS.md", "Trademarks"),
         (f"{GITHUB}/blob/main/SECURITY.md", "Security")]
THEME = "#0b0c0e"  # style.css --bg: a phone's browser bar takes the page's colour
FONTS = ("manrope-latin-wght-normal.woff2",)  # the text font, so the first screen never jumps
ASSETS = 13  # ?v= on style.css and site.js: add one when either changes, so visitors load them again
LOGO = ('<svg class="logo" viewBox="0 0 64 72" aria-hidden="true" focusable="false">'
        '<path d="M32 3 L5 12 V34 C5 51 17 63 32 69 Z" fill="#1E293B"/>'
        '<path d="M32 3 L59 12 V34 C59 51 47 63 32 69 Z" fill="#10B981"/>'
        '<path d="M18 36 L28 46 L47 25" fill="none" stroke="#FFFFFF" stroke-width="6" '
        'stroke-linecap="round" stroke-linejoin="round"/></svg>')
NOTE = ("judgekeeper and the judgekeeper logo are trademarks of Sathvik Thota. "
        "The Apache-2.0 license covers the code, not the name or logo.")


def head_links() -> str:
    """The browser bar's colour, the icon, the text font every page shows first, and the
    styles."""
    preload = "".join(f'<link rel="preload" href="assets/fonts/{f}" as="font" type="font/woff2" '
                      "crossorigin>\n" for f in FONTS)
    return (f'<meta name="theme-color" content="{THEME}">\n'
            '<link rel="icon" href="assets/logo.svg" type="image/svg+xml">\n' + preload
            + f'<link rel="stylesheet" href="assets/style.css?v={ASSETS}">')


def script() -> str:
    """The site's script, after the styles (the page for a wrong address has none)."""
    return f'<script src="assets/site.js?v={ASSETS}" defer></script>'


def _links(items, target: str = "") -> str:
    current = ' aria-current="page"'
    return "".join(f'<a href="{href}"{current if href == target else ""}>{label}</a>'
                   for href, label in items)


def header(target: str) -> str:
    """The skip link and the menu of the page `target`, with that page marked as current."""
    return (
        '<a class="skip" href="#main">Skip to the content</a>\n'
        '<header class="menu"><div class="wrap">\n'
        f'<nav class="menu-l" aria-label="Pages">{_links(NAV, target)}</nav>\n'
        f'<a class="brand" href="index.html">{LOGO}<span>judgekeeper<sup>™</sup></span></a>\n'
        f'<div class="menu-r"><a class="gh" href="{GITHUB}">GitHub</a></div>\n'
        "</div></header>")


def footer() -> str:
    """The logo, then only the links the menu does not have, the copyright, and the trademark
    notice. The links are a div with role="navigation": a nav would pick up the menu's styles."""
    return (
        '<footer class="foot"><div class="wrap">\n'
        f'<div class="brand">{LOGO}<span>judgekeeper</span></div>\n'
        f'<div class="foot-r" role="navigation" aria-label="Legal">{_links(LEGAL)}'
        f'<span class="copy">© 2026 Sathvik Thota · <a href="{GITHUB}/blob/main/LICENSE">'
        "Apache-2.0 license</a></span></div>\n"
        f'<p class="note">{NOTE}</p>\n'
        "</div></footer>")


BLOCKS = [  # (pattern of the block in a page, what it becomes)
    (r'(?:<meta name="theme-color"[^>]*>\n)?<link rel="icon".*?<link rel="stylesheet" href="assets/style\.css[^"]*">',
     lambda name: head_links()),
    (r'<script src="assets/site\.js[^"]*" defer></script>', lambda name: script()),
    (r'<a class="skip".*?</header>', header),
    (r'<footer class="foot">.*?</footer>', lambda name: footer()),
]


def apply(page: Path) -> None:
    """Rewrite the shared blocks of a hand-written page."""
    text = page.read_text(encoding="utf-8")
    for pattern, block in BLOCKS:
        new = block(page.name)
        text, n = re.subn(pattern, lambda m, new=new: new, text, count=1, flags=re.DOTALL)
        if n != 1:
            raise SystemExit(f"{page.name}: no block matches {pattern[:30]!r}")
    page.write_text(text, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    for page in sys.argv[1:] or sorted(WEBSITE.glob("*.html")):
        apply(Path(page))
