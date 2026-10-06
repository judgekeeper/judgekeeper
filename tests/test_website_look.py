"""The frame and the look every page shares, the home page's hero and route, and the Guide.

- The frame: every page carries the head lines, the header (navigation and theme switch) and
  the footer that scripts/site_frame.py writes.
- Nothing loads from another server: the fonts are files of the site, with their licences.
- The theme is dark unless the system or the visitor asks for light; the visitor's choice and
  the ticked steps are kept in the browser only inside try/catch.
- The home page: the headline that never breaks inside "LLM-as-a-judge", the two buttons, the
  two-verdicts card and the six-step route.
- The Guide: six steps, each with "You're done when" and a done tick, "Didn't work?" quoting
  what judgekeeper really prints, the coding-assistant prompt, and the result and labeling
  pictures in the product's own words.
- Every older page starts with "New here?".
"""

from __future__ import annotations

import importlib.util
import json
import re
import shlex
from pathlib import Path

from judgekeeper import start_label, start_page
from judgekeeper.cli import _parser
from tests.website_pages import MORE, NAV, ROOT, WEBSITE, Element, pages, parse

GUIDE = WEBSITE / "start.html"
HOME = WEBSITE / "index.html"
CSS = (WEBSITE / "assets" / "style.css").read_text(encoding="utf-8")
SRC = ROOT / "src" / "judgekeeper"
OLDER = {"own-metric.html", "assistant.html", "setup.html", "learn.html", "tutorial.html"}
STEPS = [("install", "Install"), ("connect", "Connect your results"), ("start", "Start"),
         ("label", "Label"), ("result", "Your result"), ("improve", "Improve your judge")]
ROUTE = ["Install", "Connect", "Start", "Label", "Result", "Improve"]
NB_HYPHEN = "‑"


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
    return " ".join(el.text().split())


# The frame -------------------------------------------------------------------------------

def test_every_page_carries_the_frame_site_frame_writes():
    frame = _frame()
    assert frame.NAV == NAV and frame.MORE == MORE
    for page in pages():
        text = page.read_text(encoding="utf-8")
        assert frame.head_links() in text, f"{page.name}: run python scripts/site_frame.py"
        assert frame.header(page.name) in text, f"{page.name}: run python scripts/site_frame.py"
        assert frame.footer() in text, f"{page.name}: run python scripts/site_frame.py"


def test_the_navigation_is_home_guide_reference_github_and_the_theme_switch():
    for page in pages():
        (header,) = _all(parse(page), "header", "site-header")
        (nav,) = _all(header, "nav", "site-nav")
        assert [(a.attrs["href"], a.text().strip()) for a in _all(nav, "a")] == NAV, page.name
        buttons = _all(header, "button")
        assert [b.classes() for b in buttons] == [{"theme-btn"}, {"menu-btn"}], page.name
        assert buttons[0].attrs.get("aria-label"), page.name
        assert buttons[1].attrs.get("aria-controls") == "site-nav", page.name
        assert [a.text().strip() for a in _all(header, "a")][1:] == [label for _, label in NAV]


def test_every_page_has_the_footer_with_start_here_and_more():
    for page in pages():
        (footer,) = _all(parse(page), "footer", "site-footer")
        columns = {h.text(): h.parent for h in _all(footer, "h2")}
        assert list(columns) == ["Start here", "More"], page.name
        more = [(a.attrs["href"], a.text()) for a in _all(columns["More"], "a")]
        assert more == MORE, page.name
        assert [a.text() for a in _all(columns["Start here"], "a")] == [
            "Guide", "Reference", "GitHub"]


def test_more_names_every_page_outside_the_navigation():
    in_nav = {href for href, _ in NAV}
    outside = {p.name for p in pages()} - in_nav
    assert outside == {href for href, _ in MORE} == OLDER


# Nothing from another server -------------------------------------------------------------

FAMILIES = {"Bricolage Grotesque": ("BricolageGrotesque", {"600", "800"}),
            "Atkinson Hyperlegible": ("AtkinsonHyperlegible", {"400", "700"}),
            "JetBrains Mono": ("JetBrainsMono", {"400", "600"})}


def _font_faces() -> list[dict[str, str]]:
    faces = []
    for body in re.findall(r"@font-face\s*\{(.*?)\}", CSS, flags=re.DOTALL):
        pairs = (line.split(":", 1) for line in body.split(";") if ":" in line)
        faces.append({k.strip(): v.strip() for k, v in pairs})
    return faces


