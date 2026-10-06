"""Write the files of worked example A, "your own metric", under docs/examples/own-metric/.

One company-style rule: a support reply must state the refund window the policy gives and must
not promise a refund the policy does not allow. Everything here is synthetic. The script
writes a made-up policy, the rule (the `judgekeeper init` template filled in), 60 made-up
customer questions with a reply each, and the human labels. The label of every item is known
by construction, because this script decides which replies break the policy: a reply in the
`correct` slice follows it, and a reply in the `wrong window`, `over-promise` or
`polite but wrong` slice breaks it in that way. Deterministic: rerunning reproduces every file
byte for byte.

    python scripts/make_own_metric_example.py            # writes docs/examples/own-metric/

Then, from that folder, the function judge and the report (see docs/own-metric.md):

    judgekeeper judge anchors.jsonl --callable function_judge:judge --prompt rule.md \\
      --model function_judge.py --runs 3 --out runs/
    judgekeeper validate anchors.jsonl runs/ --out function/
"""

from __future__ import annotations

import csv
import random
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from judgekeeper.table import import_labels
from judgekeeper.templates import template_text

OUT = ROOT / "docs" / "examples" / "own-metric"
SEED = 20261003
RUBRIC_VERSION = "refund-policy-v1"
MARKER = re.compile(r"\[FILL IN: [^\]]+\]")

POLICY = """\
# Refund policy (an illustration)

A made-up policy for a made-up shop. It exists so the example rule has something to check.

- An unopened item can be returned for a full refund within 30 days of delivery.
- Opened electronics can be returned for a full refund within 14 days of delivery.
- A digital download cannot be refunded once the download has started.
- A sale item can be exchanged within 14 days of delivery. It cannot be refunded.
- Shipping charges are never refunded.
"""

# The parts of the rule the user writes, in the order of the template's [FILL IN] markers.
RULE_PARTS = [
    ("the reply states the refund rule the policy gives for the customer's case, and it "
     "promises no refund the policy does not allow"),
    ("The reply names the rule that applies to the customer's item (the 30-day window for an "
     "unopened item, the 14-day window for opened electronics, no refund for a started digital "
     "download, exchange only for a sale item) and its answer follows that rule. A short or "
     "plain reply is fine."),
    ("The reply gives a different window from the policy, leaves the rule out, or promises a "
     "refund, an exception or a shipping refund that the policy does not allow. A friendly tone "
     "does not make a wrong reply pass."),
    ("\"Unopened items can be returned for a full refund within 30 days of delivery, and yours "
     "was delivered 10 days ago, so it qualifies.\"\n"
     "- \"Digital downloads cannot be refunded once the download has started, so we are not "
     "able to refund this purchase.\"\n"
     "- \"Sale items cannot be refunded. They can be exchanged within 14 days of delivery.\""),
    ("\"You can return it for a full refund within 60 days.\" (the policy says 30 days)\n"
     "- \"That is outside the window, but we will make an exception and refund you in full.\" "
     "(an exception the policy does not allow)\n"
     "- \"I am so sorry about this. I have arranged a full refund for you today.\" (a refund "
     "the policy does not allow, and no rule stated)"),
    ("A reply that states the right window and then promises a refund anyway fails: the promise "
     "is what the customer will hold us to. A reply that refuses a refund the policy allows also "
     "fails, because it states the wrong rule for the case. Shipping charges are never refunded, "
     "so a reply that includes them in the refund fails. The reply does not need to quote the "
     "policy word for word."),
]

# category: (products, the detail the customer adds, refund window in days or None)
CATEGORIES = {
    "unopened": (["a pair of running shoes", "a kitchen scale", "a wool blanket", "a desk lamp",
                  "a set of mixing bowls"], "It is still unopened, in its original box.", 30),
    "electronics": (["a pair of wireless headphones", "a tablet", "a smart speaker",
                     "an electric toothbrush"], "I opened it and have used it a few times.", 14),
    "digital": (["an e-book", "a video course", "a photo-editing licence"],
                "I have already downloaded it.", None),
    "sale": (["a jacket from the clearance sale", "a sale-priced backpack",
              "a pair of sale boots"], "It was a sale item.", None),
}
SLICES = ("correct", "wrong window", "over-promise", "polite but wrong")
COUNTS = {"correct": 30, "wrong window": 10, "over-promise": 10, "polite but wrong": 10}


