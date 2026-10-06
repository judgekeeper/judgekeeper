"""Running `judgekeeper start` again: what is saved in `.judgekeeper/` decides what happens.

| saved                                   | start                                              |
|-----------------------------------------|----------------------------------------------------|
| nothing                                 | the full flow                                      |
| labeling not finished, no result        | "Continue?", then the page at the next answer      |
| a result, the same results              | the menu: review, label more, or nothing           |
| a result, newer results, same judge name| a re-check: the saved labels against new verdicts  |
| anything, with --new                    | moves it all to previous-<date>/ and starts fresh  |

No test opens a page: serving is replaced with a recorder.
"""

from __future__ import annotations

import builtins
import json

import pytest

from judgekeeper import start, start_label
from judgekeeper.cli import main
from judgekeeper.start_label import StartSession, Workspace, save_result
from tests.start_projects import promptfoo_data, promptfoo_project, split


def _quiet(line=""):
    pass


def _checked(root, n_pass=20, n_fail=16, labeled=None, result=True, **kwargs):
    """A project with promptfoo results and a check in `.judgekeeper/`: the first `labeled`
    answers (all when None) labeled the way the judge saw them, and a result unless not."""
    promptfoo_project(root, split(n_pass, n_fail), **kwargs)
    ws = start_label.prepare(start.find_judge(root), say=_quiet)
    groups = {q["id"]: q["group"] for q in ws.data()["queue"]}
    session = StartSession(ws)
    for item in session.items[:labeled]:
        session.update({"id": item["id"], "label": groups[item["id"]]})
    if result:
        save_result(ws, session, say=_quiet)
    return ws


@pytest.fixture
def served(monkeypatch):
    """Serving the page is replaced: the workspaces it would have served are kept."""
    calls = []

    def serve(ws, port, open_browser, say):
        calls.append(ws)
        say("(labeling page)")
        return 0

    monkeypatch.setattr(start_label, "serve_workspace", serve)
    return calls


@pytest.fixture
def terminal(monkeypatch):
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


def _rewrite(root, verdicts, created="2026-10-09T09:00:00Z", **kwargs):
    """New promptfoo results in the same file, as after the next eval run."""
    data = promptfoo_data(verdicts, created=created, **kwargs)
    (root / "results.json").write_text(json.dumps(data), encoding="utf-8")


# Labeling not finished -------------------------------------------------------------------

def test_unfinished_labeling_asks_to_continue_and_reopens_the_page(tmp_path, capsys, served,
                                                                   terminal):
    ws = _checked(tmp_path, labeled=3, result=False)
    first = [q["group"] for q in ws.data()["queue"][:3]]
    code, out, _ = run(capsys, tmp_path)
    assert code == 0
    assert (f"You labeled 3 (Correct {first.count('pass')}, Wrong {first.count('fail')}). "
            "Continue? [Y/n]") in out
    assert [w.dir for w in served] == [ws.dir]
    assert "Looking in" not in out  # the saved pool is used as it is


def test_no_to_continue_says_how_to_start_over(tmp_path, capsys, served, terminal):
    _checked(tmp_path, labeled=3, result=False)
    terminal.append("n")
    code, out, _ = run(capsys, tmp_path)
    assert code == 0 and served == []
    assert "To start over: judgekeeper start --new" in out


def test_continue_without_a_terminal_needs_yes(tmp_path, capsys, served):
    _checked(tmp_path, labeled=3, result=False)
    code, out, _ = run(capsys, tmp_path)
    assert code == 2 and served == []
    assert "Continue labeling? Run judgekeeper start --yes to continue" in out
    code, out, _ = run(capsys, tmp_path, "--yes")
    assert code == 0 and len(served) == 1


# A result, and the same results ----------------------------------------------------------

def test_the_same_results_offer_to_label_more(tmp_path, capsys, served, terminal):
    ws = _checked(tmp_path, labeled=20)
    made = json.loads(ws.result_json.read_text())["made_at"][:10]
    queue = ws.data()["queue"]
    terminal.append("2")
    code, out, _ = run(capsys, tmp_path)
    assert code == 0
    assert "Your eval tool: promptfoo (results.json" in out
    labels = [q["group"] for q in queue[:20]]
    assert (f"Your last result ({made}): too few labels ({labels.count('pass')} Correct, "
            f"{labels.count('fail')} Wrong).") in out
    assert "  1. Ask your judge again about your 20 labeled answers" in out
    assert "  2. Label more" in out
    assert len(served) == 1 and ws.data()["queue"] == queue


