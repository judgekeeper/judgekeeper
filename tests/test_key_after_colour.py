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
BROKEN_CODES = ["\x1b[3\u200b1m", "\x1b\u200b[31m", "\x1b[\x001m", "\x1b[3\xad1m",
                "\x1b[3\x071m", "\x1b[\x1b31m", "\x1b[3\x8e1m", "\x8e[31m", "\x9b[31m",
                "\x1bO\x07P"]
# As logs and other tools keep them
LOG_CODES = ["[38:5:196m", "[2K", "[K", "[1G", "[?25l", "[10;20H", "%1B%5B31m", "\\23331m",
             "\\02331m", "\x1b]0;t\x9c", "[1;24r", "[12d", "[1P", "[2X", "[1L", "[1M",
             "[>4;2m", "[1t", "[=3h", "(B", "(0", ")0"]


@pytest.mark.parametrize("key", KEYS)
@pytest.mark.parametrize("code", CODES)
def test_a_key_right_after_a_terminal_code_is_hidden(key, code):
    for text in (f"{code}{key}", f"before {code}{key}\x1b[0m after", f"word{code}{key}"):
        assert key not in redact.scrub(text), text
        assert redact.REDACTED in redact.scrub(text), text
        assert key not in links.said(text), text


@pytest.mark.parametrize("key", KEYS)
@pytest.mark.parametrize("code", OPEN_CODES + BROKEN_CODES + LOG_CODES)
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


@pytest.mark.parametrize("code", ["\x1b[31m", "\\u001b[31m", "\x1b[3\x071m", "[31m", "\x1b[2K"])
def test_a_secret_with_a_code_between_its_name_and_its_value_is_hidden(code):
    aws = "abcdEFGH1234567890abcdEFGH1234567890abcd"
    assert aws not in redact.scrub(f'"aws_secret_access_key": "{code}{aws}"')
    token = "abcdEFGH1234567890abcdEFGH"
    assert token not in redact.scrub(f"https://{code}{token}@host.example/")


@pytest.mark.parametrize("code", ["\x1b[3\x071m", "\x1b[31m"])
def test_a_named_secret_after_a_code_is_hidden(code):
    token = "abcdEFGH1234567890abcd"
    assert token not in redact.scrub(f"{code}Bearer {token}")
    assert "s3cretpass" not in redact.scrub(f"{code}https://user:s3cretpass@host.example/")


@pytest.mark.parametrize("key", KEYS)
@pytest.mark.parametrize("code", ["\x1b[31m", "\x1b[m\x1b[K", "\x1b[0m", "\\u001b[0m", "[K"])
def test_a_code_anywhere_in_a_key_hides_all_of_it(key, code):
    for at in range(1, len(key)):
        assert redact.scrub(f"{key[:at]}{code}{key[at:]}") == redact.REDACTED, at


@pytest.mark.parametrize("key", KEYS)
@pytest.mark.parametrize("before", ["word", "10:22:01", "Key"])
@pytest.mark.parametrize("lead", ["\x1b[31m", "\x1b[01;31m\x1b[K", "\\u001b[31m", "[31m"])
def test_a_code_in_a_key_after_a_word_and_a_code_hides_all_of_it(key, before, lead):
    for at in range(1, len(key)):
        said = redact.scrub(f"{before}{lead}{key[:at]}\x1b[0m{key[at:]} end")
        assert said.endswith(f"{redact.REDACTED} end") and key[:3] not in said, at


def test_grep_colours_around_the_start_of_a_key_hide_all_of_it():
    key = KEYS[0]
    text = f"key=\x1b[01;31m\x1b[K{key[:17]}\x1b[m\x1b[K{key[17:]}"
    assert redact.scrub(text) == f"key=\x1b[01;31m\x1b[K{redact.REDACTED}"


def test_a_known_value_with_a_code_in_it_is_hidden_whole(monkeypatch):
    value = "Zy9Xw8Vu" * 6
    monkeypatch.setenv("OPENAI_API_KEY", value)
    assert redact.scrub(f"{value[:20]}\x1b[0m{value[20:]}") == redact.REDACTED


def test_a_named_secret_with_a_code_in_it_is_hidden_whole():
    said = redact.scrub("Authorization: Bearer abcdEFGH1234567890\x1b[0mabcd1234")
    assert said == f"Authorization: Bearer {redact.REDACTED}"


def test_words_beside_a_secret_found_across_a_code_stay():
    aws = "wJalrXUtnFEMIK7MDENGbPxRfiCYEXAMPLEKEY12"
    said = redact.scrub(f'[FAIL] [Section 2] "aws_secret_access_key": "\x1b[31m{aws}" [Done]')
    assert said == f'[FAIL] [Section 2] "aws_secret_access_key": "\x1b[31m{redact.REDACTED}" [Done]'


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
                 "risk-assessment-framework-for-teams-and-people",
                 "[ask-the-user-for-some-more-details-first]", "see [2] and [K] and [1m]",
                 "Basic [AuthenticationProvider]", "Bearer [TOKEN_FROM_STEP_1_ABCDEF]",
                 "[Ask-the-question-right-now-please]", "(Bearer of the news)", "(0 of 12)"):
        assert redact.scrub(text) == text


def test_text_around_the_key_is_kept():
    key = KEYS[0]
    assert redact.scrub(f"see \x1b[31m{key}\x1b[0m here") == (
        f"see \x1b[31m{redact.REDACTED}\x1b[0m here")


def test_a_long_text_of_codes_stays_fast():
    import time

    for text in ("\x1b[" * 200_000 + "1" * 200_000, "\\e]\u200b" * 250_000, "\\e]" * 330_000,
                 "ESC]" * 250_000, "[" * 100_000 + "1m" + "m" * 100_000):
        start = time.monotonic()
        redact.scrub(text)
        assert time.monotonic() - start < 6, text[:8]


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
