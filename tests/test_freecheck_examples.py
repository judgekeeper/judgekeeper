"""The browser check's three example files (website/assets/examples/) and the page around them.

Each example ships as a small script that sets window.JK_EXAMPLES[<file name>], added to the
page on the first click, so the page's policy keeps connect-src 'none'. Each example reads the
same in the page and in the tool. tests/freecheck_page.mjs runs the page's own code on a
stand-in for check.html: an example clicked or dragged in, a file of your own dropped, Clear.

Needs node; skipped with the reason when it is missing.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from judgekeeper import front, start
from tests.test_freecheck_parity import NODE, ROOT, _page, browser, tool
from tests.website_pages import WEBSITE, parse

pytestmark = pytest.mark.skipif(NODE is None, reason="needs node to run the page's free check")

EXAMPLES = WEBSITE / "assets" / "examples"
NAMES = ["shop-answers.csv", "promptfoo-results.json", "two-llm-as-a-judge-metrics.json"]
CARDS = [("Shop answers", "CSV"), ("Repeated runs", "promptfoo"), ("Two metrics", "promptfoo")]
MADE_UP = "made-up example · "


def _text(name: str) -> str:
    """The example's file, as its script hands it to the page."""
    script = (EXAMPLES / f"{name}.js").read_text(encoding="utf-8")
    run = ("globalThis.window = globalThis; require(process.argv[1]); "
           "process.stdout.write(JSON.stringify(window.JK_EXAMPLES))")
    out = subprocess.run([NODE, "-e", run, str(EXAMPLES / f"{name}.js")], capture_output=True,
                         text=True, check=True, encoding="utf-8")
    loaded = json.loads(out.stdout)
    assert list(loaded) == [name], script[:80]  # each script sets its own file, nothing else
    return loaded[name]


@pytest.fixture(scope="module")
def files(tmp_path_factory) -> dict[str, Path]:
    folder = tmp_path_factory.mktemp("examples")
    paths = {}
    for name in NAMES:
        paths[name] = folder / name / name  # each in a folder of its own, as a person's file
        paths[name].parent.mkdir()
        paths[name].write_text(_text(name), encoding="utf-8")
    return paths


def _page_state(*steps: str) -> list[dict]:
    out = subprocess.run([NODE, str(ROOT / "tests" / "freecheck_page.mjs"), *steps],
                         capture_output=True, text=True, check=True, encoding="utf-8")
    return json.loads(out.stdout)


def test_the_page_offers_the_three_examples_as_cards_that_drag():
    cards = [el for el in parse(WEBSITE / "check.html").iter() if "data-example-file" in el.attrs]
    assert [c.attrs["data-example-file"] for c in cards] == NAMES
    for card, (name, kind) in zip(cards, CARDS, strict=True):
        assert card.tag == "button" and card.attrs.get("draggable") == "true"
        assert [" ".join(e.text().split()) for e in card.iter() if e.tag in ("b", "span")
                and not e.classes() and e.parent.classes() == {"ex-t"}] == [name, kind]
    assert sorted(p.name for p in EXAMPLES.iterdir()) == sorted(f"{n}.js" for n in NAMES)
    script = (WEBSITE / "assets" / "freecheck.js").read_text(encoding="utf-8")
    assert "'assets/examples/' + file + '.js'" in script  # a script from the site, never fetched


@pytest.mark.parametrize("name", NAMES)
def test_each_example_reads_the_same_in_the_page_and_the_tool(files, name):
    path = files[name]
    page = browser(path)
    assert _page(page) == tool(path)
    for judge in page["judges"]:
        found = start.find_judge(path, metric=judge["key"] if len(page["judges"]) > 1 else None)
        block = front.found_block(found)
        assert judge["lines"][:len(block)] == block


def test_each_example_shows_what_it_is_there_for(files):
    shop, repeats, two = (browser(files[n]) for n in NAMES)
    (judge,) = shop["judges"]
    assert (judge["answers"], judge["pass"], judge["fail"]) == (60, 45, 15)
    assert "  reason     the reason column" in judge["lines"]
    assert "  model      the judge_model column" in judge["lines"]
    (judge,) = repeats["judges"]
    assert (f"{front.INDENT}(your file has 18 results: 6 answers, each run 3 times. Repeats "
            "with the same grade count once. 1 answer got different grades, so its 3 repeats "
            "each count.)") in judge["lines"]
    assert [j["key"] for j in two["judges"]] == ["helpful", "polite"]  # the page asks which
    for name in NAMES:  # made up for a shop, never a test's placeholders
        text = files[name].read_text(encoding="utf-8")
        for gone in ("What is 1 + 1", "My answer to", "Question 0?", "Answer 0.",
                     "Second line of the rubric", "grader.py", "(shortened)"):
            assert gone not in text and gone not in "\n".join(
                line for j in browser(files[name])["judges"] for line in j["lines"]), (name, gone)


@pytest.mark.parametrize("how", ["click", "drag"])
def test_an_example_clicked_or_dragged_in_is_checked_and_clear_brings_the_page_back(how):
    before, loaded, cleared = _page_state("clear", f"{how}:promptfoo-results.json", "clear")
    shown = MADE_UP + "promptfoo-results.json"
    assert loaded["title"] == loaded["name"] == shown
    assert f"File:        {shown}" in loaded["output"]
    assert "6 answers, each run 3 times" in loaded["output"]
    assert loaded["box"] == "file" and loaded["has_file"] and loaded["clear"]
    assert not loaded["examples"] and not loaded["waiting"]
    for state in (cleared, before):
        assert state["title"] == "your results file" and state["box"] == "empty"
        assert state["examples"] and state["waiting"] and not state["clear"]
        assert not state["output"] and not state["has_file"]
    assert cleared["focus"] == "fc-drop"  # Clear puts the focus back on the drop box


def test_a_file_of_your_own_dropped_after_an_example_takes_its_place(files, tmp_path):
    own = tmp_path / "results.csv"
    own.write_text("input,output,verdict\nq1,a1,pass\nq2,a2,fail\n", encoding="utf-8")
    example, mine = _page_state("click:shop-answers.csv", f"file:{own}")
    assert example["name"] == MADE_UP + "shop-answers.csv"
    assert mine["title"] == mine["name"] == "results.csv"
    assert "File:        results.csv" in mine["output"] and "shop" not in mine["output"]
    assert not mine["examples"] and mine["clear"]
