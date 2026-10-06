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
from judgekeeper.gate import FLAKY, JUDGE_CHANGED, PASS, evaluate, load_report

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
    # A missing endpoint is the provider default (files written before endpoints were recorded), not unknown.
    assert fp.endpoint is None
    assert "endpoint" not in fp.unknown_fields()
    assert fp.unknown_fields() == [f for f in UNKNOWN_FIELDS_ORDER if f != "endpoint"]


def test_unknown_fields_on_a_plain_dict():
    assert unknown_fields(FULL) == []
    assert unknown_fields({**FULL, "temperature": None, "endpoint": ENDPOINT_UNKNOWN}) == [
        "endpoint", "temperature"]


def test_old_reports_and_baselines_still_load(tmp_path):
    from tests.conftest import FIXTURES

    for path in sorted((FIXTURES / "gate").glob("*.json")):
        report = load_report(path)
        JudgeFingerprint.from_dict(report["fingerprint"])
    old = json.loads((FIXTURES / "pairwise" / "baseline.json").read_text(encoding="utf-8"))
    assert evaluate(old, old)["status"] in (PASS, FLAKY)


def _report(fp: dict) -> dict:
    from tests.conftest import FIXTURES

    r = json.loads((FIXTURES / "gate" / "pass.json").read_text(encoding="utf-8"))
    r["fingerprint"] = fp
    return r


def test_gate_known_and_different_is_judge_changed():
    base = _report(FULL)
    now = _report({**FULL, "model": "other", "temperature": None})
    result = evaluate(now, base)
    assert result["status"] == JUDGE_CHANGED
    assert [c["field"] for c in result["judge_changes"]] == ["model"]


def test_gate_unknown_field_warns_and_does_not_block():
    base = _report(FULL)
    now = _report({**FULL, "temperature": None, "snapshot": None})
    result = evaluate(now, base)
    assert result["status"] == PASS
    assert any("snapshot" in w and "temperature" in w and "--require-fingerprint" in w
               for w in result["warnings"])


def test_gate_unknown_endpoint_warns():
    result = evaluate(_report({**FULL, "endpoint": ENDPOINT_UNKNOWN}), _report(FULL))
    assert result["status"] == PASS
    assert any("endpoint" in w for w in result["warnings"])


def test_gate_require_fingerprint_blocks_on_unknown():
    base = _report({**FULL, "temperature": None})
    result = evaluate(_report(FULL), base, require_fingerprint=True)
    assert result["status"] == JUDGE_CHANGED
    assert "cannot prove same judge" in result["reason"].lower()
    assert [c["field"] for c in result["judge_changes"]] == ["temperature"]


def test_gate_require_fingerprint_passes_when_everything_known():
    assert evaluate(_report(FULL), _report(FULL), require_fingerprint=True)["status"] == PASS


def test_cli_require_fingerprint(tmp_path):
    from judgekeeper.cli import main

    base, now = tmp_path / "base.json", tmp_path / "now.json"
    base.write_text(json.dumps(_report({**FULL, "snapshot": None})), encoding="utf-8")
    now.write_text(json.dumps(_report(FULL)), encoding="utf-8")
    assert main(["gate", str(now), "--baseline", str(base), "--out", str(tmp_path / "a")]) == 0
    assert main(["gate", str(now), "--baseline", str(base), "--out", str(tmp_path / "b"),
                 "--require-fingerprint"]) == 5
