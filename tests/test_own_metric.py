"""The "Your own metric" page and its two worked examples under docs/examples/own-metric/.

Example A (a plain Python function) is offline and reproducible: the generator writes the
same bytes every time, and judging the committed files again gives the committed report.
Example B (a DeepEval GEval metric) needs a live model, so its report is checked only when
it is committed. Every figure on the page and in the guide is read back from a report.
"""

from __future__ import annotations

import csv
import importlib.util
import json
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from judgekeeper.cli import _parser, main
from judgekeeper.prompts import FILL_IN, load_prompt
from tests.website_pages import ROOT, WEBSITE, command_lines, judgekeeper_argv

EXAMPLE = ROOT / "docs" / "examples" / "own-metric"
PAGE = ROOT / "docs" / "own-metric.md"
GUIDE = ROOT / "docs" / "guide.md"
FUNCTION_REPORT = EXAMPLE / "function" / "report.json"
DEEPEVAL_REPORT = EXAMPLE / "deepeval" / "report.json"
GENERATED = ("policy.md", "rule.md", "items.csv", "labels.csv", "anchors.jsonl",
             "anchors.manifest.json")
SLICES = ("correct", "wrong window", "over-promise", "polite but wrong")
PLACEHOLDER = re.compile(r"<[a-z]|\[--|\.\.\.")  # syntax lines such as [--pairwise]
NUMBER = re.compile(r"\d+\.\d+|\d+(?:\.\d+)?\s?%")


