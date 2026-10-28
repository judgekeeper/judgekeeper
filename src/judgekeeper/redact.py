"""Scrub credentials out of text before it is written to disk or shown to the user.

Two layers. First, the current value of every credential environment variable this process
can see (the known names, every provider key name `keys.py` knows or found, and any name
ending in _API_KEY, _TOKEN or _SECRET); values shorter than 8 characters are ignored, since
they would match ordinary text. Second, as a backstop for keys not in the environment, strings
shaped like a key (_KEY_SHAPES), Bearer and Basic headers, and the login part of a URL
(`user:password@`, `:password@`, or a long token alone). A key split by a hidden character is
looked for with the character dropped, and a key right after one even after a letter.

`printable` drops terminal escape sequences from text taken from an input file, and
`one_line` also turns every line break into a space, so a name from a results file can never
start a line of its own (one that could look like the `Next:` line). A judge fingerprint is
scrubbed too: its model and snapshot come from the provider's response, and a gateway can put
anything there.
"""

from __future__ import annotations

import functools
import itertools
import os
import re

REDACTED = "[REDACTED]"
_MASK = "\ue000"  # where a credential was, while scrub() works out what to hide
CREDENTIAL_VARS = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "LANGFUSE_PUBLIC_KEY",
                   "LANGFUSE_SECRET_KEY", "MLFLOW_TRACKING_PASSWORD", "AWS_ACCESS_KEY_ID",
                   "AWS_SECRET_ACCESS_KEY")
CREDENTIAL_SUFFIXES = ("_API_KEY", "_TOKEN", "_SECRET")
MIN_SECRET_LENGTH = 8

# Variables registered during this process (the key names keys.py found).
_named_vars: set[str] = set()
# Credentials registered during this process that are not in the environment (a key in the
# project's .env files or promptfoo's config `env:` block, keys.hide_keys): only hidden, never
# passed on
_named_values: set[str] = set()

_TOKEN_CHARS = r"[A-Za-z0-9._~+/=-]"
_BEARER = re.compile(rf"(\bBearer\s+)(?={_TOKEN_CHARS}*\d){_TOKEN_CHARS}{{16,}}", re.IGNORECASE)
_BASIC = re.compile(r"(\bBasic\s+)[A-Za-z0-9+/]{16,}={0,2}", re.IGNORECASE)
# The scheme is bounded: unbounded, every word start in "a.a.a.a..." would scan to the end of
# the run looking for "://", making scrub() quadratic on long dotted text.
_URL_USERINFO = re.compile(
    r"(\b[A-Za-z][A-Za-z0-9+.-]{0,30}://)(?:[^/@\s:]+:[^/@\s]*|:[^/@\s]+)@")
# A token as the whole login (`https://<token>@host`): long, with a digit, so `git@` stays
_URL_TOKEN = re.compile(r"(\b[A-Za-z][A-Za-z0-9+.-]{0,30}://)(?=[^/@\s:]*\d)"
                        r"[A-Za-z0-9._~+=-]{20,}@")
_START = r"(?<![A-Za-z0-9])"  # a key starts after anything but a letter or digit (`key_sk-`)
# Each key shape as (what must not come before it, the key)
_SHAPES = (
    (_START, r"sk-ant-[A-Za-z0-9_-]{8,}"),
    (_START, r"sk-[A-Za-z0-9_-]{20,}"),
    (r"\b", r"(?:AKIA|ASIA)[A-Z0-9]{16}\b"),  # AWS access keys
    (r"\b", r"gh[opsu]_[A-Za-z0-9]{30,}"),  # GitHub tokens
    (r"\b", r"github_pat_[A-Za-z0-9_]{30,}"),
    (r"\b", r"AIza[A-Za-z0-9_-]{30,}"),  # Google API keys
    (r"\b", r"xox[bp]-[A-Za-z0-9-]{20,}"),  # Slack tokens
    (_START, r"gsk_[A-Za-z0-9]{20,}"),  # Groq
    (_START, r"hf_[A-Za-z0-9]{30,}"),  # Hugging Face
    (_START, r"xai-[A-Za-z0-9]{20,}"),  # xAI
    # a JWT: two base64url parts that start with {" and a signature (empty when unsigned)
    (r"(?<![A-Za-z0-9_-])", r"eyJ[A-Za-z0-9_-]{5,}\.eyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]*"),
)
_KEY_SHAPES = tuple(re.compile(before + key) for before, key in _SHAPES)
# The same keys with nothing checked before them: for a key right after a hidden character,
# which reads as a space even with a letter before it (`key<ZWSP>sk-…`)
_KEY_ANYWHERE = tuple(re.compile(key) for _, key in _SHAPES)
# An AWS secret has no shape of its own: it is found after its name (then `=`, `:` or a
# space), or as a 40-character string on the same line as an AWS access key. A bare one with
# neither clue stays: guessing would hide real text.
_AWS_SECRET = re.compile(
    r"(\baws_secret_access_key[\"']?(?:\s*[:=]\s*|\s+)[\"']?)[A-Za-z0-9/+=]{40}", re.IGNORECASE)
