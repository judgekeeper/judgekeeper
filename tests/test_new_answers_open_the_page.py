"""After a change, a plain run opens the marking page for the new answers, also with more than
enough marks kept for a result (with the page open from before or closed), and measures once
they are marked."""

from __future__ import annotations

from judgekeeper import background, start_label
from judgekeeper.label import is_open
from tests.test_fixed_and_broke import Project, _mark, _write, here, project  # noqa: F401

MARK = "Step 2 of 5: Mark"
FOUND = "Found 3 new answers since your last results. Mark them to see what changed."
NEXT = "Next: mark more answers, then run `judgekeeper --no-browser` to see your updated result."


def _change(p: Project, n: int = 3) -> None:
    p.round += 1
    for i in range(n):
        p.outs[i] = f"Answer {i}, take {p.round + 1}."
    _write(p.here, p.outs)


def _opens_the_page(said: str, started: list, before: int) -> None:
    assert MARK in said and FOUND in said, said
    assert "You passed" not in said and "Step 3 of 5" not in said, said
    assert "judgekeeper mark" not in said, said  # no extra command to open it
    assert said.index(FOUND) < said.index(NEXT), said
    assert len(started) == before + 1, started  # the page started for the new answers


def test_new_answers_open_the_page_when_it_is_still_open(project, pages):  # noqa: F811
    started, _ = pages
    project.first(fails={0, 1, 2}, n=20)
    assert is_open(start_label.Workspace(project.here).dir)
    before = len(started)
    _change(project)
    _opens_the_page(project.run(), started, before)


def test_new_answers_open_the_page_when_it_was_closed(project, pages):  # noqa: F811
    started, _ = pages
    project.first(fails={0, 1, 2}, n=20)
    background.stop(start_label.Workspace(project.here).dir)
    before = len(started)
    _change(project)
    _opens_the_page(project.run(), started, before)


def test_the_page_opens_again_until_the_new_answers_are_marked(project):  # noqa: F811
    project.first(fails={0, 1, 2}, n=20)
    _change(project)
    project.run()
    background.stop(start_label.Workspace(project.here).dir)
    said = project.run()  # none of them marked yet
    assert MARK in said and "3 new answers are waiting to be marked." in said, said
    _mark(project.here, {i: "pass" for i in range(3)})
    said = project.run()
    assert "Step 3 of 5: Measure" in said and "You passed" in said, said


CLOSED = ("The marking page that was open is closed now: it showed your answers from before. "
          "To open it again, run `judgekeeper mark --no-browser`.")


def test_a_run_that_closes_the_page_and_measures_says_so(project):  # noqa: F811
    project.first(fails={0, 1, 2}, n=20)
    ws = start_label.Workspace(project.here)
    assert is_open(ws.dir)
    del project.outs[19]  # an answer gone, none new: the result, with the page closed
    _write(project.here, project.outs)
    said = project.run()
    assert "Step 3 of 5: Measure" in said and not is_open(ws.dir), said
    assert said.count(CLOSED) == 1 and said.index(CLOSED) < said.index("Next:"), said
    assert CLOSED not in project.run()  # nothing closed this time


def test_a_run_that_leaves_the_page_open_says_nothing_of_it(project):  # noqa: F811
    project.first(fails={0, 1, 2}, n=20)
    said = project.run()
    assert "Step 3 of 5: Measure" in said and "is closed now" not in said, said


def test_the_terminal_result_gives_the_rate_and_range_the_page_gives(project):  # noqa: F811
    import json
    import re

    said = project.first(fails={0, 1, 2, 3, 4, 5, 6, 7}, n=20)
    ws = start_label.Workspace(project.here)
    r = json.loads(ws.result_json.read_text(encoding="utf-8"))
    page = re.sub(r"<style.*?</style>|<script.*?</script>|<[^>]+>", " ",
                  ws.report_html.read_text(encoding="utf-8"), flags=re.DOTALL)
    got = re.search(r"Of the answers you marked, you passed (about \S+) between (\S+) and (\S+)",
                    " ".join(page.split()))
    assert got and got.group(1) == "about 60%", page
    line = f"Of the answers you marked, you passed {got[1]}, between {got[2]} and {got[3]}."
    assert f"You passed 12 of 20 answers. {line}" in said, said
    assert r["pass_rate"] == 0.6


REMOVED = ("No answer you marked Fail is listed now, so judgekeeper removed "
           ".judgekeeper/fix/failed-answers.md.")


def test_the_run_that_removes_failed_answers_md_says_so_once(project):  # noqa: F811
    project.first(fails={0, 1, 2, 3, 4, 5}, n=20)
    path = start_label.Workspace(project.here).dir / "fix" / "failed-answers.md"
    assert path.is_file()
    said = project.again({i: "pass" for i in project.shown("fail")})  # each one listed fixed
    assert not path.is_file() and said.count(REMOVED) == 1, said
    assert said.index("You passed") < said.index(REMOVED) < said.index("Next:"), said
    assert REMOVED not in project.run()


def test_failed_answers_md_stays_while_new_answers_wait(project):  # noqa: F811
    project.first(fails={0, 1, 2, 3, 4, 5}, n=20)
    path = start_label.Workspace(project.here).dir / "fix" / "failed-answers.md"
    _change(project)
    said = project.run()
    assert path.is_file() and REMOVED not in said, said
