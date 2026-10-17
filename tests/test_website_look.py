"""The look every page shares, and the parts of each page the design pins.

- The frame: every page carries the head lines, the menu and the footer that
  scripts/site_frame.py writes. The menu is four links, the logo and GitHub; the footer is the
  logo, Privacy, Trademarks, Security and the copyright.
- Dark only: the product's dark colours, no switch, no light rules, nothing kept in the browser.
- Fonts from the site only: Manrope and JetBrains Mono with their licences; no ligatures in
  monospace, so "->" shows as typed.
- Motion: only the green underline over the five words and the terminal typing, and neither
  under reduced motion.
- Phone: tables and code scroll inside their box.
- Home: the hero, the demo card that works like the marking page, the steps with their
  terminal, the closing box. The Guide, How it works, Privacy, the browser check and the
  Reference: their side lists and their parts.

The tests run no JavaScript: the pages were checked in Chrome at 1440 and 390 wide.
"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import pytest

from judgekeeper import targets
from tests.website_pages import (
    GITHUB,
    LEGAL,
    NAV,
    ROOT,
    WEBSITE,
    Element,
    hand_written_pages,
    pages,
    parse,
)

HOME = WEBSITE / "index.html"
GUIDE = WEBSITE / "start.html"
LEARN = WEBSITE / "learn.html"
PRIVACY = WEBSITE / "privacy.html"
CHECK = WEBSITE / "check.html"
REFERENCE = WEBSITE / "reference.html"
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
        for block in (frame.head_links(), frame.header(page.name), frame.footer()):
            assert block in text, f"{page.name}: run python scripts/site_frame.py"


def test_the_menu_is_four_links_the_logo_and_github():
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
        "green": "#10B981", "green-fill": "#0d9668", "red": "#e5484d", "red-fill": "#c73b40"}


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
    """Body text 4.5 to 1 on every ground it sits on; the small labels in the faint colour,
    the green underline and white on the bold Pass and Fail fills 3 to 1, as on the
    product's pages."""
    t = _tokens()
    for text in ("fg", "muted"):
        for ground in ("bg", "hover", "current"):
            assert _contrast(t[text], t[ground]) >= 4.5, (text, ground)
    assert _contrast(t["green"], t["bg"]) >= 3 and _contrast(t["faint"], t["bg"]) >= 2.9
    for fill in ("green-fill", "red-fill"):
        assert _contrast("#FFFFFF", t[fill]) >= 3, fill


def test_keyboard_focus_shows():
    assert "outline: 2px solid var(--fg)" in _rule(":focus-visible")
    assert ".skip:focus" in CSS


# Motion ------------------------------------------------------------------------------------

COLOUR_ONLY = {"color", "background", "background-color", "border-color", "filter",
               "text-decoration-color"}


def test_the_only_motion_is_the_underline_and_the_terminal_typing():
    """Hover colours may fade; nothing moves, slides, turns or appears by itself."""
    assert "@keyframes" not in CSS and "animation:" not in CSS.replace("animation: none", "")
    for selector, declarations in _rules():
        for value in re.findall(r"transition:\s*([^;]+)", declarations):
            if value.startswith("none"):
                continue
            props = {part.split()[0] for part in value.split(",")}
            assert props <= COLOUR_ONLY, (selector, value)
    reduce = CSS[CSS.index("@media (prefers-reduced-motion: reduce)"):]
    assert "transition: none !important" in reduce[:200]
    # the two moving parts, and both stop under reduced motion
    assert JS.count("prefers-reduced-motion: reduce") == 1
    assert "function type(" in JS and "function sweep(" in JS
    for gone in ("smooth", "IntersectionObserver(function (e) { reveal", "animate(", "count-up",
                 "parallax", "pointermove"):
        assert gone not in JS, gone


def test_each_screen_types_once_and_replay_types_it_again():
    typing = JS[JS.index("function type("):]
    assert "if (reduce || !animate)" in typing  # at once: reduced motion, or seen before
    assert "seen[key]" in JS and 'replay.addEventListener("click"' in JS


# Phone -------------------------------------------------------------------------------------

