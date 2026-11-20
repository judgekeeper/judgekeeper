"""The result page's layout, state by state: one column with a lit heading bar per section
(the verdict, the score, each list, What next), Pass and Fail in colour, nothing loaded from
outside, the scripts the page's CSP allows, the same words as before but for the approved
changes, and numbers that match their counts."""

from __future__ import annotations

import hashlib
import json
import re
from html import unescape
from html.parser import HTMLParser
from pathlib import Path

import pytest

from judgekeeper import look, mark_page, report_page
from tests.test_product_pages import (
    CHECK,
    GATE,
    NOT_GATE_TNR,
    TOO_FEW,
    _mistakes,
    _result,
)

TEXT_BEFORE = Path(__file__).parent / "fixtures" / "result_page_text_before.json"
WORSE = ("Your marks still test your old LLM-as-a-judge. To try another one, run "
         "`judgekeeper check <new results file>`.")
LAST = {"judge": "bike-grader-v2",
        "lines": ["When you say Pass, it also says Pass: about 70% (between 60% and 80%)"]}


def _shown(r: dict, easy: int, strict: int, ids: bool = False) -> dict:
    """The disagreements listed: `easy` and `strict` of them, at most as many as there are."""
    c = report_page.counts(r)
    rows = _mistakes(min(easy, c["easy"]), min(strict, c["strict"]))
    if ids:
        rows = [{**m, "id": f"m{k}"} for k, m in enumerate(rows)]
    return {"mistakes": rows, "parts": [], "own": []}


def state(name: str) -> tuple[dict, dict, dict]:
    """A result in one of the states the page shows: (r, fixing, more of page()'s options)."""
    kw: dict = {}
    if name in ("needs-all", "file-all"):
        r = _result(40, 40, 40, 22, 40, 2, left=0)
        kw = {"started_else": True} if name == "file-all" else {}
    elif name in ("needs-ranges", "reasons", "empty-group", "imported", "check-worse"):
        r = _result(*NOT_GATE_TNR, **({"imported": {"marks": 12, "from": ["labels.csv"]}}
                                     if name == "imported" else {}))
        if name == "check-worse":
            kw = {"worse": WORSE, "last": LAST}
    elif name == "good-all":
        r = _result(30, 30, 30, 29, 30, 1, left=0)
    elif name == "good-ranges":
        r = _result(*GATE)
    elif name == "early":
        r = _result(*CHECK)
    elif name == "too-few":
        r = _result(*TOO_FEW)
    elif name == "few":
        r = _result(16, 16, 16, 15, 16, 1, left=0,
                    fingerprint={"model": "openai:gpt-4.1-mini-2025-04-14-fine-tuned-support"})
    elif name == "one-grade":
        r = _result(100, 0, 60, 20, 0, 0)
    elif name == "zero":
        r = _result(100, 100, 40, 40, 40, 0)  # no disagreement
    else:
        raise KeyError(name)
    if name == "one-grade":
        fixing = _shown(r, 7, 0)
    elif name == "empty-group":
        fixing = _shown(r, 5, 0)
    else:
        fixing = _shown(r, 5, 2, ids=name == "reasons")
    return r, fixing, kw


SERVED = ["needs-all", "needs-ranges", "reasons", "good-all", "good-ranges", "early", "too-few",
          "few", "one-grade", "zero"]
SAVED = ["needs-all", "file-all", "needs-ranges", "empty-group", "imported", "check-worse"]
PAGES = [(name, True) for name in SERVED] + [(name, False) for name in SAVED]
TEXT_PAGES = [(n, live) for n, live in PAGES
              if n in ("needs-all", "needs-ranges", "reasons", "file-all", "early", "too-few",
                       "zero", "check-worse")]


def page(name: str, live: bool) -> str:
    """The served page (with the token in its link back) or report.html, for `name`."""
    r, fixing, kw = state(name)
    return report_page.page(r, back="/?token=t" if live else None, fixing=fixing, **kw)


def _id(name: str, live: bool) -> str:
    return f"{name}-{'served' if live else 'report'}"


# A small tree from html.parser -----------------------------------------------------------

VOID = {"meta", "link", "br", "img", "input", "col", "hr", "path", "rect", "circle", "line",
        "polyline", "polygon"}


