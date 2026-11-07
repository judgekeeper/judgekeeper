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
TESTED = {"promptfoo": "Tested with promptfoo 0.123 and 0.124.",
          "DeepEval": "Tested with DeepEval 4.2.",
          "Inspect AI": "Tested with Inspect AI 0.3.273.",
          "MLflow": "Tested with MLflow 3.16"}


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
    table = _flat(tools["A CSV, TSV or JSONL file"])
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


# What a result needs, said up front -----------------------------------------------------------

NEEDS = ("A result needs at least 15 Pass and 15 Fail marks from you. It also needs 20 marks on "
         "answers your LLM-as-a-judge passed and 20 on answers it failed (or all of them, if there "
         "are fewer). If your LLM-as-a-judge fails under 10% of the answers, finding 15 answers you "
         "mark Fail can take many marks.")


def test_the_reference_says_what_a_result_needs_near_its_top():
    text = REFERENCE.read_text(encoding="utf-8")
    first_command = text.index("## judgekeeper: find, mark, measure")
    second = text.index("\n## ", first_command + 1)
    assert NEEDS in " ".join(text[:second].split())


def test_the_reference_states_the_whole_rule_for_a_result_and_the_readme_no_part_of_it():
    """judgekeeper says how many more to mark, so the README's measure step gives no count:
    half the rule would read as enough. The reference states all of it."""
    from judgekeeper import front, targets

    n, g = targets.ROUGH, targets.FIRST_GROUP
    first = (f"A result needs at least {n} Pass and {n} Fail marks from you. It also needs {g} "
             f"marks on answers your LLM-as-a-judge passed and {g} on answers it failed (or all "
             "of them, if there are fewer).")
    assert NEEDS.startswith(first + " If ")
    assert f"under {front.FEW_FAILS:.0%} of the answers" in NEEDS
    assert NEEDS in " ".join((ROOT / "docs" / "reference.md").read_text(encoding="utf-8").split())
    readme = (ROOT / "README.md").read_text(encoding="utf-8").splitlines()
    at = next(i for i, line in enumerate(readme) if line.startswith("3. **Measure:**"))
    assert not re.search(r"\d", readme[at][len("3."):]), readme[at]


def test_the_reference_says_which_marks_wait_in_the_words_check_uses():
    """After `check` takes on a new LLM-as-a-judge that graded only some answers, a later mark
    on an answer it didn't grade waits; the reference says so with the result's own words."""
    from judgekeeper import check

    text = REFERENCE.read_text(encoding="utf-8")
    section = text[text.index("## check:"):text.index("\n## ", text.index("## check:") + 1)]
    para = next(p for p in section.split("\n\n") if p.startswith("**Marks that wait.**"))
    flat = " ".join(para.split())
    wait = check.WAIT.split("your new LLM-as-a-judge ", 1)[1]  # "has no Pass or Fail grade ..."
    assert wait.rstrip(".") in flat
    assert check.WAIT_COUNT.format(run="run `judgekeeper check <new results file>`") in flat


# The marking page and the documents your LLM-as-a-judge was given --------------------------

def test_the_docs_say_the_marking_page_leaves_out_the_documents():
    """DeepEval's retrieval_context is never read, so a faithfulness check is marked with the
    documents open; elsewhere they show only when they are part of the question."""
    deepeval = _flat(_tools()["DeepEval"])
    assert ("The marking page shows the question (`input`) and the answer (`actual_output`), "
            "not the documents your LLM-as-a-judge was given (`retrieval_context`, `context`). "
            "For a faithfulness check, keep those documents open while you mark.") in deepeval
    marking = _flat(_sections()["judgekeeper: find, mark, measure"])
    assert ("It shows the question and the answer, not the documents your LLM-as-a-judge was "
            "given, unless they are part of the question (such as a promptfoo var). For a "
            "faithfulness check, keep those documents open while you mark.") in marking
    reader = ROOT / "src" / "judgekeeper" / "readers" / "deepeval.py"
    assert "retrieval" not in reader.read_text(encoding="utf-8").lower()  # never read


def test_the_reference_says_where_kappa_is_and_that_it_never_decides():
    numbers = _flat(_sections()["How the numbers are worked out"])
    assert ('so it stands apart from them: on its own line in the terminal, and under "More '
            'details" on the result page and in report.html. It never decides the result: TPR '
            "and TNR do.") in numbers
    assert "only in the report's More details" not in numbers


def test_the_reference_says_when_a_kept_mark_is_counted():
    """The kept count is only for labels that differ from the mark; the same labels again say
    "Nothing new" (labels.said)."""
    from judgekeeper.labels import Added, Plan, said

    assert said(Added(same=3), Plan(), "a.csv") == [
        "Nothing new: the labels in a.csv are already your marks."]
    assert said(Added(kept=2, same=1), Plan(), "a.csv") == [
        "Kept your earlier mark on 2 answers that a.csv labels differently."]
    again = _flat(_sections()["Bring labels you already have"])
    assert ("An answer you already marked keeps your mark, from the page or an earlier import; "
            "when a label differs from your mark, judgekeeper says how many it kept. The same "
            'labels again say "Nothing new".') in again
