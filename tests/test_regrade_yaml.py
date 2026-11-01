"""promptfoo: `fix` writes .judgekeeper/fix/regrade.yaml, a config that grades the marked answers
again, and says the three steps to use it; `check` points at the same file when the new results
hold too few of the marked answers, and says "Better" when a group's whole range is a clear rise.
No test calls an API: the file is only text.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
import yaml

from judgekeeper import check, fix
from judgekeeper.cli import main
from tests.start_projects import promptfoo_data
from tests.test_fix import RULE, project, run
from tests.test_only_reads import FIRST
from tests.test_only_reads import project as any_project
from tests.test_only_reads import run as run_any

TRICKY = 'Say "yes" only if: the answer is polite.\nSecond line, with a \\ and \'quotes\' — é 😀 {{question}}'
GRADER = {"provider": "openai", "model": "openai:gpt-4.1-mini"}


@pytest.fixture
def here(tmp_path, monkeypatch):
    root = tmp_path / "support-bot"
    root.mkdir()
    monkeypatch.chdir(root)
    return root


def _flat(out: str) -> str:
    return " ".join(out.split())


def _written(ws) -> dict:
    return yaml.safe_load((ws.dir / "fix" / "regrade.yaml").read_text(encoding="utf-8"))


# fix writes the file ----------------------------------------------------------------------------

def test_fix_writes_a_ready_regrade_file_and_says_the_three_steps(here, capsys):
    ws = project(here)
    code, out = run(capsys)
    assert code == 0, out
    path = ws.dir / "fix" / "regrade.yaml"
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    line = next(n for n, x in enumerate(lines, 1) if x.lstrip().startswith("value:"))
    assert _written(ws) == {
        "prompts": ["{{answer}}"], "providers": ["echo"], "tests": "file://marked-answers.csv",
        "defaultTest": {"options": {"provider": {"id": "openai:gpt-4.1-mini",
                                                 "config": {"temperature": 0}}},
                        "assert": [{"type": "llm-rubric", "value": RULE}]}}
    flat = _flat(out)
    assert (f"1. Change the rule in .judgekeeper/fix/regrade.yaml (line {line}). "
            "2. Run: `npx promptfoo eval -c .judgekeeper/fix/regrade.yaml -o "
            ".judgekeeper/fix/new.json` "
            "3. Then: `judgekeeper fix .judgekeeper/fix/new.json`") in flat
    assert "Next: follow the three steps above." in flat
    assert "judgekeeper's docs/eval-tools.md shows the whole config" not in flat
    assert (ws.dir / "fix" / "marked-answers.csv").is_file()


def test_a_rule_with_quotes_colons_and_new_lines_survives(tmp_path):
    ws = SimpleNamespace(root=tmp_path)
    data = {"fingerprint": GRADER, "rule": TRICKY, "metric": "llm-rubric", "results_files": []}
    text = fix._regrade_yaml(ws, data)
    assert yaml.safe_load(text)["defaultTest"]["assert"][0]["value"] == TRICKY
    assert len(text.splitlines()) == 9  # the rule is one line, so "line N" is exact
    for odd in (" ", "\x85", " ", "﻿"):
        again = fix._regrade_yaml(ws, {**data, "rule": f"a{odd}b"})
        assert yaml.safe_load(again)["defaultTest"]["assert"][0]["value"] == f"a{odd}b"
        assert len(again.splitlines()) == 9


def test_a_named_metric_and_its_type_are_kept(here, capsys):
    ws = project(here)
    data = promptfoo_data([True] * 25 + [False] * 25, rubric=RULE, metric="correctness")
    for row in data["results"]["results"]:
        row["testCase"]["options"] = {"provider": {"id": "openai:gpt-4.1-mini"}}
        row["gradingResult"]["componentResults"][0]["assertion"]["type"] = "g-eval"
    (here / "named.json").write_text(json.dumps(data), encoding="utf-8")
    kind = fix._promptfoo_assertion(ws, {"metric": "correctness",
                                         "results_files": ["named.json"]})
    assert kind == ("g-eval", "correctness")
    text = fix._regrade_yaml(ws, {"fingerprint": GRADER, "rule": RULE, "metric": "correctness",
                                  "results_files": ["named.json"]})
    assert yaml.safe_load(text)["defaultTest"]["assert"] == [
        {"type": "g-eval", "metric": "correctness", "value": RULE}]


@pytest.mark.parametrize("data", [
    {"fingerprint": {"provider": "file", "model": "your own provider (x)"}},
    {"fingerprint": {"provider": None, "model": "gpt-4.1-mini"}},
    {"fingerprint": GRADER, "rule": ""},
    {"fingerprint": GRADER, "one_rule": False},
    {"fingerprint": GRADER, "metric": "something-else"},
])
def test_no_file_when_the_grader_or_rule_cannot_be_read(tmp_path, data):
    base = {"rule": RULE, "metric": "llm-rubric", "results_files": []}
    assert fix._regrade_yaml(SimpleNamespace(root=tmp_path), {**base, **data}) is None


def test_the_old_text_stays_when_there_is_no_file(here, capsys, monkeypatch):
    ws = project(here)
    monkeypatch.setattr(fix, "_regrade_yaml", lambda *a: None)
    code, out = run(capsys)
    assert code == 0 and not (ws.dir / "fix" / "regrade.yaml").exists()
    assert fix.regrade_line("promptfoo") in _flat(out)
    assert "Next: change your LLM-as-a-judge's rule in your eval tool" in _flat(out)


def test_a_file_the_person_changed_is_not_written_over(here, capsys):
    ws = project(here)
    run(capsys)
    path = ws.dir / "fix" / "regrade.yaml"
    path.write_text(path.read_text(encoding="utf-8").replace(RULE, "My new rule."),
                    encoding="utf-8")
    run(capsys)
    assert _written(ws)["defaultTest"]["assert"][0]["value"] == "My new rule."


def test_a_rule_variable_the_csv_lacks_is_said(here, capsys):
    ws = project(here, rule="Be polite about {{product}} and {{ context }}. See {{question}}.")
    code, out = run(capsys)
    flat = _flat(out)
    assert code == 0, out
    assert "Your rule uses {{product}}; marked-answers.csv has only question and answer." in flat
    assert "Your rule uses {{context}}; marked-answers.csv has only question and answer." in flat
    assert "{{question}}; marked-answers.csv" not in flat
    assert (ws.dir / "fix" / "regrade.yaml").is_file()


def test_a_link_in_place_of_the_file_is_not_followed(here, capsys, tmp_path):
    ws = project(here)
    (ws.dir / "fix").mkdir(exist_ok=True)
    target = tmp_path / "elsewhere.yaml"
    (ws.dir / "fix" / "regrade.yaml").symlink_to(target)
    assert fix.promptfoo_regrade(ws) is None  # nothing written through the link
    assert not target.exists()


# fix: the two sides --------------------------------------------------------------------------

def test_fix_shows_the_two_sides_for_the_old_and_the_new_rule(here, capsys):
    from tests.test_fix import regraded

    project(here)
    run(capsys)
    _, out = run(capsys, regraded(here).name)
    lines = out.splitlines()
    at = lines.index("  Old rule:")
    assert lines[at + 1].startswith("    When you say Pass: agrees on ")
    assert lines[at + 2].startswith("    When you say Fail: agrees on ")
    assert lines[at + 3] == "  New rule:"
    assert lines[at + 4].startswith("    When you say Pass: agrees on ")
    assert lines[at + 5].startswith("    When you say Fail: agrees on ")
    assert "agreed with you on" not in out
    assert "With the new rule," in out  # the fixed/broke line stays


# check: too few marked answers ----------------------------------------------------------------

def _few(root, rows: int = 10) -> str:
    data = json.loads((root / FIRST["promptfoo"]).read_text(encoding="utf-8"))
    data["results"]["results"] = data["results"]["results"][:rows]
    (root / "few.json").write_text(json.dumps(data), encoding="utf-8")
    return "few.json"


def test_check_with_too_few_of_the_same_answers_leads_with_the_steps(
        here, capsys, monkeypatch):
    ws = any_project("promptfoo", here, monkeypatch)
    capsys.readouterr()
    assert not (ws.dir / "fix" / "regrade.yaml").exists()
    code, out = run_any(capsys, "check", _few(here))
    flat = _flat(out)
    assert code == 3, out
    path = ws.dir / "fix" / "regrade.yaml"
    line = next(n for n, x in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
                if x.lstrip().startswith("provider:"))
    assert "Result: can't tell yet." in flat
    assert "wrote new answers" not in flat  # the 10 are answers it marked, not new ones
    assert ("can't tell yet. Your new results hold 4 of the answers you marked Pass and 6 you "
            "marked Fail; a re-check needs 15 of each. Grade the answers you marked: "
            f"1. Change the grader in .judgekeeper/fix/regrade.yaml (line {line}). "
            "2. Run: `npx promptfoo eval -c .judgekeeper/fix/regrade.yaml -o "
            ".judgekeeper/fix/new.json` "
            "3. Then: `judgekeeper check .judgekeeper/fix/new.json`") in flat
    assert yaml.safe_load(path.read_text(encoding="utf-8"))["providers"] == ["echo"]


def test_check_with_too_few_of_the_same_answers_keeps_the_old_next_for_other_tools(
        here, capsys, monkeypatch):
    from tests.test_new_results import _jsonl, judge

    any_project("jsonl", here, monkeypatch)
    capsys.readouterr()
    code, out = run_any(capsys, "check", _jsonl(here / "few.jsonl",
                                                [(i, judge(i)) for i in range(10)]).name)
    flat = _flat(out)
    assert code == 3, out
    assert "wrote new answers" not in flat
    assert ("Grade the answers you marked: Next: run `judgekeeper fix` to write the answers you "
            "marked to "
            ".judgekeeper/fix/marked-answers.csv, grade every one again") in flat
    assert not (here / ".judgekeeper" / "fix" / "regrade.yaml").exists()


def test_the_steps_exit_with_3_through_main(here, capsys, monkeypatch):
    any_project("promptfoo", here, monkeypatch)
    capsys.readouterr()
    assert main(["check", _few(here)]) == 3


# check: "Better" ------------------------------------------------------------------------------

def _groups(old_wrong: int, new_wrong: int, n: int = 30, new_wrong_pass: int | None = None):
    """Both groups of `n` marks: the old judge got `old_wrong` of each group wrong, the new one
    `new_wrong` (`new_wrong_pass` on the Pass side), always the first ones of the group."""
    marked = {f"p{i}": "pass" for i in range(n)} | {f"f{i}": "fail" for i in range(n)}
    old, new = {}, {}
    for prefix, mark, other in (("p", "pass", "fail"), ("f", "fail", "pass")):
        again = new_wrong_pass if prefix == "p" and new_wrong_pass is not None else new_wrong
        for k in range(n):
            old[f"{prefix}{k}"] = other if k < old_wrong else mark
            new[f"{prefix}{k}"] = other if k < again else mark
    return check.groups(marked, old, new)


def test_a_clear_rise_in_a_group_is_better(here):
    g = _groups(old_wrong=20, new_wrong=0)
    assert g["passed"]["verdict"] == g["failed"]["verdict"] == "better"
    assert not g["passed"]["exit_worse"]
    assert check.outcome(g) == "no_drop"  # the one-line result is not a new kind
    assert [x.split()[-1] for x in check.table_lines(g)[1:]] == ["Better", "Better"]
    assert check.paired_lines(g["passed"])[0] == (
        "Better: your new LLM-as-a-judge agrees with you more on this side.")


def test_a_small_rise_is_still_no_big_drop(here):
    g = _groups(old_wrong=6, new_wrong=4)
    assert g["passed"]["verdict"] == "no_drop"
    assert check.table_lines(g)[1].endswith("No big drop")


def test_worse_still_wins_over_better(here):
    g = _groups(old_wrong=20, new_wrong=0, new_wrong_pass=30)  # Fail side rises, Pass side falls
    assert g["failed"]["verdict"] == "better" and g["passed"]["verdict"] == "worse"
    assert check.outcome(g) == "worse"


# check: none of the marked answers are in the new results -------------------------------------

def _none_in(root) -> str:
    data = json.loads((root / FIRST["promptfoo"]).read_text(encoding="utf-8"))
    for row in data["results"]["results"]:
        row["response"]["output"] += " A new answer."
    (root / "new.json").write_text(json.dumps(data), encoding="utf-8")
    return "new.json"


def test_check_with_none_of_the_answers_found_leads_with_the_steps(here, capsys, monkeypatch):
    ws = any_project("promptfoo", here, monkeypatch)
    capsys.readouterr()
    code, out = run_any(capsys, "check", _none_in(here))
    flat = _flat(out)
    assert code == 3, out
    line = next(n for n, x in enumerate(
        (ws.dir / "fix" / "regrade.yaml").read_text(encoding="utf-8").splitlines(), 1)
        if x.lstrip().startswith("provider:"))
    assert "None of your" in flat and "is in your new results." in flat
    assert ("Your eval wrote new answers, so there's nothing to compare. Grade the answers you "
            "marked instead: "
            f"1. Change the grader in .judgekeeper/fix/regrade.yaml (line {line}). "
            "2. Run: `npx promptfoo eval -c .judgekeeper/fix/regrade.yaml -o "
            ".judgekeeper/fix/new.json` "
            "3. Then: `judgekeeper check .judgekeeper/fix/new.json` "
            "Next: follow the three steps above; or start over on your new answers with "
            "`judgekeeper --new`.") in flat


def test_check_with_none_of_the_answers_found_keeps_the_old_next_for_other_tools(
        here, capsys, monkeypatch):
    from tests.test_new_results import _jsonl

    any_project("jsonl", here, monkeypatch)
    capsys.readouterr()
    rows = _jsonl(here / "new.jsonl", [(0, True)])
    rows.write_text(rows.read_text(encoding="utf-8").replace("Answer", "Another"),
                    encoding="utf-8")
    code, out = run_any(capsys, "check", rows.name)
    flat = _flat(out)
    assert code == 3, out
    assert ("Your eval wrote new answers, so there's nothing to compare. Grade the answers you "
            "marked instead: Next: run `judgekeeper fix` to write the answers you marked") in flat
    assert "or start over on your new answers with `judgekeeper --new`." in flat


# the grader's config ---------------------------------------------------------------------------

SECRET = "test-value-not-a-real-key-0000"
BEARER = "Bearer abcdefghijklmnopqrstuvwxyz123456"


def _grader_config(root, config: dict) -> None:
    """The grader of every answer in results.json given `config`, as promptfoo saves it."""
    path = root / "results.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    for row in data["results"]["results"]:
        row["testCase"]["options"]["provider"]["config"] = config
    path.write_text(json.dumps(data), encoding="utf-8")


def test_the_grader_config_is_kept_without_any_key(here, capsys):
    from tests.test_fix import regraded

    ws = project(here)
    _grader_config(here, {"temperature": 0, "apiBaseUrl": "http://127.0.0.1:9590/v1",
                          "max_tokens": 300, "apiKey": SECRET, "access_token": SECRET,
                          "headers": {"X-Team": "support", "Authorization": BEARER}})
    code, out = run(capsys)
    assert code == 0, out
    text = (ws.dir / "fix" / "regrade.yaml").read_text(encoding="utf-8")
    provider = yaml.safe_load(text)["defaultTest"]["options"]["provider"]
    assert provider == {"id": "openai:gpt-4.1-mini",
                        "config": {"temperature": 0, "apiBaseUrl": "http://127.0.0.1:9590/v1",
                                   "max_tokens": 300, "headers": {"X-Team": "support"}}}
    assert SECRET not in text and "abcdefghijklmnop" not in text
    for name in ("apiKey", "access_token", "headers.Authorization"):
        assert (f"    # {name} left out: judgekeeper never writes keys to files. Set it the "
                "way your own config does.\n") in text
    lines = text.splitlines()
    comments = [n for n, x in enumerate(lines) if x.lstrip().startswith("#")]
    assert lines[max(comments) + 1].lstrip().startswith("provider:")  # right above it
    value = next(n for n, x in enumerate(lines, 1) if x.lstrip().startswith("value:"))
    assert f"Change the rule in .judgekeeper/fix/regrade.yaml (line {value})." in _flat(out)
    # the person follows the steps: promptfoo saves the grader regrade.yaml names
    new = regraded(here)
    data = json.loads(new.read_text(encoding="utf-8"))
    for row in data["results"]["results"]:
        row["testCase"]["options"]["provider"] = provider
    new.write_text(json.dumps(data), encoding="utf-8")
    code = main(["check", new.name])
    flat = _flat("".join(capsys.readouterr()))
    assert "Your LLM-as-a-judge changed: rule changed." in flat, flat
    assert "temperature" not in flat


def test_a_grader_with_no_config_is_its_name_alone(tmp_path):
    ws = SimpleNamespace(root=tmp_path)
    data = {"fingerprint": GRADER, "rule": RULE, "metric": "llm-rubric", "results_files": []}
    text = fix._regrade_yaml(ws, data)
    assert yaml.safe_load(text)["defaultTest"]["options"] == {"provider": "openai:gpt-4.1-mini"}
    assert "#" not in text


def test_the_docs_say_when_no_regrade_file_is_written():
    from pathlib import Path

    docs = " ".join((Path(__file__).parent.parent / "docs" / "eval-tools.md")
                    .read_text(encoding="utf-8").split())
    assert ("`judgekeeper fix` writes `.judgekeeper/fix/regrade.yaml` for you when your grader "
            "is a named provider") in docs
    assert ("For a `file://` or `exec:` grader, or promptfoo's default grader, it writes no "
            "file and prints the steps instead.") in docs


def test_any_field_that_may_hold_a_key_is_left_out():
    config = {"temperature": 0, "maxTokens": 512, "max_tokens": 300, "apiBaseUrl": "http://x/v1",
              "apikey": SECRET, "secretkey": SECRET, "sessionToken": SECRET,
              "credentials": {"type": "service_account", "client_email": "a@b.c"},
              "Authorization": "x", "bearer": "x", "cookie": "x", "passwd": "x",
              "useAuth": True, "deployment": "support-4o",
              "headers": [{"name": "x-api-key", "value": "abc"}],
              "extra": [{"privateKey": SECRET, "region": "eu"}, "plain", BEARER],
              "nested": {"deep": [{"items": [{"api_KEY_value": SECRET, "n": 1}]}]}}
    kept, left = fix._without_keys(config)
    assert kept == {"temperature": 0, "maxTokens": 512, "max_tokens": 300,
                    "apiBaseUrl": "http://x/v1", "useAuth": True, "deployment": "support-4o",
                    "extra": [{"region": "eu"}, "plain"],
                    "nested": {"deep": [{"items": [{"n": 1}]}]}}
    assert left == ["apikey", "secretkey", "sessionToken", "credentials", "Authorization",
                    "bearer", "cookie", "passwd", "headers", "extra[0].privateKey", "extra[2]",
                    "nested.deep[0].items[0].api_KEY_value"]
    assert SECRET not in json.dumps(kept) and "abc" not in json.dumps(kept)