def test_tables_and_code_scroll_inside_their_box():
    for page in [*hand_written_pages(), REFERENCE]:
        for table in _all(parse(page), "table"):
            assert "tw" in table.parent.classes(), page.name
    assert "overflow-x: auto" in _rule(".tw")
    assert "overflow: auto" in _rule(".term-out")
    assert "overflow-x: auto" in _rule(".g-ref .g-main pre")
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
          "If your judge needs work, write a better rule and test it on marks kept aside."),
         ("check", "Re-check", "After you change your judge, see if it still agrees with you.")]


def _main(page: Path) -> Element:
    return next(el for el in _els(page) if el.tag == "main")


def test_home_is_the_hero_the_steps_and_the_closing_box():
    sections = [el for el in _main(HOME).children if isinstance(el, Element)]
    assert [s.classes() for s in sections] == [{"hero"}, {"steps"}, {"close"}]


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
    assert ".five a.is-on" in CSS and "var(--green)" in _rule(".five a.is-on")


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
    (tabs,) = _all(steps, "ol", "steplist")
    found = [(b.attrs["data-step"], _flat(_all(b, "b")[0]), _flat(_all(b, "span", "d")[0]))
             for b in _all(tabs, "button")]
    assert found == STEPS
    assert [b.attrs.get("aria-selected") for b in _all(tabs, "button")] == [
        "true", "false", "false", "false", "false"]
    (term,) = [el for el in steps.iter() if el.attrs.get("id") == "term"]
    assert _flat(_all(term, "span", "term-title")[0]) == "example project"
    fix_tabs = _by_id(HOME, "t-tabs")
    assert "hidden" in fix_tabs.attrs
    assert [(_flat(b), b.attrs["data-screen"]) for b in _all(fix_tabs, "button")] == [
        ("First run", "fix"), ("Testing your rule", "fix_test")]
    assert _flat(_by_id(HOME, "t-replay")) == "Replay"


def test_the_closing_box_points_to_the_browser_check():
    close = _all(_main(HOME), "section", "close")[0]
    assert _flat(_all(close, "h2")[0]) == "Have eval results?"
    assert _flat(_all(close, "p")[0]) == ("Check your LLM-as-a-judge. Your file stays on your "
                                          "computer.")
    (button,) = _all(close, "a", "b-main")
    assert (button.attrs["href"], _flat(button)) == ("check.html", "Check in your browser")


# The pages with a side list -----------------------------------------------------------------

def _side(page: Path) -> list[tuple[str, str]]:
    (nav,) = _all(_main(page), "nav", "g-nav")
    return [(a.attrs["href"], _flat(a)) for a in _all(nav, "a")]


def test_each_side_list_points_at_its_sections():
    for page in (GUIDE, LEARN, PRIVACY, REFERENCE):
        ids = {el.attrs.get("id") for el in _els(page)}
        side = _side(page)
        assert side, page.name
        for href, _ in side:
            assert href.startswith("#") and href[1:] in ids, (page.name, href)
        (head,) = _all(_main(page), "header", "g-head")
        assert len(_all(head, "h1")) == 1 and _all(head, "p", "g-lede"), page.name


def test_the_guide_is_install_five_steps_then_keys_format_and_more():
    assert _side(GUIDE) == [
        ("#install", "Install"), ("#find", "Step 1 · Find"), ("#mark", "Step 2 · Mark"),
        ("#measure", "Step 3 · Measure"), ("#fix", "Step 4 · Fix"),
        ("#recheck", "Step 5 · Re-check"), ("#keys", "Keys and costs"),
        ("#own-format", "Your own format"), ("#misc", "Start over, stop, remote")]
    assert _flat(_all(_main(GUIDE), "h1")[0]) == "Guide"
    for step in ("find", "mark", "measure", "fix", "recheck"):
        section = _by_id(GUIDE, step)
        (eyebrow,) = _all(section, "p", "eyebrow")
        assert _flat(eyebrow).startswith("Step "), step
        done = [_flat(p) for p in _all(section, "p", "done")]
        assert done == [] if step == "recheck" else done[0].startswith("Done when "), step
    (fold,) = _all(_by_id(GUIDE, "find"), "details")
    assert _flat(_all(fold, "summary")[0]) == "Didn't work?"
    (nxt,) = _all(_main(GUIDE), "a", "next")
    assert (nxt.attrs["href"], _flat(nxt)) == ("learn.html", "Next · How it works")


