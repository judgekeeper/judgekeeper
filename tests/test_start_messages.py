"""What `judgekeeper start` says, checked against what new users ran into: a judge that fails
few answers, hints that must work as printed, `--no-browser` and No, the exit code for
"stopped at a question", resuming, the judge's rule cut short, choosing a judge, and
`--ask-again` before any labels.

The person's labels decide Correct and Wrong; the judge's fails only decide how the answers
are picked. So a judge that passes nearly everything goes on to labeling, with a note.
"""

from __future__ import annotations

import builtins
import json
import re
import sys
import types

import pytest

from judgekeeper import start, start_label
from judgekeeper.cli import _parser, main
from judgekeeper.textio import split_command
from tests.start_projects import (
    deepeval_project,
    inspect_data,
    inspect_project,
    promptfoo_data,
    promptfoo_project,
    records_project,
    split,
    table_project,
)

QUESTION = start.EXIT_QUESTION


@pytest.fixture(autouse=True)
def no_labeling(monkeypatch):
    """Labeling is replaced: the runs it would have started are kept, with their flags."""
    calls = []

    def run_labeling(found, port, open_browser, say, command="judgekeeper start"):
        calls.append({"found": found, "port": port, "open_browser": open_browser})
        say("(labeling page)")
        return 0

    def serve(ws, port, open_browser, say, command="judgekeeper start"):
        calls.append({"ws": ws, "port": port, "open_browser": open_browser})
        say("(labeling page)")
        return 0

    monkeypatch.setattr(start_label, "run_labeling", run_labeling)
    monkeypatch.setattr(start_label, "serve_workspace", serve)
    return calls


@pytest.fixture
def terminal(monkeypatch):
    """A person at a terminal: answers come from the list the test fills in, then Enter."""
    answers: list[str] = []
    monkeypatch.setattr(start, "_interactive", lambda: True)

    def fake_input(prompt=""):
        print(prompt)
        return answers.pop(0) if answers else ""

    monkeypatch.setattr(builtins, "input", fake_input)
    return answers


def run(capsys, *argv):
    code = main(["start", *map(str, argv)])
    out, err = capsys.readouterr()
    return code, out, err


# 1. A judge that fails few answers -------------------------------------------------------

def test_two_fails_in_sixty_go_on_to_labeling_with_an_honest_note(tmp_path, capsys,
                                                                   no_labeling):
    promptfoo_project(tmp_path, split(58, 2))
    code, out, _ = run(capsys, tmp_path, "--yes")
    assert code == 0 and no_labeling
    assert ("Your judge failed only 2 of 60 answers. That may mean it passes too much: your "
            "labels will show it.") in out
    assert "You'll see all 2 it failed among the first 10, then answers it passed." in out
    for wrong in ("too few", "Make more answers", "half from", "may not reach",
                  "Labeling anyway"):
        assert wrong not in out, wrong


def test_one_fail_in_fifty(tmp_path, capsys):
    deepeval_project(tmp_path, split(49, 1))
    code, out, _ = run(capsys, tmp_path, "--yes")
    assert code == 0
    assert "Your judge failed only 1 of 50 answers." in out
    assert "You'll see the one it failed among the first 10, then answers it passed." in out
    assert "deepeval test run" not in out  # no "more of the same answers"


def test_seven_fails_come_within_the_first_twenty(tmp_path, capsys):
    promptfoo_project(tmp_path, split(53, 7))
    _, out, _ = run(capsys, tmp_path, "--yes")
    assert "Your judge failed only 7 of 60 answers." in out
    assert "You'll see all 7 it failed among the first 20, then answers it passed." in out


def test_no_fails_at_all(tmp_path, capsys, no_labeling):
    promptfoo_project(tmp_path, split(40, 0))
    code, out, _ = run(capsys, tmp_path, "--yes")
    assert code == 0 and no_labeling
    assert ("Your judge failed none of your 40 answers. That may mean it passes too much: "
            "your labels will show it.") in out
    assert "You'll see only answers it passed." in out


