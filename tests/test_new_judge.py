"""Trying your new judge on your old marks.

After the person changes their judge (a new rule, a new model) and runs their eval once,
`start` finds the new judge in the newest results, rebuilds it, and has it grade the answers
the person already marked: old judge and new judge side by side, the "it will look better on
these answers" warning, then a short confirmation check on new answers.

No test calls a paid API or needs promptfoo: the one process function is replaced by the fake
promptfoo of test_again_run, which answers each test with the verdict the newest results give
its question.
"""

from __future__ import annotations

import builtins
import json
from pathlib import Path

import pytest

from judgekeeper import again, keys, new_judge, start, start_label
from judgekeeper.cli import main
from judgekeeper.judgments import read_run
from judgekeeper.start_label import StartSession, Workspace, save_result
from tests.start_projects import (
    RUBRIC,
    answer,
    promptfoo_data,
    promptfoo_project,
    question,
    split,
)
from tests.test_again_run import FakePromptfoo

NEW_RUBRIC = "Is polite, correct and short."
VERSION = {"promptfooVersion": "0.123.1"}


def _quiet(line=""):
    pass


def _checked(root, n_pass=20, n_fail=16):
    """A promptfoo project with a finished check: every answer labeled as the judge saw it."""
    promptfoo_project(root, split(n_pass, n_fail))
    _meta(root)
    ws = start_label.prepare(start.find_judge(root), say=_quiet)
    session = StartSession(ws)
    for q in ws.data()["queue"]:
        session.update({"id": q["id"], "label": q["group"]})
    save_result(ws, session, say=_quiet)
    return ws


def _meta(root):
    path = root / "results.json"
    data = json.loads(path.read_text())
    data.setdefault("metadata", {}).update(VERSION)
    path.write_text(json.dumps(data))


def _new_run(root, verdicts=None, rubric=NEW_RUBRIC, same=0, rubrics=None, drop=0, **kwargs):
    """The next eval run, with a changed judge: the same questions, new answers (the first
    `same` answers unchanged), the new judge's verdicts; written over results.json."""
    verdicts = verdicts or split(20, 16)
    outputs = [answer(i) if i < same else f"{answer(i)} (v2)" for i in range(len(verdicts))]
    data = promptfoo_data(verdicts, rubric=rubric, created="2026-10-09T09:00:00Z",
                          outputs=outputs, **kwargs)
    rows = data["results"]["results"]
    if rubrics:
        for row, text in zip(rows, rubrics, strict=False):
            row["gradingResult"]["componentResults"][0]["assertion"]["value"] = text
    data["results"]["results"] = rows[drop:]
    data["metadata"].update(VERSION)
    (root / "results.json").write_text(json.dumps(data))


@pytest.fixture
def fake(monkeypatch, tmp_path):
    """A checked promptfoo project, the project's own promptfoo, the fake behind the one
    process function, and a key set in the shell."""
    ws = _checked(tmp_path)
    binary = tmp_path / "node_modules" / ".bin" / "promptfoo"
    binary.parent.mkdir(parents=True)
    binary.write_text("")
    for name in keys.all_names():
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "x" * 30)
    monkeypatch.setattr(again, "which", lambda name: None)
    holder = {}

    def runner(argv, cwd, env=None, timeout=None):
        if "fake" not in holder:  # the newest results are read when first called
            holder["fake"] = FakePromptfoo(ws)
        return holder["fake"](argv, cwd, env, timeout)

    monkeypatch.setattr(again, "run_process", runner)
    ws.fake = holder
    return ws


def _evals(ws) -> int:
    fake = ws.fake.get("fake")
    return sum("eval" in c.argv for c in fake.calls) if fake else 0


@pytest.fixture
def terminal(monkeypatch):
    answers: list[str] = []
    monkeypatch.setattr(start, "_interactive", lambda: True)

    def fake_input(prompt=""):
        print(prompt)
        return answers.pop(0) if answers else ""

    monkeypatch.setattr(builtins, "input", fake_input)
    return answers


