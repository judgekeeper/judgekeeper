"""The front door: one message everywhere, a one-screen README, the guide that holds the rest,
a plain sentence before the numbers and a grouped help screen.

Nothing here calls a network service.
"""

from __future__ import annotations

import copy
import json
import re
import tomllib
from pathlib import Path

import pytest

from judgekeeper.cli import _parser, main
from judgekeeper.html_report import render_html
from judgekeeper.report import NOT_TRUSTWORTHY, TRUSTWORTHY, WITH_CARE, plain_summary
from tests.conftest import FIXTURES
from tests.website_pages import ROOT, WEBSITE, command_lines, judgekeeper_argv

MESSAGE = "Check your LLM-as-a-judge."
SUPPORT = "See how often it agrees with human labels, in one command."
# The term of art is in the message, so one plain sentence right after it says what it means.
EXPLAINS = ("An LLM-as-a-judge is an AI model that grades the answers of another AI model. "
            "Teams use one because reading every answer by hand is slow.")
OLD_MESSAGE = "grades the judge"
README = ROOT / "README.md"
SITE = "https://www.judgekeeper.com/"
GUIDE = ROOT / "docs" / "guide.md"
COMMANDS = ["attribute", "baseline", "check", "export", "freeze", "gate", "import",
            "import-labels", "init", "judge", "label", "migrate", "start", "template", "validate"]
LAST_HELP_LINE = "Run `judgekeeper <command> --help` for a command's options."
# Syntax lines, not commands to type: <tool>, [--flag], ..., and the stand-ins X and Y.
PLACEHOLDER = re.compile(r"<[a-z]|\[--|\.\.\.| [XY](?= |$)")


def _lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def _sections(path: Path) -> dict[str, str]:
    """`## ` heading -> the text under it, up to the next `## ` heading."""
    parts = re.split(r"^## ", path.read_text(encoding="utf-8"), flags=re.MULTILINE)
    return {part.splitlines()[0].strip(): part for part in parts[1:]}


def _code_blocks(markdown: str) -> list[str]:
    return re.findall(r"```\w*\n(.*?)```", markdown, flags=re.DOTALL)


def _slug(heading: str) -> str:
    """The anchor GitHub gives a heading."""
    text = re.sub(r"[^\w\- ]", "", heading.strip().lower())
    return text.replace(" ", "-")


def _anchors(path: Path) -> set[str]:
    in_code, found = False, set()
    for line in _lines(path):
        if line.startswith("```"):
            in_code = not in_code
        elif not in_code and line.startswith("#"):
            found.add(_slug(line.lstrip("#")))
    return found


def _check_links(path: Path) -> int:
    """Every relative link resolves to a file or folder in the repository."""
    checked = 0
    for target in re.findall(r"\]\(([^)\s]+)\)", path.read_text(encoding="utf-8")):
        if re.match(r"[a-z]+:", target):
            continue
        file_part, _, fragment = target.partition("#")
        dest = (path.parent / file_part).resolve() if file_part else path
        assert dest.exists(), f"{path.name}: {target} does not exist"
        assert ROOT in dest.parents, f"{path.name}: {target} leaves the repository"
        if fragment and dest.suffix == ".md":
            assert fragment in _anchors(dest), f"{path.name}: no heading for {target}"
        checked += 1
    return checked


# 1. The message

def test_the_readme_leads_with_the_message_and_the_supporting_line():
    lines = _lines(README)
    assert lines[0].startswith('<p align="center"><img '), "the logo comes first"
    lines = [line for line in lines[1:] if line.strip()]
    assert lines[0] == "# judgekeeper"
    first, second, third = [line for line in lines[1:] if line.strip()][:3]
    assert first == f"**{MESSAGE}**"
    assert second == SUPPORT
    assert third == EXPLAINS


def test_the_home_page_carries_the_message():
    text = (WEBSITE / "index.html").read_text(encoding="utf-8")
    # The browser tab and a search result also need the project's name.
    title = re.search(r"<title>(.*?)</title>", text, flags=re.DOTALL)[1]
    assert title == f"{MESSAGE} | judgekeeper"
    assert re.search(r"<h1>(.*?)</h1>", text, flags=re.DOTALL)[1] == MESSAGE
    lead = f'<p class="lead">{SUPPORT}</p>'
    assert lead in text
    after = text[text.index(lead) + len(lead):].lstrip()
    explains = EXPLAINS.replace("LLM-as-a-judge", "<strong>LLM-as-a-judge</strong>", 1)
    assert after.startswith(f"<p>{explains}</p>")
    description = re.search(r'<meta name="description" content="(.*?)">', text)[1]
    assert description == f"{MESSAGE[:-1]}: {SUPPORT[0].lower()}{SUPPORT[1:]}"
    assert description.count(".") == 1 and description.endswith(".")  # one sentence
    assert "Bring your own metric" not in text and "proof expires" not in text[:text.index(
        "</h1>")]
    assert 'href="own-metric.html"' in text


