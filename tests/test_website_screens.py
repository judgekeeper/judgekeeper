"""The terminal screens on the website are what judgekeeper prints.

One example project, as the screens show it: promptfoo, 40 answers graded by
openai:gpt-4.1-mini (23 Pass, 17 Fail), the rule on line 14 of promptfooconfig.yaml. The
person marks 12 answers, then 30; `judgekeeper fix` keeps some aside, a new rule is tested on
them, and the model changes to gpt-4.1-nano for `judgekeeper check`. The two steps that ask the
judge use the fake promptfoo of the other tests (no AI call), and the person answers "y" at
the terminal. Each screen on the Home page must be the
output line for line, after the "$ judgekeeper ..." line the site adds.

The Measure step's report.html and result.json are committed in docs/examples/site-example/,
so the figures on the screens come from a report (Home's terminal links it). To write them again:

    TZ=UTC JK_WRITE_SITE_EXAMPLE=1 pytest tests/test_website_screens.py
"""

from __future__ import annotations

import html
import json
import os
import re
import shutil
from pathlib import Path

import pytest

from judgekeeper import again, fix, keys, start
from judgekeeper.cli import main
from judgekeeper.start_label import StartSession, Workspace
from tests.start_projects import project_promptfoo, promptfoo_data, split
from tests.test_again_run import FakePromptfoo
from tests.website_pages import WEBSITE, as_shown, parse

RULE = "The answer solves the customer's problem and is polite."
NEW_RULE = ("The answer fully solves the customer's problem, gives a clear next step and is "
            "polite.")