@pytest.fixture
def confirmed(monkeypatch):
    """The confirmation page is not served: `labels(items, groups)` decides each label (by
    default the new judge's own verdict), then the result is made as the page would."""
    class Calls(list):
        labels = None  # a function (items, groups) -> {id: label}; None: as the new judge

    calls = Calls()

    def serve(ws, cws, port, open_browser, say):
        session = StartSession(cws)
        groups = {q["id"]: q["group"] for q in cws.data()["queue"]}
        chosen = (calls.labels or (lambda items, groups: {
            i["id"]: groups[i["id"]] for i in items}))(session.items, groups)
        for item_id, label in chosen.items():
            session.update({"id": item_id, "label": label})
        calls.append(cws)
        new_judge.finish_confirmation(ws, cws, session, say)
        return 0

    monkeypatch.setattr(new_judge, "serve_confirmation", serve)
    return calls


def run(capsys, *argv):
    code = main(["start", *map(str, argv)])
    out, err = capsys.readouterr()
    return code, out, err


def _folder(ws) -> Path:
    (folder,) = ws.dir.glob("new-judge-*")
    return folder


# Offered only when the judge changed -----------------------------------------------------

def test_a_changed_rubric_offers_to_try_the_new_judge(fake, capsys):
    _new_run(fake.root)
    code, out, _ = run(capsys, fake.root)
    assert code == 2  # no terminal: the menu as flags
    assert "Your judge changed since your last check: the prompt changed." in out
    line = next(x for x in out.splitlines() if "--try-new-judge" in x)
    assert "Try your new judge on your 36 marked answers (36 calls, " in line
    assert out.index("--try-new-judge") < out.index("--ask-again")
    assert _evals(fake) == 0


def test_the_try_line_is_choice_one_at_a_terminal(fake, capsys, terminal):
    _new_run(fake.root)
    terminal += ["4"]  # 1 try, 2 ask again, 3 label more, 4 nothing for now
    code, out, _ = run(capsys, fake.root)
    assert code == 0
    assert "  1. Try your new judge on your 36 marked answers" in out
    assert "  4. Nothing for now" in out and _evals(fake) == 0


def test_a_changed_model_offers_it_too(fake, capsys):
    _new_run(fake.root, rubric=RUBRIC, model="openai:gpt-5.4-mini")
    _, out, _ = run(capsys, fake.root)
    assert ("Your judge changed since your last check: the model was openai:gpt-4.1-mini, now "
            "openai:gpt-5.4-mini.") in out
    assert "--try-new-judge" in out


def test_the_same_judge_offers_no_new_judge(fake, capsys):
    _, out, _ = run(capsys, fake.root)
    assert "--try-new-judge" not in out


def test_try_new_judge_without_a_new_judge(fake, capsys):
    code, out, _ = run(capsys, fake.root, "--try-new-judge")
    assert code == 2
    assert ("Your newest results hold the same judge as your last check, so there is no new "
            "judge to try.") in out


def test_a_renamed_judge_asks_whether_it_is_the_new_version(fake, capsys, terminal):
    _new_run(fake.root, metric="tone")
    terminal += ["y", "4"]
    code, out, _ = run(capsys, fake.root)
    assert code == 0
    assert "Is tone the new version of your judge llm-rubric? [Y/n]" in out
    assert "Try your new judge on your 36 marked answers" in out


def test_a_renamed_judge_without_a_terminal_needs_a_flag(fake, capsys):
    _new_run(fake.root, metric="tone")
    code, out, _ = run(capsys, fake.root)
    assert code == 2
    assert ("Is tone the new version of your judge llm-rubric? Run judgekeeper start "
            "--try-new-judge to try it, or judgekeeper start --new to check it as a new judge."
            ) in out
    code, out, _ = run(capsys, fake.root, "--try-new-judge")
    assert "Try your new judge" in out and "36 labeled answers × 1 time = 36 judge calls." in out


def test_a_renamed_judge_said_no_to_points_to_new(fake, capsys, terminal):
    _new_run(fake.root, metric="tone")
    terminal += ["n"]
    code, out, _ = run(capsys, fake.root)
    assert code == 0
    assert "To check these results instead, run judgekeeper start --new" in out


