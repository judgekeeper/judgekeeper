"""mistakes.md always holds the rule the marks were made with, besides the rule now, so
"mistakes.md keeps a copy" stays true after check moves the marks to a new rule."""

from __future__ import annotations

from judgekeeper import fix

ROWS = [{"id": "a", "input": "Q?", "output": "A.", "judge": "pass", "final": "fail",
         "reason": "ok"}]


def _section(text: str, heading: str) -> str:
    return text.split(f"## {heading}\n", 1)[1].split("\n## ", 1)[0]


def test_a_new_rule_now_keeps_the_rule_marked_with():
    text = fix.mistakes_md("Pass short answers.", ROWS, marked="Pass kind answers.")
    assert "<<<RULE\nPass short answers.\nRULE>>>" in _section(
        text, "Your LLM-as-a-judge's rule now")
    assert "<<<MARKED RULE\nPass kind answers.\nMARKED RULE>>>" in _section(
        text, "The rule you marked with")
    assert text.index("rule now") < text.index("The rule you marked with")


def test_the_same_rule_is_not_written_twice():
    text = fix.mistakes_md("Pass kind answers.", ROWS, marked="Pass kind answers.")
    assert text.count("Pass kind answers.") == 1
    assert _section(text, "The rule you marked with").strip() == "The same as the rule now."


def test_without_a_rule_there_is_no_section():
    assert "marked with" not in fix.mistakes_md(None, ROWS)


def test_the_rule_marked_with_is_kept_when_check_takes_a_new_rule():
    from judgekeeper.check import _marked_rule_kept

    data = {"rule": "Pass kind answers."}
    _marked_rule_kept(data)
    data["rule"] = "Pass short answers."
    _marked_rule_kept(data)
    assert data["marked_rule"] == "Pass kind answers."
    assert fix.marked_rule(data) == "Pass kind answers."
    assert fix.marked_rule({"rule": "R"}) == "R"
    assert fix.marked_rule({"rule": "R", "one_rule": False}) is None