def question(product: str, days: int, detail: str) -> str:
    return (f"Hi, I bought {product} and it was delivered {days} days ago. {detail} "
            f"Can I get a refund?")


def allowed(category: str, days: int) -> bool:
    window = CATEGORIES[category][2]
    return window is not None and days <= window


def correct_reply(category: str, days: int) -> str:
    if category == "unopened":
        rule = "Unopened items can be returned for a full refund within 30 days of delivery."
    elif category == "electronics":
        rule = "Opened electronics can be returned for a full refund within 14 days of delivery."
    elif category == "digital":
        return ("Digital downloads cannot be refunded once the download has started, so we are "
                "not able to refund this purchase. If the file does not work, reply here and "
                "we will help.")
    else:
        later = ("so an exchange is still possible" if days <= 14
                 else "so the exchange window has also passed")
        return (f"Sale items cannot be refunded. They can be exchanged within 14 days of "
                f"delivery; yours was delivered {days} days ago, {later}.")
    if allowed(category, days):
        return (f"Yes. {rule} Yours was delivered {days} days ago, so it qualifies. Send it "
                "back and we will refund the item price; shipping charges are not refunded.")
    return (f"{rule} Yours was delivered {days} days ago, which is outside that window, so we "
            "cannot refund it.")


def wrong_window_reply(category: str, days: int, rng: random.Random) -> tuple[str, str]:
    if category == "unopened":
        wrong = rng.choice([60, 90])
        text = (f"Unopened items can be returned for a full refund within {wrong} days of "
                f"delivery. Yours was delivered {days} days ago, so it qualifies.")
        return text, f"says {wrong} days; the policy says 30"
    if category == "electronics":
        text = (f"Opened electronics can be returned for a full refund within 30 days of "
                f"delivery. Yours was delivered {days} days ago, so it qualifies.")
        return text, "says 30 days; the policy says 14"
    if category == "digital":
        text = ("Digital downloads can be refunded within 7 days of purchase. Reply with your "
                "order number and we will process it.")
        return text, "gives a 7-day window; the policy allows no refund"
    text = (f"Sale items can be exchanged within 30 days of delivery and cannot be refunded. "
            f"Yours was delivered {days} days ago, so an exchange is still possible.")
    return text, "says a 30-day exchange window; the policy says 14"


def over_promise_reply(category: str, days: int, kind: str) -> tuple[str, str]:
    if kind == "shipping":  # an allowed refund, plus the shipping charge
        rule = correct_reply(category, days).split(" Send it back")[0]
        text = (f"{rule} Send it back and we will refund the item price and the shipping "
                "charge too.")
        return text, "promises a shipping refund; shipping is never refunded"
    if category == "digital":
        text = ("Digital downloads cannot be refunded once the download has started, but I "
                "have gone ahead and refunded it anyway.")
        return text, "refunds a started download; the policy allows no refund"
    if category == "sale":
        text = ("Sale items cannot be refunded, only exchanged within 14 days of delivery, "
                "but I will refund it anyway as a goodwill gesture.")
        return text, "refunds a sale item; the policy allows exchange only"
    rule = correct_reply(category, days).split(" Yours was")[0]
    text = (f"{rule} Yours was delivered {days} days ago, which is outside that window, but "
            "we will make an exception this once and refund you in full.")
    return text, "promises an exception; the policy allows none"


