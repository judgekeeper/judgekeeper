"""`check` and `fix <file>` compare a new LLM-as-a-judge with the right grades, on the right
answers: a value shared by many questions never matches an answer to another question, the
old grades come from the LLM-as-a-judge that made them, and a regrade never loops or brings
marked answers back as new. No test calls an API: judgekeeper only reads the results files.
"""

from __future__ import annotations

import csv
import json
import re
import time
from pathlib import Path

import pytest

from judgekeeper import batches, fix
from judgekeeper.cli import main
from judgekeeper.start_label import StartSession, Workspace
from tests.start_projects import promptfoo_data


@pytest.fixture
def here(tmp_path, monkeypatch):
    project = tmp_path / "support-bot"
    project.mkdir()
    monkeypatch.chdir(project)
    return project


def run(capsys, *argv) -> tuple[int, str]:
    code = main([str(a) for a in argv])
    out, err = capsys.readouterr()
    return code, " ".join((out + err).split())


# H1: a value many questions share is not the question ----------------------------------------

YES_NO = 60
PERSONA = "Pedalwise support bot"


def _yes_no(path: Path, no: set[int], rubric: str = "Right answer only.",
            persona: bool = True) -> Path:
    """promptfoo results of YES_NO yes/no questions, each with the same persona var. Question
    i's right answer is Yes when i is even; every answer is "Yes." except those in `no`. The
    LLM-as-a-judge is right on every one."""
    outputs = ["No." if i in no else "Yes." for i in range(YES_NO)]
    right = [(o == "Yes.") == (i % 2 == 0) for i, o in enumerate(outputs)]
    data = promptfoo_data(right, rubric=rubric, outputs=outputs)
    for i, row in enumerate(data["results"]["results"]):
        qvars = {"question": f"Question {i}: is claim {i} true?",
                 **({"persona": PERSONA} if persona else {})}
        row["vars"] = row["testCase"]["vars"] = qvars
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _marked_yes_no(root: Path, persona: bool = True) -> Workspace:
    (root / "promptfooconfig.yaml").write_text(
        "description: support bot\nprompts:\n  - 'Answer: {{question}}'\n", encoding="utf-8")
    _yes_no(root / "results.json", set(), persona=persona)
    assert main(["--no-browser"]) == 0
    ws = Workspace(root)
    session = StartSession(ws)
    groups = {q["id"]: q["group"] for q in ws.data()["queue"]}
    for item in session.items:  # the person agrees with the LLM-as-a-judge on every answer
        session.update({"id": item["id"], "label": groups[item["id"]], "seconds": 5})
    main(["mark", "--no-browser", "--stop"])
    return ws


@pytest.mark.parametrize("persona", [True, False])
def test_a_shared_var_never_matches_another_questions_answer(here, capsys, persona):
    """New answers "No." on every fourth question, still graded right: those marked answers
    are not in the new results, and no other question's "Yes." stands in for them."""
    _marked_yes_no(here, persona=persona)
    capsys.readouterr()
    new = _yes_no(here / "new.json", {i for i in range(YES_NO) if i % 4 == 0},
                  rubric="Right answers only, please.", persona=persona)
    code, out = run(capsys, "check", new.name)
    assert code == 0, out
    assert ("15 of your 60 marked answers had no grade in your new results, so judgekeeper "
            "left them out") in out, out
    assert "counted against" not in out and "Worse" not in out, out


def test_the_echo_regrade_still_finds_every_answer_kept_aside(here, capsys):
    """promptfoo grading marked-answers.csv again holds vars {question, answer}: the question
    names one marked answer, so each kept aside is found, the persona never needed."""
    ws = _marked_yes_no(here)
    capsys.readouterr()
    assert main(["fix"]) == 0
    capsys.readouterr()
    kept = len(fix.read_split(ws).hidden)
    with (ws.dir / "fix" / "marked-answers.csv").open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == YES_NO
    wrong = [(r["answer"] == "Yes.") != (int(re.search(r"Question (\d+):", r["question"])[1])
                                         % 2 == 0) for r in rows]  # every grade the other way
    data = promptfoo_data(wrong, rubric="Right answers only, please.",
                          outputs=[r["answer"] for r in rows])
    for row, r in zip(data["results"]["results"], rows, strict=True):
        row["vars"] = row["testCase"]["vars"] = {"question": r["question"],
                                                 "answer": r["answer"]}
    (here / "regraded.json").write_text(json.dumps(data), encoding="utf-8")
    code, out = run(capsys, "fix", "regraded.json")
    assert code == 0, out
    assert f"tested on the {kept} marks kept aside" in out, out
    assert "no grade" not in out, out


# H2: the old grades are the old LLM-as-a-judge's own ------------------------------------------

