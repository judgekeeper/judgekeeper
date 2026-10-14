"""Release preparation: versions, workflows, packaging, the website build and the guide.

Nothing here publishes or calls a network service. The release workflow is parsed, never run.
"""

import importlib.util
import json
import re
import subprocess
import sys
import tarfile
import tomllib
import zipfile
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = ROOT / ".github" / "workflows"
VERSION = "1.0.0b2"
BETA = "Development Status :: 4 - Beta"
EXAMPLE = ROOT / "docs" / "examples" / "llmbar-haiku"


def _toml(path):
    return tomllib.loads(path.read_text(encoding="utf-8"))


def _workflow(name):
    data = yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))
    # YAML 1.1 reads the key `on` as True.
    data["on"] = data.pop(True, data.get("on"))
    return data


def _steps_text(job: dict) -> str:
    return "\n".join(json.dumps(step) for step in job.get("steps", []))


# The version and the distribution

def test_versions_agree():
    from judgekeeper import __version__

    main = _toml(ROOT / "pyproject.toml")["project"]
    assert main["version"] == __version__ == VERSION
    assert BETA in main["classifiers"]
    for minor in ("3.11", "3.12", "3.13", "3.14"):
        assert f"Programming Language :: Python :: {minor}" in main["classifiers"]


def test_no_pytest_plugin_and_no_api_extras():
    main = _toml(ROOT / "pyproject.toml")["project"]
    assert "entry-points" not in main
    assert not [c for c in main["classifiers"] if "Pytest" in c]
    assert set(main["optional-dependencies"]) == {"dev", "inspect", "mlflow"}
    assert not (ROOT / "packages").exists()


def test_there_is_no_github_action():
    """1.0 is commands a person runs: no action.yml, its fixtures or its CI job."""
    assert not (ROOT / "action.yml").exists()
    assert not (ROOT / "tests" / "fixtures" / "action").exists()
    assert "action" not in _workflow("ci.yml")["jobs"]


def test_changelog_leads_with_this_version():
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    entries = re.findall(r"^## (\S+)", text, flags=re.MULTILINE)
    assert entries == [VERSION, "1.0.0b1", "0.1.3", "0.1.2", "0.1.1", "0.1.0"]


# Workflows

def test_release_workflow_runs_only_on_a_published_release():
    wf = _workflow("release.yml")
    assert wf["on"] == {"release": {"types": ["published"]}}
    assert wf.get("permissions") == {"contents": "read"}


def _publish_jobs(wf: dict) -> dict:
    return {name: j for name, j in wf["jobs"].items()
            if "pypa/gh-action-pypi-publish" in _steps_text(j)}


def _env_name(job: dict) -> str:
    env = job["environment"]
    return env if isinstance(env, str) else env["name"]


def test_release_workflow_uses_trusted_publishing_and_no_tokens():
    text = (WORKFLOWS / "release.yml").read_text(encoding="utf-8")
    assert "secrets." not in text and "password" not in text and "PYPI_API_TOKEN" not in text
    wf = _workflow("release.yml")
    publish = _publish_jobs(wf)
    assert [_env_name(j) for j in publish.values()] == ["pypi"]
    for job in publish.values():
        assert job["permissions"] == {"id-token": "write"}
    for name, other in wf["jobs"].items():
        if name not in publish:
            assert "id-token" not in (other.get("permissions") or {}), name


def test_release_workflow_builds_checks_and_tests_the_wheel():
    wf = _workflow("release.yml")
    text = "\n".join(_steps_text(j) for j in wf["jobs"].values())
    assert "python -m build" in text and "pytest-judgekeeper" not in text
    assert "twine check" in text
    assert "venv" in text and "pytest" in text and ".whl" in text
    for publish in _publish_jobs(wf).values():
        assert publish.get("needs")  # publishes only what the build job built and tested


