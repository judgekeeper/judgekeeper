"""Scrub credentials out of text before it is written to disk or shown to the user.

Two layers. First, the current value of every credential environment variable this process
can see: ANTHROPIC_API_KEY, OPENAI_API_KEY, the platform credentials (LANGFUSE_PUBLIC_KEY,
LANGFUSE_SECRET_KEY, MLFLOW_TRACKING_PASSWORD), the AWS keys (AWS_ACCESS_KEY_ID,
AWS_SECRET_ACCESS_KEY), every key name `keys.py` found for a judge, and any variable whose name ends in _API_KEY, _TOKEN or _SECRET. Values shorter
than 8 characters are ignored, since they would match ordinary text. Second, as a backstop for
keys that are not in the environment, strings shaped like provider keys (sk-ant-..., sk-...),
Bearer and Basic headers, and the user:password part of a URL.

`printable` is the other half of "shown to the user": text taken from an input file may hold
terminal escape sequences, which could retitle or clear the terminal it is printed to.
`one_line` also turns every line break into a space: each line judgekeeper says is printed by
one call, so a name from a results file can never start a line of its own (one that could
look like the `Next:` line).

A judge fingerprint is scrubbed too (`scrub_fingerprint`): its model and snapshot come from
the provider's response, and a gateway can put anything there.
"""

from __future__ import annotations

import os
import re

REDACTED = "[REDACTED]"
CREDENTIAL_VARS = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "LANGFUSE_PUBLIC_KEY",
                   "LANGFUSE_SECRET_KEY", "MLFLOW_TRACKING_PASSWORD", "AWS_ACCESS_KEY_ID",
                   "AWS_SECRET_ACCESS_KEY")
CREDENTIAL_SUFFIXES = ("_API_KEY", "_TOKEN", "_SECRET")
MIN_SECRET_LENGTH = 8

# Variables registered during this process (the key names keys.py found).
_named_vars: set[str] = set()

_TOKEN_CHARS = r"[A-Za-z0-9._~+/=-]"
_BEARER = re.compile(rf"(\bBearer\s+)(?={_TOKEN_CHARS}*\d){_TOKEN_CHARS}{{16,}}", re.IGNORECASE)
_BASIC = re.compile(r"(\bBasic\s+)[A-Za-z0-9+/]{16,}={0,2}", re.IGNORECASE)
# The scheme is bounded: unbounded, every word start in "a.a.a.a..." would scan to the end of
# the run looking for "://", making scrub() quadratic on long dotted text.
_URL_USERINFO = re.compile(r"(\b[A-Za-z][A-Za-z0-9+.-]{0,30}://)[^/@\s:]+:[^/@\s]*@")
_KEY_SHAPES = (
    re.compile(r"\bsk-ant-[A-Za-z0-9_-]{8,}"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}"),
)


# C0 controls other than tab and newline, DEL, and the C1 range: what a terminal acts on.
# And characters that change how text reads without being seen (_HIDDEN): zero-width ones,
# the marks, overrides and isolates of bidirectional text, and the byte order mark. A name
# holding them could pass for another name.
_HIDDEN = "\u200b-\u200f\u202a-\u202e\u2066-\u2069\ufeff"
_CONTROL = re.compile(f"[\\x00-\\x08\\x0b-\\x1f\\x7f-\\x9f{_HIDDEN}]")
_UNSEEN = re.compile(f"[\\x00-\\x08\\x0b\\x0c\\x0e-\\x1f\\x7f-\\x9f{_HIDDEN}]")


def printable(text) -> str:
    """`text` without control characters (tab and newline stay), safe to print to a terminal."""
    return _CONTROL.sub("", str(text))


def visible(text: str) -> str:
    """`text` for a page: control characters (ESC among them), zero-width and bidirectional
    controls dropped; tabs and line breaks stay."""
    return _UNSEEN.sub("", text)


def visible_value(value):
    """`value` with every string in it (inside lists and objects too, keys as well) visible."""
    if isinstance(value, str):
        return visible(value)
    if isinstance(value, list):
        return [visible_value(v) for v in value]
    if isinstance(value, dict):
        return {visible_value(k): visible_value(v) for k, v in value.items()}
    return value


# Every character str.splitlines() splits at: a name holding one could start a new line.
_LINE_BREAKS = re.compile("[\n\r\x0b\x0c\x1c\x1d\x1e\x85\u2028\u2029]")


def one_line(text) -> str:
    """`printable` text with every line break turned into a space: one line of output."""
    return printable(_LINE_BREAKS.sub(" ", str(text)))


def register_key_env(name: str) -> None:
    """Treat the value of environment variable `name` as a credential from now on."""
    _named_vars.add(name)


def _is_credential_var(name: str) -> bool:
    return (name in CREDENTIAL_VARS or name in _named_vars
            or name.upper().endswith(CREDENTIAL_SUFFIXES))


def _secret_values() -> list[str]:
    values = {
        value for name, value in os.environ.items()
        if _is_credential_var(name) and len(value) >= MIN_SECRET_LENGTH
    }
    # Longest first, so a value that contains another is replaced whole.
    return sorted(values, key=len, reverse=True)


def scrub(text: str | None) -> str | None:
    """Return `text` with every credential replaced by [REDACTED]. None passes through."""
    if not text:
        return text
    for value in _secret_values():
        text = text.replace(value, REDACTED)
    text = _BEARER.sub(rf"\g<1>{REDACTED}", text)
    text = _BASIC.sub(rf"\g<1>{REDACTED}", text)
    text = _URL_USERINFO.sub(rf"\g<1>{REDACTED}@", text)
    for pattern in _KEY_SHAPES:
        text = pattern.sub(REDACTED, text)
    return text


def scrub_value(value):
    """`value` with every string in it (inside lists and objects too) scrubbed."""
    if isinstance(value, str):
        return scrub(value)
    if isinstance(value, list):
        return [scrub_value(v) for v in value]
    if isinstance(value, dict):
        return {k: scrub_value(v) for k, v in value.items()}
    return value


def scrub_fingerprint(fp, seen: dict | None = None):
    """A fingerprint dict with every string value scrubbed. Anything else passes through.

    `seen` is a cache of values already scrubbed, for callers that write thousands of
    fingerprints that differ only in their timestamp.
    """
    if not isinstance(fp, dict):
        return fp
    seen = {} if seen is None else seen
    out = {}
    for key, value in fp.items():
        if isinstance(value, str):
            if value not in seen:
                seen[value] = scrub(value)
            value = seen[value]
        out[key] = value
    return out
