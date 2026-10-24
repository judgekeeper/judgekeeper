"""1.0 is commands a person runs. judgekeeper writes only inside .judgekeeper/: a whole run
(the first look, marking, the result, a re-check that asks the judge) on a git project leaves
every other file as it was, `.claude/`, `.cursor/`, `.git/hooks/` and `.pre-commit-config.yaml`
included. There is no page that turns on automatic checks, and the flags that served them
(`check --on`, `--off`, `--hook`, `--fast`, `--ci`, `--baseline`, `--port`) are a usage error
with one `Next:` line.
No test calls an API: the re-check asks the fake promptfoo of test_again_run.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import shutil
import subprocess
import urllib.error
import urllib.request

import pytest

from judgekeeper.cli import main
from judgekeeper.start_label import StartSession, Workspace
from tests.page_http import retried
from tests.test_check import HAIKU, LENIENT, TAG, _new_outputs, _results, judge  # noqa: F401
from tests.test_front import assert_one_next_at_the_end

MARKED_25 = [True] * 25 + [False] * 25


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _tree(root) -> dict[str, str]:
    """Every file outside .judgekeeper/ (in .git/ only its hooks and config): path -> hash."""
    out = {}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        if rel == ".judgekeeper" or rel.startswith(".judgekeeper/"):
            continue
        if rel.startswith(".git/") and not (rel.startswith(".git/hooks") or rel == ".git/config"):
            continue
        out[rel] = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else "dir"
    return out


def _git_project(root) -> None:
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    (root / ".claude").mkdir()
    (root / ".claude" / "settings.json").write_text("{}\n", encoding="utf-8")
    (root / ".cursor").mkdir()
    (root / ".pre-commit-config.yaml").write_text("repos: []\n", encoding="utf-8")
    (root / "requirements-dev.txt").write_text("pytest\n", encoding="utf-8")
    (root / "promptfooconfig.yaml").write_text("description: support bot\n", encoding="utf-8")


def _mark_all(root) -> None:
    session = StartSession(Workspace(root))
    for q in Workspace(root).data()["queue"]:
        session.update({"id": q["id"], "label": q["group"], "seconds": 5})


def _cli(capsys, *argv):
    code = main([str(a) for a in argv])
    out, err = capsys.readouterr()
    assert TAG.strip() not in out + err
    return code, out, err


@pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
def test_a_whole_run_changes_nothing_outside_judgekeeper(here, capsys, judge):  # noqa: F811
    _git_project(here)
    _results(here, MARKED_25)
    before = _tree(here)
    assert _cli(capsys)[0] == 0  # the first look; the page opens
    _mark_all(here)
    code, out, _ = _cli(capsys)  # the result, with 25 Pass and 25 Fail
    assert code == 0, out
    assert "automatic" not in out.lower()
    assert _cli(capsys, "mark")[0] == 0
    assert _cli(capsys, "--stop")[0] == 0
    assert _tree(here) == before
    _results(here, LENIENT, model=HAIKU, outputs=_new_outputs())  # the person changed the judge
    before = _tree(here)
    code, out, _ = _cli(capsys, "check", "--yes")
    assert code == 1, out
    assert "will have your new LLM-as-a-judge grade" in out and "Agreed with you:" in out
    assert _tree(here) == before
    assert not (here / ".claude" / "settings.local.json").exists()
    assert not (here / ".cursor" / "hooks.json").exists()
    assert not (here / ".git" / "hooks" / "pre-commit").exists()
    assert not (here / ".judgekeeper" / "checks.json").exists()


@pytest.mark.parametrize("flags", [["--on"], ["--off"], ["--hook"], ["--fast"], ["--ci"],
                                   ["--baseline"], ["--port", "9000"]])
def test_a_removed_check_flag_is_a_usage_error_with_one_next_line(here, capsys, flags):
    code, out, err = _cli(capsys, "check", *flags)
    assert code == 2
    assert "Traceback" not in out + err
    assert f"unrecognized arguments: {flags[0]}" in err
    assert assert_one_next_at_the_end(out + err) == (
        "Next: run `judgekeeper check --help` to see the options.")


def test_check_help_shows_only_the_path_and_yes(capsys):
    assert main(["check", "--help"]) == 0
    out = capsys.readouterr().out
    options = set(re.findall(r"--[a-z-]+", out))
    assert options == {"--help", "--yes"}


def test_the_hook_and_dev_requirement_code_is_gone():
    for name in ("judgekeeper.keep", "judgekeeper.dev_requirements"):
        assert importlib.util.find_spec(name) is None, name


def test_the_marking_page_has_no_turn_on(here, capsys, no_browser):
    _results(here, MARKED_25)
    assert _cli(capsys)[0] == 0
    base, token = no_browser[-1].split("/?token=")
    for path in ("/turn-on", "/no-thanks"):
        req = urllib.request.Request(
            f"{base}{path}?token={token}", data=json.dumps({}).encode(),
            headers={"Content-Type": "application/json", "Origin": base})
        with pytest.raises(urllib.error.HTTPError) as e:
            retried(lambda req=req: urllib.request.urlopen(req, timeout=10))
        assert e.value.code == 404, path


def test_a_post_without_the_pages_origin_writes_no_mark(here, capsys, no_browser):
    _results(here, MARKED_25)
    assert _cli(capsys)[0] == 0
    base, token = no_browser[-1].split("/?token=")
    item = Workspace(here).data()["queue"][0]["id"]
    req = urllib.request.Request(
        f"{base}/label?token={token}", data=json.dumps({"id": item, "label": "pass"}).encode(),
        headers={"Content-Type": "application/json"})
    with pytest.raises(urllib.error.HTTPError) as e:
        retried(lambda: urllib.request.urlopen(req, timeout=10))
    assert e.value.code == 403
    marks = Workspace(here).marks
    assert not marks.exists() or '"label"' not in marks.read_text(encoding="utf-8")


def test_no_message_tells_an_agent_what_to_say_to_the_person():
    """Every message speaks to the person: none says "tell the person" or "ask the person"
    (the strings in the code, so a rarely printed line is checked too)."""
    import ast
    from pathlib import Path

    import judgekeeper

    for path in Path(judgekeeper.__file__).parent.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                text = " ".join(node.value.lower().split())
                for words in ("tell the person", "ask the person", "give the person"):
                    assert words not in text, (path.name, node.lineno, node.value[:80])