def test_ci_builds_and_runs_the_installed_wheel_on_every_push():
    wf = _workflow("ci.yml")
    assert "push" in wf["on"]
    text = "\n".join(_steps_text(j) for j in wf["jobs"].values())
    for needed in ("python -m build", "venv", "judgekeeper --version", "judgekeeper --help",
                   "judgekeeper start --help", "judgekeeper.record(", ".judgekeeper/records",
                   "twine check"):
        assert needed in text, needed
    assert "demo" not in text and "pytest-judgekeeper" not in text


def test_release_runs_the_installed_wheel_end_to_end_before_publishing():
    text = "\n".join(_steps_text(j) for j in _workflow("release.yml")["jobs"].values())
    for needed in ("judgekeeper --version", "judgekeeper --help", "judgekeeper mark --help",
                   "judgekeeper.record(", ".judgekeeper/records"):
        assert needed in text, needed
    assert "demo" not in text


def test_ci_tests_every_python_the_classifiers_name_and_windows_on_every_pull_request():
    wf = _workflow("ci.yml")
    classifiers = _toml(ROOT / "pyproject.toml")["project"]["classifiers"]
    named = sorted(c.rsplit(" ", 1)[1] for c in classifiers
                   if re.fullmatch(r"Programming Language :: Python :: 3\.\d+", c))
    assert sorted(wf["jobs"]["test"]["strategy"]["matrix"]["python-version"]) == named
    assert wf["jobs"]["test"]["runs-on"] == "ubuntu-latest"
    assert not [j for j in wf["jobs"].values() if j["runs-on"] == "windows-latest"]
    # Windows runs on every pull request and every push to main, and by hand.
    win = _workflow("windows.yml")
    on = win["on"]
    assert set(on) == {"pull_request", "push", "workflow_dispatch"}
    assert on["push"] == {"branches": ["main"]}
    (job,) = win["jobs"].values()
    assert job["runs-on"] == "windows-latest" and "pytest" in _steps_text(job)
    (python,) = [s for s in job["steps"] if s.get("uses", "").startswith("actions/setup-python@")]
    assert str(python["with"]["python-version"]) == "3.12"
    assert "not yet a supported platform" not in (WORKFLOWS / "windows.yml").read_text(
        encoding="utf-8")


def test_ci_runs_the_background_page_on_macos():
    """The marking page runs as its own process; the unit tests run on Linux and Windows,
    so its real-process test also runs on macOS."""
    job = _workflow("ci.yml")["jobs"]["test-macos"]
    assert job["runs-on"] == "macos-latest"
    assert "pytest" in _steps_text(job) and "tests/test_mark_background.py" in _steps_text(job)


# Packaging

def _build_wheel(src: Path, out: Path) -> Path:
    if importlib.util.find_spec("build") is None or importlib.util.find_spec("hatchling") is None:
        pytest.skip("needs the build and hatchling packages (the dev extra)")
    subprocess.run([sys.executable, "-m", "build", "--wheel", "--no-isolation", "--outdir",
                    str(out), str(src)], check=True, capture_output=True)
    (wheel,) = out.glob("*.whl")
    return wheel


def test_wheel_ships_the_package_and_no_demo(tmp_path):
    wheel = _build_wheel(ROOT, tmp_path)
    assert wheel.name == f"judgekeeper-{VERSION}-py3-none-any.whl"
    names = set(zipfile.ZipFile(wheel).namelist())
    for needed in ("judgekeeper/label.py", "judgekeeper/start.py",
                   "judgekeeper/schemas/records.schema.json",
                   "judgekeeper/fonts/bricolage-grotesque-latin-600-normal.woff2",
                   "judgekeeper/fonts/bricolage-grotesque-latin-800-normal.woff2",
                   "judgekeeper/fonts/OFL-BricolageGrotesque.txt"):  # the page's font, OFL
        assert needed in names, needed
    for gone in ("judgekeeper/demo_data/", "judgekeeper/demo.py", "judgekeeper/templates/",
                 "judgekeeper/pytest_plugin.py", "judgekeeper/gate.py"):
        assert not any(name.startswith(gone) for name in names), gone
    dist_info = f"judgekeeper-{VERSION}.dist-info"
    entry_points = zipfile.ZipFile(wheel).read(f"{dist_info}/entry_points.txt").decode()
    assert "[pytest11]" not in entry_points and "judgekeeper.cli:main" in entry_points
    assert f"{dist_info}/licenses/LICENSE" in names