CONFIG = f"""description: support bot
prompts:
  - "Answer the customer: {{{{question}}}}"
providers:
  - openai:gpt-4.1
defaultTest:
  options:
    provider:
      id: openai:gpt-4.1-mini
      config:
        temperature: 0
  assert:
    - type: llm-rubric
      value: "{RULE}"
tests: file://tests.yaml
"""
# The example's 40 answers: a homeware shop's support bot, the shop of Home's demo. Each is
# (question, answer, the judge's reason when it passes it, its reason when it fails it). The
# judge passes 0-22 and fails 23-39; the person's marks go in question order (_mark), so:
# 0-3, 6-8 and 15-22 are good answers; 4, 5 and 9-14 are wrong ones the judge passes; 23-26 and
# 29-32 are right but plain ones it fails; 27, 28 and 33-39 are bad ones it fails.
SHOP = [
    ("How long do I have to return something?",
     ("You have 30 days from delivery. Start a return from your order page and we'll email you a "
     "free label."),
     "Gives the 30-day window and the next step, politely.",
     "Doesn't say when the refund arrives."),
    ("Do you ship to Canada?",
     "Yes. Delivery takes 5 to 8 working days, and duties are included at checkout.",
     "Answers clearly, with the delivery time.", "Doesn't mention tracking."),
    ("Can I change my delivery address?",
     "Yes, until the order ships. Open Orders, choose the order and click Change address.",
     "Clear steps, and polite.", "Doesn't say what to do once it has shipped."),
    ("Is there a student discount?",
     "Yes, 10% off with a valid student email. Sign up on our Students page to get your code.",
     "Correct, and gives the next step.", "Doesn't say if it works on sale items."),
    ("Can I return a lamp after 60 days?",
     "Of course! We accept returns at any time, no questions asked.",
     "Friendly, and solves the customer's problem.", "Too casual for a returns question."),
    ("My mug arrived chipped. What now?",
     "Sorry about that! Just throw it away and order a new one. It should arrive fine this time.",
     "Says sorry and gives a clear next step.", "Doesn't offer a refund."),
    ("Where is my order?",
     ("Sorry for the wait. Your tracking link is in your shipping email, and most orders arrive "
     "within 3 working days."),
     "Says sorry and where to find tracking.", "Doesn't look up the order."),
    ("Can I pay with PayPal?",
     "Yes, PayPal is one of the options at checkout, along with cards and Apple Pay.",
     "Answers directly.", "Doesn't thank the customer."),
    ("Do you sell gift cards?",
     "Yes, from $10 to $200. They're emailed right away and never expire.",
     "Clear and complete.", "Doesn't say how to buy one."),
    ("Is the oak table solid wood?",
     "Yes, every table we sell is made of solid oak.",
     "Answers the question politely.", "Too short."),
    ("Is shipping free?",
     "Shipping is always free on every order, wherever you are!",
     "Positive, and answers the question.", "Doesn't give delivery times."),
    ("How do I use my discount code?",
     "Discount codes are applied for you, so there's nothing to do.",
     "Polite, and solves the problem.", "Doesn't say where to see the discount."),
    ("Can I cancel my order?",
     "Yes, you can cancel at any time, even after delivery.",
     "Clear and helpful.", "Doesn't say how to cancel."),
    ("Is the rug washable?",
     "Yes, all our rugs can go in the washing machine on a hot wash.",
     "Answers the question, and is friendly.", "Doesn't give care tips."),
    ("Do you price match?",
     "Yes! Send us any lower price and we'll beat it by 20%.",
     "Polite, and offers a solution.", "Doesn't say how to send the price."),
    ("What sizes does the linen duvet cover come in?",
     "Single, double, king and super king. The sizes are on the product page under Details.",
     "Lists the sizes and where to see them.", "Doesn't give the measurements."),
    ("Can I order a fabric sample?",
     "Yes, up to 5 free samples per order. Add them from the product page.",
     "Clear, with the next step.", "Doesn't say how long samples take."),
    ("How do I track a return?",
     "We email you once it arrives. Refunds reach your card within 5 working days.",
     "Says what happens and when.", "Doesn't give a tracking link."),
    ("Do you have a shop I can visit?",
     "We're online only for now, but you can drop returns at any post office.",
     "Honest, and offers what it can.", "Doesn't say sorry."),
    ("Is the candle vegan?",
     "Yes, our candles are made with soy wax and contain no animal products.",
     "Correct and clear.", "Doesn't name the scent."),
    ("Can I add a gift note?",
     "Yes. At checkout, tick This is a gift and type your note. Prices won't show on the slip.",
     "Clear steps.", "Doesn't say if gift wrap is offered."),
    ("How do I clean the copper kettle?",
     "Wipe it with a soft cloth and a little lemon juice. Avoid scourers, which scratch copper.",
     "Helpful care advice.", "Doesn't mention descaling."),
    ("Do you deliver on Saturdays?",
     "Yes, in most areas. Choose Saturday delivery at checkout for $6.",
     "Answers with the price.", "Doesn't say which areas."),
    ("Do you ship to Australia?",
     "Not yet, sorry. We ship to the US, Canada and the UK.",
     "Honest and polite.", "Doesn't offer another way to help."),
    ("Is the vase dishwasher safe?",
     "No, hand wash only.", "Correct.", "Too short, and not friendly."),
    ("Can I return a sale item?",
     "Yes, within 30 days, the same as full-price items.",
     "Correct.", "Doesn't thank the customer."),
    ("Can I call you?",
     "We don't have a phone line, but the chat on our site replies within an hour.",
     "Offers another way.", "Doesn't answer the question asked."),
    ("My lamp arrived broken. What now?",
     "Please check our website for more information.",
     "Polite.", "Doesn't help: no next step."),
    ("Where is my refund?",
     "Refunds are handled by your bank, not us.",
     "Answers the question.", "Blames the bank and gives no help."),
    ("Are your mugs microwave safe?",
     "Yes.", "Correct.", "One word: not polite enough."),
    ("Do you restock sold-out items?",
     "Usually within 4 weeks. Click Notify me on the product page.",
     "Gives a time and a next step.", "Doesn't say sorry it's sold out."),
    ("Can I collect my order?",
     "No, we only deliver.", "Correct.", "Doesn't solve the customer's problem."),
    ("Why was I charged twice?",
     "The second charge is a hold from your bank. It drops off within 3 days.",
     "Explains the charge.", "Doesn't say sorry."),
    ("The rug looks different from the photo.",
     "Colours can vary. That's just how it is.",
     "Explains why.", "Rude, and doesn't offer a return."),
    ("I got the wrong item.",
     "Are you sure you ordered the right one?",
     "Asks a question to help.", "Doubts the customer."),
    ("Can I talk to someone?",
     "I can only answer questions about orders.",
     "Honest.", "Doesn't help."),
    ("My parcel says delivered but it isn't here.",
     "Parcels are your responsibility once delivered.",
     "Answers the question.", "Not polite, and no help."),
    ("Do you have this table in walnut?",
     "lol no", "Answers.", "Not polite."),
    ("How do I stop your emails?",
     "You can't.", "Answers.", "Wrong, and not polite."),
    ("My discount code doesn't work.",
     "Codes always work. Try again.",
     "Short.", "Doesn't solve the problem."),
]
SEED = 7  # the marks fix keeps aside
MEASURE_STEP = "measure-step"  # where the run keeps the Measure step's report
SITE_EXAMPLE = Path(__file__).resolve().parent.parent / "docs" / "examples" / "site-example"
COMMANDS = {"find": "judgekeeper", "mark": "judgekeeper", "measure": "judgekeeper",
            "fix": "judgekeeper fix", "fix_test": "judgekeeper fix", "check": "judgekeeper check"}


