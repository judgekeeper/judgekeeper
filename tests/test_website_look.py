"""The look every page shares, and the parts of each page the design pins.

- The frame: the head lines, the menu and the footer that scripts/site_frame.py writes.
- Dark only: the product's dark colours, no switch, no light rules, nothing kept in the browser.
- Fonts from the site only: Manrope and JetBrains Mono with their licences; no ligatures in
  monospace, so "->" shows as typed.
- Motion: only the few moving parts the design names, and none of them under reduced motion.
- Phone: tables and code scroll inside their box; the browser check's lines wrap.
- Each page's own parts: Home, the Guide, the browser check and Privacy.

The tests run no JavaScript; they read the HTML and CSS.
"""

from __future__ import annotations

import html
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
TRADEMARK_NOTE = ("judgekeeper and the judgekeeper logo are [trademarks](https://github.com/"
                  "judgekeeper/judgekeeper/blob/main/TRADEMARKS.md) of Sathvik Thota. The "
                  "Apache-2.0 license covers the code, not the name or logo.")  # word for word
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
    """The declarations of the first rule for `selector` (written `selector { ... }`, alone or
    in a list; `.jk-state` is not found in `.jk-row-t .jk-state {`)."""
    found = re.search(r"(?m)(?:^|[{},])[ \t]*" + re.escape(selector) + r" \{", css)
    if not found:
        raise ValueError(f"no rule for {selector}")
    start = found.end() - 2 - len(selector)
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

def test_the_website_tm_is_styled_as_the_tool_pages_tm():
    """One ™ style wherever it follows the wordmark (src/judgekeeper/look.py has the same rule)."""
    from tests.test_product_pages import TM_RULE

    css = (WEBSITE / "assets" / "style.css").read_text(encoding="utf-8")
    assert TM_RULE in " ".join(css.split())


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
        assert brand.attrs["href"] == "index.html" and _flat(brand) == "judgekeeper™"
        assert _all(brand, "svg", "logo"), page.name
        assert len(_all(brand, "sup")) == 1, f"{page.name}: one ™, after the name, none on the logo"
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
        assert _flat(copy) == "© 2026 Sathvik Thota", page.name  # the license is its own link
        tail = [c for c in links.children if isinstance(c, Element)][-2:]
        assert [(el.tag, _flat(el)) for el in tail] == [
            ("a", "Apache-2.0 license"), ("span", "© 2026 Sathvik Thota")], page.name
        assert not _all(footer, "p", "note") and TRADEMARK_NOTE not in _flat(footer), page.name
        assert not _all(footer, "h2") and "More" not in _flat(footer), page.name


def test_the_footer_names_match_the_licence():
    assert "Copyright 2026 Sathvik Thota" in (ROOT / "NOTICE").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "<h1>judgekeeper <sup><sup><sub>™</sub></sup></sup></h1>" in readme and readme.rstrip().endswith(TRADEMARK_NOTE)
    assert "Apache-2.0" in (ROOT / "TRADEMARKS.md").read_text(encoding="utf-8")
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
                    if el.tag in {"link", "script", "img"} and url and el.attrs.get("rel") != "canonical":
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
        "green": "#10B981", "green-fill": "#047857", "red": "#e5484d", "red-fill": "#c73b40",
        "slate": "#1E293B"}  # the logo's two colours: its green and its dark half


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
    # the four words show focus with their own green line, so no ring around them
    assert "outline: none" in _rule(".five a:focus-visible")
    assert ".five a:focus-visible::after" in CSS
    # the one ring is in the text colour; no other focus rule brings back a white box
    assert [s for s, d in _rules() if "focus" in s and "var(--fg)" in d] == [":focus-visible"]
    assert ".skip:focus" in CSS


# Motion ------------------------------------------------------------------------------------

COLOUR_ONLY = {"color", "background", "background-color", "border-color", "filter",
               "text-decoration-color"}


def test_the_only_motion_is_the_underline_the_typing_and_the_cursor():
    """Hover colours may fade; nothing else moves, slides, turns or appears by itself. The green
    line under the four words grows, a click on a word scrolls to the steps, the steps'
    terminal types its screen, the browser check's cursor blinks, and its example cards lift
    1px on hover (none of it under reduced motion). The demo waits for a click: it never plays
    by itself, and no number on Home counts up."""
    # one animation: the browser check's cursor blinks
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
            if selector.endswith(".ex-card"):
                assert value == "border-color 140ms ease, transform 140ms ease"
                continue
            assert props <= COLOUR_ONLY, (selector, value)
    reduce = CSS[CSS.index("@media (prefers-reduced-motion: reduce)"):]
    assert "*, *::before, *::after { transition: none !important" in reduce[:200]
    # the moving parts in the script, and all of them stop under reduced motion
    assert JS.count("prefers-reduced-motion: reduce") == 1
    assert "function type(" in JS and "function sweep(" in JS
    assert "if (reduce || !animate)" in JS and "if (!reduce && words.length" in JS
    assert "function autoplay(" not in JS  # the demo plays only when you mark
    assert "function setUpCounts(" not in JS and ".rt-n" not in JS
    assert not [el for page in pages() for el in parse(page).iter() if "rt-n" in el.classes()]
    assert JS.count("smooth") == 1 and 'behavior: reduce ? "auto" : "smooth"' in JS
    for gone in ("IntersectionObserver(function (e) { reveal", "animate(", "count-up",
                 "parallax", "pointermove", "demo-cursor", "hl-draw"):
        assert gone not in JS + CSS, gone


def test_each_screen_types_once_and_replay_types_it_again():
    typing = JS[JS.index("function type("):]
    assert "if (reduce || !animate)" in typing  # at once: reduced motion, or seen before
    assert "seen[key]" in JS and 'replay.addEventListener("click"' in JS


# Phone -------------------------------------------------------------------------------------

def test_tables_and_code_scroll_inside_their_box():
    for page in pages():  # no page has a table or a code block now; one would need a box
        assert not _all(parse(page), "table") and not _all(parse(page), "pre", "gx-code"), page.name
    assert "overflow: auto" in _rule(".term-out")
    assert "overflow-x: auto" in _rule(".cmd code")
    assert "overflow-y: auto" in _rule(".ck2-term .ck-out")
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
    running past the box's edge; Copy still copies it on one line. The Guide's step commands
    and the record() line wrap at every width, and each handy command's words sit above it."""
    rule = _rule(".cmd code", _narrow(600))
    assert "white-space: pre-wrap" in rule and "overflow-wrap: anywhere" in rule
    for selector in (".gd-panel .cmd code", ".cmd.prompt code"):
        assert "overflow-wrap: anywhere" in _rule(selector), selector
    assert "white-space: normal" in _rule(".gd-panel .cmd code")
    assert "white-space: pre-wrap" in _rule(".cmd.prompt code")
    (record,) = [c for c in _all(parse(GUIDE), "code") if "record(" in c.text()]
    assert "prompt" in record.parent.classes()  # it wraps like a prompt, not cut at the edge
    for cell in _all(_by_id(GUIDE, "misc"), "div", "cmd"):
        words = [c for c in cell.parent.children if isinstance(c, Element)]
        assert [el.tag for el in words] == ["span", "div"], _flat(cell)  # the words, then it
    assert "flex-direction: column" in _rule(".gd-handy-grid > div")
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
STEPS = [("find", "Read", "Read your eval results and your labels, or mark answers Pass or Fail in your browser."),
         ("measure", "Measure", "See how often your agent-as-a-judge or LLM-as-a-judge agrees with you, and how much the people marking agree with each other."),
         ("fix", "Fix", "Write a better rule for your LLM-as-a-judge, or a better prompt for your agent or chatbot, and test it on marks kept aside."),
         ("check", "Re-check", "Change your LLM-as-a-judge, agent or chatbot, and see if it gets better or worse.")]


def _main(page: Path) -> Element:
    return next(el for el in _els(page) if el.tag == "main")


def test_home_is_the_hero_with_the_demo_the_steps_the_public_datasets_and_the_closing_row():
    sections = [el for el in _main(HOME).children if isinstance(el, Element)]
    assert [s.classes() for s in sections] == [{"hero", "home-hero"}, {"steps"}, {"real"},
                                               {"close"}]
    assert [s.attrs.get("id") for s in sections] == [None, "steps", "real", "ai-check"]
    assert "demo-sec" not in CSS  # the demo sits in the hero, not in a section of its own