def _build_sdist(src: Path, out: Path) -> list[str]:
    """The paths inside the built sdist, without the leading `<name>-<version>/` folder."""
    if importlib.util.find_spec("build") is None or importlib.util.find_spec("hatchling") is None:
        pytest.skip("needs the build and hatchling packages (the dev extra)")
    subprocess.run([sys.executable, "-m", "build", "--sdist", "--no-isolation", "--outdir",
                    str(out), str(src)], check=True, capture_output=True)
    (sdist,) = out.glob("*.tar.gz")
    with tarfile.open(sdist) as tar:
        return sorted(name.split("/", 1)[1] for name in tar.getnames() if "/" in name)


# hatchling always adds the metadata file and the .gitignore it read its exclusions from.
SDIST_ALWAYS = {"PKG-INFO", ".gitignore"}
NOT_IN_SDIST = ("docs/", "tests/", "website/", "scripts/", "deploy/", ".github/", "skills/",
                "packages/", "prompts/", "SECURITY.md", "action.yml")


def test_sdist_holds_only_the_package_and_its_readme_licence_and_changelog(tmp_path):
    names = _build_sdist(ROOT, tmp_path)
    top = {"README.md", "LICENSE", "TRADEMARKS.md", "CHANGELOG.md", "pyproject.toml"}
    for name in names:
        assert name in top | SDIST_ALWAYS or name.startswith("src/judgekeeper/"), name
        assert not name.startswith(NOT_IN_SDIST), name
        assert "__pycache__" not in name and not name.endswith(".DS_Store"), name
    assert top <= set(names)
    # Every packaged source file is there, so a wheel built from the sdist is the same wheel.
    package = ROOT / "src" / "judgekeeper"
    for path in package.rglob("*"):
        if path.is_file() and "__pycache__" not in path.parts and path.name != ".DS_Store":
            assert f"src/judgekeeper/{path.relative_to(package).as_posix()}" in names, path


def test_release_workflows_test_the_wheels_from_the_checkout_not_the_sdist():
    """The sdist ships no tests, so the workflows must run the suite from the checkout."""
    for name in ("release.yml", "ci.yml"):
        text = (WORKFLOWS / name).read_text(encoding="utf-8")
        assert "actions/checkout@" in text
        assert ".tar.gz" not in text and "tar x" not in text, name
        assert '-m pytest -p no:cacheprovider' in text, name


# The website build