def test_few_passes_is_the_same_the_other_way_round(tmp_path, capsys):
    promptfoo_project(tmp_path, split(3, 40))
    _, out, _ = run(capsys, tmp_path, "--yes")
    assert ("Your judge passed only 3 of 43 answers. That may mean it fails too much: your "
            "labels will show it.") in out
    assert "You'll see all 3 it passed among the first 10, then answers it failed." in out


def test_the_picking_line_matches_the_queue():
    """The note's "among the first N" is what build_queue really does."""
    for n_fail in (1, 2, 5, 6, 7, 14):
        answers = [start.Answer(str(i), "q", "a", "fail" if i < n_fail else "pass", "", None,
                                None, "x") for i in range(60)]
        queue = start_label.build_queue(answers, seed=7)
        last_fail = max(i for i, q in enumerate(queue) if q["group"] == "fail")
        line = start.picking_line(60 - n_fail, n_fail)
        shown = int(re.search(r"among the first (\d+)", line)[1])
        assert last_fail < shown <= last_fail + 10


def test_the_targets_are_about_your_labels(tmp_path, capsys):
    promptfoo_project(tmp_path, split(40, 20))
    _, out, _ = run(capsys, tmp_path, "--yes")
    assert "  A rough check needs 15 you mark Correct and 15 you mark Wrong." in out
    assert "  A reliable result needs 25 you mark Correct and 25 you mark Wrong." in out
    assert "judgekeeper picks half from the judge's" in out  # both groups are big enough


def test_a_reliable_result_out_of_reach_is_said(tmp_path, capsys):
    promptfoo_project(tmp_path, split(25, 15))
    _, out, _ = run(capsys, tmp_path, "--yes")
    assert ("  A reliable result needs 25 you mark Correct and 25 you mark Wrong: that takes "
            "50 answers, and you have 40.") in out
    assert "  A rough check needs 15 you mark Correct and 15 you mark Wrong." in out


def test_too_few_answers_says_the_real_count(tmp_path, capsys, terminal):
    promptfoo_project(tmp_path, split(20, 2))
    code, out, _ = run(capsys, tmp_path)
    assert code == 0
    assert "You have 22 answers; a rough check needs at least 30." in out
    assert "with some the judge failed" not in out and "too few for a result" not in out
    assert "Make more answers with your own eval, then run judgekeeper start" in out
    assert "Label the 22 you have anyway? The result will say how unsure it is. [y/N]" in out


def test_too_few_with_yes_says_one_line_and_goes_on(tmp_path, capsys, no_labeling):
    promptfoo_project(tmp_path, split(20, 2))
    code, out, _ = run(capsys, tmp_path, "--yes")
    assert code == 0 and no_labeling
    assert out.count("a rough check needs at least 30") == 1
    assert "Labeling anyway, as you asked (--yes)." in out
    assert "Make more answers" not in out and "Label the 22" not in out
    assert ("  A rough check needs 15 you mark Correct and 15 you mark Wrong: that takes 30 "
            "answers, and you have 22.") in out


COSTS = "  Running your eval again makes model calls, so it costs money."


@pytest.mark.parametrize("make, lines", [
    (lambda root: promptfoo_project(root, split(10, 5)),
     ["  Add more tests to promptfooconfig.yaml, then run: promptfoo eval -o results.json",
      COSTS]),
    (lambda root: deepeval_project(root, split(10, 5)),
     ["  Add more test cases to test_support.py, then run: deepeval test run test_support.py",
      COSTS]),
    (lambda root: inspect_project(root, split(10, 5)),
     [("  Add more samples to the dataset in support_task.py, then run: inspect eval "
       "support_task.py --model openai/gpt-4.1 --model-role grader=anthropic/claude-haiku-4-5"),
      COSTS]),
    (lambda root: table_project(root, split(10, 5)),
     ["  Add more rows to results.csv."]),
])
def test_more_answers_names_the_real_files(tmp_path, capsys, monkeypatch, make, lines):
    monkeypatch.chdir(tmp_path)  # the commands run in the project folder
    make(tmp_path)
    code, out, _ = run(capsys)
    assert code == QUESTION  # no terminal to ask in
    shown = out.splitlines()
    first = shown.index(lines[0])
    assert shown[first:first + len(lines)] == lines
    assert "your_task.py" not in out and "--limit" not in out


