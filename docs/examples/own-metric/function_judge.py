"""A judge that is a short Python function: the refund rule in rule.md as keyword checks.

Run from this folder (synthetic data; labels by construction; an illustration, not a benchmark):

    judgekeeper judge anchors.jsonl --callable function_judge:judge --prompt rule.md \\
      --model function_judge.py --runs 3 --out runs/
    judgekeeper validate anchors.jsonl runs/ --out function/

The function is deliberately simple. It checks that the reply names the rule for the
customer's case and that it uses none of a few over-promising phrases. It never looks at how
many days ago the item was delivered, so a warm reply that states the right window and then
promises a refund anyway gets past it. The report shows where.
"""

# The policy text the reply must contain for each kind of item.
RULE = {"unopened": "30 days", "electronics": "14 days", "digital": "cannot be refunded",
        "sale": "cannot be refunded"}
# Phrases that promise more than the policy allows.
OVER_PROMISE = ("exception", "anyway", "shipping charge too")


def category(question: str) -> str:
    q = question.lower()
    if "downloaded" in q:
        return "digital"
    if "sale" in q:
        return "sale"
    if "unopened" in q:
        return "unopened"
    return "electronics"


def judge(item: dict) -> tuple[str, str]:
    """item: {"id", "input", "output"}; returns (verdict, reason)."""
    reply = item["output"].lower()
    needed = RULE[category(item["input"])]
    if needed not in reply:
        return "fail", f"does not state the policy's rule for this item ({needed!r} missing)"
    for phrase in OVER_PROMISE:
        if phrase in reply:
            return "fail", f"promises more than the policy allows ({phrase!r})"
    return "pass", "states the policy's rule and promises nothing beyond it"
