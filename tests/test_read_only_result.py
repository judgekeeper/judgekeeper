"""A result page while .judgekeeper/ can't be written. The page shows the result from the marks
(nothing is saved, and no disagreement is listed: the hidden marks can't be set aside). A file
that can't be written is named by its own name, never the temporary file it was written
through, and the line has one full stop where its parts meet."""

from __future__ import annotations

import os
import sys

import pytest

from judgekeeper import start_label, textio
from tests.test_label_server import _serve_until_done
from tests.test_repeats import ws  # noqa: F401

posix = pytest.mark.skipif(sys.platform == "win32" or os.geteuid() == 0,
                           reason="file permissions: POSIX, not as root")


@posix
def test_a_file_in_a_folder_that_cant_be_written_is_named_itself(tmp_path):
    folder = tmp_path / ".judgekeeper"
    folder.mkdir()
    folder.chmod(0o555)
    try:
        with pytest.raises(PermissionError) as e:
            textio.write_replacing(folder / "anchors.jsonl", "x")
    finally:
        folder.chmod(0o755)
    assert e.value.filename == str(folder / "anchors.jsonl")
    said = textio.describe_os_error(e.value)
    assert ".tmp" not in said and "anchors.jsonl" in said


def test_a_refused_rename_names_the_file_not_the_temporary_one(tmp_path, monkeypatch):
    path = tmp_path / "result.json"

    def refuse(src, dst):
        raise PermissionError(13, "Permission denied", src, dst)

    monkeypatch.setattr(textio, "is_windows", lambda: False)
    monkeypatch.setattr(textio.os, "replace", refuse)
    with pytest.raises(PermissionError) as e:
        textio.write_replacing(path, "x")
    assert e.value.filename == str(path) and e.value.filename2 is None
    assert ".tmp" not in textio.describe_os_error(e.value)
    assert list(tmp_path.iterdir()) == []  # no temporary file left


def _marked(ws) -> start_label.StartSession:  # noqa: F811
    """25 marks in each of the judge's groups, each the judge's own grade: a first result."""
    page = start_label.StartSession(ws)
    n = {"pass": 0, "fail": 0}
    for item in page.items:
        group = page.groups[item["id"]]
        if n[group] < 25:
            page.update({"id": item["id"], "label": group, "seconds": 3})
            n[group] += 1
    return page


@posix
def test_the_result_page_shows_while_the_folder_cant_be_written(ws):  # noqa: F811
    page = _marked(ws)
    before = sorted(p.name for p in ws.dir.iterdir())
    ws.dir.chmod(0o555)
    try:
        html = start_label.live_result(ws, page, back="/?token=t")
    finally:
        ws.dir.chmod(0o755)
    assert 'class="verdict' in html and "50</b> answers" in html
    assert sorted(p.name for p in ws.dir.iterdir()) == before  # nothing written, no .tmp left
    page.update({"id": page.items[-1]["id"], "label": "pass"})  # writable again: as before
    assert "50</b> answers" not in start_label.live_result(ws, page, back="/?token=t")
    assert ws.result_json.is_file()


@pytest.mark.parametrize("windows", [False, True])
def test_a_result_that_cant_be_saved_has_one_full_stop(tmp_path, monkeypatch, windows):
    """One full stop after each sentence, also with the line said only on Windows."""
    monkeypatch.setattr(textio, "is_windows", lambda: windows)

    def result(session, back):
        raise PermissionError(13, "Permission denied", str(tmp_path / "marks.jsonl"))

    server, thread, client = _serve_until_done(tmp_path, result=result)
    try:
        resp, payload = client.request("GET", "/result")
        said = payload.decode()
        assert resp.status == 500 and said.startswith("Not saved: cannot write ")
        last = ("If the file is open in Excel or another program, close it first."
                if windows else "or change the folder's permissions.")
        assert ".." not in said and f"{last} Your marks are saved; try again" in said
        assert said.endswith("once the folder can be written.")
        assert ("permissions. If the file is open" in said) is windows
    finally:
        server.stop()
        thread.join(timeout=5)