def test_every_command_box_has_a_copy_button_that_ticks():
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


def test_the_guide_shows_the_existing_pictures_of_the_real_pages():
    """New pictures come later; until then the pictures in assets/shots/."""
    for step, src in (("mark", "assets/shots/label.webp"), ("measure", "assets/shots/result.webp")):
        (figure,) = _all(_by_id(GUIDE, step), "figure", "shot")
        (link,) = _all(figure, "a")
        (img,) = _all(figure, "img")
        assert link.attrs["href"] == img.attrs["src"] == src
        assert (WEBSITE / src).is_file() and (WEBSITE / src).stat().st_size < 250_000
        assert (img.attrs.get("width"), img.attrs.get("height")) == ("1440", "900")
        assert img.attrs.get("alt", "").strip(), src
    assert "width: 100%" in _rule(".shot img") and "height: auto" in _rule(".shot img")


def test_the_guide_tables():
    def rows(section: str) -> list[list[str]]:
        (table,) = _all(_by_id(GUIDE, section), "table")
        return [[_flat(td) for td in _all(tr, "td")] for tr in _all(table, "tr")][1:]
    assert rows("fix") == [
        ["Better", "Use the new rule."],
        ["Safe to try", ("Not clearly better yet, and very unlikely to be more than 10 points "
                        "worse. You can try it.")],
        ["Can't tell yet", "Mark a few more answers and test again."],
        ["Looks worse, or Worse", "Keep the old rule."]]
    assert [r[0] for r in rows("own-format")] == ["input", "output", "verdict"]
    assert [r[1] for r in rows("misc")] == ["judgekeeper --stop", "judgekeeper --new",
                                            "judgekeeper --no-browser", "judgekeeper --help"]


def test_how_it_works_has_its_side_list_the_range_and_the_marks_kept_aside():
    assert _side(LEARN) == [
        ("#why", "Why check an LLM-as-a-judge"), ("#first-check", "The first check"),
        ("#numbers", "What the numbers mean"), ("#kept-aside", "Marks kept aside"),
        ("#recheck", "How a re-check works"), ("#questions", "Questions")]
    slider = _by_id(LEARN, "n")
    assert {k: slider.attrs[k] for k in ("type", "min", "max", "step", "value")} == {
        "type": "range", "min": "10", "max": "200", "step": "5", "value": "15"}
    assert _flat(_by_id(LEARN, "n-out")) == "15"
    sim = _by_id(LEARN, "sim")
    assert "data-example" in sim.attrs
    assert ("An example: a judge that agrees with you about 61% of the time. Move the slider: "
            "more marks, smaller range.") in _flat(sim)
    kept = _by_id(LEARN, "kept")
    assert _flat(_all(kept, "p", "kept-h")[0]) == "10 marks kept aside"
    buttons = [(int(b.attrs["data-fixed"]), int(b.attrs["data-broke"]), _flat(b))
               for b in _all(kept, "button")]
    assert buttons == [(6, 0, "Fixed 6, broke 0"), (4, 0, "Fixed 4, broke 0"),
                       (4, 2, "Fixed 4, broke 2"), (1, 3, "Fixed 1, broke 3")]
    assert _flat(_all(kept, "p", "kept-cap")[0]) == (
        "Examples. Your result always comes from your own marks.")
    assert _by_id(LEARN, "kept-out").attrs.get("aria-live") == "polite"


READOUTS = {
    "better": "Result: your new rule is better. A difference this large is very unlikely to be "
              "a coincidence.",
    "safe": "Result: safe to try. Not clearly better yet, but very unlikely to be more than 10 "
            "points worse.",
    "leans better": "Result: can't tell yet. It leans toward better, but a split this small "
                    "could easily be a coincidence.",
    "leans worse": "Result: it looks worse. Keep the old rule."}


@pytest.mark.parametrize(("fixed", "broke"), [(6, 0), (4, 0), (4, 2), (1, 3)])
def test_each_kept_aside_example_says_what_judgekeeper_would(fixed, broke):
    """The readout for each example is the verdict judgekeeper gives on 10 marks kept aside."""
    kind = targets.fix_verdict(fixed, broke, 10).kind
    assert f'"{fixed},{broke}": "{READOUTS[kind]}"'.replace('"', "'") in JS.replace('"', "'")


