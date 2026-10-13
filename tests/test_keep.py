"""Keeping watch: the "Turn on" page, the hooks it adds, the status, and `check --off`.

Only the person's click on the page turns automatic checks on. A page whose link was printed
where a coding agent could read it refuses. The click writes .judgekeeper/checks.json, adds
the agent hooks (.claude/settings.local.json, .cursor/hooks.json), a check before each git
commit, judgekeeper in the dev requirements (when it is installed in the project), and asks
the judge once (the baseline, faked here). `check --off` removes exactly what was added.

No test calls an API: the baseline is a fake, and the page runs in a thread (conftest.pages).
"""

from __future__ import annotations

import io
import json
import os
import shutil
import sys
import time
import urllib.request

import pytest

from judgekeeper import __version__, check, keep, textio
from judgekeeper.cli import main
from judgekeeper.marks import PRINTED
from tests.page_http import retried
from tests.test_check import HAIKU, LENIENT, MODEL, TAG, _marked, _results
from tests.test_front import assert_one_next_at_the_end

V = __version__
KEEP_OPEN = "The page that turns on automatic checks is open in your browser."
NEXT_KEEP = ("Next: ask the person if judgekeeper should keep checking their judge by itself. "
             "They answer on the page open in their browser (only they can turn this on). Then "
             "run `judgekeeper` again.")
NEXT_RESULT = ("Next: nothing. Tell the person the result above. To mark more, run "
               "`judgekeeper mark`.")
MARK_MORE = "Mark up to 25 Pass and 25 Fail to turn on automatic checks."
OFF_LINE = "Automatic checks: off. To turn them on, run `judgekeeper check --on`."
UVX = ["uvx", f"judgekeeper@{V}"]


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def baseline(monkeypatch):
    """The judge asked once after Turn on: a fake that says one line."""
    calls = []

    def fake(path, said):
        calls.append(path)
        said.say("Asked your judge again about 50 marked answers: it changed its mind on 1 of "
                 "your 50 marked answers.")
        return 0

    monkeypatch.setattr(check, "baseline", fake)
    return calls


@pytest.fixture(autouse=True)
def no_extras(monkeypatch):
    """No optional extra is installed (the test environment may have mlflow)."""
    monkeypatch.setattr(textio, "extras_here", lambda: ())


@pytest.fixture(autouse=True)
def git_config(tmp_path_factory, monkeypatch):
    """git reads no config of this computer's: an empty file stands in for the global one
    (a test writes in it), and the system's is skipped."""
    path = tmp_path_factory.mktemp("git-config") / "global"
    path.write_text("", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(path))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    return path


needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="needs git")


@pytest.fixture
def by_uvx(monkeypatch):
    """judgekeeper was started by uvx."""
    monkeypatch.setattr(textio, "started_by_uvx", lambda: True)


def run(capsys, *argv, printed=False):
    code = main([str(a) for a in argv])
    out, err = capsys.readouterr()
    assert TAG.strip() not in out + err
    assert printed or "token=" not in out + err
    return code, out


def _call(url: str, path: str, body=None):
    base, token = url.split("/?token=")
    req = urllib.request.Request(f"{base}{path}?token={token}",
                                 data=None if body is None else json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})

    def send():
        with urllib.request.urlopen(req, timeout=10) as r:
            raw = r.read().decode("utf-8")
            return json.loads(raw) if r.headers.get_content_type() == "application/json" \
                else raw

    return retried(send)


def _done(url: str) -> dict:
    """The page's state once the work after the click is done."""
    for _ in range(100):
        state = _call(url, "/state")
        if state["phase"] != "asking":
            return state
        time.sleep(0.05)
    raise AssertionError("the baseline never finished")


def _offered(here, capsys, no_browser) -> str:
    """`judgekeeper` with 25 + 25 marks: the result, and the Turn on page opened."""
    code, out = run(capsys)
    assert code == 0, out
    assert KEEP_OPEN in out
    return no_browser[-1]


def _turn_on(here, capsys, no_browser, **body) -> dict:
    url = _offered(here, capsys, no_browser)
    answer = _call(url, "/turn-on", body)
    assert answer["phase"] in ("asking", "done"), answer
    return _done(url)


def _checks(root) -> dict:
    return json.loads((root / ".judgekeeper" / "checks.json").read_text(encoding="utf-8"))


def _settings(root) -> dict:
    return json.loads((root / ".claude" / "settings.local.json").read_text(encoding="utf-8"))


def _told(capsys) -> str:
    """The first `judgekeeper` after the click: what was set up (said once)."""
    code, out = run(capsys)
    assert code == 0 and "Keeping watch." in out, out
    return out


def _hook_commands(settings: dict) -> list[dict]:
    return [h for entry in settings["hooks"]["PostToolUse"] for h in entry["hooks"]]


# The offer ---------------------------------------------------------------------------------

def test_the_result_offers_turn_on_at_25_of_each(here, capsys, pages, no_browser):
    _marked(here)
    code, out = run(capsys)
    assert code == 0
    assert "Of the answers you passed, your judge passed" in out
    assert KEEP_OPEN in out
    assert "still open" not in out
    assert assert_one_next_at_the_end(out) == NEXT_KEEP
    started, _ = pages
    assert started[-1]["view"] == "keep"
    assert not (here / ".judgekeeper" / "checks.json").exists()


def test_under_25_of_each_says_how_far_to_go(here, capsys, pages):
    _marked(here, n_pass=15, n_fail=25)
    code, out = run(capsys)
    assert code == 0
    assert MARK_MORE in out and KEEP_OPEN not in out
    assert assert_one_next_at_the_end(out) == NEXT_RESULT
    assert all(s.get("view") != "keep" for s in pages[0])


