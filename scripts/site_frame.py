"""The frame every page shares: the lines in <head> that load the look, the header with the
navigation and the theme switch, and the footer.

Written here, once. scripts/render_reference.py puts them into the generated pages; the
hand-written pages carry the same blocks, and tests/test_website_look.py compares every page
with them. After a change here, run this script: it rewrites the blocks in the hand-written
pages (and run scripts/render_reference.py for the generated ones). Standard library only.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

WEBSITE = Path(__file__).resolve().parent.parent / "website"
GITHUB = "https://github.com/judgekeeper/judgekeeper"
NAV = [("index.html", "Home"), ("start.html", "Guide"), ("reference.html", "Reference"),
       (GITHUB, "GitHub")]
START_HERE = [("start.html", "Guide"), ("reference.html", "Reference"), (GITHUB, "GitHub")]
MORE = [("own-metric.html", "No judge yet? Your own metric"),
        ("assistant.html", "With a coding assistant"),
        ("setup.html", "Setup and API keys"),
        ("learn.html", "How it works, in depth"),
        ("tutorial.html", "Advanced commands")]
FONTS = ("atkinson-hyperlegible-latin-400-normal.woff2", "bricolage-grotesque-latin-800-normal.woff2")
LOGO = ('<svg viewBox="0 0 64 72" aria-hidden="true" focusable="false">'
        '<path d="M32 3 L5 12 V34 C5 51 17 63 32 69 Z" fill="#1E293B"/>'
        '<path d="M32 3 L59 12 V34 C59 51 47 63 32 69 Z" fill="#10B981"/>'
        '<path d="M18 36 L28 46 L47 25" fill="none" stroke="#FFFFFF" stroke-width="6" '
        'stroke-linecap="round" stroke-linejoin="round"/></svg>')
SUN = ('<svg class="sun" viewBox="0 0 24 24" aria-hidden="true" focusable="false">'
       '<circle cx="12" cy="12" r="4.2"/><path d="M12 2.5v2.2M12 19.3v2.2M2.5 12h2.2M19.3 12h2.2'
       'M5.3 5.3l1.6 1.6M17.1 17.1l1.6 1.6M5.3 18.7l1.6-1.6M17.1 6.9l1.6-1.6"/></svg>')
MOON = ('<svg class="moon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">'
        '<path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z"/></svg>')


def head_links() -> str:
    """The icon, the two fonts every page shows first, the styles and the theme, which is set
    before the page is drawn (assets/theme.js, not deferred) so it never flashes."""
    preload = "".join(f'<link rel="preload" href="assets/fonts/{f}" as="font" type="font/woff2" '
                      "crossorigin>\n" for f in FONTS)
    return ('<link rel="icon" href="assets/logo.svg" type="image/svg+xml">\n' + preload
            + '<link rel="stylesheet" href="assets/style.css">\n'
            + '<script src="assets/theme.js"></script>')


def _links(items, target: str = "") -> str:
    current = ' aria-current="page"'
    return "".join(f'<li><a href="{href}"{current if href == target else ""}>{label}</a></li>'
                   for href, label in items)


def header(target: str) -> str:
    """The skip link and the header of the page `target`, with that page marked as current."""
    return (
        '<a class="skip" href="#main">Skip to the content</a>\n'
        '<header class="site-header">\n<div class="wrap">\n'
        f'<a class="brand" href="index.html">{LOGO}judgekeeper</a>\n'
        '<nav class="site-nav" id="site-nav" aria-label="Site">\n'
        f"<ul>{_links(NAV, target)}</ul>\n</nav>\n"
        '<button class="theme-btn" type="button" aria-label="Switch to the light theme">'
        f"{SUN}{MOON}</button>\n"
        '<button class="menu-btn" type="button" aria-expanded="false" aria-controls="site-nav">'
        "Menu</button>\n</div>\n</header>")


def footer() -> str:
    return (
        '<footer class="site-footer">\n<div class="wrap cols">\n'
        f'<div><a class="brand" href="index.html">{LOGO}judgekeeper</a>\n'
        '<p class="fine">Free and open source, MIT license. It shows how often your judge '
        "agrees with your labels; it never decides for you.</p></div>\n"
        f'<div><h2>Start here</h2><ul>{_links(START_HERE)}</ul></div>\n'
        f'<div><h2>More</h2><ul>{_links(MORE)}</ul></div>\n'
        "</div>\n</footer>")


BLOCKS = [  # (pattern of the block in a page, what it becomes)
    ((r'<link rel="icon".*?<link rel="stylesheet" href="assets/style.css">'
      r'(\n<script src="assets/theme.js"></script>)?'), lambda name: head_links()),
    (r'<a class="skip".*?</header>', header),
    (r'<footer class="site-footer">.*?</footer>', lambda name: footer()),
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
    generated = {"reference.html", "own-metric.html", "assistant.html"}
    for page in sys.argv[1:] or sorted(p for p in WEBSITE.glob("*.html")
                                       if p.name not in generated):
        apply(Path(page))
