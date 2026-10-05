"""Judge fingerprint: who judged, with what prompt, at what settings, when.

Every identity field may be None, meaning unknown: data imported from a spreadsheet or a
homemade judge rarely records the snapshot or the temperature. `endpoint` is the exception,
because None already means the provider's default endpoint; an unknown endpoint
is the string "unknown".
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields, replace
from datetime import UTC, datetime
from urllib.parse import urlsplit

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
    # Optional so that files written before endpoints were recorded still load (as the default endpoint).
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


def endpoint_host(base_url: str | None) -> str | None:
    """The host of a base URL, for the fingerprint: no scheme, port, path, query or credentials.

    Raises ValueError for a URL that carries credentials (user:password@host) or is not an
    http(s) URL with a host. The message never repeats the URL, which may hold a secret.
    """
    if not base_url:
        return None
    parts = urlsplit(base_url)
    if "@" in parts.netloc:
        raise ValueError(
            "base URL must not contain credentials (user:password@host); put the key in an "
            "environment variable and name it with --api-key-env"
        )
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("base URL must be an http:// or https:// URL with a host, "
                         "e.g. https://gateway.example.com/v1")
    return parts.hostname


LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1")


def is_local_host(hostname: str) -> bool:
    return hostname in LOCAL_HOSTS or hostname.endswith(".localhost")


def plaintext_warning(url: str | None) -> str | None:
    """A warning when `url` is plain http:// to a host that is not this machine, else None.

    The key and every judgment would travel unencrypted. Names the host only, never the URL.
    """
    if not url:
        return None
    parts = urlsplit(url)
    if parts.scheme != "http" or not parts.hostname or is_local_host(parts.hostname):
        return None
    return (f"{parts.hostname} is reached over plain http://, so the API key and every request "
            "travel unencrypted; use https:// unless this is a local server")
