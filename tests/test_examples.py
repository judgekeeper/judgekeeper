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
    assert not _unranged(README.read_text(encoding="utf-8"))


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
            "ragtruth": "c103204b9ce28d6bbad859304bf30de72b8ed8fe",
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
    sample = json.loads((ROOT / "docs/examples/ragtruth/sample-ids.json").read_text(
        encoding="utf-8"))
    assert sample["commit"] == DATASETS["ragtruth"] and sample["filter"]


def test_the_datasets_licenses_and_citations_are_in_the_notices():
    text = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    for needed in ("Copyright (c) 2023 JailbreakBench Team", "Copyright (c) 2023 Particle Media",
                   "NeurIPS 2024 Datasets and Benchmarks Track", "ACL 2024",
                   "https://github.com/JailbreakBench/jailbreakbench",
                   "https://github.com/ParticleMedia/RAGTruth", *DATASETS.values()):
        assert needed in text, needed
    assert text.count("Permission is hereby granted, free of charge") == 2
    for folder in ("jailbreakbench", "ragtruth"):
        loader = (ROOT / "docs" / "examples" / folder / "load.py").read_text(encoding="utf-8")
        assert DATASETS[folder] in loader and "print(NOTICE)" in loader, folder


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
