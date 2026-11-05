"""Docs and website pull requests skip the heavy jobs. Code always runs them, the required checks
always report, and a failed `changes` job never skips anything."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ci_changes.py"
WORKFLOWS = ROOT / ".github" / "workflows"
MATRIX = {"ci.yml": ["test"], "windows.yml": ["test-windows-versions"]}
WHOLE = {"ci.yml": ["test-extras", "test-macos", "package"], "windows.yml": ["test-windows"]}
SKIPS = "needs.changes.outputs.code != 'false'"


def _says(*paths: str) -> str:
    return subprocess.run([sys.executable, str(SCRIPT)], input="\n".join(paths) + "\n", text=True,
                          capture_output=True, check=True).stdout.strip()


def _jobs(name: str) -> dict:
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))["jobs"]


@pytest.mark.parametrize("path", [
    "src/judgekeeper/cli.py", "tests/test_cli.py", "scripts/build_pages.py", "pyproject.toml",
    ".github/workflows/ci.yml", ".github/release-requirements.txt", "deploy/railway/Caddyfile",
    ".gitignore", "LICENSE", "a-new-folder/notes.md", "src/README.md", "tests/fixtures/a.md"])
def test_code_runs_everything(path):
    assert _says(path) == "code=true"
    assert _says("README.md", "website/index.html", path) == "code=true"  # with docs too


@pytest.mark.parametrize("paths", [
    ["website/index.html"], ["website/assets/style.css", "website/sitemap.xml"],
    ["docs/reference.md"], ["docs/examples/ragtruth/report.md"], ["README.md"],
    ["CHANGELOG.md", "SECURITY.md", "docs/eval-tools.md"]])
def test_docs_and_website_pages_are_not_code(paths):
    assert _says(*paths) == "code=false"


def test_no_paths_runs_everything():
    assert _says() == "code=true"


def test_a_path_git_had_to_quote_runs_everything():
    assert _says('"docs/caf\\303\\251.md"') == "code=true"


@pytest.mark.parametrize("name", ["ci.yml", "windows.yml"])
def test_only_a_pull_request_can_skip_and_a_rename_counts_both_ways(name):
    (*_, step) = _jobs(name)["changes"]["steps"]
    assert step["shell"] == "bash"  # with pipefail: a failed git diff fails the job
    assert 'if [ "$EVENT" = pull_request ]; then' in step["run"]
    assert "git diff --no-renames --name-only HEAD^1 HEAD" in step["run"]
    assert 'echo "code=true"' in step["run"]


@pytest.mark.parametrize("name", ["ci.yml", "windows.yml"])
def test_every_job_waits_for_changes_and_only_false_skips(name):
    jobs = _jobs(name)
    assert set(jobs) == {"changes", *MATRIX[name], *WHOLE[name]}
    for job in (*MATRIX[name], *WHOLE[name]):
        assert jobs[job]["needs"] == "changes"
        assert "!cancelled()" in jobs[job]["if"], job  # a failed `changes` never skips it
    for job in WHOLE[name]:
        assert SKIPS in jobs[job]["if"], job


@pytest.mark.parametrize("name", ["ci.yml", "windows.yml"])
def test_a_matrix_job_always_starts_so_each_required_check_reports(name):
    """A matrix job skipped whole reports one check with no version in its name, and the
    required `test (3.12)` would wait for ever: it starts, and its steps skip."""
    for job in MATRIX[name]:
        spec = _jobs(name)[job]
        assert spec["if"] == "${{ !cancelled() }}", job
        for step in spec["steps"]:
            assert "needs.changes.outputs.code" in step["if"], step


def test_the_docs_and_website_tests_run_in_a_required_check():
    (step,) = [s for s in _jobs("ci.yml")["test"]["steps"]
               if s.get("name") == "Test the docs and website"]
    assert step["if"] == "needs.changes.outputs.code == 'false' && matrix.python-version == '3.12'"
    listed = step["run"].split('"')[1]
    named = subprocess.run(["grep", "-lE", listed, *map(str, ROOT.glob("tests/test_*.py"))],
                           capture_output=True, text=True, check=True).stdout
    for test in ("test_website.py", "test_website_look.py", "test_site_shots.py", "test_docs.py",
                 "test_reference.py", "test_freecheck_page.py", "test_release.py"):
        assert test in named, test
