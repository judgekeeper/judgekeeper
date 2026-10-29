"""The look every page shares, and the parts of each page the design pins.

- The frame: the head lines, the menu and the footer that scripts/site_frame.py writes.
- Dark only: the product's dark colours, no switch, no light rules, nothing kept in the browser.
- Fonts from the site only: Manrope and JetBrains Mono with their licences; no ligatures in
  monospace, so "->" shows as typed.
- Motion: only the few moving parts the design names, and none of them under reduced motion.
- Phone: tables and code scroll inside their box; the browser check's lines wrap.
- Each page's own parts: Home, the Guide, the browser check and Privacy.

The tests run no JavaScript: the pages were checked in Chrome at 1440 and 390 wide.
"""

from __future__ import annotations

import importlib.util
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from judgekeeper import fix
from tests.website_pages import (
    GITHUB,
    LEGAL,
    NAV,
    ROOT,
    WEBSITE,
    Element,
    pages,
    parse,
)

HOME = WEBSITE / "index.html"
GUIDE = WEBSITE / "start.html"
PRIVACY = WEBSITE / "privacy.html"
CHECK = WEBSITE / "check.html"
NOT_FOUND = WEBSITE / "errors" / "404.html"
CSS = (WEBSITE / "assets" / "style.css").read_text(encoding="utf-8")
JS = (WEBSITE / "assets" / "site.js").read_text(encoding="utf-8")
FONTS = WEBSITE / "assets" / "fonts"
PACKAGE_FONTS = ROOT / "src" / "judgekeeper" / "fonts"


