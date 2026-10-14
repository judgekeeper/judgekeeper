"""promptfoo results "from another project": the results' `config.description` is compared
with every promptfoo config in the project (any .yaml, .yml or .json file with `prompts` and
`providers` or `tests` at the top), not only promptfooconfig.yaml. The question says what a
"no" changes, and the list of questions does not claim judgekeeper went on."""

from __future__ import annotations

import json

import pytest

from tests.start_projects import promptfoo_project, split
from tests.test_front import assert_one_next_at_the_end, run

CONFIG = "description: {d}\nprompts:\n  - 'Answer: {{{{question}}}}'\nproviders:\n  - echo\n"


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _results(here, description="support bot"):
    promptfoo_project(here, split(18, 18), description=description, config=False)


def _asks(out: str) -> bool:
    return "looks like it is from another project" in out


@pytest.mark.parametrize("name", ["promptfoo.yaml", "evals/support.yml", "configs/eval.yaml"])
def test_a_config_with_another_name_or_folder_is_compared(here, capsys, name):
    _results(here)
    (here / name).parent.mkdir(parents=True, exist_ok=True)
    (here / name).write_text(CONFIG.format(d="support bot"), encoding="utf-8")
    (here / "promptfooconfig.yaml").write_text(CONFIG.format(d="billing bot"), encoding="utf-8")
    _, out, _ = run(capsys)
    assert not _asks(out), out


def test_a_json_config_is_compared(here, capsys):
    _results(here, description="another bot")
    (here / "eval.json").write_text(json.dumps({
        "description": "support bot", "prompts": ["hi"], "tests": []}), encoding="utf-8")
    _, out, _ = run(capsys)
    assert _asks(out)


def test_a_file_without_promptfoo_keys_is_not_a_config(here, capsys):
    _results(here, description="another bot")
    (here / "compose.yaml").write_text("description: support bot\nservices: {}\n",
                                       encoding="utf-8")
    _, out, _ = run(capsys)
    assert not _asks(out)


def test_no_config_matches_so_it_asks_and_says_what_no_changes(here, capsys):
    _results(here, description="another bot")
    (here / "evals").mkdir()
    (here / "evals" / "a.yaml").write_text(CONFIG.format(d="support bot"), encoding="utf-8")
    code, out, _ = run(capsys)
    assert code == 3
    assert ('results.json looks like it is from another project (its description is "another '
            'bot", and no promptfoo config here has it). Use it anyway? If not, nothing is '
            "read: run judgekeeper with the path of your own results file.") in " ".join(
                out.split())
    assert "went on as if" not in out
    assert "judgekeeper needs your answer to this question:" in out
    assert "`judgekeeper --yes`" in assert_one_next_at_the_end(out)
