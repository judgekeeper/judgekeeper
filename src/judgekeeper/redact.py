"""Scrub credentials out of text before it is written to disk or shown to the user.

Two layers. First, the current value of every credential environment variable this process
can see (the known names, every provider key name `keys.py` knows or found, and any name
ending in _API_KEY, _TOKEN, _SECRET or _PASSWORD); values shorter than 8 characters are
ignored, since they would match ordinary text. Second, as a backstop for keys not in the
environment, strings shaped like a key (_KEY_SHAPES), Bearer and Basic headers, and the
login part of a URL (`user:password@`, `:password@`, or a long token alone). A key split by
a hidden character is looked for with the character dropped, and a key right after one even
after a letter.

`printable` drops terminal escape sequences from text taken from an input file, and
`one_line` also turns every line break into a space, so a name from a results file can never
start a line of its own (one that could look like the `Next:` line). A judge fingerprint is
scrubbed too: its model and snapshot come from the provider's response, and a gateway can put
anything there.
"""

from __future__ import annotations

import bisect
import functools
import itertools
import os
import re
from array import array

REDACTED = "[REDACTED]"
_MASK = "\ue000"  # where a credential was, while scrub() works out what to hide
CREDENTIAL_VARS = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "LANGFUSE_PUBLIC_KEY",
                   "LANGFUSE_SECRET_KEY", "MLFLOW_TRACKING_PASSWORD", "AWS_ACCESS_KEY_ID",
                   "AWS_SECRET_ACCESS_KEY")
CREDENTIAL_SUFFIXES = ("_API_KEY", "_TOKEN", "_SECRET", "_PASSWORD")
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
# A key starts after anything but an ASCII letter or digit (`key_sk-`, `café` and a key). The
# check comes after its first letter, which lets the search jump from one such letter to the next.
def _key(first: str, rest: str, before: str = "A-Za-z0-9") -> re.Pattern:
    return re.compile(f"{first}(?<![{before}]{first}){rest}")


_KEY_SHAPES = (
    _key("s", r"k-ant-[A-Za-z0-9_-]{8,}"),
    _key("s", r"k-[A-Za-z0-9_-]{20,}"),
    _key("A", r"(?:KIA|SIA)[A-Z0-9]{16}(?![A-Za-z0-9])"),  # AWS access keys
    _key("g", r"h[opsu]_[A-Za-z0-9]{30,}"),  # GitHub tokens
    _key("g", r"ithub_pat_[A-Za-z0-9_]{30,}"),
    _key("A", r"Iza[A-Za-z0-9_-]{30,}"),  # Google API keys
    _key("x", r"ox[bp]-[A-Za-z0-9-]{20,}"),  # Slack tokens
    _key("g", r"sk_[A-Za-z0-9]{20,}"),  # Groq
    _key("h", r"f_[A-Za-z0-9]{30,}"),  # Hugging Face
    _key("x", r"ai-[A-Za-z0-9]{20,}"),  # xAI
    # a JWT: two base64url parts that start with {" and a signature (empty when unsigned)
    _key("e", r"yJ[A-Za-z0-9_-]{5,}\.eyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]*", "A-Za-z0-9_-"),
)
# How each key above starts
_KEY_BEGINS = r"(?:sk-|AKIA|ASIA|gh[opsu]_|github_pat_|AIza|xox[bp]-|gsk_|hf_|xai-|eyJ)"
_KEY_START = re.compile(_KEY_BEGINS)
# An escaped character right before a key: `\n` or `\t` (JSON kept as a string in JSON),
# `"`, or a URL's `%20`. Its last letter or digit would join the key's word.
_ESCAPED_KEY = re.compile(rf"(?:\\[nrt]|\\u00[0-9A-Fa-f]{{2}}|%[0-9A-Fa-f]{{2}})(?={_KEY_BEGINS})")
# An AWS secret has no shape of its own: it is found after its name (then `=`, `:` or a
# space), or as a 40-character string on the same line as an AWS access key. A bare one with
# neither clue stays: guessing would hide real text.
_AWS_SECRET = re.compile(
    r"(\baws_secret_access_key[\"']?(?:\s*[:=]\s*|\s+)[\"']?)[A-Za-z0-9/+=]{40}", re.IGNORECASE)
_AWS_KEY_ID = _KEY_SHAPES[2]
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
_SPLIT_RUNS = re.compile(f"{_SPLITTERS.pattern}+")
# Hidden characters right after a letter or digit, before the first letter of a key's start:
# a key may start after them (`key<ZWSP>sk-…`, `key<ZWSP>AK<ZWSP>IA…`)
_AFTER_LETTER = re.compile(f"(?<=[A-Za-z0-9]){_SPLITTERS.pattern}+(?=[sAghxe])")
_MASKED = re.compile(f"{_MASK}+")
# A page keeps the two joiners (U+200C, U+200D): joined emoji and scripts such as Persian
# and Hindi need them to read right. A credential split by one is still found (_SPLITTERS).
# The spaces that look like none or like a line break on a page (_ODD_SPACES) each show as
# a plain space.
_UNSEEN = re.compile(f"(?![\\u200c\\u200d])[\\x00-\\x08\\x0b\\x0c\\x0e-\\x1f\\x7f-\\x9f{_HIDDEN}]")
_ODD_SPACES = re.compile("[\u00a0\u2028\u2029\u3000]")


def printable(text) -> str:
    """`text` without control characters (tab and newline stay), safe to print to a terminal."""
    return _CONTROL.sub("", str(text))


