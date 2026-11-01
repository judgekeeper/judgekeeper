"""What the terminal says, screen by screen: the first run (Find, then Mark), `judgekeeper`
again before a first result, `judgekeeper mark`, nothing found, `--help` and `--stop`.

Rules for every screen: each block has its label ("Step 1 of 5: Find"); "grade", not
"verdict"; lines fit in 80 columns (prose wraps at 64, a command in backticks is never split);
the folder's name, never its whole path; other tools are ones judgekeeper "can read results
from"; one `Next:` paragraph at the end that speaks to the person.
"""

from __future__ import annotations

import pytest

from judgekeeper import __version__
from judgekeeper.cli import main
from judgekeeper.start_label import StartSession, Workspace
from tests.start_projects import deepeval_project, promptfoo_project, split, table_project

RULE = "The answer solves the customer's problem and is polite."
LONG_RULE = ("The answer must fully solve the customer's problem, be polite, short, and never "
             "promise a refund it cannot give.")
HEAD = [f"judgekeeper {__version__}", ""]


@pytest.fixture
def here(tmp_path, monkeypatch):
    project = tmp_path / "support-bot"
    project.mkdir()
    monkeypatch.chdir(project)
    return project


def screen(capsys, *argv) -> tuple[int, list[str]]:
    code = main([str(a) for a in argv])
    out, err = capsys.readouterr()
    lines = (out + err).splitlines()
    for line in lines:
        assert len(line) <= 80, line
        column = line.strip().startswith("input,") or line.endswith(" column")  # its real name
        assert "verdict" not in line.lower() or column, line
        assert "tell the person" not in line and "ask the person" not in line, line
    return code, lines


def _mark(root, n_pass: int, n_fail: int) -> None:
    session = StartSession(Workspace(root))
    for item in session.items:
        if n_pass and session.groups[item["id"]] == "pass":
            session.update({"id": item["id"], "label": "pass", "seconds": 5})
            n_pass -= 1
        elif n_fail and session.groups[item["id"]] == "fail":
            session.update({"id": item["id"], "label": "fail", "seconds": 5})
            n_fail -= 1


FIRST = [
    *HEAD,
    "Step 1 of 5: Find",
    "",
    "Eval tool:       promptfoo",
    "File:            results.json",
    "Answers:         40 answers",
    "LLM-as-a-judge:  openai:gpt-4.1-mini",
    f'Rule:            "{RULE}"',
    "judgekeeper has read from your file:",
    "  question   each test's vars",
    "  answer     each test's output",
    "  grade      your LLM-as-a-judge's Pass or Fail",
    "",
    "Your LLM-as-a-judge passed 23 answers and failed 17.",
    "Checked: your LLM-as-a-judge gave every answer a clear Pass or",
    "Fail.",
    "",
    "Step 2 of 5: Mark",
    "",
]
NEEDS = [
    "A result needs at least 15 answers you mark Pass and 15 you mark",
    "Fail, and 20 marks on answers your LLM-as-a-judge passed and 20",
    "on answers it failed (or all of them, when there are fewer).",
    "",
]
MARK_TEXT = [
    "It shows the answers",
    "one at a time. Mark each one Pass or Fail, the way you want your",
    "LLM-as-a-judge to decide. Your LLM-as-a-judge's grade stays",
    "hidden.",
]


def test_screen_1_the_first_run(here, capsys):
    promptfoo_project(here, split(23, 17), rubric=RULE)
    code, lines = screen(capsys)
    assert code == 0
    assert lines == [
        *FIRST,
        *NEEDS,
        "Opening the marking page in your browser…",
        "The marking page is open in your browser. " + MARK_TEXT[0],
        *MARK_TEXT[1:],
        "",
        "Next: mark answers until the link at the top shows your numbers,",
        "then click it.",
    ]


def test_screen_1_without_a_browser_prints_the_link(here, capsys, no_browser):
    promptfoo_project(here, split(23, 17), rubric=RULE)
    code, lines = screen(capsys, "--no-browser")
    assert code == 0
    at = lines.index("Step 2 of 5: Mark")
    assert lines[at + 2:at + 6] == NEEDS
    assert lines[at + 6] == "Open this link in your browser to mark answers:"
    assert lines[at + 7].startswith("http://127.0.0.1:") and "?token=" in lines[at + 7]
    assert lines[at + 8:at + 11] == [
        "It shows the answers one at a time. Mark each one Pass or Fail,",
        "the way you want your LLM-as-a-judge to decide. Your",
        "LLM-as-a-judge's grade stays hidden."]
    assert lines[-2:] == ["Next: mark answers until the link at the top shows your numbers,",
                          "then click it."]