class Node:
    def __init__(self, tag: str, attrs: dict, parent: Node | None):
        self.tag, self.attrs, self.parent, self.kids, self.text = tag, attrs, parent, [], []

    @property
    def classes(self) -> set[str]:
        return set((self.attrs.get("class") or "").split())

    def all(self):
        for kid in self.kids:
            yield kid
            yield from kid.all()

    def find(self, tag: str | None = None, cls: str | None = None, id: str | None = None):
        return [n for n in self.all() if (tag is None or n.tag == tag)
                and (cls is None or cls in n.classes) and (id is None or n.attrs.get("id") == id)]

    def inside(self, node: Node) -> bool:
        up = self.parent
        while up is not None:
            if up is node:
                return True
            up = up.parent
        return False

    def words(self) -> str:
        return " ".join("".join(self._bits()).split())

    def _bits(self):
        for part in self.text:
            yield part if isinstance(part, str) else "".join(part._bits())


class Tree(HTMLParser):
    def __init__(self, html: str):
        super().__init__(convert_charrefs=True)
        self.root = self.at = Node("root", {}, None)
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        node = Node(tag, dict(attrs), self.at)
        self.at.kids.append(node)
        self.at.text.append(node)
        if tag not in VOID:
            self.at = node

    def handle_startendtag(self, tag, attrs):
        node = Node(tag, dict(attrs), self.at)
        self.at.kids.append(node)
        self.at.text.append(node)

    def handle_endtag(self, tag):
        up = self.at
        while up is not None and up.tag != tag:
            up = up.parent
        if up is not None and up.parent is not None:
            self.at = up.parent

    def handle_data(self, data):
        self.at.text.append(data)


def _main(html: str) -> Node:
    return Tree(html).root.find("main", "result")[0]


# 1. The structure of each state ----------------------------------------------------------

def _ranged(r: dict) -> bool:
    shown = [report_page.estimate(r.get(k), r.get(f"{k}_interval"), report_page.why_for(r, k))
             for k in ("tpr", "tnr")]
    return any(b != "–" for _, b in shown) or report_page.kappa_shown(r)[1] is not None


def _apart(text: str) -> tuple[str, str | None]:
    """A shown number without " (you marked every answer)", and the why in its other brackets."""
    text = text.removesuffix(f" ({report_page.EVERY_MARKED})")
    m = re.fullmatch(r"(.+?) \((.+)\)", text)
    return (m.group(1), m.group(2)) if m else (text, None)


def _why_under(r: dict) -> bool:
    """Whether a number with no range says why under it."""
    shown = [report_page.estimate(r.get(k), r.get(f"{k}_interval"), report_page.why_for(r, k))[0]
             for k in ("tpr", "tnr")] + [report_page.kappa_shown(r)[0]]
    return any(_apart(t)[1] for t in shown)


def _exact(r: dict) -> bool:
    tail = f"({report_page.EVERY_MARKED})"
    said = [report_page.estimate(r.get(k), r.get(f"{k}_interval"), report_page.why_for(r, k))[0]
            for k in ("tpr", "tnr")] + [report_page.kappa_shown(r)[0]]
    return any(x.endswith(tail) for x in said)


@pytest.mark.parametrize("name, live", PAGES, ids=[_id(*p) for p in PAGES])
def test_each_state_has_its_sections_in_order(name, live):
    r, fixing, kw = state(name)
    html = page(name, live)
    main = _main(html)
    sections = [n for n in main.kids if n.tag in ("section", "div", "p")]
    verdict = main.find("section", "verdict")
    score = main.find("section", "score")
    assert len(verdict) == 1 and len(score) == 1
    assert sections.index(verdict[0]) < sections.index(score[0])
    score = score[0]
    result = r["check"] != "too_few" and r.get("verdict_level") is not None
    cnts = score.find("div", "cnts")
    assert len(cnts) == 1
    assert [p.classes & {"c-pass", "c-fail"} for p in cnts[0].find("p")] == [{"c-pass"},
                                                                             {"c-fail"}]
    if result:
        assert score.find(id="nums-h")
        cells = score.find("div", "cell")
        assert [sorted(c.classes - {"cell"}) for c in cells] == [["c-tpr"], ["c-tnr"],
                                                                  ["c-kappa"]]
        assert bool(score.find(cls="n-rng")) == (_ranged(r) or _why_under(r))
        assert bool(score.find("p", "foot")) == _exact(r)
    else:
        assert [k.tag for k in score.kids] == ["div"] and not score.find(cls="nums")
    assert not score.find(cls="sub") and "Estimated for all" not in html
    groups = main.find("section", "group")
    c = report_page.counts(r)
    with_rows = [m for m in fixing["mistakes"]] if report_page.shows_disagreements(r) else []
    kinds = {"easy" if m["judge"] == "pass" else "strict" for m in with_rows}
    assert len(groups) == len(kinds)
    for group in groups:
        for kept in group.find("p", "kept"):
            assert kept.parent.tag == "div" and "gh" in kept.parent.classes
    nexts = [n for n in main.find("section", "next-box") if n.find(id="next-h")]
    assert len(nexts) == (report_page.next_step(r) != "mark" and "worse" not in kw)
    for li in main.find("li"):
        assert li.parent.tag == "ul" and "notes-list" in li.parent.classes
    assert c["passed"] + c["failed"] > 0
    for gone in ('class="band', "More details", '<table class="panel', 'class="opt"',
                 "Optional: tell judgekeeper", "uses your reasons to find where",
                 "wider ranges than these"):
        assert gone not in html, gone


