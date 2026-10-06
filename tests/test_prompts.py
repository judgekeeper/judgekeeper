import hashlib

import pytest

from judgekeeper.prompts import PromptError, load_prompt, parse_verdict

PROMPT = """---
rubric_version: pairwise-v1
---
Instruction: {{input}}
Output A: {{output_a}}
Output B: {{output_b}}
End with "Verdict: A" or "Verdict: B".
"""


def test_load_prompt_reads_frontmatter_and_hashes_full_file(tmp_path):
    p = tmp_path / "pairwise.md"
    p.write_text(PROMPT, encoding="utf-8")
    prompt = load_prompt(p)
    assert prompt.rubric_version == "pairwise-v1"
    assert prompt.prompt_hash == hashlib.sha256(PROMPT.encode()).hexdigest()
    assert "rubric_version" not in prompt.template


def test_prompt_hash_ignores_line_endings(tmp_path):
    a = tmp_path / "a.md"
    b = tmp_path / "b.md"
    a.write_text(PROMPT, encoding="utf-8")
    b.write_bytes(PROMPT.replace("\n", "\r\n").encode())
    assert load_prompt(a).prompt_hash == load_prompt(b).prompt_hash


def test_render_does_not_interpret_braces_in_content(tmp_path):
    p = tmp_path / "pairwise.md"
    p.write_text(PROMPT, encoding="utf-8")
    text = load_prompt(p).render(input="f({x})", output_a="{output_b}", output_b="b")
    assert "Instruction: f({x})" in text
    assert "Output A: {output_b}" in text
    assert "Output B: b" in text


def test_missing_rubric_version_rejected(tmp_path):
    p = tmp_path / "x.md"
    p.write_text("no frontmatter {{input}}", encoding="utf-8")
    with pytest.raises(PromptError, match="rubric_version"):
        load_prompt(p)


@pytest.mark.parametrize(
    "text,allowed,expected",
    [
        ("blah\nVerdict: A", ("A", "B"), "A"),
        ("Verdict: A ... on reflection\n**Verdict:** B", ("A", "B"), "B"),
        ("verdict: output b", ("A", "B"), "B"),
        ("Verdict: PASS", ("pass", "fail"), "pass"),
        ("Verdict: fail.", ("pass", "fail"), "fail"),
        ("I cannot decide", ("A", "B"), None),
        ("Verdict: C", ("A", "B"), None),
    ],
)
def test_parse_verdict(text, allowed, expected):
    assert parse_verdict(text, allowed) == expected
