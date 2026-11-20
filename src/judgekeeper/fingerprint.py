"""Judge fingerprint: who judged, with what prompt, at what settings, when.

Every identity field may be None, meaning unknown: data imported from a spreadsheet or a
homemade judge rarely records the snapshot or the temperature. `endpoint` is the exception,
because None already means the provider's default endpoint; an unknown endpoint is the string
"unknown".
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, fields, replace
from datetime import UTC, datetime

# Fields that must match for two judgment files to count as the same judge.
IDENTITY_FIELDS = ("provider", "model", "prompt_hash", "rubric_version", "temperature",
                   "endpoint")
# Fields that can be unknown, in the order reports list them.
UNKNOWN_FIELDS_ORDER = ("provider", "model", "snapshot", "endpoint", "prompt_hash",
                        "rubric_version", "temperature")
ENDPOINT_UNKNOWN = "unknown"


def is_unknown(field: str, value) -> bool:
    if field == "endpoint":
        return value == ENDPOINT_UNKNOWN
    return value is None


def unknown_fields(fp: dict) -> list[str]:
    """Identity fields of a fingerprint dict that are unknown. A missing key is unknown, except
    `endpoint`, whose absence means the provider default."""
    return [f for f in UNKNOWN_FIELDS_ORDER if is_unknown(f, fp.get(f))]


def utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class JudgeFingerprint:
    provider: str | None = None
    model: str | None = None
    snapshot: str | None = None
    prompt_hash: str | None = None
    rubric_version: str | None = None
    temperature: float | None = None
    created_at: str | None = None
    # Host of the base URL the judge was reached through; None for the provider's default.
    # Optional, so files that never recorded an endpoint still load (as the default endpoint).
    endpoint: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> JudgeFingerprint:
        """Missing fields read as unknown (None); unknown keys are ignored."""
        if not isinstance(data, dict):
            raise ValueError("fingerprint must be a JSON object")  # noqa: TRY004 - callers map ValueError
        names = {f.name for f in fields(cls)}
        return cls(**{k: data[k] for k in names if k in data})

    def unknown_fields(self) -> list[str]:
        return unknown_fields(self.to_dict())

    def identity(self) -> tuple:
        return tuple(getattr(self, f) for f in IDENTITY_FIELDS)

    def with_(self, **changes) -> JudgeFingerprint:
        return replace(self, **changes)


def rule_hash(rule: str | None) -> str | None:
    """The judge's rule as "sha256:<hex>", the same on every system (line endings as \\n);
    None when the rule is not known."""
    if rule is None:
        return None
    text = rule.replace("\r\n", "\n").replace("\r", "\n")
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()

