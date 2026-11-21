"""The marking page's link holds its token. Where the browser would get the link as a command
argument (any program BROWSER names, xdg-open on Linux), every user of the machine could read
it in the process list. The browser then gets a small file in .judgekeeper/ instead, which
only redirects to the link: owner-only, replaced on the next start, removed when the page
stops. macOS and Windows hand the link over without an argument, and keep doing so."""

from __future__ import annotations

import os
import stat
import webbrowser
from types import SimpleNamespace

import pytest

from judgekeeper import label, page, start_label
from judgekeeper.cli import main
from tests.start_projects import promptfoo_project, split

POSIX = os.name == "posix"
REAL = page.hands_url_to_program  # the conftest replaces it in page.py for each test


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    promptfoo_project(tmp_path, split(20, 16))
    return tmp_path


@pytest.fixture
def argument(monkeypatch):
    """The browser gets the link as an argument (as xdg-open or a BROWSER program does)."""
    monkeypatch.setattr("judgekeeper.page.hands_url_to_program", lambda: True)


def _run(capsys, *argv):
    code = main([str(a) for a in argv])
    out, err = capsys.readouterr()
    return code, out, err


def _opened_file(arg: str, folder):
    assert arg.startswith("file://")
    from urllib.parse import unquote, urlsplit

    path = unquote(urlsplit(arg).path)
    if os.name == "nt":
        path = path.lstrip("/")
    return os.path.realpath(path), os.path.realpath(folder / page.OPEN_FILE)


def test_the_browser_gets_a_file_that_holds_the_link_not_the_link(here, capsys, no_browser,
                                                                  argument):
    code, out, err = _run(capsys, "--port", "0")
    assert code == 0, out + err
    ws = start_label.Workspace(here)
    lock = label.read_lock(ws.dir)
    token = lock["token"]
    [arg] = no_browser
    assert token not in arg and "token=" not in arg
    opened, expected = _opened_file(arg, ws.dir)
    assert opened == expected
    redirect = (ws.dir / page.OPEN_FILE).read_text(encoding="utf-8")
    assert f"http://127.0.0.1:{lock['port']}/?token={token}" in redirect
    assert "http-equiv=\"refresh\"" in redirect and "<a href=" in redirect
    assert "<script" not in redirect and "src=" not in redirect  # nothing from outside
    if POSIX:
        assert stat.S_IMODE((ws.dir / page.OPEN_FILE).stat().st_mode) == 0o600
    assert token not in out + err  # the terminal says what it said before
    assert _run(capsys, "--stop")[0] == 0
    assert not (ws.dir / page.OPEN_FILE).exists()


def test_the_result_is_opened_the_same_way(here, capsys, no_browser, argument):
    ws = start_label.Workspace(here)
    assert _run(capsys, "--port", "0")[0] == 0
    lock = label.read_lock(ws.dir)
    from judgekeeper.page import Page

    shown = page.show(lambda line: None, Page(label.link(lock["port"], lock["token"]),
                                              lock["port"], lock["token"]),
                      False, False, result=True, folder=ws.dir)
    assert shown == page.BROWSER
    redirect = (ws.dir / page.OPEN_FILE).read_text(encoding="utf-8")
    assert f"http://127.0.0.1:{lock['port']}/result?token={lock['token']}" in redirect
    assert lock["token"] not in no_browser[-1]


def test_a_file_from_an_earlier_start_is_replaced(here, capsys, no_browser, argument):
    ws = start_label.Workspace(here)
    ws.dir.mkdir(mode=0o700)
    (ws.dir / page.OPEN_FILE).write_text("old token a-dead-page-held", encoding="utf-8")
    assert _run(capsys, "--port", "0")[0] == 0
    text = (ws.dir / page.OPEN_FILE).read_text(encoding="utf-8")
    assert "a-dead-page-held" not in text and label.read_lock(ws.dir)["token"] in text
    assert _run(capsys, "--stop")[0] == 0
    assert not (ws.dir / page.OPEN_FILE).exists()


def test_a_page_that_is_gone_leaves_no_file_with_its_token(here, capsys, no_browser, argument):
    folder = here / ".judgekeeper"
    assert _run(capsys, "--port", "0")[0] == 0
    assert _run(capsys, "--stop")[0] == 0
    stale = ('{"pid": 999999, "port": 9, "stop": "' + "s" * 43 + '", "token": "' + "t" * 43
             + '", "settings": null}')
    for name in (label.LOCK, label.LOCK_COPY):
        (folder / name).write_text(stale, encoding="utf-8")
    (folder / page.OPEN_FILE).write_text("redirect " + "t" * 43, encoding="utf-8")
    assert label.live_lock(folder) is None
    assert not (folder / page.OPEN_FILE).exists()


def test_a_page_removes_only_a_file_that_holds_its_own_token(tmp_path):
    ws = start_label.Workspace(tmp_path)
    ws.dir.mkdir(mode=0o700)
    server = label.make_server(SimpleNamespace(out=tmp_path / "labels.csv"), 0,
                               page="<p>", lock=ws.dir, token="this-pages-token")
    try:
        (ws.dir / page.OPEN_FILE).write_text("a later page's token", encoding="utf-8")
        server.release()
        assert (ws.dir / page.OPEN_FILE).read_text(encoding="utf-8") == "a later page's token"
        server.hold(ws.dir)
        (ws.dir / page.OPEN_FILE).write_text("redirect this-pages-token", encoding="utf-8")
        server.release()
        assert not (ws.dir / page.OPEN_FILE).exists()
    finally:
        server.httpd.server_close()


