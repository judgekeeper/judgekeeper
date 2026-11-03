"""What `fix <file>` and `check <file>` make of new results that are not a clean regrade: an
answer graded twice with different grades, answers kept aside left out, the grades judgekeeper
already has, repeats, and too few marked answers to tell.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from judgekeeper import fix
from judgekeeper.textio import quote_arg
from tests.test_only_reads import (
    FIRST,
    WRONG,
    N,
    hidden,
    judge,
    person,
    project,
    run,
    write_results,
)


@pytest.fixture
def here(tmp_path, monkeypatch):
    project = tmp_path / "support-bot"
    project.mkdir()
    monkeypatch.chdir(project)
    return project


def flat(out: str) -> str:
    return " ".join(out.split())


def _jsonl(path: Path, rows: list[tuple[int, bool]]) -> Path:
    """A results file of the jsonl project's answers: (index, pass) per row, repeats too."""
    from tests.start_projects import answer, question

    path.write_text("".join(json.dumps({"input": question(i), "output": answer(i),
                                        "verdict": "pass" if v else "fail",
                                        "model": "gpt-4.1"}) + "\n" for i, v in rows),
                    encoding="utf-8")
    return path


AGREED_FAILS = [i for i in range(N) if not person(i) and not judge(i)]


# An answer graded twice with different grades -------------------------------------------------

def test_check_counts_an_answer_with_two_grades_against_the_judge(here, capsys, monkeypatch):
    project("jsonl", here, monkeypatch)
    capsys.readouterr()
    flipped = AGREED_FAILS[:12]  # 12 agreed Fails now passed: a drop over 20 points
    rows = [(i, judge(i) or i in flipped) for i in range(N)]
    code, out = run(capsys, "check", _jsonl(here / "new.jsonl", rows).name)
    assert code == 1, out
    rows += [(i, False) for i in flipped]  # the same 12 again, with the old grade
    code, out = run(capsys, "check", _jsonl(here / "twice.jsonl", rows).name)
    assert code == 1, out
    said = flat(out)
    assert ("12 answers got different grades in your new results. judgekeeper counts them against your "
            "LLM-as-a-judge.") in said
    assert "had no grade" not in said


def test_fix_counts_an_answer_with_two_grades_against_the_new_rule(here, capsys, monkeypatch):
    ws = project("jsonl", here, monkeypatch)
    capsys.readouterr()
    run(capsys, "fix")
    kept = hidden(ws)
    fixed = sorted(WRONG & set(kept))
    rows = [(i, person(i)) for i in range(N)]  # every answer graded as the person marked
    rows.append((fixed[0], judge(fixed[0])))  # one fixed mistake again, with the old grade
    code, out = run(capsys, "fix", _jsonl(here / "twice.jsonl", rows).name)
    assert code == 0, out
    assert ("1 answer got different grades in your new results. judgekeeper counts them against your "
            "LLM-as-a-judge.") in flat(out)
    test = fix.read_split(ws).tests[-1]
    assert test["fixed"] == len(fixed) - 1 and test["n"] == len(kept)


# Answers kept aside left out ---------------------------------------------------------------------

def test_fix_gives_no_verdict_when_answers_kept_aside_are_missing(here, capsys, monkeypatch):
    ws = project("jsonl", here, monkeypatch)
    capsys.readouterr()
    run(capsys, "fix")
    kept = hidden(ws)
    gone = kept[:3]
    rows = [(i, person(i)) for i in range(N) if i not in gone]
    code, out = run(capsys, "fix", _jsonl(here / "part.jsonl", rows).name)
    said = flat(out)
    assert (f"Result: can't tell. 3 of the {len(kept)} answers kept aside have no grade in your "
            "new results: 3 are not in the file.") in said, out
    assert said.count("Result:") == 1
    nxt = said[said.rindex("Next:"):]
    assert "marked-answers.csv" in nxt
    assert "more questions" not in nxt and "Mark more answers" not in said
    assert code == 3


def test_the_same_rule_graded_again_in_full_is_a_new_test(here, capsys, monkeypatch):
    """A partial regrade, then the full one with the same rule: the full one is tested, not
    called the test before."""
    ws = project("promptfoo", here, monkeypatch)
    capsys.readouterr()
    run(capsys, "fix")
    kept = hidden(ws)
    part = write_results("promptfoo", here / "part.json",
                         {i: person(i) for i in range(N) if i != kept[0]}, regraded=True)
    run(capsys, "fix", part.name)
    full = write_results("promptfoo", here / "full.json", {i: person(i) for i in range(N)},
                         regraded=True)
    code, out = run(capsys, "fix", full.name)
    assert code == 0 and "You tested this LLM-as-a-judge before" not in out, out
    assert fix.read_split(ws).tests[-1]["n"] == len(kept)


