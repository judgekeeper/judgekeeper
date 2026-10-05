"""Repository hygiene checks that guard CI on a fresh clone."""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True,
                          check=True).stdout


def _in_git_checkout() -> bool:
    if shutil.which("git") is None:
        return False
    try:
        return _git("rev-parse", "--is-inside-work-tree").strip() == "true"
    except subprocess.CalledProcessError:
        return False


@pytest.mark.skipif(not _in_git_checkout(), reason="not a git checkout")
def test_every_fixture_file_is_tracked():
    """A .gitignore rule once hid fixture runs: tests passed locally and failed on a clone."""
    on_disk = {
        p.relative_to(ROOT).as_posix()
        for p in FIXTURES.rglob("*")
        if p.is_file() and "__pycache__" not in p.parts
    }
    tracked = set(_git("ls-files", "-z", "--", "tests/fixtures").split("\0")) - {""}
    untracked = sorted(on_disk - tracked)
    assert not untracked, f"fixture files not tracked by git (check .gitignore): {untracked}"