ROWS = 90


def _table(path: Path, model: str, wrong) -> Path:
    """A results table of ROWS answers: every third one made up (the person fails it); the
    LLM-as-a-judge agrees with the person except on the rows `wrong(i)`."""
    lines = ["input,output,verdict,reason,model"]
    for i in range(ROWS):
        bad = i % 3 == 0
        verdict = (not bad) != wrong(i)
        lines.append(f"Question {i}: what is the return policy?,"
                     f"Answer {i}: {'BAD made-up wrong answer.' if bad else '30 days.'},"
                     f"{'pass' if verdict else 'fail'},because,{model}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _mark(ws: Workspace, keep) -> None:
    session = StartSession(ws)
    for item in session.items:
        i = int(re.search(r"Question (\d+):", json.dumps(item["input"]))[1])
        if keep(i):
            session.update({"id": item["id"], "label": "fail" if i % 3 == 0 else "pass",
                            "seconds": 5})


def test_marks_added_after_two_changes_are_never_graded_by_the_first(here, capsys):
    """Marks on 60 answers; two new LLM-as-a-judges taken on in turn, the same grades (right
    on those 60, wrong on most others); then 30 more marks. The 30 have no grade from the one
    before: left out, never compared with the first one's grades."""
    (here / "pyproject.toml").write_text('[project]\nname = "x"\n', encoding="utf-8")
    _table(here / "results.csv", "gpt-4.1-mini", lambda i: i % 5 == 0)
    assert main(["--no-browser"]) == 0
    ws = Workspace(here)
    _mark(ws, lambda i: i < 60)
    main(["mark", "--no-browser", "--stop"])
    for model in ("m2", "m3"):
        new = _table(here / f"{model}.csv", model, lambda i: i >= 60 and i % 3 != 0)
        code, out = run(capsys, "check", new.name)
        assert code == 0, out
    time.sleep(1.1)  # marks are stamped to the second
    _mark(ws, lambda i: i >= 60)
    code, out = run(capsys, "check", "m3.csv")
    assert code == 0, out
    assert "You added 30 marks since your last check." in out, out
    assert "Worse" not in out and "Result: worse" not in out, out
    assert ("30 of your marked answers have no grade from your old LLM-as-a-judge, only from "
            "one before it, so judgekeeper left them out of the table.") in out, out


# M4: back to the LLM-as-a-judge the marks were made on, only when its grades are too ---------

def test_a_table_under_the_first_models_name_is_still_compared(here, capsys):
    """A table holds no rule: the same model's name with other grades is not the
    LLM-as-a-judge the marks were made on."""
    (here / "pyproject.toml").write_text('[project]\nname = "x"\n', encoding="utf-8")
    _table(here / "results.csv", "gpt-4.1-mini", lambda i: i % 5 == 0)
    assert main(["--no-browser"]) == 0
    _mark(Workspace(here), lambda i: i < 60)
    main(["mark", "--no-browser", "--stop"])
    code, out = run(capsys, "check", _table(here / "m2.csv", "m2", lambda i: False).name)
    assert code == 0, out
    every_fail = _table(here / "af.csv", "gpt-4.1-mini", lambda i: i % 3 != 0)
    code, out = run(capsys, "check", every_fail.name)
    assert code == 1, out
    assert "back to the one you marked with" not in out and "Result: worse" in out, out


# M5: answers kept aside that marked-answers.csv lacks ------------------------------------------

def _regrade_csv(ws: Workspace, path: Path) -> Path:
    """marked-answers.csv graded again, as a new rule that agrees with the person would."""
    with (ws.dir / "fix" / "marked-answers.csv").open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["input", "output", "verdict", "reason", "model"])
        for r in rows:
            w.writerow([r["question"], r["answer"], "fail" if "BAD" in r["answer"] else "pass",
                        "because", "gpt-4.1-mini"])
    return path