def test_the_fonts_are_files_of_the_site_with_their_licences():
    faces = _font_faces()
    seen: dict[str, set[str]] = {}
    for face in faces:
        family = face["font-family"].strip("\"'")
        (src,) = re.findall(r"url\(([^)]+)\)", face["src"])
        assert src.startswith("fonts/") and src.endswith(".woff2"), src
        assert (WEBSITE / "assets" / src).is_file(), src
        assert "font-display" in face, family
        seen.setdefault(family, set()).add(face["font-weight"])
    for family, (licence, weights) in FAMILIES.items():
        assert weights <= seen.get(family, set()), family
        text = (WEBSITE / "assets" / "fonts" / f"OFL-{licence}.txt").read_text(encoding="utf-8")
        assert "SIL OPEN FONT LICENSE" in text.upper(), licence
    for url in re.findall(r"url\(([^)]+)\)", CSS):
        assert not re.match(r"['\"]?(https?:)?//", url), url


def test_no_page_or_asset_asks_another_server_for_anything():
    files = [*pages(), *(WEBSITE / "assets").glob("*.css"), *(WEBSITE / "assets").glob("*.js")]
    for path in files:
        text = path.read_text(encoding="utf-8")
        for host in ("fonts.googleapis", "fonts.gstatic", "cdn.", "unpkg", "googletagmanager"):
            assert host not in text, (path.name, host)
        if path.suffix == ".html":
            for el in parse(path).iter():
                for attr in ("src", "href"):
                    url = el.attrs.get(attr, "")
                    if el.tag in {"link", "script", "img"} and url:
                        assert not re.match(r"(https?:)?//", url), (path.name, url)


# Theme and the browser's storage ---------------------------------------------------------

DARK_PAPER, LIGHT_PAPER = "#0F172A", "#F6F8FB"


def _block(selector: str) -> str:
    start = CSS.index(selector + " {")
    return CSS[start:CSS.index("}", start)]


def test_the_theme_is_dark_unless_the_system_or_the_visitor_asks_for_light():
    assert f"--paper: {DARK_PAPER}" in _block(":root")  # the first :root block: no condition
    light = CSS.index("@media (prefers-color-scheme: light)")
    assert ':root:not([data-theme="dark"])' in CSS[light:light + 200]
    assert f"--paper: {LIGHT_PAPER}" in CSS[light:light + 400]
    assert f"--paper: {LIGHT_PAPER}" in _block(':root[data-theme="light"]')
    assert CSS.count(LIGHT_PAPER) == 2
    assert "prefers-color-scheme: dark" not in CSS  # dark needs no condition


def test_the_theme_is_set_before_the_page_is_drawn():
    for page in pages():
        (head,) = _all(parse(page), "head")
        scripts = _all(head, "script")
        theme = [s for s in scripts if s.attrs.get("src") == "assets/theme.js"]
        assert len(theme) == 1, page.name
        assert "defer" not in theme[0].attrs and "async" not in theme[0].attrs, page.name
    js = (WEBSITE / "assets" / "theme.js").read_text(encoding="utf-8")
    assert "dataset.theme" in js and "jk-theme" in js


def test_the_browser_storage_is_used_only_inside_try_and_only_for_two_things():
    keys = set()
    for path in (WEBSITE / "assets").glob("*.js"):
        text = path.read_text(encoding="utf-8")
        for line in text.splitlines():
            if "localStorage" in line:
                assert path.name in {"theme.js", "site.js"}, path.name
                before, _, after = line.partition("localStorage")
                assert "try {" in before and "catch" in after, (path.name, line.strip())
        keys |= set(re.findall(r'"(jk-[a-z]+)"', text))
    assert keys == {"jk-theme", "jk-done"}


# Text on a background, in both themes: WCAG AA asks for 4.5 to 1 for body-size text.
PAIRS = [("ink", "paper"), ("ink-2", "paper"), ("ink-3", "paper"), ("ink-2", "sheet"),
         ("ink-3", "sheet"), ("ink-2", "tint"), ("ink-3", "tint"), ("link", "paper"),
         ("link", "sheet"), ("agree", "agree-bg"), ("agree", "sheet"), ("fail", "fail-bg"),
         ("fail", "sheet"), ("care", "care-bg"), ("ink", "agree-bg"), ("ink", "care-bg"),
         ("code-ink", "code-bg"), ("code-dim", "code-bg"), ("code-ok", "code-bg"),
         ("code-dim", "code-bar")]