# The grades judgekeeper already has --------------------------------------------------------------

@pytest.mark.parametrize("tool", ["promptfoo", "jsonl"])
def test_the_marked_results_again_are_no_rule_test(tool, here, capsys, monkeypatch):
    ws = project(tool, here, monkeypatch)
    capsys.readouterr()
    run(capsys, "fix")
    code, out = run(capsys, "fix", FIRST[tool])
    assert code == 3, out
    assert ("These grades are the same as when you marked. Use the results from after your "
            "change.") in flat(out)
    assert "Result:" not in out
    assert fix.read_split(ws).tests == []


# Repeats with the same grade -------------------------------------------------------------------

@pytest.mark.parametrize("command", ["fix", "check"])
def test_repeats_with_the_same_grade_are_counted_once_and_said(command, here, capsys,
                                                               monkeypatch):
    project("jsonl", here, monkeypatch)
    capsys.readouterr()
    run(capsys, "fix")
    rows = [(i, person(i)) for i in range(N)] + [(i, person(i)) for i in range(4)]
    code, out = run(capsys, command, _jsonl(here / "repeats.jsonl", rows).name)
    assert code in (0, 1), out
    assert ("4 repeated results in your new results were counted once.") in flat(out)


# check with too few marked answers found -------------------------------------------------------

def test_check_with_too_few_marked_answers_found_cant_tell(here, capsys, monkeypatch):
    project("jsonl", here, monkeypatch)
    capsys.readouterr()
    flipped = AGREED_FAILS[:8]  # a big drop, but on few answers
    some = [i for i in range(N) if i < 10 or i in flipped]
    rows = [(i, judge(i) or i in flipped) for i in some]
    code, out = run(capsys, "check", _jsonl(here / "few.jsonl", rows).name)
    said = flat(out)
    assert code == 3, out
    assert "Compared with before: can't tell yet." in said
    assert "A re-check needs 15 of each" in said
    assert ("Next: run `judgekeeper fix` to write the answers you marked to "
            ".judgekeeper/fix/marked-answers.csv, grade every one again with your LLM-as-a-judge "
            "as it is now, then run `judgekeeper check <new results file>`.") in said, said


def test_inspect_check_with_too_few_says_to_score_the_whole_log_again(here, capsys):
    pytest.importorskip("inspect_ai")
    from judgekeeper.check import _state, regrade_marked

    log, _ = _marked_inspect_log(here, capsys)
    assert regrade_marked(_state("."), every=True).startswith(
        "score your whole marked log again with your LLM-as-a-judge as it is now: run "), log


# Inspect AI: the log graded again ----------------------------------------------------------------

def _marked_inspect_log(here, capsys, option: bool = False) -> tuple:
    """An Inspect AI log graded by model_graded_qa (a mock grader), every answer marked, and
    `judgekeeper fix` run once: (the log, the workspace). `option`: the grader is the scorer's
    `model=` (mockllm/grader), not the grader role."""
    from inspect_ai import Task
    from inspect_ai import eval as run_eval
    from inspect_ai.dataset import Sample
    from inspect_ai.model import ModelOutput, get_model
    from inspect_ai.scorer import model_graded_qa
    from inspect_ai.solver import generate

    from judgekeeper.cli import main
    from judgekeeper.start_label import StartSession, Workspace
    from tests.test_only_reads import closed

    old_rule = "Old rule. GRADE: C or GRADE: I."
    name = "mockllm/grader" if option else "mockllm/model"
    grades = [ModelOutput.from_content(name, f"GRADE: {'C' if i % 3 else 'I'}")
              for i in range(N)]
    grader = get_model(name, custom_outputs=grades)
    task = Task(dataset=[Sample(input=f"Question {i}?", target=f"Answer {i}") for i in range(N)],
                solver=generate(), scorer=model_graded_qa(instructions=old_rule,
                                                          **({"model": grader} if option else {})))
    log = Path(run_eval(task, model="mockllm/model", display="none", log_dir=str(here / "logs"),
                        **({} if option else {"model_roles": {"grader": grader}}))[0].location)
    assert main(["--no-browser"]) == 0
    ws = Workspace(here)
    session = StartSession(ws)
    for n, item in enumerate(session.items):
        session.update({"id": item["id"], "label": "pass" if n % 2 else "fail", "seconds": 5})
    closed(ws)
    capsys.readouterr()
    code, out = run(capsys, "fix")
    assert code == 0, out
    said = flat(out)
    new = fix.new_log(ws)
    assert new == "logs/new.eval"  # next to the marked log, where `check` finds it
    model = f" -S model={quote_arg('mockllm/grader')}" if option else ""  # roles are kept
    assert fix.inspect_score(ws) == (f"inspect score logs/{log.name} --scorer model_graded_qa "
                                     f"-S instructions={quote_arg('<new rule>')}{model} "
                                     "--action overwrite")
    assert fix.inspect_score(ws, new) == f"{fix.inspect_score(ws)} --output-file {new}"
    assert (f"run `{fix.inspect_score(ws, new)}` and then run `judgekeeper fix {new}`") in said
    assert "with `--output-file" not in said, said
    assert fix.REGRADE["inspect"] in said, said  # with the way round a rule `-S` can't take
    assert fix.EVAL_TOOLS in fix.REGRADE["inspect"] and "score() in Python" in said
    assert fix.EVAL_TOOLS == "https://github.com/judgekeeper/judgekeeper/blob/main/docs/eval-tools.md"
    tools = (Path(__file__).parents[1] / "docs" / "eval-tools.md").read_text(encoding="utf-8")
    assert "- **A new rule with a comma, or a colon followed by a space.**" in tools
    return log, ws


