"""The words a person reads in `judgekeeper start`: the first block the terminal prints (one
row per thing found, for every tool and every missing value), the keys on the pages, and a
scan of every page's text for the words that must not be there: "Correct", "Wrong", "label"
and "verdict" (the person reads Pass, Fail, mark and decision; the saved files keep their
names)."""

from __future__ import annotations

import re
from datetime import datetime
from html import unescape

import pytest

from judgekeeper import judge_check, new_judge, start, start_fix, start_label, start_page
from judgekeeper.start_review import review_lines
from tests.start_projects import (
    deepeval_project,
    inspect_project,
    promptfoo_project,
    records_project,
    split,
    table_project,
)

BANNED = ("Correct", "Wrong")  # as words a person reads; "correct" in a rule is their text
BANNED_ANY_CASE = ("label", "verdict")


def when(iso: str) -> str:
    return start.when_words(datetime.fromisoformat(iso).astimezone())


# The first block ----------------------------------------------------------------------------

def test_the_first_block_for_promptfoo(tmp_path):
    promptfoo_project(tmp_path, split(30, 20))
    found = start.find_judge(tmp_path)
    assert start.found_lines(found) == [
        "judgekeeper found your LLM-as-a-judge:", "",
        "  Eval tool       promptfoo",
        f"  Results file    results.json (saved {when('2026-10-03T14:12:00Z')})",
        '  What it checks  "Is polite and correct."',
        "  Judge model     openai:gpt-4.1-mini",
        "  Its decisions   50 answers: 30 passed, 20 failed",
    ]


def test_the_first_block_for_deepeval(tmp_path):
    deepeval_project(tmp_path, split(20, 12))
    lines = start.found_lines(start.find_judge(tmp_path))
    assert lines[2] == "  Eval tool       DeepEval"
    assert lines[3].startswith("  Results file    .deepeval/.latest_run_full.json (saved ")
    assert lines[4] == '  What it checks  "Is the actual output factually correct given the input?"'
    assert lines[5] == "  Judge model     gpt-4.1"
    assert lines[6] == "  Its decisions   32 answers: 20 passed, 12 failed"
    assert lines[7] == "  Pass mark       score 0.5 or more"  # DeepEval decides by a threshold


def test_the_first_block_for_inspect(tmp_path):
    inspect_project(tmp_path, split(18, 14))
    lines = start.found_lines(start.find_judge(tmp_path))
    assert lines[2] == "  Eval tool       Inspect AI"
    assert lines[3] == (f"  Results file    logs/2026-10-02_support.json (saved "
                        f"{when('2026-09-30T10:00:00+00:00')})")
    assert lines[4] == '  What it checks  "Grade the answer as C (correct) or I (incorrect)."'
    assert lines[5] == "  Judge model     anthropic/claude-haiku-4-5"
    assert lines[6] == "  Its decisions   32 answers: 18 passed, 14 failed"


def test_the_first_block_for_a_table_says_what_is_missing(tmp_path):
    table_project(tmp_path, split(16, 16), name="data/results.csv")
    lines = start.found_lines(start.find_judge(tmp_path))
    assert lines[2] == "  Eval tool       a table (results.csv)"
    assert lines[3].startswith("  Results file    data/results.csv (saved ")
    assert lines[4] == "  What it checks  not in the file"
    assert lines[5] == "  Judge model     not named in the results (add --judge-model NAME)"
    assert lines[6] == "  Its decisions   32 answers: 16 passed, 16 failed"


def test_the_first_block_for_your_own_code(tmp_path):
    records_project(tmp_path, split(20, 16))
    lines = start.found_lines(start.find_judge(tmp_path))
    assert lines[2] == "  Eval tool       your own code (judgekeeper.record())"
    assert lines[3] == "  Results file    .judgekeeper/records/ (1 file)"
    assert lines[4] == '  What it checks  "Be polite."'
    assert lines[5] == "  Judge model     claude-opus-5"


def test_the_first_block_for_mlflow():
    found = start.Found(root=None, tool="mlflow", results=[], used=["run 1"], metric="tone",
                        pool=start.Pool(), fingerprint={}, judge="tone", signs={},
                        rule="Is calm.", models=["openai:/gpt-4.1"], experiment="support",
                        store="mlflow.db")
    found.results = [type("R", (), {"rel": "mlflow.db"})()]
    lines = start.found_lines(found)
    assert lines[2:4] == ["  Eval tool       MLflow", "  Results file    mlflow.db (experiment support)"]
    assert lines[4:7] == ['  What it checks  "Is calm."', "  Judge model     openai:/gpt-4.1",
                          "  Its decisions   0 answers: 0 passed, 0 failed"]


