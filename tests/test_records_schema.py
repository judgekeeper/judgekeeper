"""The records JSON Schema and judgekeeper's own checks say the same thing.

judgekeeper checks records in plain Python (no jsonschema dependency); the schema
(src/judgekeeper/schemas/records.schema.json, copied to docs/records.schema.json) is for
everyone else. jsonschema is a test-only dependency.
"""

import json
from importlib import resources
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from judgekeeper.records import problems
from tests.test_records_format import BAD, FULL

ROOT = Path(__file__).resolve().parent.parent
PACKAGED = ROOT / "src" / "judgekeeper" / "schemas" / "records.schema.json"
DOCS_COPY = ROOT / "docs" / "records.schema.json"
EXAMPLES = sorted((ROOT / "docs" / "examples" / "records").glob("*.jsonl"))


@pytest.fixture(scope="module")
def validator():
    schema = json.loads(PACKAGED.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def test_the_schema_is_draft_2020_12():
    schema = json.loads(PACKAGED.read_text(encoding="utf-8"))
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"


def test_the_docs_copy_is_the_same_file():
    assert DOCS_COPY.read_bytes() == PACKAGED.read_bytes()


def test_the_schema_ships_inside_the_package():
    text = resources.files("judgekeeper").joinpath("schemas/records.schema.json").read_text(
        encoding="utf-8")
    assert json.loads(text)["title"]


def test_there_are_three_example_files():
    assert [p.name for p in EXAMPLES] == ["full.jsonl", "minimal.jsonl",
                                          "with-human-labels.jsonl"]


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.name)
def test_both_accept_every_example_record(validator, path):
    for line in path.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        assert validator.is_valid(record), list(validator.iter_errors(record))
        assert problems(record) == []


GOOD = [
    {"label": "pass"},
    {},
    FULL,
    {"score": "0.75"},
    {"score": True},
    {"annotator_kind": "llm_judge", "label": True},
    {"annotator_kind": " Human ", "label": "fail"},
    {"target_id": 7, "run": "2", "name": "q", "created_at": 20261001},
    {"evaluator": "{\"model\": \"m\"}"},
    {"evaluator": {"temperature": "0.2", "endpoint": None, "anything": [1]}},
    {"metadata": {}, "trajectory": [], "outcome": {"score": 0.5}, "app_version": 3},
    {"trajectory": [{"role": "user", "content": [{"type": "text", "text": "hi"}]}]},
    {"schema_version": 7, "new_field": {"a": 1}},
    {"input": {"question": "q"}, "output": ["a", "b"], "label": None, "score": None},
]


@pytest.mark.parametrize("record", GOOD)
def test_both_accept_good_records(validator, record):
    assert problems(record) == []
    assert validator.is_valid(record), list(validator.iter_errors(record))


@pytest.mark.parametrize("bad, words", BAD)
def test_both_reject_bad_records(validator, bad, words):
    record = {"label": "pass", **bad}
    assert problems(record)
    assert not validator.is_valid(record)