def test_the_package_description_carries_the_message():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert project["description"] == ("Check your LLM-as-a-judge: see how often it agrees with "
                                      "human labels.")
    # Both spellings of the term, so a search for either one finds the package.
    assert project["keywords"] == [
        "llm", "evaluation", "evals", "llm-evaluation", "llm-as-a-judge", "llm-as-judge",
        "llm-judge", "human-labels", "custom-metric", "rubric", "calibration", "drift"]
    plugin = tomllib.loads((ROOT / "packages" / "pytest-judgekeeper" / "pyproject.toml")
                           .read_text(encoding="utf-8"))["project"]
    assert plugin["keywords"] == ["pytest", "llm", "llm-as-a-judge", "llm-as-judge",
                                  "evaluation"]


def test_the_help_description_is_the_message():
    assert _parser().description == MESSAGE


def _own_words(path: Path) -> str:
    """A page's prose, on one line: without what a program printed, without the prompt (shown
    word for word) and, for the skill, without its frontmatter description."""
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".html":
        text = re.sub(r"<pre\b.*?</pre>", "", text, flags=re.DOTALL)
    else:
        text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    if path.name == "SKILL.md":
        text = text.split("---", 2)[2]
    return " ".join(text.split())


def test_no_page_carries_the_old_message_or_promises_trust():
    """judgekeeper shows how often a judge agrees with human labels; whether to rely on the
    judge is the reader's decision. The verdict phrases a report prints are not prose."""
    pages = [README, GUIDE, ROOT / "docs" / "assistant.md", ROOT / "docs" / "assistant-prompt.md",
             ROOT / "docs" / "own-metric.md", ROOT / "skills" / "judgekeeper" / "SKILL.md",
             WEBSITE / "llms.txt", *sorted(WEBSITE.glob("*.html"))]
    assert len(pages) >= 15
    for path in pages:
        whole = " ".join(path.read_text(encoding="utf-8").split())
        assert OLD_MESSAGE not in whole and "grades your app" not in whole, path.name
        prose = _own_words(path)
        for promise in ("can be trusted", "judge to trust", "is trustworthy with",
                        "you can rely on"):
            assert promise not in prose, f"{path.name}: {promise}"


def test_python_m_judgekeeper_is_the_same_entry_point():
    """The fallback the install guide gives when the `judgekeeper` command is not found."""
    import subprocess
    import sys

    proc = subprocess.run([sys.executable, "-m", "judgekeeper", "--help"], capture_output=True,
                          text=True, timeout=60, check=False)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.splitlines()[0] == MESSAGE
    assert "Start here:" in proc.stdout and "__main__" not in proc.stdout
    usage = subprocess.run([sys.executable, "-m", "judgekeeper", "no-such-command"],
                           capture_output=True, text=True, timeout=60, check=False)
    assert usage.returncode == 2


# 2. The README: one screen

def test_the_readme_is_one_screen_in_order():
    lines = _lines(README)
    assert len(lines) <= 60
    assert list(_sections(README)) == ["Install", "Use it on your own judge", "What you get",
                                       "When you need more", "Status", "Issues", "License"]
    sections = _sections(README)
    assert "\npip install judgekeeper\njudgekeeper --version\n" in sections["Install"]
    assert "inside your project's own Python environment" in sections["Install"]
    use = sections["Use it on your own judge"]
    assert "\njudgekeeper check results.csv --judge verdict --human label\n" in use
    assert "one row per answer" in use
    assert f"]({SITE}own-metric.html)" in use
    assert f"]({SITE}examples/llmbar-haiku/report.html)" in sections["What you get"]
    status = sections["Status"]
    assert "alpha" in status.lower() and "0.2.0" in status
    for link in (f"]({SITE}learn.html)", f"]({SITE}reference.html)",
                 "](https://github.com/judgekeeper/judgekeeper/blob/main/CHANGELOG.md)"):
        assert link in status, link
    assert ("This project is maintained by one person and does not accept pull requests. Bug "
            "reports and ideas are welcome as [issues](https://github.com/judgekeeper/"
            "judgekeeper/issues).") in sections["Issues"]
    assert "MIT" in sections["License"]