def test_the_result_table_takes_its_bar_from_the_code():
    (table,) = _all(_by_id(LEARN, "numbers"), "table")
    bars = [el for el in table.iter() if "data-const" in el.attrs]
    assert [el.attrs["data-const"] for el in bars] == ["judgekeeper.targets:RATE_GATE"] * 3
    assert targets.RATE_GATE == 0.80


def test_privacy_says_what_the_site_and_the_tool_do_with_data():
    assert _side(PRIVACY) == [("#site", "This website"), ("#local", "judgekeeper on your computer"),
                              ("#questions", "Questions")]
    site, local = (_all(_by_id(PRIVACY, s), "li") for s in ("site", "local"))
    assert len(site) == 4 and len(local) == 4
    text = _flat(_main(PRIVACY))
    assert "light or dark" not in text and "local storage" not in text  # dark only, no store
    assert "Railway" in text and "never uploaded" in text
    hrefs = [a.attrs["href"] for a in _all(_main(PRIVACY), "a")]
    assert f"{GITHUB}/issues" in hrefs and f"{GITHUB}/blob/main/SECURITY.md" in hrefs


def test_the_browser_check_is_one_column_with_the_drop_area_and_its_result():
    main = _main(CHECK)
    assert {"g", "g-check"} <= main.classes()
    drop = _by_id(CHECK, "fc-drop")
    assert drop.tag == "button" and drop.attrs.get("type") == "button"
    assert [_flat(el) for el in drop.iter() if {"fc-main", "fc-kinds"} & el.classes()] == [
        "Drop your results file here, or click to choose one.",
        "promptfoo · DeepEval · CSV · JSONL"]
    file_input = _by_id(CHECK, "fc-file")
    assert file_input.attrs["type"] == "file" and "sr" in file_input.classes()
    result = _by_id(CHECK, "fc-result")
    assert result.attrs.get("aria-live") == "polite" and not result.children
    after = _by_id(CHECK, "fc-next")
    assert "hidden" in after.attrs and _all(after, "div", "cmd")
    (alt,) = _all(main, "p", "fc-alt")
    assert [a.attrs["href"] for a in _all(alt, "a")] == ["start.html#install"]
    # what freecheck.js writes into the result has its look
    for selector in (".fc-result .fc-term", ".fc-problem", ".fc-pick-list .btn"):
        assert selector + " {" in CSS, selector


# The reference: rendered from docs/reference.md -----------------------------------------------

def test_the_reference_has_a_side_list_of_its_sections_and_keeps_the_usage_lines():
    markdown = (ROOT / "docs" / "reference.md").read_text(encoding="utf-8")
    headings = re.findall(r"^## (.+)$", markdown, flags=re.MULTILINE)
    assert [label for _, label in _side(REFERENCE)] == [
        h.replace("`", "").replace("**", "") for h in headings]
    head = _all(_main(REFERENCE), "header", "g-head")[0]
    assert _flat(_all(head, "h1")[0]) == "judgekeeper reference"
    assert _flat(_all(head, "p")[0]) == ("Every command, flag, exit code, file and format. The "
                                         "README has the short version.")
    blocks = re.findall(r"^```[a-z]*\n(.*?)\n```$", markdown, flags=re.MULTILINE | re.DOTALL)
    shown = [el.text() for el in _els(REFERENCE) if el.tag == "code" and el.parent.tag == "pre"]
    assert shown == blocks  # every line break kept
    assert {"g", "g-ref"} <= _main(REFERENCE).classes()


def test_a_line_quoted_from_judgekeeper_is_what_it_prints():
    """`data-said-by` names the module that prints the quoted line (cut at its last full
    stop when the page quotes only the start)."""
    quoted = [el for page in hand_written_pages() for el in parse(page).iter()
              if "data-said-by" in el.attrs]
    assert quoted
    for el in quoted:
        source = (ROOT / "src" / "judgekeeper" / f"{el.attrs['data-said-by']}.py").read_text(
            encoding="utf-8")
        assert el.text().strip().removesuffix(".") in source, el.text()