def test_inspect_score_as_fix_says_gives_fix_the_new_grades(here, capsys, monkeypatch):
    """The command fix prints for Inspect AI, run for real with the new rule in its place: the
    new grades are under the scorer's own name in a new log, fix reads them as the new rule,
    and the log the marks were made on stays as it was."""
    pytest.importorskip("inspect_ai")
    import hashlib
    import shlex
    import subprocess
    import sys

    from judgekeeper import judge_setup
    from judgekeeper.fingerprint import rule_hash

    log, ws = _marked_inspect_log(here, capsys)
    new = fix.new_log(ws)
    new_rule = "New rule. GRADE C or GRADE I."
    before = hashlib.sha256(log.read_bytes()).hexdigest()
    printed = shlex.split(fix.inspect_score(ws, quote_arg(new)))  # its paths have no "\\"
    assert printed[:2] == ["inspect", "score"] and "instructions=<new rule>" in printed
    argv = [f"instructions={new_rule}" if a == "instructions=<new rule>" else a
            for a in printed[2:]]
    # Inspect's own command line, with a grader whose reply holds a grade
    cli = ("import sys; from inspect_ai.model._providers.mockllm import MockLLM; "
           "MockLLM.default_output = 'GRADE: C'; from inspect_ai._cli.main import main; "
           "sys.argv[0] = 'inspect'; main()")
    done = subprocess.run(
        [sys.executable, "-c", cli, "score", *argv, "--model-role", "grader=mockllm/model",
         "--display", "none"],
        cwd=here, capture_output=True, text=True, timeout=300, stdin=subprocess.DEVNULL,
        check=False)
    assert done.returncode == 0, done.stdout + done.stderr
    assert hashlib.sha256(log.read_bytes()).hexdigest() == before

    code, out = run(capsys, "fix", new)
    assert code == 0, out
    assert "Result:" in out
    test = fix.read_split(ws).tests[-1]
    marked_rule = (judge_setup.read(ws) or {})["setup"]["rule_hash"]
    assert test["rule_hash"] and test["rule_hash"] != marked_rule
    assert test["rule_hash"] == rule_hash(new_rule)  # the rule in the command reached the scorer
    code, out = run(capsys, "check")  # the new log, with the others: no choice to make
    assert "need a choice" not in out and "run your eval once" not in out, out


# Inspect's command line, where only the grader model's reply holds a grade (the task's model
# gives none): a log graded by the wrong model has no grades
GRADER_ONLY = ("import sys; from inspect_ai.model._providers.mockllm import MockLLM; "
               "init = MockLLM.__init__\n"
               "def mine(self, model_name, *a, **k):\n"
               "    init(self, model_name, *a, **k)\n"
               "    if model_name == 'grader': self.default_output = 'GRADE: C'\n"
               "MockLLM.__init__ = mine\n"
               "from inspect_ai._cli.main import main; sys.argv[0] = 'inspect'; main()")