def test_the_readme_has_no_jargon_no_demo_and_no_link_to_the_unused_pages_address():
    text = README.read_text(encoding="utf-8")
    assert "judgekeeper.github.io" not in text
    for word in ("kappa", "tpr", "tnr"):
        assert word not in text.lower(), word
    for gone in ("demo", "examples.html", "See it work", "Skip the"):
        assert gone not in text, gone
    assert "before the first PyPI release" not in text


def test_the_readme_table_has_a_row_for_each_layer_and_for_agents():
    table = [line for line in _sections(README)["When you need more"].splitlines()
             if line.startswith("|")]
    rows = table[2:]
    assert len(rows) == 5
    for row, (command, link) in zip(rows, (
            ("judgekeeper label", "start.html#step-label"),
            ("judgekeeper init", "own-metric.html"),
            ("judgekeeper gate", "learn.html#keeps"),
            ("judgekeeper import", "learn.html#works"),
            ("skills/judgekeeper/SKILL.md", "assistant.html")), strict=True):
        assert command in row and f"]({SITE}{link})" in row, row


def _readme_links() -> list[str]:
    return re.findall(r"\]\(([^)\s]+)\)", README.read_text(encoding="utf-8"))


def test_every_link_in_the_readme_is_absolute():
    """PyPI shows this README, and a relative link does not resolve there."""
    links = _readme_links()
    assert len(links) >= 9
    for target in links:
        assert target.startswith(("https://www.judgekeeper.com/",
                                  "https://github.com/judgekeeper/judgekeeper/")), target


def test_every_website_link_in_the_readme_is_a_page_and_an_anchor_that_exist():
    site_links = [t for t in _readme_links() if t.startswith(SITE)]
    assert len(site_links) >= 8
    for target in site_links:
        page, _, fragment = target[len(SITE):].partition("#")
        page = page or "index.html"
        # The site serves website/ and, under examples/, docs/examples/ (scripts/build_pages.py).
        file = (ROOT / "docs" / page) if page.startswith("examples/") else (WEBSITE / page)
        assert file.is_file(), f"{target}: no {file.relative_to(ROOT)}"
        if fragment:
            assert f'id="{fragment}"' in file.read_text(encoding="utf-8"), target


def test_every_github_link_in_the_readme_is_a_file_in_the_repository():
    prefix = "https://github.com/judgekeeper/judgekeeper/blob/main/"
    for target in _readme_links():
        if target == "https://github.com/judgekeeper/judgekeeper/issues":
            continue
        if target.startswith("https://github.com/"):
            assert target.startswith(prefix), target
            assert (ROOT / target[len(prefix):]).is_file(), target


def test_every_command_in_the_readme_parses():
    text = README.read_text(encoding="utf-8")
    lines = [line for block in _code_blocks(text) for line in command_lines(block)]
    lines += re.findall(r"`((?:uvx )?judgekeeper [^`]+)`", text)
    found = [(line, judgekeeper_argv(line)) for line in lines]
    found = [(line, argv) for line, argv in found if argv is not None]
    assert len(found) >= 6
    for line, argv in found:
        try:
            _parser().parse_args(argv)
        except SystemExit as e:
            if e.code not in (0, None):  # 0: --version, which prints and stops
                pytest.fail(f"README: `{line}` does not parse (exit {e.code})")


# 3. The guide

def test_the_guide_has_a_heading_per_layer_then_the_rest():
    heads = list(_sections(GUIDE))
    assert heads == ["Start here", "Why", "0. The core", "1. Labels", "2. Rule and judge",
                     "3. Keep checking", "4. Your tools", "First results",
                     "Why this and not X", "The website"]
    text = GUIDE.read_text(encoding="utf-8")
    for moved in ("### I have a spreadsheet", "### I have a judge function",
                  "### I use a framework", "### Your own metric, worked through"):
        assert moved in text, moved
    sections = _sections(GUIDE)
    assert "### I have a spreadsheet" in sections["0. The core"]
    assert "### I have a judge function" in sections["2. Rule and judge"]
    assert "### Your own metric, worked through" in sections["2. Rule and judge"]
    assert "### I use a framework" in sections["4. Your tools"]