def polite_reply(category: str, days: int, variant: int) -> tuple[str, str]:
    window = {"unopened": "a full refund on unopened items within 30 days of delivery",
              "electronics": "a full refund on opened electronics within 14 days of delivery",
              "digital": ("no refund on a digital download once it has started: digital "
                          "downloads cannot be refunded"),
              "sale": ("exchange only for sale items, within 14 days: sale items cannot be "
                       "refunded")}[category]
    openers = ["I am so sorry to hear this, and thank you for your patience.",
               "Thank you for reaching out, and I am sorry the purchase was not what you hoped.",
               "I completely understand, and I apologise for the trouble."]
    closers = [("I would hate to leave you unhappy, so I have arranged a full refund for you "
                "today. You should see it within five working days."),
               ("Your satisfaction matters most to us, so I have processed a full refund. "
                "Please let me know if there is anything else I can do."),
               ("I will make an exception for you and refund the full amount today. Thank you "
                "for being a customer.")]
    text = (f"{openers[variant]} Our policy gives {window}, and I know that {days} days on this "
            f"is frustrating. {closers[variant]}")
    return text, "warm, states the rule, then promises a refund the policy does not allow"


def make_items(rng: random.Random) -> list[dict]:
    items = []

    def pick(category: str, want_allowed: bool | None) -> int:
        window = CATEGORIES[category][2]
        if window is None:
            return rng.randint(2, 40)
        if want_allowed:
            return rng.randint(2, window)
        return rng.randint(window + 3, 90)

    def add(slice_name: str, category: str, days: int, reply: str, note: str) -> None:
        products, detail, _ = CATEGORIES[category]
        items.append({"input": question(rng.choice(products), days, detail), "output": reply,
                      "slice": slice_name, "label": "pass" if slice_name == "correct" else "fail",
                      "notes": note})

    categories = list(CATEGORIES)
    for n in range(COUNTS["correct"]):
        category = categories[n % 4]
        days = pick(category, want_allowed=(n // 4) % 2 == 0)
        why = "follows the policy" if allowed(category, days) else "refuses as the policy says"
        add("correct", category, days, correct_reply(category, days), why)
    for n in range(COUNTS["wrong window"]):
        category = categories[n % 4]
        days = pick(category, want_allowed=True)
        reply, note = wrong_window_reply(category, days, rng)
        add("wrong window", category, days, reply, note)
    for n in range(COUNTS["over-promise"]):
        if n % 5 == 4:
            category = categories[n % 2]  # unopened or electronics, within the window
            days = pick(category, want_allowed=True)
            reply, note = over_promise_reply(category, days, "shipping")
        else:
            category = categories[n % 4]
            days = pick(category, want_allowed=False)
            reply, note = over_promise_reply(category, days, "exception")
        add("over-promise", category, days, reply, note)
    for n in range(COUNTS["polite but wrong"]):
        category = categories[n % 4]
        days = pick(category, want_allowed=False)
        reply, note = polite_reply(category, days, n % 3)
        add("polite but wrong", category, days, reply, note)
    rng.shuffle(items)
    for n, item in enumerate(items, 1):
        item["id"] = f"r{n:02d}"
    return items


def rule_text() -> str:
    parts = iter(RULE_PARTS)
    text = MARKER.sub(lambda m: next(parts), template_text(pairwise=False))
    assert next(parts, None) is None, "a rule part has no marker"
    return text.replace("rubric_version: my-metric-v1", f"rubric_version: {RUBRIC_VERSION}", 1)


def write_csv(path: Path, columns: list[str], rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(columns)
        for row in rows:
            w.writerow([row[c] for c in columns])


def build(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    rng = random.Random(SEED)
    items = make_items(rng)
    # "\n" line endings on every system: the files are committed and compared byte for byte
    (out / "policy.md").write_text(POLICY, encoding="utf-8", newline="\n")
    (out / "rule.md").write_text(rule_text(), encoding="utf-8", newline="\n")
    write_csv(out / "items.csv", ["id", "input", "output", "slice"], items)
    labels = [{**i, "human_label": i["label"]} for i in items]
    write_csv(out / "labels.csv", ["id", "input", "output", "human_label", "notes", "slice"],
              labels)
    import_labels(out / "labels.csv", out / "anchors.jsonl")


def main() -> None:
    build(OUT)
    print(f"wrote {OUT}: policy.md, rule.md, items.csv, labels.csv, anchors.jsonl and its manifest")


if __name__ == "__main__":
    main()