def test_screen_1_a_long_rule_is_one_line_cut_short(here, capsys):
    promptfoo_project(here, split(23, 17), rubric=LONG_RULE)
    _, lines = screen(capsys)
    at = next(i for i, line in enumerate(lines) if line.startswith("Rule:"))
    assert lines[at] == 'Rule:            "The answer must fully solve the customer\'s problem, be po…"'
    assert lines[at + 1] == "                 (shortened; full rule in promptfooconfig.yaml)"


def test_screen_1_a_free_check_that_finds_a_problem(here, capsys):
    promptfoo_project(here, split(40, 0), rubric=RULE)
    _, lines = screen(capsys)
    at = next(i for i, line in enumerate(lines) if line.startswith("Checked:"))
    assert lines[at].startswith("Checked: your LLM-as-a-judge passed every answer.")


def test_screen_2_again_before_a_first_result(here, capsys):
    promptfoo_project(here, split(23, 17), rubric=RULE)
    screen(capsys)
    _mark(here, 8, 4)
    code, lines = screen(capsys)
    assert code == 0
    assert lines == [
        *HEAD,
        "Step 2 of 5: Mark",
        "",
        "You marked 12 answers so far: 8 Pass, 4 Fail.",
        "That's not enough for a result yet.",
        "A result needs at least 15 answers you mark Pass and 15 you mark",
        "Fail, and 20 marks on answers your LLM-as-a-judge passed and 20",
        "on answers it failed (or all of them, when there are fewer).",
        "",
        "The marking page is still open in your browser. The bar at the",
        "top fills as you mark.",
        "",
        "Next: mark answers until the link at the top shows your numbers,",
        "then click it.",
    ]


def test_screen_2_reopens_a_closed_page(here, capsys, pages):
    promptfoo_project(here, split(23, 17), rubric=RULE)
    screen(capsys)
    _mark(here, 8, 4)
    screen(capsys, "--stop")
    started = len(pages[0])
    code, lines = screen(capsys)
    assert code == 0 and len(pages[0]) == started + 1
    at = lines.index("The marking page is open in your browser again. The bar at the")
    assert lines[at + 1] == "top fills as you mark."


def test_screen_4_mark_more(here, capsys):
    promptfoo_project(here, split(23, 17), rubric=RULE)
    screen(capsys)
    _mark(here, 20, 17)  # a first result: 20 in the passed group, all 17 of the failed one
    code, lines = screen(capsys, "mark")
    assert code == 0
    assert lines == [
        *HEAD,
        "Step 2 of 5: Mark (more answers)",
        "",
        "You marked 37 answers so far: 20 Pass, 17 Fail.",
        "",
        "The marking page is already running. Each new mark makes your",
        "numbers more precise.",
        "Need its link? Run `judgekeeper mark --no-browser` to print it.",
        "",
        "Next: mark more answers, then run `judgekeeper` to see your",
        "updated result.",
    ]


def test_screen_4_every_answer_marked(here, capsys, pages):
    promptfoo_project(here, split(23, 17), rubric=RULE)
    screen(capsys)
    _mark(here, 23, 17)
    started = len(pages[0])
    code, lines = screen(capsys, "mark")
    assert code == 0
    assert lines == [
        *HEAD,
        "Step 2 of 5: Mark",
        "",
        "You have marked all 40 answers. There are no more to mark.",
        "",
        "Next: run your eval on more questions, then run",
        "`judgekeeper mark`: the new answers join the ones you marked.",
    ]
    assert len(pages[0]) == started  # no page to open


def test_screen_7_a_tool_with_no_results(here, capsys):
    (here / "requirements.txt").write_text("deepeval\n", encoding="utf-8")
    code, lines = screen(capsys)
    assert code == 3
    assert lines == [
        *HEAD,
        "Step 1 of 5: Find",
        "",
        "Found DeepEval in this folder (requirements.txt), but no saved",
        "results yet. DeepEval saves results only when you run deepeval",
        "test run or evaluate().",
        "",
        "Next: run your eval once from this folder, then run",
        "`judgekeeper` again.",
    ]


