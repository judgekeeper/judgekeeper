"""The look every page judgekeeper serves shares: the logo, the fonts, the colours, the top
bar and the focus ring.

The pages are dark only (page #0b0c0e, text #e6e8eb): there is no light theme and no switch,
and `color-scheme: dark` on :root keeps the browser's own parts (scroll bars, form controls)
dark too. Hairlines only: no boxes, no shadows, no rounded panels. Green and red colour only
Pass and Fail (and the "See your result" link), amber a verdict that needs work.

The fonts (Manrope, and JetBrains Mono at 400 and 500, both under the SIL Open Font License;
the mono files are Fontsource's) are embedded as base64 from this package's `fonts/` folder, so
a page loads nothing from anywhere else.
"""

from __future__ import annotations

import base64
import hashlib
from functools import lru_cache
from importlib import resources

SANS, MONO = "Manrope", "JetBrains Mono"
FONTS = (("manrope-latin-wght-normal.woff2", SANS, "200 800"),
         ("jetbrains-mono-latin-400-normal.woff2", MONO, "400"),
         ("jetbrains-mono-latin-500-normal.woff2", MONO, "500"))  # numbers on the result
FONT_LICENCES = ("OFL-Manrope.txt", "OFL-JetBrainsMono.txt")
NAVY, GREEN = "#1E293B", "#10B981"  # the logo's two halves: the judge and the person

# The logo: the website's logo.svg, its paths and colours as they are.
SHIELD = ('<svg viewBox="0 0 64 72" aria-hidden="true" focusable="false">'
          f'<path d="M32 3 L5 12 V34 C5 51 17 63 32 69 Z" fill="{NAVY}"/>'
          f'<path d="M32 3 L59 12 V34 C59 51 47 63 32 69 Z" fill="{GREEN}"/>'
          '<path d="M18 36 L28 46 L47 25" fill="none" stroke="#FFFFFF" stroke-width="6" '
          'stroke-linecap="round" stroke-linejoin="round"/></svg>')
LOGO = f'<span class="logo-mark">{SHIELD}</span>'
BRAND = f'<span class="brand">{LOGO}<span>judgekeeper<sup>™</sup></span></span>'


@lru_cache(maxsize=1)
def font_faces() -> str:
    """The @font-face rules, each font embedded as base64."""
    folder = resources.files("judgekeeper") / "fonts"
    rules = []
    for name, family, weight in FONTS:
        data = base64.b64encode((folder / name).read_bytes()).decode("ascii")
        rules.append(f'@font-face {{ font-family: "{family}"; font-weight: {weight}; '
                     'font-style: normal; font-display: swap; '
                     f'src: url("data:font/woff2;base64,{data}") format("woff2"); }}')
    return "\n".join(rules)


# The colours: dark only.
TOKENS = """
:root { color-scheme: dark;
  --bg: #0b0c0e; --text: #e6e8eb; --muted: #8b919a; --faint: #767c86;
  --line: #262a30; --hover: #121418; --current: #17191e;
  --green: #10B981; --green-fill: #047857; --red: #e5484d; --red-fill: #c73b40;
  --amber: #e0a43a; --scrim: rgba(0,0,0,.66);
  --sans: "Manrope", system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  --mono: "JetBrains Mono", ui-monospace, Menlo, Consolas, monospace; }
"""

# What every page shares beyond the colours: the top bar (72px, a hairline under it: the judge
# and the eval tool left, the logo and name centred, the page's own things right) and the
# focus ring, inset in the text colour, so no ring ever shows a gap.
BASE = """
* { box-sizing: border-box; }
[hidden] { display: none !important; }
html, body { margin: 0; }
body { background: var(--bg); color: var(--text); font: 500 16px/1.5 var(--sans);
  -webkit-font-smoothing: antialiased; }
a { color: inherit; }
button { font: inherit; color: inherit; background: none; border: 0; padding: 0;
  cursor: pointer; }
code, kbd { font-family: var(--mono); }
:focus { outline: none; }
:focus-visible { outline: 2px solid var(--text); outline-offset: -2px; }
.sr { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0);
  white-space: nowrap; }
.top { height: 72px; flex: none; display: grid; grid-template-columns: minmax(0, 1fr) auto
  minmax(0, 1fr); align-items: center; gap: 16px; padding: 0 28px;
  border-bottom: 1px solid var(--line); }
.meta { justify-self: start; display: grid; grid-template-columns: auto auto; gap: 2px 12px;
  align-items: baseline; min-width: 0; line-height: 1.4; }
.meta .k { font-size: 12px; font-weight: 600; letter-spacing: .04em; text-transform: uppercase;
  color: var(--muted); }
.meta .v { font-family: var(--mono); font-size: 12.5px; color: var(--text); white-space: nowrap;
  overflow: hidden; text-overflow: ellipsis; min-width: 0; }
.brand { display: flex; align-items: center; gap: 11px; color: var(--text); justify-self: center;
  font-size: 24px; font-weight: 800; letter-spacing: -.01em; }
.brand sup { font-size: .42em; line-height: 1; font-weight: 600; margin-left: .476em;
  position: relative; top: -1em; vertical-align: baseline; }
.logo-mark { display: inline-flex; flex: none; }
.logo-mark svg { width: 34px; height: 38px; }
.top .right { min-width: 0; display: flex; align-items: center; justify-content: flex-end;
  gap: 16px; white-space: nowrap; }
@media (max-width: 900px) {
  .top { height: auto; grid-template-columns: 1fr; padding: 12px 16px; gap: 10px; }
  .meta { grid-row: 1; }
  .brand { grid-row: 2; justify-self: start; }
  .top .right { grid-row: 3; justify-content: space-between; white-space: normal; }
}
@media (max-width: 760px) {
  .meta .k { font-size: 13px; }
  .meta .v { font-size: 14px; }
}
@media (max-width: 420px) {
  .meta { grid-template-columns: minmax(0, 1fr); gap: 0; }
  .meta .v { white-space: normal; overflow-wrap: anywhere; }
  .meta .v + .k { margin-top: 6px; }
}
@media (prefers-reduced-motion: reduce) { * { transition: none !important;
  animation: none !important; scroll-behavior: auto !important; } }
"""


def script_hash(script: str) -> str:
    """The CSP source that lets exactly this inline script run."""
    digest = base64.b64encode(hashlib.sha256(script.encode("utf-8")).digest()).decode("ascii")
    return f"'sha256-{digest}'"


def meta(judge: str | None, tool: str | None) -> str:
    """The top bar's left: two plain lines, the judge's model and the eval tool (escaped
    text); nothing when neither is known."""
    parts = []
    if judge:
        parts.append(f'<span class="k">LLM-as-a-judge:</span><span class="v" '
                     f'title="{judge}">{judge}'
                     "</span>")
    if tool:
        parts.append(f'<span class="k">Eval tool:</span><span class="v">{tool}</span>')
    return f'<div class="meta">{"".join(parts)}</div>' if parts else ""


def top(left: str, right: str) -> str:
    """The top bar: the judge and tool left, the logo and name centred, the page's state
    right."""
    left = left or '<div class="meta"></div>'  # the grid's first column, even when empty
    return f'<header class="top">{left}{BRAND}<div class="right">{right}</div></header>'


def head(title: str, style: str, meta: str = "") -> str:
    """The page up to <body>: `meta` is any more tags for its head."""
    return ("<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
            f"{meta}<title>{title}</title>\n"
            f"<style>{font_faces()}\n{TOKENS}{BASE}{style}</style>\n</head>\n<body>\n")