# 2. Pass and Fail in colour --------------------------------------------------------------

@pytest.mark.parametrize("name, live", PAGES, ids=[_id(*p) for p in PAGES])
def test_pass_and_fail_are_in_colour_in_the_headings_and_counts_only(name, live):
    main = _main(page(name, live))
    for group in main.find("section", "group"):
        h2 = group.find("h2")[0]
        assert len(h2.find("span", "w-pass")) == 1 and len(h2.find("span", "w-fail")) == 1
    for p in main.find("p", "c-pass") + main.find("p", "c-fail"):
        verb = p.find("span", "w-pass" if "c-pass" in p.classes else "w-fail")
        assert len(verb) == 1 and verb[0].words() in ("passed", "failed")
    coloured = main.find(cls="w-pass") + main.find(cls="w-fail")
    for box in main.find("table") + main.find("ul", "notes-list"):
        assert not [n for n in coloured if n.inside(box)]


# 3. Nothing from outside -----------------------------------------------------------------

@pytest.mark.parametrize("name, live", PAGES, ids=[_id(*p) for p in PAGES])
def test_nothing_is_loaded_or_linked_from_outside(name, live):
    html = page(name, live)
    for found in re.findall(r'(?:src|href)="([^"]*)"|url\(([^)]*)\)|@import\s+([^;]+)', html):
        link = next(x for x in found if x).strip("'\" ")
        assert not link.startswith(("http://", "https://", "//")), link
    links = re.findall(r'<a [^>]*href="([^"]*)"', html)
    if live:
        assert set(links) <= {"/?token=t"}
    else:
        assert not links and "token" not in html


# 4. The scripts the CSP allows -----------------------------------------------------------

SCRIPT_SHA256 = "9b80caabf5fca1ae4f1eee82f9569155cadfc66eca67cb75a6e6de5994d3990e"
REASONS_SCRIPT_SHA256 = "2d835a68c78a1dcf8a8128c671c582c1a94d96bb512b2f802f33be0078414fa3"


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@pytest.mark.parametrize("name, live", PAGES, ids=[_id(*p) for p in PAGES])
def test_every_script_on_the_page_is_in_its_own_csp(name, live):
    html = page(name, live)
    csp = re.search(r'<meta http-equiv="Content-Security-Policy" content="([^"]*)">', html)[1]
    assert csp == (report_page.LIVE_CSP if live else report_page.CSP)
    scripts = re.findall(r"<script>(.*?)</script>", html, re.DOTALL)
    assert scripts
    for script in scripts:
        assert look.script_hash(script) in csp


def test_the_two_scripts_are_pinned():
    """An edit to either script changes its hash in the CSP: this test names the new one."""
    assert _sha(report_page.SCRIPT) == SCRIPT_SHA256
    assert _sha(report_page.REASONS_SCRIPT) == REASONS_SCRIPT_SHA256


def test_the_ready_box_on_the_marking_page_shows_no_verdict_line():
    html = mark_page.label_page("support bot", "judgekeeper mark",
                                model="openai:gpt-4.1-mini", tool="promptfoo")
    box = html[html.index('<div class="ready" id="ready"'):html.index("</div>\n</div>",
                                                                      html.index('id="ready"'))]
    assert "ready-note" not in box and "ready-note" not in html
    assert "Your result is ready." in box and "See your result" in box and "Keep marking" in box


# 5. The same words, but for the approved changes -----------------------------------------

