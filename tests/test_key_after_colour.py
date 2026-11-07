"""A key right after a terminal colour code is hidden, as SECURITY.md says.

The code's last letter (the `m` of `\\x1b[31m`) touches the key, and a key only starts after
something that is not a letter or digit, so it needs a reading of its own.
"""

from __future__ import annotations

import json

import pytest

from judgekeeper import links, redact

KEYS = ["sk-ant-api03-" + "A1b2C3d4" * 5, "sk-proj" + "A1b2C3d4" * 5, "AKIA" + "ABCDEFGH12345678",
        "ghp_" + "A1b2C3d4" * 5, "github_pat_" + "A1b2C3d4" * 5, "AIza" + "A1b2C3d4" * 5,
        "xoxb-" + "A1b2C3d4" * 3, "gsk_" + "A1b2C3d4" * 4, "hf_" + "A1b2C3d4" * 5,
        "xai-" + "A1b2C3d4" * 4, "eyJhbGciOiJI.eyJzdWIiOiIx.abcdefghijkl"]
CODES = ["\x1b[31m", "\x1b[0m", "\x1b[1;31m", "\x1b[38;5;196m", "\x1b[2K", "\x1b[10;20H",
         "\x1b(B", "\x1bM", "\x9b31m", "\\u001b[31m", "\\u001B[31m", "\\x1b[31m", "\\033[31m",
         "\\e[31m", "\\E[31m", "\x1bOP", "\x1bOA", "\x1bNx", "\x8fA", "\x8eA", "[31m", "[0m",
         "[1;31m", "^[[31m", "\u241b[31m", "ESC[31m", "\\u009b31m", "\\x9b31m",
         "\\U0000001b[31m", "\\u{1b}[31m", "&#27;[31m", "&#x1b;[31m", "%1B[31m",
         "\x1b]0;title\x07", "\x1b]0;title\x1b\\", "\\x1b]0;t\\x07", "\\033]0;t\\007",
         "\\u001b]0;t\\u0007"]
# The code's last character is the key's first letter: a code not ended when the key starts
OPEN_CODES = ["\x1b[31", "\x9b31", "\\x1b", "\\033", "\\e", "\\e[1", "\x1b-", "\x1b"]
# A hidden character inside the code
BROKEN_CODES = ["\x1b[3\u200b1m", "\x1b\u200b[31m", "\x1b[\x001m", "\x1b[3\xad1m"]


@pytest.mark.parametrize("key", KEYS)
@pytest.mark.parametrize("code", CODES)
def test_a_key_right_after_a_terminal_code_is_hidden(key, code):
    for text in (f"{code}{key}", f"before {code}{key}\x1b[0m after", f"word{code}{key}"):
        assert key not in redact.scrub(text), text
        assert redact.REDACTED in redact.scrub(text), text
        assert key not in links.said(text), text


@pytest.mark.parametrize("key", KEYS)
@pytest.mark.parametrize("code", OPEN_CODES + BROKEN_CODES)
def test_a_key_after_a_code_left_open_or_broken_is_hidden(key, code):
    for text in (f"{code}{key}", f"before {code}{key} after"):
        assert key not in redact.scrub(text), text
        assert key[-10:] not in redact.scrub(text), text
        assert key not in links.said(text), text


@pytest.mark.parametrize("before, secret", [
    ("Bearer ", "abcdEFGH1234567890abcd"), ("Basic ", "abcdEFGH1234567890abcd"),
    ("aws_secret_access_key=", "abcdEFGH1234567890abcdEFGH1234567890abcd")])
@pytest.mark.parametrize("code", ["\x1b[31m", "\x1b[1;31m", "\\u001b[31m", "\x1b[3\u200b1m"])
def test_a_secret_named_by_what_comes_before_it_is_hidden_after_a_code(before, secret, code):
    assert secret not in redact.scrub(f"{before}{code}{secret}")


def test_a_login_in_a_url_is_hidden_after_a_code():
    assert "s3cretpass" not in redact.scrub("\x1b[31mhttps://user:s3cretpass@host.example/")


@pytest.mark.parametrize("key", KEYS)
def test_a_key_after_a_code_and_split_by_a_hidden_character_is_hidden(key):
    for at in (1, 2, 5):
        text = f"\x1b[31m{key[:at]}\u200d{key[at:]}\x1b[0m"
        said = redact.scrub(text)
        assert redact.REDACTED in said and key[-10:] not in said, text


def test_text_with_a_code_and_no_key_stays_as_it_is():
    for text in ("\x1b[31mred\x1b[0m", "\\e[31m plain", "\\033[1m skills and more",
                 "\x1b[31mskipped this one", "C:\\e[1]\\file.txt", "see [31m and [1m",
                 "ESC[31m is a colour", "task-force-of-twenty-one-people-working", "50%1B[31m",
                 "risk-assessment-framework-for-teams-and-people"):
        assert redact.scrub(text) == text


def test_text_around_the_key_is_kept():
    key = KEYS[0]
    assert redact.scrub(f"see \x1b[31m{key}\x1b[0m here") == (
        f"see \x1b[31m{redact.REDACTED}\x1b[0m here")


def test_a_long_text_of_codes_stays_fast():
    import time

    text = "\x1b[" * 200_000 + "1" * 200_000
    start = time.monotonic()
    redact.scrub(text)
    assert time.monotonic() - start < 5


def test_no_file_keeps_a_key_after_a_code(tmp_path, monkeypatch, capsys):
    from judgekeeper.cli import main

    key = KEYS[0]
    rows = ["question,answer,verdict,reason"]
    rows += [json.dumps(f"Q{i} \x1b[31m{key}\x1b[0m", ensure_ascii=False) + ","
             + json.dumps(f"A{i} \x1b[31m{key}\x1b[0m", ensure_ascii=False) + ","
             + ("pass" if i % 2 else "fail") + ","
             + json.dumps(f"\x1b[31m{key}\x1b[0m", ensure_ascii=False) for i in range(40)]
    (tmp_path / "results.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    try:
        main(["--no-browser", "--port", "0", "--yes"])
    finally:
        main(["--stop"])
    assert key not in capsys.readouterr().out
    written = [p for p in (tmp_path / ".judgekeeper").rglob("*") if p.is_file()]
    assert written
    for path in written:
        assert key not in path.read_text(encoding="utf-8", errors="replace"), path