def test_the_page_says_what_turning_on_does(here, capsys, no_browser):
    _marked(here)
    url = _offered(here, capsys, no_browser)
    html = _call(url, "/")
    assert "Keep checking your judge?" in html
    assert ("When your judge's model, rule, pass mark or eval tool changes, judgekeeper "
            "re-tests it on your marks, using your own judge through promptfoo with the key "
            "your evals already use.") in html
    assert "Each check asks your judge about up to 50 answers." in html
    assert "Turn on" in html and "No thanks" in html
    assert "even though it can change files" not in html  # not an agent judge
    assert TAG.strip() not in html


def test_an_agent_judge_that_can_write_gets_the_extra_box(here, capsys, no_browser):
    _marked(here, agent=True)
    url = _offered(here, capsys, no_browser)
    html = _call(url, "/")
    assert "Also run my judge by itself, even though it can change files." in html
    assert _call(url, "/state")["agent"] is True


# Turn on -----------------------------------------------------------------------------------

@pytest.mark.parametrize("path", ["/turn-on", "/no-thanks"])
def test_both_answers_are_refused_when_the_link_was_printed(here, baseline, path):
    ws = _marked(here)
    session = keep.KeepSession(ws)
    session.link = PRINTED
    assert session.state()["phase"] == "refused"  # said as the page loads
    answer = session.posts[path]({})
    assert answer["phase"] == "refused"
    assert answer["lines"] == ["Open judgekeeper in your own terminal to turn this on."]
    assert not (ws.dir / "checks.json").exists() and baseline == []
    assert not (here / ".claude").exists()


NEXT_TERMINAL = ("Next: ask the person to run `judgekeeper check --on` in their own terminal.")


def test_without_a_browser_the_agent_never_gets_the_link(here, capsys, pages, baseline,
                                                         monkeypatch):
    from judgekeeper import label

    _marked(here)
    monkeypatch.setattr("webbrowser.open", lambda url, *a, **k: False)
    code, out = run(capsys)
    assert code == 0
    assert "Turn-on page" not in out and KEEP_OPEN not in out
    assert assert_one_next_at_the_end(out) == NEXT_TERMINAL
    assert not label.is_open(here / ".judgekeeper")
    assert not (here / ".judgekeeper" / "checks.json").exists()
    code, out = run(capsys, "check", "--on")
    assert code == 3
    assert assert_one_next_at_the_end(out) == NEXT_TERMINAL


def test_a_click_sets_everything_up(here, capsys, no_browser, baseline, by_uvx):
    ws = _marked(here)
    (here / ".cursor").mkdir()
    (here / ".git" / "hooks").mkdir(parents=True)
    config = ("repos:\n  - repo: https://github.com/astral-sh/ruff-pre-commit\n    rev: v0.6.0\n"
              "    hooks:\n      - id: ruff\n")
    (here / ".pre-commit-config.yaml").write_text(config, encoding="utf-8")
    state = _turn_on(here, capsys, no_browser)
    assert state["phase"] == "done"
    assert state["lines"][0] == ("Keeping watch. Your marks stay on this computer "
                                 "(.judgekeeper/ is not in git).")
    assert "Added the agent hook to .claude/settings.local.json." in state["lines"]
    assert "Added the agent hook to .cursor/hooks.json." in state["lines"]
    assert ("Added a check before each git commit to .git/hooks/pre-commit."
            in state["lines"])
    assert any("changed its mind on 1" in x for x in state["lines"])
    assert baseline == [str(here.resolve())]

    data = _checks(here)
    assert data["on"] is True and data["by"] == "page" and data["allow_agent_judge"] is False
    assert data["since"].endswith("Z") and data["sitting"]
    assert [a["file"] for a in data["added"]] == [
        ".claude/settings.local.json", ".cursor/hooks.json", ".git/hooks/pre-commit"]

    hooks = _hook_commands(_settings(here))
    assert len(hooks) == 2
    for h in hooks:
        assert h == {"type": "command", "command": "uvx",
                     "args": [f"judgekeeper@{V}", "check", "--hook", "${CLAUDE_PROJECT_DIR}"],
                     "timeout": 600}
    assert [e["matcher"] for e in _settings(here)["hooks"]["PostToolUse"]] == ["Bash",
                                                                               "Write|Edit"]
    cursor = json.loads((here / ".cursor" / "hooks.json").read_text(encoding="utf-8"))
    assert cursor["version"] == 1
    for event in ("afterShellExecution", "afterFileEdit"):
        assert cursor["hooks"][event] == [{"command": f"uvx judgekeeper@{V} check --hook",
                                           "timeout": 600}]
    # the team's config is never edited: the check is local, as the marks are
    assert (here / ".pre-commit-config.yaml").read_text(encoding="utf-8") == config
    assert ws.marks.is_file()


def test_the_agent_judge_box_is_kept(here, capsys, no_browser, baseline, by_uvx):
    _marked(here, agent=True)
    _turn_on(here, capsys, no_browser, allow_agent_judge=True)
    assert _checks(here)["allow_agent_judge"] is True


def test_installed_in_the_project_runs_its_own_and_pins_it(here, capsys, no_browser, baseline,
                                                           monkeypatch):
    _marked(here)
    monkeypatch.setattr(keep, "_prefix", lambda: here / ".venv")
    (here / "requirements-dev.txt").write_text("pytest\r\n", encoding="utf-8", newline="")
    state = _turn_on(here, capsys, no_browser)
    assert f"Added judgekeeper=={V} to requirements-dev.txt." in state["lines"]
    pinned = f"pytest\r\njudgekeeper=={V}\r\n".encode()
    assert (here / "requirements-dev.txt").read_bytes() == pinned
    exe = "Scripts/judgekeeper.exe" if os.name == "nt" else "bin/judgekeeper"
    (h, _) = _hook_commands(_settings(here))
    assert h["command"] == f"${{CLAUDE_PROJECT_DIR}}/.venv/{exe}"
    assert h["args"] == ["check", "--hook", "${CLAUDE_PROJECT_DIR}"]


