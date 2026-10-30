"""The README's numbers and the example reports they come from: every % comes with its range,
and every link into docs/examples/ points at a committed file."""

from __future__ import annotations

import re

from tests.website_pages import ROOT, WEBSITE, pages

README = ROOT / "README.md"
PCT = r"\d+(?:\.\d+)?%"
RANGE = re.compile(rf"\(?(?:between|range) {PCT} (?:and|to) {PCT}\)?")
AFTER = re.compile(rf"\s*[(,]\s*(?:between|range) {PCT} (?:and|to) {PCT}")


def _unranged(text: str) -> list[str]:
    """Each % that is not inside a range and not followed by one, with its context."""
    inside = [m.span() for m in RANGE.finditer(text)]
    out = []
    for m in re.finditer(PCT, text):
        if any(a <= m.start() < b for a, b in inside):
            continue
        if not AFTER.match(text, m.end()):
            out.append(text[max(0, m.start() - 40):m.end() + 20])
    return out


def test_every_percent_in_the_readme_comes_with_its_range():
    """The one bare percentage is the bar for "good enough to use", from the code."""
    from judgekeeper import targets

    gate = (f"the low end of both TPR and TNR is at least "
            f"{targets.RATE_GATE:.0%}.")
    text = README.read_text(encoding="utf-8")
    assert gate in text
    assert not _unranged(text.replace(gate, ""))


def test_the_range_check_catches_a_bare_percent():
    assert _unranged("It agreed 91% of the time.")
    assert not _unranged("about 62% (between 55% and 69%)")
    assert not _unranged("0 of 20 (0%, range 0% to 16%)")


def _example_links(text: str) -> set[str]:
    """docs/examples/... paths in a page, and a site page's examples/... links."""
    found = set(re.findall(r"docs/examples/[\w./-]*[\w/]", text))
    for link in re.findall(r"""(?:href|src)=["'](?:\.?/)?examples/([^"'#?]*)""", text):
        found.add("docs/examples/" + link)
    return found


def test_every_link_into_docs_examples_points_at_a_committed_file():
    sources = [README, *pages(), WEBSITE / "llms.txt"]
    links = {}
    for source in sources:
        for link in _example_links(source.read_text(encoding="utf-8")):
            links.setdefault(link, source.relative_to(ROOT).as_posix())
    assert any(source == "README.md" for source in links.values())
    for link, source in sorted(links.items()):
        assert (ROOT / link.rstrip("/")).exists(), (source, link)


DATASETS = {"jailbreakbench": "886acc352a31533ffbcf4ef22c744658688086fc",
            "jailbreakbench-claude": "886acc352a31533ffbcf4ef22c744658688086fc",
            "ragtruth": "c103204b9ce28d6bbad859304bf30de72b8ed8fe",
            "ragtruth-qa": "c103204b9ce28d6bbad859304bf30de72b8ed8fe",
            "ragtruth-data2txt": "c103204b9ce28d6bbad859304bf30de72b8ed8fe",
            "probes": "c103204b9ce28d6bbad859304bf30de72b8ed8fe"}


def test_every_results_file_from_a_dataset_says_where_it_comes_from():
    import json

    for folder, revision in DATASETS.items():
        for path in sorted((ROOT / "docs" / "examples" / folder).rglob("*")):
            name = path.relative_to(ROOT).as_posix()
            text = path.read_text(encoding="utf-8") if path.is_file() else ""
            if path.suffix in (".csv", ".txt") and path.name != "rule.txt":
                assert text.startswith("# Source: "), name
                assert f"# Revision: {revision}\n" in text, name
            elif path.suffix == ".json" and path.name != "sample-ids.json":
                source = next(iter(json.loads(text).items()))
                assert source[0] == "source" and source[1]["revision"] == revision, name
            elif path.suffix == ".html":
                assert text.startswith("<!doctype html>\n<!--\nSource: "), name
                assert f"Revision: {revision}\n" in text, name
    for folder in ("ragtruth", "ragtruth-qa", "ragtruth-data2txt"):
        sample = json.loads((ROOT / "docs/examples" / folder / "sample-ids.json").read_text(
            encoding="utf-8"))
        assert sample["commit"] == DATASETS[folder] and sample["filter"], folder
        assert [len(ids) for ids in sample["ids"].values()] == [100, 100], folder