def test_a_grader_set_as_the_scorers_model_is_in_the_command_fix_prints(here, capsys):
    """model_graded_qa(model=...) is not kept by `inspect score`: without `-S model=`, the
    task's model grades and every grade is empty. The printed command names the grader, it
    parses and runs with Inspect's own command line, and a log with no grades is said plainly,
    not answered with the same command."""
    pytest.importorskip("inspect_ai")
    import shlex
    import subprocess
    import sys

    from inspect_ai._cli.score import score_command

    _, ws = _marked_inspect_log(here, capsys, option=True)
    assert fix.scorer_model(ws) == "mockllm/grader"
    new = fix.new_log(ws)
    printed = shlex.split(fix.inspect_score(ws, quote_arg(new)))  # its paths have no "\\"
    argv = ["instructions=New rule. GRADE C or GRADE I." if a == "instructions=<new rule>"
            else a for a in printed[2:]]
    assert "model=mockllm/grader" in score_command.make_context("score", list(argv)).params["s"]

    def score(args):
        done = subprocess.run([sys.executable, "-c", GRADER_ONLY, "score", *args,
                               "--display", "none"], cwd=here, capture_output=True, text=True,
                              timeout=300, stdin=subprocess.DEVNULL, check=False)
        assert done.returncode == 0, done.stdout + done.stderr
        return run(capsys, "fix", new)

    i = argv.index("model=mockllm/grader")
    code, out = score(argv[:i - 1] + argv[i + 1:])  # the command as it was: no grader model
    said = flat(out)
    assert code != 0 and "Result:" not in said, said
    assert fix.NO_GRADES.format(n=len(fix.read_split(ws).hidden)) in said, said
    assert fix.NO_GRADES_INSPECT in said, said
    assert said.endswith(f"run `{fix.inspect_score(ws, quote_arg(new))}` and then run "
                         f"`judgekeeper fix {new}`."), said
    (here / new).unlink()  # else Inspect asks before it writes over it
    code, out = score(argv)  # as printed
    assert code == 0 and "Result:" in out, out


def test_a_rule_with_commas_graded_again_in_python_as_the_docs_show(here, capsys):
    """`inspect score -S` cuts a rule at its commas (Inspect reads -S values as YAML, then
    splits text at commas); Inspect's score() in Python, as docs/eval-tools.md shows, keeps
    the whole rule, and fix reads it as the new rule."""
    pytest.importorskip("inspect_ai")
    from inspect_ai import score
    from inspect_ai.log import read_eval_log, write_eval_log
    from inspect_ai.model import ModelOutput, get_model
    from inspect_ai.scorer import model_graded_qa

    from judgekeeper.fingerprint import rule_hash

    log, ws = _marked_inspect_log(here, capsys)
    new_rule = "New rule, with commas: dates, prices, names. GRADE: C or GRADE: I."
    grader = get_model("mockllm/model", custom_outputs=[
        ModelOutput.from_content("mockllm/model", "GRADE: C") for _ in range(N)])
    write_eval_log(score(read_eval_log(str(log)), model_graded_qa(instructions=new_rule),
                         model_roles={"grader": grader}, action="overwrite", display="none"),
                   "logs/new.eval")
    code, out = run(capsys, "fix", "logs/new.eval")
    assert code == 0 and "Result:" in out, out
    assert fix.read_split(ws).tests[-1]["rule_hash"] == rule_hash(new_rule)


def test_the_docs_python_regrade_names_the_llm_as_a_judge(here, capsys):
    """The Python snippet in docs/eval-tools.md, run as written: it passes `model=`, so the new
    log names the grader and `check` sees the same model, with only the rule changed."""
    pytest.importorskip("inspect_ai")
    import subprocess
    import sys

    docs = (Path(__file__).parents[1] / "docs" / "eval-tools.md").read_text(encoding="utf-8")
    snippet = docs.split("```python\n", 1)[1].split("```", 1)[0]
    assert 'model="<the grader model you used>"' in snippet, snippet
    log, _ = _marked_inspect_log(here, capsys)
    (here / "rule.txt").write_text("New rule. GRADE: C or GRADE: I.", encoding="utf-8")
    script = "\n".join(line.removeprefix("  ") for line in snippet.splitlines())
    script = (script.replace("logs/<your log>.eval", log.relative_to(here).as_posix())
              .replace("<the grader model you used>", "mockllm/model"))
    mock = ("from inspect_ai.model._providers.mockllm import MockLLM\n"
            "MockLLM.default_output = 'GRADE: C'\n")  # a grader whose reply holds a grade
    done = subprocess.run([sys.executable, "-c", mock + script], cwd=here, capture_output=True,
                          text=True, timeout=300, stdin=subprocess.DEVNULL, check=False)
    assert done.returncode == 0, done.stdout + done.stderr
    _, out = run(capsys, "check", "logs/new.eval")
    assert "Your LLM-as-a-judge changed: rule changed." in flat(out), out


def test_the_lines_on_grading_again_link_the_eval_tools_page():
    """A pip install has no docs/ folder: the lines link the page on GitHub."""
    from judgekeeper import fix

    for tool in ("promptfoo", "inspect"):
        assert fix.EVAL_TOOLS in fix.REGRADE[tool], tool
    assert not any("judgekeeper's docs/" in line for line in fix.REGRADE.values())
