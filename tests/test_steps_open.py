"""`judgekeeper steps runs.jsonl` opens the steps marking page (after writing the Label Studio
files as before), through the same page machinery as the answers page: one page per project,
in the background, --no-browser, --port, --wait and --stop. --new is for answers only. In CI
no page opens and the output is as before."""

from __future__ import annotations

import json
from urllib.request import Request, urlopen

import pytest

from judgekeeper import label, page
from judgekeeper.cli import main
from tests.page_http import retried

OPEN = "The marking page is open in your browser. Click the first wrong step of each run."
CLICK = "Click the first wrong step of each run."
NEXT = 'Next: mark runs on the page, then click "See the numbers so far".'
LABEL_STUDIO = ("Label in Label Studio instead? Import .judgekeeper/steps/label-these.json with "
                "label-config.xml, then run judgekeeper steps on its export.")
LINK = "Open this link in your browser to mark steps:"


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rows = [{"id": f"r{i}", "task": f"Task {i}",
             "steps": [{"role": "user", "content": f"Ask {i}"},
                       {"role": "assistant", "content": f"Do {i}"}]} for i in range(4)]
    (tmp_path / "runs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows),
                                         encoding="utf-8")
    return tmp_path


def _run(capsys, *argv):
    code = main([str(a) for a in argv])
    out, err = capsys.readouterr()
    return code, out, err


def _lines(out):
    return [x for x in out.splitlines() if x.strip()]


def _get(url):
    host = url.split("/")[2]
    return retried(lambda: urlopen(Request(url, headers={"Host": host}), timeout=5).read())


def test_steps_opens_the_page_in_the_browser(here, capsys, pages, no_browser):
    code, out, _ = _run(capsys, "steps", "runs.jsonl")
    assert code == 0, out
    lines = _lines(out)
    assert lines[1].startswith("Wrote 4 runs for Label Studio to .judgekeeper/steps/")
    assert lines[2:] == [page.OPENING_BROWSER, OPEN, NEXT, LABEL_STUDIO]
    assert len(no_browser) == 1 and "token=" in no_browser[0]
    assert (here / ".judgekeeper" / "steps" / "label-these.json").is_file()
    assert (here / ".judgekeeper" / "steps" / "label-config.xml").is_file()
    html = _get(no_browser[0]).decode("utf-8")
    assert "<title>judgekeeper: mark steps</title>" in html


def test_no_browser_prints_the_steps_link(here, capsys, pages, no_browser):
    code, out, _ = _run(capsys, "steps", "runs.jsonl", "--no-browser")
    assert code == 0, out
    lines = _lines(out)
    assert not no_browser
    at = lines.index(LINK)
    assert lines[at + 1].startswith("http://127.0.0.1:") and "token=" in lines[at + 1]
    assert lines[at + 2:] == [CLICK, NEXT, LABEL_STUDIO]
    assert "Next: in Label Studio" not in out


def test_the_page_is_started_with_the_runs_file(here, capsys, pages):
    started, _ = pages
    _run(capsys, "steps", "runs.jsonl", "--no-browser", "--port", "0")
    flags = started[-1]["flags"]
    assert flags["steps"] == str((here / "runs.jsonl").resolve())
    assert flags["port"] == 0 and flags["no_browser"] is True


def test_a_second_run_keeps_the_open_page_and_its_link(here, capsys, pages, no_browser):
    _, first, _ = _run(capsys, "steps", "runs.jsonl", "--no-browser")
    started, _ = pages
    code, out, _ = _run(capsys, "steps", "runs.jsonl", "--no-browser")
    assert code == 0 and len(started) == 1, out
    link = [x for x in _lines(first) if x.startswith("http://")]
    assert link and link[0] in out  # the same link: the open tab keeps working


def test_steps_and_the_answers_page_are_one_page_at_a_time(here, capsys, pages):
    _run(capsys, "steps", "runs.jsonl", "--no-browser")
    lock = label.read_lock(here / ".judgekeeper")
    assert lock and lock["settings"]["flags"]["steps"].endswith("runs.jsonl")


def test_stop_closes_the_steps_page(here, capsys, pages):
    _run(capsys, "steps", "runs.jsonl", "--no-browser")
    folder = here / ".judgekeeper"
    assert label.is_open(folder)
    code, out, _ = _run(capsys, "steps", "--stop")
    assert code == 0, out
    assert "Closed the marking page." in out
    assert "Next: run `judgekeeper steps runs.jsonl` when you want to continue." in out
    assert not label.is_open(folder)


def test_stop_with_no_page_says_so(here, capsys):
    code, out, _ = _run(capsys, "steps", "--stop")
    assert code == 0 and "No marking page is open." in out


def test_new_is_for_answers_only(here, capsys, pages):
    started, _ = pages
    code, out, err = _run(capsys, "steps", "runs.jsonl", "--new")
    assert code == 2
    assert ("--new works for answers only. To take back a step mark, use Undo on the page."
            in out + err)
    assert not started


def test_in_ci_no_page_opens_and_the_output_is_as_before(here, capsys, pages, monkeypatch):
    monkeypatch.setenv("CI", "true")
    started, _ = pages
    code, out, _ = _run(capsys, "steps", "runs.jsonl", "--no-browser")  # a page flag, taken
    assert code == 0 and not started
    assert "Next: in Label Studio, make a project" in out
    assert "marking page" not in out


