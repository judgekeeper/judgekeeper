"""The keys in a project's .env files and promptfoo config are hidden however the results are
named, and the .env files are read with care: never through a link, never whole when huge.
"""

from __future__ import annotations

import os
import re
import time
import urllib.request
from pathlib import Path

import pytest

from judgekeeper import keys, redact
from judgekeeper.cli import main
from judgekeeper.start_label import Workspace
from tests import test_only_reads
from tests.test_only_reads import N, closed, judge, mark_all, write_results

LOCAL = "localMadeUpSecret" + "K9" * 7  # 31 characters
STAGING = "stagingMadeUpToken" + "Z4" * 6
COHERE = "cohereMadeUpValue" + "Q7" * 11 + "x"
SECRETS = (LOCAL, STAGING, COHERE)


@pytest.fixture
def here(tmp_path, monkeypatch):
    project = tmp_path / "support-bot"
    project.mkdir()
    monkeypatch.chdir(project)
    for name in ("LOCAL_SECRET", "APPENV_TOKEN", "COHERE_API_KEY", "APP_ENV"):
        monkeypatch.delenv(name, raising=False)
    return project


def _keys_at_the_root(root: Path, monkeypatch) -> None:
    """Keys in the root's .env.local, .env.staging (APP_ENV=staging) and promptfoo config, and
    answers that hold them."""
    monkeypatch.setenv("APP_ENV", "staging")
    (root / ".env.local").write_text(f"LOCAL_SECRET: {LOCAL}\n", encoding="utf-8")
    (root / ".env.staging").write_text(f"APPENV_TOKEN={STAGING}\n", encoding="utf-8")
    (root / "promptfooconfig.yaml").write_text(
        f"description: support bot\nenv:\n  COHERE_API_KEY: {COHERE}\n"
        "prompts:\n  - 'Answer: {{question}}'\n", encoding="utf-8")
    plain = test_only_reads.answer
    monkeypatch.setattr(test_only_reads, "answer",
                        lambda i: f"{plain(i)} Use {' and '.join(SECRETS)}." if i < 3 else plain(i))


def _state(out: str) -> str:
    link = re.search(r"http://127\.0\.0\.1:\d+/\?token=[\w-]+", out)[0]
    base, token = link.split("/?token=")
    with urllib.request.urlopen(f"{base}/state?token={token}", timeout=10) as r:
        return r.read().decode("utf-8")


# Keys at the project's root, results named in a folder below it --------------------------------

@pytest.mark.parametrize("tool, named, command", [
    ("promptfoo", "evals/results.json", []),
    ("deepeval", "results/test_run_20261027_101500.json", []),
    ("mlflow", "stores/mlflow.db", ["mark"]),
])
def test_root_keys_are_hidden_when_results_below_are_named(tool, named, command, here, capsys,
                                                          monkeypatch):
    _keys_at_the_root(here, monkeypatch)
    write_results(tool, here / named, {i: judge(i) for i in range(N)})
    code = main([*command, named, "--no-browser", "--port", "0"])
    out, err = capsys.readouterr()
    assert code == 0, out + err
    ws = Workspace(here)
    state = _state(out)  # the first batch
    mark_all(ws)
    closed(ws)
    code = main([named, "--no-browser", "--port", "0"])  # Measure: too few to tell yet
    assert code == 3, "".join(capsys.readouterr())
    assert main(["fix"]) == 0
    out += "".join(capsys.readouterr())
    saved = {p.name: p.read_text(encoding="utf-8", errors="replace")
             for p in ws.dir.rglob("*") if p.is_file()}
    for name in ("pool.jsonl", "pool-judge.jsonl", "report.html", "mistakes.md",
                 "marked-answers.csv"):
        assert name in saved, sorted(saved)
    assert redact.REDACTED in saved["pool.jsonl"]
    for value in SECRETS:
        assert value not in out and value not in state
        assert [n for n, text in saved.items() if value in text] == []


# A .env that is a link, or huge -----------------------------------------------------------------

def _link(link: Path, target: Path) -> None:
    try:
        os.symlink(target, link)
    except (OSError, NotImplementedError):
        pytest.skip("this system cannot make links")


@pytest.mark.parametrize("name", [".env", ".env.local", ".env.staging"])
def test_a_env_linked_to_a_huge_file_is_skipped_at_once(here, monkeypatch, name):
    monkeypatch.setenv("APP_ENV", "staging")
    huge = here.parent / "huge"
    with huge.open("wb") as f:
        f.truncate(50 * 2**20)  # 50 MB, sparse
    _link(here / name, huge)
    start = time.monotonic()
    keys.hide_keys(here)
    assert time.monotonic() - start < 1
    note = keys.LINKED.format(file=name)
    assert keys.unsaid() == [note]
    keys.hide_keys(here)
    assert keys.notes() == [note] and keys.unsaid() == []  # noted and said once


def test_a_env_linked_outside_the_project_is_not_read(here):
    creds = here.parent / "outside" / "creds"
    creds.parent.mkdir()
    creds.write_text(f"AWS_SECRET_ACCESS_KEY={LOCAL}\n", encoding="utf-8")
    _link(here / ".env", creds)
    assert keys.names_in(here / ".env") == set()
    keys.hide_keys(here)
    assert redact.scrub(LOCAL) == LOCAL  # never read, so never registered


def test_a_env_over_1_mb_is_not_read(here):
    (here / ".env").write_text(f"LOCAL_SECRET={LOCAL}\n" + "# padding\n" * 2**17,
                               encoding="utf-8")
    assert (here / ".env").stat().st_size > keys.FILE_LIMIT
    keys.hide_keys(here)
    assert keys.notes() == [keys.TOO_BIG.format(file=".env")]
    assert redact.scrub(LOCAL) == LOCAL
    (here / ".env").write_text(f"LOCAL_SECRET={LOCAL}\n", encoding="utf-8")
    keys.hide_keys(here)
    assert redact.scrub(LOCAL) == redact.REDACTED


def test_a_linked_or_huge_config_is_not_read(here):
    outside = here.parent / "config.yaml"
    outside.write_text(f"env:\n  COHERE_API_KEY: {COHERE}\n", encoding="utf-8")
    _link(here / "promptfooconfig.yaml", outside)
    assert keys.config_env(here / "promptfooconfig.yaml") == {}
    big = here / "big.yaml"
    big.write_text(f"env:\n  COHERE_API_KEY: {COHERE}\n" + "# x\n" * 2**19, encoding="utf-8")
    assert keys.config_env(big) == {}
    assert keys.notes() == [keys.LINKED.format(file="promptfooconfig.yaml"),
                            keys.TOO_BIG.format(file="big.yaml")]


def test_judgekeeper_says_once_that_a_linked_env_was_not_read(here, capsys):
    from tests.start_projects import promptfoo_project, split

    promptfoo_project(here, split(20, 16))
    outside = here.parent / "creds"
    outside.write_text("AWS_SECRET_ACCESS_KEY=x\n", encoding="utf-8")
    _link(here / ".env", outside)
    assert main(["--no-browser", "--port", "0"]) == 0
    said = " ".join("".join(capsys.readouterr()).split())
    assert said.count(keys.LINKED.format(file=".env")) == 1, said