def test_the_closing_row_is_eval_results_then_answers_with_no_llm_as_a_judge():
    """Two columns on thin lines, no window: "Have eval results?" with the button to the
    browser check, then "No LLM-as-a-judge?" with the button to the Guide's steps."""
    (box,) = _all(_main(HOME), "section", "close")
    assert box.attrs.get("id") == "ai-check"
    cols = _all(box, "div", "close-col")
    assert [_flat(_all(c, "h2")[0]) for c in cols] == ["Have eval results?", "No LLM-as-a-judge?"]
    assert [_flat(_all(c, "p")[0]) for c in cols] == [
        ("Check the LLM-as-a-judge that grades your agent or chatbot. Your file stays on your "
         "computer."), "Mark the answers of your agent or chatbot Pass or Fail."]
    links = [(a.attrs["href"], a.classes(), _flat(a)) for a in _all(box, "a")]
    assert links == [("check.html", {"b-main"}, "Try it in your browser"),
                     ("start.html#ai-check", {"b-main"}, "See the steps")]
    assert _by_id(GUIDE, "ai-check").attrs.get("role") == "tabpanel"  # the link lands on it
    assert not _all(box, "script") and not _all(box, "div", "rt-bar") and not _all(box, "p", "close-prompt")
    for gone in (".close-win", ".close-box", ".rt-win", ".ai-win", ".close-prompt"):
        assert gone not in CSS, gone


def test_the_demo_card_keeps_one_height():
    """The card is as tall as its tallest answer or its end card, measured on load, when the
    fonts arrive and on resize, so nothing below it moves while you mark."""
    lock = JS[JS.index("function lockHeight("):]
    lock = lock[:lock.index("\n    }\n")]
    assert "items.forEach" in lock and 'classList.add("is-end")' in lock
    assert "fillList(" in lock  # the end card is measured with its list filled
    assert 'card.style.minHeight = tallest + "px"' in lock
    assert 'addEventListener("resize"' in JS and "document.fonts.ready.then(lockHeight)" in JS
    # the room the card gets sits under the answer, or around the end card
    assert "flex: 1" in _rule(".jk-live") and "flex: 1" in _rule(".jk-row-a")
    assert "flex: 1" in _rule(".jk-card.is-end .jk-end")


def test_the_hero_is_the_headline_the_four_words_two_buttons_and_the_demo():
    hero = _all(_main(HOME), "section", "hero")[0]
    (h1,) = _all(hero, "h1")
    assert _flat(h1) == "Check agents and chatbots with human judgment."
    assert [br.classes() for br in _all(h1, "br")] == [{"h1-br"}]  # two lines on a laptop
    # "human judgment." in green, kept on one line; no line is drawn under it
    (hl,) = _all(h1, "span", "hl")
    assert _flat(hl) == "human judgment."
    assert "color: var(--green)" in _rule(".hl") and "white-space: nowrap" in _rule(".hl")
    assert not _all(hl, "svg") and "hl-line" not in CSS
    (five,) = _all(hero, "nav", "five")
    words = [(a.attrs["href"], a.attrs["data-step"], _flat(a)) for a in _all(five, "a")]
    assert words == [("#steps", key, f"{label}.") for key, label, _ in STEPS]
    assert [a.classes() for a in _all(five, "a")] == [{"is-on"}, set(), set(), set()]
    buttons = [(a.attrs["href"], a.classes(), _flat(a)) for a in _all(hero, "a")
               if {"b-main", "b-side"} & a.classes()]
    assert buttons == [("start.html", {"b-main"}, "Get started"),
                       ("check.html", {"b-side"}, "Try it in your browser")]
    sub_line = ("You mark what's right. See how often your agent or chatbot, and its "
                "agent-as-a-judge or LLM-as-a-judge, agree with you, and whether each change "
                "makes that better or worse.")
    assert [p for p in _all(hero, "p", None)
            if not any("jk-card" in a.classes() for a in p.ancestors())] == []
    # the sub-line sits under the steps heading, not in the hero
    (steps_lede,) = _all(_main(HOME), "p", "steps-lede")
    assert _flat(steps_lede) == sub_line
    assert not _all(hero, "ul", "hero-facts") and "hero-facts" not in CSS
    # the demo sits at the hero's right, with no light around it
    (right,) = _all(hero, "div", "hero-r")
    (card,) = _all(right, "section", "jk-card")
    assert card.attrs["id"] == "demo" and "box-shadow" not in _rule(".jk-card")
    # the chosen step's green line; a hovered or focused word gets one too
    assert "var(--green)" in _rule(".five a::after")
    assert ".five a.is-on::after" in CSS and ".five a:hover::after" in CSS


def test_the_demo_card_is_drawn_like_the_marking_page():
    demo = _by_id(HOME, "demo")
    assert demo.attrs.get("aria-label") == "Live demo of the marking page"
    labels = [_flat(el) for el in _by_id(HOME, "d-pane-answer").iter() if "jk-label" in el.classes()]
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
                  '["You and your ", {nb: "LLM-as-a-judge"}, " disagreed on ", [n], " of "',
                  '["You and your ", {nb: "LLM-as-a-judge"}, " agreed on all ", [items.length]',
                  '"LLM-as-a-judge"',
                  'ArrowLeft: "fail"', 'ArrowRight: "pass"'):
        assert words in JS, words
    for gone in ('"Not marked yet"', '"Skipped"', "your judge"):
        assert gone not in JS, gone
    # the count sits in a small pill; the result line wraps in two even lines when it must
    state = _rule(".jk-state")
    for wanted in ("border-radius: 999px", "font-variant-numeric: tabular-nums",
                   "font-size: 12.5px", "color: var(--fg)"):
        assert wanted in state, wanted
    assert "align-self: flex-start" in _rule(".jk-row-q .jk-state")
    assert "margin-bottom: 22px" in _rule(".jk-end-top")
    assert "font-size: clamp(16px, 1.4vw, 18px)" in _rule(".jk-end-head h2")
    assert "white-space: nowrap" in _rule(".jk-end-head h2 .mono")
    assert "text-wrap: balance" in _rule(".jk-end-head h2", CSS[CSS.index(".jk-end-head h2 .mono"):])
    assert ".jk-end-head h2 { white-space: nowrap; }" not in CSS
    assert "justify-content: center" in _rule(".jk-end-actions")
    # the judge's grade stays hidden while you mark, as on the real page
    assert "Your judge said" not in JS
    sizes = {"jk-question": "font-size: 24px", "jk-answer": "font-size: 20px",
             "jk-btn": "height: 50px"}
    for cls, size in sizes.items():
        assert size in _rule(f".{cls}"), cls


def _raw(el: Element) -> str:
    """The text of an element with its spaces as written (no collapsing inside)."""
    return "".join(c if isinstance(c, str) else _raw(c) for c in el.children)


def test_the_steps_read_cleanly_as_plain_text():
    # Google glues the number, the bold name and the sentence together: hidden ". " and ": "
    # between them keep it readable. The page looks the same: they use the .sr class.
    (tabs,) = _all(_main(HOME), "div", "steplist")
    texts = [" ".join(_raw(b).split()) for b in _all(tabs, "button")]
    assert texts == [f"{n}. {name}: {words}" for n, (_, name, words) in enumerate(STEPS, 1)]
    assert texts[0] == "1. Read: Read your eval results and your labels, or mark answers Pass or Fail in your browser."
    assert "data-nosnippet" in tabs.attrs  # Google leaves the step list out of its snippet
    assert "data-nosnippet" in _by_id(HOME, "demo").attrs  # and the marking demo
    for b in _all(tabs, "button"):
        hidden = [s for s in b.iter() if s.tag == "span" and "sr" in s.classes()]
        assert [_raw(s) for s in hidden] == [". ", ": "]
        assert all(s.attrs.get("aria-hidden") is None for s in hidden)


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
    assert found == [(key, name + ":", words) for key, name, words in STEPS]  # ": " is hidden
    assert [b.attrs.get("aria-selected") for b in buttons] == [
        "true", "false", "false", "false"]
    assert [b.attrs.get("tabindex") for b in buttons] == ["0", "-1", "-1", "-1"]
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
    assert _flat(_all(foot, "span", "tf-text")[0]) == "Example with made-up answers"
    (link,) = _all(foot, "a", "tf-link")
    assert (link.attrs["href"], _flat(link)) == ("examples/site-example/report.html",
                                                 "see its report")
    assert 'content: " ↗"' in _rule(".tf-link::after")
    assert "dashed" in _rule(".tf-link")
    bar = _rule(".term-foot")
    assert "height: 38px" in bar and "border-top: 1px solid var(--line)" in bar
    assert "background: var(--term-bar)" in bar and "font-size: 12px" in bar
    assert "min-height: 44px" in _rule(".term-foot", _phone())  # room for its link
    assert "white-space: normal" in _rule(".tf-text", _phone())  # never cut with "…"