def test_page_flags_on_an_export_open_no_page(here, capsys, pages):
    started, _ = pages
    export = here / "export.json"
    export.write_text("[]", encoding="utf-8")
    code, out, err = _run(capsys, "steps", "export.json", "--no-browser")
    assert code == 2 and not started
    assert ("`judgekeeper steps EXPORT.json` opens no page, so it takes no --port or "
            "--no-browser." in err)
    assert "Next: run `judgekeeper steps export.json`." in out + err


def test_a_mark_through_the_opened_page_lands_in_the_steps_marks(here, capsys, pages,
                                                                no_browser):
    _run(capsys, "steps", "runs.jsonl")
    url = no_browser[0]
    port, token = int(url.split(":")[2].split("/")[0]), url.split("token=")[1]
    body = json.dumps({"id": "r1", "first_wrong_step": 2, "was": None,
                       "seconds": 2}).encode()
    request = Request(f"http://127.0.0.1:{port}/label?token={token}", data=body, method="POST",
                      headers={"Content-Type": "application/json",
                               "Origin": f"http://127.0.0.1:{port}"})
    assert retried(lambda: urlopen(request, timeout=5).status) == 200
    marks = (here / ".judgekeeper" / "steps" / "marks.jsonl").read_text(encoding="utf-8")
    assert json.loads(marks.splitlines()[-1])["first_wrong_step"] == 2


def _mark_on_disk(here, marks):
    from judgekeeper import steps_page
    from judgekeeper.start_label import Workspace

    session = steps_page.StepsSession(Workspace(here), here / "runs.jsonl")
    for run_id, value in marks.items():
        session.update({"id": run_id, "first_wrong_step": value, "was": None, "seconds": 1})


def test_no_browser_with_marks_prints_the_numbers_after_the_link(here, capsys, pages):
    _mark_on_disk(here, {"r1": 2})
    code, out, _ = _run(capsys, "steps", "runs.jsonl", "--no-browser")
    lines = _lines(out)
    at = lines.index(LINK)
    assert lines[at + 2] == CLICK
    assert lines[at + 3].startswith("Read 4 runs from runs.jsonl and your marks from ")
    assert NEXT not in lines and LABEL_STUDIO not in lines
    assert sum(x.startswith("Next: ") for x in lines) == 1
    assert code == 3  # no agent-as-a-judge picks yet


def test_every_run_marked_opens_the_result(here, capsys, pages, no_browser):
    _mark_on_disk(here, {f"r{i}": 0 for i in range(4)})
    code, out, _ = _run(capsys, "steps", "runs.jsonl")
    assert "/result?token=" in no_browser[0]
    lines = _lines(out)
    assert "Your result page is open in your browser." in lines
    assert CLICK not in out and NEXT not in lines
    assert any(x.startswith("Read 4 runs from runs.jsonl and your marks from ") for x in lines)
    assert sum(x.startswith("Next: ") for x in lines) == 1 and code == 3


def test_every_run_marked_and_no_browser_prints_the_result_link(here, capsys, pages):
    _mark_on_disk(here, {f"r{i}": 0 for i in range(4)})
    _, out, _ = _run(capsys, "steps", "runs.jsonl", "--no-browser")
    lines = _lines(out)
    at = lines.index("Open this link in your browser to see your result:")
    assert "/result?token=" in lines[at + 1] and CLICK not in out


def test_wait_serves_here_and_says_the_numbers_once_the_page_closes(here, capsys, pages,
                                                                   monkeypatch):
    from judgekeeper import page

    def serve(server):  # a person marks one run, then closes the page
        server.session.update({"id": "r2", "first_wrong_step": 1, "was": None, "seconds": 2})
        server.stop()
        server.serve()

    monkeypatch.setattr(page, "serve", serve)
    started, _ = pages
    code, out, _ = _run(capsys, "steps", "runs.jsonl", "--wait", "--no-browser")
    lines = _lines(out)
    assert not started  # served by this process
    assert "The page stays open while this runs. To stop it: Ctrl-C." in lines
    assert lines[-1].startswith("Next: ")
    assert any(x.startswith("Read 4 runs from runs.jsonl and your marks from ") for x in lines)
    assert code == 3


def test_plain_stop_on_a_steps_page_says_the_steps_command(here, capsys, pages):
    _run(capsys, "steps", "runs.jsonl", "--no-browser")
    code, out, _ = _run(capsys, "--stop")
    assert code == 0 and "Closed the marking page." in out
    assert ("Next: run `judgekeeper steps runs.jsonl` when you want to continue."
            in " ".join(out.split()))


def test_steps_help_lists_the_page_flags_but_not_new(capsys):
    """steps refuses --new, so its help leaves it out; the other page flags are listed."""
    assert main(["steps", "--help"]) == 0
    out = capsys.readouterr().out
    assert "--new" not in out
    for flag in ("--port", "--no-browser", "--wait", "--stop"):
        assert flag in out, flag
    assert "[--wait | --stop]" in " ".join(out.split())