INLINE = {"b", "code", "a", "strong", "em"}
INLINE_SPANS = {"term", "mono", "w-pass", "w-fail", "about", "off", "cw"}  # cw: look.command


class _Pieces(HTMLParser):
    """The page's text in pieces: a new piece at every tag but inline ones."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.skip, self.spans = [""], 0, []

    def _cut(self):
        if self.out[-1].strip():
            self.out.append("")

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "svg"):
            self.skip += 1
        elif tag == "span":
            inline = bool(set((dict(attrs).get("class") or "").split()) & INLINE_SPANS) or \
                not dict(attrs).get("class")
            self.spans.append(inline)
            if not inline:
                self._cut()
        elif tag not in INLINE:
            self._cut()

    def handle_endtag(self, tag):
        if tag in ("script", "style", "svg"):
            self.skip -= 1
        elif tag == "span":
            if self.spans and not self.spans.pop():
                self._cut()
        elif tag not in INLINE:
            self._cut()

    def handle_data(self, data):
        if not self.skip:
            self.out[-1] += data


def sentences(html: str) -> list[str]:
    """Every sentence the page says, in order."""
    body = html.split("<body>", 1)[1]
    parser = _Pieces()
    parser.feed(body)
    out = []
    for piece in parser.out:
        text = " ".join(unescape(piece).split())
        out += [x for x in re.split(r"(?<=[.!?])\s+", text) if x]
    return out


APPROVED = [  # the wording changes this layout makes
    (r"^It passed (\d+) and failed (\d+)\.$", r"Of these, your LLM-as-a-judge passed \1 and failed \2."),
    (r"^(.+) \(you marked every answer\)$", r"\1"),
    (r"^(−?[\d.]+%?) and (−?[\d.]+%?)$", r"between \1 and \2"),
    ((r"^How often your LLM-as-a-judge agrees with you(, estimated for all \d+ answers \(you "
     r"marked \d+\))?\.$"), "How often your LLM-as-a-judge agrees with you"),
    ((r"^(\d+) more of these (is|are) kept aside on purpose, so a new rule can be tested on "
     r"answers you haven't looked at again\.$"), r"\1 more \2 kept aside to test your fix."),
    ((r"^(\d+) more (disagreements? (?:is|are)) kept aside on purpose, so a new rule can be "
     r"tested on answers you haven't looked at again\.$"), r"\1 more \2 kept aside to test your fix."),
    (r"^Next, in your terminal, in your project folder:$", "Next, in your project folder:"),
    (r"^Show all$", "Show more"),
]
CUT = {"More details", "Value", "Estimate", "Between", "Optional: tell judgekeeper why you disagree.",
       "judgekeeper fix uses your reasons to find where your LLM-as-a-judge goes wrong.",  # 6
       "The result uses wider ranges than these, so a lucky streak can't decide it.",
       "You can look after every mark."}
EXACT_NOTE = "You marked every answer, so these numbers are exact."


def approved(before: list[str]) -> list[str]:
    """The sentences of today's page with the approved changes made."""
    out, exact = [], False
    for line in before:
        if line in CUT:
            continue
        exact |= line.endswith(" (you marked every answer)")
        for old, new in APPROVED:
            line = re.sub(old, new, line)
        out.append(line)
    return out + ([EXACT_NOTE] if exact else [])


@pytest.mark.parametrize("name, live", TEXT_PAGES, ids=[_id(*p) for p in TEXT_PAGES])
def test_the_words_are_todays_but_for_the_approved_changes(name, live):
    """Only the order may change: the sentences of today's page (saved from main before the
    new layout) with the approved changes made are the new page's sentences."""
    before = json.loads(TEXT_BEFORE.read_text(encoding="utf-8"))[_id(name, live)]
    assert sorted(approved(before)) == sorted(sentences(page(name, live)))


# 6. The numbers match their counts -------------------------------------------------------

def _plain(node: Node) -> str:
    return node.words()