# The plan and the question -----------------------------------------------------------------

def test_the_plan_is_asked_once_by_default_and_no_spends_nothing(fake, capsys, terminal):
    _new_run(fake.root)
    terminal += [""]  # Enter at Go ahead? (No)
    code, out, _ = run(capsys, fake.root, "--try-new-judge")
    assert code == 0
    assert out.count("Try your new judge") >= 1 and "Your judge: llm-rubric" in out
    assert "  36 labeled answers × 1 time = 36 judge calls." in out
    assert "Go ahead? [y/N]" in out
    assert out.rstrip().endswith("Your judge was not called; nothing was spent.")
    assert _evals(fake) == 0 and not list(fake.dir.glob("new-judge-*"))


def test_without_a_terminal_allow_calls_is_needed(fake, capsys):
    _new_run(fake.root)
    code, out, _ = run(capsys, fake.root, "--try-new-judge")
    assert code == 2
    assert ("To go ahead without a terminal: judgekeeper start --try-new-judge --allow-calls 36"
            in out)


def test_the_new_judge_grades_the_old_answers_never_the_new_outputs(fake, capsys):
    _new_run(fake.root)
    run(capsys, fake.root, "--try-new-judge", "--allow-calls", 36)
    tests = fake.fake["fake"].files_seen["tests"]
    old = {a["id"]: a for a in again.labeled_answers(fake)}
    assert {t["description"] for t in tests} == set(old)
    for t in tests:
        assert t["providerOutput"] == old[t["description"]]["output"]  # the old answer
        assert "(v2)" not in t["providerOutput"]
        assert t["assert"] == [{"type": "llm-rubric", "value": NEW_RUBRIC}]  # the new judge


def test_assertions_that_differ_by_test_are_matched_by_vars(fake, capsys):
    rubrics = [f"Rule {i}" for i in range(36)]
    _new_run(fake.root, rubrics=rubrics, drop=2)  # questions 0 and 1 are not in the new run
    _, out, _ = run(capsys, fake.root, "--try-new-judge", "--allow-calls", 34)
    tests = fake.fake["fake"].files_seen["tests"]
    by_question = {t["vars"]["question"]: t["assert"][0]["value"] for t in tests}
    assert by_question[question(5)] == "Rule 5" and question(0) not in by_question
    assert ("2 answers are left out: no test in your newest results matches them." in out)


# The numbers side by side -----------------------------------------------------------------

def _flipped(n_fail_to_pass=4):
    """The new judge passes the first `n_fail_to_pass` answers the old one failed."""
    v = split(20, 16)
    return [True if (not x and i < 20 + n_fail_to_pass) else x for i, x in enumerate(v)]


def test_old_and_new_side_by_side(fake, capsys):
    _new_run(fake.root, verdicts=_flipped(4))
    code, out, _ = run(capsys, fake.root, "--try-new-judge", "--allow-calls", 36)
    assert code == 0
    assert "Your new judge vs your old judge, on your 36 marked answers:" in out
    wrong = next(x for x in out.splitlines() if "you marked Wrong, the judge failed:" in x)
    correct = next(x for x in out.splitlines() if "you marked Correct, the judge passed:" in x)
    # old: the person agreed with every old verdict; new: 4 of the 16 Wrong now pass
    assert "old 100% (" in wrong and "->  new 75% (" in wrong
    assert "old 100% (" in correct and "->  new 100% (" in correct
    assert "100% to 100%" not in out  # a range never collapses to one point
    block = json.loads(fake.result_json.read_text())["new_judge"]
    assert block["new"]["tnr"] == pytest.approx(0.75) and block["new"]["tpr"] == 1.0
    assert block["old"]["source"] == "result"


def test_the_will_look_better_line_is_always_shown(fake, capsys):
    _new_run(fake.root)
    _, out, _ = run(capsys, fake.root, "--try-new-judge", "--allow-calls", 36)
    assert ("You changed your judge after seeing mistakes on these answers, so it will look "
            "better on them.") in out
    assert ("To confirm on new answers, mark 10 Correct and 10 Wrong: judgekeeper start "
            "--try-new-judge") in out  # no terminal: the question as a command