def test_a_git_hook_is_written_when_there_is_none(here, capsys, no_browser, baseline, by_uvx):
    _marked(here)
    (here / ".git" / "hooks").mkdir(parents=True)
    (here / ".git" / "config").write_text("[core]\n\tbare = false\n", encoding="utf-8")
    state = _turn_on(here, capsys, no_browser)
    hook = here / ".git" / "hooks" / "pre-commit"
    assert "Added a check before each git commit to .git/hooks/pre-commit." in state["lines"]
    text = hook.read_text(encoding="utf-8")
    assert text == f"#!/bin/sh\n{BLOCK}"
    if os.name != "nt":
        assert os.access(hook, os.X_OK)


BLOCK = ("# judgekeeper: re-checks your judge before each commit (no AI call). "
         "`judgekeeper check --off` takes this block out.\n"
         f"uvx judgekeeper@{V} check --fast || exit $?\n"
         "# judgekeeper: end\n")
SNIPPET = ["- repo: local", "  hooks:", "    - id: judgekeeper", "      name: judgekeeper",
           f"      entry: uvx judgekeeper@{V} check --fast", "      language: system",
           "      pass_filenames: false", "      always_run: true"]


def test_a_git_hook_of_the_persons_gets_a_marked_block(here, capsys, no_browser, baseline,
                                                       by_uvx):
    _marked(here)
    (here / ".git" / "hooks").mkdir(parents=True)
    hook = here / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\nmake lint\n", encoding="utf-8")
    state = _turn_on(here, capsys, no_browser)
    assert hook.read_text(encoding="utf-8") == f"#!/bin/sh\n{BLOCK}make lint\n"
    assert "Added a check before each git commit to .git/hooks/pre-commit." in state["lines"]
    hook.write_text(hook.read_text(encoding="utf-8") + "make test\n", encoding="utf-8")
    run(capsys, "check", "--off")
    assert hook.read_text(encoding="utf-8") == "#!/bin/sh\nmake lint\nmake test\n"


@pytest.mark.parametrize("hook_text, where, shown", [
    ("#!/usr/bin/env python3\n# File generated by pre-commit: https://pre-commit.com\n",
     ".pre-commit-config.yaml", SNIPPET),
    ("#!/bin/sh\n. \"$(dirname \"$0\")/_/husky.sh\"\n", "your git pre-commit hook",
     [f"uvx judgekeeper@{V} check --fast"]),
    ("#!/usr/bin/env python3\nprint('lint')\n", "your git pre-commit hook",
     [f"uvx judgekeeper@{V} check --fast"]),
])
def test_a_hook_run_by_another_tool_is_left_alone(here, capsys, no_browser, baseline, by_uvx,
                                                   hook_text, where, shown):
    _marked(here)
    (here / ".git" / "hooks").mkdir(parents=True)
    hook = here / ".git" / "hooks" / "pre-commit"
    hook.write_text(hook_text, encoding="utf-8")
    state = _turn_on(here, capsys, no_browser)
    assert hook.read_text(encoding="utf-8") == hook_text
    at = state["lines"].index(f"Your git pre-commit hook is run by another tool, so judgekeeper "
                              f"left it as it is. To check before each commit, add this to "
                              f"{where}:")
    assert state["lines"][at + 1:at + 1 + len(shown)] == [f"  {x}" for x in shown]
    assert [a["file"] for a in _checks(here)["added"]] == [".claude/settings.local.json"]
    _told(capsys)
    _, out = run(capsys)
    assert ("  Runs when: your judge changes (agent hook); before each git commit: not set up "
            "(add the lines below).") in out.splitlines()
    assert f"    {shown[-1]}" in out.splitlines()


def test_a_hooks_path_is_left_alone(here, capsys, no_browser, baseline, by_uvx):
    _marked(here)
    (here / ".git" / "hooks").mkdir(parents=True)
    (here / ".git" / "config").write_text("[core]\n\thooksPath = .githooks\n", encoding="utf-8")
    state = _turn_on(here, capsys, no_browser)
    assert not (here / ".git" / "hooks" / "pre-commit").exists()
    assert any("left it as it is" in x for x in state["lines"])


def _git_repo(root) -> None:
    import subprocess

    subprocess.run(["git", "init", "-q", str(root)], check=True, capture_output=True)


HOOKS_FOLDER_STATUS = ("  Runs when: your judge changes (agent hook); before each git commit: "
                       "not set up (your git uses its own hooks folder).")


@needs_git
def test_a_hooks_path_set_for_every_repository_is_left_alone(here, capsys, no_browser,
                                                            baseline, by_uvx, git_config):
    _marked(here)
    _git_repo(here)
    folder = here.parent / "my-hooks"
    git_config.write_text(f"[core]\n\thooksPath = {folder.as_posix()}\n", encoding="utf-8")
    state = _turn_on(here, capsys, no_browser)
    assert not (here / ".git" / "hooks" / "pre-commit").exists()
    assert not folder.exists()
    at = state["lines"].index(f"Your git uses its own hooks folder ({folder.as_posix()}), so "
                              "judgekeeper left it as it is. To check before each commit, add "
                              "this line to the pre-commit hook there:")
    assert state["lines"][at + 1] == f"  uvx judgekeeper@{V} check --fast"
    _told(capsys)
    _, out = run(capsys)
    assert HOOKS_FOLDER_STATUS in out.splitlines()
    assert f"    uvx judgekeeper@{V} check --fast" in out.splitlines()


@needs_git
def test_a_hooks_path_naming_git_own_folder_gets_the_hook(here, capsys, no_browser, baseline,
                                                          by_uvx, git_config):
    _marked(here)
    _git_repo(here)
    git_config.write_text("[core]\n\thooksPath = .git/hooks\n", encoding="utf-8")
    state = _turn_on(here, capsys, no_browser)
    assert "Added a check before each git commit to .git/hooks/pre-commit." in state["lines"]


