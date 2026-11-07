"""Secrets in the forms real tools write them: JSON dumps, repr text, diffs, cat -A, env output."""

from __future__ import annotations

import pytest

from judgekeeper import links, redact

ANT = "sk-ant-api03-" + "Qz7Lm2Xp" * 5
AWS = "wJalrXUtnFEMIK7MDENGbPxRfiCYEXAMPLEKEY12"
JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
TOK = "abcdEFGH1234567890abcdEF"


@pytest.mark.parametrize("text, secret", [
    (f"\x1b[31m-{JWT}\x1b[m", JWT),  # git diff --color, a removed line
    (f"[-{JWT}-]", JWT),  # git diff --word-diff=plain
    (f"tests/test_a.py::test_auth[valid-{JWT}] \x1b[32mPASSED\x1b[0m", JWT),  # pytest -v
    (f"12-{JWT}", JWT),  # grep -n -C1
    (f"id_{JWT}", JWT),
    # JSON or repr of a tool's output: a written-out line break or tab before the name
    ('{"stdout": "A=1\\nAWS_SECRET_ACCESS_KEY=' + AWS + '\\nZ=1\\n"}', AWS),
    ("'[default]\\naws_secret_access_key = " + AWS + "\\n'", AWS),
    ('{"stdout": "curl output\\nBearer ' + TOK + '\\n"}', TOK),
    ("'Authorization:\\tBearer " + TOK + "'", TOK),
    ('{"stdout":"x\\nBasic YWxpY2U6c2VjcmV0MTIz\\n"}', "YWxpY2U6c2VjcmV0MTIz"),
    ('{"stdout": "\\u001b[32m$ env\\u001b[0m\\nA=1\\nAWS_SECRET_ACCESS_KEY=' + AWS + '\\nZ=1"}', AWS),
    # AWS secrets under the names tools give them
    ('{"log": "{\\"aws_secret_access_key\\": \\"' + AWS + '\\"}\\n", "stream": "stdout"}', AWS),
    ('{:aws_secret_access_key=>"' + AWS + '"}', AWS),
    (f"TF_VAR_aws_secret_access_key={AWS}", AWS),
    (f"INPUT_AWS_SECRET_ACCESS_KEY={AWS}", AWS),
    ('"SecretAccessKey": "' + AWS + '",', AWS),
    (f"--aws-secret-access-key {AWS}", AWS),
    (f"secret_access_key = {AWS}", AWS),
    (f'aws_secret_key = "{AWS}"', AWS),
    # cat -A, cat -v and cat -t
    (f"KEY^I{ANT}^M$", ANT),
    (f"^[]0;user@host: ~^G{ANT}", ANT),
    (f"50%^M{ANT}", ANT),
    (f"Authorization^IBearer {TOK}", TOK),
    # a control byte written out
    ("b'\\x00" + ANT + "'", ANT),
    ('read(3, "\\0' + ANT + '", 120) = 120', ANT),
    # PHP's json_encode writes / as \/
    ('{"url":"https:\\/\\/u:s3cretpass9@host.example\\/x"}', "s3cretpass9"),
    # a short login still ends in base64 padding
    ("> Authorization: Basic Ym9iOnNlY3JldA==", "Ym9iOnNlY3JldA"),
])
def test_a_secret_is_hidden_as_a_tool_writes_it(text, secret):
    for said in (redact.scrub(text), links.said(text)):
        assert secret not in said


def test_a_url_password_with_an_at_sign_is_hidden_whole():
    said = redact.scrub("postgres://app:p@ssw0rd123@db.example.com:5432/app")
    assert said == f"postgres://{redact.REDACTED}@db.example.com:5432/app"


@pytest.mark.parametrize("text", [
    "Basic training for new staff", "Basic = simple", "basic idea", "[Ask-the-question-right-now-please]",
    "a secret key is a long string", "secret_access_key: see the docs for how to set one",
    "the token-based-authentication-system-for-all", "see ^I and ^M in cat -A output",
    "C:\\temp\\new\\table", "100%^M", "git@github.com:judgekeeper/judgekeeper.git",
    "mail me at someone@example.com, or a@b.example", "abc-eyJ and more text",
])
def test_normal_text_stays(text):
    assert redact.scrub(text) == text


def test_a_mail_address_after_a_url_login_stays():
    said = redact.scrub('"https://u:p@host","mail@x.example"')
    assert said.endswith('@host","mail@x.example"')


TEXTS = [f"see {ANT} here", f"Bearer {TOK}", f"bearer {TOK}", "Basic YWxpY2U6c2VjcmV0MTIz", JWT,
         f"aws_secret_access_key={AWS}", f"SecretAccessKey: {AWS}", f"--aws-secret-key {AWS}",
         f"AKIAABCDEFGH12345678 {AWS}", "ASIAABCDEFGH12345678", "https://u:pass1234@host",
         "https:\\/\\/u:pass1234@host", f"https://{TOK}@host", "ghp_" + "A1b2C3d4" * 5,
         "github_pat_" + "A1b2C3d4" * 5, "AIza" + "A1b2C3d4" * 5, "xoxb-" + "A1b2C3d4" * 3,
         "gsk_" + "A1b2C3d4" * 4, "hf_" + "A1b2C3d4" * 5, "xai-" + "A1b2C3d4" * 4]


@pytest.mark.parametrize("text", TEXTS)
def test_every_secret_scrub_can_hide_shows_a_sign(text):
    """A text with no sign skips every search, so the sign must cover all of them."""
    assert redact._SECRET_SIGN.search(text)
    assert redact._scrub(text) != text


def test_a_value_from_the_environment_needs_no_sign(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "Zy9Xw8Vu" * 6)
    assert redact.scrub("value Zy9Xw8Vu" + "Zy9Xw8Vu" * 5) == f"value {redact.REDACTED}"


def test_the_skip_changes_no_result(monkeypatch):
    import random

    rng = random.Random(9)
    parts = [*TEXTS, "\x1b[31m", "\x1b[0m", "\\u001b[0m", "[K", "\u200b", "word", " ", "\\n", "-"]
    texts = ["".join(rng.choice(parts) for _ in range(rng.randint(1, 6))) for _ in range(3000)]
    fast = [redact.scrub(t) for t in texts]
    monkeypatch.setattr(redact, "_SECRET_SIGN", type("Always", (), {"search": lambda s, t: True})())
    assert fast == [redact.scrub(t) for t in texts]