def test_old_numbers_from_asking_again_are_used_and_said(fake, capsys):
    run(capsys, fake.root, "--ask-again", "--allow-calls", 72)  # the old judge, asked again
    r = json.loads(fake.result_json.read_text())
    r["again"]["made_at"] = "2026-10-06T10:00:00Z"
    r["again"]["today"].update(tnr=0.5, tnr_interval=[0.3, 0.7])
    fake.result_json.write_text(json.dumps(r))
    _new_run(fake.root)
    _, out, _ = run(capsys, fake.root, "--try-new-judge", "--allow-calls", 36)
    wrong = next(x for x in out.splitlines() if "you marked Wrong, the judge failed:" in x)
    assert "old 50% (30% to 70%)" in wrong
    assert "The old numbers are from asking your old judge again on 2026-10-06." in out


# What is saved ---------------------------------------------------------------------------

def test_the_new_judge_files(fake, capsys):
    before = json.loads(fake.result_json.read_text())
    labels = fake.labels.read_bytes()
    _new_run(fake.root)
    run(capsys, fake.root, "--try-new-judge", "--allow-calls", 36)
    folder = _folder(fake)
    assert {p.name for p in folder.iterdir()} >= {"new-judge.json", "new-judge-1.jsonl",
                                                 "promptfoo.json"}
    header, records = read_run(folder / "new-judge-1.jsonl")
    assert len(records) == 36 and header["source"]["metric"] == "llm-rubric"
    saved_hash = fake.data()["fingerprint"]["prompt_hash"]
    for rec in records.values():
        fp = rec["fingerprint"]
        assert fp["model"] == "openai:gpt-4.1-mini" and fp["prompt_hash"] != saved_hash
        assert fp["tool"] == "promptfoo" and fp["judge_copy"] == "exact" and fp["created_at"]
    after = json.loads(fake.result_json.read_text())
    for key in ("tpr", "tnr", "kappa", "labels", "made_at"):
        assert after[key] == before[key]  # the main result stays the old judge's
    assert after["new_judge"]["folder"] == f".judgekeeper/{folder.name}"
    assert fake.labels.read_bytes() == labels
    assert "Your new judge" in fake.result_html.read_text()


def test_trying_the_same_new_judge_again_asks_nothing_again(fake, capsys):
    _new_run(fake.root)
    run(capsys, fake.root, "--try-new-judge", "--allow-calls", 36)
    assert _evals(fake) == 1
    code, out, _ = run(capsys, fake.root, "--try-new-judge")
    assert code == 0 and _evals(fake) == 1
    assert "You already tried this judge on" in out
    assert "Your new judge vs your old judge, on your 36 marked answers:" in out


# The confirmation check --------------------------------------------------------------------

def test_the_confirmation_uses_new_answers_and_the_new_judges_groups(fake, capsys, confirmed):
    new = _flipped(4)
    _new_run(fake.root, verdicts=new, same=6)  # 6 answers are unchanged, so already marked
    code, _, _ = run(capsys, fake.root, "--try-new-judge", "--allow-calls", 36, "--yes")
    assert code == 0
    (cws,) = confirmed
    data = cws.data()
    old = {a["id"] for a in again.labeled_answers(fake)}
    queue = {q["id"]: q["group"] for q in data["queue"]}
    assert not set(queue) & old and len(queue) == 30
    pool = [json.loads(x) for x in cws.pool.read_text().splitlines()]
    assert all("(v2)" in p["output"] for p in pool)  # the newest results' new answers
    by_question = {p["id"]: int(p["input"]["question"].split()[1].rstrip("?")) for p in pool}
    assert all(queue[i] == ("pass" if new[by_question[i]] else "fail") for i in queue)
    assert cws.dir == _folder(fake) / "confirm"


def test_the_confirmation_page_aims_at_ten_and_ten(fake, capsys, confirmed):
    _new_run(fake.root)
    run(capsys, fake.root, "--try-new-judge", "--allow-calls", 36, "--yes")
    page = new_judge.confirmation_page(confirmed[0])
    assert "A quick check needs 10 of each." in page and "Quick check ready." in page


