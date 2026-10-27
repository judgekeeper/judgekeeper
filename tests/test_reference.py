"""docs/reference.md documents the 1.0 commands only: `judgekeeper`, `mark`, `fix` and
`check`. Each command's flags come from its own --help (one source: the table says what the
help says), then the exit codes, the files in .judgekeeper/, the table format, record() and the
keys. What is read from each eval tool, with its traps, is in docs/eval-tools.md. The site links
the code prints point at ids the pages have.
"""

from __future__ import annotations

import re

import pytest

from judgekeeper.cli import REMOVED, _front_parser, _parser
from tests.start_projects import promptfoo_project, split
from tests.test_front import run
from tests.website_pages import ROOT, WEBSITE, parse

REFERENCE = ROOT / "docs" / "reference.md"
EVAL_TOOLS = ROOT / "docs" / "eval-tools.md"
COMMANDS = {None: "judgekeeper: find, mark, measure",
            "mark": "mark: mark more answers",
            "fix": "fix: see where your LLM-as-a-judge goes wrong, then test a better rule",
            "check": "check: re-check your LLM-as-a-judge after a change"}
GONE_FLAGS = ("--review", "--fix", "--ask-again", "--try-new-judge", "--label-more",
              "--test-pass-mark", "--rule-file", "--times", "--allow-calls", "--python",
              "--judge-command", "--agent-prompt", "--fields")
# The code prints a link to this heading's id, so its words stay.
RECORD_HEADING = "record(): save your own LLM-as-a-judge's verdicts with one line"


def _text() -> str:
    return REFERENCE.read_text(encoding="utf-8")


def _flat(text: str) -> str:
    return " ".join(text.split())


def _sections() -> dict[str, str]:
    parts = re.split(r"^## ", _text(), flags=re.MULTILINE)
    return {part.splitlines()[0].strip(): part for part in parts[1:]}


def _parser_of(command: str | None):
    if command is None:
        return _front_parser()
    (sub,) = [a for a in _parser()._actions if a.dest == "command"]
    return sub.choices[command]


def _options(command: str | None) -> dict[str, str]:
    """Each option --help shows (PATH and the long flags), with its help text."""
    found = {}
    for action in _parser_of(command)._actions:
        if action.help in (None, "==SUPPRESS==") or "--help" in action.option_strings:
            continue
        name = action.metavar if not action.option_strings else next(
            s for s in action.option_strings if s.startswith("--"))
        found[name] = action.help
    return found


def _rows(section: str) -> dict[str, str]:
    """The flag table: its first cell's first word (backticks off) and the second cell."""
    rows = {}
    for line in section.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if line.startswith("| `") and len(cells) == 2:
            rows[cells[0].strip("`").split()[0]] = cells[1].replace("`", "")
    return rows


def _usage_flags(section: str) -> set[str]:
    usage = section[section.index("```\n") + 4:section.index("\n```", section.index("```\n"))]
    return {w for w in re.findall(r"--[a-z-]+|PATH", usage)}


def test_the_reference_has_a_section_for_each_command_and_no_other():
    sections = _sections()
    heads = re.findall(r"^#{2,3} (.+)$", _text(), flags=re.MULTILINE)
    assert len(heads) == len(set(heads))
    commands = [h for h in sections if re.match(r"(judgekeeper|[a-z]+): ", h)]
    assert commands == list(COMMANDS.values())
    text = _text()
    for name in ("start", *REMOVED):
        assert not re.search(rf"judgekeeper {name}\b", text), name
    for flag in GONE_FLAGS:
        assert not re.search(rf"{flag}(?![\w-])", text), flag


@pytest.mark.parametrize("command", [None, "fix", "check"], ids=["judgekeeper", "fix", "check"])
def test_each_flag_table_says_what_the_commands_help_says(command):
    section = _sections()[COMMANDS[command]]
    options, rows = _options(command), _rows(section)
    assert set(rows) == set(options)
    for name, help_text in options.items():
        said = help_text[0].upper() + help_text[1:]
        assert rows[name] == said or re.match(rf"{re.escape(said)}[.:;] ", rows[name]), name
    assert _usage_flags(section) == set(options)


def test_mark_has_the_flags_of_judgekeeper_and_says_so():
    section = _sections()[COMMANDS["mark"]]
    front, mark = _options(None), _options("mark")
    assert {k: v for k, v in front.items() if k not in ("--version", "--debug")} == mark
    assert "the same flags as `judgekeeper`" in _flat(section)
    assert _usage_flags(section) == set(mark)


def test_the_exit_codes_are_the_ones_the_commands_use():
    section = _sections()["Exit codes"]
    codes = re.findall(r"^\| (\d+) \|", section, flags=re.MULTILINE)
    assert codes == ["0", "1", "2", "3", "130"]
    one = next(line for line in section.splitlines() if line.startswith("| 1 |"))
    assert "`check`" in one and "Worse" in one
    from judgekeeper import check, cli, fix, front

    assert (cli.EXIT_OK, check.EXIT_WORSE, cli.EXIT_USAGE, front.EXIT_NEEDS_YOU,
            cli.EXIT_STOPPED) == (0, 1, 2, 3, 130)
    assert fix.EXIT_NEEDS_YOU == 3


