"""Unknown-tolerant fingerprints: imported data rarely knows every field."""

import itertools
import json

import pytest

from judgekeeper.fingerprint import (
    ENDPOINT_UNKNOWN,
    UNKNOWN_FIELDS_ORDER,
    JudgeFingerprint,
    unknown_fields,
)

FULL = {"provider": "anthropic", "model": "m", "snapshot": "m-1", "prompt_hash": "h",
        "rubric_version": "v1", "temperature": 0.0, "created_at": "2026-10-01T00:00:00Z",
        "endpoint": "api.example.com"}
OPTIONAL = ("provider", "model", "snapshot", "prompt_hash", "rubric_version", "temperature",
            "endpoint")


def _unknown_value(field):
    return ENDPOINT_UNKNOWN if field == "endpoint" else None


@pytest.mark.parametrize("n", range(len(OPTIONAL) + 1))
def test_round_trip_with_every_combination_of_unknown_fields(n):
    for combo in itertools.combinations(OPTIONAL, n):
        data = {**FULL, **{f: _unknown_value(f) for f in combo}}
        fp = JudgeFingerprint.from_dict(data)
        assert fp.to_dict() == data
        assert JudgeFingerprint.from_dict(json.loads(json.dumps(fp.to_dict()))) == fp
        assert set(fp.unknown_fields()) == set(combo)


def test_from_dict_never_raises_on_missing_fields():
    fp = JudgeFingerprint.from_dict({})
    assert fp.provider is None and fp.model is None and fp.temperature is None
    assert fp.created_at is None
    # A missing endpoint means the provider default (older files have none), not unknown.
    assert fp.endpoint is None
    assert "endpoint" not in fp.unknown_fields()
    assert fp.unknown_fields() == [f for f in UNKNOWN_FIELDS_ORDER if f != "endpoint"]


def test_unknown_fields_on_a_plain_dict():
    assert unknown_fields(FULL) == []
    assert unknown_fields({**FULL, "temperature": None, "endpoint": ENDPOINT_UNKNOWN}) == [
        "endpoint", "temperature"]