@needs_git
def test_the_status_sees_a_hooks_path_set_after_turning_on(here, capsys, no_browser, baseline,
                                                           by_uvx, git_config):
    _marked(here)
    _git_repo(here)
    _turn_on(here, capsys, no_browser)
    _told(capsys)
    git_config.write_text("[core]\n\thooksPath = ~/.githooks\n", encoding="utf-8")
    _, out = run(capsys)
    assert HOOKS_FOLDER_STATUS in out.splitlines()


def test_installed_elsewhere_no_local_path_reaches_a_shared_file(here, capsys, no_browser,
                                                                 baseline, monkeypatch):
    _marked(here)
    elsewhere = here.parent / "tools-env"
    monkeypatch.setattr(keep, "_prefix", lambda: elsewhere)
    (here / ".cursor").mkdir()
    config = "repos:\n- repo: local\n  hooks: []\n"
    (here / ".pre-commit-config.yaml").write_text(config, encoding="utf-8")
    state = _turn_on(here, capsys, no_browser)
    assert (here / ".pre-commit-config.yaml").read_text(encoding="utf-8") == config
    assert not (here / ".cursor" / "hooks.json").exists()  # a file a team may commit
    assert ("Cursor runs the agent hook in .claude/settings.local.json too." in state["lines"])


def test_the_persons_settings_are_kept(here, capsys, no_browser, baseline, by_uvx):
    _marked(here)
    (here / ".claude").mkdir()
    before = {"permissions": {"allow": ["Bash(npm test)"]},
              "hooks": {"PostToolUse": [{"matcher": "Edit", "hooks": [
                  {"type": "command", "command": "prettier"}]}]}, "model": "opus"}
    text = json.dumps(before, indent=2).replace("\n", "\r\n") + "\r\n"
    (here / ".claude" / "settings.local.json").write_bytes(text.encode())
    _turn_on(here, capsys, no_browser)
    raw = (here / ".claude" / "settings.local.json").read_bytes()
    assert b"\r\n" in raw and b"\n" not in raw.replace(b"\r\n", b"")
    after = json.loads(raw)
    assert list(after) == ["permissions", "hooks", "model"]
    assert after["permissions"] == before["permissions"] and after["model"] == "opus"
    assert after["hooks"]["PostToolUse"][0] == before["hooks"]["PostToolUse"][0]
    assert len(after["hooks"]["PostToolUse"]) == 3


def test_settings_that_cant_be_read_are_left_alone(here, capsys, no_browser, baseline, by_uvx):
    _marked(here)
    (here / ".claude").mkdir()
    (here / ".claude" / "settings.local.json").write_text("{not json", encoding="utf-8")
    state = _turn_on(here, capsys, no_browser)
    assert (here / ".claude" / "settings.local.json").read_text(encoding="utf-8") == "{not json"
    assert any(x.startswith(".claude/settings.local.json can't be read as JSON")
               for x in state["lines"])


def test_a_second_turn_on_adds_nothing_twice(here, capsys, no_browser, baseline, by_uvx):
    ws = _marked(here)
    (here / ".git" / "hooks").mkdir(parents=True)
    _turn_on(here, capsys, no_browser)
    settings = (here / ".claude" / "settings.local.json").read_text(encoding="utf-8")
    hook = (here / ".git" / "hooks" / "pre-commit").read_text(encoding="utf-8")
    session = keep.KeepSession(ws)
    session.posts["/turn-on"]({})
    session.wait()
    assert (here / ".claude" / "settings.local.json").read_text(encoding="utf-8") == settings
    assert (here / ".git" / "hooks" / "pre-commit").read_text(encoding="utf-8") == hook
    assert len(_checks(here)["added"]) == 2


def test_no_thanks_is_remembered(here, capsys, no_browser, pages, baseline):
    _marked(here)
    url = _offered(here, capsys, no_browser)
    answer = _call(url, "/no-thanks", {})
    assert answer["phase"] == "declined"
    data = _checks(here)
    assert data["on"] is False and data["declined"].endswith("Z") and data["by"] == "page"
    assert not (here / ".claude").exists() and baseline == []
    n = len(pages[0])
    code, out = run(capsys)
    assert code == 0
    assert OFF_LINE in out and KEEP_OPEN not in out
    assert "The judgekeeper page is still open." in out and "marking page" not in out
    assert assert_one_next_at_the_end(out) == NEXT_RESULT
    assert len(pages[0]) == n  # no page opened by itself
    code, out = run(capsys, "--stop")
    assert "Closed the judgekeeper page." in out


def test_no_thanks_keeps_what_off_left_behind(here, capsys, no_browser, pages, baseline,
                                              by_uvx):
    _marked(here)
    (here / ".git" / "hooks").mkdir(parents=True)
    _turn_on(here, capsys, no_browser)
    hook = here / ".git" / "hooks" / "pre-commit"
    hook.write_text(hook.read_text(encoding="utf-8").replace("|| exit $?", ""),
                    encoding="utf-8")
    run(capsys, "check", "--off")
    left = _checks(here)["added"]
    assert [a["file"] for a in left] == [".git/hooks/pre-commit"]
    run(capsys, "check", "--on")
    _call(no_browser[-1], "/no-thanks", {})
    assert _checks(here)["added"] == left
    run(capsys, "check", "--on")
    _call(no_browser[-1], "/turn-on", {})
    _done(no_browser[-1])
    assert left[0] in _checks(here)["added"]


def test_on_and_off_are_in_the_help(capsys):
    _, out = run(capsys, "check", "--help")
    assert "--on" in out and "--off" in out


# check --on ----------------------------------------------------------------------------------