def _build_pages(out: Path) -> None:
    spec = importlib.util.spec_from_file_location("build_pages",
                                                  ROOT / "scripts" / "build_pages.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.build(ROOT / "website", ROOT / "docs" / "examples", out)


def test_pages_site_is_the_website_with_each_report_under_examples(tmp_path):
    _build_pages(tmp_path)
    assert (tmp_path / "index.html").read_bytes() == (ROOT / "website" / "index.html").read_bytes()
    assert not (tmp_path / "examples.html").exists()
    for page in ("start.html", "learn.html", "setup.html",
                 "reference.html", "llms.txt", "assets/style.css"):
        assert (tmp_path / page).is_file(), page
    assert not (tmp_path / "README.md").exists()
    banner = "assets/social-preview.png"  # the picture in link previews; og:image points at it
    assert (tmp_path / banner).read_bytes() == (ROOT / "website" / banner).read_bytes()
    for name in ("index.html", "report.html"):
        report = tmp_path / "examples" / "llmbar-haiku" / name
        assert report.read_bytes() == (EXAMPLE / "report.html").read_bytes()
    index = (tmp_path / "examples" / "index.html").read_text(encoding="utf-8")
    assert index.startswith("<!doctype html>")
    assert 'href="llmbar-haiku/"' in index
    assert "http" not in index.replace("http-equiv", "")  # no external assets
    assert (tmp_path / ".nojekyll").is_file()
    assert not (tmp_path / "CNAME").exists()  # the build sets no custom domain


# README and the guide (the short README's own contract is in test_front_door.py)

def _guide() -> str:
    return (ROOT / "docs" / "guide.md").read_text(encoding="utf-8")


def test_changelog_entry_says_what_keeps_checking():
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    entry = text[text.index(f"## {VERSION}"):text.index("## 1.0.0b1")]
    assert len(entry.strip().splitlines()) < 20
    flat = " ".join(entry.split())
    for needed in (f"`uvx judgekeeper@{VERSION}`", f"`pip install judgekeeper=={VERSION}`",
                   "`judgekeeper check`", "`judgekeeper check --off`", "Only your click",
                   "History", "`action.yml`", "`mode: fast`", "`mode: full`", "skill"):
        assert needed in flat, needed


def test_changelog_entry_says_what_changed_since_0_1_3():
    """0.2.0 was never released: the first beta's entry says what changed from 0.1.3."""
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    beta = "1.0.0b1"
    entry = text[text.index(f"## {beta}"):text.index("## 0.1.3")]
    assert len(entry.strip().splitlines()) < 20
    assert "## 0.2.0" not in text
    flat = " ".join(entry.split())
    for needed in (f"`uvx judgekeeper@{beta}`", f"`pip install judgekeeper=={beta}`",
                   "`judgekeeper mark`",
                   "your browser", "TPR, TNR and kappa", "skills/judgekeeper/SKILL.md",
                   "no AI call", "beta", "Removed:", "the pytest plugin", "the GitHub Action"):
        assert needed in flat, needed
    for name in ("init", "freeze", "judge", "validate", "baseline", "gate", "migrate", "check",
                 "template", "import-labels", "label", "import", "export", "attribute", "demo"):
        assert f"`{name}`" in flat, name


def test_older_changelog_entries_stay_as_they_were_written():
    """An entry is history: 0.1.2 keeps the headline it shipped with."""
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    entry = text[text.index("## 0.1.2"):text.index("## 0.1.1")]
    for needed in ("Your AI judge grades your app. judgekeeper grades the judge.", "README",
                   "docs/guide.md", "--help", "plain", "Nothing was removed or renamed"):
        assert needed in entry, needed


def test_readme_covers_uvx_and_pip_and_names_no_hidden_command():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert f"\nuvx judgekeeper@{VERSION}\n" in readme
    assert f"\npip install judgekeeper=={VERSION}\n" in readme
    assert "beta" in readme
    for gone in ("judgekeeper start", "judgekeeper demo", "before the first PyPI release"):
        assert gone not in readme, gone
    for needed in ("TPR", "TNR", "kappa"):
        assert needed in readme, needed


def test_every_install_command_names_the_version_in_pyproject():
    """uv and pip skip betas unless the version is named: `uvx judgekeeper` and `pip install
    judgekeeper` would get 0.1.3. README and the changelog's newest entry name the
    exact version in pyproject.toml, so the next beta can't forget it."""
    version = _toml(ROOT / "pyproject.toml")["project"]["version"]
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    texts = {"README.md": (ROOT / "README.md").read_text(encoding="utf-8"),
             "CHANGELOG.md": changelog[:changelog.index("## ", changelog.index("## ") + 3)]}
    for name, text in texts.items():
        uvx = re.findall(r"uvx judgekeeper(@[\w.]+)?", text)
        pip = re.findall(r"pip install judgekeeper(==[\w.]+)?", text)
        assert uvx and set(uvx) == {f"@{version}"}, (name, uvx)
        assert set(pip) <= {f"=={version}"}, (name, pip)
    assert re.findall(r"pip install judgekeeper(==[\w.]+)?", texts["README.md"])


def test_readme_has_no_link_to_the_website_while_it_is_offline():
    """PyPI shows the README; the website stays offline until it is rewritten."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "judgekeeper.com" not in readme
    blob = "https://github.com/judgekeeper/judgekeeper/blob/main/docs/examples/"
    for example in ("real-data-check/report.md", "coverage/coverage.md"):
        assert f"]({blob}{example})" in readme, example
    assert "](https://github.com/judgekeeper/judgekeeper/tree/main/docs/examples/llmbar-haiku)" \
        in readme


def test_guide_links_the_published_report_and_the_file():
    guide = _guide()
    assert "https://www.judgekeeper.com/examples/llmbar-haiku/" in guide
    assert "](examples/llmbar-haiku/report.html)" in guide


def test_docs_do_not_point_at_the_unused_pages_address():
    for path in (ROOT / "README.md", ROOT / "docs" / "guide.md"):
        assert "judgekeeper.github.io" not in path.read_text(encoding="utf-8"), path


def test_package_metadata_links_the_repo_while_the_website_is_offline():
    """PyPI shows these links. The README is the documentation until the website is back."""
    urls = _toml(ROOT / "pyproject.toml")["project"]["urls"]
    assert urls["Homepage"] == "https://github.com/judgekeeper/judgekeeper"
    assert urls["Source"] == "https://github.com/judgekeeper/judgekeeper"
    assert "Documentation" not in urls
    assert urls["Issues"] == "https://github.com/judgekeeper/judgekeeper/issues"
    assert not [u for u in urls.values() if "judgekeeper.com" in u]


def test_contributing_says_issues_not_pull_requests_and_how_to_report_privately():
    text = (ROOT / ".github" / "CONTRIBUTING.md").read_text(encoding="utf-8")
    assert "does not accept pull requests" in text
    assert "https://github.com/judgekeeper/judgekeeper/security/advisories/new" in text
    assert "Never paste API keys" in text


def _first_results() -> str:
    text = _guide()
    start = text.index("## First results")
    return text[start:text.index("\n## ", start + 1)]


def test_first_results_lead_with_the_measured_claim():
    report = json.loads((EXAMPLE / "report.json").read_text(encoding="utf-8"))
    slices = {s["slice"]: s for s in report["slices"]}
    natural = f"{slices['Natural']['kappa_mean']:.2f}"
    gptout = f"{slices['Adversarial/GPTOut']['kappa_mean']:.2f}"
    section = _first_results()
    lead = section.split("\n\n")[1]
    assert natural in lead and gptout in lead
    assert "Natural" in lead and "GPTOut" in lead
    assert "docs/examples/llmbar-haiku/" in lead


def test_first_results_numbers_come_from_the_committed_report():
    report = json.loads((EXAMPLE / "report.json").read_text(encoding="utf-8"))
    section = _first_results()
    rows = {}
    for line in section.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 4 and re.fullmatch(r"\d\.\d\d", cells[-1]):
            rows[cells[0]] = [float(c) for c in cells[-3:]]
    for run in report["runs"]:
        assert rows[str(run["run"])] == [round(run[k], 2) for k in ("kappa", "tpr", "tnr")]
    h = report["headline"]
    assert rows["Mean"] == [round(h[k], 2) for k in ("kappa_mean", "tpr_mean", "tnr_mean")]
    for s in report["slices"]:
        assert rows[s["slice"]] == [round(s[k], 2) for k in ("kappa_mean", "tpr_mean",
                                                             "tnr_mean")]


LEVEL_WORDS = {"usable": "usable as a gate", "usable_with_care": "usable with care",
               "not_trustworthy": "not trustworthy as a gate"}


def _llmbar_report() -> dict:
    return json.loads((EXAMPLE / "report.json").read_text(encoding="utf-8"))


def test_llmbar_report_verdict_follows_the_current_thresholds():
    """The committed LLMBar report's verdict matches the current thresholds."""
    from judgekeeper import targets

    report = _llmbar_report()
    h = report["headline"]
    low = min(h["tpr_mean"], h["tnr_mean"])
    if low < targets.RATE_GATE or h["kappa_mean"] < targets.KAPPA_GATE:
        level = "not_trustworthy"
    elif low < targets.RATE_CARE:
        level = "usable_with_care"
    else:
        level = "usable"
    assert report["verdict"]["level"] == level
    assert report["verdict"]["summary"].lower().startswith(LEVEL_WORDS[level])
    page = (EXAMPLE / "report.html").read_text(encoding="utf-8")
    assert report["verdict"]["summary"].split(":")[0] in page
    for other in set(LEVEL_WORDS.values()) - {LEVEL_WORDS[level]}:
        assert f"{other}:" not in page.lower(), other


def test_guide_and_learn_page_quote_the_llmbar_verdict_as_the_report_states_it():
    report = _llmbar_report()
    summary = report["verdict"]["summary"].split(" Read the flags")[0]
    assert f"Verdict: **{summary}**" in _first_results()
    for flag in report["verdict"]["flags"]:
        assert flag["message"] in _first_results()
    learn = (ROOT / "website" / "learn.html").read_text(encoding="utf-8")
    result = learn[learn.index('<section id="result"'):]
    result = re.sub(r"<[^>]+>", "", result[:result.index("</section>")])
    words = LEVEL_WORDS[report["verdict"]["level"]]
    assert f"Verdict: {words}" in result
    for other in set(LEVEL_WORDS.values()) - {words}:
        assert f"Verdict: {other}" not in result


# Pins

def test_actions_are_pinned_to_commit_hashes():
    """Tags can be moved; a full commit hash cannot."""
    files = sorted((ROOT / ".github" / "workflows").glob("*.yml"))
    for path in files:
        for line in path.read_text(encoding="utf-8").splitlines():
            m = re.search(r"uses:\s*(\S+)", line)
            if not m or m.group(1).startswith("./"):
                continue
            assert re.fullmatch(r"[\w.-]+/[\w.-]+@[0-9a-f]{40}", m.group(1)), f"{path.name}: {line.strip()}"
            assert re.search(r"#\s*v\d", line), f"{path.name}: no version comment on {line.strip()}"


def test_security_policy_says_a_file_edit_can_turn_checks_on():
    flat = " ".join((ROOT / "SECURITY.md").read_text(encoding="utf-8").split())
    for needed in ("cannot prove a person clicked", "`.judgekeeper/checks.json`",
                   '"turned on by a file edit, not on the page"', "`judgekeeper check --off`",
                   "never through a link"):
        assert needed in flat, needed


def test_security_policy_and_dependabot_exist():
    policy = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
    for needed in ("--judge-command", "judgekeeper start"):
        assert needed in policy, needed
    for gone in ("judgekeeper label", "`template`", "--callable", "--api-key-env", "gate.md"):
        assert gone not in policy, gone
    import yaml
    config = yaml.safe_load((ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8"))
    assert {u["package-ecosystem"] for u in config["updates"]} >= {"github-actions", "pip"}


BUILD_TOOLS = {"ruff", "build", "hatchling"}  # in [dev] to build and lint, not for the tests


@pytest.mark.parametrize("workflow", ["ci.yml", "release.yml"])
def test_the_installed_wheel_gets_every_package_the_tests_need(workflow):
    """The wheel jobs list the test-only packages by hand: each one in [dev] must be there."""
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    needed = [d for d in project["optional-dependencies"]["dev"]
              if re.split(r"[<>=\[ ]", d, maxsplit=1)[0] not in BUILD_TOOLS]
    text = (WORKFLOWS / workflow).read_text(encoding="utf-8")
    for dependency in needed:
        assert f'"{dependency}"' in text, dependency


def test_ci_runs_the_typescript_snippet_with_node_22():
    """The test job installs Node.js 22 (pinned by commit, like every action) and tells the
    TypeScript snippet test it may not skip."""
    steps = _workflow("ci.yml")["jobs"]["test"]["steps"]
    (node,) = [s for s in steps if s.get("uses", "").startswith("actions/setup-node@")]
    assert re.fullmatch(r"actions/setup-node@[0-9a-f]{40}", node["uses"])
    assert str(node["with"]["node-version"]) == "22"
    (test,) = [s for s in steps if s.get("name") == "Test"]
    assert test["env"]["JUDGEKEEPER_NEEDS_NODE"] == "1"
    assert test["run"].startswith("pytest")
