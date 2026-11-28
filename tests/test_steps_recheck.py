"""`judgekeeper steps` again after a change: what changed since the last check on the same
marks, the Next line once every run is marked, "picks" in every line, and marks that a program
may have made, said as on the answers page. Synthetic data only; no test calls an AI."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from judgekeeper import steps
from tests.test_steps import people_first, reviewer_first
from tests.test_steps_marks import (
    MARKS,
    hashes_of,
    mark,
    marked_project,
    result,
    write_marks,
    write_runs,
)

SINCE = "Since the last check, on the same marks:"
CHANCE = "  A change smaller than the ranges above could be chance."
CHANGED = "Your marks changed since the last check, so these numbers are not compared with it."


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def write_picks(here: Path, name: str, pick, model="reviewer-a", n=40) -> Path:
    path = here / name
    path.write_text("".join(json.dumps({"id": f"r{i}", "first_wrong_step": pick(i),
                                        "model": model}) + "\n" for i in range(n)),
                    encoding="utf-8")
    return path


def better(i):
    """The first picks, with three more runs that went wrong caught and four more steps right."""
    if 20 <= i < 23:
        return people_first(i)
    if 34 <= i < 38:
        return people_first(i)
    return reviewer_first(i)


def lines_for(here: Path, picks: str, runs: Path | None = None) -> list[str]:
    lines, _ = steps.numbers_from_marks(runs or here / "runs.jsonl", here / MARKS, here / picks)
    return lines


def block(lines: list[str]) -> list[str]:
    at = lines.index(SINCE) if SINCE in lines else next(
        k for k, x in enumerate(lines) if x.startswith("Since the last check"))
    end = next((k for k in range(at + 1, len(lines)) if not lines[k].startswith("  ")),
               len(lines))
    return lines[at:end]


# Item 1: what changed since the last check -------------------------------------------------

def test_a_second_check_on_the_same_marks_says_old_and_new(here):
    marked_project(here)
    first = lines_for(here, "g.jsonl")
    assert not any(x.startswith("Since the last check") for x in first)
    write_picks(here, "new.jsonl", better)
    again = lines_for(here, "new.jsonl")
    assert block(again) == [
        SINCE,
        "  Runs you say went wrong, caught: 75% (15 of 20) -> 90% (18 of 20).",
        "  Runs you say were fine, left alone: 80% (16 of 20) -> 80% (16 of 20).",
        "  Kappa: 0.55 -> 0.70.",
        "  The same first wrong step: 60% (9 of 15) -> 89% (16 of 18).",
        CHANCE,
    ]
    assert again.index(SINCE) < again.index("Saved in .judgekeeper/steps/result.json.")


def test_the_earlier_numbers_are_kept_under_before_with_no_step_text(here):
    marked_project(here)
    lines_for(here, "g.jsonl")
    first = result(here)
    write_picks(here, "new.jsonl", better)
    lines_for(here, "new.jsonl")
    saved = result(here)
    before = saved["before"]
    assert set(before) == {"made_at", "marks_hash", "reviewers"}
    assert before["marks_hash"] == first["people"]["marks_hash"] == saved["people"]["marks_hash"]
    old = first["reviewers"][0]
    assert before["reviewers"] == [{"name": "reviewer-a", "model": "reviewer-a",
                                    "runs_compared": old["runs_compared"],
                                    "run_level": old["run_level"],
                                    "step_level": old["step_level"],
                                    "marks_hash": first["people"]["marks_hash"],
                                    "made_at": first["made_at"]}]
    assert "made up step" not in json.dumps(saved)


def test_looking_again_with_nothing_changed_keeps_the_comparison(here):
    """The result page works the numbers out again on every view: that must not lose them."""
    marked_project(here)
    lines_for(here, "g.jsonl")
    write_picks(here, "new.jsonl", better)
    shown = block(lines_for(here, "new.jsonl"))
    before = result(here)["before"]
    assert block(lines_for(here, "new.jsonl")) == shown
    assert result(here)["before"] == before


def test_the_result_page_twice_then_the_terminal_still_compare_with_the_earlier(here, capsys):
    from judgekeeper import steps_page
    from judgekeeper.start_label import Workspace

    marked_project(here)
    lines_for(here, "g.jsonl")
    write_picks(here, "new.jsonl", better)
    session = steps_page.StepsSession(Workspace(here), here / "runs.jsonl",
                                      reviewer=str(here / "new.jsonl"), shown="runs.jsonl")
    for _ in range(2):
        page = steps_page.result_page(session, "/")
        assert "Runs you say went wrong, caught: 75% (15 of 20) -&gt; 90% (18 of 20)." in page
    steps.say_numbers_from_marks(here / "runs.jsonl", "runs.jsonl", "new.jsonl")
    out = " ".join(capsys.readouterr().out.split())
    assert "Runs you say went wrong, caught: 75% (15 of 20) -> 90% (18 of 20)." in out


def test_the_same_numbers_again_add_no_block(here):
    """Nothing changed since the last check: no block, and `before` stays as it was."""
    marked_project(here)
    lines_for(here, "g.jsonl")
    write_picks(here, "copy.jsonl", reviewer_first)
    assert not any(x.startswith("Since the last check") for x in lines_for(here, "copy.jsonl"))
    assert "before" not in result(here) and "marks_hash" in result(here)["people"]


def test_no_chance_line_when_no_number_changed():
    w = {"p": 0.8, "k": 16, "n": 20, "lo": 0.58, "hi": 0.92}
    entry = {"name": "a", "run_level": {"tpr": w, "tnr": w, "kappa": 0.5},
             "step_level": {"same": None}}
    said = steps._since_lines(entry, dict(entry), marks=True)
    assert said == [SINCE, "  Runs you say went wrong, caught: 80% (16 of 20) -> 80% (16 of 20).",
                    "  Runs you say were fine, left alone: 80% (16 of 20) -> 80% (16 of 20).",
                    "  Kappa: 0.50 -> 0.50."]


def test_marks_changed_since_says_one_line_and_no_numbers(here):
    runs = marked_project(here)
    lines_for(here, "g.jsonl")
    hashes = hashes_of(runs)
    marks = (here / MARKS).read_text(encoding="utf-8")
    (here / MARKS).write_text(marks + json.dumps(mark("r3", 2, hashes)) + "\n", encoding="utf-8")
    write_picks(here, "new.jsonl", better)
    lines = lines_for(here, "new.jsonl")
    assert CHANGED in lines and lines.count(CHANGED) == 1
    assert not any(x.startswith("Since the last check") for x in lines)
    assert lines.index(CHANGED) < lines.index("Saved in .judgekeeper/steps/result.json.")


def test_a_new_name_is_compared_with_the_one_before(here):
    marked_project(here)
    lines_for(here, "g.jsonl")
    write_picks(here, "new.jsonl", better, model="reviewer-b")
    assert block(lines_for(here, "new.jsonl"))[0] == (
        'Since the last check (then "reviewer-a"), on the same marks:')


def test_a_name_from_none_says_no_model_name(here):
    marked_project(here)
    write_picks(here, "plain.jsonl", reviewer_first, model=None)
    lines_for(here, "plain.jsonl")
    write_picks(here, "new.jsonl", better, model="reviewer-b")
    assert block(lines_for(here, "new.jsonl"))[0] == (
        "Since the last check (then with no model name), on the same marks:")


def test_too_few_before_shows_too_few(here):
    marked_project(here)
    write_picks(here, "few.jsonl", reviewer_first, n=25)  # 5 runs that went wrong have a pick
    lines_for(here, "few.jsonl")
    said = block(lines_for(here, "g.jsonl"))
    assert "  Runs you say went wrong, caught: too few -> 75% (15 of 20)." in said
    assert "  Runs you say were fine, left alone: 80% (16 of 20) -> 80% (16 of 20)." in said
    assert "  The same first wrong step: too few -> 60% (9 of 15)." in said


def test_a_run_with_no_picks_carries_the_last_numbers_on(here):
    marked_project(here)
    lines_for(here, "g.jsonl")
    steps.numbers_from_marks(here / "runs.jsonl", here / MARKS, None)
    write_picks(here, "new.jsonl", better)
    assert block(lines_for(here, "new.jsonl"))[0] == SINCE


def test_a_result_with_no_hash_is_not_compared(here):
    marked_project(here)
    lines_for(here, "g.jsonl")
    saved = result(here)
    del saved["people"]["marks_hash"]
    (here / ".judgekeeper/steps/result.json").write_text(json.dumps(saved), encoding="utf-8")
    write_picks(here, "new.jsonl", better)
    lines = lines_for(here, "new.jsonl")
    assert not any(x.startswith("Since the last check") for x in lines) and CHANGED not in lines
    (here / ".judgekeeper/steps/result.json").write_text("{not json", encoding="utf-8")
    lines = lines_for(here, "g.jsonl")
    assert not any(x.startswith("Since the last check") for x in lines)
    assert "marks_hash" in result(here)["people"]


def test_an_export_says_the_people_marking_and_the_same_labels(here, capsys):
    from judgekeeper.cli import main
    from tests.test_steps import project, save

    export = save(here, project())
    main(["steps", str(export), "--reviewer", str(write_picks(here, "g.jsonl", reviewer_first))])
    capsys.readouterr()
    main(["steps", str(export), "--reviewer", str(write_picks(here, "new.jsonl", better))])
    out = capsys.readouterr().out
    assert "Since the last check, on the same labels:" in out
    assert "  Runs the people marking say went wrong, caught: " in out


# Item 2: the Next line once every run is marked -------------------------------------------

def test_every_run_marked_and_too_few_says_add_runs_of_that_kind(here):
    marked_project(here, n=10)  # 10 runs, all fine
    lines, _ = steps.numbers_from_marks(here / "runs.jsonl", here / MARKS, here / "g.jsonl")
    assert lines[-1] == ("Next: every run is marked, so add runs to runs.jsonl: at least 15 more "
                         "that went wrong and 5 more that were fine (each number needs 15 runs "
                         "of its kind). Then mark them on the page: `judgekeeper steps runs.jsonl "
                         "--reviewer g.jsonl`.")
    rows = (here / "runs.jsonl").read_text(encoding="utf-8")
    (here / "runs.jsonl").write_text(rows + rows.splitlines()[0].replace('"r0"', '"r10"') + "\n",
                                     encoding="utf-8")  # one run not marked yet
    lines, _ = steps.numbers_from_marks(here / "runs.jsonl", here / MARKS, here / "g.jsonl")
    assert lines[-1] == ("Next: mark more runs on the page: "
                         "`judgekeeper steps runs.jsonl --reviewer g.jsonl`.")


def test_one_kind_short_names_only_that_kind(here):
    runs = write_runs(here, 32)
    hashes = hashes_of(runs)
    write_marks(here, [mark(f"r{i}", 0 if i < 12 else 2, hashes) for i in range(32)])
    write_picks(here, "g.jsonl", lambda i: 0 if i < 12 else 2, n=32)
    lines, _ = steps.numbers_from_marks(runs, here / MARKS, here / "g.jsonl")
    assert lines[-1].startswith("Next: every run is marked, so add runs to runs.jsonl: at least "
                                "3 more that were fine (each number needs 15 runs of its kind).")


def test_every_run_marked_with_picks_left_out_says_fix_the_picks(here):
    marked_project(here, n=10)
    write_picks(here, "g.jsonl", lambda i: 99 if i == 2 else 0, n=8)  # 2 with none, 1 not a step
    lines, _ = steps.numbers_from_marks(here / "runs.jsonl", here / MARKS, here / "g.jsonl")
    assert lines[-1] == ("Next: some runs have no pick from your agent-as-a-judge, or a pick that "
                         "is not a step of the run: fix them in g.jsonl and run `judgekeeper "
                         "steps runs.jsonl --reviewer g.jsonl`.")


@pytest.mark.parametrize("picks", ["all", "left_out"])
def test_both_new_next_lines_use_the_start_command_under_uvx(here, monkeypatch, picks):
    from judgekeeper import textio

    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    monkeypatch.setattr(textio, "started_by_uvx", lambda: True)
    marked_project(here, n=10)
    if picks == "left_out":
        write_picks(here, "g.jsonl", lambda i: 0, n=8)
    lines, _ = steps.numbers_from_marks(here / "runs.jsonl", here / MARKS, here / "g.jsonl")
    start = ("Next: some runs have no pick" if picks == "left_out"
             else "Next: every run is marked, so add runs")
    assert lines[-1].startswith(start)
    assert lines[-1].endswith(f"`{textio.program('steps runs.jsonl --reviewer g.jsonl')}`.")
    assert "`uvx " in lines[-1]


# Item 3: "picks" in every line ---------------------------------------------------------------

def test_no_line_says_guess(here):
    marked_project(here)
    write_picks(here, "g.jsonl", lambda i: 99 if i == 3 else reviewer_first(i))
    kept = [x for x in (here / "g.jsonl").read_text(encoding="utf-8").splitlines()
            if '"r1"' not in x]  # a fine run with no pick
    with_extra = "".join(x + "\n" for x in kept) + "".join(
        json.dumps({"id": f"gone{k}", "first_wrong_step": 1, "model": "reviewer-a"}) + "\n"
        for k in range(2))
    (here / "g.jsonl").write_text(with_extra, encoding="utf-8")
    lines = lines_for(here, "g.jsonl")
    assert "  Left out: 1 with no pick from this agent-as-a-judge, 1 with a pick that is not a " \
           "step of the run." in lines
    assert "  Left out: 2 picks are for runs that are not in runs.jsonl." in lines
    assert lines[-1] == ("Next: change your agent-as-a-judge, save its new picks as a JSONL file "
                         "and run `judgekeeper steps runs.jsonl --reviewer NEW-PICKS.jsonl`.")
    none, _ = steps.numbers_from_marks(here / "runs.jsonl", here / MARKS, None)
    assert "There are no agent-as-a-judge picks to compare your marks with yet." in none
    assert none[-1].endswith("`judgekeeper steps runs.jsonl --reviewer PICKS.jsonl`.")
    with pytest.raises(steps.StepsError, match=r"in the picks \(found: reviewer-a\)"):
        steps.numbers_from_marks(here / "runs.jsonl", here / MARKS, here / "g.jsonl", "nope")
    assert not any("guess" in x.lower() for x in lines + none)


def test_one_pick_for_a_run_not_in_the_runs(here):
    marked_project(here)
    (here / "g.jsonl").write_text((here / "g.jsonl").read_text(encoding="utf-8") + json.dumps(
        {"id": "gone", "first_wrong_step": 1, "model": "reviewer-a"}) + "\n", encoding="utf-8")
    assert "  Left out: 1 pick is for a run that is not in runs.jsonl." in lines_for(here, "g.jsonl")


# Item 6: marks a program may have made --------------------------------------------------------

def fast_project(here: Path, seconds=0.3, link=None, n_fast=40):
    runs = write_runs(here, 40)
    hashes = hashes_of(runs)
    more = {"link": link} if link else {}
    write_marks(here, [mark(f"r{i}", people_first(i), hashes,
                            **({"seconds": seconds, **more} if i < n_fast else {}))
                       for i in range(40)])
    write_picks(here, "g.jsonl", reviewer_first)
    return runs


QUICK = ("40 of your marks took under a second each. That is faster than a person reads, so a "
         "program may have made them.")
PRINTED = ("40 of your marks came through a link judgekeeper printed. That's expected if you "
           "opened it yourself.")


def test_marks_under_a_second_are_said_as_on_the_answers_page(here):
    fast_project(here)
    lines = lines_for(here, "g.jsonl")
    assert QUICK in lines
    assert lines.index(QUICK) == 1  # right after "Read 40 runs ..."
    assert result(here)["people"]["under_second"] == 40


def test_a_quarter_under_a_second_says_the_count_only(here):
    fast_project(here, n_fast=12)
    assert "12 of your marks took under a second each." in lines_for(here, "g.jsonl")
    fast_project(here, n_fast=10)
    assert not any("under a second" in x for x in lines_for(here, "g.jsonl"))
    assert result(here)["people"]["under_second"] == 10


def test_printed_and_browser_env_links_are_counted_and_said_on_the_page(here):
    fast_project(here, seconds=4.5, link="printed")
    lines = lines_for(here, "g.jsonl")  # what the result page shows: always
    assert PRINTED in lines
    assert lines_for(here, "g.jsonl").count(PRINTED) == 1
    saved = result(here)["people"]
    assert (saved["printed"], saved["browser_env"]) == (40, 0)
    fast_project(here, seconds=4.5, link="browser-env")
    assert ("40 of your marks came through a page opened by the program named in BROWSER, so a "
            "program could have made them. If you marked them yourself, you can ignore this."
            ) in lines_for(here, "g.jsonl")


def test_the_terminal_says_the_link_line_once_until_the_count_changes(here, capsys):
    fast_project(here, seconds=4.5, link="printed")
    assert steps.say_numbers_from_marks(here / "runs.jsonl", "runs.jsonl", "g.jsonl") == 0
    assert PRINTED in capsys.readouterr().out.replace("\n", " ")
    steps.say_numbers_from_marks(here / "runs.jsonl", "runs.jsonl", "g.jsonl")
    assert "came through a link" not in capsys.readouterr().out
    assert (here / ".judgekeeper/steps/link-said.json").is_file()
    marks = (here / MARKS).read_text(encoding="utf-8").splitlines()
    (here / MARKS).write_text("\n".join(marks[:-1]) + "\n", encoding="utf-8")  # 39 now
    steps.say_numbers_from_marks(here / "runs.jsonl", "runs.jsonl", "g.jsonl")
    assert "39 of your marks came through a link" in capsys.readouterr().out.replace("\n", " ")


def test_only_the_marks_that_count_are_counted(here):
    runs = write_runs(here, 40)
    hashes = hashes_of(runs)
    fast = {"seconds": 0.2, "link": "printed"}
    write_marks(here, [mark("r0", 1, hashes, **fast), mark("r0", 2, hashes),  # newest is slow
                       mark("r1", 1, {}, **fast),  # steps changed since
                       *[mark(f"r{i}", people_first(i), hashes) for i in range(2, 40)]])
    write_picks(here, "g.jsonl", reviewer_first)
    lines_for(here, "g.jsonl")
    saved = result(here)["people"]
    assert (saved["under_second"], saved["printed"], saved["browser_env"]) == (0, 0, 0)


# Each agent-as-a-judge is compared only with its own earlier numbers -------------------------

def write_judges(here: Path, name: str, **picks) -> Path:
    """One picks file holding several agent-as-a-judges: model name -> its pick for run i."""
    path = here / name
    path.write_text("".join(json.dumps({"id": f"r{i}", "first_wrong_step": pick(i),
                                        "model": model}) + "\n"
                            for model, pick in picks.items() for i in range(40)),
                    encoding="utf-8")
    return path


def model_lines(here: Path, picks: str, model: str | None = None) -> list[str]:
    lines, _ = steps.numbers_from_marks(here / "runs.jsonl", here / MARKS, here / picks, model)
    return lines


def since(lines: list[str]) -> list[str]:
    return [x for x in lines if x.startswith("Since the last check") or x == CHANGED]


BETTER = [SINCE,
          "  Runs you say went wrong, caught: 75% (15 of 20) -> 90% (18 of 20).",
          "  Runs you say were fine, left alone: 80% (16 of 20) -> 80% (16 of 20).",
          "  Kappa: 0.55 -> 0.70.",
          "  The same first wrong step: 60% (9 of 15) -> 89% (16 of 18).",
          CHANCE]


def test_two_judges_of_one_picks_file_are_never_compared_with_each_other(here):
    marked_project(here)
    write_judges(here, "two.jsonl", **{"judge-A": reviewer_first, "judge-B": lambda i: 0})
    model_lines(here, "two.jsonl", "judge-B")
    assert since(model_lines(here, "two.jsonl", "judge-A")) == []


def test_a_judge_is_compared_with_its_own_numbers_after_another_was_checked(here):
    marked_project(here)
    write_judges(here, "two.jsonl", **{"judge-A": reviewer_first, "judge-B": lambda i: 0})
    model_lines(here, "two.jsonl", "judge-A")
    assert since(model_lines(here, "two.jsonl", "judge-B")) == []
    write_judges(here, "two.jsonl", **{"judge-A": better, "judge-B": lambda i: 0})
    assert block(model_lines(here, "two.jsonl", "judge-A")) == BETTER


def test_an_earlier_name_still_in_the_picks_is_not_taken_for_a_rename(here):
    marked_project(here)
    lines_for(here, "g.jsonl")  # reviewer-a
    write_judges(here, "two.jsonl", **{"reviewer-a": reviewer_first, "reviewer-b": better})
    assert since(model_lines(here, "two.jsonl", "reviewer-b")) == []


def test_both_judges_at_once_are_each_compared_with_their_own(here):
    marked_project(here)
    write_judges(here, "two.jsonl", **{"judge-A": reviewer_first, "judge-B": better})
    model_lines(here, "two.jsonl", "judge-B")
    assert since(model_lines(here, "two.jsonl")) == []  # none for A; B the same as before
    write_judges(here, "two.jsonl", **{"judge-A": better, "judge-B": reviewer_first})
    lines = model_lines(here, "two.jsonl")
    assert since(lines) == [SINCE, SINCE]
    caught = [x for x in lines if x.startswith("  Runs you say went wrong, caught:")]
    assert caught == ["  Runs you say went wrong, caught: 75% (15 of 20) -> 90% (18 of 20).",
                      "  Runs you say went wrong, caught: 90% (18 of 20) -> 75% (15 of 20)."]


def test_before_keeps_each_judge_with_the_marks_it_was_checked_on(here):
    marked_project(here)
    write_judges(here, "two.jsonl", **{"judge-A": reviewer_first, "judge-B": lambda i: 0})
    model_lines(here, "two.jsonl", "judge-B")
    model_lines(here, "two.jsonl", "judge-A")
    before = result(here)["before"]
    assert [r["name"] for r in before["reviewers"]] == ["judge-B"]
    write_judges(here, "two.jsonl", **{"judge-A": better, "judge-B": lambda i: 0})
    model_lines(here, "two.jsonl", "judge-A")
    kept = result(here)["before"]["reviewers"]
    assert sorted(r["name"] for r in kept) == ["judge-A", "judge-B"]
    marks_hash = result(here)["people"]["marks_hash"]
    assert all(r["marks_hash"] == marks_hash and r["made_at"] for r in kept)