def test_the_closing_box_points_to_the_browser_check():
    close = _all(_main(HOME), "section", "close")[-1]
    assert _flat(_all(close, "h2")[0]) == "Have eval results?"
    assert _flat(_all(close, "p")[0]) == ("Check the LLM-as-a-judge that grades your agent or "
                                          "chatbot. Your file stays on your computer.")
    (button, _) = _all(close, "a", "b-main")
    assert (button.attrs["href"], _flat(button)) == ("check.html", "Try it in your browser")


def test_the_closing_row_continues_the_public_datasets_lines():
    """The closing row sits right under the results: a thin line above it, and the footer's
    line closes it."""
    assert "padding-top: 0" in _rule(".real + .close .wrap")
    assert "border-top: 1px solid var(--line)" in _rule(".close-row")
    assert "border-block" not in _rule(".close-row")


def test_the_public_datasets_are_three_tabs_each_with_its_numbers_and_report():
    """"On public datasets.": a list of three tabs at the left (above, on a narrow screen), and
    a window at the right with the chosen one's numbers, a line on what they show, and a
    status bar naming the labels with a link to the report. Nothing counts up."""
    (real,) = _all(_main(HOME), "section", "real")
    assert real.attrs.get("id") == "real"
    assert _flat(_all(real, "h2")[0]) == "On public datasets."
    (tabs,) = _all(real, "div", "ds-list")
    assert (tabs.attrs.get("role"), tabs.attrs.get("aria-orientation")) == ("tablist", "vertical")
    buttons = _all(tabs, "button")
    assert [(b.attrs["id"], b.attrs["aria-controls"], b.attrs["aria-selected"],
             _flat(_all(b, "b")[0]), _flat(_all(b, "span")[0])) for b in buttons] == [
        ("ds-tab-a", "ds-a", "true", "Agent runs", "AgentProcessBench"),
        ("ds-tab-b", "ds-b", "false", "Chatbot answers", "XSTest"),
        ("ds-tab-c", "ds-c", "false", "judgekeeper itself", "3 public datasets")]
    assert _flat(_all(real, "span", "term-title")[0]) == "public datasets"
    panels = _all(real, "div", "ds-panel")
    assert [(el.attrs["id"], el.attrs["role"], el.attrs["aria-labelledby"]) for el in panels] == [
        ("ds-a", "tabpanel", "ds-tab-a"), ("ds-b", "tabpanel", "ds-tab-b"),
        ("ds-c", "tabpanel", "ds-tab-c")]
    feet = [(_flat(_all(el, "span", "tf-text")[0]), _flat(_all(el, "a", "tf-link")[0]))
            for el in panels]
    assert feet == [("249 agent runs, labelled by people", "see its report"),
                    ("447 answers, labelled by two people", "see its report"),
                    ("Over 1,000 checks per setup, on 3 datasets", "see its report")]
    # each dataset is the one its report names (the numbers: tests/test_website.py)
    for el, name in zip(panels, ("AgentProcessBench", "XSTest", "over 1,000 checks")):
        (link,) = _all(el, "a", "tf-link")
        report = (ROOT / link.attrs["href"].split("/blob/main/", 1)[1]).read_text(encoding="utf-8")
        assert name in report, name
    assert "3 public datasets" in (ROOT / "docs/examples/real-data-check/report.md").read_text(
        encoding="utf-8")
    assert "grid-template-columns: repeat(3, minmax(0, 1fr))" in _rule(".ds-nums.three")
    assert "grid-template-columns: 340px minmax(0, 1fr)" in _rule(".ds-grid")
    assert _rule(".ds-grid", _narrow(860)).strip() == "grid-template-columns: 1fr;"
    # the tabs swap panels in place: a hidden one keeps its room, so nothing below jumps
    assert "visibility: hidden" in _rule(".ds-panel.is-off") and "grid-area: 1 / 1" in _rule(".ds-panel")
    assert "function setUpDatasets()" in JS and "setUpDatasets();" in JS
    assert not _all(real, "a", "rt") and not _all(real, "span", "waf")


def test_the_demo_card_has_a_tab_for_answers_and_one_for_agent_steps():
    """Mark answers is the marking demo; Mark steps works like `judgekeeper steps`: click the
    first wrong step of each run, then see where you and the agent-as-a-judge picked
    differently. The tabs show only with JavaScript; without it the card is the marking demo
    alone, and with it the card opens on Mark answers."""
    tabs = _by_id(HOME, "d-tabs")
    assert tabs.attrs.get("role") == "tablist" and "hidden" in tabs.attrs
    assert [(b.attrs["id"], b.attrs["aria-controls"], b.attrs["aria-selected"], _flat(b))
            for b in _all(tabs, "button")] == [
        ("d-tab-answer", "d-pane-answer", "true", "Mark answers"),
        ("d-tab-steps", "d-pane-steps", "false", "Mark steps")]
    assert 'show("answer");  // the card opens on Mark answers' in JS
    assert "hidden" not in _by_id(HOME, "d-pane-answer").attrs
    steps = _by_id(HOME, "d-pane-steps")
    assert steps.attrs.get("role") == "tabpanel" and "hidden" in steps.attrs
    assert [_flat(el) for el in steps.iter() if "jk-label" in el.classes()] == [
        "Agent run", "Click the first wrong step", "Your result"]
    assert [_flat(_by_id(HOME, i)) for i in ("s-fine", "s-undo", "s-again")] == [
        "All steps are fine 0", "Undo Z", "↻ Try again"]
    (go,) = _all(_by_id(HOME, "s-end"), "a", "jk-go")
    assert (go.attrs["href"], _flat(go)) == ("start.html#agent-steps", "Check your agent-as-a-judge")
    assert _by_id(GUIDE, "agent-steps").attrs.get("role") == "tabpanel"
    assert _by_id(HOME, "s-list").attrs.get("aria-label") == (
        "Your first wrong steps and the agent-as-a-judge's")
    # each run: the task, its steps, and the step the agent-as-a-judge picked (0: none wrong)
    runs = json.loads(_by_id(HOME, "demo-runs").text())
    assert len(runs) == 4
    for task, run_steps, picked in runs:
        assert task and 3 <= len(run_steps) <= 4 and 0 <= picked <= len(run_steps)
    assert 0 in [picked for *_, picked in runs]  # one run where all steps are fine
    for words in ('["You and your ", {nb: "agent-as-a-judge"}, " disagreed on ", [n], " of "',
                  '["You and your ", {nb: "agent-as-a-judge"}, " agreed on all ", [runs.length]',
                  '"Agent run"', '"Agent-as-a-judge"', '"None"', '$("d-tabs").hidden = false'):
        assert words in JS, words
    assert "reviewer" not in JS.lower()
    lock = JS[JS.index("function lockHeight("):]
    assert "tallestRun()" in lock[:lock.index("\n    }\n")]  # one height for both tabs
    assert "display: none" in _rule(".jk-send") and "display: none" in _rule(".jk-pane.is-done .jk-sl")
    assert "var(--green)" in _rule(".jk-tab::after") and "transition" not in _rule(".jk-tab::after")


def test_the_demo_shows_the_check_right_after_each_mark():
    """The point of the demo lands on the first click: once you mark an answer (or pick a
    run's first wrong step), the card says what the check said and whether it agrees with
    you, then waits for Next. Your own mark is still made before you see the check's."""
    said = _by_id(HOME, "d-said")
    assert "jk-said" in said.classes()
    assert _by_id(HOME, "d-verdict").attrs.get("aria-live") == "polite"
    assert _flat(_by_id(HOME, "d-next")) == "Next answer →"
    assert "jk-acts" in _by_id(HOME, "d-acts").classes()
    assert _flat(_by_id(HOME, "s-next")) == "Next →"
    assert _by_id(HOME, "s-match").attrs.get("aria-live") == "polite"
    for words in ('"Agrees with you"', '"Disagrees with you"', '"See your result ',
                  '"LLM-as-a-judge: "', '"Agent-as-a-judge: "', '"You"', '"Both"'):
        assert words in JS, words
    # while the check's answer shows, the mark buttons give way to it, and Skip waits
    assert "display: none" in _rule(".jk-said")
    assert "display: none" in _rule(".is-said .jk-acts")
    assert "display: grid" in _rule(".is-said .jk-said")
    assert "display: none" in _rule(".is-said #d-skip")
    assert "display: none" in _rule(".is-said #s-fine")
    assert "height: 50px" in _rule(".jk-verdict")  # as tall as the buttons it replaces
    # the card's one height covers each step of each run with the widest tag
    run_height = JS[JS.index("function tallestRun("):]
    assert "renderRun(k + 1)" in run_height[:run_height.index("\n    }\n")]
    # → or Enter moves on; nothing else marks while the check's answer shows
    assert 'e.key === "Enter"' in JS