def test_the_confirmation_result(fake, capsys, confirmed):
    _new_run(fake.root, verdicts=_flipped(4))  # the new judge: 24 passes, 12 fails

    def labels(items, groups):  # 2 of the new judge's fails are marked Correct
        fails = [i["id"] for i in items if groups[i["id"]] == "fail"]
        return {i["id"]: ("pass" if i["id"] in fails[:2] else groups[i["id"]]) for i in items}

    confirmed.labels = labels
    _, out, _ = run(capsys, fake.root, "--try-new-judge", "--allow-calls", 36, "--yes")
    assert "On 36 new answers you marked (quick check):" in out
    assert "  Of the answers you marked Wrong, your new judge failed about 100% (" in out
    assert "  Of the answers you marked Correct, it passed about 92% (" in out  # 24 of 26
    block = json.loads(fake.result_json.read_text())["new_judge"]["confirmation"]
    assert block["labels"] == {"correct": 26, "wrong": 10} and block["check"] == "quick"
    assert (_folder(fake) / "confirm" / "result.json").is_file()
    assert "On 36 new answers you marked" in fake.result_html.read_text()


def test_fewer_than_ten_of_each_says_the_ranges_are_very_wide(fake, capsys, confirmed):
    _new_run(fake.root, verdicts=_flipped(4))
    confirmed.labels = lambda items, groups: {i["id"]: groups[i["id"]] for i in items[:12]}
    _, out, _ = run(capsys, fake.root, "--try-new-judge", "--allow-calls", 36, "--yes")
    assert "new answers you marked (fewer than 10 Correct or 10 Wrong: the ranges are very " \
           "wide):" in out


def test_no_to_the_confirmation_keeps_the_numbers(fake, capsys, terminal, confirmed):
    _new_run(fake.root)
    terminal += ["y", "n"]  # go ahead; no confirmation
    code, out, _ = run(capsys, fake.root, "--try-new-judge")
    assert code == 0 and confirmed == []
    assert "Mark 10 Correct and 10 Wrong new answers to confirm? [Y/n]" in out
    assert json.loads(fake.result_json.read_text())["new_judge"]["confirmation"] is None


def test_new_makes_the_new_judge_the_one_checked_and_deletes_nothing(fake, capsys, confirmed):
    _new_run(fake.root)
    run(capsys, fake.root, "--try-new-judge", "--allow-calls", 36, "--yes")
    files = sorted(p.relative_to(fake.dir).as_posix() for p in fake.dir.rglob("*")
                   if p.is_file())
    run(capsys, fake.root, "--new")
    (previous,) = fake.dir.glob("previous-*")
    moved = sorted(p.relative_to(previous).as_posix() for p in previous.rglob("*")
                   if p.is_file())
    assert moved == files  # the old marks and the confirmation marks, nothing deleted
    assert any(p.endswith("confirm/labels.csv") for p in moved) and "labels.csv" in moved


# The other tools rebuild the new judge from their newest results ---------------------------

def test_a_judge_command_is_tried_on_the_marked_answers(fake, capsys):
    import sys

    from tests.conftest import FIXTURES

    _new_run(fake.root)
    command = f"{sys.executable} {FIXTURES / 'exec' / 'bare.py'}"
    code, out, _ = run(capsys, fake.root, "--try-new-judge", "--judge-command", command,
                       "--allow-calls", 36)
    assert code == 0 and f"This runs `{command}` 36 times." in out
    assert "Your new judge vs your old judge" in out and _evals(fake) == 0


def test_the_view_shows_the_newest_results(fake):
    _new_run(fake.root, metric="tone")
    found = start.find_judge(fake.root)
    view = new_judge.View(fake, found)
    data = view.data()
    assert data["metric"] == "tone" and data["results_files"] == ["results.json"]
    assert data["fingerprint"] == found.fingerprint and view.root == fake.root
    assert Workspace(fake.root).data()["metric"] == "llm-rubric"  # the saved check is untouched
