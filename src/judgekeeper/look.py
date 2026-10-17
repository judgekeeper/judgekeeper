"""The look every page judgekeeper serves shares: the logo, the fonts, the colours, the top
bar and the focus ring.

The pages open dark (page #0b0c0e, text #e6e8eb); a switch in the top bar turns them light
(white page, #111317 text) and back. The choice is kept in the browser's storage under
`jk-theme` and read before the page is drawn, so it never flashes; a browser that blocks the
storage shows dark. Hairlines only: no boxes, no shadows, no rounded panels. Green and red
colour only Pass and Fail (and the "See your result" link), amber a verdict that needs work.

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
BRAND = f'<span class="brand">{LOGO}<span>judgekeeper</span></span>'


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


# The colours: dark by default, light when the person picks it.
TOKENS = """
:root { color-scheme: dark;
  --bg: #0b0c0e; --text: #e6e8eb; --muted: #8b919a; --faint: #585e68;
  --line: #262a30; --hover: #121418; --current: #17191e;
  --green: #10B981; --green-fill: #0d9668; --red: #e5484d; --red-fill: #c73b40;
  --amber: #e0a43a; --scrim: rgba(0,0,0,.66);
  --sans: "Manrope", system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  --mono: "JetBrains Mono", ui-monospace, Menlo, Consolas, monospace; }
:root[data-theme="light"] { color-scheme: light;
  --bg: #ffffff; --text: #111317; --muted: #5f6672; --faint: #9aa0aa;
  --line: #d9dde3; --hover: #f6f7f9; --current: #eef0f3;
  --green: #059669; --green-fill: #059669; --red: #dc2626; --red-fill: #dc2626;
  --amber: #b7791f; --scrim: rgba(17,19,23,.42); }
"""

# What every page shares beyond the colours: the top bar (72px, a hairline under it: the judge
# and the eval tool left, the logo and name centred, the page's own things and the theme
# switch right) and the focus ring, inset in the text colour, so no ring ever shows a gap.
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
  color: var(--faint); }
.meta .v { font-family: var(--mono); font-size: 12.5px; color: var(--text); white-space: nowrap;
  overflow: hidden; text-overflow: ellipsis; min-width: 0; }
.brand { display: flex; align-items: center; gap: 11px; color: var(--text); justify-self: center;
  font-size: 24px; font-weight: 800; letter-spacing: -.01em; }
.logo-mark { display: inline-flex; flex: none; }
.logo-mark svg { width: 34px; height: 38px; }
.top .right { min-width: 0; display: flex; align-items: center; justify-content: flex-end;
  gap: 16px; white-space: nowrap; }
.theme { width: 34px; height: 34px; border: 1px solid var(--line); color: var(--muted);
  display: inline-flex; align-items: center; justify-content: center; flex: none; }
.theme:hover { color: var(--text); background: var(--hover); }
.theme svg { width: 16px; height: 16px; fill: none; stroke: currentColor; stroke-width: 1.8;
  stroke-linecap: round; }
.theme .moon { display: none; }
:root[data-theme="light"] .theme .moon { display: block; }
:root[data-theme="light"] .theme .sun { display: none; }
@media (max-width: 760px) {
  .top { height: auto; grid-template-columns: 1fr; padding: 12px 16px; gap: 10px; }
  .meta { grid-row: 1; }
  .brand { grid-row: 2; justify-self: start; }
  .top .right { grid-row: 3; justify-content: space-between; white-space: normal; }
}
@media (prefers-reduced-motion: reduce) { * { transition: none !important;
  animation: none !important; scroll-behavior: auto !important; } }
"""

# Read before the page is drawn: light when the person picked it, else dark.
THEME_FIRST = ("try { if (window.localStorage.getItem(\"jk-theme\") === \"light\") { "
               "document.documentElement.setAttribute(\"data-theme\", \"light\"); } } "
               "catch (e) { /* storage blocked: dark */ }")

# The switch: light or dark, remembered when the browser allows it.
THEME_SWITCH = """
  (function () {
    var root = document.documentElement, b = document.getElementById("theme");
    function sync() { b.setAttribute("aria-pressed", String(root.getAttribute("data-theme") !==
      "light")); }
    b.addEventListener("click", function () {
      var light = root.getAttribute("data-theme") !== "light";
      if (light) { root.setAttribute("data-theme", "light"); }
      else { root.removeAttribute("data-theme"); }
      try { window.localStorage.setItem("jk-theme", light ? "light" : "dark"); }
      catch (e) { /* not remembered */ }
      sync();
    });
    sync();
  })();
"""

SWITCH = ('<button type="button" class="theme" id="theme" aria-label="Dark mode" '
          'aria-pressed="true"><svg class="moon" viewBox="0 0 24 24" aria-hidden="true" '
          'focusable="false"><path d="M21 12.8A9 9 0 1 1 11.2 3 7 7 0 0 0 21 12.8Z"/></svg>'
          '<svg class="sun" viewBox="0 0 24 24" aria-hidden="true" focusable="false">'
          '<circle cx="12" cy="12" r="4.2"/><path d="M12 2.5v2.2M12 19.3v2.2M2.5 12h2.2M19.3 '
          '12h2.2M5.3 5.3l1.6 1.6M17.1 17.1l1.6 1.6M5.3 18.7l1.6-1.6M17.1 6.9l1.6-1.6"/>'
          '</svg></button>')


def script_hash(script: str) -> str:
    """The CSP source that lets exactly this inline script run."""
    digest = base64.b64encode(hashlib.sha256(script.encode("utf-8")).digest()).decode("ascii")
    return f"'sha256-{digest}'"


def meta(judge: str | None, tool: str | None) -> str:
    """The top bar's left: two plain lines, the judge's model and the eval tool (escaped
    text); nothing when neither is known."""
    parts = []
    if judge:
        parts.append(f'<span class="k">Judge:</span><span class="v" title="{judge}">{judge}'
                     "</span>")
    if tool:
        parts.append(f'<span class="k">Eval tool:</span><span class="v">{tool}</span>')
    return f'<div class="meta">{"".join(parts)}</div>' if parts else ""


def top(left: str, right: str) -> str:
    """The top bar: the judge and tool left, the logo and name centred, the page's state and
    the theme switch right."""
    left = left or '<div class="meta"></div>'  # the grid's first column, even when empty
    return (f'<header class="top">{left}{BRAND}<div class="right">{right}{SWITCH}</div>'
            "</header>")


def head(title: str, style: str, script: str, meta: str = "") -> str:
    """The page up to <body>: `script` is the opening tag of the theme script (with its nonce,
    or plain where a hash lets it run)."""
    return ("<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
            f"{meta}<title>{title}</title>\n{script}{THEME_FIRST}</script>\n"
            f"<style>{font_faces()}\n{TOKENS}{BASE}{style}</style>\n</head>\n<body>\n")
