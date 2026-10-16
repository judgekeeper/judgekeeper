"""The look every page judgekeeper serves shares: the logo, the fonts, the colours (light by
default, dark only when the person picks it with the switch in the top bar), the top bar and
the focus ring.

The fonts (Manrope and JetBrains Mono, both under the SIL Open Font License) are embedded as
base64 from this package's `fonts/` folder, so a page loads nothing from anywhere else. The
dark colours are their own (black page, #111 cards, white text): no filter turns the light
page round. The choice is kept in the browser's storage under `jk-theme`, read before the page
is drawn so it never flashes white; a browser that blocks the storage shows light.
"""

from __future__ import annotations

import base64
import hashlib
from functools import lru_cache
from importlib import resources

SANS, MONO = "Manrope", "JetBrains Mono"
FONTS = (("manrope-latin-wght-normal.woff2", SANS, "200 800"),
         ("jetbrains-mono-latin-400-normal.woff2", MONO, "400"))
FONT_LICENCES = ("OFL-Manrope.txt", "OFL-JetBrainsMono.txt")
NAVY, GREEN = "#1E293B", "#10B981"  # the logo's two halves: the judge and the person
SLATE = "#64748B"  # the judge's half in dark

# The logo: the paths of the website's logo.svg. In dark its left half is slate, so it shows on
# black.
SHIELD = ('<svg viewBox="0 0 64 72" aria-hidden="true" focusable="false">'
          f'<path class="l" d="M32 3 L5 12 V34 C5 51 17 63 32 69 Z" fill="{NAVY}"/>'
          f'<path d="M32 3 L59 12 V34 C59 51 47 63 32 69 Z" fill="{GREEN}"/>'
          '<path d="M18 36 L28 46 L47 25" fill="none" stroke="#FFFFFF" stroke-width="6" '
          'stroke-linecap="round" stroke-linejoin="round"/></svg>')
LOGO = f'<span class="logo-tile">{SHIELD}</span>'
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


# The colours. Light is the default; dark has its own values. Red and green colour only Fail
# and Pass (and the logo and thin accent lines); amber marks a weak number. Light is the
# mirror of dark: white page, black text, black buttons.
TOKENS = """
:root { color-scheme: light;
  --paper: #FFFFFF; --sheet: #F5F5F5; --tint: #EDEDED; --tint-2: #F0F0F0; --chip: #FAFAFA;
  --ink: #000000; --ink-2: #1F1F1F; --ink-3: #4D4D4D;
  --rule: #D9D9D9; --rule-2: #E6E6E6; --rule-3: #C7C7C7; --track: #DDDDDD; --dash: #A6A6A6;
  --accent: #000000; --accent-2: #1F1F1F; --accent-bg: #EBEBEB; --accent-line: #BDBDBD;
  --mark-line: #10B981;
  --btn: #000000; --btn-hover: #1F1F1F; --btn-active: #333333; --on-btn: #FFFFFF;
  --pass: #1F6B4A; --pass-bg: #EEF6F1; --pass-line: #3D9A6A; --pass-dot: #E3EFE8;
  --pass-on: #1F6B4A; --pass-kbd: #EAF3EE; --pass-kbd-line: #A9D2BC;
  --fail: #9E3A2E; --fail-bg: #FDF1EF; --fail-line: #D27A6E; --fail-dot: #FBE9E6;
  --fail-on: #9E3A2E; --fail-kbd: #FFF6F5; --fail-kbd-line: #D9A9A2;
  --amber: #8A5213; --amber-solid: #D98B3A; --amber-bg: #FBF1E6; --amber-line: #EACDAB;
  --amber-band: #F3DFC4; --good-band: #C7C7C7;
  --blue: #4D4D4D; --blue-solid: #4D4D4D; --blue-bg: #F0F0F0; --blue-line: #D0D0D0;
  --logo-l: #1E293B; --focus: #000000; --scrim: rgba(0,0,0,.45);
  --shadow: 0 1px 2px rgba(0,0,0,.06);
  --shadow-lg: 0 24px 56px rgba(0,0,0,.12), 0 2px 6px rgba(0,0,0,.06);
  --sans: "Manrope", system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  --mono: "JetBrains Mono", ui-monospace, Menlo, Consolas, monospace; }
:root[data-theme="dark"] { color-scheme: dark;
  --paper: #000000; --sheet: #111111; --tint: #1A1A1A; --tint-2: #161616; --chip: #0A0A0A;
  --ink: #FFFFFF; --ink-2: #E6E6E6; --ink-3: #B3B3B3;
  --rule: #2A2A2A; --rule-2: #222222; --rule-3: #3A3A3A; --track: #2A2A2A; --dash: #555555;
  --accent: #FFFFFF; --accent-2: #E6E6E6; --accent-bg: #1F1F1F; --accent-line: #4A4A4A;
  --mark-line: #FFFFFF;
  --btn: #FFFFFF; --btn-hover: #E6E6E6; --btn-active: #CCCCCC; --on-btn: #000000;
  --pass: #6FCF9B; --pass-bg: #0E1C14; --pass-line: #3D9A6A; --pass-dot: #12291C;
  --pass-on: #1E7A4E; --pass-kbd: #12291C; --pass-kbd-line: #3D9A6A;
  --fail: #FF8A7A; --fail-bg: #1C0F0D; --fail-line: #A8483B; --fail-dot: #2A1412;
  --fail-on: #B4473A; --fail-kbd: #2A1412; --fail-kbd-line: #A8483B;
  --amber: #F0B45A; --amber-solid: #E09A45; --amber-bg: #2A2010; --amber-line: #6E5020;
  --amber-band: #5C4219; --good-band: #3A3A3A;
  --blue: #B3B3B3; --blue-solid: #B3B3B3; --blue-bg: #1A1A1A; --blue-line: #3A3A3A;
  --logo-l: #64748B; --focus: #FFFFFF; --scrim: rgba(0,0,0,.7);
  --shadow: 0 1px 2px rgba(0,0,0,.6);
  --shadow-lg: 0 24px 56px rgba(0,0,0,.7), 0 2px 6px rgba(0,0,0,.5); }
"""

