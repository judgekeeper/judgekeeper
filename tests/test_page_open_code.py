"""The marking page's link holds its token. Where the browser would get the link as a command
argument (any program BROWSER names, xdg-open on Linux), every user of the machine could read
it in the process list. The browser then gets a link with a one-time code in place of the
token: the page takes it once, within two minutes, and answers with a redirect to the token
link. macOS and Windows hand the link over without an argument, and keep doing so."""

from __future__ import annotations

import http.client
import json
import re
import subprocess
import sys
import threading
import webbrowser
from types import SimpleNamespace

import pytest

from judgekeeper import label, page, start_label
from judgekeeper.cli import main
from tests.start_projects import promptfoo_project, split

REAL = page.hands_url_to_program  # the conftest replaces it in page.py for each test
CODE_LINK = re.compile(r"^http://127\.0\.0\.1:(\d+)/(result)?\?code=([\w-]+)$")
TOKEN = "T" * 43
CODE = "C" * 43


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


def _get(port: int, path: str, method="GET", headers=None, body=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        conn.request(method, path, body=body, headers=headers or {})
        resp = conn.getresponse()
        return resp.status, dict(resp.getheaders()), resp.read()
    finally:
        conn.close()


@pytest.fixture
def served(tmp_path):
    """A page server holding TOKEN and CODE, served in a thread: (server, port)."""
    session = SimpleNamespace(out=tmp_path / "labels.csv", link=None)
    server = label.make_server(session, 0, page="<p>", token=TOKEN, code=CODE)
    thread = threading.Thread(target=server.serve, daemon=True)
    thread.start()
    yield server, server.port
    server.stop()
    thread.join(timeout=5)


# What the launcher gets ---------------------------------------------------------------------

def test_the_launcher_gets_a_code_link_not_the_token(here, capsys, no_browser, argument):
    code, out, err = _run(capsys, "--port", "0")
    assert code == 0, out + err
    ws = start_label.Workspace(here)
    lock = label.read_lock(ws.dir)
    [arg] = no_browser
    found = CODE_LINK.match(arg)
    assert found and int(found[1]) == lock["port"], arg
    assert lock["token"] not in arg and "token=" not in arg
    one_time = found[3]
    assert len(one_time) >= 43  # as strong as the token
    assert one_time != lock["token"] and lock["token"] not in one_time
    assert one_time not in out + err  # the terminal says what it said before


def test_the_code_link_opens_the_page_once(here, capsys, no_browser, argument):
    assert _run(capsys, "--port", "0")[0] == 0
    lock = label.read_lock(start_label.Workspace(here).dir)
    port = lock["port"]
    path = no_browser[0].split(f":{port}", 1)[1]
    status, headers, _ = _get(port, path)
    assert status == 303 and headers["Location"] == f"/?token={lock['token']}"
    assert headers["Cache-Control"] == "no-store" and headers["Referrer-Policy"] == "no-referrer"
    assert _get(port, headers["Location"])[0] == 200  # the page itself
    again = _get(port, path)
    wrong_token = _get(port, "/?token=" + "x" * 43)
    assert again[0] == 403 and again[2] == wrong_token[2]  # what a wrong token gets
    assert _get(port, headers["Location"])[0] == 200  # the token link still works


def test_the_result_is_opened_the_same_way(here, capsys, no_browser, argument):
    assert _run(capsys, "--port", "0")[0] == 0
    ws = start_label.Workspace(here)
    lock = label.read_lock(ws.dir)
    assert lock["token"]
    shown = page.show(lambda line: None,
                      page.Page(label.link(lock["port"], lock["token"]), lock["port"],
                                lock["token"], code=_code_of(no_browser[0])),
                      False, False, result=True)
    assert shown == page.BROWSER
    found = CODE_LINK.match(no_browser[-1])
    assert found and found[2] == "result"
    status, headers, _ = _get(lock["port"], f"/result?code={found[3]}")
    assert status == 303 and headers["Location"] == f"/result?token={lock['token']}"


def _code_of(link: str) -> str:
    return CODE_LINK.match(link)[3]


# What the page takes ----------------------------------------------------------------------------

def test_the_code_gives_a_redirect_to_the_token_link_once(served):
    server, port = served
    status, headers, body = _get(port, f"/?code={CODE}")
    assert status == 303 and headers["Location"] == f"/?token={TOKEN}" and body == b""
    assert headers["Cache-Control"] == "no-store" and headers["Referrer-Policy"] == "no-referrer"
    assert _get(port, f"/?code={CODE}")[0] == 403
    assert server.code is None


def test_a_used_wrong_or_missing_code_gets_what_a_wrong_token_gets(served):
    _server, port = served
    wrong_token = _get(port, "/?token=" + "x" * 43)
    assert wrong_token[0] == 403
    for query in (f"code={'D' * 43}", f"code={CODE[:-1]}", "code=", "code=%00"):
        status, _, body = _get(port, f"/?{query}")
        assert (status, body) == (wrong_token[0], wrong_token[2]), query
    assert _get(port, f"/?code={CODE}")[0] == 303  # wrong guesses did not use it up
    assert _get(port, f"/?code={CODE}")[2] == wrong_token[2]
    json_wrong = _get(port, "/state?token=" + "x" * 43)
    assert _get(port, f"/state?code={CODE}")[2:] == json_wrong[2:]


def test_an_expired_code_gets_a_403(served):
    server, port = served
    started = server.code_until - label.CODE_LIFE
    server.clock = lambda: started + label.CODE_LIFE - 1
    assert server.code is not None
    server.clock = lambda: started + label.CODE_LIFE + 1
    status, _, _ = _get(port, f"/?code={CODE}")
    assert status == 403 and server.code is None


def test_a_code_that_is_still_alive_works_up_to_its_last_second(served):
    server, port = served
    server.clock = lambda: server.code_until - 1
    assert _get(port, f"/?code={CODE}")[0] == 303


def test_a_code_dies_when_the_server_stops(served):
    server, _port = served
    server.stop()
    assert server.code is None and server.take_code(CODE) is False


def test_the_host_checks_still_apply_to_the_code_request(served):
    server, port = served
    for host in ("evil.com", f"localhost:{port}", "127.0.0.1"):
        assert _get(port, f"/?code={CODE}", headers={"Host": host})[0] == 403, host
    assert server.code == CODE  # a refused request used nothing up
    assert _get(port, f"/?code={CODE}")[0] == 303


def test_a_code_opens_only_the_two_pages(served):
    server, port = served
    for path in ("/state", "/alive", "/stop", "/label", "/project", "/favicon.ico"):
        assert _get(port, f"{path}?code={CODE}")[0] in (403, 204, 404), path
    assert server.code == CODE
    assert _get(port, f"/result?code={CODE}")[0] == 303


@pytest.mark.parametrize("path", ["/label", "/stop", "/printed", "/"])
def test_post_endpoints_refuse_a_code_in_place_of_the_token(served, path):
    server, port = served
    origin = {"Origin": f"http://127.0.0.1:{port}", "Content-Type": "application/json"}
    status, _, _ = _get(port, f"{path}?code={CODE}", "POST", origin, json.dumps({}))
    assert status == 403
    assert server.code == CODE


def test_a_server_with_no_code_takes_none(tmp_path):
    session = SimpleNamespace(out=tmp_path / "labels.csv", link=None)
    server = label.make_server(session, 0, page="<p>", token=TOKEN)
    thread = threading.Thread(target=server.serve, daemon=True)
    thread.start()
    try:
        assert _get(server.port, f"/?code={CODE}")[0] == 403
        assert _get(server.port, "/?code=")[0] == 403
    finally:
        server.stop()
        thread.join(timeout=5)


# Where the code is kept --------------------------------------------------------------------------

@pytest.mark.real_page
def test_the_code_is_in_no_file_no_log_and_no_command_line(here, capsys, no_browser, argument):
    from tests.test_page_token import _process_text

    ws = start_label.Workspace(here)
    try:
        code, out, err = _run(capsys, "--port", "0")
        assert code == 0, out + err
        one_time = _code_of(no_browser[0])
        lock = label.read_lock(ws.dir)
        assert lock["token"] != one_time
        for path in (p for p in ws.dir.rglob("*") if p.is_file()):
            assert one_time not in path.read_bytes().decode(errors="replace"), path.name
        assert (ws.dir / "page.log").exists()
        assert one_time not in _process_text(lock["pid"])
        assert _get(lock["port"], f"/?code={one_time}")[0] == 303  # it was alive all along
    finally:
        _run(capsys, "--stop")
    for path in (p for p in ws.dir.rglob("*") if p.is_file()):
        assert one_time not in path.read_bytes().decode(errors="replace"), path.name


# Which browsers get it ---------------------------------------------------------------------------

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
    lock = label.read_lock(start_label.Workspace(here).dir)
    assert no_browser == [label.link(lock["port"], lock["token"])]


def test_a_program_named_in_browser_gets_the_code(monkeypatch):
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


def test_a_page_that_was_open_already_gets_no_code_link(here, capsys, no_browser, argument):
    """No new tab for it, so nothing is handed to a launcher."""
    assert _run(capsys, "--port", "0")[0] == 0
    first = list(no_browser)
    assert _run(capsys, "--port", "0")[0] == 0
    assert no_browser == first


# A browser -------------------------------------------------------------------------------------------

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
        print(tab.url)
        print(tab.locator("#a-text").text_content().strip())
    finally:
        browser.close()
"""


@pytest.mark.real_page
def test_a_headless_browser_follows_the_code_link_to_the_first_card(here, capsys, no_browser,
                                                                    argument):
    """The server takes a first load that arrives by the code link and sends on: the page
    opens with its first answer. Headless only, in a process of its own; skipped where
    Playwright or its Chromium is not installed."""
    ws = start_label.Workspace(here)
    try:
        code, out, err = _run(capsys, "--port", "0")
        assert code == 0, out + err
        [arg] = no_browser
        assert CODE_LINK.match(arg)
        lock = label.read_lock(ws.dir)
        done = subprocess.run([sys.executable, "-c", HEADLESS, arg,
                               f"http://127.0.0.1:{lock['port']}/?token=*"],
                              capture_output=True, text=True, timeout=120, check=False)
        if done.returncode == 77:
            pytest.skip("no headless Chromium with Playwright here")
        assert done.returncode == 0, done.stderr
        landed, answer = done.stdout.strip().splitlines()
        assert landed == label.link(lock["port"], lock["token"])
        assert answer.startswith("Answer"), done.stdout
    finally:
        _run(capsys, "--stop")


def test_no_file_is_written_for_the_browser(here, capsys, no_browser, argument):
    assert _run(capsys, "--port", "0")[0] == 0
    names = {p.name for p in (here / ".judgekeeper").iterdir()}
    assert not any(n.endswith(".html") for n in names), names