def test_check_on_opens_the_turn_on_page(here, capsys, pages, no_browser):
    ws = _marked(here)
    (ws.dir / "checks.json").write_text(json.dumps({"on": False, "declined": "x", "by": "page"}),
                                        encoding="utf-8")
    code, out = run(capsys, "check", "--on")
    assert code == 0
    assert KEEP_OPEN in out
    assert assert_one_next_at_the_end(out) == NEXT_KEEP
    assert pages[0][-1]["view"] == "keep"
    assert _call(no_browser[-1], "/state")["phase"] == "ask"


def test_check_on_takes_a_port(here, capsys, pages, no_browser):
    _marked(here)
    code, _ = run(capsys, "check", "--on", "--port", "8790")
    assert code == 0
    assert pages[0][-1]["port"] == 8790


def test_check_on_needs_25_of_each(here, capsys, pages):
    _marked(here, n_pass=15, n_fail=25)
    code, out = run(capsys, "check", "--on")
    assert code == 3
    assert MARK_MORE in out
    assert assert_one_next_at_the_end(out) == (
        "Next: run `judgekeeper mark` and ask the person to mark answers until they have 25 "
        "Pass and 25 Fail.")
    assert pages[0] == []


def test_check_on_when_on_says_so(here, capsys, pages, no_browser, baseline, by_uvx):
    _marked(here)
    _turn_on(here, capsys, no_browser)
    n = len(pages[0])
    code, out = run(capsys, "check", "--on")
    assert code == 0
    assert "Automatic checks are already on." in out
    assert len(pages[0]) == n


def test_a_check_that_could_not_test_names_check_on(here, capsys, no_calls):
    _marked(here)
    _results(here, LENIENT, model=HAIKU, outputs=[f"new {i}" for i in range(50)])
    code, out = run(capsys, "check")
    assert code == 3
    assert assert_one_next_at_the_end(out) == (
        f"Next: tell the person their judge changed (model {MODEL} -> {HAIKU}) and none of "
        "their marked answers could be re-checked yet. To let judgekeeper ask their judge, run "
        "`judgekeeper check --on`: it opens a page where the person can turn on automatic "
        "checks.")


@pytest.fixture
def no_calls(monkeypatch):
    from judgekeeper import again

    def refuse(*args, **kwargs):
        raise AssertionError("the judge was asked")

    monkeypatch.setattr(again, "run_process", refuse)


# The status ----------------------------------------------------------------------------------

def test_after_the_click_judgekeeper_says_what_was_set_up_once(here, capsys, no_browser,
                                                               baseline, by_uvx):
    _marked(here)
    (here / ".git" / "hooks").mkdir(parents=True)
    _turn_on(here, capsys, no_browser)
    code, out = run(capsys)
    assert code == 0
    assert out.splitlines()[2:] == [
        "Automatic checks: ON. The person turned them on on the page, and judgekeeper:",
        "  Added the agent hook to .claude/settings.local.json.",
        "  Added a check before each git commit to .git/hooks/pre-commit.",
        ("  Asked your judge again about 50 marked answers: it changed its mind on 1 of your 50 "
         "marked answers."),
        "Keeping watch. Your marks stay on this computer (.judgekeeper/ is not in git).",
        "",
        ('Next: nothing. Tell the person: "judgekeeper will re-check your judge when it '
         'changes."'),
    ]
    _, again = run(capsys)
    assert "Automatic checks: ON since" in again


def test_the_status_when_checks_are_on(here, capsys, no_browser, baseline, by_uvx):
    _marked(here)
    (here / ".git" / "hooks").mkdir(parents=True)
    _turn_on(here, capsys, no_browser)
    _told(capsys)
    code, out = run(capsys)
    assert code == 0
    lines = out.splitlines()
    day = check._day(_checks(here)["since"])
    assert lines[2:] == [
        f"Automatic checks: ON since {day}, turned on by the person on the page.",
        "  Runs when: your judge changes (agent hook), and before each git commit (no AI call).",
        "  Uses: your own judge, through promptfoo, with the key your evals already use.",
        f"Your marks: 50 (25 Pass, 25 Fail), the newest from {day}.",
        "Last check: none yet.",
        "This set can see a drop of 30 points or more.",
        "Not checked automatically: new kinds of answers from your app (coming later).",
        "All checks: .judgekeeper/report.html (History)",
        "",
        f"To turn automatic checks off: uvx judgekeeper@{V} check --off",
        "",
        "Next: nothing. Tell the person what is on, and how to turn it off.",
    ]


def test_the_status_names_the_last_check(here, capsys, no_browser, baseline, by_uvx):
    _marked(here)
    _turn_on(here, capsys, no_browser)
    _told(capsys)
    _results(here, LENIENT, model=HAIKU)
    assert run(capsys, "check")[0] == 1
    code, out = run(capsys)
    assert code == 0
    day = check._day(_checks(here)["since"])
    assert (f"Last check: {day}, your judge changed (model {MODEL} -> {HAIKU}): worse on "
            "answers you failed.") in out.splitlines()


def test_the_status_says_when_the_judge_changed_since(here, capsys, no_browser, baseline,
                                                     by_uvx):
    _marked(here)
    _turn_on(here, capsys, no_browser)
    _told(capsys)
    _results(here, LENIENT, model=HAIKU)
    code, out = run(capsys)
    assert code == 0
    assert f"Your judge changed since your marks: model {MODEL} -> {HAIKU}." in out
    assert assert_one_next_at_the_end(out) == f"Next: run `uvx judgekeeper@{V} check`."


# check --off ---------------------------------------------------------------------------------