_AWS_KEY_ID = re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")
_AWS_SECRET_SHAPE = re.compile(r"(?<![A-Za-z0-9/+=])[A-Za-z0-9/+=]{40}(?![A-Za-z0-9/+=])")
_LINE = re.compile(r"[^\n]+")


# C0 controls other than tab and newline, DEL, and the C1 range: what a terminal acts on.
# And characters that change how text reads without being seen (_HIDDEN): the Unicode format
# characters (category Cf: zero-width ones, the marks, overrides and isolates of
# bidirectional text, the byte order mark, the tag characters an AI model reads as plain
# text) and the Default_Ignorable_Code_Point set (variation selectors, the combining grapheme
# joiner, the Hangul fillers, and the code points kept for more of them), and the braille
# blank, a symbol that shows as nothing. A name holding them could pass for another name.
# Unicode 16; test_security_refusals checks it against Python's own list.
_HIDDEN = ("\u00ad\u034f\u0600-\u0605\u061c\u06dd\u070f\u0890\u0891\u08e2\u115f\u1160"
           "\u17b4\u17b5\u180b-\u180f\u200b-\u200f\u202a-\u202e\u2060-\u206f\u2800\u3164"
           "\ufe00-\ufe0f\ufeff\uffa0\ufff0-\ufffb\U000110bd\U000110cd\U00013430-\U0001343f"
           "\U0001bca0-\U0001bca3\U0001d173-\U0001d17a\U000e0000-\U000e0fff")
_CONTROL = re.compile(f"[\\x00-\\x08\\x0b-\\x1f\\x7f-\\x9f{_HIDDEN}]")
# What can hide inside a credential: every character `printable` drops (a carriage return
# too), so a key split by one is never joined back when it prints
_SPLITTERS = _CONTROL
# A page keeps the two joiners (U+200C, U+200D): joined emoji and scripts such as Persian
# and Hindi need them to read right. A credential split by one is still found (_SPLITTERS).
# The spaces that look like none or like a line break on a page (_ODD_SPACES) each show as
# a plain space.
_UNSEEN = re.compile(f"(?![\\u200c\\u200d])[\\x00-\\x08\\x0b\\x0c\\x0e-\\x1f\\x7f-\\x9f{_HIDDEN}]")
_ODD_SPACES = re.compile("[\u00a0\u2028\u2029\u3000]")


def printable(text) -> str:
    """`text` without control characters (tab and newline stay), safe to print to a terminal."""
    return _CONTROL.sub("", str(text))


def visible(text: str) -> str:
    """`text` for a page: control characters (ESC among them), zero-width and bidirectional
    controls dropped; a no-break space, an ideographic space and a Unicode line or paragraph
    separator each a plain space; tabs, line breaks and the zero-width joiners stay."""
    return _ODD_SPACES.sub(" ", _UNSEEN.sub("", text))


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


def register_secret(name: str, value: str) -> None:
    """Treat `value` as a credential from now on when `name` is a credential's name."""
    if _is_credential_var(name) and len(value) >= MIN_SECRET_LENGTH:
        _named_values.add(value)