def _load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _report(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _labels(anchors: Path) -> dict[str, tuple]:
    items = [json.loads(line) for line in anchors.read_text(encoding="utf-8").splitlines()]
    return {i["id"]: (i["input"], i["output"], i["human_label"], i.get("slice")) for i in items}


def _rows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


# The files

def test_the_generator_is_deterministic(tmp_path):
    module = _load_script("make_own_metric_example")
    module.build(tmp_path)
    for name in GENERATED:
        assert (tmp_path / name).read_bytes() == (EXAMPLE / name).read_bytes(), name
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(GENERATED)


def test_the_rule_is_the_filled_in_template():
    text = (EXAMPLE / "rule.md").read_text(encoding="utf-8")
    assert FILL_IN not in text
    prompt = load_prompt(EXAMPLE / "rule.md")
    assert prompt.rubric_version != "my-metric-v1"
    assert "{{input}}" in prompt.template and "{{output}}" in prompt.template
    assert "refund" in text.lower()


def test_the_items_and_labels_are_by_construction():
    items = _rows(EXAMPLE / "items.csv")
    labels = _rows(EXAMPLE / "labels.csv")
    assert len(items) == 60
    assert {i["slice"] for i in items} == set(SLICES)
    assert [i["id"] for i in items] == [r["id"] for r in labels]
    for item, row in zip(items, labels, strict=True):
        assert row["input"] == item["input"] and row["output"] == item["output"]
        expected = "pass" if item["slice"] == "correct" else "fail"
        assert row["human_label"] == expected, item["id"]
    anchors = [json.loads(line) for line in
               (EXAMPLE / "anchors.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [a["id"] for a in anchors] == [i["id"] for i in items]
    dist = _report(EXAMPLE / "anchors.manifest.json")["label_distribution"]
    assert dist == {"pass": 30, "fail": 30}


# Example A: the function judge

def _run_example_a(out: Path, monkeypatch) -> dict:
    monkeypatch.chdir(EXAMPLE)
    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    runs = out / "runs"
    assert main(["judge", "anchors.jsonl", "--callable", "function_judge:judge",
                 "--prompt", "rule.md", "--model", "function_judge.py", "--runs", "3",
                 "--out", str(runs)]) == 0
    assert main(["validate", "anchors.jsonl", str(runs), "--out", str(out / "report")]) == 0
    sys.modules.pop("function_judge", None)
    return _report(out / "report" / "report.json")


def _comparable(report: dict) -> dict:
    fp = {k: v for k, v in report["fingerprint"].items() if k != "created_at"}
    runs = [{k: v for k, v in r.items() if k != "file"} for r in report["runs"]]
    return {"anchors": report["anchors"], "fingerprint": fp, "n_runs": report["n_runs"],
            "headline": report["headline"], "verdict": report["verdict"], "runs": runs,
            "noise_floor": report["noise_floor"], "slices": report["slices"],
            "disagreements": report["disagreements"], "items": report["items"],
            "source": report["source"]}


def test_a_fresh_run_reproduces_the_committed_report(tmp_path, monkeypatch):
    fresh = _run_example_a(tmp_path, monkeypatch)
    assert _comparable(fresh) == _comparable(_report(FUNCTION_REPORT))


def test_the_function_judge_is_imperfect_on_a_slice():
    report = _report(FUNCTION_REPORT)
    assert report["source"]["kind"] == "callable"
    assert report["fingerprint"]["rubric_version"] == load_prompt(EXAMPLE / "rule.md").rubric_version
    assert report["n_runs"] == 3 and report["anchors"]["n_items"] == 60
    assert {s["slice"] for s in report["slices"]} == set(SLICES)
    weak = [s["slice"] for s in report["slices"]
            if (s["tpr_mean"] is not None and s["tpr_mean"] < 1)
            or (s["tnr_mean"] is not None and s["tnr_mean"] < 1)]
    assert weak
    assert report["disagreements"]
    assert (EXAMPLE / "function" / "report.html").read_text(encoding="utf-8").startswith(
        "<!doctype html>")


# Example B: the DeepEval metric

def test_the_deepeval_script_is_committed_and_takes_no_key_from_a_file():
    text = (EXAMPLE / "deepeval_metric.py").read_text(encoding="utf-8")
    assert "JUDGEKEEPER_ANTHROPIC_KEY" in text
    assert "https://api.anthropic.com" in text
    assert "claude-haiku-4-5-20251001" in text
    assert "import deepeval" in text  # the judgekeeper command it runs at the end
    assert "sk-ant-" not in text


@pytest.mark.skipif(not DEEPEVAL_REPORT.is_file(), reason="example B has not been run")
def test_the_deepeval_report_records_source_and_judge():
    report = _report(DEEPEVAL_REPORT)
    assert report["source"]["kind"] == "deepeval"
    fp = report["fingerprint"]
    assert fp["provider"] == "anthropic"
    assert fp["model"].startswith("claude-haiku-4-5-20251001")  # DeepEval appends " (Anthropic)"
    assert "provider" not in report["fingerprint_unknown"]
    assert "model" not in report["fingerprint_unknown"]
    assert report["n_runs"] == 3 and report["anchors"]["n_items"] == 60
    # the same items and labels as example A (the import keeps id, text, label and slice)
    assert _labels(EXAMPLE / "deepeval" / "anchors.jsonl") == _labels(EXAMPLE / "anchors.jsonl")
    assert (EXAMPLE / "deepeval" / "report.html").is_file()


# The page

def _page_sections() -> dict[str, str]:
    text = PAGE.read_text(encoding="utf-8")
    parts = re.split(r"^## ", text, flags=re.MULTILINE)
    return {part.splitlines()[0]: part for part in parts[1:]}


def _section(contains: str) -> str:
    sections = _page_sections()
    (key,) = [k for k in sections if contains in k]
    return sections[key]


def _prose(markdown: str) -> str:
    return re.sub(r"```.*?```", "", markdown, flags=re.DOTALL)


def _tables(markdown: str) -> list[list[list[str]]]:
    tables, current = [], []
    for line in markdown.splitlines():
        if line.startswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if not set("".join(cells)) <= set("-: "):
                current.append(cells)
        elif current:
            tables.append(current)
            current = []
    if current:
        tables.append(current)
    return tables


def _figures(report: dict) -> set[str]:
    out = set()
    h = report["headline"]
    for key in ("kappa_mean", "tpr_mean", "tnr_mean", "kappa_min", "kappa_max"):
        out.add(f"{h[key]:.2f}")
    for r in report["runs"]:
        out |= {f"{r[k]:.2f}" for k in ("kappa", "tpr", "tnr") if r[k] is not None}
    for s in report["slices"]:
        out |= {f"{s[k]:.2f}" for k in ("kappa_mean", "tpr_mean", "tnr_mean")
                if s[k] is not None}
    nf = report["noise_floor"]
    if nf.get("items_flipped_fraction") is not None:
        out |= {f"{nf['items_flipped_fraction']:.0%}", f"{nf['items_flipped_fraction']:.1%}"}
    return out


def _slice_table(section: str) -> dict[str, list[str]]:
    (table,) = [t for t in _tables(section) if t[0][0] == "Slice"]
    assert table[0] == ["Slice", "Items", "Kappa", "TPR", "TNR"]
    return {row[0]: row[1:] for row in table[1:]}


def _cell(value) -> str:
    return "n/a" if value is None else f"{value:.2f}"  # one class in a slice: no kappa, no TNR


def _check_slices(section: str, report: dict) -> None:
    rows = _slice_table(section)
    assert set(rows) == {s["slice"] for s in report["slices"]}
    for s in report["slices"]:
        assert rows[s["slice"]] == [str(s["n"]), *(_cell(s[k]) for k in
                                                   ("kappa_mean", "tpr_mean", "tnr_mean"))], s["slice"]


def _headline_sentence(report: dict) -> str:
    h = report["headline"]
    return f"kappa {h['kappa_mean']:.2f}, TPR {h['tpr_mean']:.2f}, TNR {h['tnr_mean']:.2f}"


def test_the_page_has_its_sections():
    heads = list(_page_sections())
    assert len(heads) == 6
    for n, needle in enumerate(("idea", "rule", "example A", "example B", "any rule",
                                "does not do"), 1):
        assert heads[n - 1].startswith(f"{n}.") and needle in heads[n - 1], heads[n - 1]


def test_the_page_quotes_example_a_from_its_report():
    report = _report(FUNCTION_REPORT)
    section = _section("example A")
    assert _headline_sentence(report) in section
    _check_slices(section, report)
    for word in ("synthetic", "by construction", "illustration", "one example"):
        assert word in section, word


def test_the_page_quotes_example_b_from_its_report():
    section = _section("example B")
    if not DEEPEVAL_REPORT.is_file():
        assert not NUMBER.search(_prose(section)), "no results without a committed run"
        return
    report = _report(DEEPEVAL_REPORT)
    assert _headline_sentence(report) in section
    _check_slices(section, report)


def test_no_unsourced_numbers_on_the_page():
    allowed = _figures(_report(FUNCTION_REPORT))
    if DEEPEVAL_REPORT.is_file():
        allowed |= _figures(_report(DEEPEVAL_REPORT))
    text = _prose(PAGE.read_text(encoding="utf-8"))
    bad = [m for m in NUMBER.findall(text) if m not in allowed]
    assert not bad, bad


def test_every_command_on_the_page_parses():
    text = PAGE.read_text(encoding="utf-8")
    blocks = re.findall(r"```(?:\w*)\n(.*?)```", text, flags=re.DOTALL)
    found = []
    for block in blocks:
        for line in command_lines(block):
            argv = judgekeeper_argv(line)
            if argv is not None and not PLACEHOLDER.search(line):
                found.append((line, argv))
    assert len(found) >= 6
    for line, argv in found:
        try:
            _parser().parse_args(argv)
        except SystemExit as e:
            pytest.fail(f"`judgekeeper {' '.join(argv)}` does not parse (exit {e.code}): {line}")


def test_the_page_shows_three_other_rules_and_the_limits():
    section = _section("any rule")
    for topic in ("doctor", "folder", "action item"):
        assert topic in section, topic
    assert "different" in section
    limits = _section("does not do")
    assert "rule" in limits and "label" in limits


def test_the_page_is_rendered_and_current(tmp_path):
    out = tmp_path / "own-metric.html"
    subprocess.run([sys.executable, str(ROOT / "scripts/render_reference.py"), str(PAGE),
                    str(out)], check=True, capture_output=True)
    assert out.read_text(encoding="utf-8") == (WEBSITE / "own-metric.html").read_text(
        encoding="utf-8"), "run: python scripts/render_reference.py"


def test_the_site_links_the_page():
    # The page is in the top bar and linked from inside the other pages.
    for name in ("start.html", "index.html", "setup.html", "tutorial.html"):
        assert 'href="own-metric.html"' in (WEBSITE / name).read_text(encoding="utf-8"), name
    tree = ET.parse(WEBSITE / "sitemap.xml")
    locs = [el.text for el in tree.iter() if el.tag.endswith("loc")]
    assert "https://www.judgekeeper.com/own-metric.html" in locs


# The guide (the short README, the package description and the home page carry the main
# message; tests/test_front_door.py checks them)

def test_the_guide_carries_the_own_metric_message_and_links_the_page():
    text = GUIDE.read_text(encoding="utf-8")
    assert ("**Bring your own metric. judgekeeper checks it against your labels and tells you "
            "when that check is out of date.**") in text
    assert "](own-metric.md)" in text
    assert "judgekeeper init" in text
    assert "before the first PyPI release" not in text
    assert "JUDGE_CHANGED" in text and "ANCHORS_CHANGED" in text
    assert "metric card" not in text.lower()


def test_the_guide_quotes_the_examples_from_their_reports():
    text = GUIDE.read_text(encoding="utf-8")
    assert _headline_sentence(_report(FUNCTION_REPORT)) in text
    assert "synthetic" in text and "by construction" in text
    if DEEPEVAL_REPORT.is_file():
        assert _headline_sentence(_report(DEEPEVAL_REPORT)) in text


def test_the_package_keeps_the_own_metric_keywords_and_the_site_links_the_page():
    import tomllib

    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert {"custom-metric", "rubric"} <= set(project["keywords"])
    assert 'href="own-metric.html"' in (WEBSITE / "start.html").read_text(encoding="utf-8")