def test_every_window_has_the_three_dots_and_a_centred_title():
    """The demo card, the closing box and the Guide's install card share the terminal's bar."""
    bar = _rule(".rt-bar")
    assert "background: var(--term-bar)" in bar and "font-family: var(--mono)" in bar
    assert "var(--term-dot)" in _rule(".rt-bar::before")
    assert "text-align: center" in _rule(".rt-title")


def test_the_demo_card_is_a_window_called_marking_page():
    """Without JavaScript the bar shows the title; with it, the two tabs take its place, so
    the card is no taller than the marking demo alone."""
    (card,) = _all(_main(HOME), "section", "jk-card")
    first = next(el for el in card.children if isinstance(el, Element))
    assert {"rt-bar", "jk-bar"} <= first.classes()
    (title,) = _all(first, "span", "rt-title")
    assert _flat(title) == "marking page" and title.attrs.get("aria-hidden") == "true"
    assert [el.attrs.get("role") for el in first.iter() if el.attrs.get("id") == "d-tabs"] == ["tablist"]
    assert '$("d-title").hidden = true' in JS
    assert "flex: none" in _rule(".jk-bar")


def test_the_homes_windows_share_the_guides_slate_and_the_chosen_step_is_green():
    """The marking card, the example project and the public datasets: each in the Guide's
    slate panel. The chosen step's number is green in a plain ring."""
    for selector in (".jk-card", ".steps-grid .term", ".ds-win", ".gd", ".gwin", ".ck2-term"):
        assert "background: var(--slate-panel)" in _rule(selector), selector
    for selector in (".jk-card", ".gd", ".gwin"):
        assert "border: 1px solid var(--slate)" in _rule(selector), selector
    chosen = _rule(".steplist button[aria-selected=true] .n")
    for part in ("color: var(--green)", "border-color: var(--green)"):
        assert part in chosen, part
    assert "box-shadow" not in chosen  # a plain ring, no glow
    assert "border-radius: 50%" in _rule(".steplist .n")
    assert "border-left-color: var(--green)" in _rule(".steplist button[aria-selected=true]")
    assert not [sel for sel, d in _rules() if sel.startswith(".steplist") and "transition" in d]
    # text in the windows keeps 4.5 to 1 on the slate panel over the page
    t = _tokens()
    panel = "#" + "".join(f"{round(.4 * int(t['slate'][i:i + 2], 16) + .6 * int(t['bg'][i:i + 2], 16)):02x}"
                          for i in (1, 3, 5))
    for text in ("fg", "muted", "green", "red"):
        assert _contrast(t[text], panel) >= 4.5, (text, panel)


# The Guide ------------------------------------------------------------------------------------

REFERENCE_MD = f"{GITHUB}/blob/main/docs/reference.md"
EXAMPLES = f"{GITHUB}/blob/main/docs/examples"
# "What do you have?": each tab's id, its label and line, and its heading
GUIDE_TABS = [("results", "Eval results", "graded by an LLM-as-a-judge"),
              ("ai-check", "Answers only", "no LLM-as-a-judge"),
              ("agent-steps", "Agent runs", "the steps of each run")]
# each tab's steps: the word, its words, and the commands beside them
GUIDE_STEPS = {
    "results": [
        ("Read.", ("Run it in your project folder. It finds your results and opens the marking "
                   "page. Mark each answer Pass or Fail. While you mark, the grade from your "
                   "LLM-as-a-judge stays hidden."), ["judgekeeper"]),
        ("Measure.", ("See how often your LLM-as-a-judge agrees with you, and the answers where "
                      "you disagree. Too early to tell? Mark more."), ["judgekeeper mark"]),
        ("Fix.", ("Get the answers it got wrong and write a better rule. Grade the marked answers "
                  "again with the new rule, and judgekeeper tests it on marks kept aside."),
         ["judgekeeper fix", "judgekeeper fix new-results.json"]),
        ("Re-check.", ("Changed its model or rule? Grade your marked answers again and see if it "
                       "still agrees with you. No new marking."),
         ["judgekeeper check new-results.json"])],
    "ai-check": [
        ("Read.", ("Run it in your project folder. Mark each answer Pass or Fail, and add a "
                   "reason to the failed ones."), ["judgekeeper"]),
        ("Measure.", "From 10 marks, see how many passed, with a range.", []),
        ("Fix.", ("Get the failed answers, apart from the half kept aside, with a prompt for your "
                  "coding agent to improve the prompt of your agent or chatbot."),
         ["judgekeeper fix"]),
        ("Re-check.", ("Save the new answers over the old file and mark them. On the answers kept "
                       "aside, see how many were fixed and how many broke."), ["judgekeeper"])],
    "agent-steps": [
        ("Read.", ("Opens a page with each run’s steps. Click the first wrong step, or All steps "
                   "are fine."), ["judgekeeper steps runs.jsonl"]),
        ("Measure.", ("Add the picks of your agent-as-a-judge to see how often it finds the same "
                      "first wrong step as you."),
         ["judgekeeper steps runs.jsonl --reviewer picks.jsonl"]),
        ("Re-check.", ("Change your agent-as-a-judge, save its new picks and run it again. No new "
                       "marking."), ["judgekeeper steps runs.jsonl --reviewer new-picks.jsonl"])]}


def _panel(wanted: str) -> Element:
    (panel,) = [el for el in _all(_main(GUIDE), "div", "gd-panel") if el.attrs["id"] == wanted]
    return panel


def _codes(root: Element) -> list[str]:
    return [_flat(c) for c in _all(root, "code") if "cmd" in c.parent.classes()]


def _anchor(heading: str) -> str:
    """The anchor GitHub gives a Markdown heading."""
    return re.sub(r"[^\w\- ]", "", heading.lower()).replace(" ", "-")


def test_the_guide_says_how_to_check_an_agent_as_a_judge_step_by_step():
    """The Agent runs tab: a JSONL file of runs, then Read, Measure and Re-check with
    `judgekeeper steps`, the picks file, a Label Studio export, an example and the part of the
    reference on steps."""
    panel = _panel("agent-steps")
    assert _flat(_all(panel, "h3", "gd-h")[0]) == "Agent runs"
    assert _flat(_all(panel, "p", "gd-intro")[0]) == (
        "Runs of your agent in a JSONL file, one run per line with an id and its steps.")
    rows = [(_flat(_all(r, "b")[0]), _flat(_all(r, "span")[0]), _codes(r))
            for r in _all(panel, "div", "gd-more-row")]
    assert rows == [
        ("The picks file", "One line per run. 0 means all steps are fine.",
         ['{"id": "run-1", "first_wrong_step": 3, "model": "my-judge"}']),
        ("Already labelled in Label Studio", "judgekeeper reads the project’s JSON export.",
         ["judgekeeper steps export.json"])]
    # the picks line is one judgekeeper reads: its keys are the ones `steps` takes
    pick = json.loads(rows[0][2][0])
    assert set(pick) == {"id", "first_wrong_step", "model"}
    from judgekeeper import steps
    source = Path(steps.__file__).read_text(encoding="utf-8")
    for key in pick:
        assert f'"{key}"' in source, key
    links = [(a.attrs["href"], _flat(a)) for a in _all(_all(panel, "div", "gd-foot")[0], "a")]
    heading = "steps: mark an agent run's first wrong step, then check an agent-as-a-judge"
    assert links == [(f"{EXAMPLES}/agent-steps/README.md", "See an example run"),
                     (f"{REFERENCE_MD}#{_anchor(heading)}", "Full reference")]
    # the link lands on that part of the reference
    reference = (ROOT / "docs" / "reference.md").read_text(encoding="utf-8")
    assert f"\n## {heading}\n" in reference