def test_fix_with_a_file_rewrites_the_csv_that_lacks_answers_kept_aside(here, capsys):
    """30 more marks after `fix` add answers kept aside that marked-answers.csv does not hold:
    `fix <file>` writes it again and says to grade it, so the next regrade gets a result."""
    (here / "pyproject.toml").write_text('[project]\nname = "x"\n', encoding="utf-8")
    _table(here / "results.csv", "gpt-4.1-mini", lambda i: i % 5 == 0)
    assert main(["--no-browser"]) == 0
    ws = Workspace(here)
    _mark(ws, lambda i: i < 60)
    main(["mark", "--no-browser", "--stop"])
    assert main(["fix"]) == 0
    capsys.readouterr()
    first = _regrade_csv(ws, here / "new.csv")  # graded before the 30 more marks
    time.sleep(1.1)
    _mark(ws, lambda i: i >= 60)
    code, out = run(capsys, "fix", first.name)
    assert code == 3, out
    assert ("judgekeeper wrote .judgekeeper/fix/marked-answers.csv again: it now holds every "
            "answer you marked, with the answers kept aside your new results lack.") in out, out
    assert ("Next: grade every answer in .judgekeeper/fix/marked-answers.csv again with your "
            "new rule, then run `judgekeeper fix <new results file>`.") in out, out
    with (ws.dir / "fix" / "marked-answers.csv").open(encoding="utf-8", newline="") as f:
        assert len(list(csv.DictReader(f))) == ROWS
    code, out = run(capsys, "fix", _regrade_csv(ws, here / "new2.csv").name)
    assert code == 0, out
    assert f"tested on the {len(fix.read_split(ws).hidden)} marks kept aside" in out, out


# M6: the echo regrade's answers are the marked ones, not new ---------------------------------

def test_the_echo_regrade_taken_on_adds_no_marked_answer_as_new(here, capsys, monkeypatch):
    """promptfoo's echo regrade holds vars {question, answer}; once `check` takes it on, the
    next run finds no answer you haven't seen: each is a marked one."""
    from tests.test_only_reads import N, closed, person, project, write_results

    ws = project("promptfoo", here, monkeypatch)
    assert main(["fix"]) == 0
    new = write_results("promptfoo", here / "regraded.json", {i: person(i) for i in range(N)},
                        regraded=True)
    assert main(["fix", new.name]) == 0
    assert main(["check", new.name]) == 0
    capsys.readouterr()
    _, out = run(capsys, "--no-browser")
    closed(ws)
    assert "you haven't seen" not in out, out
    assert set(batches.of(ws.data()).values()) == {1}
    assert len(ws.pool.read_text(encoding="utf-8").splitlines()) == N


# N1: after "better" or "safe to try", the Next lines lead to a re-check, never round again ----------------------

def test_after_better_the_next_lines_re_check_and_never_loop(here, capsys, monkeypatch):
    """`fix` after "safe to try" (as after "better") says to check the results it just tested, which grade every marked
    answer. Running the eval again writes new answers: `check` says so, and its Next is to grade
    the marked answers again, not to run the eval again."""
    from tests.test_only_reads import N, person, project, write_results

    project("promptfoo", here, monkeypatch)
    assert main(["fix"]) == 0
    new = write_results("promptfoo", here / "regraded.json", {i: person(i) for i in range(N)},
                        regraded=True)
    capsys.readouterr()
    code, out = run(capsys, "fix", new.name)
    assert code == 0 and "Result: safe to try." in out, out
    assert out.endswith("Next: keep your new rule, then run `judgekeeper check regraded.json` "
                        "to re-check it on all your marks."), out
    assert main(["check", new.name]) == 0
    data = json.loads(new.read_text(encoding="utf-8"))
    for row in data["results"]["results"][5:]:  # the eval ran again: most answers are new
        row["response"]["output"] += " Anything else?"
        row["vars"] = row["testCase"]["vars"] = {"question": row["vars"]["question"]}
    (here / "rerun.json").write_text(json.dumps(data), encoding="utf-8")
    capsys.readouterr()
    code, out = run(capsys, "check", "rerun.json")
    assert code == 3, out
    assert ("Your new results ask 35 of those questions again with a different answer: your "
            "eval wrote new answers, and judgekeeper compares only the answers you marked."
            ) in out, out
    assert "run your eval" not in out, out
    assert out.endswith("Next: grade the answers in .judgekeeper/fix/marked-answers.csv again "
                        "with your LLM-as-a-judge as it is now, then run `judgekeeper check "
                        "<new results file>`."), out


# N6: Inspect AI scores its log again, never marked-answers.csv --------------------------------

def test_nothing_to_fix_on_inspect_says_to_score_the_log_again(here, capsys, monkeypatch):
    from tests.test_only_reads import FIRST, N, closed, mark_all, person, write_results

    write_results("inspect", here / FIRST["inspect"], {i: person(i) for i in range(N)})
    assert main(["--no-browser"]) == 0
    ws = Workspace(here)
    mark_all(ws)
    closed(ws)
    capsys.readouterr()
    code, out = run(capsys, "fix")
    assert code == 0 and "there is nothing to fix" in out, out
    assert out.endswith("Next: nothing to fix. To test another rule anyway, score your log "
                        "again with it: run `inspect score <log> --scorer <name> --action "
                        "overwrite` with `--output-file logs/new.eval`, then run `judgekeeper "
                        "fix logs/new.eval`."), out


# N5: no "'better' needs" line for a rule that leans worse -------------------------------------