def test_a_judge_model_you_gave_is_said_as_such(tmp_path):
    promptfoo_project(tmp_path, split(20, 12), model=None)
    lines = start.found_lines(start.find_judge(tmp_path))
    assert "  Judge model     not named in the results (add --judge-model NAME)" in lines
    lines = start.found_lines(start.find_judge(tmp_path, judge_model="gpt-4.1-mini"))
    assert "  Judge model     gpt-4.1-mini (as you told me)" in lines


def test_with_several_judges_the_rule_row_names_the_one_chosen(tmp_path):
    records_project(tmp_path, split(20, 16), name="helpful", pid=1)
    records_project(tmp_path, split(20, 16), name="safe", pid=2, rule="Is safe.")
    lines = start.found_lines(start.find_judge(tmp_path, metric="safe"))
    assert '  What it checks  safe: "Is safe."' in lines


def test_the_rule_is_cut_at_about_seventy_characters(tmp_path):
    rule = "Is polite, correct for the shop's policy, and tells the customer what to do next, always."
    promptfoo_project(tmp_path, split(20, 12), rubric=rule)
    row = next(x for x in start.found_lines(start.find_judge(tmp_path)) if "What it checks" in x)
    shown = row.split("  What it checks  ")[1].strip('"')
    assert shown.endswith("…") and len(shown) <= 71 and rule.startswith(shown[:-1])


def test_older_results_added_are_said_under_the_block(tmp_path):
    runs = tmp_path / "runs"
    deepeval_project(runs, split(6, 4), name="test_run_20261003_090000.json", start=0)
    deepeval_project(runs, split(15, 10), name="test_run_20261002_090000.json", start=10)
    lines = start.found_lines(start.find_judge(tmp_path))
    assert lines[-1] == ("  Fewer than 30 answers in the newest results, so older results from "
                         "the same judge were added: runs/test_run_20261002_090000.json")


def test_the_terminal_says_the_block_then_next_then_the_question(tmp_path, capsys, monkeypatch):
    promptfoo_project(tmp_path, split(30, 20))
    talk = start.Talk(yes=True, flags=(str(tmp_path),))
    found = start.find_judge(tmp_path, talk=talk)
    capsys.readouterr()
    monkeypatch.setattr(start_label, "run_labeling", lambda *a, **k: 0)  # the page is not opened
    start.label_found(talk, found, port=0, open_browser=True)
    out = capsys.readouterr().out
    assert out.index("judgekeeper found") < out.index("Its decisions") < out.index(
        "Your judge made a real decision") < out.index("Next: in your browser") < out.index(
        "This shows how often your judge agrees with you.")
    for gone in ("rough", "reliable", "minutes", "label", "Correct", "Wrong"):
        assert gone not in out, gone


# The keys ---------------------------------------------------------------------------------

def test_the_labeling_page_keys_are_the_arrows_and_the_old_digits():
    page = start_page.label_page(None, None)
    assert '{arrowright: "pass", arrowleft: "fail", "1": "pass", "2": "fail"}' in page
    assert "Fail <kbd>←</kbd>" in page and "Pass <kbd>→</kbd>" in page
    assert "<kbd>1</kbd>" not in page and "<kbd>2</kbd>" not in page  # shown: the arrows only
    assert page.index('id="fail"') < page.index('id="pass"')  # Fail on the left


def test_the_review_page_keys():
    page = start_page.review_page(None, None)
    assert ('{arrowleft: "fail", n: "unsure", arrowright: "pass", "1": "pass", "2": "fail",\n'
            '                "3": "unsure"}') in page
    for shown in ("Fail <kbd>←</kbd>", "Not sure <kbd>N</kbd>", "Pass <kbd>→</kbd>",
                  "Your judge was wrong <kbd>1</kbd>", "I was wrong <kbd>2</kbd>",
                  "The rule is unclear <kbd>3</kbd>"):
        assert shown in page, shown


# No banned word on any page ---------------------------------------------------------------