def test_each_ragtruth_config_holds_its_frozen_rule_once_and_one_judge_slot():
    for folder in ("ragtruth", "ragtruth-qa", "ragtruth-data2txt"):
        base = ROOT / "docs" / "examples" / folder
        rule = (base / "rule.txt").read_text(encoding="utf-8").strip()
        config = (base / "promptfooconfig.yaml").read_text(encoding="utf-8")
        assert config.count(rule) == 1 and config.count("JUDGE_PROVIDER") == 1, folder


def test_the_datasets_licenses_and_citations_are_in_the_notices():
    text = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    for needed in ("Copyright (c) 2023 JailbreakBench Team", "Copyright (c) 2023 Particle Media",
                   "NeurIPS 2024 Datasets and Benchmarks Track", "ACL 2024",
                   "https://github.com/JailbreakBench/jailbreakbench",
                   "https://github.com/ParticleMedia/RAGTruth", *DATASETS.values()):
        assert needed in text, needed
    assert text.count("Permission is hereby granted, free of charge") == 4
    for folder in ("jailbreakbench", "ragtruth", "ragtruth-qa", "ragtruth-data2txt"):
        loader = (ROOT / "docs" / "examples" / folder / "load.py").read_text(encoding="utf-8")
        assert DATASETS[folder] in loader and "print(NOTICE)" in loader, folder


def test_the_notices_name_every_dataset_the_examples_use():
    """Each folder whose loader downloads a dataset, and each dataset the real-data check
    cites, has its section; the fonts are named too."""
    import json

    text =(ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    headings = re.findall(r"^## (.+)$", text, flags=re.MULTILINE)
    examples = ROOT / "docs" / "examples"
    for loader in sorted(examples.glob("*/load.py")):
        assert f"`docs/examples/{loader.parent.name}/`" in text, loader.parent.name
    check = json.loads((examples / "real-data-check" / "report.json").read_text(encoding="utf-8"))
    for data in check["data"].values():
        assert data["name"] in headings, data["name"]
        assert data["source"] in text and data["revision"] in text, data["name"]
        assert data["licence"] in text, data["name"]
    datasets = [h for h in headings if h != "Fonts"]
    words = {2: "two", 3: "three", 4: "four", 5: "five", 6: "six"}
    assert f"use {words[len(datasets)]} public datasets" in text
    assert "Creative Commons Attribution 4.0" in text  # MT-Bench: attribution required
    assert "Fonts" in headings and "Manrope" in text and "JetBrains Mono" in text
    assert "SIL Open Font License 1.1" in text


def test_example_reports_in_the_1_0_look_use_its_colours():
    """A committed report keeps its numbers, but its colours are 1.0's: the labels at the top
    in the muted colour (the faint one is too low in contrast) and the current green."""
    from judgekeeper import look

    green = re.search(r"--green-fill: #[0-9a-fA-F]{6};", look.TOKENS).group()
    reports = [p for p in (ROOT / "docs" / "examples").rglob("*.html")
               if ".meta .k" in p.read_text(encoding="utf-8")]
    assert len(reports) >= 3
    for path in reports:
        text = " ".join(path.read_text(encoding="utf-8").split())
        name = path.relative_to(ROOT).as_posix()
        assert ".meta .k { font-size: 12px; font-weight: 600; letter-spacing: .04em; " \
               "text-transform: uppercase; color: var(--muted); }" in text, name
        assert green in text, name


def test_the_examples_readme_has_one_line_per_folder():
    """docs/examples/README.md: one line per folder, and the made-up one says so."""
    examples = ROOT / "docs" / "examples"
    text = (examples / "README.md").read_text(encoding="utf-8")
    folders = sorted(p.name for p in examples.iterdir() if p.is_dir())
    lines = [line for line in text.splitlines() if line.startswith("- ")]
    assert [re.match(r"- \*\*`([\w-]+)/`\*\*", line)[1] for line in lines] == folders
    for line in lines:
        made_up = "`site-example/`" in line
        assert ("made-up" in line) is made_up, line
    assert "llmbar-haiku" not in folders


def test_the_check_reports_name_no_removed_command():
    """`judgekeeper start` is gone; the reports say what judgekeeper does."""
    for name in ("real-data-check/report.md", "coverage/coverage.md"):
        text = (ROOT / "docs" / "examples" / name).read_text(encoding="utf-8")
        assert "start's" not in text and "`start`" not in text, name