def test_layer_two_opens_with_the_own_metric_sentence():
    body = _sections(GUIDE)["2. Rule and judge"].split("\n\n")
    assert body[1] == ("**Bring your own metric. judgekeeper checks it against your labels "
                       "and tells you when that check is out of date.**")
    section = "\n\n".join(body)
    assert "JUDGE_CHANGED" in section and "ANCHORS_CHANGED" in section
    assert "judgekeeper init" in section and "](own-metric.md)" in section
    assert "metric card" not in GUIDE.read_text(encoding="utf-8").lower()


def test_what_left_the_readme_is_in_the_guide_word_for_word():
    text = GUIDE.read_text(encoding="utf-8")
    for moved in (
        ("Judges disagree with humans more than raw agreement suggests, flip verdicts "
         "between identical runs, and change silently when the provider updates the model."),
        ("Either below 0.80 is \"not trustworthy as a gate\"; 0.80 to 0.90 is \"usable with "
         "care\"."),
        "judgekeeper never guesses.",
        "with one run the noise floor is reported as unknown and `gate` returns `FLAKY`.",
        ("A judge that raises or returns nothing is recorded as an error, excluded from the "
         "metrics and counted, never scored as a fail."),
        ("Point judgekeeper at the files your eval tool already writes and add human labels. "
         "Your eval code does not change."),
        "`gate` never fails on a change inside the noise band.",
        "judgekeeper is owned by no model or platform vendor",
        "pytest --judgekeeper-report reports/my-judge/report.json",
        "python3 -m http.server --directory website 8000",
    ):
        assert moved in text, moved
    for tool in ("promptfoo", "deepeval", "inspect", "mlflow", "langfuse", "records"):
        assert f"judgekeeper import {tool}" in text, tool


def test_the_guide_links_the_published_report_and_the_file():
    core = _sections(GUIDE)["0. The core"]
    assert "https://www.judgekeeper.com/examples/llmbar-haiku/" in core
    assert "](examples/llmbar-haiku/report.html)" in core


def test_every_link_in_the_guide_resolves():
    assert _check_links(GUIDE) >= 15
    text = GUIDE.read_text(encoding="utf-8")
    assert "](docs/" not in text, "links in docs/guide.md are relative to docs/"
    for page in ("](reference.md)", "](own-metric.md)", "](integrations/)", "](../README.md)"):
        assert page in text, page


def test_every_command_in_the_guide_parses():
    found, skipped = [], []
    for block in _code_blocks(GUIDE.read_text(encoding="utf-8")):
        for line in command_lines(block):
            argv = judgekeeper_argv(line)
            if argv is None:
                continue
            typed = " ".join(["judgekeeper", *argv])  # without the shell comment
            (skipped if PLACEHOLDER.search(typed) else found).append((line, argv))
    assert len(found) >= 15
    assert [line.split()[1] for line, _ in skipped] == ["attribute"]  # X and Y stand-ins
    for line, argv in found:
        try:
            _parser().parse_args(argv)
        except SystemExit as e:
            if e.code not in (0, None):  # 0: --version, which prints and stops
                pytest.fail(f"guide: `{line}` does not parse (exit {e.code})")


def test_the_guide_is_not_a_website_page():
    assert not (WEBSITE / "guide.html").exists()


# 4. A plain sentence before the numbers

def _report(tpr, tnr, level=TRUSTWORTHY, positive="pass") -> dict:
    return {"headline": {"tpr_mean": tpr, "tnr_mean": tnr, "kappa_mean": 0.5,
                         "positive_label": positive, "n_positive": 0 if tpr is None else 50,
                         "n_negative": 0 if tnr is None else 50},
            "verdict": {"level": level, "summary": "unused", "flags": []}}


def test_plain_summary_single_output():
    assert plain_summary(_report(0.9667, 0.8571, WITH_CARE)) == (
        "Of the answers people passed, the judge passed 97%. Of the answers people failed, "
        "the judge failed 86%. It is usable with care.")


def test_plain_summary_pairwise():
    assert plain_summary(_report(0.9519, 0.8789, TRUSTWORTHY, positive="A")) == (
        "When people preferred A, the judge agreed 95% of the time. When people preferred B, "
        "88%. It is usable as a gate.")