def test_off_removes_exactly_what_was_added(here, capsys, no_browser, baseline, by_uvx):
    ws = _marked(here)
    (here / ".claude").mkdir()
    mine = {"permissions": {"allow": ["Bash(ls)"]}}
    (here / ".claude" / "settings.local.json").write_text(json.dumps(mine, indent=2) + "\n",
                                                          encoding="utf-8")
    (here / ".cursor").mkdir()
    (here / ".git" / "hooks").mkdir(parents=True)
    hook = here / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\nmake lint\n", encoding="utf-8")
    _turn_on(here, capsys, no_browser)
    # Claude Code adds a permission of its own after Turn on
    settings = _settings(here)
    settings["permissions"]["allow"].append("Bash(npm test)")
    (here / ".claude" / "settings.local.json").write_text(json.dumps(settings, indent=2) + "\n",
                                                          encoding="utf-8")
    history = ws.history_jsonl.read_bytes()
    code, out = run(capsys, "check", "--off")
    assert code == 0
    assert out.splitlines()[2:] == [
        "Automatic checks: OFF.",
        ("Removed: the agent hook in .claude/settings.local.json, the agent hook in "
         ".cursor/hooks.json, the judgekeeper lines in .git/hooks/pre-commit."),
        "Kept: your marks and history in .judgekeeper/ (judgekeeper never deletes your marks).",
        f"To turn them on again, run `uvx judgekeeper@{V} check --on`.",
        "",
        "Next: nothing. Tell the person automatic checks are off.",
    ]
    assert _settings(here) == {"permissions": {"allow": ["Bash(ls)", "Bash(npm test)"]}}
    assert not (here / ".cursor" / "hooks.json").exists() and (here / ".cursor").is_dir()
    assert hook.read_text(encoding="utf-8") == "#!/bin/sh\nmake lint\n"
    data = _checks(here)
    assert data["on"] is False and data["added"] == [] and data["off"].endswith("Z")
    assert ws.marks.is_file() and ws.history_jsonl.read_bytes() == history


def test_off_gives_the_settings_back_as_they_were(here, capsys, no_browser, baseline, by_uvx):
    _marked(here)
    (here / ".claude").mkdir()
    text = '{\r\n    "env": {"FOO": "1"},\r\n    "model": "opus"\r\n}\r\n'
    settings = here / ".claude" / "settings.local.json"
    settings.write_bytes(text.encode())
    _turn_on(here, capsys, no_browser)
    assert b'\r\n        "PostToolUse"' in settings.read_bytes()  # its own indent kept
    run(capsys, "check", "--off")
    assert settings.read_bytes() == text.encode()


def test_off_removes_files_it_made(here, capsys, no_browser, baseline, by_uvx):
    _marked(here)
    (here / ".git" / "hooks").mkdir(parents=True)
    _turn_on(here, capsys, no_browser)
    run(capsys, "check", "--off")
    assert not (here / ".claude").exists()
    assert not (here / ".git" / "hooks" / "pre-commit").exists()


def test_off_leaves_a_file_changed_since_alone(here, capsys, no_browser, baseline, by_uvx):
    _marked(here)
    (here / ".git" / "hooks").mkdir(parents=True)
    _turn_on(here, capsys, no_browser)
    hook = here / ".git" / "hooks" / "pre-commit"
    changed = hook.read_text(encoding="utf-8").replace(" || exit $?", "")  # its block edited
    hook.write_text(changed, encoding="utf-8")
    code, out = run(capsys, "check", "--off")
    assert code == 0
    assert hook.read_text(encoding="utf-8") == changed
    assert ("Left as it is: .git/hooks/pre-commit (changed since judgekeeper added to it; "
            "remove the judgekeeper lines yourself).") in out.splitlines()
    assert "Removed: the agent hook in .claude/settings.local.json." in out.splitlines()


def test_off_takes_judgekeeper_out_of_the_requirements(here, capsys, no_browser, baseline,
                                                     monkeypatch):
    _marked(here)
    monkeypatch.setattr(keep, "_prefix", lambda: here / ".venv")
    text = '[project]\nname = "app"\n\n[dependency-groups]\ndev = [\n    "pytest",\n]\n'
    (here / "pyproject.toml").write_text(text, encoding="utf-8")
    _turn_on(here, capsys, no_browser)
    assert f'"judgekeeper=={V}"' in (here / "pyproject.toml").read_text(encoding="utf-8")
    code, out = run(capsys, "check", "--off")
    assert code == 0
    assert (here / "pyproject.toml").read_text(encoding="utf-8") == text
    assert "judgekeeper in the dev group in pyproject.toml" in out


def test_after_off_the_result_names_check_on(here, capsys, no_browser, pages, baseline,
                                             by_uvx):
    _marked(here)
    _turn_on(here, capsys, no_browser)
    run(capsys, "check", "--off")
    n = len(pages[0])
    _, out = run(capsys)
    assert f"Automatic checks: off. To turn them on, run `uvx judgekeeper@{V} check --on`." \
        in out
    assert len(pages[0]) == n


def test_off_when_never_on(here, capsys):
    _marked(here)
    code, out = run(capsys, "check", "--off")
    assert code == 0
    assert "Automatic checks are already off." in out
    assert not (here / ".judgekeeper" / "checks.json").exists()


def test_checks_json_stays_on_new(here, capsys, no_browser, baseline, by_uvx):
    from judgekeeper import start_again

    _marked(here)
    _turn_on(here, capsys, no_browser)
    assert "checks.json" in start_again.KEPT


# The agent hook, end to end ------------------------------------------------------------------

def test_the_agent_hook_end_to_end(here, capsys, no_browser, baseline, by_uvx, monkeypatch,
                                   no_calls):
    _marked(here)
    _turn_on(here, capsys, no_browser)
    hook = _hook_commands(_settings(here))[0]
    args = [a.replace("${CLAUDE_PROJECT_DIR}", str(here)) for a in hook["args"]]
    assert args[0] == f"judgekeeper@{V}"
    _results(here, LENIENT, model=HAIKU)
    monkeypatch.chdir(here.parent)  # a hook runs wherever the agent is
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({
        "hook_event_name": "PostToolUse", "tool_name": "Bash",
        "tool_input": {"command": "npx promptfoo eval"}})))
    code = main(args[1:])
    out = capsys.readouterr().out
    assert code == 0
    data = json.loads(out)
    assert "it now passes 9 answers you failed" in data["hookSpecificOutput"]["additionalContext"]
    assert data["systemMessage"].startswith("judgekeeper: your judge changed")