FILES = (".gitignore", "judge.json", "judge-check.json", "judge-check.csv", "start.json",
         "pool.jsonl", "pool-judge.jsonl", "marks.jsonl", "server.json", "page.json",
         "results-seen.json", "result.json", "report.html", "history.jsonl", "anchors.jsonl",
         "anchors.manifest.json", "fix/split.json", "fix/mistakes.md", "fix/marked-answers.csv",
         "rules/", "verdicts/", "previous-<date>/")


def _files_section() -> str:
    return _sections()["The .judgekeeper/ folder"]


def test_files_table_and_history():
    section = _files_section()
    for name in FILES:
        assert f"`{name}`" in section, name
    history = next(line for line in section.splitlines() if line.startswith("| `history.jsonl`"))
    assert "no answer text" in history


def test_every_file_a_real_run_writes_is_in_the_files_table(tmp_path, monkeypatch, capsys,
                                                            pages):
    from judgekeeper import start_label
    from tests.test_loop import _click

    monkeypatch.chdir(tmp_path)
    promptfoo_project(tmp_path, split(40, 30))
    run(capsys)
    _click(start_label.Workspace(tmp_path))
    for argv in ((), ("fix",), ("check",)):
        run(capsys, *argv)
    section = _files_section()
    folder = tmp_path / ".judgekeeper"
    written = [p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file()]
    assert len(written) > 10
    for name in written:
        shown = name if "/" not in name else name.split("/")[0] + "/"
        assert f"`{name}`" in section or f"`{shown}`" in section, name


TRAPS = {"promptfoo": ("A human rating overrides the row's `success` and `pass`.",
                       "`--repeat` rows carry no repeat index.",
                       "The default grader is not recorded."),
         "DeepEval": ("Default test case names are positional.",
                      "`DEEPEVAL_LOCAL_STORE=sqlite`"),
         "Inspect AI": ("`P` (partial credit) has no default", "`--no-log-samples`"),
         "MLflow": ("Trace ids change every run.", "A copied `mlruns/` folder.",
                    "MLflow's own problems, not judgekeeper's.")}
TESTED = {"promptfoo": "Tested with promptfoo 0.123 and 0.124, the versions in tests/fixtures.",
          "DeepEval": "Tested with DeepEval 4.2, the version in tests/fixtures.",
          "Inspect AI": "Tested with Inspect AI 0.3.273, the version in tests/fixtures.",
          "MLflow": "Tested with MLflow 3.16, the version in tests/fixtures"}


def _tools() -> dict[str, str]:
    """docs/eval-tools.md, one section per eval tool."""
    parts = re.split(r"^## ", EVAL_TOOLS.read_text(encoding="utf-8"), flags=re.MULTILINE)
    return {part.splitlines()[0].strip(): part for part in parts[1:]}


@pytest.mark.parametrize("tool", sorted(TRAPS))
def test_each_tool_has_its_traps_and_tested_versions(tool):
    section = _tools()[tool]
    assert "**Traps.**" in section
    flat = _flat(section)
    for trap in TRAPS[tool]:
        assert trap in flat, trap
    assert TESTED[tool] in flat


def test_the_table_format_and_record_are_described():
    tools = _tools()
    table = _flat(tools["A CSV or JSONL file"])
    for needed in ("`input`, `output` and `verdict`", "`judge_verdict`", "`judge`",
                   "`judge_model`", "the columns it read"):
        assert needed in table, needed
    assert "judgekeeper.record()" in tools
    sections = _sections()
    assert "Records format" in sections
    assert RECORD_HEADING in sections


def test_no_key_is_needed_and_none_is_ever_written():
    flat = _flat(_sections()["Your API keys"])
    for needed in ("judgekeeper makes no AI call and needs no API key",
                   "It never runs your eval tool or your project's code",
                   "judgekeeper never prints a key or writes one to a file",
                   "There is no flag that takes a key"):
        assert needed in flat, needed
    for gone in ("Before any AI call", "asks first", "--yes"):
        assert gone not in flat, gone


def test_the_reference_keeps_to_the_agreed_words():
    """Outside code: "grade", never "verdict" (a column name keeps it, in backticks); no
    "luck" or "chance"; "can read results from", never "works with"."""
    text = re.sub(r"```.*?```", "", _text().replace(RECORD_HEADING, ""), flags=re.DOTALL)
    text = re.sub(r"\]\(#[\w-]+\)", "]", text)  # links to the heading's id
    text = re.sub(r"`[^`]*`", "", text)
    for word in (r"verdicts?", r"luck(y)?", r"chance", r"works with", r"integrates? with",
                 r"rough(ly)?", r"AI judges?", r"trusted", r"proven"):
        assert not re.search(rf"\b{word}\b", text, re.IGNORECASE), word
    assert "can read results from" in text


def _ids(page: str) -> set[str]:
    return {el.attrs["id"] for el in parse(WEBSITE / page).iter() if "id" in el.attrs}


def test_every_site_link_the_code_prints_points_at_an_id_a_page_has():
    """Each judgekeeper.com/<page>#<id> in src/. The Guide (start.html) must keep its ids when
    the pages are rewritten: own-format (which shows the record() line) and install today."""
    links = set()
    for path in (ROOT / "src" / "judgekeeper").rglob("*.py"):
        links |= set(re.findall(r"judgekeeper\.com/([\w-]+\.html#[\w-]+)",
                                path.read_text(encoding="utf-8")))
    assert {"start.html#own-format", "start.html#install"} <= links
    for link in sorted(links):
        page, wanted = link.split("#")
        assert wanted in _ids(page), link