@pytest.mark.parametrize("level,sentence", [
    (TRUSTWORTHY, "It is usable as a gate."),
    (WITH_CARE, "It is usable with care."),
    (NOT_TRUSTWORTHY, "It is not trustworthy as a gate."),
])
def test_plain_summary_says_each_verdict_level(level, sentence):
    assert plain_summary(_report(0.95, 0.95, level)).endswith(" " + sentence)
    assert plain_summary(_report(0.95, 0.95, level, positive="A")).endswith(" " + sentence)


@pytest.mark.parametrize("rate,shown", [(0.954, "95%"), (0.956, "96%"), (1.0, "100%"),
                                        (0.0, "0%"), (2 / 3, "67%")])
def test_plain_summary_rounds_to_a_whole_percent(rate, shown):
    text = plain_summary(_report(rate, rate))
    assert re.findall(r"[\d.]+\s?%", text) == [shown, shown]


def test_plain_summary_prints_no_number_for_an_unknown_rate():
    no_fail = plain_summary(_report(1.0, None, NOT_TRUSTWORTHY))
    assert no_fail == ("Of the answers people passed, the judge passed 100%. No answers that "
                       "people failed were in this set. It is not trustworthy as a gate.")
    no_pass = plain_summary(_report(None, 0.5, NOT_TRUSTWORTHY))
    assert no_pass.startswith("No answers that people passed were in this set. Of the answers "
                              "people failed, the judge failed 50%.")
    no_b = plain_summary(_report(0.9, None, NOT_TRUSTWORTHY, positive="A"))
    assert no_b.startswith("When people preferred A, the judge agreed 90% of the time. No "
                           "answers where people preferred B were in this set.")
    no_a = plain_summary(_report(None, 0.9, NOT_TRUSTWORTHY, positive="A"))
    assert no_a.startswith("No answers where people preferred A were in this set. When people "
                           "preferred B, the judge agreed 90% of the time.")
    for text in (no_fail, no_pass, no_b, no_a):
        assert len(re.findall(r"\d+", text)) == 1  # the known rate and nothing else
        assert "None" not in text and "n/a" not in text
    neither = plain_summary(_report(None, None, NOT_TRUSTWORTHY))
    assert not re.search(r"\d", neither)


def test_plain_summary_always_gives_both_rates_never_one_combined_figure():
    report = _report(0.9, 0.5)
    report["headline"]["accuracy_mean"] = 0.123
    text = plain_summary(report)
    assert "90%" in text and "50%" in text and "12" not in text
    assert "agreement" not in text and "accura" not in text


def test_plain_summary_does_not_change_the_report():
    report = _report(0.9, 0.8, WITH_CARE)
    before = copy.deepcopy(report)
    plain_summary(report)
    assert report == before


def _printed_report(capsys, out: Path) -> tuple[list[str], dict]:
    printed = capsys.readouterr().out.strip("\n").splitlines()
    return printed, json.loads((out / "report.json").read_text(encoding="utf-8"))


def _assert_plain_then_summary(printed: list[str], report: dict, out: Path) -> None:
    start = printed.index(plain_summary(report))
    assert printed[start + 1] == report["verdict"]["summary"]
    flags = [f"  - {flag['message']}" for flag in report["verdict"]["flags"]]
    assert printed[start + 2:start + 2 + len(flags)] == flags
    assert printed[start + 2 + len(flags)] == (f"wrote {out / 'report.json'} and "
                                                f"{out / 'report.html'}")


def test_check_prints_the_plain_sentence_first(tmp_path, capsys):
    out = tmp_path / "rep"
    assert main(["check", str(FIXTURES / "check" / "results.csv"), "--out", str(out)]) == 0
    printed, report = _printed_report(capsys, out)
    assert printed[0] == plain_summary(report)
    _assert_plain_then_summary(printed, report, out)
    assert len(printed) == 2 + len(report["verdict"]["flags"]) + 1


def test_validate_prints_the_plain_sentence_first(tmp_path, capsys):
    out = tmp_path / "rep"
    mig = FIXTURES / "migrate"
    assert main(["validate", str(mig / "anchors.jsonl"), str(mig / "old"),
                 "--out", str(out)]) == 0
    printed, report = _printed_report(capsys, out)
    assert printed[0] == plain_summary(report)
    _assert_plain_then_summary(printed, report, out)


def test_validate_prints_the_pairwise_sentence(pairwise_dir, tmp_path, capsys):
    out = tmp_path / "rep"
    assert main(["validate", str(pairwise_dir / "anchors.jsonl"), str(pairwise_dir / "runs"),
                 "--out", str(out)]) == 0
    printed, report = _printed_report(capsys, out)
    assert report["headline"]["positive_label"] == "A"
    assert printed[0] == plain_summary(report)
    assert printed[0].startswith(("When people preferred A", "No answers where people"))


