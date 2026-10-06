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
PLUGIN_DIST = ROOT / "packages" / "pytest-judgekeeper"
WORKFLOWS = ROOT / ".github" / "workflows"
VERSION = "0.2.0"
ALPHA = "Development Status :: 3 - Alpha"
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


# Versions and the two distributions

def test_versions_agree():
    from judgekeeper import __version__

    main = _toml(ROOT / "pyproject.toml")["project"]
    plugin = _toml(PLUGIN_DIST / "pyproject.toml")["project"]
    assert main["version"] == plugin["version"] == __version__ == VERSION
    assert plugin["dependencies"] == [f"judgekeeper=={VERSION}"]
    assert plugin["name"] == "pytest-judgekeeper"
    for project in (main, plugin):
        assert ALPHA in project["classifiers"]
        assert "Framework :: Pytest" in plugin["classifiers"]
        for minor in ("3.11", "3.12", "3.13", "3.14"):
            assert f"Programming Language :: Python :: {minor}" in project["classifiers"]


def test_plugin_entry_point_lives_in_judgekeeper_only():
    main = _toml(ROOT / "pyproject.toml")["project"]
    plugin = _toml(PLUGIN_DIST / "pyproject.toml")["project"]
    assert main["entry-points"]["pytest11"] == {"judgekeeper": "judgekeeper.pytest_plugin"}
    # Declaring it twice would register the plugin twice and break pytest.
    assert "entry-points" not in plugin


def test_plugin_distribution_has_no_code():
    files = [p for p in PLUGIN_DIST.rglob("*") if p.is_file()
             and not {"dist", "build"} & set(p.relative_to(PLUGIN_DIST).parts)]
    assert sorted(p.name for p in files) == ["LICENSE", "README.md", "pyproject.toml"]
    assert (PLUGIN_DIST / "LICENSE").read_bytes() == (ROOT / "LICENSE").read_bytes()
    readme = (PLUGIN_DIST / "README.md").read_text(encoding="utf-8").strip().splitlines()
    body = [line for line in readme if line.strip() and not line.startswith("#")]
    assert len(body) == 2


def test_changelog_leads_with_this_version():
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    entries = re.findall(r"^## (\S+)", text, flags=re.MULTILINE)
    assert entries == [VERSION, "0.1.3", "0.1.2", "0.1.1", "0.1.0"]


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
    # One job per PyPI project, each behind its own environment: PyPI refuses two pending
    # publishers with the same owner, repository, workflow and environment.
    assert sorted(_env_name(j) for j in publish.values()) == ["pypi", "pypi-plugin"]
    for job in publish.values():
        assert job["permissions"] == {"id-token": "write"}
    for name, other in wf["jobs"].items():
        if name not in publish:
            assert "id-token" not in (other.get("permissions") or {}), name


def test_each_publish_job_uploads_only_its_own_project():
    wf = _workflow("release.yml")
    publish = {_env_name(j): j for j in _publish_jobs(wf).values()}
    core, plugin = _steps_text(publish["pypi"]), _steps_text(publish["pypi-plugin"])
    assert "rm dist/pytest_judgekeeper-" in core
    assert "rm dist/judgekeeper-" in plugin
    # The plugin pins judgekeeper==VERSION, so it goes up after judgekeeper.
    core_job = next(n for n, j in wf["jobs"].items() if j is publish["pypi"])
    needs = publish["pypi-plugin"]["needs"]
    assert core_job in (needs if isinstance(needs, list) else [needs])


def test_release_workflow_builds_checks_and_tests_the_wheel():
    wf = _workflow("release.yml")
    text = "\n".join(_steps_text(j) for j in wf["jobs"].values())
    assert "python -m build" in text and "packages/pytest-judgekeeper" in text
    assert "twine check" in text
    assert "venv" in text and "pytest" in text and ".whl" in text
    for publish in _publish_jobs(wf).values():
        assert publish.get("needs")  # publishes only what the build job built and tested


def test_ci_builds_and_runs_the_installed_wheel_on_every_push():
    wf = _workflow("ci.yml")
    assert "push" in wf["on"]
    text = "\n".join(_steps_text(j) for j in wf["jobs"].values())
    for needed in ("python -m build", "packages/pytest-judgekeeper", "venv",
                   "judgekeeper --version", "judgekeeper --help", "judgekeeper check ",
                   "report.html", "judgekeeper init", "twine check"):
        assert needed in text, needed
    assert "demo" not in text


def test_release_runs_the_installed_wheel_end_to_end_before_publishing():
    text = "\n".join(_steps_text(j) for j in _workflow("release.yml")["jobs"].values())
    for needed in ("judgekeeper --version", "judgekeeper --help", "judgekeeper check ",
                   "report.html"):
        assert needed in text, needed
    assert "demo" not in text