def test_the_same_results_say_how_far_the_last_result_got(tmp_path, capsys, served, terminal):
    _checked(tmp_path, n_pass=20, n_fail=16)
    terminal.append("3")
    code, out, _ = run(capsys, tmp_path)
    assert code == 0
    assert "): rough check (20 Correct, 16 Wrong)." in out


def test_nothing_for_now_stops(tmp_path, capsys, served, terminal):
    _checked(tmp_path)
    terminal.append("3")
    code, out, _ = run(capsys, tmp_path)
    assert code == 0 and served == []
    assert "  3. Nothing for now" in out


# Re-check --------------------------------------------------------------------------------

def test_newer_results_are_rechecked_with_the_saved_labels(tmp_path, capsys, served):
    ws = _checked(tmp_path, n_pass=20, n_fail=16)
    before = json.loads(ws.result_json.read_text())
    # The next eval run: the same 36 answers, but the judge now fails 4 it passed.
    _rewrite(tmp_path, split(16, 20))
    code, out, _ = run(capsys, tmp_path)
    assert code == 0 and served == []
    assert "36 of your 36 labeled answers are in your latest results (2026-10-09)." in out
    # All 36 are labeled, so the corrected rates are the plain ones: of the 20 marked
    # Correct the judge now passes 16 (80%); of the 16 marked Wrong it fails all 16.
    assert ("Of the answers you marked Correct, your judge passed about 100% before and about "
            "80% now.") in out
    assert ("Of the answers you marked Wrong, your judge failed about 100% before and about "
            "100% now.") in out
    after = json.loads(ws.result_json.read_text())
    assert after["tpr"] == pytest.approx(0.8) and after["groups"]["pass"]["pool"] == 16
    history = sorted(ws.history.glob("result-*.json"))
    assert [json.loads(h.read_text())["made_at"] for h in history] == [before["made_at"]]
    assert "changed since your last check" not in out


def test_a_recheck_keeps_the_old_check_and_carries_the_labels(tmp_path, capsys, served):
    ws = _checked(tmp_path, n_pass=20, n_fail=16)
    old_labels = ws.labels.read_text()
    _rewrite(tmp_path, split(16, 20))
    run(capsys, tmp_path)
    (archive,) = ws.history.glob("check-*")
    assert (archive / "labels.csv").read_text() == old_labels
    assert (archive / "start.json").is_file() and (archive / "pool-judge.jsonl").is_file()
    session = StartSession(ws)
    assert session.counts() == {"correct": 20, "wrong": 16, "skipped": 0}
    assert ws.data()["pool"] == {"answers": 36, "pass": 16, "fail": 20}


def test_a_changed_judge_is_said_first_then_offered_to_try(tmp_path, capsys, served):
    _checked(tmp_path, n_pass=20, n_fail=16)
    _rewrite(tmp_path, split(20, 16), model="openai:gpt-5.4-mini")
    code, out, _ = run(capsys, tmp_path)
    assert code == 2  # no terminal: the menu as flags
    line = ("Your judge changed since your last check: the model was openai:gpt-4.1-mini, now "
            "openai:gpt-5.4-mini.")
    assert line in out
    assert out.index(line) < out.index("--try-new-judge")
    assert "Of the answers you marked Correct" not in out  # no re-check with a changed judge


def test_a_changed_prompt_is_said_too(tmp_path, capsys, served):
    _checked(tmp_path, n_pass=20, n_fail=16)
    _rewrite(tmp_path, split(20, 16), rubric="Is polite, correct and short.")
    code, out, _ = run(capsys, tmp_path)
    assert code == 2
    assert "Your judge changed since your last check: the prompt changed." in out
    assert "Try your new judge on your 36 marked answers" in out