def _tokens(block: str) -> dict[str, str]:
    return dict(re.findall(r"--([a-z0-9-]+):\s*(#[0-9A-Fa-f]{6})", block))


def _contrast(a: str, b: str) -> float:
    def lum(colour: str) -> float:
        rgb = [int(colour[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
        return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]
    hi, lo = sorted((lum(a), lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def test_text_colours_meet_wcag_aa_in_both_themes():
    dark = _tokens(_block(":root"))
    light = {**dark, **_tokens(_block(':root[data-theme="light"]'))}
    media = CSS[CSS.index("@media (prefers-color-scheme: light)"):]
    assert _tokens(media[:media.index("}")]) == _tokens(_block(':root[data-theme="light"]'))
    for name, theme in (("dark", dark), ("light", light)):
        for text, back in PAIRS:
            ratio = _contrast(theme[text], theme[back])
            assert ratio >= 4.5, f"{name}: {text} on {back} is {ratio:.2f} to 1"


def test_motion_is_reduced_when_the_visitor_asks():
    reduce = CSS[CSS.index("@media (prefers-reduced-motion: reduce)"):]
    assert "animation: none" in reduce and "transition: none" in reduce
    assert "@media (prefers-reduced-motion: no-preference)" in CSS  # the card's slips


# Home ------------------------------------------------------------------------------------

def test_the_headline_never_breaks_inside_llm_as_a_judge():
    (h1,) = _all(parse(HOME), "h1")
    (keep,) = [el for el in h1.iter() if "nobr" in el.classes()]
    assert keep.text() == f"LLM{NB_HYPHEN}as{NB_HYPHEN}a{NB_HYPHEN}judge."
    assert h1.text().replace(NB_HYPHEN, "-") == "Check your LLM-as-a-judge."
    assert ".nobr { white-space: nowrap; }" in CSS


def test_the_hero_has_its_two_buttons_and_the_verdicts_card():
    main = next(el for el in _els(HOME) if el.tag == "main")
    hero = next(el for el in main.children if isinstance(el, Element))
    assert "hero" in hero.classes()
    buttons = [(a.attrs["href"], a.text().strip()) for a in _all(hero, "a", "btn")]
    assert buttons == [("start.html", "Get started"), ("#how", "How it works")]
    (card,) = _all(hero, "figure", "verdicts")
    flat = _flat(card)
    for words in ("The question", "Your app's answer", "The AI judge says", "You say",
                  "Next answer", "So far"):
        assert words in flat, words
    (data,) = [el for el in card.iter() if el.attrs.get("id") == "verdict-examples"]
    assert data.tag == "script" and data.attrs.get("type") == "application/json"
    examples = json.loads(data.text())
    assert [e["q"] for e in examples] == [
        "How do I reset my password?", "Can I get a refund after 30 days?",
        "Is my order shipped?", "What is the weight limit for carry-on bags?"]
    agree = [(e["j"] == "Pass") == (e["y"] == "Correct") for e in examples]
    assert agree == [True, False, False, True]
    first = examples[0]  # shown without JavaScript too
    assert _flat(_by_id(HOME, "vq")) == first["q"] and _flat(_by_id(HOME, "va")) == first["a"]
    assert _flat(_by_id(HOME, "vj")) == first["j"] and _flat(_by_id(HOME, "vy")) == first["y"]
    assert "They agree" in _flat(_by_id(HOME, "vb"))
    assert _by_id(HOME, "vb").attrs.get("aria-live") == "polite" or \
        card.attrs.get("aria-live") == "polite"


def test_the_home_page_is_hero_how_route_install_and_what_you_get():
    main = next(el for el in _els(HOME) if el.tag == "main")
    ids = [el.attrs.get("id") for el in main.children
           if isinstance(el, Element) and el.tag == "section"]
    assert ids == [None, "how", "route", "install", "get"]
    roles = [h.text() for h in _all(_by_id(HOME, "how"), "h3")]
    assert roles == ["Your app answers", "An AI judge grades it", "You check the judge"]


def test_the_route_has_six_stops_each_a_link_to_its_step_in_the_guide():
    (route,) = _all(_by_id(HOME, "route"), "ol", "route")
    stops = [li for li in route.children if isinstance(li, Element)]
    assert [_all(li, "b")[0].text() for li in stops] == ROUTE
    assert [_all(li, "a")[0].attrs["href"] for li in stops] == [
        f"start.html#{step}" for step, _ in STEPS]


# The Guide -------------------------------------------------------------------------------

def _steps() -> list[Element]:
    return [el for el in _els(GUIDE) if el.tag == "section" and "stop" in el.classes()]


def test_the_guide_is_named_the_guide():
    text = GUIDE.read_text(encoding="utf-8")
    assert "<title>Guide | judgekeeper</title>" in text
    (h1,) = _all(parse(GUIDE), "h1")
    assert h1.text() == "Check your judge, step by step"


def test_the_guide_has_six_steps_each_with_done_when_and_a_tick():
    steps = _steps()
    assert [(s.attrs["id"], _all(s, "h2")[0].text()) for s in steps] == STEPS
    for n, step in enumerate(steps, start=1):
        assert _all(step, "p", "why"), step.attrs["id"]
        (done,) = _all(step, "div", "donewhen")
        assert _flat(done).startswith("You're done when "), step.attrs["id"]
        (box,) = [el for el in done.iter() if el.tag == "input"]
        assert box.attrs.get("type") == "checkbox" and box.attrs.get("data-step") == str(n)
        assert _flat(box.parent) == f"Mark step {n} done" and box.parent.tag == "label"


def test_the_rail_follows_the_six_steps():
    (rail,) = _all(parse(GUIDE), "aside", "rail")
    (route,) = _all(rail, "ol")
    tops = [li for li in route.children if isinstance(li, Element)]
    firsts = [next(a for a in li.iter() if a.tag == "a") for li in tops]
    assert [a.attrs["href"] for a in firsts] == [f"#{step}" for step, _ in STEPS]
    subs = [a.attrs["href"] for a in tops[-1].iter() if a.tag == "a"][1:]
    assert subs == ["#review", "#ask-again", "#new-judge"]
    assert "Ticked steps are remembered in this browser" in _flat(rail)


def test_steps_label_what_to_type_and_what_you_will_see():
    steps = {s.attrs["id"]: s for s in _steps()}
    for step in ("install", "start"):
        labels = [_flat(el) for el in _all(steps[step], "p", "boxlabel")]
        assert labels and all(label.endswith("in your project folder") for label in labels)
        screens = _all(steps[step], "div", "screen")
        assert screens and all("What you will see" in _flat(s) for s in screens)
        assert all(_all(s, "pre", "output") for s in screens)


def test_steps_one_and_three_say_what_to_do_when_it_did_not_work():
    steps = {s.attrs["id"]: s for s in _steps()}
    for step in ("install", "start"):
        (help_box,) = _all(steps[step], "details", "help")
        assert _flat(_all(help_box, "summary")[0]) == "Didn't work?"


def test_the_didnt_work_boxes_quote_what_judgekeeper_really_prints():
    quoted = [el for el in _els(GUIDE) if "data-said-by" in el.attrs]
    assert len(quoted) >= 6
    for el in quoted:
        source = (SRC / f"{el.attrs['data-said-by']}.py").read_text(encoding="utf-8")
        said = el.text().removesuffix("…").strip()
        assert said and said in source, (el.attrs["data-said-by"], said)


GUIDE_PROMPT_NEEDS = ("inside this project's own Python environment", "uv add --dev judgekeeper",
                      "poetry add --group dev judgekeeper", "judgekeeper start --yes --no-browser",
                      "I will label the answers myself")


def test_the_guide_prompt_installs_inside_the_project_and_leaves_labeling_to_the_person():
    (fold,) = _all(parse(GUIDE), "details", "agent")
    assert _flat(_all(fold, "summary")[0]).startswith(
        "Using a coding assistant? Paste this prompt instead")
    (prompt,) = [el for el in fold.iter() if el.attrs.get("id") == "guide-prompt"]
    assert prompt.tag == "code" and "code" in prompt.parent.parent.classes()  # a copy button
    flat = " ".join(prompt.text().split())
    for needed in GUIDE_PROMPT_NEEDS:
        assert needed in flat, needed
    parser = _parser()
    for command in re.findall(r"judgekeeper (?:start|setup)[a-z -]*", flat):
        parser.parse_args(shlex.split(command.strip())[1:])


def test_the_you_need_box_comes_first():
    (ready,) = _all(parse(GUIDE), "div", "ready")
    assert [h.text() for h in _all(ready, "h2")] == ["You need", "You will end with"]
    assert "Python 3.11 or newer" in _flat(ready)


# The pictures: what a real run would say -------------------------------------------------

def _numbers(el: Element) -> dict:
    """The made-up result a preview shows, as `start_label.page_content` takes it."""
    a = el.attrs
    tpr, tpr_lo, tpr_hi = (float(x) for x in a["data-tpr"].split())
    tnr, tnr_lo, tnr_hi = (float(x) for x in a["data-tnr"].split())
    r = {"labels": {"correct": int(a["data-correct"]), "wrong": int(a["data-wrong"])},
         "tpr": tpr, "tpr_interval": (tpr_lo, tpr_hi), "tnr": tnr,
         "tnr_interval": (tnr_lo, tnr_hi), "kappa": float(a["data-kappa"]),
         "check": "rough", "judge_pass_rate": None, "real_pass_rate": None}
    r["verdict_level"] = start_label._level(r)
    r["verdict"] = start_label.VERDICTS[r["verdict_level"]]
    return r


def test_the_result_pictures_say_what_judgekeeper_would_say_for_their_numbers():
    previews = [(page, el) for page in (HOME, GUIDE) for el in _els(page)
                if "result-preview" in el.classes()]
    assert len(previews) == 2
    for page, el in previews:
        assert "data-illustration" in el.attrs and "illustration" in el.text().lower()
        r = _numbers(el)
        assert r["verdict_level"] == "check"  # amber: "check by hand"
        content = start_label.page_content(r)
        flat = _flat(el)
        for sentence in content["sentences"]:
            assert sentence in flat, (page.name, sentence)
        (box,) = _all(el, "div", "vbox")
        assert start_label.LEVELS["check"][0] in box.classes()
        assert content["verdict"]["text"] in _flat(box), page.name
        tiles = [t for t in el.iter() if "num" in t.classes()]
        assert len(tiles) == 3
        for tile, want in zip(tiles, content["tiles"], strict=True):
            assert want["plain"] in _flat(tile) and want["value"] in _flat(tile), page.name
            if page == GUIDE:
                assert want["line"] in _flat(tile)
        if page == GUIDE:
            assert content["verdict"]["detail"] in _flat(box)
            assert [t["name"] for t in content["tiles"]] == [
                _all(t, "small")[0].text() for t in tiles]


def test_the_labeling_picture_uses_the_products_words():
    (mini,) = [el for el in _els(GUIDE) if "mini" in el.classes()]
    flat = _flat(mini)
    page = start_page.label_page(None, None, start_label.STATUS)
    for words in ("The question", "The answer", "Your progress", "See my result →",
                  "Is this answer correct? Your judge's verdict is hidden."):
        assert words in flat and words in page, words
    assert start_label.STATUS[1][1] in flat  # the line under the meters at a rough check


# Older pages -----------------------------------------------------------------------------

def test_every_older_page_starts_with_new_here():
    for name in OLDER:
        main = next(el for el in _els(WEBSITE / name) if el.tag == "main")
        first = next(el for el in main.iter() if el.tag == "p")
        assert "newhere" in first.classes(), name
        assert _flat(first).startswith("New here? Start with the Guide. This page is for "), name
        assert next(a.attrs["href"] for a in _all(first, "a")) == "start.html", name


def test_the_setup_page_says_first_that_start_needs_no_key():
    main = next(el for el in _els(WEBSITE / "setup.html") if el.tag == "main")
    first = _flat(next(el for el in main.iter() if el.tag == "p"))
    assert "only when you ask your judge again" in first


def test_the_tutorial_is_the_advanced_commands():
    text = (WEBSITE / "tutorial.html").read_text(encoding="utf-8")
    assert "<title>Advanced commands, step by step | judgekeeper</title>" in text
    (h1,) = _all(parse(WEBSITE / "tutorial.html"), "h1")
    assert h1.text() == "Advanced commands, step by step"


ORDER = ["index.html", "start.html", "reference.html", "own-metric.html", "assistant.html",
         "setup.html", "learn.html", "tutorial.html"]


def test_the_sitemap_and_llms_txt_list_the_pages_in_the_new_order():
    site = "https://www.judgekeeper.com/"
    urls = [site + ("" if p == "index.html" else p) for p in ORDER]
    locs = re.findall(r"<loc>(.*?)</loc>", (WEBSITE / "sitemap.xml").read_text(encoding="utf-8"))
    assert [u for u in locs if u in urls] == urls
    llms = (WEBSITE / "llms.txt").read_text(encoding="utf-8")
    found = [u for u in re.findall(r"\]\((https://www\.judgekeeper\.com/[^)]*)\)", llms)]
    assert found == urls