def test_import_prints_the_plain_sentence_before_the_summary(tmp_path, capsys):
    out = tmp_path / "rep"
    assert main(["import", "promptfoo", str(FIXTURES / "promptfoo" / "results.json"),
                 "--metric", "helpfulness", "--out", str(out)]) == 0
    printed, report = _printed_report(capsys, out)
    _assert_plain_then_summary(printed, report, out)
    assert "78%" in plain_summary(report) and "67%" in plain_summary(report)  # 7/9 and 2/3


def test_the_plain_sentence_is_print_only(tmp_path, monkeypatch, capsys):
    out = tmp_path / "rep"
    assert main(["check", str(FIXTURES / "check" / "results.csv"), "--out", str(out)]) == 0
    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    sentence = plain_summary(report)
    for name in ("report.json", "report.html"):
        text = (out / name).read_text(encoding="utf-8")
        assert sentence not in text and "Of the answers people" not in text, name
    assert "Of the answers people" not in render_html(report)
    for path in (ROOT / "docs" / "examples").rglob("report.*"):
        text = path.read_text(encoding="utf-8")
        assert "Of the answers people" not in text and "When people preferred" not in text, path


# 5. The help screen

def _help(capsys, argv=("--help",)) -> str:
    capsys.readouterr()
    assert main(list(argv)) == 0
    return capsys.readouterr().out


def _help_groups(text: str) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {}
    current = None
    for line in text.splitlines():
        if line and not line.startswith(" ") and line.endswith(":"):
            current = groups.setdefault(line[:-1], [])
        elif not line.strip():
            current = None
        elif current is not None:
            current.append(line)
    return groups


def _subcommands() -> list[str]:
    (sub,) = [a for a in _parser()._actions if a.dest == "command"]
    return sorted(sub.choices)


def test_the_cli_has_the_same_fifteen_commands():
    assert _subcommands() == COMMANDS


def test_help_starts_with_the_message_and_ends_with_the_pointer(capsys):
    lines = _help(capsys).rstrip("\n").splitlines()
    assert lines[0] == MESSAGE
    assert lines[-1] == LAST_HELP_LINE
    assert lines[-2] == ""


def test_help_shows_three_commands_first(capsys):
    text = _help(capsys)
    groups = _help_groups(text)
    assert list(groups)[:2] == ["Start here", "More"]
    assert text.index("Start here:") < text.index("More:")
    assert groups["Start here"] == [
        "  start    find your judge's saved results and check them against your own labels",
        "  check    a table of judge verdicts and human labels in, a verdict out",
        "  label    no human labels yet? label answers in a local page",
    ]
    assert groups["More"] == [
        "  your own rule and judge   init, judge, validate, template, import-labels, freeze",
        "  keep checking             baseline, gate, migrate, attribute",
        "  your tools                import, export",
    ]


def test_help_lists_every_command_exactly_once(capsys):
    groups = _help_groups(_help(capsys))
    listed = [line.split()[0] for line in groups["Start here"]]
    for line in groups["More"]:
        listed += re.split(r"\s{2,}", line.strip())[-1].split(", ")
    assert len(listed) == len(set(listed)) == 15
    # Read from the parser, so a command added later without a group fails here.
    assert sorted(listed) == _subcommands()


def test_a_command_without_a_group_is_caught():
    from judgekeeper import cli

    grouped = [name for name, _ in cli.START_HERE]
    grouped += [name for _, names in cli.MORE for name in names]
    assert sorted(grouped) == sorted(cli.COMMANDS) == _subcommands()


def test_there_is_no_demo_command(capsys):
    assert main(["demo"]) == 2
    assert "invalid choice: 'demo'" in capsys.readouterr().err


def test_help_keeps_the_debug_option_and_no_arguments_prints_the_same(capsys):
    text = _help(capsys)
    assert "--debug" in text and "-h, --help" in text
    assert _help(capsys, argv=()) == text
    assert all(len(line) <= 100 for line in text.splitlines())


@pytest.mark.parametrize("command", COMMANDS)
def test_each_command_keeps_its_own_help(capsys, command):
    text = _help(capsys, argv=(command, "--help"))
    assert text.startswith(f"usage: judgekeeper {command} ")
    assert "Start here" not in text and MESSAGE not in text