def test_changed_answers_offer_to_label_the_latest_results(tmp_path, capsys, served, terminal):
    ws = _checked(tmp_path, n_pass=20, n_fail=16)
    old = {p.name: p.read_bytes() for p in ws.dir.iterdir() if p.is_file()}
    _rewrite(tmp_path, split(20, 16), tag=" (new wording)")  # every answer is new text
    code, out, _ = run(capsys, tmp_path)
    assert code == 0
    assert "0 of your 36 labeled answers are in your latest results (2026-10-09)." in out
    assert ("your app gives different answers now, so the old labels do not apply to them."
            in out)
    assert "Label your latest results? [Y/n]" in out
    (previous,) = ws.dir.glob("previous-*")
    assert {p.name: p.read_bytes() for p in previous.iterdir() if p.is_file()} == old
    assert len(served) == 1
    assert ws.data()["pool"]["answers"] == 36 and not ws.result_json.exists()


def test_changed_answers_without_a_terminal_need_yes(tmp_path, capsys, served):
    _checked(tmp_path, n_pass=20, n_fail=16)
    _rewrite(tmp_path, split(20, 16), tag=" (new wording)")
    code, out, _ = run(capsys, tmp_path)
    assert code == 2 and served == []
    assert "Label your latest results? Run judgekeeper start --yes to label them." in out


def test_results_from_another_tool_point_to_new(tmp_path, capsys, served):
    from tests.start_projects import table_project

    _checked(tmp_path, n_pass=20, n_fail=16)
    (tmp_path / "results.json").unlink()
    (tmp_path / "promptfooconfig.yaml").unlink()
    table_project(tmp_path, split(20, 16))
    code, out, _ = run(capsys, tmp_path)
    assert code == 0 and served == []
    assert "Your last check was of the judge llm-rubric" in out
    assert "To check these results instead, run judgekeeper start --new" in out


def test_a_renamed_judge_is_asked_about(tmp_path, capsys, served):
    _checked(tmp_path, n_pass=20, n_fail=16)
    _rewrite(tmp_path, split(20, 16), metric="tone")
    code, out, _ = run(capsys, tmp_path)
    assert code == 2 and served == []
    assert "Is tone the new version of your judge llm-rubric?" in out


# --new -----------------------------------------------------------------------------------

def test_new_moves_everything_but_the_baseline_and_deletes_nothing(tmp_path, capsys, served):
    ws = _checked(tmp_path, n_pass=20, n_fail=16)
    (ws.dir / "baseline.json").write_text("{}")
    before = {p.relative_to(ws.dir).as_posix(): p.read_bytes()
              for p in ws.dir.rglob("*") if p.is_file()}
    code, out, _ = run(capsys, tmp_path, "--new", "--yes")
    assert code == 0
    (previous,) = ws.dir.glob("previous-*")
    moved = {p.relative_to(previous).as_posix(): p.read_bytes()
             for p in previous.rglob("*") if p.is_file()}
    assert moved == {k: v for k, v in before.items() if k != "baseline.json"}
    assert (ws.dir / "baseline.json").read_text() == "{}"
    assert f"Moved your last check to .judgekeeper/{previous.name}/. Nothing was deleted." in out
    assert "36 answers with a verdict" in out and len(served) == 1


def test_new_twice_keeps_both_earlier_checks(tmp_path, capsys, served, monkeypatch):
    _checked(tmp_path, n_pass=20, n_fail=16)
    stamps = iter(["2026-10-05T10-00-00Z", "2026-10-06T10-00-00Z"])
    monkeypatch.setattr("judgekeeper.start_again._stamp", lambda: next(stamps))
    run(capsys, tmp_path, "--new", "--yes")
    run(capsys, tmp_path, "--new", "--yes")
    names = sorted(p.name for p in Workspace(tmp_path).dir.glob("previous-*"))
    assert names == ["previous-2026-10-05T10-00-00Z", "previous-2026-10-06T10-00-00Z"]


def test_new_with_nothing_saved_is_the_full_flow(tmp_path, capsys, served):
    promptfoo_project(tmp_path, split(20, 16))
    code, out, _ = run(capsys, tmp_path, "--new", "--yes")
    assert code == 0 and "Moved" not in out and len(served) == 1