def test_ci_tests_every_python_the_classifiers_name_and_windows_without_gating():
    wf = _workflow("ci.yml")
    classifiers = _toml(ROOT / "pyproject.toml")["project"]["classifiers"]
    named = sorted(c.rsplit(" ", 1)[1] for c in classifiers
                   if re.fullmatch(r"Programming Language :: Python :: 3\.\d+", c))
    assert sorted(wf["jobs"]["test"]["strategy"]["matrix"]["python-version"]) == named
    assert wf["jobs"]["test"]["runs-on"] == "ubuntu-latest"
    assert not [j for j in wf["jobs"].values() if j["runs-on"] == "windows-latest"]
    # Windows runs on demand only, so an unsupported platform never shows as a failing check.
    win = _workflow("windows.yml")
    assert list(win.get(True, win.get("on"))) == ["workflow_dispatch"]  # YAML reads `on` as True
    (job,) = win["jobs"].values()
    assert job["runs-on"] == "windows-latest" and "pytest" in _steps_text(job)


def test_action_is_marketplace_ready():
    action = yaml.safe_load((ROOT / "action.yml").read_text(encoding="utf-8"))
    assert len(action["description"]) < 125
    assert action["branding"]["icon"] and action["branding"]["color"]


# Packaging

def _build_wheel(src: Path, out: Path) -> Path:
    if importlib.util.find_spec("build") is None or importlib.util.find_spec("hatchling") is None:
        pytest.skip("needs the build and hatchling packages (the dev extra)")
    subprocess.run([sys.executable, "-m", "build", "--wheel", "--no-isolation", "--outdir",
                    str(out), str(src)], check=True, capture_output=True)
    (wheel,) = out.glob("*.whl")
    return wheel


def test_wheel_ships_templates_and_plugin_and_no_demo(tmp_path):
    wheel = _build_wheel(ROOT, tmp_path)
    assert wheel.name == f"judgekeeper-{VERSION}-py3-none-any.whl"
    names = set(zipfile.ZipFile(wheel).namelist())
    for needed in ("judgekeeper/templates/single.md", "judgekeeper/templates/pairwise.md",
                   "judgekeeper/pytest_plugin.py", "judgekeeper/label.py",
                   "judgekeeper/schemas/records.schema.json"):
        assert needed in names, needed
    for gone in ("judgekeeper/demo_data/", "judgekeeper/demo.py"):
        assert not any(name.startswith(gone) for name in names), gone
    dist_info = f"judgekeeper-{VERSION}.dist-info"
    entry_points = zipfile.ZipFile(wheel).read(f"{dist_info}/entry_points.txt").decode()
    assert "[pytest11]" in entry_points and "judgekeeper.pytest_plugin" in entry_points
    assert f"{dist_info}/licenses/LICENSE" in names


def test_plugin_wheel_is_metadata_only(tmp_path):
    wheel = _build_wheel(PLUGIN_DIST, tmp_path)
    assert wheel.name == f"pytest_judgekeeper-{VERSION}-py3-none-any.whl"
    zf = zipfile.ZipFile(wheel)
    assert not [n for n in zf.namelist() if n.endswith(".py")]
    meta = zf.read(f"pytest_judgekeeper-{VERSION}.dist-info/METADATA").decode()
    assert f"Requires-Dist: judgekeeper=={VERSION}" in meta
    assert f"pytest_judgekeeper-{VERSION}.dist-info/licenses/LICENSE" in zf.namelist()


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
    top = {"README.md", "LICENSE", "CHANGELOG.md", "pyproject.toml"}
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


def test_plugin_sdist_holds_only_its_own_three_files(tmp_path):
    names = _build_sdist(PLUGIN_DIST, tmp_path)
    assert set(names) - SDIST_ALWAYS == {"README.md", "LICENSE", "pyproject.toml"}


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
    for page in ("start.html", "assistant.html", "learn.html", "setup.html",
                 "tutorial.html", "reference.html", "llms.txt", "assets/style.css", "tutorial/items.csv"):
        assert (tmp_path / page).is_file(), page
    assert not (tmp_path / "README.md").exists()
    banner = "assets/social-preview.png"  # the picture in link previews; og:image points at it
    assert (tmp_path / banner).read_bytes() == (ROOT / "website" / banner).read_bytes()
    for name in ("index.html", "report.html"):
        report = tmp_path / "examples" / "llmbar-haiku" / name
        assert report.read_bytes() == (EXAMPLE / "report.html").read_bytes()
    assert (tmp_path / "examples" / "workflows" / "judge-gate.yml").is_file()
    index = (tmp_path / "examples" / "index.html").read_text(encoding="utf-8")
    assert index.startswith("<!doctype html>")
    assert 'href="llmbar-haiku/"' in index
    assert "http" not in index.replace("http-equiv", "")  # no external assets
    assert (tmp_path / ".nojekyll").is_file()
    assert not (tmp_path / "CNAME").exists()  # the custom domain is a later, manual step


# README and the guide (the short README's own contract is in test_front_door.py)