def _is_credential_var(name: str) -> bool:
    return (name in CREDENTIAL_VARS or name in _named_vars or name in _key_names()
            or name.upper().endswith(CREDENTIAL_SUFFIXES))


def is_credential(name: str) -> bool:
    """Whether a variable named `name` holds a credential whose value is hidden."""
    return _is_credential_var(name)


@functools.cache
def _key_names() -> frozenset[str]:
    """The API key names of the providers judgekeeper knows (AWS_BEARER_TOKEN_BEDROCK among
    them): each one's value is hidden, never passed on."""
    from judgekeeper.keys import key_names  # keys imports this module

    return frozenset(key_names())


_cached: tuple = (None, [])  # (the environment and named variables read, their secrets)


def _secret_values() -> list[str]:
    """The credentials in the environment, longest first. Worked out again only when the
    environment changed: a big results file has hundreds of thousands of strings to scrub."""
    global _cached
    data = getattr(os.environ, "_data", None)  # the raw environment: compared, not decoded
    key = None if data is None else (tuple(data.items()), frozenset(_named_vars),
                                     frozenset(_named_values))
    if key is not None and _cached[0] == key:
        return _cached[1]
    values = {
        value for name, value in os.environ.items()
        if _is_credential_var(name) and len(value) >= MIN_SECRET_LENGTH
    } | _named_values
    # Longest first, so a value that contains another is replaced whole.
    found = sorted(values, key=len, reverse=True)
    _cached = (key, found)
    return found


def scrub(text: str | None) -> str | None:
    """Return `text` with every credential replaced by [REDACTED]. None passes through. A
    credential split by a hidden character (which a page or the terminal then drops), or right
    after one, is found too: then the text comes back without its hidden characters."""
    if not text:
        return text
    scrubbed = _scrub(text)
    if not _SPLITTERS.search(text):
        return scrubbed
    # Read three ways: as it is, with the hidden characters dropped (a key split by one), and
    # with a key starting right after one even when a letter comes before. What any of them
    # hides stays hidden.
    kept = [i for i, c in enumerate(text) if not _SPLITTERS.match(c)]
    joined = "".join(text[i] for i in kept)
    as_is = _hidden(text)
    before = [as_is[i] for i in kept]
    hidden = [a or b for a, b in zip(before, _hidden(joined))]
    for at, i in enumerate(kept):
        if i and _SPLITTERS.match(text[i - 1]):
            for pattern in _KEY_ANYWHERE:
                if found := pattern.match(joined, at):
                    hidden[at:found.end()] = [True] * (found.end() - at)
    if hidden == before:
        return scrubbed
    return "".join(REDACTED if hide else "".join(c for c, _ in run)
                   for hide, run in itertools.groupby(zip(joined, hidden), lambda c: c[1]))


def _hidden(text: str) -> list[bool]:
    """Which characters of `text` _scrub hides."""
    masked = _scrub(text, lambda found: _MASK * len(found))
    return [m == _MASK != c for m, c in zip(masked, text)]


def _scrub(text: str, hide=lambda found: REDACTED) -> str:
    """`text` with every credential found in it put through `hide`."""
    def after_name(m):  # the name before a credential stays
        return m[1] + hide(m[0][len(m[1]):])

    def login(m):  # and the @ after a URL's login
        return m[1] + hide(m[0][len(m[1]):-1]) + "@"

    for value in _secret_values():
        text = text.replace(value, hide(value))
    text = _BEARER.sub(after_name, text)
    text = _BASIC.sub(after_name, text)
    text = _URL_USERINFO.sub(login, text)
    text = _URL_TOKEN.sub(login, text)
    text = _AWS_SECRET.sub(after_name, text)
    if _AWS_KEY_ID.search(text):
        text = _LINE.sub(lambda m: _AWS_SECRET_SHAPE.sub(lambda s: hide(s[0]), m[0])
                         if _AWS_KEY_ID.search(m[0]) else m[0], text)
    for pattern in _KEY_SHAPES:
        text = pattern.sub(lambda m: hide(m[0]), text)
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