@pytest.mark.parametrize("name, live", PAGES, ids=[_id(*p) for p in PAGES])
def test_each_number_is_its_estimate_and_each_count_line_its_counts(name, live):
    r, _, _ = state(name)
    main = _main(page(name, live))
    if main.find(id="nums-h"):
        cells = {min(c.classes - {"cell"}): c for c in main.find("div", "cell")}
        for key in ("tpr", "tnr"):
            shown, between = report_page.estimate(r.get(key), r.get(f"{key}_interval"),
                                                  report_page.why_for(r, key))
            value, why = _apart(shown)
            cell = cells[f"c-{key}"]
            assert _plain(cell.find(cls="n-val")[0]) == value
            rng = cell.find(cls="n-rng")
            assert [_plain(x) for x in rng] == (
                [f"between {between}"] if between != "–" else [why] if why else [])
        kappa, lo, hi = report_page.kappa_shown(r)
        value, why = _apart(kappa)
        cell = cells["c-kappa"]
        assert _plain(cell.find(cls="n-val")[0]) == value
        assert [_plain(x) for x in cell.find(cls="n-rng")] == (
            [f"between {lo} and {hi}"] if lo is not None else [why] if why else [])
    c = report_page.counts(r)
    lines = [_plain(p) for p in main.find("div", "cnts")[0].find("p")]
    if main.find(id="nums-h"):
        assert lines == [
            (f"You passed {c['passed']} {'answer' if c['passed'] == 1 else 'answers'}. Of these, "
            f"your LLM-as-a-judge passed {c['passed'] - c['strict']} and failed {c['strict']}."),
            (f"You failed {c['failed']} {'answer' if c['failed'] == 1 else 'answers'}. Of these, "
            f"your LLM-as-a-judge passed {c['easy']} and failed {c['failed'] - c['easy']}.")]
    else:
        assert lines == [f"You passed {c['passed']} answers.", f"You failed {c['failed']} answers."]


# A number with no range: the value alone, why under it -----------------------------------

COUNTS = {"passed": 1, "failed": 1, "strict": 0, "easy": 0}


def _gate(**r) -> dict:
    return {"check": "result", "verdict_level": "gate", "kappa": None, "kappa_interval": None,
            **r}


CELL = re.compile(r'<span class="n-val">((?:<span class="about">[^<]*</span>)?[^<]*)</span>'
                  r'(?:<span class="n-rng">([^<]*)</span>)?</div>')


def _cells(page: str) -> list[tuple[str, str | None]]:
    """Each number cell's big value and the small line under it (None when there is none)."""
    return [(unescape(re.sub(r"<[^>]+>", "", v)), unescape(n) if n else None)
            for v, n in CELL.findall(page)]


@pytest.mark.parametrize("r, want", [
    # an LLM-as-a-judge that gave every answer one grade
    (_gate(tpr=1.0, tpr_interval=[1.0, 1.0], tnr=0.0, tnr_interval=[0.0, 0.0], left=14,
           groups={"pass": {"pool": 44}, "fail": {"pool": 0}}),
     [("100%", "it gave every answer the same grade"),
      ("0%", "it gave every answer the same grade"), ("n/a", None)]),
    # every answer it failed is marked: TPR has no range, TNR has one
    (_gate(tpr=1.0, tpr_interval=[1.0, 1.0], tnr=0.8, tnr_interval=[0.6, 0.9], left=9,
           groups={"pass": {"pool": 30}, "fail": {"pool": 20}}),
     [("100%", "you marked every answer it failed"), ("about 80%", "between 60% and 90%"),
      ("n/a", None)]),
])
def test_a_number_with_no_range_shows_its_value_alone_and_why_under_it(r, want):
    page = report_page._score(r, COUNTS)
    assert _cells(page) == want
    assert "(it gave" not in page and "(you marked" not in page


def test_every_answer_marked_still_says_it_once_at_the_foot():
    r = _gate(tpr=0.9, tpr_interval=[0.9, 0.9], tnr=0.8, tnr_interval=[0.8, 0.8], left=0,
              groups={"pass": {"pool": 30}, "fail": {"pool": 20}}, kappa=0.7,
              kappa_interval=[0.7, 0.7])
    page = report_page._score(r, COUNTS)
    assert _cells(page) == [("90%", None), ("80%", None), ("0.70", None)]
    assert page.count(report_page.EXACT) == 1


def test_the_three_numbers_sit_on_one_line_whatever_their_labels_length():
    style = report_page.STYLE
    assert ".nums { display: grid; grid-template-columns: 1fr 1fr 1fr; }" in style
    cell = style.split("\n.cell {", 1)[1].split("}", 1)[0]
    assert "grid-row: span 3" in cell and "grid-template-rows: subgrid" in cell
    assert "display: flex" not in cell
    lab = style.split("\n.n-lab {", 1)[1].split("}", 1)[0]
    assert "align-self: end" in lab
