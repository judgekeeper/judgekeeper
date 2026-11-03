"""No test opens a real browser: not when a test takes the name of the fixture that stops it,
nor in a Python a test starts. Each test first names a stand-in browser (a Python that does
nothing), since a machine with no browser, as a CI one, would open nothing anyway."""

import subprocess
import sys
import webbrowser

import pytest

from tests.conftest import NO_BROWSER

STAND_IN = [sys.executable, "-c", "pass", "%s"]


@pytest.mark.parametrize("no_browser", [None])  # the fixture's name, so the fixture is not used
def test_a_test_that_takes_the_fixtures_name_opens_no_browser(no_browser, monkeypatch):
    monkeypatch.setattr(webbrowser, "_browsers",
                        {"stand-in": [None, webbrowser.GenericBrowser(STAND_IN)]})
    monkeypatch.setattr(webbrowser, "_tryorder", ["stand-in"])
    with pytest.raises(RuntimeError, match=NO_BROWSER):
        webbrowser.open("http://127.0.0.1:9/")


def test_a_python_a_test_starts_opens_no_browser(tmp_path):
    script = ("import webbrowser\n"
              f"webbrowser.register('stand-in', None, webbrowser.GenericBrowser({STAND_IN!r}),"
              " preferred=True)\n"
              "webbrowser.open('http://127.0.0.1:9/')\n")
    done = subprocess.run([sys.executable, "-c", script],
                          cwd=tmp_path, capture_output=True, text=True, timeout=60, check=False)
    assert done.returncode != 0 and NO_BROWSER in done.stderr, done.stderr
