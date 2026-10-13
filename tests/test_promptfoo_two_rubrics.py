"""A promptfoo test with two `llm-rubric` assertions and no `metric:` names can't be read as
one judge. The message numbers tests from 1 as people count them and names the config file the
test is in; never the test's description or its variables (input text is never printed). It
ends each sentence with a full stop and says that adding `metric:` means running the eval
again."""

from __future__ import annotations

import copy
import json
import os

import pytest

from tests.start_projects import promptfoo_data, split
from tests.test_front import run

SAYS = ("has more than one 'llm-rubric' judge. Give each one a name with metric: in its "
        "assertion, then run your eval again (that makes model calls).")
SENTINEL = "SENTINEL-4c1e"
CONFIG = ("description: support bot\nprompts:\n  - 'Answer: {{question}}'\n"
          "providers:\n  - echo\n")


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _two_rubrics(created="2026-10-03T14:12:00.000Z"):
    data = promptfoo_data(split(18, 18), tag=f" {SENTINEL}", created=created)
    row = data["results"]["results"][2]
    row["testCase"]["description"] = f"refund {SENTINEL}"
    row["gradingResult"]["componentResults"].append(
        copy.deepcopy(row["gradingResult"]["componentResults"][0]))
    return data


def _config(here, name="promptfooconfig.yaml"):
    (here / name).parent.mkdir(parents=True, exist_ok=True)
    (here / name).write_text(CONFIG, encoding="utf-8")


def test_the_test_is_numbered_from_1_in_its_config_file(here, capsys):
    _config(here)
    (here / "results.json").write_text(json.dumps(_two_rubrics()), encoding="utf-8")
    code, out, err = run(capsys)
    assert f"results.json: test 3 in promptfooconfig.yaml {SAYS}" in err
    assert SENTINEL not in out + err
    assert code == 2


def test_a_config_under_another_name(here, capsys):
    _config(here, "evals/support.yaml")
    (here / "results.json").write_text(json.dumps(_two_rubrics()), encoding="utf-8")
    _, out, err = run(capsys)
    assert f"results.json: test 3 in evals/support.yaml {SAYS}" in err
    assert SENTINEL not in out + err


def test_without_a_config_file_your_promptfoo_config(here, capsys):
    (here / "results.json").write_text(json.dumps(_two_rubrics()), encoding="utf-8")
    _, out, err = run(capsys)
    assert f"results.json: test 3 in your promptfoo config {SAYS}" in err
    assert SENTINEL not in out + err


def test_beside_a_good_file_it_is_left_out_in_full_sentences(here, capsys):
    _config(here)
    good = here / "old.json"
    good.write_text(json.dumps(promptfoo_data(split(18, 18))), encoding="utf-8")
    bad = here / "results.json"
    bad.write_text(json.dumps(_two_rubrics(created="2026-10-04T14:12:00.000Z")),
                   encoding="utf-8")
    os.utime(good, (bad.stat().st_mtime - 60,) * 2)
    code, out, err = run(capsys)
    assert f"results.json: test 3 in promptfooconfig.yaml {SAYS} It is left out." in out
    assert SENTINEL not in out + err
    assert code == 0, out