def test_screen_7_promptfoo_with_no_results_file(here, capsys):
    (here / "promptfooconfig.yaml").write_text("description: x\n", encoding="utf-8")
    code, lines = screen(capsys)
    assert code == 3
    assert lines == [
        *HEAD,
        "Step 1 of 5: Find",
        "",
        "Found promptfoo in this folder (promptfooconfig.yaml), but no",
        "saved results file yet. promptfoo keeps its results in its own",
        "database.",
        "",
        "Save them with `promptfoo eval -o promptfoo-results.json`, or",
        "list your evals with `promptfoo list evals` and run",
        "`promptfoo export eval <id> -o promptfoo-results.json`.",
        "",
        "Next: save your promptfoo results to a file as said above, then",
        "run `judgekeeper` again.",
    ]


def test_screen_7_nothing_found(tmp_path, capsys, monkeypatch):
    folder = tmp_path / "my-app"
    folder.mkdir()
    monkeypatch.chdir(folder)
    code, lines = screen(capsys)
    assert code == 3
    assert lines == [
        *HEAD,
        "Step 1 of 5: Find",
        "",
        "No eval results found in this folder (my-app). judgekeeper",
        "looked 4 folders down (tables: 2 folders deep).",
        "judgekeeper can read results from promptfoo, DeepEval,",
        "Inspect AI, MLflow, or a CSV, TSV or JSONL file.",
        "",
        "Next: run your eval once from this folder, then run",
        "`judgekeeper` again. If your results are somewhere else, run",
        "`judgekeeper PATH` with their file or folder.",
    ]
    assert str(tmp_path) not in "\n".join(lines)


def test_finding_no_results_names_the_files_judgekeeper_reads(tmp_path, capsys):
    from judgekeeper import start

    with pytest.raises(start.Stop):
        start.find_judge(tmp_path, talk=start.Talk())
    assert ("or a CSV, TSV or JSONL file with input, output and verdict columns."
            in " ".join(capsys.readouterr().out.split()))


def test_screen_8_help(capsys):
    assert main(["--help"]) == 0
    out = capsys.readouterr().out
    lines = out.splitlines()
    assert lines[:24] == [
        "Check your LLM-as-a-judge in 5 steps.",
        "",
        "  1. Find      judgekeeper          finds your eval results and the",
        "                                    LLM-as-a-judge that graded them",
        "  2. Mark      in your browser      you mark answers Pass or Fail",
        "  3. Measure   judgekeeper          shows how often your LLM-as-a-judge agrees",
        "                                    with you, and where it goes wrong",
        "  4. Fix       judgekeeper fix      if your LLM-as-a-judge needs work, change",
        "                                    its rule, grade your marked answers again,",
        "                                    and test the new rule on the half of your",
        "                                    marks kept aside",
        "  5. Re-check  judgekeeper check    after you change your LLM-as-a-judge, grade",
        "                                    your marked answers again",
        "                                    (.judgekeeper/fix/marked-answers.csv) and",
        "                                    see if it still agrees with you",
        "",
        "judgekeeper can read results from promptfoo, DeepEval, Inspect AI,",
        "MLflow, or a CSV, TSV or JSONL file with these columns:",
        "  input, output, verdict",
        "",
        "usage: judgekeeper [PATH] [options]",
        "",
        "Commands:",
        "  mark    mark more answers",
    ]
    assert lines[24:28] == [
        "  fix     see where your LLM-as-a-judge goes wrong; with the results of grading",
        "          your marked answers again, test a better rule on the marks kept aside",
        "  check   re-check your LLM-as-a-judge on your marks after a change",
        "",
    ]
    assert "Options:" in lines
    for gone in ("--fast", "--hook", "--on", "--off", "Turn on", "coding agent"):
        assert gone not in out, gone
    assert max(len(line) for line in lines) <= 80


def test_screen_9_stop(here, capsys):
    promptfoo_project(here, split(23, 17), rubric=RULE)
    screen(capsys)
    _mark(here, 2, 1)
    code, lines = screen(capsys, "--stop")
    assert code == 0
    assert lines == [
        *HEAD,
        "Closed the marking page. Your marks are saved.",
        "",
        "Next: run `judgekeeper` when you want to continue.",
    ]


def test_screen_9_with_no_page_open(here, capsys):
    promptfoo_project(here, split(23, 17), rubric=RULE)
    code, lines = screen(capsys, "--stop")
    assert code == 0
    assert lines == [*HEAD, "No marking page is open.", "",
                     "Next: run `judgekeeper` when you want to continue."]


