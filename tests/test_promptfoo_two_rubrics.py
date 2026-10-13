"""A promptfoo test with two `llm-rubric` assertions and no `metric:` names can't be read as
one judge. The message numbers tests from 1 as people count them, names the test by its
description (or its first variable), ends each sentence with a full stop, and says that adding
`metric:` means running the eval again."""

from __future__ import annotations

import copy
import json
import os

import pytest

from tests.start_projects import promptfoo_data, split
from tests.test_front import run

SAYS = ("has more than one 'llm-rubric' judge. Give each one a name with metric: in its "
        "assertion, then run your eval again (that makes model calls).")


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _two_rubrics(description=True):
    data = promptfoo_data(split(18, 18))
    row = data["results"]["results"][2]
    row["gradingResult"]["componentResults"].append(
        copy.deepcopy(row["gradingResult"]["componentResults"][0]))
    if not description:
        del row["testCase"]["description"]
    return data


def test_the_test_is_numbered_from_1_and_named(here, capsys):
    (here / "results.json").write_text(json.dumps(_two_rubrics()), encoding="utf-8")
    code, _, err = run(capsys)
    assert f'results.json: test 3 ("t2") {SAYS}' in err
    assert "test 2 " not in err
    assert code == 2


def test_without_a_description_its_first_variable(here, capsys):
    (here / "results.json").write_text(json.dumps(_two_rubrics(description=False)),
                                       encoding="utf-8")
    _, _, err = run(capsys)
    assert f'test 3 ("Question 2?") {SAYS}' in err


def test_beside_a_good_file_it_is_left_out_in_full_sentences(here, capsys):
    good = here / "old.json"
    good.write_text(json.dumps(promptfoo_data(split(18, 18))), encoding="utf-8")
    bad = here / "results.json"
    data = _two_rubrics()
    data["metadata"]["evaluationCreatedAt"] = "2026-10-04T14:12:00.000Z"
    bad.write_text(json.dumps(data), encoding="utf-8")
    os.utime(good, (bad.stat().st_mtime - 60,) * 2)
    code, out, _ = run(capsys)
    assert f'test 3 ("t2") {SAYS} It is left out.' in out
    assert code == 0, out
