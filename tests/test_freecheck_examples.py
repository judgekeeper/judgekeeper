"""The browser check's example files (website/assets/examples/), its three example cards and
the page around them.

Each example ships as a small script that sets window.JK_EXAMPLES[<file name>], added to the
page on the first click, so the page's policy keeps connect-src 'none'. Each example reads the
same in the page and in the tool. tests/freecheck_page.mjs runs the page's own code on a
stand-in for check.html: an example clicked or dragged in, a file of your own dropped, Clear.

Needs node; skipped with the reason when it is missing.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

from judgekeeper import front, start
from tests.test_freecheck_parity import (
    NODE,
    ROOT,
    _page,
    browser,
    page_answers,
    page_runs,
    tool,
    tool_answers,
    tool_runs,
)
from tests.website_pages import WEBSITE, parse

pytestmark = pytest.mark.skipif(NODE is None, reason="needs node to run the page's free check")

EXAMPLES = WEBSITE / "assets" / "examples"
GRADED = ["shop-answers.csv", "promptfoo-results.json", "two-llm-as-a-judge-metrics.json"]
NAMES = [*GRADED, "shop-answers-no-grades.csv", "agent-runs.jsonl"]
# The three cards under the drop box: each one's title, line and the example it opens.
CARDS = [("Eval results", "LLM-as-a-judge grades", "shop-answers.csv"),
         ("Answers only", "no LLM-as-a-judge", "shop-answers-no-grades.csv"),
         ("Agent runs", "for an agent-as-a-judge", "agent-runs.jsonl")]
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


def test_no_example_names_a_real_model():
    """The examples are shown on the page as they are: their LLM-as-a-judge and the model it
    grades have neutral names (my-judge-v1, my-app-model)."""
    real = re.compile(r"gpt-|openai|claude|anthropic|gemini|llama|mistral", re.IGNORECASE)
    for name in NAMES:
        assert not real.search(_text(name)), name
    assert "my-judge-v1" in _text("promptfoo-results.json")


def _page_state(*steps: str) -> list[dict]:
    out = subprocess.run([NODE, str(ROOT / "tests" / "freecheck_page.mjs"), *steps],
                         capture_output=True, text=True, check=True, encoding="utf-8")
    return json.loads(out.stdout)


def test_the_page_offers_the_three_examples_as_cards_that_drag():
    cards = [el for el in parse(WEBSITE / "check.html").iter() if "ex-card" in el.classes()]
    assert len(cards) == len(CARDS)
    for card, (name, kind, file) in zip(cards, CARDS, strict=True):
        assert card.tag == "button" and card.attrs.get("type") == "button"
        assert [" ".join(e.text().split()) for e in card.iter() if e.tag in ("b", "span")
                and not e.classes() and e.parent.classes() == {"ex-t"}] == [name, kind]
        assert card.attrs.get("data-example-file") == file  # each opens its example, and drags
        assert card.attrs.get("draggable") == "true"
        assert "data-preview-kind" not in card.attrs
    assert sorted(p.name for p in EXAMPLES.iterdir()) == sorted(f"{n}.js" for n in NAMES)
    script = (WEBSITE / "assets" / "freecheck.js").read_text(encoding="utf-8")
    assert "'assets/examples/' + file + '.js'" in script  # a script from the site, never fetched


@pytest.mark.parametrize("name", GRADED)
def test_each_example_reads_the_same_in_the_page_and_the_tool(files, name, monkeypatch):
    """Run in the file's own folder, as the page stands for (it knows only the file's name)."""
    path = files[name]
    monkeypatch.chdir(path.parent)
    page = browser(path)
    assert _page(page) == tool(path)
    for judge in page["judges"]:
        found = start.find_judge(path, metric=judge["key"] if len(page["judges"]) > 1 else None)
        block = front.found_block(found)
        assert judge["lines"][:len(block)] == block


@pytest.mark.parametrize("name", GRADED)
def test_each_example_reads_the_same_in_a_folder_under_home(tmp_path, monkeypatch, name):
    """As on a Windows runner, where the temporary folder is under the home folder."""
    home = tmp_path.resolve() / "Users" / "ann-x"
    path = home / "AppData" / name / name
    path.parent.mkdir(parents=True)
    path.write_text(_text(name), encoding="utf-8")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    test_each_example_reads_the_same_in_the_page_and_the_tool({name: path}, name, monkeypatch)


def test_each_example_shows_what_it_is_there_for(files):
    shop, repeats, two = (browser(files[n]) for n in GRADED)
    (judge,) = shop["judges"]
    assert (judge["answers"], judge["pass"], judge["fail"]) == (60, 45, 15)
    assert "  reason     the reason column" in judge["lines"]
    assert "  model      the judge_model column" in judge["lines"]
    (judge,) = repeats["judges"]
    assert (f"{front.INDENT}(your file has 18 results: 6 answers, each run 3 times. Repeats "
            "with the same grade count once. 1 answer got different grades, so each of its 3 "
            "repeats counts.)") in judge["lines"]
    assert [j["key"] for j in two["judges"]] == ["helpful", "polite"]  # the page asks which
    for name in NAMES:  # made up for a shop, never a test's placeholders
        text = files[name].read_text(encoding="utf-8")
        for gone in ("What is 1 + 1", "My answer to", "Question 0?", "Answer 0.",
                     "Second line of the rubric", "grader.py", "(shortened)"):
            assert gone not in text and gone not in "\n".join(_printed(files[name])), (name, gone)


def _printed(path: Path) -> list[str]:
    said = browser(path)
    return said.get("lines") or [line for j in said["judges"] for line in j["lines"]]


def test_the_answers_only_example_reads_as_the_tool_reads_it(files, monkeypatch):
    path = files["shop-answers-no-grades.csv"]
    monkeypatch.chdir(path.parent)
    said = browser(path)
    assert said["kind"] == "answers" and page_answers(said) == tool_answers(path)
    assert said["lines"][3:13] == [
        "Eval tool:       your own CSV file",
        "File:            shop-answers-no-grades.csv",
        "Answers:         40 answers",
        "LLM-as-a-judge:  none in your file",
        "",
        ("This file has no LLM-as-a-judge grades, so judgekeeper checks the answers of your "
         "agent or chatbot: you mark each one Pass or Fail."),
        "",
        "First answer in your file:",
        "  Question:      Can I return a lamp after 60 days?",
        "  Answer:        Of course! We accept returns at any time, no questions asked."]


def test_the_agent_runs_example_reads_as_judgekeeper_steps_reads_it(files, monkeypatch):
    path = files["agent-runs.jsonl"]
    monkeypatch.chdir(path.parent)
    said = browser(path)
    assert said["kind"] == "runs" and page_runs(said) == tool_runs(path)
    assert said["lines"][:11] == [
        "$ judgekeeper steps agent-runs.jsonl",
        "",
        "File:            agent-runs.jsonl",
        "Runs:            12 runs",
        "Steps:           3 to 8 in each run",
        "",
        ("This file has agent runs, so judgekeeper checks each run's steps: you click the first "
         "wrong step, or All steps are fine."),
        "",
        "First run in your file:",
        "  Step 1  user       I want to return order 4471.",
        "  Step 2  tool call  lookup_order(4471)"]
    assert said["lines"][-1] == ("Next: to click the first wrong step of each run, run "
                                 "judgekeeper steps agent-runs.jsonl in your project folder.")


@pytest.mark.parametrize("how", ["click", "drag"])
def test_an_example_clicked_or_dragged_in_is_checked_and_clear_brings_the_page_back(how):
    before, loaded, cleared = _page_state("clear", f"{how}:shop-answers.csv", "clear")
    shown = MADE_UP + "shop-answers.csv"
    assert loaded["title"] == loaded["name"] == shown
    assert f"File:            {shown}" in loaded["output"]
    assert "Answers:         60 answers" in loaded["output"]
    assert loaded["scripts"] == ["assets/examples/shop-answers.csv.js"]
    assert loaded["box"] == "file" and loaded["has_file"] and loaded["clear"]
    assert not loaded["examples"] and not loaded["waiting"]
    for state in (cleared, before):
        assert state["title"] == "your file" and state["box"] == "empty"
        assert state["examples"] and state["waiting"] and not state["clear"]
        assert not state["output"] and not state["has_file"]
    assert cleared["focus"] == "fc-drop"  # Clear puts the focus back on the drop box


@pytest.mark.parametrize(("how", "name", "line"), [
    ("click", "shop-answers-no-grades.csv", "Answers:         40 answers"),
    ("drag", "agent-runs.jsonl", "Runs:            12 runs")])
def test_the_answers_and_runs_cards_open_their_examples(how, name, line):
    before, loaded, cleared = _page_state("clear", f"{how}:{name}", "clear")
    shown = MADE_UP + name
    assert loaded["title"] == loaded["name"] == shown
    assert f"File:            {shown}" in loaded["output"] and line in loaded["output"]
    assert loaded["scripts"] == [f"assets/examples/{name}.js"]
    assert loaded["box"] == "file" and loaded["has_file"] and loaded["clear"]
    for state in (cleared, before):
        assert state["box"] == "empty" and state["examples"] and not state["output"]


def test_each_example_script_only_sets_its_file():
    """One assignment of a JSON string to window.JK_EXAMPLES[<its name>], and nothing else."""
    pattern = re.compile(r'\(window\.JK_EXAMPLES = window\.JK_EXAMPLES \|\| \{\}\)'
                         r'\["([\w.-]+)"\] = ("(?:[^"\\\n]|\\.)*");\n?')
    assert sorted(p.name for p in EXAMPLES.glob("*.js")) == sorted(f"{n}.js" for n in NAMES)
    for name in NAMES:
        script = (EXAMPLES / f"{name}.js").read_text(encoding="utf-8")
        found = pattern.fullmatch(script)
        assert found and found[1] == name, name
        assert isinstance(json.loads(found[2]), str), name


@pytest.mark.parametrize("dropped", ["../../assets/freecheck", "nope.csv", "shop-answers.csv.js"])
def test_a_dropped_name_that_is_no_example_loads_nothing(dropped):
    before, after = _page_state("clear", f"name:{dropped}")
    assert after == {**before, "step": after["step"]}
    assert after["scripts"] == [] and not after["output"]


def test_a_file_of_your_own_dropped_after_an_example_takes_its_place(files, tmp_path):
    own = tmp_path / "results.csv"
    own.write_text("input,output,verdict\nq1,a1,pass\nq2,a2,fail\n", encoding="utf-8")
    example, mine = _page_state("click:shop-answers.csv", f"file:{own}")
    assert example["name"] == MADE_UP + "shop-answers.csv"
    assert mine["title"] == mine["name"] == "results.csv"
    assert "File:            results.csv" in mine["output"] and "shop" not in mine["output"]
    assert not mine["examples"] and mine["clear"]
