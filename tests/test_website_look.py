"""The look every page shares, and the parts of each page the design pins.

- The frame: every page carries the head lines, the menu and the footer that
  scripts/site_frame.py writes. The menu is Home, the Guide, the logo and GitHub; the footer is
  the logo, Full reference (docs/reference.md on GitHub), Privacy, Trademarks, Security and the
  copyright.
- Dark only: the product's dark colours, no switch, no light rules, nothing kept in the browser.
- Fonts from the site only: Manrope and JetBrains Mono with their licences; no ligatures in
  monospace, so "->" shows as typed.
- Motion: only the green line under the five words, the terminal typing, the scroll to the
  steps and the browser check's waiting cursor, and none of them under reduced motion.
- Phone: tables and code scroll inside their box; the browser check's lines wrap.
- Home: the hero, the demo card that works like the marking page, the steps with their
  terminal, the closing box. The Guide: Home's hero with the install, the 5 steps as a list, three
  cards. The browser check: Home's hero with the drop card and a terminal. Privacy: its side
  list.

The tests run no JavaScript: the pages were checked in Chrome at 1440 and 390 wide.
"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

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
        assert found == [*LEGAL, (f"{GITHUB}/blob/main/LICENSE", "MIT license")], page.name
        (copy,) = _all(links, "span", "copy")
        assert _flat(copy) == "© 2026 Sathvik Thota · MIT license", page.name
        assert not _all(footer, "h2") and "More" not in _flat(footer), page.name


def test_the_footer_names_match_the_licence():
    assert "Copyright (c) 2026 Sathvik Thota" in (ROOT / "LICENSE").read_text(encoding="utf-8")
    for path in ("TRADEMARKS.md", "SECURITY.md", "LICENSE"):
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

DARK = {"bg": "#0b0c0e", "fg": "#e6e8eb", "muted": "#8b919a", "faint": "#585e68",
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
    assert "outline: 2px solid var(--green)" in ring and "border-radius: 4px" in ring
    assert "border-radius: 12px" in _rule(".jk-card:focus-visible")
    # the five words show focus with their own green line, so no ring around them
    assert "outline: none" in _rule(".five a:focus-visible")
    assert ".five a:focus-visible::after" in CSS
    # no rule brings back the white box
    assert not [s for s, d in _rules() if "focus" in s and "var(--fg)" in d]
    assert ".skip:focus" in CSS


# Motion ------------------------------------------------------------------------------------

COLOUR_ONLY = {"color", "background", "background-color", "border-color", "filter",
               "text-decoration-color"}


def test_the_only_motion_is_the_underline_and_the_terminal_typing():
    """Hover colours may fade; nothing else moves, slides, turns or appears by itself. The green
    line under the five words grows, and a click on a word scrolls to the steps."""
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
            assert props <= COLOUR_ONLY, (selector, value)
    reduce = CSS[CSS.index("@media (prefers-reduced-motion: reduce)"):]
    assert "*, *::before, *::after { transition: none !important" in reduce[:200]
    # the two moving parts, and both stop under reduced motion
    assert JS.count("prefers-reduced-motion: reduce") == 1
    assert "function type(" in JS and "function sweep(" in JS
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
STEPS = [("find", "Find", "Finds your eval results and the judge that graded them."),
         ("mark", "Mark", "You mark answers Pass or Fail in your browser."),
         ("measure", "Measure",
          "Shows how often your judge agrees with you, and where it goes wrong."),
         ("fix", "Fix",
          ("If your judge needs work, write a better rule. For promptfoo, DeepEval, Inspect AI "
          "and MLflow, test it on marks kept aside.")),
         ("check", "Re-check", "After you change your judge, see if it still agrees with you.")]


def _main(page: Path) -> Element:
    return next(el for el in _els(page) if el.tag == "main")


def test_home_is_the_hero_the_steps_and_the_closing_box():
    sections = [el for el in _main(HOME).children if isinstance(el, Element)]
    assert [s.classes() for s in sections] == [{"hero"}, {"steps"}, {"close"}]


def test_the_demo_card_keeps_one_height():
    """The card is as tall as its tallest answer or its end card, measured on load, when the
    fonts arrive and on resize, so nothing below it moves while you mark (checked in Chrome at
    1440, 1000 and 390 wide: the same height for every answer and the end card)."""
    lock = JS[JS.index("function lockHeight("):]
    lock = lock[:lock.index("\n    }\n")]
    assert "items.forEach" in lock and 'classList.add("is-end")' in lock
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
                       ("check.html", {"b-side"}, "Check in your browser")]
    assert not _all(hero, "p", None) or all(
        any("jk-card" in a.classes() for a in p.ancestors()) for p in _all(hero, "p"))
    # the chosen step's green line, which gives way while another word is hovered or focused
    assert "var(--green)" in _rule(".five a::after")
    assert ".five a.is-on::after" in CSS and ".five:hover a.is-on:not(:hover)::after" in CSS


def test_the_demo_card_is_drawn_like_the_marking_page():
    demo = _by_id(HOME, "demo")
    assert demo.attrs.get("aria-label") == "Live demo of the marking page"
    labels = [_flat(el) for el in demo.iter() if "jk-label" in el.classes()]
    assert labels == ["Question", "Answer"]
    assert _flat(_by_id(HOME, "d-state")) == "Not marked yet"
    assert _by_id(HOME, "d-state").attrs.get("aria-live") == "polite"
    assert [_flat(_by_id(HOME, i)) for i in ("d-fail", "d-pass", "d-skip", "d-undo")] == [
        "Fail ←", "Pass →", "Skip this one S", "Undo Z"]
    # Without JavaScript the card shows the first answer.
    assert [_flat(_by_id(HOME, "d-q")), _flat(_by_id(HOME, "d-a"))] == DEMO[0][:2]
    data = _by_id(HOME, "demo-items")
    assert data.tag == "script" and data.attrs.get("type") == "application/json"
    assert json.loads(data.text()) == DEMO
    end = _by_id(HOME, "d-end")
    assert _flat(_all(end, "h2")[0]) == "You marked every answer."
    (go,) = _all(end, "a", "jk-go")
    assert (go.attrs["href"], _flat(go)) == ("start.html", "Check your own LLM-as-a-judge")
    assert _flat(_by_id(HOME, "d-again")) == "↻ Try again"
    for words in ('"Marked "', '"Skipped"', '"Not marked yet"',
                  '"You and your judge disagreed on "', '" of "',
                  '"You and your judge agreed on all "', 'ArrowLeft: "fail"',
                  'ArrowRight: "pass"'):
        assert words in JS, words
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
    # under the terminal, its source: no link to the Guide
    (more,) = _all(steps, "p", "steps-more")
    assert "example project (made-up answers)" in _flat(more)
    (link,) = _all(more, "a")
    assert (link.attrs["href"], _flat(link)) == ("examples/site-example/report.html", "its report")


def test_the_closing_box_points_to_the_browser_check():
    close = _all(_main(HOME), "section", "close")[0]
    assert _flat(_all(close, "h2")[0]) == "Have eval results?"
    assert _flat(_all(close, "p")[0]) == ("Check your LLM-as-a-judge. Your file stays on your "
                                          "computer.")
    (button,) = _all(close, "a", "b-main")
    assert (button.attrs["href"], _flat(button)) == ("check.html", "Check in your browser")


# The Guide ------------------------------------------------------------------------------------

REFERENCE_MD = f"{GITHUB}/blob/main/docs/reference.md"
GUIDE_STEPS = [("step-find", "Find your results"), ("step-mark", "Mark answers Pass or Fail"),
               ("step-measure", "Read your result"),
               ("step-fix", "Write a better rule and test it"),
               ("step-check", "Re-check after you change your judge")]


def test_the_guide_is_the_install_the_five_steps_and_three_cards():
    sections = [el for el in _main(GUIDE).children if isinstance(el, Element)]
    assert [s.classes() for s in sections] == [{"hero", "gx-hero"}, {"gx-steps"}, {"gx-more"}]
    hero = sections[0]
    assert hero.attrs["id"] == "install"  # judgekeeper prints start.html#install
    assert _flat(_all(hero, "h1")[0]) == "Start in one command."
    (card,) = _all(hero, "div", "gx-install")
    assert _flat(_all(card, "p", "gx-k")[0]) == "In your project folder, run"
    assert _flat(_all(card, "code")[0]) == "uvx judgekeeper"
    assert not _all(_main(GUIDE), "nav")  # no side list
    # the cards; Your own format holds the record() line judgekeeper links to
    cards = [(c.attrs["id"], _flat(_all(c, "h3")[0])) for c in _all(sections[2], "div", "gx-card")]
    assert cards == [("keys", "Keys and costs"), ("own-format", "Your own format"),
                     ("misc", "Handy commands")]
    (record,) = _all(_by_id(GUIDE, "own-format"), "pre", "gx-code")
    assert record.text().startswith("import judgekeeper\njudgekeeper.record(input=question,")
    reference = (ROOT / "docs" / "reference.md").read_text(encoding="utf-8")
    assert record.text() in reference  # moved from the reference, not rewritten


def test_the_guide_lists_the_five_steps_with_no_tabs_or_terminal():
    (steps,) = _all(_main(GUIDE), "ol", "gl")
    items = _all(steps, "li", "gl-step")
    assert [(li.attrs["id"], _flat(_all(li, "h3")[0])) for li in items] == GUIDE_STEPS
    for n, li in enumerate(items, 1):
        (number,) = _all(li, "span", "gl-n")
        assert _flat(number) == str(n) and number.attrs.get("aria-hidden") == "true"
    for step in ("step-find", "step-mark", "step-measure", "step-fix"):
        done = [_flat(p) for p in _all(_by_id(GUIDE, step), "p", "done")]
        assert done[0].startswith("Done when "), step
    (fold,) = _all(_by_id(GUIDE, "step-find"), "details")
    assert _flat(_all(fold, "summary")[0]) == "Didn't work?"
    # how the numbers are worked out: in the full reference
    links = [a.attrs["href"] for a in _all(_by_id(GUIDE, "step-measure"), "a")]
    assert links == [f"{REFERENCE_MD}#how-the-numbers-are-worked-out"]
    assert "\n## How the numbers are worked out\n" in (ROOT / "docs" / "reference.md").read_text(
        encoding="utf-8")
    assert "The result is Worse, No drop bigger than 20 points, or Not sure." in _flat(
        _by_id(GUIDE, "step-check"))
    text = GUIDE.read_text(encoding="utf-8")
    for gone in ("<template", "steplist", "t-out", "learn.html", "data-panel", "npx"):
        assert gone not in text, gone
    # a number in a circle, and a line down to the next one
    assert "var(--green)" in _rule(".gl-n") and "border-radius: 50%" in _rule(".gl-n")
    assert "width: 1px" in _rule(".gl-step:not(:last-child)::before")


def test_every_command_box_has_a_copy_button_that_says_copied():
    boxes = [box for page in (GUIDE, CHECK) for box in _all(parse(page), "div", "cmd")]
    assert [_flat(_all(b, "code")[0]) for b in boxes] == [
        "uvx judgekeeper", "judgekeeper", "judgekeeper fix", "judgekeeper check",
        "uvx judgekeeper"]
    for box in boxes:
        (button,) = _all(box, "button", "copy")
        assert "data-copy" in button.attrs and button.attrs["aria-label"] == "Copy"
        assert _all(button, "svg", "i-copy") and _all(button, "svg", "i-tick")
        (said,) = _all(button, "span", "copied")
        assert said.attrs.get("aria-live") == "polite"
    assert '"Copied"' in JS and "clipboard" in JS
    # the tick and "Copied" show in green inside the button, never over the command
    assert "color: var(--green)" in _rule(".cmd .copy.done")
    assert "position" not in _rule(".cmd .copied") and "display: inline" in _rule(
        ".cmd .copy.done .copied")
    assert "padding: 12px 18px" in _rule(".cmd code")
    assert "padding: 14px 20px" in _rule(".cmd-big code")


def test_the_guide_tables():
    def rows(section: str) -> list[list[str]]:
        (table,) = _all(_by_id(GUIDE, section), "table")
        return [[_flat(td) for td in _all(tr, "td")] for tr in _all(table, "tr")
                if _all(tr, "td")]
    # every result fix can give: its name and its words, as fix.py has them
    said = [(fix.VERDICT_NAMES[k], fix.RESULT[k].removeprefix("Result: ")) for k in fix.RESULT]
    assert [(name, words[0].upper() + words[1:]) for name, words in said] == [
        tuple(row[:2]) for row in rows("step-fix")]
    assert [row[2] for row in rows("step-fix")] == [
        "Use the new rule.", "You can use the new rule.",
        "Mark the few more answers it asks for, then run judgekeeper fix again.",
        "Keep the old rule, or write a different one.", "Keep the old rule.", "Keep the old rule."]
    assert [r[0] for r in rows("misc")] == ["judgekeeper --stop", "judgekeeper --new",
                                            "judgekeeper --no-browser", "judgekeeper --help"]


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
                  "judgekeeper.com without www, GoDaddy, the domain registrar, forwards you "
                  "to www.judgekeeper.com and sees that one request: your IP address and the "
                  "page you asked for.",
                  "once the page has loaded, it works with Wi-Fi turned off",
                  "Contact: judgekeeper.project@outlook.com.",
                  "by writing to judgekeeper.project@outlook.com.",
                  "Data Privacy Framework and Standard Contractual Clauses",
                  "my legitimate interest", "not sold, shared or combined",
                  "Do Not Track", "erased or restricted, or object to its use",
                  "Information Commissioner's Office", "Last updated: 21 October 2026"):
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

def test_the_browser_check_is_homes_hero_with_the_drop_card_and_a_terminal():
    main = _main(CHECK)
    assert main.classes() == {"ck"}
    (hero,) = _all(main, "section", "hero")
    assert "ck-hero" in hero.classes()
    assert _flat(_all(hero, "h1")[0]) == "Check your LLM-as-a-judge in your browser."
    drop = _by_id(CHECK, "fc-drop")
    assert drop.tag == "button" and drop.attrs.get("type") == "button"
    assert [_flat(el) for el in drop.iter() if {"fc-main", "fc-kinds"} & el.classes()] == [
        "Drop your results file here, or choose one", "promptfoo · DeepEval · CSV · JSONL"]
    file_input = _by_id(CHECK, "fc-file")
    assert file_input.attrs["type"] == "file" and "sr" in file_input.classes()
    # under the drop card, always shown: the command row
    (run,) = _all(main, "div", "ck-run")
    assert _flat(_all(run, "p")[0]) == "To run judgekeeper in your project folder:"
    assert _flat(_all(run, "code")[0]) == "uvx judgekeeper"
    # the terminal: the file's name in its bar once read, Clear, the waiting screen, the result
    assert _flat(_by_id(CHECK, "ck-title")) == "your results file"
    clear = _by_id(CHECK, "ck-clear")
    assert clear.tag == "button" and "hidden" in clear.attrs and _flat(clear) == "Clear"
    assert " ".join(_by_id(CHECK, "ck-wait").text().split()) == (
        "$ judgekeeper Step 1 of 5: Find Waiting for your results file. Drop it on the left. "
        "It stays on your computer. ▋")
    result = _by_id(CHECK, "fc-result")
    assert result.attrs.get("aria-live") == "polite" and not result.children
    script = (WEBSITE / "assets" / "freecheck.js").read_text(encoding="utf-8")
    assert ('NOT_RECOGNISED = "This doesn\'t look like results judgekeeper can read in the '
            'browser. The tool also reads Inspect AI and MLflow: run uvx judgekeeper in your '
            'project.";') in script
    assert "zone.focus()" in script  # Clear puts the focus back on the drop card


def test_the_browser_check_fits_one_screen_with_one_line_above_the_footer():
    assert "border-bottom: 0" in _rule(".hero.ck-hero")  # the footer draws the line
    assert "padding-block: 48px" in _rule(".ck-hero .wrap")
    assert "font-size: 46px" in _rule(".ck-hero h1")
    term = _rule(".ck-term")
    for part in ("height: calc(100vh - 262px)", "min-height: 420px", "max-height: 760px"):
        assert part in term, part
    assert "overflow-y: auto" in _rule(".ck-out")  # long output scrolls inside the terminal
    # the drop card's hover, drag and focus: a green border inside it, no ring outside
    focus = _rule(".fc-drop:hover, .fc-drop.over, .fc-drop:focus-visible")
    assert "inset 0 0 0 1px var(--green)" in focus and "outline: none" in focus


def test_the_browser_check_lines_wrap_and_never_scroll_sideways():
    """At every width a line wraps inside the terminal (checked in Chrome at 1440 and 390
    wide). On a phone a value goes under its label, and a line that only goes on from the one
    above has no indent."""
    term = _rule(".fc-term")
    assert "white-space: pre-wrap" in term and "overflow-wrap: anywhere" in term
    assert not [s for s, d in _rules() if "fc-term" in s and "overflow-x" in d]
    phone = CSS[CSS.index("@media (max-width: 760px) {\n  .fc-drop"):]
    phone = phone[:phone.index("\n}\n")]
    assert "flex-direction: column" in _rule(".fc-term .ln", phone)
    assert "display: none" in _rule(".fc-term .ln > .pad", phone)
    script = (WEBSITE / "assets" / "freecheck.js").read_text(encoding="utf-8")
    assert "line.k.trim() ? 'k t-label' : 'k t-label pad'" in script
    # Home's terminal colours
    for cls in ("t-prompt", "t-cmd", "t-step", "t-label", "t-warn", "t-good", "t-next"):
        assert f"'{cls}'" in script, cls
        assert f".term .{cls}" in CSS, cls


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

def test_the_guide_shows_the_marking_and_result_pages_after_their_first_paragraph():
    for step, picture in (("step-mark", "label.webp"), ("step-measure", "result.webp")):
        body = _all(_by_id(GUIDE, step), "div", "gl-body")[0]
        tags = [el.tag for el in body.children if not isinstance(el, str)]
        assert tags[:3] == ["h3", "p", "figure"], step
        (img,) = _all(body, "img")
        assert img.attrs["src"] == f"assets/shots/{picture}"
        assert (WEBSITE / "assets" / "shots" / picture).is_file()
        assert (img.attrs["width"], img.attrs["height"]) == ("2880", "1800")
        assert len(img.attrs["alt"]) > 80 and "screenshot" not in img.attrs["alt"].lower()
    assert "max-width: 760px" in _rule(".gx-shot")
    shot = _rule(".gx-shot img")
    assert "width: 100%" in shot and "border-radius: 8px" in shot and "border: 1px" in shot
    # Home stays terminal: no picture there
    assert not _all(_main(HOME), "img") and not _all(_main(HOME), "figure")


TOOLS = "For promptfoo, DeepEval, Inspect AI and MLflow"


def test_testing_a_new_rule_is_said_only_for_the_tools_fix_can_ask():
    """fix can't ask a judge in your own file or record() (fix.can_test): the site says what to
    do instead, and never that every judge's rule is tested on marks kept aside."""
    assert set(fix.SWAPPABLE) == {"promptfoo", "deepeval", "inspect", "mlflow"}
    meta = [el.attrs["content"] for el in parse(HOME).iter()
            if el.tag == "meta" and "description" in el.attrs.get("name", "")
            + el.attrs.get("property", "")]
    assert len(meta) == 3 and all(TOOLS in m and "on your own computer" in m for m in meta)
    assert TOOLS + ", test it on marks kept aside." in _flat(_by_id(HOME, "tab-fix"))
    step = _flat(_by_id(GUIDE, "step-fix"))
    assert "promptfoo, DeepEval, Inspect AI or MLflow: write your new rule" in step
    assert ("Your own CSV or JSONL file, or judgekeeper.record(): "
            + fix.CANT_ASK.removesuffix(".") + ", so it can't test a new rule.") in step
    assert "Change the rule where your eval keeps it, run your eval, then judgekeeper check." \
        in step
    assert "its mistakes on the marks you can see" in step and "every mistake" not in step
    own = _flat(_by_id(GUIDE, "own-format"))
    assert "can't test a new rule: change the rule in your eval, run it, then judgekeeper " \
           "check." in own
    llms = (WEBSITE / "llms.txt").read_text(encoding="utf-8")
    assert ("for promptfoo, DeepEval, Inspect AI and MLflow, tests a better rule on marks kept "
            "aside (for your own CSV or JSONL file or `judgekeeper.record()`, you change the rule "
            "in your eval, run it, then `judgekeeper check`)") in llms
    assert "re-checks your LLM-as-a-judge" in llms and "re-checks your judge" not in llms
    for page in pages():
        assert "own terminal" not in _flat(_main(page)), page.name


def test_privacy_says_re_runs_use_temporary_copies():
    local = _flat(_by_id(PRIVACY, "local"))
    assert "runs your eval on temporary copies and deletes them after" in local