def test_the_hook_exits_0_on_any_error(here, capsys, monkeypatch):
    from judgekeeper import marks

    _marked(here)

    def broken(path):
        raise PermissionError(13, "Permission denied", str(path))

    monkeypatch.setattr(marks, "read", broken)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({
        "hook_event_name": "PostToolUse", "tool_name": "Bash"})))
    code = main(["check", "--hook"])
    out, err = capsys.readouterr()
    assert code == 0 and err == ""
    context = json.loads(out)["hookSpecificOutput"]["additionalContext"]
    assert context.startswith("judgekeeper could not check your judge: ")


# The report's History ------------------------------------------------------------------------

def test_the_report_has_a_history_row_per_check(here, capsys, no_calls):
    ws = _marked(here)
    run(capsys)  # the result: report.html
    _results(here, LENIENT, model=HAIKU)
    assert run(capsys, "check")[0] == 1
    html = ws.report_html.read_text(encoding="utf-8")
    assert "<h3>History</h3>" in html
    row = html.split("<h3>History</h3>")[1]
    assert f"model {MODEL} -&gt; {HAIKU}" in row
    assert "50 marks (50 free)" in row
    assert "Answers you failed: 100% → 64%" in row
    assert "Worse" in row and "exact" in row
    assert "<script" not in html


def test_the_report_has_no_history_before_a_check(here, capsys):
    ws = _marked(here)
    run(capsys)
    assert "<h3>History</h3>" not in ws.report_html.read_text(encoding="utf-8")


def test_history_rows(here):
    rows = keep.history_rows([
        {"time": "2026-10-19T10:00:00Z", "kind": "check", "trigger": "hook",
         "changed": ["model a -> b"], "marks": 50, "free": 12, "asked": 38, "exact": "close",
         "groups": {"passed": {"n": 25, "old": 0.96, "new": 0.92, "verdict": "no drop seen"},
                    "failed": {"n": 25, "old": 0.9, "new": 0.6, "verdict": "worse"}}},
        {"time": "2026-10-12T10:00:00Z", "kind": "check", "trigger": "baseline", "changed": [],
         "marks": 50, "free": 0, "asked": 50, "exact": "exact", "groups": None,
         "flipped": ["a"]},
        {"time": "2026-10-12T09:00:00Z", "kind": "result"},
    ])
    assert [r["changed"] for r in rows] == [
        "model a -> b", "Asked your judge once, to learn how steady it is"]
    assert rows[0]["tested"] == "50 marks (12 free, 38 asked again)"
    assert rows[0]["groups"] == ["Answers you passed: 96% → 92%",
                                 "Answers you failed: 90% → 60%"]
    assert rows[0]["verdict"] == "Worse" and rows[0]["exact"] == "close copy"
    assert rows[1]["verdict"] == "Changed its mind on 1 of 50"


# The page as its own process -----------------------------------------------------------------

@pytest.mark.real_page
def test_the_turn_on_page_runs_as_its_own_process(here, capsys, no_browser):
    from judgekeeper import background, label

    _marked(here)
    try:
        import socket

        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        code, out = run(capsys, "check", "--on", "--port", port)
        assert code == 0 and KEEP_OPEN in out
        html = _call(no_browser[-1], "/")
        assert "Keep checking your judge?" in html
        assert label.is_open(here / ".judgekeeper")
    finally:
        background.stop(here / ".judgekeeper")



def test_no_internal_words_in_the_code():
    import re
    from pathlib import Path

    import judgekeeper

    for path in Path(judgekeeper.__file__).parent.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"\bScene \d|walkthrough", text), path.name


def test_one_mark_is_said_as_one(here):
    (row,) = keep.history_rows([{"time": "2026-10-19T10:00:00Z", "kind": "check",
                                 "trigger": "baseline", "changed": [], "free": 0, "asked": 1,
                                 "exact": "exact", "groups": None, "flipped": []}])
    assert row["tested"] == "1 mark (1 asked again)"


def test_a_hook_error_reaches_the_agent_on_one_line(here, capsys, monkeypatch):
    from judgekeeper import marks

    _marked(here)

    def broken(path):
        raise ValueError("first line\nsecond line")

    monkeypatch.setattr(marks, "read", broken)
    monkeypatch.setattr(sys, "stdin", io.StringIO("{}"))
    assert main(["check", "--hook"]) == 0
    context = json.loads(capsys.readouterr().out)["hookSpecificOutput"]["additionalContext"]
    assert "\n" not in context and "first line" in context


def test_uvx_with_an_extra_runs_the_hooks_with_it(here, capsys, no_browser, baseline, by_uvx,
                                                  monkeypatch):
    monkeypatch.setattr(textio, "extras_here", lambda: ("mlflow",))
    _marked(here)
    (here / ".git" / "hooks").mkdir(parents=True)
    _turn_on(here, capsys, no_browser)
    (hook, _) = _hook_commands(_settings(here))
    assert hook["command"] == "uvx"
    assert hook["args"][:3] == ["--from", f"judgekeeper[mlflow]=={V}", "judgekeeper"]
    text = (here / ".git" / "hooks" / "pre-commit").read_text(encoding="utf-8")
    assert f"uvx --from 'judgekeeper[mlflow]=={V}' judgekeeper check --fast || exit $?" in text


# check --off acts only on the files Turn on writes ------------------------------------------------

def _forged(root, added) -> None:
    """checks.json as an agent could write it: on, listing whatever it likes."""
    data = {"on": True, "since": "2026-10-13T08:00:00Z", "by": "page", "sitting": "s1",
            "added": added}
    (root / ".judgekeeper" / "checks.json").write_text(json.dumps(data), encoding="utf-8")


def _outside(here, name: str, text: str):
    path = here.parent / f"{here.name}-{name}"
    path.write_text(text, encoding="utf-8")
    return path


