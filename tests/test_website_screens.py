"""The terminal screens on the website are what judgekeeper prints.

One example project, as the screens show it: promptfoo, 40 answers graded by
openai:gpt-4.1-mini (23 Pass, 17 Fail), the rule on line 14 of promptfooconfig.yaml. The
person marks 12 answers, then 30; `judgekeeper fix` keeps some aside, a new rule is tested on
them, and the model changes to gpt-4.1-nano for `judgekeeper check`. The two steps that ask the
judge use the fake promptfoo of the other tests (no AI call), and the person answers "y" at
the terminal. Each screen on the Home page, and the same screens on the Guide, must be the
output line for line, after the "$ judgekeeper ..." line the site adds.
"""

from __future__ import annotations

import json

import pytest

from judgekeeper import again, fix, keys, start
from judgekeeper.cli import main
from judgekeeper.start_label import StartSession, Workspace
from tests.start_projects import answer, project_promptfoo, promptfoo_data, question, split
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
SEED = 7  # the marks fix keeps aside
COMMANDS = {"find": "judgekeeper", "mark": "judgekeeper", "measure": "judgekeeper",
            "fix": "judgekeeper fix", "fix_test": "judgekeeper fix", "check": "judgekeeper check"}


def _results(root, verdicts, model="openai:gpt-4.1-mini", outputs=None) -> None:
    data = promptfoo_data(verdicts, model=model, rubric=RULE, outputs=outputs)
    data["metadata"]["promptfooVersion"] = "0.124.1"
    (root / "results.json").write_text(json.dumps(data), encoding="utf-8")


def _mark(root, plan, person: dict) -> None:
    """plan: (the judge's grade, the person's mark, how many) of answers not marked yet."""
    session = StartSession(Workspace(root))
    for grade, mark, count in plan:
        for item in session.items:
            if count and session.groups[item["id"]] == grade and item["id"] not in person:
                session.update({"id": item["id"], "label": mark, "seconds": 5})
                person[item["id"]] = mark
                count -= 1


def _question_marks(root, person: dict) -> dict[str, bool]:
    """The person's marks by question text, as promptfoo sees the answers."""
    ws = Workspace(root)
    rows = [json.loads(line) for line in ws.pool.read_text(encoding="utf-8").splitlines()]
    texts = {row["id"]: json.dumps(row["input"]) for row in rows}
    return {question(i): person[item] == "pass" for item, text in texts.items()
            for i in range(40) if item in person and f'"{question(i)}"' in text}


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
        if question(i) in passed_right + failed_right + failed_wrong:
            new[i] = not new[i]
    _results(root, new, model="openai:gpt-4.1-nano",
             outputs=[f"{answer(i)} (new run)" for i in range(40)])
    holder.pop("fake")
    holder["wobble"] = set([q for q in marks if q not in passed_right][:3])
    run("check", "check")
    return out


def _site(page: str) -> dict[str, list[str]]:
    els = list(parse(WEBSITE / page).iter())
    if page == "index.html":
        return {el.attrs["data-screen"]: el.text().strip("\n").splitlines()
                for el in els if el.tag == "template"}
    shown = [el.text().strip("\n").splitlines() for el in els
             if el.tag == "pre" and "term-out" in el.classes()]
    return dict(zip(["find", "fix", "fix_test", "check"], shown, strict=True))


@pytest.mark.parametrize("page", ["index.html", "start.html"])
def test_each_screen_on_the_site_is_what_judgekeeper_prints(tmp_path, monkeypatch, capsys,
                                                            pages, page):
    root = tmp_path / "example-project"
    root.mkdir()
    monkeypatch.chdir(root)
    real = real_screens(root, capsys, monkeypatch)
    for name, lines in _site(page).items():
        assert lines[0] == f"$ {COMMANDS[name]}", (page, name)
        assert lines[1:] == [as_shown(line) for line in real[name]], (page, name)