def test_the_result_is_step_3_and_speaks_to_the_person(here, capsys):
    promptfoo_project(here, split(23, 17), rubric=RULE)
    screen(capsys)
    _mark(here, 20, 17)
    code, lines = screen(capsys)
    assert code == 0
    assert lines[2:4] == ["Step 3 of 5: Measure", ""]
    assert ("The marking page is still open. Mark more answers to make these ranges narrower, "
            "so the numbers are more certain.") in " ".join(lines)
    assert lines[-2:] == ["Next: nothing to do. When you change your LLM-as-a-judge or",
                          "update your eval tool, run `judgekeeper check`."]


def test_a_switch_to_another_eval_tool_gives_no_check_verdict(here, capsys):
    """Marks made on promptfoo's results, then only DeepEval's results: `check` can't compare
    judges across two eval tools, so it says so and gives no verdict."""
    promptfoo_project(here, split(23, 17), rubric=RULE)
    screen(capsys)
    _mark(here, 15, 15)
    screen(capsys, "--stop")
    (here / "results.json").unlink()
    (here / "promptfooconfig.yaml").unlink()
    deepeval_project(here, split(25, 25))
    code, lines = screen(capsys, "check")
    assert code == 3
    assert lines[2:] == [
        "Step 5 of 5: Re-check",
        "",
        "Your results now come from DeepEval, not promptfoo.",
        "judgekeeper can't compare LLM-as-a-judge results across two eval tools.",
        "",
        "Next: run `judgekeeper` to start fresh with DeepEval.",
    ]
    for word in ("Worse", "No big drop", "Agreed with you"):
        assert word not in "\n".join(lines), word


def test_old_marks_from_another_tool_give_no_mixed_result(here, capsys):
    """Marks made on promptfoo's results, then DeepEval's results: plain `judgekeeper` says the
    marks are for other results and asks before starting over; it shows no result."""
    promptfoo_project(here, split(23, 17), rubric=RULE)
    screen(capsys)
    _mark(here, 15, 15)
    screen(capsys, "--stop")
    (here / "results.json").unlink()
    (here / "promptfooconfig.yaml").unlink()
    deepeval_project(here, split(25, 25))
    code, lines = screen(capsys)
    text = "\n".join(lines)
    assert code == 3
    assert "Your marks are for other results" in " ".join(text.split())
    assert "Start over with these results?" in text
    for word in ("Step 3 of 5", "your LLM-as-a-judge also passed", "Of the answers you passed"):
        assert word not in text, word


def test_wrapping_keeps_commands_whole_and_never_starts_a_line_with_next():
    from judgekeeper.textio import wrap

    text = "Next: " + "word " * 10 + "`judgekeeper mark --tool promptfoo --metric x`" + " end"
    lines = wrap(text)
    assert all(len(line) <= 64 for line in lines if "`" not in line)
    assert any(line.startswith("`judgekeeper mark --tool promptfoo --metric x`")
               for line in lines)
    fake = wrap("Your LLM-as-a-judge: " + "x " * 26 + "Next: run `other`.")
    assert not [line for line in fake if line.startswith("Next:")]
    for n in range(20, 34):
        lines = wrap("a " * n + "Inspect AI, MLflow")
        assert not [line for line in lines if line.endswith("Inspect")], lines


def test_too_few_answers_says_so_without_a_target_number(here, capsys):
    """No target numbers on screen: the page shows how far the marks are."""
    promptfoo_project(here, split(4, 3), rubric=RULE)
    code, lines = screen(capsys)
    assert code == 3
    text = " ".join(" ".join(lines).split())
    assert ("You have 7 answers with a clear grade. That is not enough answers for a first "
            "result.") in text
    assert "15" not in text


@pytest.mark.parametrize("name, kind", [("results.csv", "CSV"), ("graded.jsonl", "JSONL")])
def test_a_table_is_named_by_its_file_kind(here, capsys, name, kind):
    if kind == "CSV":
        table_project(here, split(15, 15), name=name)
    else:
        import json

        rows = [{"input": f"Q{i}", "output": f"A{i}", "verdict": "pass" if v else "fail"}
                for i, v in enumerate(split(15, 15))]
        (here / name).write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    _, lines = screen(capsys)
    assert f"Eval tool:       your own {kind} file" in lines
