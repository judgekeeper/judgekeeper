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
EXAMPLE = ROOT / "docs" / "examples" / "jailbreakbench"
# The old LLMBar run, kept only as a source of the real-data check
LLMBAR = ROOT / "docs" / "examples" / "real-data-check" / "sources" / "llmbar-haiku.json"


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

@pytest.mark.version_number
def test_versions_agree():
    from judgekeeper import __version__

    main = _toml(ROOT / "pyproject.toml")["project"]
    assert main["version"] == __version__ == VERSION
    assert BETA in main["classifiers"]
    for minor in ("3.11", "3.12", "3.13", "3.14"):
        assert f"Programming Language :: Python :: {minor}" in main["classifiers"]


def test_package_description_and_classifiers():
    main = _toml(ROOT / "pyproject.toml")["project"]
    assert main["description"] == ("Check your LLM-as-a-judge in 5 steps: "
                                   "Find. Mark. Measure. Fix. Re-check.")
    for classifier in ("Operating System :: OS Independent",
                       "Intended Audience :: Developers",
                       "Topic :: Scientific/Engineering :: Artificial Intelligence"):
        assert classifier in main["classifiers"], classifier


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


def test_practice_release_runs_only_by_hand_and_uploads_to_testpypi_without_a_token():
    text = (WORKFLOWS / "testpypi.yml").read_text(encoding="utf-8")
    assert "secrets." not in text and "password" not in text and "TOKEN" not in text
    wf = _workflow("testpypi.yml")
    assert set(wf["on"]) == {"workflow_dispatch"}
    rc = wf["on"]["workflow_dispatch"]["inputs"]["rc"]
    assert rc["type"] == "number" and rc["default"] == 1
    assert wf.get("permissions") == {"contents": "read"}
    publish = _publish_jobs(wf)
    assert [_env_name(j) for j in publish.values()] == ["testpypi"]
    for job in publish.values():
        assert job["permissions"] == {"id-token": "write"} and job.get("needs")
        (step,) = [s for s in job["steps"] if "pypa/gh-action-pypi-publish" in s.get("uses", "")]
        assert step["with"] == {"repository-url": "https://test.pypi.org/legacy/"}
        # The same pinned commit as the real release.
        real = _publish_jobs(_workflow("release.yml"))["publish"]["steps"]
        assert step["uses"] in [s.get("uses") for s in real]
    for name, other in wf["jobs"].items():
        if name not in publish:
            assert "id-token" not in (other.get("permissions") or {}), name


def test_practice_release_builds_rc_in_the_runner_and_tests_it_like_the_release():
    wf = _workflow("testpypi.yml")
    build = _steps_text(wf["jobs"]["build"])
    for needed in ("${version}rc${RC}", "pyproject.toml", "src/judgekeeper/__init__.py",
                   "python -m build", "twine check --strict", "venv", ".whl",
                   "judgekeeper --version", "judgekeeper.record(",
                   '-m pytest -p no:cacheprovider -m \\"not version_number\\"'):
        assert needed in build, needed
    text = (WORKFLOWS / "testpypi.yml").read_text(encoding="utf-8")
    assert "git commit" not in text and "git push" not in text  # main keeps its version
    assert "persist-credentials: false" in text
    # Only the practice run leaves the tests of the version number out.
    for name in ("ci.yml", "release.yml", "windows.yml"):
        assert "version_number" not in (WORKFLOWS / name).read_text(encoding="utf-8"), name


def test_practice_release_installs_from_testpypi_on_three_systems():
    job = _workflow("testpypi.yml")["jobs"]["install"]
    assert set(job["needs"]) == {"build", "publish"}
    matrix = job["strategy"]["matrix"]
    assert set(matrix["os"]) == {"ubuntu-latest", "macos-latest", "windows-latest"}
    assert matrix["python"] == ["3.11", "3.14"] and job["strategy"]["fail-fast"] is False
    assert job["env"]["INDEX"] == "https://test.pypi.org/simple/"
    steps = _steps_text(job)
    uvx = 'uvx --index-url \\"$INDEX\\" \\"judgekeeper==$VERSION\\"'
    for needed in (f"{uvx} --version", f"{uvx} --help", f"{uvx} --no-browser", f"{uvx} --stop",
                   "seq 1 30", "sleep 10", "range(1, 41)", "Step 1 of 5: Find",
                   "http://127"):
        assert needed in steps, needed
    for key in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", " fix", " check"):
        assert key not in steps, key  # it never makes an AI call


def test_ci_builds_and_runs_the_installed_wheel_on_every_push():
    wf = _workflow("ci.yml")
    # every pull request, and every push to main: a pull request's push runs it once
    assert wf["on"]["push"] == {"branches": ["main"]}
    assert "pull_request" in wf["on"]
    text = "\n".join(_steps_text(j) for j in wf["jobs"].values())
    for needed in ("python -m build", "venv", "judgekeeper --version", "judgekeeper --help",
                   "judgekeeper mark --help", "judgekeeper fix --help",
                   "judgekeeper check --help", "judgekeeper.record(", ".judgekeeper/records",
                   "twine check"):
        assert needed in text, needed
    assert "demo" not in text and "pytest-judgekeeper" not in text
    assert "judgekeeper start" not in text


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