def _results(root, verdicts, model="openai:gpt-4.1-mini", outputs=None) -> None:
    """results.json with the shop's questions and answers, and the judge's reason for the
    grade it gave."""
    data = promptfoo_data(verdicts, model=model, rubric=RULE, outputs=outputs)
    data["metadata"]["promptfooVersion"] = "0.124.1"
    for i, row in enumerate(data["results"]["results"]):
        q, a, why_pass, why_fail = SHOP[i]
        row["vars"]["question"] = q  # the same dict as the test case's vars
        if outputs is None:
            row["response"]["output"] = a
        row["gradingResult"]["componentResults"][0]["reason"] = (
            why_pass if verdicts[i] else why_fail)
    (root / "results.json").write_text(json.dumps(data), encoding="utf-8")


def _mark(root, plan, person: dict) -> None:
    """plan: (the judge's grade, the person's mark, how many) of answers not marked yet, taken
    in question order, so each answer's words fit the marks it gets (see SHOP)."""
    ws = Workspace(root)
    session = StartSession(ws)
    rows = [json.loads(line) for line in ws.pool.read_text(encoding="utf-8").splitlines()]
    number = {row["id"]: [q for q, *_ in SHOP].index(row["input"]["question"]) for row in rows}
    items = sorted(session.items, key=lambda item: number[item["id"]])
    for grade, mark, count in plan:
        for item in items:
            if count and session.groups[item["id"]] == grade and item["id"] not in person:
                session.update({"id": item["id"], "label": mark, "seconds": 5})
                person[item["id"]] = mark
                count -= 1


def _question_marks(root, person: dict) -> dict[str, bool]:
    """The person's marks by question text, as promptfoo sees the answers."""
    ws = Workspace(root)
    rows = [json.loads(line) for line in ws.pool.read_text(encoding="utf-8").splitlines()]
    texts = {row["id"]: json.dumps(row["input"]) for row in rows}
    return {q: person[item] == "pass" for item, text in texts.items()
            for q, *_ in SHOP if item in person and json.dumps(q) in text}


def real_screens(root, capsys, monkeypatch) -> dict[str, list[str]]:
    """Run the example project through the five steps; what each run printed."""
    project_promptfoo(root)
    for name in keys.all_names():
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "x" * 30)
    monkeypatch.setattr(again, "which", lambda name: None)
    monkeypatch.setattr(fix.secrets, "randbelow", lambda n: SEED)
    monkeypatch.setattr(start, "_interactive", lambda: True)

    def answer_yes(prompt=""):
        print(prompt + "y")  # what the terminal shows once the person typed y
        return "y"

    monkeypatch.setattr("builtins.input", answer_yes)
    (root / "promptfooconfig.yaml").write_text(CONFIG, encoding="utf-8")
    _results(root, split(23, 17))
    out, person = {}, {}

    def run(name, *argv):
        main(list(argv))
        printed, err = capsys.readouterr()
        out[name] = (printed + err).rstrip("\n").splitlines()

    run("find")
    _mark(root, [("pass", "pass", 4), ("fail", "pass", 4), ("pass", "fail", 2),
                 ("fail", "fail", 2)], person)
    run("mark")
    _mark(root, [("pass", "pass", 3), ("fail", "pass", 4), ("pass", "fail", 6),
                 ("fail", "fail", 5)], person)
    run("measure")
    # Home's Measure screen links its report: keep that step's report as it was then
    kept = root / MEASURE_STEP
    kept.mkdir()
    for name in ("report.html", "result.json"):
        shutil.copyfile(root / ".judgekeeper" / name, kept / name)
    run("fix", "fix")

    marks = _question_marks(root, person)
    holder = {}

    def promptfoo(argv, cwd, env=None, timeout=None):
        """The old rule grades as saved; the new rule grades as the person marked."""
        fake = holder.setdefault("fake", FakePromptfoo(Workspace(root), version="0.124.1"))
        if "eval" in argv:
            config = json.loads((cwd / argv[argv.index("-c") + 1]).read_text(encoding="utf-8"))
            tests = json.loads((cwd / config["tests"].removeprefix("file://"))
                               .read_text(encoding="utf-8"))
            fake.flips = set()
            for t in tests:
                q = t["vars"]["question"]
                if t["assert"][0]["value"] == NEW_RULE and fake.saved[q][0] != marks[q]:
                    fake.flips.add((t["description"], 0))
                if holder.get("wobble") and q in holder["wobble"]:
                    fake.flips.add((t["description"], 1))  # the second ask says the opposite
        return fake(argv, cwd, env, timeout)

    monkeypatch.setattr(again, "run_process", promptfoo)
    (root / ".judgekeeper" / "fix" / "rule.txt").write_text(NEW_RULE, encoding="utf-8")
    run("fix_test", "fix")

    # The model changes and the eval runs again: the new judge fails 6 answers the person
    # passed that the old judge passed too, and swaps one right and one wrong answer the
    # person failed. Asked twice, it changes its mind on 3.
    passed_right = [q for q, ok in marks.items() if ok and holder["fake"].saved[q][0]][:6]
    failed = [q for q, ok in marks.items() if not ok]
    failed_right = [q for q in failed if not holder["fake"].saved[q][0]][:1]
    failed_wrong = [q for q in failed if holder["fake"].saved[q][0]][:1]
    new = split(23, 17)
    for i in range(40):
        if SHOP[i][0] in passed_right + failed_right + failed_wrong:
            new[i] = not new[i]
    _results(root, new, model="openai:gpt-4.1-nano",
             outputs=[f"{a} (new run)" for _, a, *_ in SHOP])
    holder.pop("fake")
    holder["wobble"] = set([q for q in marks if q not in passed_right][:3])
    run("check", "check")
    return out


