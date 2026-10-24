"""The docs: the reference, the README and the version. (The website's pages have their
tests in tests/test_website*.py.)
"""

from __future__ import annotations

import re
import tomllib

from judgekeeper import __version__
from tests.website_pages import ROOT

README = ROOT / "README.md"
REFERENCE = ROOT / "docs" / "reference.md"


def _sections(path) -> dict[str, str]:
    parts = re.split(r"^## ", path.read_text(encoding="utf-8"), flags=re.MULTILINE)
    return {part.splitlines()[0].strip(): part for part in parts[1:]}


# README, guide, skill --------------------------------------------------------------------

def test_the_readme_shows_pip_and_uv_as_equals_pip_first():
    sections = _sections(README)
    install = sections["Install"]
    pip = install.index(f"\ncd your-project\npip install judgekeeper=={__version__}\njudgekeeper\n")
    assert pip < install.index(f"\ncd your-project\nuvx judgekeeper@{__version__}\n")
    for tool in ("promptfoo", "DeepEval", "Inspect AI", "MLflow"):
        assert tool in sections["The 5 steps"], tool


# The version -----------------------------------------------------------------------------

def test_the_version_is_1_0_0b1_everywhere():
    main_toml = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert __version__ == main_toml["project"]["version"] == "1.0.0b2"


# Results in your own format, and after the first result ----------------------------------

def test_the_reference_explains_the_own_format():
    reference = " ".join(REFERENCE.read_text(encoding="utf-8").split())
    for needed in ("judge_model", "the columns it read", "judgekeeper.toml"):
        assert needed in reference, needed
    assert "calling a metric's `measure()` directly saves nothing" in reference


def test_see_your_result_shows_once_there_are_enough_marks():
    """The page shows the button only once there are enough marks of each kind."""
    reference = " ".join(REFERENCE.read_text(encoding="utf-8").split())
    assert "See your result" in reference
    assert "any time" not in reference.split("See your result", 1)[1][:80]
    assert "appears once there are enough marks of each kind" in reference