def test_inspect_in_another_log_folder_names_it(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    inspect_project(tmp_path, split(10, 5), name="evals/runs/2026-10-02_support.json")
    found = start.find_judge("evals/runs/2026-10-02_support.json")
    assert start.more_answers(found)[0].endswith(" --log-dir evals/runs")


def test_inspect_without_a_task_file_prints_no_placeholder(tmp_path):
    data = inspect_data(split(10, 5))
    del data["eval"]["task_file"]
    path = tmp_path / "logs" / "2026-10-02_support.json"
    path.parent.mkdir()
    path.write_text(json.dumps(data), encoding="utf-8")
    lines = start.more_answers(start.find_judge(tmp_path))
    assert lines[0] == "  Add more samples to your Inspect task's dataset, then run it again."
    assert not any("your_task" in line or "--limit" in line for line in lines)


def test_an_eval_log_is_read_with_inspect_for_its_task_file(tmp_path, monkeypatch):
    """A .eval log is a zip archive Inspect compresses its own way: its header is read with
    inspect_ai, as the log itself is."""
    header = inspect_data(split(1, 0))["eval"]
    header["task_file"] = "quiz.py"

    class Log:
        eval = types.SimpleNamespace(model_dump=lambda mode="json": header)

    seen = []

    def read_eval_log(path, header_only=False):
        seen.append(header_only)
        return Log()

    log = types.ModuleType("inspect_ai.log")
    log.read_eval_log = read_eval_log
    monkeypatch.setitem(sys.modules, "inspect_ai", types.ModuleType("inspect_ai"))
    monkeypatch.setitem(sys.modules, "inspect_ai.log", log)
    path = tmp_path / "logs" / "2026-10-06_quiz.eval"
    path.parent.mkdir()
    path.write_bytes(b"PK\x03\x04")
    from judgekeeper.readers.inspect_logs import eval_header

    assert eval_header(path)["task_file"] == "quiz.py"
    assert seen == [True]


# 2. Hints repeat the flags you gave ------------------------------------------------------

HINT = re.compile(r"Run (judgekeeper start\b.*?) (?:to|when) ")


def follow(capsys, out: str, question: str):
    """Run the first printed hint as printed: it must not stop at the same question."""
    command = HINT.search(out)[1]
    code, again, _ = run(capsys, *split_command(command)[2:])
    assert question not in again, command
    return code, again, command


def _labels_need_a_map(root):
    table_project(root, ["good"] * 20 + ["bad"] * 12)


def test_the_open_hint_keeps_a_label_map_and_no_browser(tmp_path, capsys, monkeypatch,
                                                        no_labeling):
    monkeypatch.chdir(tmp_path)
    _labels_need_a_map(tmp_path / "proj")
    code, out, _ = run(capsys, "proj", "--label-map", "good=pass,bad=fail", "--no-browser")
    assert code == QUESTION
    assert ("Start the labeling page? Run judgekeeper start proj --label-map good=pass,bad=fail "
            "--no-browser --yes to start it (it prints a link).") in out
    code, _, _ = follow(capsys, out, "Start the labeling page?")
    assert code == 0
    assert no_labeling[-1]["open_browser"] is False


def test_the_open_hint_keeps_the_judge_you_chose(tmp_path, capsys, monkeypatch, no_labeling):
    monkeypatch.chdir(tmp_path)
    data = promptfoo_data(split(20, 12), metric="helpfulness")
    for i, row in enumerate(data["results"]["results"]):
        other = json.loads(json.dumps(row["gradingResult"]["componentResults"][0]))
        other["assertion"] = {"type": "llm-rubric", "value": "Has a calm tone.", "metric": "tone"}
        other["pass"] = i % 2 == 0
        row["gradingResult"]["componentResults"].append(other)
    (tmp_path / "results.json").write_text(json.dumps(data), encoding="utf-8")
    code, out, _ = run(capsys, "--metric", "tone")
    assert code == QUESTION
    assert "Open the labeling page? Run judgekeeper start --metric tone --yes to open it." in out
    code, again, _ = follow(capsys, out, "Open the labeling page?")
    assert code == 0 and "Several judges" not in again
    assert no_labeling[-1]["found"].metric == "tone"


def test_the_too_few_hint_keeps_your_flags(tmp_path, capsys, monkeypatch, no_labeling):
    monkeypatch.chdir(tmp_path)
    table_project(tmp_path / "proj", ["good"] * 20 + ["bad"] * 2)
    code, out, _ = run(capsys, "proj", "--label-map", "good=pass,bad=fail", "--port", "8999")
    assert code == QUESTION
    assert ("Label the 22 you have anyway? Run judgekeeper start proj --label-map "
            "good=pass,bad=fail --port 8999 --yes to say yes.") in out
    code, _, _ = follow(capsys, out, "Label the 22 you have anyway?")
    assert code == 0
    assert no_labeling[-1]["port"] == 8999


def test_the_continue_hint_keeps_your_flags(tmp_path, capsys, monkeypatch, no_labeling):
    monkeypatch.chdir(tmp_path)
    promptfoo_project(tmp_path / "proj", split(20, 12))
    start_label.prepare(start.find_judge(tmp_path / "proj"), say=lambda line="": None)
    code, out, _ = run(capsys, "proj", "--no-browser")
    assert code == QUESTION
    assert ("Continue labeling? Run judgekeeper start proj --no-browser --yes to continue, or "
            "judgekeeper start proj --no-browser --new to start over.") in out
    code, _, _ = follow(capsys, out, "Continue labeling?")
    assert code == 0
    assert no_labeling[-1]["ws"].root == (tmp_path / "proj").resolve()


def test_every_start_option_is_repeated_or_left_out_on_purpose():
    """A new flag must be added to start.REPEATED (or to the flags each hint adds itself)."""
    sub = next(a for a in _parser()._actions if a.dest == "command")
    options = {a.dest for a in sub.choices["start"]._actions if a.option_strings}
    options -= {"help", "debug"}
    repeated = {dest for dest, _ in start.REPEATED} | {"port", "no_browser"}
    assert options == repeated | start.NOT_REPEATED
    assert not repeated & start.NOT_REPEATED


def test_the_command_puts_the_path_first_and_quotes_what_needs_it():
    flags = start.repeated_flags("my results", metric="safe wording", port=8765,
                                 no_browser=True)
    talk = start.Talk(flags=flags)
    shown = talk.command("--yes")
    assert shown.startswith("judgekeeper start ")
    assert split_command(shown) == ["judgekeeper", "start", "my results", "--metric",
                                    "safe wording", "--no-browser", "--yes"]
    assert start.Talk().command() == "judgekeeper start"


# 3. --no-browser and saying No -----------------------------------------------------------

def test_no_browser_asks_to_start_the_page(tmp_path, capsys, terminal, monkeypatch):
    monkeypatch.chdir(tmp_path)
    promptfoo_project(tmp_path, split(20, 12))
    terminal.append("n")
    code, out, _ = run(capsys, "--no-browser")
    assert code == 0
    assert "Start the labeling page? It will print a link. [Y/n]" in out
    assert "Open the labeling page" not in out
    assert out.rstrip().splitlines()[-1] == ("OK. Run judgekeeper start --no-browser when "
                                             "you're ready to label.")


def test_no_at_a_terminal_says_how_to_come_back(tmp_path, capsys, terminal, monkeypatch):
    monkeypatch.chdir(tmp_path)
    promptfoo_project(tmp_path, split(20, 12))
    terminal.append("n")
    code, out, _ = run(capsys)
    assert code == 0
    assert "Open the labeling page now? [Y/n]" in out
    assert out.rstrip().splitlines()[-1] == "OK. Run judgekeeper start when you're ready to label."
    assert not (tmp_path / ".judgekeeper").exists()


# 4. The exit code for "stopped at a question" --------------------------------------------

def test_the_question_code_is_new():
    from judgekeeper import cli, gate

    used = {cli.EXIT_OK, cli.EXIT_FAILURE, cli.EXIT_USAGE, cli.EXIT_HASH_MISMATCH,
            *gate.EXIT_CODES.values(), 6, 7, 130}  # 6 and 7: attribute
    assert QUESTION not in used
    assert f"{QUESTION} when it stopped at a question" in cli.__doc__


def test_the_reference_lists_the_question_code():
    from tests.website_pages import ROOT

    text = (ROOT / "docs" / "reference.md").read_text(encoding="utf-8")
    assert f"| {QUESTION} | stopped at a question it cannot ask" in text


def test_a_choice_without_a_terminal_is_a_question(tmp_path, capsys):
    promptfoo_project(tmp_path, split(20, 12))
    table_project(tmp_path, split(16, 16), name="scores.csv")
    code, out, _ = run(capsys, tmp_path)
    assert code == QUESTION
    assert "choose one with --tool promptfoo or --tool table" in out


def test_real_usage_errors_keep_two(tmp_path, capsys):
    assert run(capsys, tmp_path)[0] == 2  # nothing found
    assert run(capsys, tmp_path, "--tool", "deepeval")[0] == 2
    assert main(["start", "--tool-typo"]) == 2


# 5. Resume and small wording -------------------------------------------------------------

def test_resuming_names_the_results_and_the_counts(tmp_path, capsys, terminal):
    promptfoo_project(tmp_path, split(20, 12))
    start_label.prepare(start.find_judge(tmp_path), say=lambda line="": None)
    terminal.append("n")
    code, out, _ = run(capsys, tmp_path)
    assert code == 0
    lines = [line.rstrip() for line in out.splitlines()]
    asked = lines.index("You labeled 0 (Correct 0, Wrong 0). Continue? [Y/n]")
    assert lines[asked - 1] == "Using results.json: the judge passed 20 and failed 12."


def test_the_rule_is_cut_at_a_word():
    rule = ("The answer is polite, is correct for a small UK online homeware shop (no made-up "
            "promises, never reveals passwords), and gives the customer a clear next step.")
    assert start.rubric_line(rule) == "The answer is polite, is correct for a small UK online…"
    assert start.rubric_line("x" * 100) == "x" * 59 + "…"  # no word to cut at


def test_after_choosing_a_judge_it_says_the_flag_for_next_time(tmp_path, capsys, terminal):
    records_project(tmp_path, split(20, 16), name="helpful", pid=1)
    records_project(tmp_path, split(20, 16), name="safe_wording", pid=2)
    terminal += ["2", "n"]
    _, out, _ = run(capsys, tmp_path)
    lines = out.splitlines()
    asked = next(i for i, line in enumerate(lines) if line.startswith("Which one? [1-2]"))
    assert lines[asked + 1] == "(Next time: --metric safe_wording)"


def test_after_choosing_a_tool_too(tmp_path, capsys, terminal):
    promptfoo_project(tmp_path, split(20, 12))
    table_project(tmp_path, split(16, 16), name="scores.csv")
    terminal += ["2", "n"]
    _, out, _ = run(capsys, tmp_path)
    assert "(Next time: --tool table)" in out


def test_ask_again_before_labels_says_what_it_will_do(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    promptfoo_project(tmp_path, split(20, 12))
    code, out, _ = run(capsys, "--ask-again", "--no-browser")
    assert code == 2
    assert out.splitlines() == [
        ("There is no result to ask about yet: asking your judge again needs your labels. "
         "Label first: judgekeeper start --no-browser --yes"),
        ("Then judgekeeper start --no-browser --ask-again shows the plan (how many calls, the "
         "cost, the key's name) and asks before any call."),
    ]


def test_ask_again_before_labels_on_records_names_judge_command(tmp_path, capsys,
                                                                 monkeypatch):
    monkeypatch.chdir(tmp_path)
    records_project(tmp_path, split(20, 16))
    code, out, _ = run(capsys, "--ask-again")
    assert code == 2
    assert out.splitlines()[-1] == (
        "Your judge runs in your own code, so asking it again needs --judge-command: your "
        "judge as a command that reads one answer as JSON on stdin and prints its verdict.")


def test_ask_again_at_a_terminal_needs_no_yes_to_label(tmp_path, capsys, terminal,
                                                       monkeypatch):
    monkeypatch.chdir(tmp_path)
    promptfoo_project(tmp_path, split(20, 12))
    _, out, _ = run(capsys, "--ask-again")
    assert "Label first: judgekeeper start\n" in out