def test_a_rule_that_leans_worse_gets_no_better_needs_line(here, capsys, monkeypatch):
    from tests.test_only_reads import WRONG, N, hidden, judge, person, project, write_results

    ws = project("promptfoo", here, monkeypatch)
    assert main(["fix"]) == 0
    right = [i for i in hidden(ws) if i not in WRONG]
    verdicts = {i: judge(i) for i in range(N)}
    for i in right[:2]:  # two right answers broken, no mistake fixed
        verdicts[i] = not person(i)
    new = write_results("promptfoo", here / "regraded.json", verdicts, regraded=True)
    capsys.readouterr()
    code, out = run(capsys, "fix", new.name)
    assert code == 0 and "leans toward worse" in out, out
    assert "'better' needs" not in out and "Only " not in out, out


# N2: a choice of one folder never hides newer results elsewhere -------------------------------

def _inspect_log(path: Path, verdicts: dict[int, bool], rule: str) -> Path:
    """An Inspect AI log (as test_only_reads writes it) graded with the rule `rule`."""
    from tests.test_only_reads import write_results

    write_results("inspect", path, verdicts)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["eval"]["scorers"][0]["options"]["instructions"] = rule
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_check_says_newer_results_outside_the_chosen_folder(here, capsys, monkeypatch):
    """A log in the project folder chosen as where to read (`file = "."`), then a newer log in
    logs/: `check` names the file it read, and says the newer one is not read, never "no
    change" or "No big drop" on the older one."""
    import os

    from tests.test_only_reads import N, judge, person, project

    ws = project("inspect", here, monkeypatch)
    _inspect_log(here / "new.json", {i: person(i) for i in range(N)}, "Grade it C or I, strictly.")
    (here / "judgekeeper.toml").write_text('[start]\nsource = "inspect"\nfile = "."\n',
                                           encoding="utf-8")
    capsys.readouterr()
    code, out = run(capsys, "check")
    assert code == 0 and "New results: new.json" in out, out
    newer = _inspect_log(here / "logs" / "new2.json", {i: not judge(i) for i in range(N)},
                         "Grade it C or I, any way.")
    stamp = (here / "new.json").stat().st_mtime + 60
    os.utime(newer, (stamp, stamp))
    code, out = run(capsys, "check")
    assert code == 3, out
    assert ("Your newest Inspect AI results, logs/new2.json, are not where your "
            "judgekeeper.toml says to read them (the project folder), so judgekeeper compared "
            "nothing.") in out, out
    assert "No big drop" not in out and "has not changed" not in out, out
    assert out.endswith("Next: run `judgekeeper check logs/new2.json` to re-check on them, or "
                        "set `file` in judgekeeper.toml to the folder they are in."), out
    assert ws.start.is_file()


def test_the_inspect_regrade_lines_keep_the_log_folder_after_a_check(here, capsys, monkeypatch):
    """`check logs/new.json` takes on the new grades; every line after it still writes the
    regraded log in logs/, beside the others, never in the project folder."""
    from tests.test_only_reads import N, person, project

    ws = project("inspect", here, monkeypatch)
    assert main(["fix"]) == 0
    new = _inspect_log(here / "logs" / "new.json", {i: person(i) for i in range(N)},
                       "Grade it C or I, strictly.")
    assert main(["fix", "logs/new.json"]) == 0
    assert main(["check", "logs/new.json"]) == 0
    assert new.is_file()
    capsys.readouterr()
    assert fix.new_log(ws) == "logs/new.eval"

    class Talk:
        def command(self, *_):
            return "judgekeeper fix"

    line = fix._regrade_same(Talk(), ws)
    assert "`--output-file logs/new.eval`" in line and "fix logs/new.eval" in line, line


# N4: Measure says why it suggests going back --------------------------------------------------

def test_measure_after_a_worse_check_says_why_it_says_go_back(here, capsys):
    from tests.test_only_reads import closed

    ws = _marked_yes_no(here)
    outputs = ["Yes."] * YES_NO
    data = promptfoo_data([i % 2 != 0 for i in range(YES_NO)], rubric="Pass every no.",
                          outputs=outputs)  # every grade the wrong way
    for i, row in enumerate(data["results"]["results"]):
        row["vars"] = row["testCase"]["vars"] = {"question": f"Question {i}: is claim {i} true?",
                                                 "persona": PERSONA}
    (here / "new.json").write_text(json.dumps(data), encoding="utf-8")
    assert main(["check", "new.json"]) == 1
    capsys.readouterr()
    _, out = run(capsys, "--no-browser")
    closed(ws)
    assert ("Your last check found your LLM-as-a-judge in your newest results worse than this "
            "one. Next: go back to your old LLM-as-a-judge") in out, out
