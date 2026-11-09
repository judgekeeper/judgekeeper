"""Keys are hidden before any text is cut for the terminal or a file: a key cut short is too
short for scrub to know, so cutting first would show most of it. And a path given with a
password shows hidden in the "There is no file named …" line, as in its Next line."""
import types

import pytest

from judgekeeper import check, cli, fix, front, mapper, reasons, start, start_fix_rule
from judgekeeper.redact import REDACTED, scrub

BODY = "FAKEk3qZtRwLmXcVbNpHsJdGyAeKuQoWiEr7"  # 36 characters, as a GitHub token's
GHP = "ghp_" + BODY
AWS_BODY = "FAKEk3qZtR/wLmXcVbNpHsJdGyAeKuQoWi+r7T2z"  # 40, as an AWS secret
AWS = "AWS_SECRET_ACCESS_KEY=" + AWS_BODY
KEYS = [(GHP, BODY), (AWS, AWS_BODY)]


def _shows_part(text: str, body: str) -> bool:
    """Whether any 4 characters of the key's secret part show in `text`."""
    return any(body[i:i + 4] in text for i in range(len(body) - 3))


def _texts(width: int):
    """For each key, texts with the key starting at every place around a cut at `width`, so
    the cut falls before it, in it and after it."""
    for key, body in KEYS:
        for pad in range(max(width - len(key) - 4, 0), width + 2):
            yield ("w" * pad + " " + key + " then more words to be cut away here", body)


def test_the_test_keys_are_hidden_whole_and_seen_when_cut():
    for key, body in KEYS:
        assert not _shows_part(scrub(f"use {key} now"), body)
    assert _shows_part(scrub(f"use {GHP[:33]}…"), BODY)  # cut short, scrub can't know it


def _found(rule: str, one_rule: bool = True, tmp=".") -> types.SimpleNamespace:
    return types.SimpleNamespace(reference=None, rule=rule, one_rule=one_rule,
                                 n_rules=1 if one_rule else 3, tool="table", root=str(tmp),
                                 task_file=None)


@pytest.mark.parametrize("one_rule, width", [(True, front.RULE_SHOWN),
                                             (False, front.FIRST_SHOWN)])
def test_finds_rule_line_shows_no_part_of_a_key_where_it_is_cut(tmp_path, one_rule, width):
    for text, body in _texts(width):
        lines = front._rule_lines(_found(text, one_rule, tmp_path))
        shown = scrub("\n".join(lines))  # as the terminal prints it
        assert not _shows_part(shown, body), shown
        assert shown.startswith("Rule:")


def test_fixs_rule_quote_shows_no_part_of_a_key_where_it_is_cut():
    for text, body in _texts(fix.RULE_SHOWN):
        shown = scrub(fix._rule_quote(text))
        assert not _shows_part(shown, body), shown


def test_a_decision_value_shows_no_part_of_a_key_where_it_is_cut():
    for text, body in _texts(front.VALUE_WIDTH):
        shown = scrub(front._shown([text, "pass"]))
        assert not _shows_part(shown, body), shown


def test_a_mapping_example_shows_no_part_of_a_key_where_it_is_cut():
    for text, body in _texts(mapper.EXAMPLE_WIDTH):
        shown = scrub(mapper._example(text))
        assert not _shows_part(shown, body), shown


def test_the_rules_first_line_shows_no_part_of_a_key_where_it_is_cut():
    for text, body in _texts(start.RUBRIC_WIDTH):
        shown = scrub(start.rubric_line(text) or "")
        assert not _shows_part(shown, body), shown


def test_a_matched_rule_line_shows_no_part_of_a_key_where_it_is_cut():
    for text, body in _texts(start_fix_rule.LINE_SHOWN):
        shown = scrub(start_fix_rule._shown(text))
        assert not _shows_part(shown, body), shown


def test_an_answer_in_suggestions_md_shows_no_part_of_a_key_where_it_is_cut():
    for text, body in _texts(reasons.SHOWN):
        row = {"id": "a1", "judge": "pass", "final": "fail", "output": text,
               "reasons": ["left_out"], "words": {}, "parts": [], "spans": [], "why": ""}
        md = reasons.suggestions_md([row])
        assert not _shows_part(md, body), md
        assert "<<<ANSWER\n" in md