def test_the_guide_is_the_install_what_you_have_and_handy_commands():
    sections = [el for el in _main(GUIDE).children if isinstance(el, Element)]
    assert [s.classes() for s in sections] == [{"hero", "gx-hero"}, {"gd-sec"},
                                               {"gd-sec", "gd-handy"}]
    assert [s.attrs["id"] for s in sections] == ["install", "steps", "misc"]  # judgekeeper
    hero = sections[0]                                       # prints start.html#install
    (h1,) = _all(hero, "h1")
    assert _flat(h1) == "Install judgekeeper in your project."
    assert [_flat(s) for s in _all(h1, "span", "h-brand")] == ["judgekeeper"]
    assert "color: var(--green)" in _rule(".h-brand")
    assert "font-size: clamp(42px, calc(11vw - 80px), 62px)" in _rule(".gx-hero h1")
    mid = CSS[CSS.index("@media (max-width: 1100px) {"):]
    mid = mid[:mid.index("\n}\n")]
    assert "font-size: clamp(42px, 4.2vw, 52px)" in _rule(".gx-hero h1", mid)
    # three facts under the headline; the list keeps the old #keys anchor
    (facts,) = _all(hero, "ul", "gx-facts")
    assert facts.attrs.get("id") == "keys" and "gf" in facts.classes()
    assert [_flat(li) for li in _all(facts, "li")] == [
        "No API key needed", "Runs locally", "Open source"]
    # the install card: a window with a tab each for pip, uv and a coding agent; without
    # JavaScript the three show one after another
    (card,) = _all(hero, "div", "gx-install")
    assert "gwin" in card.classes()
    (tabs,) = _all(card, "div", "gi-tabs")
    assert tabs.attrs.get("role") == "tablist" and "hidden" in tabs.attrs
    assert [(b.attrs["id"], b.attrs["aria-controls"], _flat(b)) for b in _all(tabs, "button")] == [
        ("gi-tab-gi-pip", "gi-pip", "pip"), ("gi-tab-gi-uv", "gi-uv", "uv"),
        ("gi-tab-gi-agent", "gi-agent", "Coding agent")]
    panels = _all(card, "div", "gi-panel")
    assert [(p.attrs["id"], p.attrs["role"], p.attrs["aria-labelledby"]) for p in panels] == [
        ("gi-pip", "tabpanel", "gi-tab-gi-pip"), ("gi-uv", "tabpanel", "gi-tab-gi-uv"),
        ("gi-agent", "tabpanel", "gi-tab-gi-agent")]
    # pip into the project's virtual environment: a system Python refuses it (PEP 668)
    assert [[_flat(h) for h in _all(p, "p", "gx-way-h")] for p in panels] == [
        ["Install in your project’s virtual environment", "Run in your project folder"],
        ["Run in your project folder, with nothing to install first (uv)",
         "Or add it to your project, then run uv run judgekeeper"],
        ["Give your coding agent this prompt"]]
    # one command per box, so nobody pastes the two pip lines as one
    assert [_codes(p) for p in panels] == [
        ["pip install judgekeeper", "judgekeeper"], ["uvx judgekeeper", "uv add --dev judgekeeper"],
        ["Follow www.judgekeeper.com/start.html to run judgekeeper on my project."]]
    assert _flat(_all(panels[2], "p", "gi-note")[0]) == (
        "It installs judgekeeper, runs it and gives you the marking page link. You mark, then it "
        "explains the result.")
    assert _flat(_all(card, "p", "gi-foot")[0]) == "macOS, Linux and Windows. Python 3.11 to 3.14."
    assert not _all(card, "div", "cmd-2") and ".cmd-2" not in CSS
    # no side list and no bar over the steps: the tabs say where you are
    assert not [n for n in _all(_main(GUIDE), "nav")] and "sp-rail" not in CSS
    assert _flat(_all(sections[1], "h2")[0]) == "What do you have?"
    assert _flat(_all(sections[2], "h2")[0]) == "Handy commands"
    handy = [(_flat(_all(d, "span")[0]), _codes(d)[0])
             for d in _all(sections[2], "div") if d.parent.classes() == {"gd-handy-grid"}]
    assert handy == [("Close the marking page", "judgekeeper --stop"),
                     ("Start over (old marks are kept)", "judgekeeper --new"),
                     ("Get the link, no browser", "judgekeeper --no-browser"),
                     ("See every option", "judgekeeper --help")]
    assert "grid-template-columns: repeat(2, minmax(0, 1fr))" in _rule(".gd-handy-grid")
    assert "padding-block: 64px 56px" in _rule(".gx-hero .wrap")
    assert "clip: rect(0 0 0 0)" in _rule(".sr")


def test_your_own_file_or_code_is_two_short_ways_and_a_link_for_the_rest():
    """Under the Eval results steps: a three-column file and its command, the one record()
    line, and labels you already have; scores, pass marks and every other option are in the
    reference."""
    panel = _panel("results")
    (more,) = _all(panel, "div", "gd-more")
    assert _flat(_all(more, "h4")[0]) == "Other starting points"
    rows = _all(more, "div", "gd-more-row")
    assert rows[0].attrs.get("id") == "own-format"  # judgekeeper prints start.html#own-format
    said = [(_flat(_all(r, "b")[0]), _flat(_all(r, "span")[0]), _codes(r)) for r in rows]
    assert said == [
        ("Your own file", "A CSV, TSV or JSONL file with input, output and verdict columns.",
         ["judgekeeper results.csv"]),
        ("Grading in your own code", "Add this line after each grade, then run judgekeeper.",
         ["judgekeeper.record(input=question, output=answer, verdict=grade)"]),
        ("Already have Pass or Fail labels",
         "A CSV, TSV or JSONL file with an answer and a label column, or a Label Studio export.",
         ["judgekeeper --labels your-labels.csv"])]
    links = [(a.attrs["href"], _flat(a)) for a in _all(_all(panel, "div", "gd-foot")[0], "a")]
    assert links == [(f"{EXAMPLES}/label-studio/README.md", "See an example run"),
                     (REFERENCE_MD, "Full reference")]
    reference = (ROOT / "docs" / "reference.md").read_text(encoding="utf-8")
    assert "\n## How grades are read\n" in reference  # scores and pass marks
    text = GUIDE.read_text(encoding="utf-8")
    for gone in ("--pass-if", "pass_mark=", "can't test a new rule"):
        assert gone not in text, gone


def test_the_guides_record_line_saves_what_judgekeeper_reads(tmp_path, monkeypatch):
    """The line the Guide shows, run as it is after a grade (with judgekeeper imported), gives
    answers judgekeeper finds."""
    from judgekeeper import recorder, start

    (code,) = [c for c in _all(_by_id(GUIDE, "results"), "code") if "record(" in c.text()]
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'app'\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("JUDGEKEEPER_RECORD", raising=False)
    recorder._reset()
    try:
        for i, grade in enumerate(["pass", "fail"]):
            space = {"question": f"Do you ship to {i}?", "answer": "Yes.", "grade": grade}
            exec("import judgekeeper\n" + code.text(), space)  # noqa: S102 - the Guide's line
    finally:
        recorder._reset()
    found = start.find_judge(tmp_path)
    assert (found.pool.n_pass, found.pool.n_fail) == (1, 1)


def test_what_you_have_is_three_tabs_and_a_link_opens_its_tab():
    """"What do you have?": a tab each for eval results, answers only and agent runs, over one
    box. Without JavaScript the three panels show one after another, each under its heading;
    with it one shows, and a link to a part of a panel (#own-format, #agent-steps) opens it."""
    (box,) = _all(_main(GUIDE), "div", "gd")
    (tabs,) = _all(box, "div", "gd-tabs")
    assert tabs.attrs.get("role") == "tablist" and "hidden" in tabs.attrs
    assert tabs.attrs.get("aria-label") == "What do you have?"
    found = [(b.attrs["aria-controls"], _flat(_all(b, "b")[0]), _flat(_all(b, "span")[0]))
             for b in _all(tabs, "button")]
    assert found == GUIDE_TABS
    assert [b.attrs["id"] for b in _all(tabs, "button")] == [f"gd-tab-{i}" for i, *_ in GUIDE_TABS]
    panels = _all(box, "div", "gd-panel")
    assert [(p.attrs["id"], p.attrs["role"], p.attrs["aria-labelledby"],
             _flat(_all(p, "h3", "gd-h")[0])) for p in panels] == [
        (i, "tabpanel", f"gd-tab-{i}", label) for i, label, _ in GUIDE_TABS]
    # the chosen tab: green under it; a panel's own heading shows only without the tabs
    assert "border-bottom-color: var(--green)" in _rule(".gd-tabs button[aria-selected=true]")
    assert "display: none" in _rule(".tabs-on .gd-h")
    assert "display: none" in _rule(".gd-panel.is-off")
    tabs_js = JS[JS.index("function setUpTabs("):]
    tabs_js = tabs_js[:tabs_js.index("\n  }\n")]
    for part in ("list.hidden = false", 'classList.add("tabs-on")', "location.hash",
                 '"hashchange"', '"ArrowRight"', '"ArrowLeft"'):
        assert part in tabs_js, part
    assert 'function setUpGuide() { $all(".gd-tabs, .gi-tabs").forEach(setUpTabs); }' in JS
    # each place judgekeeper or the site links to is inside a panel, so it opens that tab
    for anchor in ("own-format", "question-prompt"):
        assert any(a.attrs.get("role") == "tabpanel" for a in _by_id(GUIDE, anchor).ancestors())