def _frame():
    spec = importlib.util.spec_from_file_location("site_frame", ROOT / "scripts/site_frame.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _els(page: Path) -> list[Element]:
    return list(parse(page).iter())


def _by_id(page: Path, wanted: str) -> Element:
    return next(el for el in _els(page) if el.attrs.get("id") == wanted)


def _all(root: Element, tag: str, cls: str | None = None) -> list[Element]:
    return [el for el in root.iter() if el.tag == tag and (cls is None or cls in el.classes())]


def _flat(el: Element) -> str:
    """The text of an element as it reads: a line break counts as a space."""
    parts = [c if isinstance(c, str) else " " if c.tag == "br" else _flat(c)
             for c in el.children]
    return " ".join("".join(parts).split())


def _rule(selector: str, css: str = CSS) -> str:
    """The declarations of the first rule for `selector` (written `selector { ... }`)."""
    start = css.index(selector + " {")
    return css[start + len(selector) + 2:css.index("}", start)]


def _phone(css: str = CSS) -> str:
    """Every rule inside the phone blocks (`@media (max-width: 760px)`), one after another."""
    return _narrow(760, css)


def _narrow(width: int, css: str = CSS) -> str:
    """Every rule inside the narrow-screen blocks (`@media (max-width: <width>px)`)."""
    inside, at = [], 0
    while (at := css.find(f"@media (max-width: {width}px) {{", at)) != -1:
        depth, open_at = 0, css.index("{", at)
        for i in range(open_at, len(css)):
            depth += {"{": 1, "}": -1}.get(css[i], 0)
            if not depth:
                break
        inside.append(css[open_at + 1:i])
        at = i
    return "\n".join(inside)


def _wide(width: int = 1100, css: str = CSS) -> str:
    """Every rule inside the wide-screen blocks (`@media (min-width: <width>px)`)."""
    inside, at = [], 0
    while (at := css.find(f"@media (min-width: {width}px) {{", at)) != -1:
        depth, open_at = 0, css.index("{", at)
        for i in range(open_at, len(css)):
            depth += {"{": 1, "}": -1}.get(css[i], 0)
            if not depth:
                break
        inside.append(css[open_at + 1:i])
        at = i
    return "\n".join(inside)


def _outside_media(css: str = CSS) -> str:
    """The rules that apply at every width: the CSS without its @media blocks."""
    while (at := css.find("@media")) != -1:
        depth, open_at = 0, css.index("{", at)
        for i in range(open_at, len(css)):
            depth += {"{": 1, "}": -1}.get(css[i], 0)
            if not depth:
                break
        css = css[:at] + css[i + 1:]
    return css


def _rules(css: str = CSS) -> list[tuple[str, str]]:
    """(selector, declarations) for every rule, those inside @media included."""
    inner = re.sub(r"@media[^{]*\{", "", css)
    return [(s.strip(), d) for s, d in re.findall(r"([^{}]+)\{([^{}]*)\}", inner)]


# The frame -------------------------------------------------------------------------------

def test_every_page_carries_the_frame_site_frame_writes():
    frame = _frame()
    assert frame.NAV == NAV and frame.LEGAL == LEGAL and frame.GITHUB == GITHUB
    for page in pages():
        text = page.read_text(encoding="utf-8")
        for block in (frame.head_links(), frame.script(), frame.header(page.name), frame.footer()):
            assert block in text, f"{page.name}: run python scripts/site_frame.py"


def test_the_menu_is_home_the_guide_the_logo_and_github():
    for page in pages():
        (header,) = _all(parse(page), "header", "menu")
        (nav,) = _all(header, "nav", "menu-l")
        assert [(a.attrs["href"], a.text().strip()) for a in _all(nav, "a")] == NAV, page.name
        (brand,) = _all(header, "a", "brand")
        assert brand.attrs["href"] == "index.html" and _flat(brand) == "judgekeeper"
        assert _all(brand, "svg", "logo"), page.name
        (github,) = _all(header, "a", "gh")
        assert (github.attrs["href"], _flat(github)) == (GITHUB, "GitHub"), page.name
        assert not _all(header, "button"), f"{page.name}: no theme switch, no menu button"


def test_the_footer_is_the_logo_the_legal_links_and_the_copyright():
    for page in [*pages(), NOT_FOUND]:
        (footer,) = _all(parse(page), "footer", "foot")
        (brand,) = [el for el in footer.iter() if "brand" in el.classes()]
        assert _flat(brand) == "judgekeeper" and _all(brand, "svg", "logo"), page.name
        (links,) = [el for el in footer.iter() if "foot-r" in el.classes()]
        assert links.attrs.get("role") == "navigation", page.name  # a nav would get menu styles
        found = [(a.attrs["href"].lstrip("/"), _flat(a)) for a in _all(links, "a")]
        assert found == [*LEGAL, (f"{GITHUB}/blob/main/LICENSE", "Apache-2.0 license")], page.name
        (copy,) = _all(links, "span", "copy")
        assert _flat(copy) == "© 2026 Sathvik Thota · Apache-2.0 license", page.name
        assert not _all(footer, "h2") and "More" not in _flat(footer), page.name


def test_the_footer_names_match_the_licence():
    assert "Copyright 2026 Sathvik Thota" in (ROOT / "NOTICE").read_text(encoding="utf-8")
    for path in ("TRADEMARKS.md", "SECURITY.md", "LICENSE", "NOTICE"):
        assert (ROOT / path).is_file(), path


# Fonts: from the site only -----------------------------------------------------------------

def _font_faces() -> list[dict[str, str]]:
    faces = []
    for body in re.findall(r"@font-face\s*\{(.*?)\}", CSS, flags=re.DOTALL):
        pairs = (line.split(":", 1) for line in body.split(";") if ":" in line)
        faces.append({k.strip(): v.strip() for k, v in pairs})
    return faces


def test_the_fonts_are_manrope_and_jetbrains_mono_served_by_the_site():
    seen = set()
    for face in _font_faces():
        family = face["font-family"].strip("\"'")
        (src,) = re.findall(r"url\(([^)]+)\)", face["src"])
        assert src.startswith("fonts/") and src.endswith(".woff2"), src
        assert (WEBSITE / "assets" / src).is_file(), src
        assert face["font-display"] == "swap", family
        seen.add((family, face["font-weight"], src.removeprefix("fonts/")))
    assert seen == {("Manrope", "200 800", "manrope-latin-wght-normal.woff2"),
                    ("JetBrains Mono", "400", "jetbrains-mono-latin-400-normal.woff2"),
                    ("JetBrains Mono", "500", "jetbrains-mono-latin-500-normal.woff2")}
    assert {p.name for p in FONTS.iterdir()} == {
        "manrope-latin-wght-normal.woff2", "jetbrains-mono-latin-400-normal.woff2",
        "jetbrains-mono-latin-500-normal.woff2", "OFL-Manrope.txt", "OFL-JetBrainsMono.txt"}
    for name in ("manrope-latin-wght-normal.woff2", "jetbrains-mono-latin-400-normal.woff2",
                 "jetbrains-mono-latin-500-normal.woff2", "OFL-Manrope.txt",
                 "OFL-JetBrainsMono.txt"):  # the same files the product pages embed
        assert (FONTS / name).read_bytes() == (PACKAGE_FONTS / name).read_bytes(), name
    for licence, family in (("Manrope", "Manrope"), ("JetBrainsMono", "JetBrains Mono")):
        text = (FONTS / f"OFL-{licence}.txt").read_text(encoding="utf-8")
        assert "SIL Open Font License" in text and family in text, licence
    assert '--sans: "Manrope",' in _rule(":root") and '--mono: "JetBrains Mono",' in _rule(":root")
    assert _frame().FONTS == ("manrope-latin-wght-normal.woff2",)  # preloaded: the text font


def test_no_page_or_asset_asks_another_server_for_anything():
    files = [*pages(), NOT_FOUND, *(WEBSITE / "assets").glob("*.css"),
             *(WEBSITE / "assets").glob("*.js")]
    for path in files:
        text = path.read_text(encoding="utf-8")
        for host in ("fonts.googleapis", "fonts.gstatic", "cdn.", "unpkg", "googletagmanager",
                     "Bricolage"):
            assert host not in text, (path.name, host)
        if path.suffix == ".html":
            for el in parse(path).iter():
                for attr in ("src", "href"):
                    url = el.attrs.get(attr, "")
                    if el.tag in {"link", "script", "img"} and url:
                        assert not re.match(r"(https?:)?//", url), (path.name, url)
    for url in re.findall(r"url\(([^)]+)\)", CSS):
        assert not re.match(r"['\"]?(https?:)?//", url), url


def test_monospace_text_shows_what_you_type():
    """JetBrains Mono joins "->", "=>" and ">=" into one sign; a command must show both
    characters. Every rule that sets the mono font turns ligatures off."""
    mono = [(s, d) for s, d in _rules() if "var(--mono)" in d and "--mono:" not in d]
    assert len(mono) > 10
    for selector, declarations in mono:
        assert "font-variant-ligatures: none" in declarations, selector
    base = _rule("code, pre, kbd, samp")
    assert "var(--mono)" in base and "font-variant-ligatures: none" in base


# Dark only ---------------------------------------------------------------------------------

DARK = {"bg": "#0b0c0e", "fg": "#e6e8eb", "muted": "#8b919a", "faint": "#767c86",
        "line": "#262a30", "hover": "#121418", "current": "#17191e", "panel": "#0b0c0e",
        "rule": "#343941", "term-bg": "#07080a", "term-bar": "#101215", "term-dot": "#33373e",
        "green": "#10B981", "green-fill": "#047857", "red": "#e5484d", "red-fill": "#c73b40"}


def _tokens() -> dict[str, str]:
    return dict(re.findall(r"--([a-z0-9-]+):\s*(#[0-9A-Fa-f]{6})", _rule(":root")))


def test_the_site_is_dark_only_with_the_products_colours():
    assert "color-scheme: dark" in _rule(":root")
    assert _tokens() == DARK
    for path in [*pages(), NOT_FOUND, *(WEBSITE / "assets").glob("*.css"),
                 *(WEBSITE / "assets").glob("*.js")]:
        text = path.read_text(encoding="utf-8")
        for gone in ("prefers-color-scheme", "data-theme", "jk-theme", "theme.js",
                     "localStorage", "sessionStorage"):
            assert gone not in text, (path.name, gone)
    assert CSS.count(":root {") == 1  # one set of colours


def _contrast(a: str, b: str) -> float:
    def lum(colour: str) -> float:
        rgb = [int(colour[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
        return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]
    hi, lo = sorted((lum(a), lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def test_text_colours_meet_wcag_aa():
    """Body text and white on the green and red buttons 4.5 to 1 on every ground it sits on;
    the green underline 3 to 1. The small labels use the muted colour, not the faint one."""
    t = _tokens()
    for text in ("fg", "muted"):
        for ground in ("bg", "hover", "current"):
            assert _contrast(t[text], t[ground]) >= 4.5, (text, ground)
    assert _contrast(t["green"], t["bg"]) >= 3 and _contrast(t["faint"], t["bg"]) >= 2.9
    for fill in ("green-fill", "red-fill"):
        assert _contrast("#FFFFFF", t[fill]) >= 4.5, fill
    assert "var(--faint)" not in CSS
    # a hover brightens the fill a little, so white text keeps its contrast
    assert "filter: brightness(1.08)" in _rule(".jk-pass:hover")


def test_keyboard_focus_shows_a_soft_ring_and_a_click_leaves_none():
    assert "outline: none" in _rule(":focus")
    ring = _rule(":focus-visible")
    assert "outline: 2px solid var(--fg)" in ring and "border-radius: 4px" in ring
    assert "border-radius: 12px" in _rule(".jk-card:focus-visible")
    # the five words show focus with their own green line, so no ring around them
    assert "outline: none" in _rule(".five a:focus-visible")
    assert ".five a:focus-visible::after" in CSS
    # the one ring is in the text colour; no other focus rule brings back a white box
    assert [s for s, d in _rules() if "focus" in s and "var(--fg)" in d] == [":focus-visible"]
    assert ".skip:focus" in CSS


# Motion ------------------------------------------------------------------------------------

COLOUR_ONLY = {"color", "background", "background-color", "border-color", "filter",
               "text-decoration-color"}


def test_the_only_motion_is_the_underline_the_typing_and_the_count_up():
    """Hover colours may fade; nothing else moves, slides, turns or appears by itself. The green
    line under the five words grows, a click on a word scrolls to the steps, the public-dataset
    tiles grow a green line on hover and their numbers count up once, and the browser check's
    example cards lift 1px on hover (not under reduced motion)."""
    # one animation: the browser check's cursor blinks while it waits for a file
    assert re.findall(r"@keyframes ([\w-]+)", CSS) == ["ck-blink"]
    assert re.findall(r"animation:\s*([^;]+);", CSS.replace("animation: none !important", "")) == [
        "ck-blink 1.1s steps(1) infinite"]
    for selector, declarations in _rules():
        for value in re.findall(r"transition:\s*([^;]+)", declarations):
            if value.startswith("none"):
                continue
            props = {part.split()[0] for part in value.split(",")}
            if selector.endswith(".five a::after"):  # the selector may follow a comment
                assert value == "transform 240ms ease"
                continue
            if selector.endswith(".rt::before"):
                assert value == "transform 300ms ease"
                continue
            if selector.endswith(".ex-card"):
                assert value == "border-color 140ms ease, transform 140ms ease"
                continue
            assert props <= COLOUR_ONLY, (selector, value)
    reduce = CSS[CSS.index("@media (prefers-reduced-motion: reduce)"):]
    assert "*, *::before, *::after { transition: none !important" in reduce[:200]
    # the two moving parts, and both stop under reduced motion
    assert JS.count("prefers-reduced-motion: reduce") == 1
    assert "function type(" in JS and "function sweep(" in JS
    assert 'if (!nums.length || reduce || !("IntersectionObserver" in window)) return;' in JS
    assert JS.count("smooth") == 1 and 'behavior: reduce ? "auto" : "smooth"' in JS
    for gone in ("IntersectionObserver(function (e) { reveal", "animate(", "count-up",
                 "parallax", "pointermove"):
        assert gone not in JS, gone


def test_each_screen_types_once_and_replay_types_it_again():
    typing = JS[JS.index("function type("):]
    assert "if (reduce || !animate)" in typing  # at once: reduced motion, or seen before
    assert "seen[key]" in JS and 'replay.addEventListener("click"' in JS


# Phone -------------------------------------------------------------------------------------

def test_tables_and_code_scroll_inside_their_box():
    for page in pages():
        for table in _all(parse(page), "table"):
            assert "tw" in table.parent.classes(), page.name
    assert "overflow-x: auto" in _rule(".tw")
    assert "overflow: auto" in _rule(".term-out")
    assert "overflow-x: auto" in _rule(".gx-code")
    assert "overflow-x: auto" in _rule(".cmd code")
    assert "@media (max-width: 760px)" in CSS and "@media (max-width: 860px)" in CSS
    for page in [*pages(), NOT_FOUND]:
        (meta,) = [el for el in parse(page).iter() if el.attrs.get("name") == "viewport"]
        assert meta.attrs["content"] == "width=device-width, initial-scale=1", page.name


def _sizes(declarations: str) -> list[float]:
    return [float(n) for n in re.findall(r"font(?:-size)?:[^;]*?([\d.]+)px", declarations)]


def _phone_rules() -> list[tuple[str, str]]:
    """(selector, declarations) for every rule in a block for screens 760px wide or less, one
    pair per selector of a list."""
    widths = {int(w) for w in re.findall(r"@media \(max-width: (\d+)px\)", CSS)}
    css = "".join(_narrow(w) for w in widths if w <= 760)
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
    return [(one.strip(), d) for s, d in _rules(css) for one in s.split(",")]


def test_on_a_phone_a_long_command_wraps_inside_its_box():
    """At 600px and below a command wraps (at a space, after a "/", or anywhere) instead of
    running past the box's edge; Copy still copies it on one line. Handy commands put each
    comment under its command, and the record() line wraps too."""
    phone = _narrow(600)
    for selector in (".cmd code", ".gx-code"):
        rule = _rule(selector, phone)
        assert "white-space: pre-wrap" in rule and "overflow-wrap: anywhere" in rule, selector
    assert "display: block" in _rule(".gm-pre .t-dim", phone)
    (path,) = [c for c in _all(parse(GUIDE), "code") if "path/" in c.text()]
    assert len(_all(path, "wbr")) == 2 and path.text() == "judgekeeper path/to/results.json"
    (record,) = [c for c in _all(parse(GUIDE), "code") if "record(" in c.text()]
    assert len(_all(record, "wbr")) == 1  # it breaks after "record(", not inside a word
    assert "code.textContent" in JS  # what Copy copies: the text, never a break


def test_on_a_phone_the_demo_terminal_wraps_and_fits_its_text():
    """At 600px and below the demo's lines wrap at 12px, and the box is as tall as the screen
    it shows; on a laptop the box keeps its height."""
    rule = _rule(".term-out", _narrow(600))
    for part in ("white-space: pre-wrap", "overflow-wrap: anywhere", "height: auto"):
        assert part in rule, part
    assert "font-size: 12px" in _rule(".term-out", _phone())
    assert "height: calc(29 * 1.55em + 40px)" in _rule(".term-out")
    mid = CSS[CSS.index("@media (max-width: 1100px) {"):]
    assert "font-size: 12px" in _rule(".term-out", mid[:mid.index("\n}\n")])


def test_on_a_phone_no_text_is_smaller_than_12px():
    """No phone rule sets text under 12px, and every size under 12px is raised on a phone."""
    phone = _phone_rules()
    assert not [(s, d) for s, d in phone if any(n < 12 for n in _sizes(d))]
    small = [s for s, d in _rules(_outside_media()) if any(n < 12 for n in _sizes(d))]
    assert small
    raised = {s for s, d in phone if _sizes(d)}
    assert not [s for s in small if s not in raised]


def test_on_a_phone_every_link_and_button_is_44px_tall():
    """The links and buttons a person taps are 44px tall on a phone: the box itself, or a
    clear area around a word whose underline must stay close to it. Links inside a sentence
    are not counted."""
    phone = {}
    for selector, declarations in _phone_rules():
        phone[selector] = phone.get(selector, "") + declarations
    for selector in (".menu .brand", ".gh", ".foot-r a", ".g-nav a", ".term-replay",
                     ".term-tabs", ".fc-pick-list .btn", ".fc-clear"):
        assert "44px" in phone[selector], selector
    assert "padding: 12px 14px" in phone[".jk-sub button"]  # 21px of text + 24px
    for word in (".menu-l a", ".five a", ".tf-link", ".jk-again", ".gx-way-h a"):
        area = phone[word + "::before"]
        assert "position: absolute" in area and "height: 44px" in area, word


# Home --------------------------------------------------------------------------------------

DEMO = [["Can I return a lamp after 60 days?",
         "Of course! We accept returns at any time, no questions asked.", "pass"],
        ["Is there a student discount?",
         "Yes, 10% with a valid student email through our partner page.", "pass"],
        ["My lamp arrived broken. What now?",
         ("Sorry about that. Reply with a photo and your order number, and we will send a free "
         "replacement."), "fail"],
        ["Do you ship to Canada?",
         "Yes, in 5 to 8 working days. Duties are included at checkout.", "pass"]]
# Each step starts with what you do, in a few plain words
STEPS = [("find", "Find", "Find your eval results and the LLM-as-a-judge that graded them."),
         ("mark", "Mark", "Mark your answers Pass or Fail in your browser."),
         ("measure", "Measure", "See how often your LLM-as-a-judge agrees with you."),
         ("fix", "Fix", "Write a better rule and test it on marks kept aside."),
         ("check", "Re-check", "Change your LLM-as-a-judge and see if it still agrees with you.")]


def _main(page: Path) -> Element:
    return next(el for el in _els(page) if el.tag == "main")


def test_home_is_the_hero_the_steps_the_public_datasets_and_the_closing_box():
    sections = [el for el in _main(HOME).children if isinstance(el, Element)]
    assert [s.classes() for s in sections] == [{"hero"}, {"steps"}, {"real"}, {"close"}]


def test_the_demo_card_keeps_one_height():
    """The card is as tall as its tallest answer or its end card, measured on load, when the
    fonts arrive and on resize, so nothing below it moves while you mark (checked in Chrome at
    1440, 1000 and 390 wide: the same height for every answer and the end card)."""
    lock = JS[JS.index("function lockHeight("):]
    lock = lock[:lock.index("\n    }\n")]
    assert "items.forEach" in lock and 'classList.add("is-end")' in lock
    assert "fillList(" in lock  # the end card is measured with its list filled
    assert 'card.style.minHeight = tallest + "px"' in lock
    assert 'addEventListener("resize"' in JS and "document.fonts.ready.then(lockHeight)" in JS
    # the room the card gets sits under the answer, or around the end card
    assert "flex: 1" in _rule(".jk-live") and "flex: 1" in _rule(".jk-row-a")
    assert "flex: 1" in _rule(".jk-card.is-end .jk-end")


def test_the_hero_is_the_headline_the_five_words_two_buttons_and_the_demo():
    hero = _all(_main(HOME), "section", "hero")[0]
    (h1,) = _all(hero, "h1")
    assert _flat(h1) == "Check your LLM-as-a-judge in 5 steps."
    (five,) = _all(hero, "nav", "five")
    words = [(a.attrs["href"], a.attrs["data-step"], _flat(a)) for a in _all(five, "a")]
    assert words == [("#steps", key, f"{label}.") for key, label, _ in STEPS]
    buttons = [(a.attrs["href"], a.classes(), _flat(a)) for a in _all(hero, "a")
               if {"b-main", "b-side"} & a.classes()]
    assert buttons == [("start.html", {"b-main"}, "Get started"),
                       ("check.html", {"b-side"}, "Try step 1 in your browser")]
    assert not _all(hero, "p", None) or all(
        any("jk-card" in a.classes() for a in p.ancestors()) for p in _all(hero, "p"))
    # the chosen step's green line, which gives way while another word is hovered or focused
    assert "var(--green)" in _rule(".five a::after")
    assert ".five a.is-on::after" in CSS and ".five:hover a.is-on:not(:hover)::after" in CSS


def test_the_demo_card_is_drawn_like_the_marking_page():
    demo = _by_id(HOME, "demo")
    assert demo.attrs.get("aria-label") == "Live demo of the marking page"
    labels = [_flat(el) for el in demo.iter() if "jk-label" in el.classes()]
    assert labels == ["Question", "Answer", "Your result"]
    assert _flat(_by_id(HOME, "d-state")) == "0 of 4 marked"
    assert _by_id(HOME, "d-state").attrs.get("aria-live") == "polite"
    assert [_flat(_by_id(HOME, i)) for i in ("d-fail", "d-pass", "d-skip", "d-undo")] == [
        "Fail ←", "Pass →", "Skip this one S", "Undo Z"]
    # Without JavaScript the card shows the first answer.
    assert [_flat(_by_id(HOME, "d-q")), _flat(_by_id(HOME, "d-a"))] == DEMO[0][:2]
    data = _by_id(HOME, "demo-items")
    assert data.tag == "script" and data.attrs.get("type") == "application/json"
    assert json.loads(data.text()) == DEMO
    # The end card reads like a result: the label and "Try again" on top, the result line,
    # one row per answer (your mark, the LLM-as-a-judge's grade), the button alone below.
    end = _by_id(HOME, "d-end")
    (top,) = _all(end, "div", "jk-end-top")
    assert [c.attrs.get("id") or _flat(c) for c in top.children if not isinstance(c, str)] == [
        "Your result", "d-again"]
    (sum_line,) = _all(end, "h2")
    assert sum_line.attrs.get("id") == "d-sum" and _flat(sum_line) == ""
    (rows,) = _all(end, "ul", "jk-end-list")
    assert rows.attrs.get("id") == "d-list"
    assert rows.attrs.get("aria-label") == "Your marks and the LLM-as-a-judge's grades"
    (actions,) = _all(end, "div", "jk-end-actions")
    (go,) = _all(actions, "a", "jk-go")
    assert (go.attrs["href"], _flat(go)) == ("start.html", "Check your own LLM-as-a-judge")
    assert [c for c in actions.children if not isinstance(c, str)] == [go]
    assert _flat(_by_id(HOME, "d-again")) == "↻ Try again"
    for words in ('"Marked "', '"Skipped · "', '" of "', '" marked"',
                  '"You and your LLM-as-a-judge disagreed on "',
                  '"You and your LLM-as-a-judge agreed on all "', '"LLM-as-a-judge"',
                  'ArrowLeft: "fail"', 'ArrowRight: "pass"'):
        assert words in JS, words
    for gone in ('"Not marked yet"', '"Skipped"', "your judge"):
        assert gone not in JS, gone
    # the count sits in a small pill; the result line keeps to one line on a desktop
    state = _rule(".jk-state")
    for wanted in ("border-radius: 999px", "font-variant-numeric: tabular-nums",
                   "font-size: 12.5px", "color: var(--fg)"):
        assert wanted in state, wanted
    assert "align-self: flex-start" in _rule(".jk-row-q .jk-state")
    assert "margin-bottom: 22px" in _rule(".jk-end-top")
    assert "font-size: clamp(16px, 1.6vw, 20px)" in _rule(".jk-end-head h2")
    assert "white-space: nowrap" in _rule(".jk-end-head h2 .mono")
    assert "@media (min-width: 1000px) { .jk-end-head h2 { white-space: nowrap; } }" in CSS
    assert "justify-content: center" in _rule(".jk-end-actions")
    # the judge's grade stays hidden while you mark, as on the real page
    assert "Your judge said" not in JS
    sizes = {"jk-question": "font-size: 26px", "jk-answer": "font-size: 20px",
             "jk-btn": "height: 50px"}
    for cls, size in sizes.items():
        assert size in _rule(f".{cls}"), cls


def test_the_steps_list_picks_a_screen_for_the_terminal():
    steps = _all(_main(HOME), "section", "steps")[0]
    assert steps.attrs.get("id") == "steps"
    assert _flat(_all(steps, "h2")[0]) == "What each step looks like."
    (tabs,) = _all(steps, "div", "steplist")
    assert (tabs.attrs.get("role"), tabs.attrs.get("aria-orientation")) == ("tablist", "vertical")
    buttons = _all(tabs, "button")
    assert [el for el in tabs.children if getattr(el, "tag", None)] == buttons  # tabs, no list
    found = [(b.attrs["data-step"], _flat(_all(b, "b")[0]), _flat(_all(b, "span", "d")[0]))
             for b in buttons]
    assert found == STEPS
    assert [b.attrs.get("aria-selected") for b in buttons] == [
        "true", "false", "false", "false", "false"]
    assert [b.attrs.get("tabindex") for b in buttons] == ["0", "-1", "-1", "-1", "-1"]
    assert [b.attrs.get("id") for b in buttons] == [f"tab-{s}" for s, *_ in STEPS]
    assert {b.attrs.get("role") for b in buttons} == {"tab"}
    assert {b.attrs.get("aria-controls") for b in buttons} == {"term"}
    (term,) = [el for el in steps.iter() if el.attrs.get("id") == "term"]
    assert (term.attrs.get("role"), term.attrs.get("aria-labelledby")) == ("tabpanel", "tab-find")
    assert _by_id(HOME, "t-out").attrs.get("tabindex") == "0"  # it scrolls: the keyboard can too
    for words in ('term.setAttribute("aria-labelledby", tab.id)', "b.tabIndex = b === chosen",
                  "ArrowDown", "ArrowUp", "Home: 0", "End: n - 1"):
        assert words in JS, words
    assert _flat(_all(term, "span", "term-title")[0]) == "example project"
    fix_tabs = _by_id(HOME, "t-tabs")
    assert "hidden" in fix_tabs.attrs
    assert [(_flat(b), b.attrs["data-screen"]) for b in _all(fix_tabs, "button")] == [
        ("First run", "fix"), ("Testing your rule", "fix_test")]
    assert _flat(_by_id(HOME, "t-replay")) == "Replay"
    fix_buttons = _all(fix_tabs, "button")
    assert [b.attrs.get("tabindex") for b in fix_buttons] == ["0", "-1"]
    # the terminal's own status bar says where it comes from; no grey line under the box
    assert not _all(steps, "p", "steps-more")
    (foot,) = _all(term, "div", "term-foot")
    (dot,) = _all(foot, "span", "tf-dot")
    assert dot.attrs.get("aria-hidden") == "true"
    assert _flat(_all(foot, "span", "tf-text")[0]) == "made-up answers · not a real project"
    (link,) = _all(foot, "a", "tf-link")
    assert (link.attrs["href"], _flat(link)) == ("examples/site-example/report.html",
                                                 "open its report")
    assert 'content: " ↗"' in _rule(".tf-link::after")
    assert "dashed" in _rule(".tf-link")
    bar = _rule(".term-foot")
    assert "height: 38px" in bar and "border-top: 1px solid var(--line)" in bar
    assert "background: var(--term-bar)" in bar and "font-size: 12px" in bar
    assert "min-height: 44px" in _rule(".term-foot", _phone())  # room for its link
    assert "white-space: normal" in _rule(".tf-text", _phone())  # never cut with "…"


def test_the_closing_box_points_to_the_browser_check():
    close = _all(_main(HOME), "section", "close")[0]
    assert _flat(_all(close, "h2")[0]) == "Have eval results?"
    assert _flat(_all(close, "p")[0]) == ("Check your LLM-as-a-judge. Your file stays on your "
                                          "computer.")
    (button,) = _all(close, "a", "b-main")
    assert (button.attrs["href"], _flat(button)) == ("check.html", "Try step 1 in your browser")


def test_the_closing_box_is_your_own_terminal_waiting_at_a_prompt():
    """A window like the others, titled "your project", with a green border and no glow; a
    "$" and a blinking cursor wait under the line, with the same space above it as above
    "On public datasets." (8 + 17 + 80 = 24 + 1 + 80 on a laptop, 8 + 17 + 56 on a phone)."""
    close = _all(_main(HOME), "section", "close")[0]
    (win,) = _all(close, "div", "close-win")
    (bar,) = _all(win, "div", "rt-bar")
    assert _flat(_all(bar, "span", "rt-title")[0]) == "your project"
    (prompt,) = _all(win, "p", "close-prompt")
    assert prompt.attrs.get("aria-hidden") == "true"
    assert _flat(_all(prompt, "span", "t-prompt")[0]) == "$"
    assert _all(prompt, "span", "ck-cursor")
    rule = _rule(".close-win")
    assert "border-radius: 12px" in rule and "var(--green)" in rule
    assert "box-shadow" not in rule
    assert "font-family: var(--mono)" in _rule(".close-win h2")
    assert "font-size: 26px" in _rule(".close-win h2")
    assert "padding-top: 17px" in _rule(".close")
    assert "padding: 24px 0 8px" in _rule(".real")
    assert "> " not in _flat(win)


def test_the_public_datasets_sit_in_a_window_of_two_linked_numbers():
    """"On public datasets.": a window titled "public datasets", two columns (one on a
    phone), mono text, a green number that counts up once (not under reduced motion), and a
    green line across the top on hover."""
    (real,) = _all(_main(HOME), "section", "real")
    assert _flat(_all(real, "h2")[0]) == "On public datasets."
    (win,) = _all(real, "div", "rt-win")
    (bar,) = _all(win, "div", "rt-bar")
    assert _flat(_all(bar, "span", "rt-title")[0]) == "public datasets"
    tiles = _all(win, "a", "rt")
    assert [_flat(_all(t, "span", "rt-src")[0]) for t in tiles] == ["JailbreakBench",
                                                                    "Real-data check"]
    assert [_flat(_all(t, "span", "rt-line")[0]) for t in tiles] == [
        "times TPR, TNR and kappa were all in judgekeeper's ranges at once",
        "times, on average over TPR and TNR, the true value was in judgekeeper's range"]
    for tile in tiles:
        assert not _flat(tile).startswith(">")
    assert "border-radius: 12px" in _rule(".rt-win")
    assert "repeat(2, minmax(0, 1fr))" in _rule(".rt-grid")
    narrow = CSS[CSS.index("@media (max-width: 560px) {\n  .real h2"):]
    assert _rule(".rt-grid", narrow).strip() == "grid-template-columns: 1fr;"
    assert "font-family: var(--mono)" in _rule(".rt")
    assert "color: var(--green)" in _rule(".rt-big")
    assert "scaleX(1)" in _rule(".rt:hover::before")
    assert "function setUpCounts()" in JS and "setUpCounts();" in JS


def test_every_window_has_the_three_dots_and_a_centred_title():
    """The demo card, the closing box and the Guide's install card share the terminal's bar."""
    bar = _rule(".rt-bar")
    assert "background: var(--term-bar)" in bar and "font-family: var(--mono)" in bar
    assert "var(--term-dot)" in _rule(".rt-bar::before")
    assert "text-align: center" in _rule(".rt-title")


def test_the_demo_card_is_a_window_called_marking_page():
    (card,) = _all(_main(HOME), "section", "jk-card")
    first = next(el for el in card.children if isinstance(el, Element))
    assert {"rt-bar", "jk-bar"} <= first.classes() and first.attrs.get("aria-hidden") == "true"
    assert _flat(_all(first, "span", "rt-title")[0]) == "marking page"
    assert "background: var(--term-bg)" in _rule(".jk-card")
    assert "flex: none" in _rule(".jk-bar")


# The Guide ------------------------------------------------------------------------------------

REFERENCE_MD = f"{GITHUB}/blob/main/docs/reference.md"
GUIDE_STEPS = [("step-find", "Find your eval results"),
               ("step-mark", "Mark your answers Pass or Fail"),
               ("step-measure", "Measure: see how often your LLM-as-a-judge agrees with you"),
               ("step-fix", "Fix: write a better rule and test it"),
               ("step-check", "Re-check after you change your LLM-as-a-judge")]


def test_the_guide_is_the_install_the_five_steps_and_three_cards():
    sections = [el for el in _main(GUIDE).children if isinstance(el, Element)]
    assert [s.classes() for s in sections] == [{"hero", "gx-hero"}, {"gx-steps"}, {"gx-more"}]
    hero = sections[0]
    assert hero.attrs["id"] == "install"  # judgekeeper prints start.html#install
    (h1,) = _all(hero, "h1")
    assert _flat(h1) == "Install judgekeeper in your project."
    assert [_flat(s) for s in _all(h1, "span", "h-brand")] == ["judgekeeper"]
    assert "color: var(--green)" in _rule(".h-brand")
    # "Install judgekeeper" stays on one line from 1000px: the text column is only 385px at
    # 1101 wide and 388px at 1000, so the heading shrinks with the screen there
    assert "font-size: clamp(42px, calc(11vw - 80px), 62px)" in _rule(".gx-hero h1")
    assert CSS.index(".gx-hero h1 {") < CSS.index("@media (max-width: 860px)")
    mid = CSS[CSS.index("@media (max-width: 1100px) {"):]
    mid = mid[:mid.index("\n}\n")]
    assert "font-size: clamp(42px, 4.2vw, 52px)" in _rule(".gx-hero h1", mid)
    assert _flat(_all(hero, "p", "gx-lede")[0]) == (
        "Works with promptfoo, DeepEval, Inspect AI, MLflow or your own file.")
    # the install card is a window on your project folder: pip and uv, both in view
    (card,) = _all(hero, "div", "gx-install")
    assert "gwin" in card.classes()
    assert _flat(_all(_all(card, "div", "rt-bar")[0], "span", "rt-title")[0]) == (
        "your project folder")
    assert not _all(card, "p", "gx-k")
    # one command per box, so nobody pastes the two pip lines as one
    pairs = [[_flat(c) for c in _all(p, "code")] for p in _all(card, "div", "gx-pair")]
    assert pairs == [["pip install judgekeeper", "judgekeeper"], ["uvx judgekeeper"]]
    assert not _all(card, "div", "cmd-2") and ".cmd-2" not in CSS
    # pip into the project's virtual environment: a system Python refuses it (PEP 668)
    assert [_flat(h) for h in _all(card, "p", "gx-way-h")] == [
        "With pip, in your project’s virtual environment", "With uv"]
    assert [_flat(s) for s in _all(card, "p", "gx-small")] == [
        "Works on macOS, Linux and Windows, with Python 3.11 to 3.14."]
    assert not _all(_main(GUIDE), "nav")  # no side list
    # three windows, the title in each bar (the h3 stays for screen readers): your own file
    # or code across the column, then the keys and the handy commands side by side
    rows = _all(sections[2], "div", "gm-row")
    assert [(r.attrs["id"], _flat(_all(r, "h3")[0])) for r in rows] == [
        ("own-format", "Your own file or code"), ("keys", "No API key needed"),
        ("misc", "Handy commands")]
    for r in rows:
        (h3,) = _all(r, "h3")
        (bar,) = _all(r, "div", "rt-bar")
        assert "sr" in h3.classes() and _flat(bar) == _flat(h3), r.attrs["id"]
        assert bar.attrs.get("aria-hidden") == "true"
    (pair,) = _all(sections[2], "div", "gm-pair")
    assert [r.attrs["id"] for r in _all(pair, "div", "gm-row")] == ["keys", "misc"]
    assert "grid-template-columns: minmax(0, 1fr) minmax(0, 1.2fr)" in _rule(".gm-pair", _wide())
    assert "grid-template-columns: minmax(0, 1fr)" in _rule(".gm-pair")  # stacked, keys first
    assert _flat(_all(_by_id(GUIDE, "keys"), "div", "gx-text")[0]) == (
        "judgekeeper only reads files. It makes no AI call and needs no API key. "
        "When you grade answers again, your own eval tool makes the calls, with your own key.")
    assert not _all(sections[2], "div", "gx-card")
    # the steps and the windows below are as wide as the top section: "The 5 steps." starts
    # under "Install", and the windows end where the install window ends
    assert not [s for s, d in _rules() if ("gx-steps .wrap" in s or "gx-more .wrap" in s)
                and "max-width" in d]
    # the top section is shorter, so the start of the steps shows on the first screen
    assert "padding-block: 64px 56px" in _rule(".gx-hero .wrap")
    assert "padding-block: 48px 32px" in _rule(".gx-steps .wrap")
    # the step windows and the windows below share one look and the column's full width
    (window,) = [d for s, d in _rules() if s.endswith("\n.sw, .gm-row")]
    for part in ("border: 1px solid var(--line)", "border-radius: 12px",
                 "background: var(--term-bg)"):
        assert part in window, part
    assert "margin-left" not in window
    assert "clip: rect(0 0 0 0)" in _rule(".sr")


def test_your_own_file_or_code_is_two_short_ways_and_a_link_for_the_rest():
    """A first-timer sees a three-column file and its command, and the one record() line;
    scores, pass marks and every other option are in the reference."""
    own = _all(_by_id(GUIDE, "own-format"), "div", "gx-text")[0]
    said = [(el.tag, _flat(el)) for el in own.children if isinstance(el, Element)]
    assert said == [
        ("p", ("No eval tool? Save your results as a CSV, TSV or JSONL file with three columns: "
              "input (the question), output (the answer) and verdict (Pass or Fail from your "
              "LLM-as-a-judge). Then run:")),
        ("div", "judgekeeper results.csv"),
        ("p", "Your LLM-as-a-judge runs in your own code? Add this after each grade:"),
        ("pre", ("import judgekeeper judgekeeper.record(input=question, output=answer, "
                "verdict=grade)")),
        ("p", ("Your LLM-as-a-judge gives a score instead of Pass or Fail? The full reference "
              "shows how to set where Pass starts, and every other option."))]
    assert [_flat(b) for p in _all(own, "p") for b in _all(p, "b")] == [
        "No eval tool?", "Your LLM-as-a-judge runs in your own code?"]
    (link,) = _all(own, "a")
    assert link.attrs["href"] == f"{REFERENCE_MD}#how-grades-are-read"
    reference = (ROOT / "docs" / "reference.md").read_text(encoding="utf-8")
    assert "\n## How grades are read\n" in reference
    # the reference line sits apart from the code: a gap, a thin line, room under it
    small = _rule("#own-format .gx-small")
    for part in ("margin-top: 24px", "padding-top: 18px", "border-top: 1px solid var(--line)",
                 "line-height: 1.7"):
        assert part in small, part
    text = GUIDE.read_text(encoding="utf-8")
    for gone in ("--pass-if", "pass_mark=", "can't test a new rule"):
        assert gone not in text, gone


def test_the_guides_record_line_saves_what_judgekeeper_reads(tmp_path, monkeypatch):
    """The two lines the Guide shows, run as they are after a grade, give answers judgekeeper
    finds."""
    from judgekeeper import recorder, start

    (code,) = _all(_by_id(GUIDE, "own-format"), "pre", "gx-code")
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'app'\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("JUDGEKEEPER_RECORD", raising=False)
    recorder._reset()
    try:
        for i, grade in enumerate(["pass", "fail"]):
            space = {"question": f"Do you ship to {i}?", "answer": "Yes.", "grade": grade}
            exec(code.text(), space)  # noqa: S102 - the Guide's own two lines
    finally:
        recorder._reset()
    found = start.find_judge(tmp_path)
    assert (found.pool.n_pass, found.pool.n_fail) == (1, 1)


def test_the_guide_shows_each_step_as_a_window_beside_a_number_rail():
    (steps,) = _all(_main(GUIDE), "ol", "gl")
    items = _all(steps, "li", "gl-step")
    assert [(li.attrs["id"], _flat(_all(li, "h3")[0])) for li in items] == GUIDE_STEPS
    for n, li in enumerate(items, 1):
        (number,) = _all(li, "span", "gl-n")
        assert _flat(number) == str(n) and number.attrs.get("aria-hidden") == "true"
        # the title sits in the window's bar; the h3 stays, hidden, for screen readers
        (window,) = _all(li, "div", "sw")
        (bar,) = _all(window, "div", "sw-bar")
        (h3,) = _all(li, "h3")
        assert _flat(bar) == _flat(h3) and "sr" in h3.classes(), li.attrs["id"]
        assert bar.attrs.get("aria-hidden") == "true" and _all(window, "div", "sw-body")
    assert "font-weight: 700" in _rule(".sw-t") and "var(--sans)" in _rule(".sw-t")
    # a long title wraps on a phone, never cut: the bar grows with it
    assert "nowrap" not in _rule(".sw-t") and "min-height: 44px" in _rule(".sw-bar")
    # numbers in green circles joined by a line; on wide screens they hang in the margin
    assert "var(--green)" in _rule(".gl-n") and "border-radius: 50%" in _rule(".gl-n")
    assert "width: 1px" in _rule(".gl-step:not(:last-child)::before")
    # a short line from each number to its window's bar
    joins = [_rule(".gl-step::after", css) for css in (CSS, _wide(1440))]
    assert "height: 1px" in joins[0] and "background: var(--line)" in joins[0]
    assert "left: -24px" in joins[1]
    assert "left: -68px" in _rule(".gl-n", _wide(1440)) and "display: block" in _rule(
        ".gl-step", _wide(1440))
    assert ".gl-n" not in _wide()  # from 1100 to 1440 wide the numbers keep their column
    done = {step: [_flat(p) for p in _all(_by_id(GUIDE, step), "p", "done")]
            for step in ("step-find", "step-mark", "step-measure")}
    assert done == {
        "step-find": [("Nothing found? Run your eval first so it saves its results, or point "
                       "judgekeeper to your results file:")],
        "step-mark": ["When See your result appears, click it."],
        "step-measure": [("Result says it’s too early to tell? Your LLM-as-a-judge needs more "
                          "of your marks to be measured. Mark more answers, then look again:")]}
    # each step's words, as the person reads them
    said = {step: [_flat(p) for p in _all(_all(_by_id(GUIDE, step), "div", "sw-body")[0], "p")
                   if not {"done", "gx-small", "gx-tap"} & p.classes()]
            for step in ("step-mark", "step-measure", "step-fix", "step-check")}
    assert said == {
        "step-mark": [("Mark each answer Pass or Fail, the way you would grade it. You won’t see "
                       "your LLM-as-a-judge’s grade, so it can’t sway you. Every mark is saved, "
                       "so you can stop at any time and come back later.")],
        "step-measure": [("The result page tells you one of three things: your LLM-as-a-judge "
                          "is good enough to use, it needs work, or it’s too early to tell. "
                          "Below that, it lists the answers where you and your LLM-as-a-judge "
                          "disagreed.")],
        "step-fix": [
            "Result says your LLM-as-a-judge needs work? Run:",
            ("It saves the answers your LLM-as-a-judge got wrong in "
             ".judgekeeper/fix/mistakes.md, apart from the marks kept aside to test your rule. "
             "Read it to write a better rule yourself, or hand it to a coding agent to help you "
             "write one."),
            ("Change the rule in your eval tool. Have it grade the answers in "
             ".judgekeeper/fix/marked-answers.csv again, save the results, then run:"),
            ("judgekeeper tests the new rule on the marks kept aside and tells you if it’s "
             "better, safe to try, worse, or if it can’t tell yet. How many marks you need "
             "depends on how big the change is. A rule that fixes 9 in 10 of its mistakes is "
             "clear from about 50 marks, one that fixes a quarter from about 80, and one that "
             "fixes 1 in 10 and breaks 5 in 100 right answers needs more than 120 "
             "(simulation).")],
        "step-check": [
            ("Changed your LLM-as-a-judge’s model or rule? Grade the answers you marked again "
             "the same way as in step 4, then:"),
            ("judgekeeper finds the answers you marked in your new results by their exact text "
             "and question, compares the new grades with your marks, and tells you if your "
             "LLM-as-a-judge "
             "still agrees with you. You don’t need to mark anything again.")]}
    bold = {step: [_flat(b) for b in _all(_by_id(GUIDE, step), "b")]
            for step in ("step-measure", "step-fix", "step-check")}
    assert bold == {"step-measure": ["Result says it’s too early to tell?"],
                    "step-fix": ["Result says your LLM-as-a-judge needs work?", "better",
                                 "safe to try", "worse", "can’t tell yet"],
                    "step-check": ["Changed your LLM-as-a-judge’s model or rule?"]}
    assert not _all(_main(GUIDE), "details")  # no fold
    # the numbers: in the reference (the one link opens the picture)
    assert not [a for a in _all(_by_id(GUIDE, "step-measure"), "a") if a.parent.tag != "figure"]
    assert not _all(_by_id(GUIDE, "step-fix"), "table")  # the six results: in the reference
    # step 4 opens with when to run fix, then what it saves
    body = _all(_by_id(GUIDE, "step-fix"), "div", "gl-body")[0]
    opening = [el.tag for el in body.children if isinstance(el, Element)][:4]
    assert opening == ["h3", "p", "div", "p"]
    assert [_flat(p) for p in _all(_by_id(GUIDE, "step-fix"), "p", "gx-small")] == [
        ("judgekeeper prints how to grade the answers again with your eval tool. It only reads "
         "the new results.")]
    # the two pictures sit in their step's window with a plain border, no second bar
    shots = [li.attrs["id"] for li in items for f in _all(li, "figure", "gx-shot")]
    assert shots == ["step-mark", "step-measure"]
    assert not any(_all(f, "div", "rt-bar") for f in _all(steps, "figure", "gx-shot"))
    assert "border: 1px solid var(--line)" in _rule(".gx-shot")
    assert "max-width" not in _rule(".gx-shot")  # the pictures fill the window
    text = GUIDE.read_text(encoding="utf-8")
    for gone in ("<template", "steplist", "t-out", "learn.html", "data-panel", "npx"):
        assert gone not in text, gone


def test_the_guides_commands_look_like_terminal_lines():
    """A green "$" before each one-line command, drawn by CSS so Copy copies the command
    alone. Handy commands are a window of terminal lines."""
    assert 'content: "$"' in _rule(".gx .cmd code::before")
    assert "var(--green)" in _rule(".gx .cmd code::before")
    assert "background: var(--term-bg)" in _rule(".gx .cmd")
    assert "code.textContent" in JS  # what Copy copies: never the "$"
    misc = _by_id(GUIDE, "misc")
    assert _flat(_all(misc, "div", "rt-bar")[0]) == "Handy commands"
    (pre,) = _all(misc, "pre", "gm-pre")
    assert pre.parent is misc  # straight in the window, no second bar
    lines = [" ".join(line.split()) for line in pre.text().splitlines()]
    assert lines == ["$ judgekeeper --stop # close the marking page",
                     "$ judgekeeper --new # start over (old marks are kept)",
                     "$ judgekeeper --no-browser # get the link, no browser",
                     "$ judgekeeper --help # see every option"]
    assert {_flat(s) for s in _all(pre, "span", "t-prompt")} == {"$"}


def test_every_command_box_has_a_copy_button_that_says_copied():
    boxes = [box for page in (GUIDE, CHECK) for box in _all(parse(page), "div", "cmd")]
    install = ["pip install judgekeeper", "judgekeeper", "uvx judgekeeper"]  # one per box
    assert [_flat(_all(b, "code")[0]) for b in boxes] == [
        *install, "judgekeeper", "judgekeeper path/to/results.json",
        "judgekeeper mark", "judgekeeper fix", "judgekeeper fix new-results.json",
        "judgekeeper check",
        "judgekeeper results.csv"]  # the check page has none: its status bar links here
    for box in boxes:
        (button,) = _all(box, "button", "copy")
        assert "data-copy" in button.attrs and button.attrs["aria-label"].startswith("Copy")
        assert _all(button, "svg", "i-copy") and _all(button, "svg", "i-tick")
        (said,) = _all(button, "span", "copied")
        assert said.attrs.get("aria-live") == "polite"
    assert '"Copied"' in JS and "clipboard" in JS
    # the tick and "Copied" show in green inside the button, never over the command
    assert "color: var(--green)" in _rule(".cmd .copy.done")
    assert "position" not in _rule(".cmd .copied") and "display: inline" in _rule(
        ".cmd .copy.done .copied")
    assert "padding: 12px 18px" in _rule(".cmd code")
    # a copy that failed says so in the button, never "Copied"
    assert "display: inline" in _rule(".cmd .copy.failed .copied")


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node to run site.js")
def test_copy_says_copied_only_when_the_copy_worked():
    """site.js's copy buttons, run in node: the clipboard, then the select-and-copy fallback;
    "Copied" only when one of them worked, else "Copy failed"."""
    body = JS[JS.index("  function setUpCopy() {"):]
    body = body[:body.index("\n  }\n") + 4]
    stub = r"""
var timers = [], sel = [], works = true, execWorks = true, execThrows = false;
function setTimeout(f, ms) { timers.push([f, ms]); return timers.length; }
function clearTimeout() {}
var code = {textContent: "judgekeeper fix"}, said = {textContent: ""}, classes = [];
var button = {parentNode: {querySelector: function () { return code; }},
  querySelector: function () { return said; },
  classList: {add: function (c) { if (classes.indexOf(c) < 0) classes.push(c); },
              remove: function (c) { classes = classes.filter(function (x) { return x !== c; }); }},
  addEventListener: function (t, f) { button.click = f; }};
function $all() { return [button]; }
var document = {createRange: function () { return {selectNodeContents: function () {}}; },
  execCommand: function (c) { sel.push(c); if (execThrows) throw new Error("no");
    return execWorks; }};
var window = {getSelection: function () {
  return {removeAllRanges: function () {}, addRange: function () {}}; }};
var navigator = {clipboard: {writeText: function () {
  return works ? Promise.resolve() : Promise.reject(new Error("no")); }}};
"""
    scenario = r"""
(async function () {
  function tick() { return new Promise(function (r) { setImmediate(r); }); }
  setUpCopy();
  var got = {};
  button.click(); await tick(); got.clipboard = [said.textContent, classes.slice()];
  works = false; button.click(); await tick();
  got.fallback = [said.textContent, classes.slice(), sel.length];
  execWorks = false; button.click(); await tick();
  got.failed = [said.textContent, classes.slice()];
  timers[timers.length - 1][0](); got.after = [said.textContent, classes.slice()];
  execThrows = true; button.click(); await tick(); got.thrown = [said.textContent, classes.slice()];
  process.stdout.write(JSON.stringify(got));
})();
"""
    code = "(function () {" + stub + body + "\n" + scenario + "})();"  # node's own navigator
    out = subprocess.run([shutil.which("node"), "-e", code],
                         capture_output=True, text=True, check=True, timeout=30)
    got = json.loads(out.stdout)
    assert got["clipboard"] == ["Copied", ["done"]]
    assert got["fallback"] == ["Copied", ["done"], 1]
    assert got["failed"] == ["Copy failed", ["failed"]]
    assert got["after"] == ["", []]
    assert got["thrown"] == ["Copy failed", ["failed"]]


# Privacy ------------------------------------------------------------------------------------

def _side(page: Path) -> list[tuple[str, str]]:
    (nav,) = _all(_main(page), "nav", "g-nav")
    return [(a.attrs["href"], _flat(a)) for a in _all(nav, "a")]


def test_privacy_says_what_the_site_and_the_tool_do_with_data():
    assert _side(PRIVACY) == [("#site", "This website"), ("#providers", "Who sees your visit"),
                              ("#rights", "Why, and your rights"),
                              ("#local", "judgekeeper on your computer"),
                              ("#questions", "Questions")]
    site, providers, rights, local = (_all(_by_id(PRIVACY, s), "li")
                                      for s in ("site", "providers", "rights", "local"))
    assert (len(site), len(providers), len(rights), len(local)) == (4, 4, 3, 4)
    text = _flat(_main(PRIVACY))
    assert "light or dark" not in text and "local storage" not in text  # dark only, no store
    assert "never uploaded" in text
    hrefs = [a.attrs["href"] for a in _all(_main(PRIVACY), "a")]
    assert f"{GITHUB}/issues" in hrefs and f"{GITHUB}/blob/main/SECURITY.md" in hrefs


def test_privacy_is_the_notice_the_law_asks_for():
    """Who runs the site and how to reach them, what each provider sees and keeps, the transfer
    safeguard, the legal basis, Do Not Track, the rights and where to complain, and a date."""
    text = _flat(_main(PRIVACY))
    for words in ("run by Sathvik Thota, the author of the open-source judgekeeper project",
                  "no cookies of its own",
                  "your IP address, your browser's user agent and the page you asked for",
                  "Railway hosts the site. To deliver and protect it, Railway processes",
                  "Railway keeps these request logs for a limited time, then deletes them",
                  ("judgekeeper.com without www, GoDaddy, the domain registrar, forwards you "
                   "to www.judgekeeper.com and sees that one request: your IP address and the "
                   "page you asked for."),
                  "once the page has loaded, checking your own file works with Wi-Fi turned off",
                  "Contact: judgekeeper.project@outlook.com.",
                  "by writing to judgekeeper.project@outlook.com.",
                  "Data Privacy Framework and Standard Contractual Clauses",
                  "my legitimate interest", "not sold, shared or combined",
                  "Do Not Track", "erased or restricted, or object to its use",
                  "Information Commissioner's Office", "Last updated: 2026-10-29"):
        assert words in text, words
    page = PRIVACY.read_text(encoding="utf-8")
    assert "90 days" not in page  # Railway gives no period in its policy or its DPA
    assert "Cloudflare" not in page and "CONTACT_ADDRESS" not in page  # Railway only
    mail = [a.attrs["href"] for a in _all(_main(PRIVACY), "a") if a.attrs["href"].startswith(
        "mailto:")]
    assert mail == ["mailto:judgekeeper.project@outlook.com"] * 2
    assert "Railway is based in the US and acts for me" in text


def test_the_site_speaks_as_judgekeeper_or_i_never_we():
    """No business voice: "we", "us" or "our" only in the Home demo's made-up answers."""
    for page in [*pages(), WEBSITE / "errors" / "404.html"]:
        main = _main(page)
        demo = [el for el in main.iter() if el.attrs.get("id") == "demo"]
        text = _flat(main)
        for el in demo:
            text = text.replace(_flat(el), "")
        found = re.findall(r"\b(?:[Ww]e|us|[Oo]urs?)\b", text)
        assert not found, (page.name, found)
    llms = (WEBSITE / "llms.txt").read_text(encoding="utf-8")
    assert not re.findall(r"\b(?:[Ww]e|us|[Oo]urs?)\b", llms)


# The browser check ---------------------------------------------------------------------------

def test_the_browser_check_is_the_drop_box_beside_a_terminal():
    main = _main(CHECK)
    assert main.classes() == {"ck"}
    (section,) = _all(main, "section", "ck2")
    left, term = [el for el in _all(section, "div") if el.parent.parent is section]
    assert "ck2-l" in left.classes() and {"term", "ck2-term"} <= term.classes()
    (h1,) = _all(left, "h1")
    assert _flat(h1) == "Try step 1 in your browser."
    assert [_flat(s) for s in _all(h1, "span", "nb")] == ["in your browser."]
    titles = re.findall(r'<title>([^<]*)</title>|content="([^"]*\| judgekeeper)"',
                        CHECK.read_text(encoding="utf-8"))
    assert {a or b for a, b in titles} == {"Try step 1 in your browser | judgekeeper"}
    # the drop box: an upload icon and what to drop; after a file, the file and Clear
    drop = _by_id(CHECK, "fc-drop")
    assert drop.tag == "button" and drop.attrs.get("type") == "button"
    (empty,) = _all(drop, "span", "fc-empty")
    (loaded,) = _all(drop, "span", "fc-loaded")
    assert "hidden" not in empty.attrs and "hidden" in loaded.attrs
    assert [_flat(el) for el in empty.iter() if el.tag in ("b", "span") and el.classes() & {
        "ck2-or", "fc-kinds"} or el.tag == "b"] == [
        "Drop your results file here", "or click to choose one",
        "promptfoo · DeepEval · CSV · TSV · JSONL"]
    assert _flat(_all(loaded, "span", "fc-kinds")[0]) == "Drop another file to check it instead"
    (name,) = _all(loaded, "b")
    assert name.attrs.get("id") == "fc-name"
    assert [_flat(s.parent) for s in drop.iter() if s.tag == "svg"] and all(
        s.attrs.get("aria-hidden") == "true" for s in drop.iter() if s.tag == "svg")
    clear = _by_id(CHECK, "fc-clear")  # its own button, over the box: never inside it
    assert clear.tag == "button" and "hidden" in clear.attrs and _flat(clear) == "Clear"
    assert clear.parent.attrs.get("class") == drop.parent.attrs.get("class") == "fc-zone"
    assert "fc-drop" not in [a.attrs.get("id") for a in clear.ancestors()]
    assert not [el for el in parse(CHECK).iter() if el.attrs.get("id") == "ck-clear"]
    file_input = _by_id(CHECK, "fc-file")
    assert file_input.attrs["type"] == "file" and "sr" in file_input.classes()
    # the examples, under a divider; no command row (the status bar links to the Guide)
    (divider,) = _all(left, "p", "ex-or")
    assert _flat(divider) == "or try an example"
    assert not _all(main, "div", "ck-run") and "uvx" not in _flat(main)
    # the terminal: the file's name in its bar once read, the waiting screen, the result
    assert _flat(_by_id(CHECK, "ck-title")) == "your results file"
    wait = _by_id(CHECK, "ck-wait")
    (ghost,) = _all(wait, "span", "ck-ghost")
    assert ghost.attrs.get("aria-hidden") == "true"
    waiting = wait.text()[:wait.text().index(ghost.text())]
    assert " ".join(waiting.split()) == (
        "$ judgekeeper Step 1 of 5: Find Waiting for your results file. Drop it in the box, or "
        "try an example. ▋")
    result = _by_id(CHECK, "fc-result")
    assert result.attrs.get("aria-live") == "polite" and not result.children
    # the status bar: the file stays here, and the next step is the Guide's install
    (foot,) = _all(term, "div", "term-foot")
    assert _flat(_all(foot, "span", "tf-text")[0]) == "your file stays on your computer"
    (link,) = _all(foot, "a")
    assert link.attrs["href"] == "start.html" and "tf-link" in link.classes()
    assert _flat(link) == "next step: install judgekeeper →"
    script = (WEBSITE / "assets" / "freecheck.js").read_text(encoding="utf-8")
    assert ('NOT_RECOGNISED = "This doesn\'t look like results judgekeeper can read in the '
            'browser. The tool also reads Inspect AI and MLflow: run uvx judgekeeper in your '
            'project.";') in script


def test_waiting_terminal_uses_the_codes_labels(tmp_path):
    """The faint lines while waiting are the labels the check then prints, values dotted."""
    from tests.test_freecheck_parity import NODE, browser

    ghost = _all(_by_id(CHECK, "ck-wait"), "span", "ck-ghost")[0].text()
    labels = [line.split("·")[0].rstrip() for line in ghost.strip().splitlines() if line]
    assert labels == ["Eval tool:", "File:", "Answers:", "LLM-as-a-judge:", "Rule:",
                      "Your LLM-as-a-judge passed", "Checked:"]
    if NODE is None:
        pytest.skip("needs node to run the page's free check")
    path = tmp_path / "results.csv"
    path.write_text("input,output,verdict\nq1,a1,pass\nq2,a2,fail\n", encoding="utf-8")
    (judge,) = browser(path)["judges"]
    printed = "\n".join(judge["lines"])
    for label in labels:
        assert f"\n{label}" in "\n" + printed, label  # the check prints each, as a line's start


def test_the_browser_check_is_two_even_columns_that_end_together():
    wrap = _rule(".ck2 .wrap")
    for part in ("grid-template-columns: minmax(0, 1fr) minmax(0, 1.15fr)", "gap: 28px 48px",
                 "align-items: stretch"):
        assert part in wrap, part
    assert "clamp(34px, 3.6vw, 48px)" in _rule(".ck2-l h1") and "font-weight: 800" in _rule(
        ".ck2-l h1")
    assert "min-height: 524px" in _rule(".ck2-term")  # the same height before and after a file
    assert "overflow-y: auto" in _rule(".ck2-term .ck-out")  # output scrolls inside
    narrow = CSS[CSS.index("@media (max-width: 1000px) {\n  .ck2"):]
    narrow = narrow[:narrow.index("\n}\n")]
    assert "grid-template-columns: minmax(0, 1fr)" in _rule(".ck2 .wrap", narrow)
    assert "min-height: 320px" in _rule(".ck2-term", narrow)
    # three equal file cards, one a row on narrow phones; a green lift on hover, none if the
    # reader asks for less motion
    assert "grid-template-columns: repeat(3, minmax(0, 1fr))" in _rule(".ex-row")
    hover = _rule(".ex-card:hover, .ex-card:focus-visible")
    assert "border-color: var(--green)" in hover and "translateY(-1px)" in hover
    assert any(".ex-card" in s and "transform: none" in d for s, d in _rules(
        CSS[CSS.index("@media (prefers-reduced-motion: reduce)"):]))
    # a file in the box: a solid green border; Clear under its name, red on hover
    assert "border-color: var(--green)" in _rule(".ck2-drop.has-file")
    assert "var(--red)" in _rule(".fc-clear:hover, .fc-clear:focus-visible")
    # phones: the status bar keeps only the next-step link
    phone = CSS[CSS.index("@media (max-width: 520px) {\n  .ex-row"):]
    phone = phone[:phone.index("\n}\n")]
    assert "display: none" in _rule(".ck2-foot .tf-text", phone)
    assert "grid-template-columns: minmax(0, 1fr)" in _rule(".ex-row", phone)
    # the drop box's hover, drag and focus: a green border inside it, no ring outside
    focus = _rule(".fc-drop:hover, .fc-drop.over, .fc-drop:focus-visible")
    assert "inset 0 0 0 1px var(--green)" in focus and "outline: none" in focus


def test_the_browser_check_lines_wrap_and_never_scroll_sideways():
    """At every width a line wraps inside the terminal (checked in Chrome at 1440 and 390
    wide). On a phone a value goes under its label, and a line that only goes on from the one
    above has no indent."""
    term = _rule(".fc-term")
    assert "white-space: pre-wrap" in term and "overflow-wrap: anywhere" in term
    assert not [s for s, d in _rules() if "fc-term" in s and "overflow-x" in d]
    phone = CSS[CSS.index("@media (max-width: 760px) {\n  .ck2 .wrap"):]
    phone = phone[:phone.index("\n}\n")]
    assert "flex-direction: column" in _rule(".fc-term .ln", phone)
    assert "display: none" in _rule(".fc-term .ln > .pad", phone)
    script = (WEBSITE / "assets" / "freecheck.js").read_text(encoding="utf-8")
    assert "line.k.trim() ? 'k t-label' : 'k t-label pad'" in script
    # Home's terminal colours
    for cls in ("t-prompt", "t-cmd", "t-step", "t-label", "t-warn", "t-good", "t-next"):
        assert f"'{cls}'" in script, cls
        assert f".term .{cls}" in CSS, cls


def _shade(lines: list[str]) -> list[str]:
    """Home's terminal lines as site.js colours them, run in node."""
    body = JS[JS.index("  function shade(text) {"):]
    body = body[:body.index("\n  }\n") + 4]
    code = (body + "\nprocess.stdout.write(JSON.stringify(shade(" + json.dumps("\n".join(lines))
            + ").split('\\n')));")
    out = subprocess.run([shutil.which("node"), "-e", code], capture_output=True, text=True,
                         check=True, timeout=30)
    return json.loads(out.stdout)


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node to run site.js")
def test_home_terminal_paints_words_inside_lines():
    """Pass green, Fail red, outcome words, the main numbers, ranges dim, file names, quoted
    text and commands plain white; "[y/N]" dim with the typed "y" green; "Checked:" green.
    Nothing inside quotes is painted."""
    said = dict(zip(["pass", "num", "range", "path", "quote", "cmd", "yes", "checked", "warn",
                     "unsure", "better"], _shade([
        "  You passed 15 answers. Of those, it said Pass on 7 and Fail on 8.",
        "You and your judge disagreed on 16 of 30 answers.",
        "  When you said Pass: about 54% (between 35% and 72%)",
        "All 10 mistakes are saved in .judgekeeper/fix/mistakes.md and promptfooconfig.yaml.",
        '  "The answer is Pass when it is polite, about 54% of the time."',
        "Next: run `judgekeeper fix` again.",
        "Go on? [y/N] y",
        "Checked: every answer has a clear Pass or Fail.",
        "  When you said Pass    22 of 25    15 of 25    Worse",
        "  When you said Fail    19 of 25    Not sure",
        "The new rule looks Better here."])))
    assert '<span class="t-pass">Pass</span>' in said["pass"]
    assert '<span class="t-fail">Fail</span>' in said["pass"]
    assert '<span class="t-num">16 of 30</span>' in said["num"]
    assert '<span class="t-num">about 54%</span>' in said["range"]
    assert '<span class="t-dim">(between 35% and 72%)</span>' in said["range"]
    assert '<span class="t-path">.judgekeeper/fix/mistakes.md</span>' in said["path"]
    assert '<span class="t-path">promptfooconfig.yaml</span>' in said["path"]
    # a quote is one plain span: its Pass and numbers stay as they are
    assert said["quote"] == ('  <span class="t-quote">"The answer is Pass when it is polite, '
                             'about 54% of the time."</span>')
    assert '<span class="t-cmd">`judgekeeper fix`</span>' in said["cmd"]
    assert said["yes"].endswith('<span class="t-dim">[y/N]</span> <span class="t-good">y</span>')
    assert said["checked"].startswith('<span class="t-good">Checked:</span>')
    assert '<span class="t-warn">Worse</span>' in said["warn"]
    assert '<span class="t-unsure">Not sure</span>' in said["unsure"]
    assert '<span class="t-good">Better</span>' in said["better"]
    # only the brand's green, red and amber, with white and grey
    def names(selector: str) -> list[str]:
        return re.sub(r"/\*.*?\*/", "", selector, flags=re.DOTALL).strip().split(", ")

    colours = {cls: " ".join(d for s, d in _rules() if f".term .{cls}" in names(s))
               for cls in ("t-pass", "t-fail", "t-num", "t-unsure", "t-path", "t-quote",
                           "t-cmd")}
    assert "var(--green)" in colours["t-pass"] and "var(--red)" in colours["t-fail"]
    assert "font-weight: 500" in colours["t-pass"] and "font-weight: 500" in colours["t-fail"]
    assert "var(--fg)" in colours["t-num"] and "var(--muted)" in colours["t-unsure"]
    assert "dotted" in colours["t-path"] and "var(--fg)" in colours["t-quote"]
    for rule in colours.values():
        assert not re.search(r"#[0-9a-f]{3,6}|blue|sand", rule), rule


def test_a_line_quoted_from_judgekeeper_is_what_it_prints():
    """`data-said-by` names the module that prints the quoted line (cut at its last full
    stop when the page quotes only the start)."""
    quoted = [el for page in pages() for el in parse(page).iter()
              if "data-said-by" in el.attrs]
    for el in quoted:
        source = (ROOT / "src" / "judgekeeper" / f"{el.attrs['data-said-by']}.py").read_text(
            encoding="utf-8")
        assert el.text().strip().removesuffix(".") in source, el.text()


# The pictures and what fix can test --------------------------------------------------------

def test_guide_page_pictures_after_first_paragraph():
    for step, picture in (("step-mark", "label.webp"), ("step-measure", "result.webp")):
        body = _all(_by_id(GUIDE, step), "div", "gl-body")[0]
        tags = [el.tag for el in body.children if not isinstance(el, str)]
        assert tags[:3] == ["h3", "p", "figure"], step
        (img,) = _all(body, "img")
        assert img.attrs["src"] == f"assets/shots/{picture}"
        assert (WEBSITE / "assets" / "shots" / picture).is_file()
        assert (img.attrs["width"], img.attrs["height"]) == ("2880", "1800")
        assert len(img.attrs["alt"]) > 80 and "screenshot" not in img.attrs["alt"].lower()
    assert "max-width" not in _rule(".gx-shot")  # the pictures fill their step's window
    assert "width: 100%" in _rule(".gx-shot img")  # the figure draws the border
    # Home stays terminal: no picture there
    assert not _all(_main(HOME), "img") and not _all(_main(HOME), "figure")


def test_on_a_phone_the_guides_pictures_open_full_size():
    """Each picture is a plain link to its file, and a small "Tap to enlarge" under it shows
    on phones only."""
    for step, picture in (("step-mark", "label.webp"), ("step-measure", "result.webp")):
        body = _all(_by_id(GUIDE, step), "div", "gl-body")[0]
        (figure,) = _all(body, "figure", "gx-shot")
        (link,) = _all(figure, "a")
        assert link.attrs == {"href": f"assets/shots/{picture}"}, step
        assert [el.tag for el in link.children if isinstance(el, Element)] == ["img"]
        after = [el for el in body.children if isinstance(el, Element)]
        tap = after[after.index(figure) + 1]
        assert (tap.tag, tap.classes(), _flat(tap)) == ("p", {"gx-tap"}, "Tap to enlarge")
    assert "display: none" in _rule(".gx-text .gx-tap")
    assert "display: block" in _rule(".gx-text .gx-tap", _narrow(600))


TOOLS = "For promptfoo, DeepEval, Inspect AI and MLflow"


def test_testing_a_new_rule_is_said_for_every_eval_tool():
    """fix reads the new results as step 1 reads results, so a new rule is tested the same way
    for every eval tool, and fix prints how to grade the answers again for each (fix.REGRADE,
    fix.OWN). No page limits testing to some tools, or says judgekeeper asks the
    LLM-as-a-judge or keeps a rule in rule.txt."""
    assert set(fix.REGRADE) == {"promptfoo", "deepeval", "inspect", "mlflow"} and fix.OWN
    meta = [el.attrs["content"] for el in parse(HOME).iter()
            if el.tag == "meta" and "description" in el.attrs.get("name", "")
            + el.attrs.get("property", "")]
    assert len(meta) == 3
    assert all(TOOLS not in m and "test a better rule" in m and "on your own computer" in m
               for m in meta)
    assert "test it on marks kept aside." in _flat(_by_id(HOME, "tab-fix"))
    assert "promptfoo" not in _flat(_by_id(HOME, "tab-fix"))
    step = _flat(_by_id(GUIDE, "step-fix"))
    assert ".judgekeeper/fix/marked-answers.csv" in step
    assert "judgekeeper fix new-results.json" in step
    assert "judgekeeper tests the new rule on the marks kept aside" in step
    assert "Testing works with" not in step
    llms = (WEBSITE / "llms.txt").read_text(encoding="utf-8")
    assert "tests a better rule" not in llms  # the Guide line links the steps instead
    assert "re-checks your judge" not in llms
    assert "costs" not in llms
    for page in pages():
        text = _flat(_main(page))
        for gone in ("own terminal", "rule.txt", "Go ahead?", "paid with your own key"):
            assert gone not in text, (page.name, gone)


def test_privacy_says_judgekeeper_only_reads_files():
    local = _flat(_by_id(PRIVACY, "local"))
    assert "judgekeeper only reads your eval results. It never runs your eval tool." in local
    assert "judgekeeper makes no AI call and needs no API key." in local
    for gone in ("temporary copies", "say yes", "asks your eval tool"):
        assert gone not in local, gone


# Phones and touch screens -------------------------------------------------------------------
# Each rule for a phone sits in a block for a narrow or a touch screen, so a laptop shows the
# pages as before (checked with full-page screenshots in Chrome at 1280, 1440 and 1920, Safari
# at 1440 and an iPad at 1024: the same pixels, but for the demo's last button).

FREECHECK = (WEBSITE / "assets" / "freecheck.js").read_text(encoding="utf-8")


def _media(query: str, css: str = CSS) -> str:
    """Every rule inside the blocks `@media <query>`, one after another."""
    inside, at = [], 0
    while (at := css.find(f"@media {query} {{", at)) != -1:
        depth, open_at = 0, css.index("{", at)
        for i in range(open_at, len(css)):
            depth += {"{": 1, "}": -1}.get(css[i], 0)
            if not depth:
                break
        inside.append(css[open_at + 1:i])
        at = i
    return "\n".join(inside)


def _last(selector: str, css: str = CSS) -> str:
    """The declarations of the last rule for `selector`: the one that wins."""
    start = css.rindex(selector + " {")
    return css[start + len(selector) + 2:css.index("}", start)]


def _join(text: str) -> str:
    """site.js's joinLines, run in node."""
    body = JS[JS.index("  function joinLines(text) {"):]
    body = body[:body.index("\n  }\n") + 4]
    code = body + f"\nprocess.stdout.write(JSON.stringify(joinLines({json.dumps(text)})));"
    out = subprocess.run([shutil.which("node"), "-e", code], capture_output=True, text=True,
                         check=True, timeout=30)
    return json.loads(out.stdout)


def test_the_demos_last_button_is_one_label():
    """At every width: "Check your own LLM-as-a-judge" is one piece of text, never two flex
    items with no space between them."""
    (go,) = [el for el in _els(HOME) if "jk-go" in el.classes()]
    (label,) = [el for el in go.children if isinstance(el, Element)]
    assert label.tag == "span" and _flat(label) == "Check your own LLM-as-a-judge"
    assert not [c for c in go.children if isinstance(c, str) and c.strip()]


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node to run site.js")
def test_on_a_phone_the_home_terminal_joins_lines_broken_to_fit_64_columns():
    """A line the screen broke only to fit goes on after the one above it; the command, the
    lines laid out in columns and a line after a full stop stay as they are."""
    text = ("$ judgekeeper\njudgekeeper 1.0.0\n\nEval tool:       promptfoo\nFile:            "
            "results.json\nChecked: your LLM-as-a-judge gave every answer a clear Pass or\nFail."
            "\n  Your LLM-as-a-judge made 8 mistakes. In 4, it said Pass where\n  you said Fail."
            "\n  When you said Pass    7 of 15              1 of 15              Worse\n"
            "  When you said Fail    7 of 15              7 of 15              Not sure\n"
            "Next: grade\nthe answers again.")
    assert _join(text).split("\n") == [
        "$ judgekeeper", "judgekeeper 1.0.0", "", "Eval tool:       promptfoo",
        "File:            results.json",
        "Checked: your LLM-as-a-judge gave every answer a clear Pass or Fail.",
        "  Your LLM-as-a-judge made 8 mistakes. In 4, it said Pass where you said Fail.",
        "  When you said Pass    7 of 15              1 of 15              Worse",
        "  When you said Fail    7 of 15              7 of 15              Not sure",
        "Next: grade the answers again."]
    typing = JS[JS.index("function type("):]
    typing = typing[:typing.index("\n    }\n")]
    assert "narrow() ? joinLines(screens[key])" in typing
    # the box is as tall as the whole screen before the typing starts, and lets go after it
    assert 'out.style.minHeight = out.offsetHeight + "px"' in typing
    assert typing.count('out.style.minHeight = ""') == 2
    # the screen waiting to be typed is joined too, or the box shrinks when the typing starts
    assert "if (narrow()) out.innerHTML = shade(joinLines(screens[screenKey()]));" in JS
    assert "font-size: 14px" in _last(".term-out", _narrow(600))


def test_on_a_phone_the_demo_reads_without_cutting_words():
    """At 480px and below the pill sits above the question, and the end card gives each
    question its own line with the two grades under it, each with its label; no hint of a key
    on a touch screen; the numbers on public datasets do not count up on a phone."""
    small = _narrow(480)
    assert "order: -1" in _last(".jk-row-q .jk-state", small)
    assert "display: none" in _last(".jk-end-list li.head", small)
    assert "white-space: normal" in _last(".jk-end-list .q", small)
    assert "content: attr(data-label)" in _last(".jk-end-list li > b.g::before", small)
    assert 'mine.setAttribute("data-label", "You")' in JS
    assert 'its.setAttribute("data-label", "LLM-as-a-judge")' in JS
    assert '". you you" ". judge judge"' in _last(".jk-end-list li", _narrow(359))
    assert "display: none" in _last(".jk-btn .key, .jk-sub .key", _media("(hover: none)"))
    counts = JS[JS.index("function setUpCounts("):]
    assert "if (narrow()) return;" in counts[:counts.index("new IntersectionObserver")]


def test_on_a_phone_the_text_is_14px_or_more():
    """The labels, the pill, window titles, the terminal and its status bar, code, the
    handy commands and the browser check's result are 14px; the footer, "Tap to enlarge" and the
    lines under the drop box 15px. The five words never go under 14px, and wrap below 360px."""
    phone = _narrow(600)
    for selector in (".jk-label, .jk-state, .jk-end-top .jk-again",
                     ".term-bar, .rt-bar, .term-foot, .steplist .n", ".gx-code, .gm-pre",
                     ".ck-out", ".rt-src"):
        assert "font-size: 14px" in _last(selector, phone), selector
    for selector in (".foot .wrap", ".gx-text .gx-tap", ".ex-or, .fc-kinds, .ck2-term .term-bar"):
        assert "font-size: 15px" in _last(selector, phone), selector
    assert "max(14px, min(17px, calc((100vw - 40px) / 19)))" in _last(".five", _narrow(359))
    assert "white-space: normal" in _last(".b-main, .b-side", _narrow(359))
    # on a phone only, so a laptop's text keeps its exact look: site.js keeps "LLM-as-a-judge"
    # in a step's words whole, and lets a path in a sentence break after each "/"
    breaks = JS[JS.index("function setUpPhoneBreaks("):]
    breaks = breaks[:breaks.index("\n  }\n")]
    assert "if (!narrow()) return;" in breaks
    assert '$all(".steplist .d")' in breaks and 'make("span", "nb", "LLM-as-a-judge")' in breaks
    assert '$all("code.path")' in breaks and 'createElement("wbr")' in breaks


def test_on_a_phone_the_guide_gives_a_command_the_whole_box():
    """At 480px and below a step's number sits in its window's bar; "$" stays on a command's
    first line; Copy shows only its tick (its word stays for a screen reader); a path breaks
    after its "/". At 300px and below the boxes are narrower and a command breaks only at a
    space or after a "/"."""
    small = _narrow(480)
    assert "display: block" in _last(".gl-step", small)
    assert "position: absolute" in _last(".gl-n", small)
    assert "padding-left: 52px" in _last(".sw-bar", small)
    phone = _narrow(600)
    assert "align-items: flex-start" in _last(".cmd code", phone)
    copied = _last(".cmd .copy.done .copied", phone)
    assert "position: absolute" in copied and "clip: rect(0 0 0 0)" in copied
    assert "overflow-wrap: anywhere" in _last(".gx-text code.path", phone)
    paths = [c for c in _all(parse(GUIDE), "code") if "path" in c.classes()]
    assert [c.text() for c in paths] == [".judgekeeper/fix/mistakes.md",
                                         ".judgekeeper/fix/marked-answers.csv"]
    assert "overflow-wrap: normal" in _last(".cmd code, .gx-pair .cmd code", _narrow(300))


def test_on_a_phone_a_picture_opens_over_the_page():
    """At 600px and below a tap on a Guide picture opens it in a dialog 1100px wide that can
    be swiped around, with a Close button 44px tall; the page behind does not scroll. A laptop
    opens the file, as the link says."""
    shots = JS[JS.index("function setUpShots("):]
    shots = shots[:shots.index("\n  }\n")]
    for part in ("if (!narrow()) return;", "e.preventDefault()", "view.showModal()",
                 'make("button", "shot-close", "Close")', "e.target === view",
                 'classList.add("has-view")', 'classList.remove("has-view")'):
        assert part in shots, part
    phone = _narrow(600)
    assert "width: 1100px" in _last(".shot-pane img", phone)
    assert "overflow: auto" in _last(".shot-pane", phone)
    assert "min-height: 44px" in _last(".shot-close", phone)
    assert "overflow: hidden" in _last("html.has-view, html.has-view body", phone)


def test_on_a_touch_screen_links_are_44px_tall():
    """A tablet held in the hand gets the phone's 44px links and buttons; on a phone Home and
    Guide are 44px tall too."""
    coarse = _media("(pointer: coarse)")
    assert "min-height: 44px" in _last(".foot-r a", coarse)
    assert "height: 44px" in _last(".gh", coarse)
    assert "min-height: 44px" in _last(".menu .brand", coarse)
    assert "min-height: 44px" in _last(".menu-l a", _phone())


def test_on_a_phone_the_browser_check_shows_the_whole_result():
    """Clear sits under the drop box, the result is part of the page (no scroll inside it),
    "$ judgekeeper" is one line, an example's result comes into view, a phone says "tap",
    a file's name breaks between words, and "·" never ends a line."""
    phone = _phone()
    assert "position: static" in _last(".fc-clear", phone)
    assert "transform: none" in _last(".fc-loaded", phone)
    assert "max-height: none" in _last(".ck2-term .ck-out", phone)
    assert "flex-direction: row" in _last(".fc-term .ln-cmd", phone)
    assert "command.classList.add('ln-cmd')" in FREECHECK
    assert "term.scrollIntoView({ block: 'start' })" in FREECHECK
    assert "media('(hover: none)')) verb.textContent = 'tap'" in FREECHECK
    assert "overflow-wrap: anywhere" in _last(".fc-loaded .fc-main b")
    assert "word-break" not in _last(".fc-loaded .fc-main b")
    (kinds,) = [el for el in _els(CHECK) if "fc-kinds" in el.classes() and "JSONL" in el.text()]
    assert kinds.text() == "promptfoo\xa0· DeepEval\xa0· CSV\xa0· TSV\xa0· JSONL"


def test_on_a_phone_privacy_lists_its_parts_in_rows():
    nav = _last(".g-nav", _narrow(860))
    assert "flex-wrap: wrap" in nav and "overflow-x: visible" in nav


def test_at_240px_the_header_and_boxes_fit():
    """A 360px Android with its text made bigger shows the page at 240px: narrower margins,
    a smaller logo and GitHub button, titles and links that wrap, and no window dots."""
    tiny = _narrow(300)
    assert "max(12px" in _last(".wrap", tiny)
    assert "font-size: 18px" in _last(".menu .brand", tiny)
    assert "padding: 0 10px" in _last(".gh", tiny)
    assert "white-space: normal" in _last(".rt-title, .term-title", tiny)
    assert "white-space: normal" in _last(".tf-link", tiny)
    assert "display: none" in _last(".rt-bar::before, .term-bar::before", tiny)


def test_every_page_colours_the_phones_browser_bar():
    for page in [*pages(), NOT_FOUND]:
        metas = [el for el in parse(page).iter() if el.attrs.get("name") == "theme-color"]
        assert [m.attrs["content"] for m in metas] == ["#0b0c0e"], page.name
    assert "--bg: #0b0c0e" in CSS