def _site(page: str) -> dict[str, list[str]]:
    return {el.attrs["data-screen"]: el.text().strip("\n").splitlines()
            for el in parse(WEBSITE / page).iter() if el.tag == "template"}


@pytest.mark.version_number  # the screens show the version line
@pytest.mark.parametrize("page", ["index.html"])
def test_each_screen_on_the_site_is_what_judgekeeper_prints(tmp_path, monkeypatch, capsys,
                                                            pages, page):
    root = tmp_path / "example-project"
    root.mkdir()
    monkeypatch.chdir(root)
    real = real_screens(root, capsys, monkeypatch)
    for name, lines in _site(page).items():
        assert lines[0] == f"$ {COMMANDS[name]}", (page, name)
        assert lines[1:] == [as_shown(line) for line in real[name]], (page, name)


def _steady(name: str, text: str) -> str:
    """The file without what changes from run to run: the times, the date of the results in
    the computer's own time zone, and the hash of the marks (each mark keeps its time)."""
    if name == "result.json":
        text = re.sub(r'"marks_sha256": "[0-9a-f]+"', '"marks_sha256": "…"', text)
        text = re.sub(r'"results_date": "[^"]*"', '"results_date": "…"', text)
    return re.sub(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", "…", text)


def test_the_site_example_report_is_this_run(tmp_path, monkeypatch, capsys):
    root = tmp_path / "example-project"
    root.mkdir()
    monkeypatch.chdir(root)
    real_screens(root, capsys, monkeypatch)
    for name in ("report.html", "result.json"):
        made = (root / MEASURE_STEP / name).read_text(encoding="utf-8")
        if os.environ.get("JK_WRITE_SITE_EXAMPLE"):
            SITE_EXAMPLE.mkdir(parents=True, exist_ok=True)
            (SITE_EXAMPLE / name).write_text(made, encoding="utf-8", newline="\n")
        kept = (SITE_EXAMPLE / name).read_text(encoding="utf-8")
        assert _steady(name, kept) == _steady(name, made), name
    assert "made-up answers" in (SITE_EXAMPLE / "README.md").read_text(encoding="utf-8")


def _report_text(page: str) -> str:
    """The report as it reads: no styles, scripts or tags, one space between words."""
    page = re.sub(r"<style.*?</style>|<script.*?</script>", "", page, flags=re.DOTALL)
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", page)).split())


def test_site_example_report_is_the_measure_step():
    """Home links this report from its Measure screen: it is the report of that step (no
    re-check above it), its answers read like a support bot's, and its numbers are the
    screens' numbers."""
    text = _report_text((SITE_EXAMPLE / "report.html").read_text(encoding="utf-8"))
    assert not re.search(r"Question \d+\?|Answer \d+\.|reason \d+", text)
    assert len([q for q, *_ in SHOP if q in text]) == 10  # 5 shown of each kind of mistake
    for gone in ("Last check", "old LLM-as-a-judge", "new LLM-as-a-judge"):
        assert gone not in text, gone
    for number in ("16 of 30 answers", ("You passed 15 answers. Of those, your LLM-as-a-judge "
                   "passed 7 and failed 8"), ("You failed 15 answers. Of those, your "
                   "LLM-as-a-judge passed 8 and failed 7"), "about 54% 35% and 72%",
                   "about 39% 23% and 58%", "−0.07"):
        assert number in text, number
    readme = (SITE_EXAMPLE / "README.md").read_text(encoding="utf-8")
    assert "Measure step" in readme