def _guide() -> str:
    return (ROOT / "docs" / "guide.md").read_text(encoding="utf-8")


def test_changelog_entry_says_what_changed():
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    entry = text[text.index(f"## {VERSION}"):text.index("## 0.1.3")]
    assert f"## {VERSION} (unreleased)" in entry
    flat = " ".join(entry.split())
    for needed in ("Removed: `judgekeeper demo`", "`judgekeeper demo --try`",
                   '"See it work"', "`judgekeeper --version`", "does not accept pull requests"):
        assert needed in flat, needed


def test_older_changelog_entries_stay_as_they_were_written():
    """An entry is history: 0.1.2 keeps the headline it shipped with."""
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    entry = text[text.index("## 0.1.2"):text.index("## 0.1.1")]
    for needed in ("Your AI judge grades your app. judgekeeper grades the judge.", "README",
                   "docs/guide.md", "--help", "plain", "Nothing was removed or renamed"):
        assert needed in entry, needed


def test_readme_and_guide_cover_the_launch_contract():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    guide = _guide()
    assert "\npip install judgekeeper\n" in readme
    assert "judgekeeper --version" in readme and "judgekeeper check " in readme
    assert "judgekeeper demo" not in readme
    assert "skills/judgekeeper/SKILL.md" in readme
    for text in (readme, guide):
        assert "before the first PyPI release" not in text
    for needed in ("judgekeeper init", "](own-metric.md)", "judgekeeper label", "pytest",
                   "skills/judgekeeper/SKILL.md", "kappa", "TPR", "TNR"):
        assert needed in guide, needed


def test_guide_links_the_published_report_and_the_file():
    guide = _guide()
    assert "https://www.judgekeeper.com/examples/llmbar-haiku/" in guide
    assert "](examples/llmbar-haiku/report.html)" in guide
    assert "](https://www.judgekeeper.com/examples/llmbar-haiku/report.html)" in (
        ROOT / "README.md").read_text(encoding="utf-8")


def test_docs_do_not_point_at_the_unused_pages_address():
    for path in (ROOT / "README.md", ROOT / "docs" / "guide.md"):
        assert "judgekeeper.github.io" not in path.read_text(encoding="utf-8"), path


def test_package_metadata_links_the_website():
    for path in (ROOT / "pyproject.toml", PLUGIN_DIST / "pyproject.toml"):
        urls = _toml(path)["project"]["urls"]
        assert urls["Homepage"] == "https://www.judgekeeper.com", path
        assert urls["Source"] == "https://github.com/judgekeeper/judgekeeper", path


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
    """A report written by an older version said "usable as a gate" with TNR 0.88."""
    from judgekeeper import report as rules

    report = _llmbar_report()
    h = report["headline"]
    low = min(h["tpr_mean"], h["tnr_mean"])
    if low < rules.RATE_GATE or h["kappa_mean"] < rules.KAPPA_GATE:
        level = rules.NOT_TRUSTWORTHY
    elif low < rules.RATE_CARE:
        level = rules.WITH_CARE
    else:
        level = rules.TRUSTWORTHY
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


# Security audit: pins

PIN_FILES = ("README.md", "docs/reference.md", "docs/examples/workflows/judge-gate.yml",
             "website/index.html", "website/learn.html", "website/setup.html",
             "website/reference.html",
             "skills/judgekeeper/SKILL.md")


def test_examples_pin_judgekeeper_to_the_released_tag():
    """`@main` would run whatever lands on main next with the user's API key."""
    refs = []
    for name in PIN_FILES:
        text = (ROOT / name).read_text(encoding="utf-8")
        refs += [(name, m) for m in re.findall(r"judgekeeper/judgekeeper(?:\.git)?@(\S+)", text)]
    assert refs, "no pinned reference found; did the examples move?"
    for name, ref in refs:
        assert ref.rstrip('"') == f"v{VERSION}", f"{name}: @{ref}"


def test_actions_are_pinned_to_commit_hashes():
    """Tags can be moved; a full commit hash cannot. action.yml runs inside users' CI."""
    files = sorted((ROOT / ".github" / "workflows").glob("*.yml")) + [ROOT / "action.yml"]
    for path in files:
        for line in path.read_text(encoding="utf-8").splitlines():
            m = re.search(r"uses:\s*(\S+)", line)
            if not m or m.group(1).startswith("./"):
                continue
            assert re.fullmatch(r"[\w.-]+/[\w.-]+@[0-9a-f]{40}", m.group(1)), f"{path.name}: {line.strip()}"
            assert re.search(r"#\s*v\d", line), f"{path.name}: no version comment on {line.strip()}"


def test_security_policy_and_dependabot_exist():
    policy = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
    for needed in ("--callable", "--exec", "report"):
        assert needed in policy, needed
    import yaml
    config = yaml.safe_load((ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8"))
    assert {u["package-ecosystem"] for u in config["updates"]} >= {"github-actions", "pip"}