NOT_OURS = "checks.json lists it, but judgekeeper did not add it there"


def test_off_never_touches_a_file_outside_the_project(here, capsys):
    _marked(here)
    gone = _outside(here, "delete.txt", "keep me\n")
    kept = _outside(here, "overwrite.txt", "mine\n")
    absolute = _outside(here, "absolute.txt", "mine too\n")
    _forged(here, [
        {"file": f"../{gone.name}", "kind": keep.COMMIT, "created": True, "block": "# x\n",
         "sha256": keep._sha("keep me\n")},
        {"file": f"../{kept.name}", "kind": keep.REQUIREMENT, "where": "x", "before": "PWNED\n",
         "sha256": keep._sha("mine\n")},
        {"file": str(absolute), "kind": keep.COMMIT, "created": True, "block": "# x\n",
         "sha256": keep._sha("mine too\n")},
        {"file": f"../{kept.name}", "kind": keep.AGENT_HOOK, "before": "PWNED\n",
         "sha256": keep._sha("mine\n"), "hooks": {}},
    ])
    code, out = run(capsys, "check", "--off")
    assert code == 0
    assert gone.read_text(encoding="utf-8") == "keep me\n"
    assert kept.read_text(encoding="utf-8") == "mine\n"
    assert absolute.read_text(encoding="utf-8") == "mine too\n"
    assert f"Left alone: ../{gone.name} ({NOT_OURS})." in out.splitlines()
    assert "Removed:" not in out


def test_off_never_touches_a_listed_file_that_is_not_ours(here, capsys):
    _marked(here)
    (here / "src").mkdir()
    app = here / "src" / "app.py"
    app.write_text("print('app')\n", encoding="utf-8")
    _forged(here, [{"file": "src/app.py", "kind": keep.COMMIT, "created": True, "block": "x",
                    "sha256": keep._sha("print('app')\n")},
                   {"file": "requirements.txt", "kind": keep.REQUIREMENT, "where": "x",
                    "before": "", "sha256": keep._sha("")}])
    (here / "requirements.txt").write_text("", encoding="utf-8")
    code, out = run(capsys, "check", "--off")
    assert code == 0 and app.is_file() and (here / "requirements.txt").is_file()
    assert f"Left alone: src/app.py ({NOT_OURS})." in out.splitlines()


def _link(link, target, folder=False) -> None:
    try:
        link.symlink_to(target, target_is_directory=folder)
    except (OSError, NotImplementedError):
        pytest.skip("this system can't make a symbolic link here")


def test_off_never_writes_through_a_link(here, capsys):
    _marked(here)
    target = _outside(here, "settings.json", "{}\n")
    (here / ".claude").mkdir()
    _link(here / ".claude" / "settings.local.json", target)
    _forged(here, [{"file": ".claude/settings.local.json", "kind": keep.AGENT_HOOK,
                    "before": "PWNED\n", "sha256": keep._sha("{}\n"), "hooks": {}}])
    code, out = run(capsys, "check", "--off")
    assert code == 0
    assert target.read_text(encoding="utf-8") == "{}\n"
    assert f"Left alone: .claude/settings.local.json ({NOT_OURS})." in out.splitlines()


def test_off_never_writes_through_a_linked_folder(here, capsys):
    _marked(here)
    folder = here.parent / f"{here.name}-hooks"
    folder.mkdir()
    (folder / "pre-commit").write_text("#!/bin/sh\n", encoding="utf-8")
    (here / ".git").mkdir()
    _link(here / ".git" / "hooks", folder, folder=True)
    _forged(here, [{"file": ".git/hooks/pre-commit", "kind": keep.COMMIT, "created": True,
                    "block": "x", "sha256": keep._sha("#!/bin/sh\n")}])
    assert run(capsys, "check", "--off")[0] == 0
    assert (folder / "pre-commit").read_text(encoding="utf-8") == "#!/bin/sh\n"


def test_off_never_crashes_on_a_malformed_entry(here, capsys):
    _marked(here)
    _forged(here, [{"file": "requirements-dev.txt", "kind": keep.REQUIREMENT, "before": "",
                    "sha256": "00"},
                   "not an entry", {"kind": keep.COMMIT}, {"file": ["x"], "kind": 3}])
    code, out = run(capsys, "check", "--off")
    assert code == 0
    assert "Automatic checks: OFF." in out
    assert "Left alone: requirements-dev.txt" in out


def test_turn_on_never_writes_through_a_linked_git_hook(here, capsys, no_browser, baseline,
                                                        by_uvx):
    _marked(here)
    target = _outside(here, "outside-hook.sh", "#!/bin/sh\nmake lint\n")
    (here / ".git" / "hooks").mkdir(parents=True)
    _link(here / ".git" / "hooks" / "pre-commit", target)
    state = _turn_on(here, capsys, no_browser)
    assert target.read_text(encoding="utf-8") == "#!/bin/sh\nmake lint\n"
    assert any(".git/hooks/pre-commit is a link" in x for x in state["lines"])
    assert [a["file"] for a in _checks(here)["added"]] == [".claude/settings.local.json"]


# Checks turned on by a file edit, not on the page --------------------------------------------------

def test_a_hand_written_checks_json_is_named_in_the_status(here, capsys):
    _marked(here)
    _forged(here, [])
    _, out = run(capsys)
    assert any(x.startswith("Automatic checks: ON since") and
               x.endswith("turned on by a file edit, not on the page.") for x in out.splitlines())


def test_the_click_is_recorded_by_the_page(here, capsys, no_browser, baseline, by_uvx):
    _marked(here)
    _turn_on(here, capsys, no_browser)
    from judgekeeper.start_label import Workspace

    assert keep.clicked(Workspace(here))
    _told(capsys)
    _, out = run(capsys)
    assert any(x.endswith("turned on by the person on the page.") for x in out.splitlines())