def test_short_text_is_still_shown_whole_and_cuts_still_end_in_an_ellipsis(tmp_path):
    assert front._rule_lines(_found("Grade it well.", tmp=tmp_path)) == [
        'Rule:            "Grade it well."']
    long = "Grade it well and " + "say why " * 20
    first = front._rule_lines(_found(long, tmp=tmp_path))[0]
    assert first.endswith('…"') and len(first.split('"')[1]) == front.RULE_SHOWN
    assert fix._rule_quote(long).endswith('…"')
    assert front._shown(["yes", "no"]) == "no, yes"


PW = "FAKEpw7Qx2Lm9Vb4Nc8Z"
URLS = [f"https://user:{PW}@mlflow.example.com",
        f"postgres://admin:{PW}@db.internal:5432/app",
        f"https://user:{PW}@example.com/results.csv"]


@pytest.mark.parametrize("url", URLS)
def test_the_no_such_line_hides_a_password_in_the_path(url):
    line = check.no_such(url)
    assert PW not in line and line.startswith("There is no ")
    assert REDACTED in line


def test_the_no_such_line_is_unchanged_for_a_plain_path():
    assert check.no_such("results-v9.csv") == "There is no file named results-v9.csv here."


@pytest.mark.parametrize("command", [[], ["mark"], ["check"], ["fix"]])
def test_no_command_shows_a_password_given_in_its_path(tmp_path, monkeypatch, capsys, command):
    monkeypatch.chdir(tmp_path)
    for name in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    page = ["--no-browser", "--yes"] if command in ([], ["mark"]) else []  # check, fix: none
    code = cli.main([*command, URLS[0], *page])
    out = capsys.readouterr()
    said = out.out + out.err
    assert code != 0
    assert PW not in said, said
    assert "There is no " in said


SK_BODY = "FAKEk3qZtRwLmXcVbNpHsJdGyAeKuQoWiEr7T2zY5u"
BEARER_BODY = "FAKEk3qZtRwLmXcVbNpH9sJdGyAeKu"
FENCE_KEYS = KEYS + [("sk-proj-" + SK_BODY, SK_BODY),
                     ("Authorization: Bearer " + BEARER_BODY, BEARER_BODY)]


def _fence_texts():
    """Texts with each key starting at every place around fenced's cut: before, across and
    just after it."""
    width = start_fix_rule.CUT
    for key, body in FENCE_KEYS:
        for pad in range(width - len(key) - 4, width + 2):
            yield "w" * pad + " " + key + " then more words to be cut away " + "z" * 60, body


def test_the_fence_keys_are_hidden_whole():
    for key, body in FENCE_KEYS:
        assert not _shows_part(scrub(f"use {key} now"), body)


def test_a_fenced_text_shows_no_part_of_a_key_where_it_is_cut():
    for text, body in _fence_texts():
        shown = start_fix_rule.fenced("ANSWER", text)
        assert not _shows_part(shown, body), shown[-120:]
        assert shown == f"<<<ANSWER\n{scrub(text)[:start_fix_rule.CUT]} (cut)\nANSWER>>>"


def test_a_fenced_text_with_no_key_is_cut_as_before():
    long = "word " * 400
    assert start_fix_rule.fenced("ANSWER", long) == (
        f"<<<ANSWER\n{long[:start_fix_rule.CUT]} (cut)\nANSWER>>>")
    assert start_fix_rule.fenced("QUESTION", "Is it <<<open>>>?") == (
        "<<<QUESTION\nIs it < <<open> >>?\nQUESTION>>>")
    assert start_fix_rule.fenced("RULE", long, cut=False) == f"<<<RULE\n{long}\nRULE>>>"


def test_the_failed_answers_and_mistakes_files_show_no_part_of_a_key_where_it_is_cut():
    from judgekeeper import no_grades

    for text, body in _fence_texts():
        for field in ("input", "output", "why"):
            row = {"id": "a", "input": "Q?", "output": "A.", "judge": "pass", "final": "fail",
                   "reason": "ok", field: text}
            failed = no_grades.failed_md([row], 0)
            mistakes = fix.mistakes_md(None, [row])
            for shown in (failed, mistakes):
                assert not _shows_part(shown, body), (field, shown[-200:])
                assert " (cut)\n" in shown
        row = {"id": "a", "input": "Q?", "output": "A.", "judge": "pass", "final": "fail",
               "reason": text}
        assert not _shows_part(fix.mistakes_md(None, [row]), body)