def test_the_guide_shows_each_step_as_its_word_its_words_and_its_commands_beside_them():
    from judgekeeper import no_grades

    for key, steps in GUIDE_STEPS.items():
        (ol,) = _all(_panel(key), "ol", "gd-steps")
        items = _all(ol, "li")
        found = []
        for li in items:
            say, cmds = [el for el in li.children if isinstance(el, Element)]
            assert "gd-say" in say.classes() and "gd-cmds" in cmds.classes(), key
            (word,) = _all(say, "h3", "gd-word")
            (dot,) = _all(word, "span", "sp-dot")  # the full stop green, like the logo's tick
            assert _flat(dot) == "." and word.children[-1] is dot
            (words,) = _all(say, "p")
            assert not _all(say, "div", "cmd"), key  # every command is beside the words
            found.append((_flat(word), _flat(words), _codes(cmds)))
        assert found == steps, key
    assert f"From {no_grades.MIN_MARKS} marks" in GUIDE_STEPS["ai-check"][1][1]
    assert "color: var(--green)" in _rule(".sp-dot")
    assert "font-weight: 800" in _rule(".gd-word") and "color: var(--green)" in _rule(".gd-word")
    # words beside commands on a laptop; one under the other on a narrow screen
    assert "grid-template-columns: minmax(0, 1fr) minmax(0, 440px)" in _rule(".gd-steps li")
    narrow = _rule(".gd-steps li, .gd-more-row, .gd-handy-grid", _narrow(900))
    assert "grid-template-columns: minmax(0, 1fr)" in narrow
    assert not _all(_main(GUIDE), "details") and not _all(_main(GUIDE), "table")
    text = GUIDE.read_text(encoding="utf-8")
    for gone in ("<template", "steplist", "t-out", "learn.html", "data-panel", "npx", "<figure"):
        assert gone not in text, gone


def test_running_text_is_never_justified():
    """Lines stay left-aligned at every width: justified text gets big holes between words."""
    assert "text-align: justify" not in CSS
    assert not [sel for sel, _ in _rules() if sel.startswith("#ai-check")]


def test_the_guides_answers_only_tab_says_which_answers_and_what_the_prompt_costs():
    """The Answers only tab: answers with no grades, the four steps, and for no answers yet
    a prompt for your coding agent, which says that running the agent or chatbot may use
    your API credits."""
    from judgekeeper import front

    panel = _panel("ai-check")
    assert _flat(_all(panel, "p", "gd-intro")[0]) == (
        "Answers from your agent or chatbot, with no grades: a CSV, TSV or JSONL file with input "
        "and output columns.")
    row = _by_id(GUIDE, "question-prompt")
    assert _flat(_all(row, "b")[0]) == "No answers yet"
    assert _flat(_all(row, "span")[0]) == (
        "Your coding agent writes about 40 test questions with you, runs your agent or chatbot "
        "on them and saves the answers. This may use your API credits.")
    (button,) = _all(row, "button", "copy")
    assert button.attrs["aria-label"] == "Copy the prompt"
    assert _flat(_all(button, "span", "gd-copy-say")[0]) == "Copy the prompt"
    (code,) = _all(row, "code")
    assert "hidden" in code.attrs  # the button copies it; the page shows its words instead
    assert code.text() == front.QUESTIONS_PROMPT.format(program="judgekeeper")  # word for word
    links = [(a.attrs["href"], _flat(a)) for a in _all(_all(panel, "div", "gd-foot")[0], "a")]
    assert links == [(f"{EXAMPLES}/ai-check/README.md", "See an example run"),
                     (REFERENCE_MD, "Full reference")]


def test_the_guides_commands_look_like_terminal_lines():
    """A green "$" before each one-line command, drawn by CSS so Copy copies the command
    alone; a prompt or a line of code has none."""
    assert 'content: "$"' in _rule(".gx .cmd code::before")
    assert "var(--green)" in _rule(".gx .cmd code::before")
    assert "content: none" in _rule(".gx .cmd.prompt code::before")
    assert "background: var(--term-bg)" in _rule(".gx .cmd")
    assert "code.textContent" in JS  # what Copy copies: never the "$"
    prompts = [_flat(_all(b, "code")[0]) for b in _all(_main(GUIDE), "div", "prompt")]
    assert prompts == ["Follow www.judgekeeper.com/start.html to run judgekeeper on my project.",
                       "judgekeeper.record(input=question, output=answer, verdict=grade)",
                       '{"id": "run-1", "first_wrong_step": 3, "model": "my-judge"}']
    assert "gx" in _main(GUIDE).classes()