# What every page shares beyond the colours. Focus rings are solid and sit on the edge
# (no offset), so no ring ever shows a white gap.
BASE = """
* { box-sizing: border-box; }
[hidden] { display: none !important; }
html, body { margin: 0; }
body { background: var(--paper); color: var(--ink); font: 500 15px/1.5 var(--sans);
  -webkit-font-smoothing: antialiased; }
a { color: var(--accent); }
a:hover { color: var(--accent-2); }
button { font: inherit; color: inherit; cursor: pointer; }
code, kbd { font-family: var(--mono); }
code { font-size: 12.5px; padding: 1px 5px; border-radius: 4px; background: var(--chip);
  color: var(--ink); overflow-wrap: anywhere; }
:focus { outline: none; }
:focus-visible { outline: 2px solid var(--focus); outline-offset: 0; }
.sr { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0);
  white-space: nowrap; }
.top { display: grid; grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr);
  align-items: center; gap: 16px; padding: 10px 24px; background: var(--sheet);
  border-bottom: 1px solid var(--rule); }
.top .left { min-width: 0; display: flex; justify-content: flex-start; }
.top .right { min-width: 0; display: flex; align-items: center; justify-content: flex-end;
  flex-wrap: wrap; gap: 14px; }
.chips { display: inline-flex; align-items: center; flex-wrap: wrap; gap: 6px 14px;
  padding: 6px 12px; border: 1px solid var(--rule); border-radius: 9px; background: var(--tint);
  min-width: 0; max-width: 100%; }
.chips > span { display: inline-flex; align-items: center; gap: 6px; min-width: 0; }
.chips .k { font-size: 11px; font-weight: 700; color: var(--ink-3); text-transform: uppercase;
  letter-spacing: .6px; flex: none; }
.chips .v { font-family: var(--mono); font-size: 13px; color: var(--ink); white-space: nowrap;
  overflow: hidden; text-overflow: ellipsis; max-width: 260px; }
.chips .sep { width: 1px; height: 16px; background: var(--rule); }
.brand { display: flex; align-items: center; gap: 10px; color: var(--ink); justify-self: center;
  font-size: 20px; font-weight: 800; letter-spacing: -.4px; }
.logo-tile { display: inline-flex; align-items: center; justify-content: center; flex: none;
  width: 30px; height: 30px; border-radius: 8px; }
.logo-tile svg { width: 25px; height: 28px; }
:root[data-theme="dark"] .logo-tile .l { fill: var(--logo-l); }
.theme { width: 36px; height: 36px; border-radius: 8px; border: 1px solid var(--rule);
  background: var(--sheet); color: var(--ink-3); display: inline-flex; align-items: center;
  justify-content: center; padding: 0; flex: none; }
.theme svg { width: 16px; height: 16px; fill: none; stroke: currentColor; stroke-width: 2;
  stroke-linecap: round; }
.theme .sun { display: none; }
:root[data-theme="dark"] .theme .sun { display: block; }
:root[data-theme="dark"] .theme .moon { display: none; }
.card { background: var(--sheet); border: 1px solid var(--rule); border-radius: 14px;
  box-shadow: var(--shadow); }
.head { display: flex; align-items: center; gap: 10px; padding: 12px 16px;
  border-bottom: 1px solid var(--rule-2); }
.head h2, .head .title { margin: 0; font-size: 13px; font-weight: 800; flex: 1 1 auto; }
.ic { width: 26px; height: 26px; border-radius: 7px; background: var(--chip); color: var(--ink-3);
  display: inline-flex; align-items: center; justify-content: center; flex: none; }
.ic.green { background: var(--accent-bg); color: var(--accent); }
.ic.amber { background: var(--amber-bg); color: var(--amber); }
.ic svg { width: 14px; height: 14px; fill: none; stroke: currentColor; stroke-width: 2.2;
  stroke-linecap: round; stroke-linejoin: round; }
@media (max-width: 600px) {
  .top { grid-template-columns: minmax(0, 1fr) auto; padding: 10px 16px; }
  .top .left { grid-column: 1 / -1; grid-row: 2; }
  .brand { justify-self: start; grid-column: 1; grid-row: 1; }
  .top .right { grid-column: 2; grid-row: 1; }
}
@media (prefers-reduced-motion: reduce) { * { transition: none !important;
  animation: none !important; scroll-behavior: auto !important; } }
"""

