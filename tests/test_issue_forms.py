"""The issue forms and CONTRIBUTING: three forms, each with the required MIT checkbox, and
blank issues off. The repo takes issues, not pull requests.
"""

from __future__ import annotations

import yaml

from tests.website_pages import ROOT

FORMS = ROOT / ".github" / "ISSUE_TEMPLATE"
MIT = "Any code, design or text I share here may be used in judgekeeper under the MIT license."
REMOVED_ANSWERS = "I removed any answer text I can't share"


def _flat(text: str) -> str:
    return " ".join(text.split())


def _form(name: str) -> dict:
    return yaml.safe_load((FORMS / name).read_text(encoding="utf-8"))


def _checkboxes(form: dict) -> dict[str, bool]:
    return {o["label"]: o.get("required", False) for item in form["body"]
            if item["type"] == "checkboxes" for o in item["attributes"]["options"]}


def _field(form: dict, wanted: str) -> dict:
    return next(item for item in form["body"] if item.get("id") == wanted)


def test_there_are_three_forms_and_no_blank_issues():
    assert sorted(p.name for p in FORMS.glob("*.yml")) == [
        "bug.yml", "config.yml", "idea.yml", "results-not-found.yml"]
    config = _form("config.yml")
    assert config["blank_issues_enabled"] is False
    assert any("security/advisories/new" in link["url"] for link in config["contact_links"])


def test_every_form_asks_for_the_mit_checkbox():
    for name in ("bug.yml", "results-not-found.yml", "idea.yml"):
        assert _checkboxes(_form(name)).get(MIT) is True, name


def test_the_bug_form_asks_for_the_version_the_eval_tool_and_the_output():
    form = _form("bug.yml")
    assert _checkboxes(form).get(REMOVED_ANSWERS) is True
    for wanted in ("ran", "saw", "version", "tool", "tool-version"):
        assert _field(form, wanted)["validations"]["required"] is True, wanted
    assert "`judgekeeper --version`" in _field(form, "version")["attributes"]["description"]
    text = (FORMS / "bug.yml").read_text(encoding="utf-8")
    assert "setup" not in text and "judgekeeper start" not in text


def test_the_results_not_found_form_asks_which_tool_or_format():
    form = _form("results-not-found.yml")
    assert form["name"] == "Results not found"
    assert _field(form, "tool")["validations"]["required"] is True
    assert _field(form, "version")["validations"]["required"] is True


def test_the_idea_form_takes_a_picture_a_figma_link_or_a_changed_version():
    form = _form("idea.yml")
    assert form["name"] == "Idea or design"
    assert _field(form, "change")["validations"]["required"] is True
    for optional in ("picture", "version-link"):
        assert not _field(form, optional).get("validations", {}).get("required"), optional
    flat = _flat((FORMS / "idea.yml").read_text(encoding="utf-8"))
    for needed in ("Figma", "fork or branch", "code change"):
        assert needed in flat, needed


def test_contributing_sends_designers_and_developers_to_the_forms():
    flat = _flat((ROOT / ".github" / "CONTRIBUTING.md").read_text(encoding="utf-8"))
    assert "accepts issues, not pull requests" in flat
    for name in ("bug.yml", "results-not-found.yml", "idea.yml"):
        assert f'"{_form(name)["name"]}"' in flat, name
    for needed in ("designer", "developer", "MIT license"):
        assert needed in flat, needed