def test_every_command_box_has_a_copy_button_that_says_copied():
    boxes = [box for page in (GUIDE, CHECK) for box in _all(parse(page), "div", "cmd")]
    install = ["pip install judgekeeper", "judgekeeper", "uvx judgekeeper",
               "uv add --dev judgekeeper",
               "Follow www.judgekeeper.com/start.html to run judgekeeper on my project."]
    steps = [c for key, _, _ in GUIDE_TABS for _, _, cmds in GUIDE_STEPS[key] for c in cmds]
    more = {"results": ["judgekeeper results.csv",
                        "judgekeeper.record(input=question, output=answer, verdict=grade)",
                        "judgekeeper --labels your-labels.csv"],
            "ai-check": [_flat(_all(_by_id(GUIDE, "question-prompt"), "code")[0])],
            "agent-steps": ['{"id": "run-1", "first_wrong_step": 3, "model": "my-judge"}',
                            "judgekeeper steps export.json"]}
    by_tab = [c for key, _, _ in GUIDE_TABS for c in
              [*[c for _, _, cmds in GUIDE_STEPS[key] for c in cmds], *more[key]]]
    handy = ["judgekeeper --stop", "judgekeeper --new", "judgekeeper --no-browser",
             "judgekeeper --help"]
    assert [_flat(_all(b, "code")[0]) for b in boxes] == [*install, *by_tab, *handy]
    assert len(by_tab) == len(steps) + 6  # the check page has none: its status bar links here
    named = {"judgekeeper.record(input=question, output=answer, verdict=grade)":
             "Copy code: judgekeeper.record()",
             install[-1]: "Copy the prompt for your coding agent",
             more["ai-check"][0]: "Copy the prompt",
             more["agent-steps"][0]: "Copy an example picks line"}
    for box in boxes:  # each button is named by what it copies
        (button,) = _all(box, "button", "copy")
        command = _flat(_all(box, "code")[0])
        assert "data-copy" in button.attrs
        assert button.attrs["aria-label"] == named.get(command, f"Copy command: {command}")
        assert _all(button, "svg", "i-copy") and _all(button, "svg", "i-tick")
        (said,) = _all(button, "span", "copied")
        assert said.attrs.get("aria-live") == "polite"
    assert '"Copied"' in JS and "clipboard" in JS
    # the tick and "Copied" show in green inside the button, never over the command
    assert "color: var(--green)" in _rule(".cmd .copy.done")
    assert "position" not in _rule(".cmd .copied") and "display: inline" in _rule(
        ".cmd .copy.done .copied")
    assert "padding: 12px 18px" in _rule(".cmd code")
    assert "padding: 11px 14px" in _rule(".gd-panel .cmd code")
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
                  "Information Commissioner's Office", "Last updated: 2026-10-30"):
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
    assert _flat(h1) == "Try judgekeeper in your browser."
    assert [_flat(s) for s in _all(h1, "span", "nb")] == ["in your browser."]
    assert [_flat(s) for s in _all(h1, "span", "hl")] == ["browser."]  # green, as on Home
    titles = re.findall(r'<title>([^<]*)</title>|content="([^"]*\| judgekeeper)"',
                        CHECK.read_text(encoding="utf-8"))
    assert {a or b for a, b in titles} == {"Try judgekeeper in your browser | judgekeeper"}
    # the drop box: an upload icon and what to drop; after a file, the file and Clear
    drop = _by_id(CHECK, "fc-drop")
    assert drop.tag == "button" and drop.attrs.get("type") == "button"
    (empty,) = _all(drop, "span", "fc-empty")
    (loaded,) = _all(drop, "span", "fc-loaded")
    assert "hidden" not in empty.attrs and "hidden" in loaded.attrs
    assert [_flat(el) for el in empty.iter() if el.tag in ("b", "span") and el.classes() & {
        "ck2-or"} or el.tag == "b"] == ["Drop your file here", "or click to choose one"]
    (kinds,) = _all(empty, "span", "fc-kinds")
    assert "ck-pills" in kinds.classes()  # each kind in a pill, as on the Guide
    assert [_flat(el) for el in kinds.children if isinstance(el, Element)] == [
        "promptfoo", "DeepEval", "CSV", "TSV", "JSONL"]
    assert _by_id(CHECK, "fc-verb").text() == "click"  # a phone says "tap" (freecheck.js)
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
    # the heading, the drop box, then the examples: no lines between them; the box lists the
    # files it reads and the terminal's status bar links to the install
    assert [(el.tag, sorted(el.classes())) for el in left.children
            if isinstance(el, Element) and "sr" not in el.classes()] == [
        ("h1", []), ("div", ["fc-zone"]), ("div", ["fc-try"])]
    assert not _all(left, "p", "gx-small")
    # the drop box and the terminal in the slate of Home's windows
    assert "background: var(--slate-panel)" in _rule(".ck2-drop")
    term_look = _rule(".ck2-term")
    assert "background: var(--slate-panel)" in term_look and "border-color: var(--slate)" in term_look
    # the examples, under a divider; no command row (the status bar links to the Guide)
    (divider,) = _all(left, "p", "ex-or")
    assert _flat(divider) == "or try an example"
    cards = _all(left, "button", "ex-card")
    assert [_flat(_all(c, "b")[0]) for c in cards] == ["Eval results", "Answers only", "Agent runs"]
    assert [c.attrs.get("data-example-file") for c in cards] == [
        "shop-answers.csv", "shop-answers-no-grades.csv", "agent-runs.jsonl"]
    assert not _all(main, "div", "ck-run") and "uvx" not in _flat(main)
    # the terminal: the file's name in its bar once read, the waiting screen, the result
    assert _flat(_by_id(CHECK, "ck-title")) == "your file"
    wait = _by_id(CHECK, "ck-wait")
    (ghost,) = _all(wait, "span", "ck-ghost")
    assert ghost.attrs.get("aria-hidden") == "true"
    waiting = wait.text()[:wait.text().index(ghost.text())]
    assert " ".join(waiting.split()) == (
        "$ judgekeeper Step 1 of 4: Read Waiting for your file. Drop it in the box, or try an "
        "example. ▋")
    result = _by_id(CHECK, "fc-result")
    assert result.attrs.get("aria-live") == "polite" and not result.children
    # the status bar: the file stays here, and the next step is the Guide's install
    (foot,) = _all(term, "div", "term-foot")
    assert _flat(_all(foot, "span", "tf-text")[0]) == "your file stays on your computer"
    (link,) = _all(foot, "a")
    assert link.attrs["href"] == "start.html" and "tf-link" in link.classes()
    assert _flat(link) == "next step: install judgekeeper →"
    script = (WEBSITE / "assets" / "freecheck.js").read_text(encoding="utf-8")
    assert ('NOT_RECOGNISED = "This isn\'t a results file this page can read. It reads '
            'promptfoo, DeepEval, CSV, TSV and JSONL files, and agent runs. For other results, '
            'run `uvx judgekeeper` in your project.";') in script


def test_waiting_terminal_uses_the_codes_labels(tmp_path):
    """The faint lines while waiting are the labels the check then prints for answers and for
    agent runs, values dotted; the page's script sets the same lines."""
    from tests.test_freecheck_parity import NODE, browser

    ghost = _all(_by_id(CHECK, "ck-wait"), "span", "ck-ghost")[0].text()
    labels = [line.split("·")[0].rstrip() for line in ghost.strip("\n").splitlines()]
    assert labels == ["File:", "Answers or runs:", "LLM-as-a-judge:", "", "This file has", "",
                      "First answer or run in your file:", ""]
    if NODE is None:
        pytest.skip("needs node to run the page's free check")
    script = subprocess.run([NODE, "-e", "process.stdout.write(require(process.argv[1]).GHOST)",
                             str(WEBSITE / "assets" / "freecheck.js")], capture_output=True,
                            text=True, check=True, encoding="utf-8").stdout
    assert script == ghost
    answers = tmp_path / "answers.csv"
    answers.write_text("input,output\nq1,a1\nq2,a2\n", encoding="utf-8")
    runs = tmp_path / "runs.jsonl"
    runs.write_text('{"id": "r1", "steps": [{"role": "user", "content": "Hi."}]}\n',
                    encoding="utf-8")
    printed = ["\n".join(browser(path)["lines"]) for path in (answers, runs)]
    for label, means in (("File:", ("File:", "File:")), ("LLM-as-a-judge:", ("LLM-as-a-judge:",)),
                         ("Answers or runs:", ("Answers:", "Runs:")),
                         ("This file has", ("This file has", "This file has")),
                         ("First answer or run in your file:",
                          ("First answer in your file:", "First run in your file:"))):
        for said, start in zip(printed, means, strict=False):
            assert f"\n{start}" in "\n" + said, label  # the check prints each, as a line's start


def test_the_browser_check_is_two_columns_and_its_terminal_fits_its_lines():
    wrap = _rule(".ck2 .wrap")
    for part in ("grid-template-columns: minmax(0, 1fr) minmax(0, 1.15fr)", "gap: 28px 48px",
                 "align-items: start"):
        assert part in wrap, part
    assert "clamp(34px, 3.6vw, 48px)" in _rule(".ck2-l h1") and "font-weight: 800" in _rule(
        ".ck2-l h1")
    # as tall as its lines, so no empty space under the waiting ones; a long check scrolls
    assert "min-height" not in _rule(".ck2-term")
    out = _rule(".ck2-term .ck-out")
    assert "flex: none" in out and "max-height: 560px" in out and "overflow-y: auto" in out
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


def test_the_browser_check_lines_keep_each_label_line_whole_on_a_phone():
    """Wider than a phone a line wraps inside the terminal. On a phone each line stays whole,
    a value beside its label ("File:", "Answers:"), and the terminal scrolls sideways for it;
    only the Next line wraps."""
    term = _rule(".fc-term")
    assert "white-space: pre-wrap" in term and "overflow-wrap: anywhere" in term
    phone = CSS[CSS.index("@media (max-width: 760px) {\n  .ck2 .wrap"):]
    phone = phone[:phone.index("\n}\n")]
    assert "overflow-x" not in term
    assert "overflow-x: auto" in _rule(".fc-term", phone)
    assert "width: max-content" in _rule(".fc-term .ln:not(.ln-next)", phone)
    assert "white-space: pre;" in _rule(".fc-term .ln:not(.ln-next) > span", phone)
    assert "flex-wrap" not in phone and ".pad" not in phone
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

def test_home_and_the_guide_show_no_pictures():
    """Home shows its demo and terminals, and the Guide its commands: no screenshot on either,
    and no link to one (the browser check has none either)."""
    for page in (HOME, GUIDE, CHECK):
        assert not _all(_main(page), "img") and not _all(_main(page), "figure"), page.name
        assert not [a for a in _all(_main(page), "a") if "assets/shots/" in a.attrs.get("href", "")]
    assert "gx-tap" not in CSS
    # and no picture viewer is left behind for them
    for gone in ("setUpShots", "shot-view", "shot-close", "has-view", "gx-shot"):
        assert gone not in JS and gone not in CSS, gone
    assert "--green-glow" not in CSS