# An emoji's own variation selector (U+FE0E text, U+FE0F emoji) stays on a page, right after
# a character that is not ASCII and not hidden, or in a keycap (1, U+FE0F, U+20E3): "✈️" is
# not "✈". After a letter or a sign it is a hidden mark like the others.
_STYLE = "\ufe0e\ufe0f"


def _style_kept(text: str, at: int) -> bool:
    before = text[at - 1] if at else ""
    if before and ord(before) > 0x7f:
        return not _UNSEEN.match(before)
    return before in "0123456789#*" and before != "" and text[at + 1:at + 2] == "\u20e3"


# The three standard subdivision flags (England, Scotland, Wales) are a black flag (U+1F3F4),
# their tag letters, then U+E007F: those tags stay, every other tag character goes, so no
# hidden text rides on a flag.
_FLAG_CODES = ("gbeng", "gbsct", "gbwls")
_FLAG_TAGS = re.compile("(?<=\U0001F3F4)(?:" + "|".join(
    "".join(chr(0xE0000 + ord(c)) for c in code) for code in _FLAG_CODES) + ")\U000E007F")


def visible(text: str) -> str:
    """`text` for a page: control characters (ESC among them), zero-width and bidirectional
    controls dropped; a no-break space, an ideographic space and a Unicode line or paragraph
    separator each a plain space; tabs, line breaks, the zero-width joiners, an emoji's own
    variation selector (_style_kept) and a flag's tags (_FLAG_TAGS) stay."""
    flags = {i for m in _FLAG_TAGS.finditer(text) for i in range(m.start(), m.end())}

    def drop(m: re.Match) -> str:
        if m.start() in flags:
            return m[0]
        return m[0] if m[0] in _STYLE and _style_kept(text, m.start()) else ""

    return _ODD_SPACES.sub(" ", _UNSEEN.sub(drop, text))


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
    if _is_credential_var(name):
        register_value(value)


def register_value(value: str) -> None:
    """Treat `value` as a credential from now on: a value that may be one, whatever its name."""
    _named_values.update(_forms(value))


def _forms(value: str) -> set[str]:
    """`value` as written and without the spaces or line break at its ends (a key is sent
    without them), when that is MIN_SECRET_LENGTH or longer; else none."""
    core = value.strip()
    return {value, core} if len(core) >= MIN_SECRET_LENGTH else set()


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
        form for name, value in os.environ.items() if _is_credential_var(name)
        for form in _forms(value)
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
    escaped = _ESCAPED_KEY.search(text) is not None
    if not escaped and not _SPLITTERS.search(text):
        return _scrub(text)
    as_is = _spans(text)
    if escaped:  # read once more with each such escape's last character a space
        as_is += _spans(_ESCAPED_KEY.sub(lambda m: m[0][:-1] + " ", text))
    as_is = _merged(as_is)
    if not _SPLITTERS.search(text):
        return _redacted(text, as_is)
    # Read as it is; with each hidden character a space (a key right after one, even after a
    # letter); with them dropped (a key split by one); and with them dropped and a space where
    # one came after a letter and a key starts once they are dropped (a key after one and
    # split by others, even in its first letters). What any reading hides stays hidden.
    to_joined = _shift(_SPLIT_RUNS.finditer(text))
    joined = _SPLITTERS.sub("", text)
    found = [*as_is, *_spans(_SPLITTERS.sub(" ", text))]
    found = [(to_joined(a), to_joined(b)) for a, b in found] + _spans(joined)
    if _ESCAPED_KEY.search(joined):  # an escape before a key split by a hidden character
        found += _spans(_ESCAPED_KEY.sub(lambda m: m[0][:-1] + " ", joined))
    starts = [at for at in (to_joined(m.start()) for m in _AFTER_LETTER.finditer(text))
              if _KEY_START.match(joined, at)]
    if starts:  # a space put into `joined` at each
        cuts = [0, *starts, len(joined)]
        spaced = " ".join(joined[a:b] for a, b in itertools.pairwise(cuts))
        moved = [at + n for n, at in enumerate(starts)]  # where each space is in `spaced`
        for a, b in _spans(spaced):
            found.append((a - bisect.bisect_left(moved, a), b - bisect.bisect_left(moved, b)))
    found = _merged(found)
    if found == _merged((to_joined(a), to_joined(b)) for a, b in as_is):
        return _redacted(text, as_is)
    return _redacted(joined, found)


def _spans(text: str) -> list[tuple[int, int]]:
    """Where in `text` _scrub hides a credential, as (start, end) spans."""
    masked = _scrub(text, lambda found: _MASK * len(found))
    return [m.span() for m in _MASKED.finditer(masked) if text[m.start():m.end()] != m[0]]


def _shift(cuts):
    """A function from a position in a text to the same position once the matches `cuts`
    (in order, apart) are taken out of it. Kept as arrays: a text may hold millions."""
    starts, ends, before = array("q"), array("q"), array("q", [0])
    for m in cuts:
        starts.append(m.start())
        ends.append(m.end())
        before.append(before[-1] + m.end() - m.start())

    def at(p: int) -> int:
        k = bisect.bisect_right(starts, p) - 1
        if k < 0:
            return p
        return p - before[k] - min(p, ends[k]) + starts[k]

    return at


def _merged(spans) -> list[tuple[int, int]]:
    """`spans` in order, those that overlap or touch made one, empty ones left out."""
    out: list[tuple[int, int]] = []
    for a, b in sorted(spans):
        if a >= b:
            continue
        if out and a <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def _redacted(text: str, spans: list[tuple[int, int]]) -> str:
    """`text` with each of `spans` (merged) replaced by [REDACTED]."""
    out, at = [], 0
    for a, b in spans:
        out += [text[at:a], REDACTED]
        at = b
    out.append(text[at:])
    return "".join(out)


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