@pytest.mark.skipif(not POSIX, reason="links need no special right on Linux and macOS")
@pytest.mark.parametrize("hard", [False, True])
def test_a_link_at_the_files_name_is_refused(tmp_path, argument, hard, monkeypatch):
    folder = tmp_path / ".judgekeeper"
    folder.mkdir(mode=0o700)
    victim = tmp_path / "victim.txt"
    victim.write_text("mine", encoding="utf-8")
    (os.link if hard else os.symlink)(victim, folder / page.OPEN_FILE)
    tried = []
    monkeypatch.setattr("webbrowser.open", lambda url, *a, **k: tried.append(url) or True)
    assert page._in_browser("http://127.0.0.1:9/?token=abc", folder) is False
    assert victim.read_text(encoding="utf-8") == "mine"
    assert tried == []  # the link is not handed to a program either


def test_where_the_file_cannot_be_written_the_link_opens_as_before(tmp_path, argument,
                                                                    monkeypatch):
    tried = []
    monkeypatch.setattr("webbrowser.open", lambda url, *a, **k: tried.append(url) or True)

    def refuse(*args, **kwargs):
        raise PermissionError("read-only folder")

    monkeypatch.setattr("judgekeeper.textio.write_replacing", refuse)
    assert page._in_browser("http://127.0.0.1:9/?token=abc", tmp_path) is True
    assert tried == ["http://127.0.0.1:9/?token=abc"]


def test_where_the_file_cannot_be_opened_the_link_is_tried(tmp_path, argument, monkeypatch):
    tried = []

    def browser(url, *a, **k):
        tried.append(url)
        return not url.startswith("file://")

    monkeypatch.setattr("webbrowser.open", browser)
    assert page._in_browser("http://127.0.0.1:9/?token=abc", tmp_path) is True
    assert [u.split(":")[0] for u in tried] == ["file", "http"]


def test_no_folder_keeps_the_old_call(tmp_path, argument, monkeypatch):
    tried = []
    monkeypatch.setattr("webbrowser.open", lambda url, *a, **k: tried.append(url) or True)
    assert page._in_browser("http://127.0.0.1:9/?token=abc", None) is True
    assert tried == ["http://127.0.0.1:9/?token=abc"]


class MacOSXOSAScript:  # the names of python's own browsers that start with no argument
    pass


class WindowsDefault:
    pass


@pytest.mark.parametrize("browser", [MacOSXOSAScript, WindowsDefault])
def test_macos_and_windows_keep_the_old_call(here, capsys, no_browser, monkeypatch, browser):
    monkeypatch.setattr("judgekeeper.page.hands_url_to_program", REAL)
    monkeypatch.setattr(webbrowser, "get", lambda *a, **k: browser())
    code, out, err = _run(capsys, "--port", "0")
    assert code == 0, out + err
    ws = start_label.Workspace(here)
    assert no_browser == [label.link(label.read_lock(ws.dir)["port"],
                                     label.read_lock(ws.dir)["token"])]
    assert not (ws.dir / page.OPEN_FILE).exists()


def test_a_program_named_in_browser_gets_the_file(monkeypatch):
    """BROWSER is how a person (or a tool) names the program that opens links: python's
    webbrowser runs it with the link as its argument."""
    monkeypatch.setenv("BROWSER", "/somewhere/open-it %s")
    monkeypatch.setattr(webbrowser, "_tryorder", None)
    monkeypatch.setattr(webbrowser, "_browsers", {})
    monkeypatch.setattr(webbrowser, "_os_preferred_browser", None, raising=False)
    assert REAL() is True


def test_no_browser_at_all_is_no_argument(monkeypatch):
    def none(*args, **kwargs):
        raise webbrowser.Error("could not locate runnable browser")

    monkeypatch.setattr(webbrowser, "get", none)
    assert REAL() is False


@pytest.mark.parametrize("browser", [webbrowser.GenericBrowser, webbrowser.BackgroundBrowser])
def test_browsers_started_with_an_argument_are_found(monkeypatch, browser):
    monkeypatch.setattr(webbrowser, "get", lambda *a, **k: browser("xdg-open"))
    assert REAL() is True


HEADLESS = """import sys
try:
    from playwright.sync_api import Error, sync_playwright
except ImportError:
    sys.exit(77)
with sync_playwright() as p:
    try:
        browser = p.chromium.launch(headless=True)
    except Error:
        sys.exit(77)
    try:
        tab = browser.new_page()
        tab.goto(sys.argv[1])
        tab.wait_for_url(sys.argv[2])
        tab.wait_for_function("document.getElementById('a-text') && "
                              "document.getElementById('a-text').textContent.trim() !== ''",
                              timeout=15000)
        print(tab.locator("#a-text").text_content().strip())
    finally:
        browser.close()
"""


@pytest.mark.real_page
def test_a_headless_browser_lands_on_the_first_card(here, capsys, no_browser, argument):
    """A browser shows the file and is sent on: the page opens with its first answer, so the
    server takes a first load that arrives by the redirect. Headless only, in a process of its
    own; skipped where Playwright or its Chromium is not installed."""
    import subprocess
    import sys

    ws = start_label.Workspace(here)
    try:
        code, out, err = _run(capsys, "--port", "0")
        assert code == 0, out + err
        [arg] = no_browser
        assert arg.startswith("file://")
        port = label.read_lock(ws.dir)["port"]
        done = subprocess.run([sys.executable, "-c", HEADLESS, arg, f"http://127.0.0.1:{port}/**"],
                              capture_output=True, text=True, timeout=120, check=False)
        if done.returncode == 77:
            pytest.skip("no headless Chromium with Playwright here")
        assert done.returncode == 0, done.stderr
        assert done.stdout.strip().startswith("Answer"), done.stdout
    finally:
        _run(capsys, "--stop")