def test_testing_a_new_rule_is_said_for_every_eval_tool():
    """fix reads the new results as step 1 reads results, so a new rule is tested the same way
    for every eval tool, and fix prints how to grade the answers again for each (fix.REGRADE,
    fix.OWN). No page limits testing to some tools, or says judgekeeper asks the
    LLM-as-a-judge or keeps a rule in rule.txt."""
    assert set(fix.REGRADE) == {"promptfoo", "deepeval", "inspect", "mlflow"} and fix.OWN
    meta = [el.attrs["content"] for el in parse(HOME).iter()
            if el.tag == "meta" and "description" in el.attrs.get("name", "")
            + el.attrs.get("property", "")]
    short = ("judgekeeper checks your AI agent or chatbot with human judgment. You mark what's "
             "right, and it shows how often an agent-as-a-judge or an LLM-as-a-judge (an AI "
             "model that grades another model's work) agrees with you, and where it goes wrong.")
    assert meta == [short + (" Read. Measure. Fix. Re-check. Open source; it reads "
                             "the results your eval tool saved."), short, short]
    for json_ld in (el for el in _els(HOME) if el.attrs.get("type") == "application/ld+json"):
        assert short in json_ld.text() and "Read. Measure." not in json_ld.text()
    assert "test it on marks kept aside." in _flat(_by_id(HOME, "tab-fix"))
    assert "promptfoo" not in _flat(_by_id(HOME, "tab-fix"))
    (step,) = [_flat(li) for li in _all(_by_id(GUIDE, "results"), "li")
               if _flat(li).startswith("Fix.")]
    assert "judgekeeper fix new-results.json" in step
    assert "Grade the marked answers again with the new rule" in step
    assert "judgekeeper tests it on marks kept aside" in step
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
# Each rule for a phone sits in a block for a narrow or a touch screen, so a laptop keeps the
# same layout.

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
    """At every width: each tab's last button ("Check your own LLM-as-a-judge", "Check your
    agent-as-a-judge") is one piece of text, never two flex items with no space between them."""
    buttons = [el for el in _els(HOME) if "jk-go" in el.classes()]
    labels = []
    for go in buttons:
        (label,) = [el for el in go.children if isinstance(el, Element)]
        assert label.tag == "span"
        assert not [c for c in go.children if isinstance(c, str) and c.strip()]
        labels.append(_flat(label))
    assert labels == ["Check your own LLM-as-a-judge", "Check your agent-as-a-judge"]


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


def test_on_a_phone_the_text_is_14px_or_more():
    """The labels, the pill, window titles, the terminal and its status bar, and the browser
    check's result and example cards are 14px; the footer and the lines under the drop box
    15px. The four words never go under 14px, and wrap below 360px."""
    phone = _narrow(600)
    for selector in (".jk-label, .jk-state, .jk-end-top .jk-again",
                     ".term-bar, .rt-bar, .term-foot, .steplist .n", ".term-out", ".ck-out",
                     ".ex-t span"):
        assert "font-size: 14px" in _last(selector, phone), selector
    for selector in (".foot .wrap", ".ex-or, .fc-kinds, .ck2-term .term-bar"):
        assert "font-size: 15px" in _last(selector, phone), selector
    assert "max(14px, min(17px, calc((100vw - 40px) / 19)))" in _last(".five", _narrow(359))
    assert "white-space: normal" in _last(".b-main, .b-side", _narrow(359))
    # on a phone only, so a laptop's text keeps its exact look: site.js keeps "LLM-as-a-judge"
    # in a step's words whole, and lets a path in a sentence break after each "/"
    breaks = JS[JS.index("function setUpPhoneBreaks("):]
    breaks = breaks[:breaks.index("\n  }\n")]
    assert "if (!narrow()) return;" in breaks
    assert '$all(".steplist .d")' in breaks and 'make("span", "nb", "LLM-as-a-judge")' in breaks
    assert '$all("code.path")' not in breaks and 'createElement("wbr")' not in breaks

@pytest.mark.skipif(shutil.which("node") is None, reason="needs node to run site.js")
def test_on_a_phone_a_step_keeps_its_unbroken_words():
    """site.js's phone breaks, run in node on each step's words as Home has them: a span the
    page already has (the Measure step's "agent-as-a-judge") stays, the words stay the same, and
    an "LLM-as-a-judge" not yet in a span gets one."""
    body = JS[JS.index("  function setUpPhoneBreaks() {"):]
    body = body[:body.index("\n  }\n") + 4]
    steps = []
    for d in re.findall(r'<span class="d">(.*?)</span></span></button>', HOME.read_text(encoding="utf-8")):
        nodes = []
        for nb, text in re.findall(r'<span class="nb">([^<]*)</span>|([^<]+)', d):
            nodes.append(["nb", nb] if nb else ["#", html.unescape(text)])
        steps.append(nodes)
    assert len(steps) == 4 and ["nb", "agent-as-a-judge"] in steps[1]
    steps.append([["#", "Check your LLM-as-a-judge and its LLM-as-a-judge rule."]])
    stub = r"""
function T(v) { return {nodeType: 3, nodeValue: v}; }
function El(cls) {
  var el = {nodeType: 1, className: cls, childNodes: [],
    appendChild: function (n) { el.childNodes.push(n); return n; },
    insertBefore: function (n, ref) { el.childNodes.splice(el.childNodes.indexOf(ref), 0, n); },
    removeChild: function (n) { el.childNodes.splice(el.childNodes.indexOf(n), 1); }};
  Object.defineProperty(el, "textContent", {
    get: function () { return el.childNodes.map(function (n) {
      return n.nodeType === 3 ? n.nodeValue : n.textContent; }).join(""); },
    set: function (v) { el.childNodes = v ? [T(v)] : []; }});
  return el;
}
function make(tag, cls, text) { var el = El(cls); if (text !== undefined) el.textContent = text;
  return el; }
var document = {createTextNode: T};
function narrow() { return true; }
var ds = STEPS.map(function (nodes) {
  var d = El("d");
  nodes.forEach(function (n) { d.appendChild(n[0] === "nb" ? make("span", "nb", n[1]) : T(n[1])); });
  return d;
});
function $all() { return ds; }
"""
    scenario = r"""
setUpPhoneBreaks();
process.stdout.write(JSON.stringify(ds.map(function (d) {
  return d.childNodes.map(function (n) {
    return n.nodeType === 3 ? ["#", n.nodeValue] : [n.className, n.textContent]; }); })));
"""
    code = ("(function () { var STEPS = " + json.dumps(steps) + ";" + stub + body + "\n"
            + scenario + "})();")
    out = subprocess.run([shutil.which("node"), "-e", code],
                         capture_output=True, text=True, check=True, timeout=30)
    got = json.loads(out.stdout)
    assert got[:4] == steps[:4]
    assert got[4] == [["#", "Check your "], ["nb", "LLM-as-a-judge"], ["#", " and its "],
                      ["nb", "LLM-as-a-judge"], ["#", " rule."]]


def test_on_a_phone_the_guide_gives_a_command_the_whole_box():
    """On a phone the Guide has a 20px gutter and every command box takes the whole width of
    its column; "$" stays on a command's first line; Copy shows only its tick (its word stays
    for a screen reader). At 300px and below the boxes are narrower and a command breaks only
    at a space or after a "/"."""
    assert "max(20px" in _rule("body:has(> main.gx) .wrap")
    for selector in (".gi-panel .cmd", ".gd-panel .cmd", ".gd-handy-grid .cmd"):
        rule = _rule(selector)
        assert "width: 100%" in rule and "min-width: 0" in rule, selector
    phone = _narrow(600)
    assert "align-items: flex-start" in _last(".cmd code", phone)
    copied = _last(".cmd .copy.done .copied", phone)
    assert "position: absolute" in copied and "clip: rect(0 0 0 0)" in copied
    assert not [c for c in _all(parse(GUIDE), "code") if "path" in c.classes()]
    assert "overflow-wrap: normal" in _last(".cmd code", _narrow(300))
    # each tab's two buttons: side by side, and on a phone the second goes under the first
    assert "flex-wrap" not in _rule(".gd-foot") and "flex-wrap: wrap" in _rule(".gd-foot", phone)


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
    a file's name breaks between words, and the file kinds wrap only between their pills."""
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
    # the kinds are pills that wrap between pills, never inside one
    (kinds,) = [el for el in _els(CHECK) if "fc-kinds" in el.classes() and "JSONL" in el.text()]
    assert "·" not in kinds.text() and "flex-wrap: wrap" in _rule(".ck-pills")


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