def visible_text(html: str) -> str:
    """The page's text as a person reads it: no styles, scripts or tags; plus the titles
    and hints (title, aria-label, placeholder) that show on hover or to a screen reader."""
    html = re.sub(r"<(style|script)[^>]*>.*?</\1>", " ", html, flags=re.DOTALL)
    hints = re.findall(r'(?:title|aria-label|placeholder)="([^"]*)"', html)
    text = re.sub(r"<[^>]+>", " ", html)
    return unescape(" ".join([text, *hints]))


def _scan(text: str, where: str) -> None:
    for word in BANNED:
        assert not re.search(rf"\b{word}\b", text), (where, word)
    for word in BANNED_ANY_CASE:
        assert word not in text.lower(), (where, word)


def _result(n_pool_pass, n_pool_fail, n_p, c_p, n_f, c_f, **extra):
    from judgekeeper import weighted

    r = start_label.describe(weighted.corrected(n_pool_pass, n_pool_fail, n_p, c_p, n_f, c_f))
    r.update(made_at="2026-10-05T12:00:00Z", **extra)
    return r


def test_the_templates_hold_no_banned_word():
    for name, page in (("label", start_page.label_page("support bot", "Be kind.")),
                       ("review", start_page.review_page("support bot", "Be kind.")),
                       ("fix", start_page.fix_page("support bot"))):
        _scan(visible_text(page), name)


@pytest.mark.parametrize("counts", [(100, 100, 20, 19, 20, 1), (100, 100, 20, 17, 20, 2),
                                    (100, 100, 25, 17, 25, 1), (100, 100, 10, 9, 10, 1),
                                    (900, 100, 25, 24, 25, 1)])
def test_the_result_page_holds_no_banned_word(counts):
    check = {"answers": 57, "error": 5, "unreadable": 2, "reason_says_opposite": 1,
             "tool": "promptfoo", "tool_counted_as": "fail"}
    review = {"made_at": "x", "looked_again": 10, "disagreements": 5, "agreed": 5,
              "changed_disagreements": 2, "changed_agreed": 0, "not_sure": 0,
              "second_look": {"tpr": 0.9, "tnr": 0.8}, "choices": {"judge_wrong": 3,
                                                                   "slipped": 1,
                                                                   "rule_unclear": 1},
              "chosen": 5, "done": True, "files": ["judge-mistakes.csv"], "to_fix": 4}
    fix = {"counts": {"passed_but_fail": 6, "failed_but_pass": 2, "unclear": 0}, "used": 35,
           "aside": 15, "tests": [{"change": "pass mark 0.5 to 0.7",
                                   "sentence": start_fix.test_sentence(15, 6, 0)}]}
    r = _result(*counts, judge_check=check, review=review, fix=fix, left=7,
                judge={"tool": "promptfoo", "metric": "llm-rubric", "rule": "Be kind.",
                       "results_files": ["results.json"], "results_date": "2026-10-05 05:30"})
    for back in (None, "/?token=t"):
        _scan(visible_text(start_label.result_html(r, back)), f"result {counts} {back}")
    _scan("\n".join(start_label.result_lines(r)), f"terminal result {counts}")


def test_the_lines_the_server_sends_hold_no_banned_word():
    texts = [*start_label.VERDICTS.values(), *(t for _, t, _ in new_judge.QUICK_STATUS),
             start_label.status_line({"check": "rough", "wide": {"tpr": 0.4, "tnr": None}}),
             start_fix.test_sentence(15, 6, 0), start_fix.test_sentence(15, 0, 6),
             start_fix.test_sentence(15, 2, 0), judge_check.LIST_LINE, start_label.ALL_LABELED,
             *review_lines({"looked_again": 10, "disagreements": 5, "agreed": 5,
                            "changed_disagreements": 2, "changed_agreed": 3,
                            "second_look": {"tpr": 0.9, "tnr": None},
                            "choices": {"judge_wrong": 3, "slipped": 1, "rule_unclear": 1},
                            "chosen": 3, "done": False}),
             *judge_check.page_lines({"answers": 57, "error": 5, "unreadable": 2, "empty": 1,
                                      "nothing_checked": 4, "empty_answer_passed": 3,
                                      "reason_says_opposite": 2, "same_decision": "pass",
                                      "tool": "promptfoo", "tool_counted_as": "fail"})]
    _scan("\n".join(texts), "server lines")