@pytest.mark.version_number
def test_wheel_ships_the_package_and_no_demo(tmp_path):
    wheel = _build_wheel(ROOT, tmp_path)
    assert wheel.name == f"judgekeeper-{VERSION}-py3-none-any.whl"
    names = set(zipfile.ZipFile(wheel).namelist())
    for needed in ("judgekeeper/label.py", "judgekeeper/start.py",
                   "judgekeeper/schemas/records.schema.json",
                   "judgekeeper/fonts/manrope-latin-wght-normal.woff2",
                   "judgekeeper/fonts/OFL-Manrope.txt",
                   "judgekeeper/fonts/jetbrains-mono-latin-400-normal.woff2",
                   "judgekeeper/fonts/jetbrains-mono-latin-500-normal.woff2",
                   "judgekeeper/fonts/OFL-JetBrainsMono.txt"):  # the pages' fonts, OFL
        assert needed in names, needed
    for gone in ("judgekeeper/demo_data/", "judgekeeper/demo.py", "judgekeeper/templates/",
                 "judgekeeper/pytest_plugin.py", "judgekeeper/gate.py"):
        assert not any(name.startswith(gone) for name in names), gone
    dist_info = f"judgekeeper-{VERSION}.dist-info"
    entry_points = zipfile.ZipFile(wheel).read(f"{dist_info}/entry_points.txt").decode()
    assert "[pytest11]" not in entry_points and "judgekeeper.__main__:main" in entry_points
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
    for name in ("release.yml", "ci.yml", "testpypi.yml"):
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
    for page in ("start.html", "check.html", "privacy.html", "llms.txt", "assets/style.css",
                 "favicon.ico"):
        assert (tmp_path / page).is_file(), page
    assert not (tmp_path / "README.md").exists()
    banner = "assets/social-preview.png"  # the picture in link previews; og:image points at it
    assert (tmp_path / banner).read_bytes() == (ROOT / "website" / banner).read_bytes()
    for name in ("index.html", "report.html"):
        report = tmp_path / "examples" / "jailbreakbench" / name
        assert report.read_bytes() == (EXAMPLE / "report.html").read_bytes()
    index = (tmp_path / "examples" / "index.html").read_text(encoding="utf-8")
    assert index.startswith("<!doctype html>")
    assert 'href="jailbreakbench/"' in index
    # Home's terminal figures: their report, said to be made-up
    assert (tmp_path / "examples" / "site-example" / "index.html").is_file()
    assert re.search(r'href="site-example/".*Example project \(made-up answers\), '
                     r"openai:gpt-4\.1-mini", index)
    assert "unedited" not in index and "real runs" in index and "made-up" in index
    assert not re.search(r'(?:src|<link[^>]*href)="http', index)  # no external assets
    assert (tmp_path / ".nojekyll").is_file()
    assert not (tmp_path / "CNAME").exists()  # the build sets no custom domain


def test_the_examples_index_lists_folders_with_a_readme_or_report_and_is_dark(tmp_path):
    _build_pages(tmp_path)
    index = (tmp_path / "examples" / "index.html").read_text(encoding="utf-8")
    listed = re.findall(r'<li><a href="[^"]*">([\w-]+)</a>', index)
    assert listed == ["jailbreakbench", "probes", "ragtruth", "real-data-check", "site-example"]
    # a folder with no report.html links to its report.md on GitHub
    assert ('href="https://github.com/judgekeeper/judgekeeper/blob/main/docs/examples/'
            'probes/report.md"') in index
    assert "llmbar-haiku" not in index
    # dark only, like the site
    assert "prefers-color-scheme" not in index and "#fff;" not in index
    assert "color-scheme: dark" in index