# Read before the page is drawn: the theme the person picked, else light.
THEME_FIRST = ("try { if (window.localStorage.getItem(\"jk-theme\") === \"dark\") { "
               "document.documentElement.setAttribute(\"data-theme\", \"dark\"); } } "
               "catch (e) { /* storage blocked: light */ }")

# The switch: dark or light, remembered when the browser allows it.
THEME_SWITCH = """
  (function () {
    var root = document.documentElement, b = document.getElementById("theme");
    function sync() { b.setAttribute("aria-pressed", String(root.getAttribute("data-theme") ===
      "dark")); }
    b.addEventListener("click", function () {
      var dark = root.getAttribute("data-theme") !== "dark";
      if (dark) { root.setAttribute("data-theme", "dark"); }
      else { root.removeAttribute("data-theme"); }
      try { window.localStorage.setItem("jk-theme", dark ? "dark" : "light"); }
      catch (e) { /* not remembered */ }
      sync();
    });
    sync();
  })();
"""

SWITCH = ('<button type="button" class="theme" id="theme" aria-label="Dark mode" '
          'aria-pressed="false"><svg class="moon" viewBox="0 0 24 24" aria-hidden="true" '
          'focusable="false"><path d="M21 12.8A9 9 0 1 1 11.2 3 7 7 0 0 0 21 12.8Z"/></svg>'
          '<svg class="sun" viewBox="0 0 24 24" aria-hidden="true" focusable="false">'
          '<circle cx="12" cy="12" r="4.2"/><path d="M12 2.5v2.2M12 19.3v2.2M2.5 12h2.2M19.3 '
          '12h2.2M5.3 5.3l1.6 1.6M17.1 17.1l1.6 1.6M5.3 18.7l1.6-1.6M17.1 6.9l1.6-1.6"/>'
          '</svg></button>')


def script_hash(script: str) -> str:
    """The CSP source that lets exactly this inline script run."""
    digest = base64.b64encode(hashlib.sha256(script.encode("utf-8")).digest()).decode("ascii")
    return f"'sha256-{digest}'"


def chips(judge: str | None, tool: str | None) -> str:
    """The top bar's left: the judge's model and the eval tool (escaped text)."""
    parts = []
    if judge:
        parts.append(f'<span><span class="k">Judge:</span><span class="v" title="{judge}">'
                     f'{judge}</span></span>')
    if tool:
        parts.append(f'<span><span class="k">Eval tool:</span><span class="v">{tool}</span>'
                     '</span>')
    if not parts:
        return ""
    return '<div class="chips">' + '<span class="sep" aria-hidden="true"></span>'.join(parts) + \
        "</div>"


def top(left: str, right: str) -> str:
    """The top bar: the judge and tool left, the logo and name centred, the page's state and
    the theme switch right."""
    return (f'<header class="top"><div class="left">{left}</div>{BRAND}'
            f'<div class="right">{right}{SWITCH}</div></header>')


def head(title: str, style: str, script: str, meta: str = "") -> str:
    """The page up to <body>: `script` is the opening tag of the theme script (with its nonce,
    or plain where a hash lets it run)."""
    return ("<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
            f"{meta}<title>{title}</title>\n{script}{THEME_FIRST}</script>\n"
            f"<style>{font_faces()}\n{TOKENS}{BASE}{style}</style>\n</head>\n<body>\n")