def test_the_build_stops_on_an_example_page_with_a_script_and_no_policy(tmp_path):
    spec = importlib.util.spec_from_file_location("build_pages",
                                                  ROOT / "scripts" / "build_pages.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.unsafe_pages(ROOT / "docs" / "examples") == []
    examples = tmp_path / "examples"
    (examples / "a" / "deep").mkdir(parents=True)
    (examples / "a" / "report.html").write_text("<p>No script.</p>", encoding="utf-8")
    (examples / "a" / "deep" / "x.html").write_text("<script>run()</script>", encoding="utf-8")
    (examples / "b").mkdir()
    (examples / "b" / "report.html").write_text(
        '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; '
        'script-src \'sha256-abc=\'"><script>run()</script>', encoding="utf-8")
    assert module.unsafe_pages(examples) == ["a/deep/x.html"]
    with pytest.raises(SystemExit, match="a/deep/x.html"):
        module.build(ROOT / "website", examples, tmp_path / "out")


# The README and the changelog (the README's own contract is in test_docs.py)

def test_changelog_entry_says_1_0_is_commands_you_run():
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    entry = text[text.index(f"## {VERSION}"):text.index("## 1.0.0b1")]
    assert len(entry.strip().splitlines()) < 20
    flat = " ".join(entry.split())
    removed = ("Removed: automatic checks, the GitHub Action and the agent skill. 1.0 is "
               "commands you run yourself; agent support may come back later.")
    for needed in (f"`uvx judgekeeper@{VERSION}`", f"`pip install judgekeeper=={VERSION}`",
                   "`judgekeeper check`", "asks first",
                   "Find. Mark. Measure. Fix. Re-check.", removed):
        assert needed in flat, needed
    for gone in ("--off", "Only your click", "action.yml", "mode: fast", "hook"):
        assert gone not in flat, gone


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
    assert "\nuvx judgekeeper\n" in readme
    assert "\npip install judgekeeper\n" in readme
    for gone in ("judgekeeper start", "judgekeeper demo", "before the first PyPI release"):
        assert gone not in readme, gone
    for needed in ("TPR", "TNR", "kappa"):
        assert needed in readme, needed


def test_every_install_command_names_the_version_in_pyproject():
    """uv and pip skip betas unless the version is named: the changelog's newest entry names
    the exact version in pyproject.toml, so the next beta can't forget it. The README names
    none: it is for 1.0.0, which they install."""
    version = _toml(ROOT / "pyproject.toml")["project"]["version"]
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    newest = changelog[:changelog.index("## ", changelog.index("## ") + 3)]
    uvx = re.findall(r"uvx judgekeeper(@[\w.]+)?", newest)
    pip = re.findall(r"pip install judgekeeper(==[\w.]+)?", newest)
    assert uvx and set(uvx) == {f"@{version}"}, uvx
    assert set(pip) <= {f"=={version}"}, pip
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert set(re.findall(r"uvx judgekeeper(@[\w.]+)?", readme)) == {""}
    assert set(re.findall(r"pip install judgekeeper(==[\w.]+)?", readme)) == {""}


def test_readme_has_no_link_to_the_website_while_it_is_offline():
    """PyPI shows the README; the website stays offline until it is rewritten."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "judgekeeper.com" not in readme


def test_docs_do_not_point_at_the_unused_pages_address():
    assert "judgekeeper.github.io" not in (ROOT / "README.md").read_text(encoding="utf-8")


def test_package_metadata_links_the_repo_while_the_website_is_offline():
    """PyPI shows these links. The reference on GitHub is the documentation."""
    urls = _toml(ROOT / "pyproject.toml")["project"]["urls"]
    assert urls["Homepage"] == "https://github.com/judgekeeper/judgekeeper"
    assert urls["Source"] == "https://github.com/judgekeeper/judgekeeper"
    assert urls["Documentation"] == (
        "https://github.com/judgekeeper/judgekeeper/blob/main/docs/reference.md")
    assert urls["Issues"] == "https://github.com/judgekeeper/judgekeeper/issues"
    assert not [u for u in urls.values() if "judgekeeper.com" in u]


def test_contributing_says_issues_not_pull_requests_and_how_to_report_privately():
    text = (ROOT / ".github" / "CONTRIBUTING.md").read_text(encoding="utf-8")
    assert "accepts issues, not pull requests" in text
    assert "https://github.com/judgekeeper/judgekeeper/security/advisories/new" in text
    assert "Never paste API keys" in text


LEVEL_WORDS = {"usable": "usable as a gate", "usable_with_care": "usable with care",
               "not_trustworthy": "not trustworthy as a gate"}


def _llmbar_report() -> dict:
    return json.loads(LLMBAR.read_text(encoding="utf-8"))


def test_llmbar_report_verdict_follows_the_current_thresholds():
    """The kept LLMBar report's verdict matches the current thresholds."""
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


def test_security_policy_says_what_judgekeeper_writes_and_that_agents_are_not_supported():
    flat = " ".join((ROOT / "SECURITY.md").read_text(encoding="utf-8").split())
    for needed in ("writes only inside `.judgekeeper/`", "never edits other tools' settings",
                   "isn't supported in 1.0", "must also come from the page itself"):
        assert needed in flat, needed
    for gone in ("Turn on", "checks.json", "--off", "page.log", "settings.local.json"):
        assert gone not in flat, gone


def test_security_policy_and_dependabot_exist():
    policy = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
    for needed in ("judgekeeper check", "judgekeeper fix", "127.0.0.1"):
        assert needed in policy, needed
    for gone in ("judgekeeper label", "`template`", "--callable", "--api-key-env", "gate.md",
                 "judgekeeper start", "--judge-command", "--python", "--ask-again",
                 "--try-new-judge", "the review"):
        assert gone not in policy, gone
    import yaml
    config = yaml.safe_load((ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8"))
    assert {u["package-ecosystem"] for u in config["updates"]} >= {"github-actions", "pip"}


BUILD_TOOLS = {"ruff", "build", "hatchling"}  # in [dev] to build and lint, not for the tests


@pytest.mark.parametrize("workflow", ["ci.yml", "release.yml", "testpypi.yml"])
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
