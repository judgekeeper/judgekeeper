"""Reviewing the disagreements after a `judgekeeper start` result. No AI call and no key.

A disagreement is a labeled answer where the person's label and the judge's saved verdict
differ. People change a label after seeing a judge's verdict far more often than they should,
so the review has two steps:

- Step A, "Look again": every disagreement mixed with as many answers the person and the
  judge agreed on (at least 3, half from each of the judge's groups where possible), in a
  seeded random order, with the judge's verdict and the first label hidden. Correct, Wrong
  or Not sure.
- Step B, "See what your judge said": only the disagreements, each with both labels, the
  judge's verdict and its reason. The judge was wrong, I was wrong (saved as `slipped`), or
  The rule is unclear; after the first or the last, one optional line of why.

`.judgekeeper/` gains:
- review.json: the result it reviews, the seed, the step A picks in the order shown (id,
  whether a disagreement, the first label, the judge's verdict), each second look and step B
  choice with its time, and the why (scrubbed). Written on every click; a new result starts a new review and the
  old one moves to history/review-<date>/.
- judge-mistakes.csv and rule-unclear.csv: the answers marked "The judge was wrong" and "The
  rule is unclear", with both labels, the judge's verdict and reason, and the why. Cells that could be
  read as spreadsheet formulas are guarded as labels.csv's are.

labels.csv never changes: the first labels stay the main result. Once step A is done,
result.json gains a `review` block: the second-look numbers (each re-looked answer's second
label, Not sure keeping the first, weighted by group as in `weighted.corrected`) and the
step B counts. Step B choices change no number.
"""

from __future__ import annotations

import csv
import json
import random
import secrets
import sys
import webbrowser

from judgekeeper import weighted
from judgekeeper.fingerprint import utc_now
from judgekeeper.judgments import read_run
from judgekeeper.label import make_server
from judgekeeper.redact import scrub
from judgekeeper.start_label import (
    FOLDER,
    Workspace,
    _scrubbed,
    _write_json,
    display,
    question_view,
    result_html,
)
from judgekeeper.start_page import review_page
from judgekeeper.table import guard_cell

MIN_AGREED = 3
SECOND = ("pass", "fail", "unsure")
CHOICES = ("judge_wrong", "slipped", "rule_unclear")
SAID = {"pass": "Correct", "fail": "Wrong"}
VERDICT = {"pass": "Pass", "fail": "Fail"}
COLUMNS = ("id", "input", "output", "your_label", "second_look_label", "judge_verdict",
           "judge_reason", "why")
WHY_MAX = 300  # characters of the one line of why
WHY_CHOICES = ("judge_wrong", "rule_unclear")  # the choices that ask why
FILES = {"judge_wrong": "judge-mistakes.csv", "rule_unclear": "rule-unclear.csv"}
SEVERAL = 3  # changed agreed answers that suggest the rule is unclear


def _plural(n: int, word: str, many: str | None = None) -> str:
    return f"{n} {word if n == 1 else many or word + 's'}"


def labeled(ws: Workspace) -> list[dict]:
    """[{"id", "first", "judge"}] for every labeled answer, in queue order."""
    from judgekeeper.start_again import _labels

    labels = _labels(ws)
    _, records = read_run(ws.pool_judge)
    return [{"id": q["id"], "first": labels[q["id"]], "judge": records[q["id"]]["verdict"]}
            for q in ws.data()["queue"] if q["id"] in labels]


def count(ws: Workspace) -> int:
    """How many labeled answers the person and the judge disagree on."""
    return sum(r["first"] != r["judge"] for r in labeled(ws))


def pick(rows: list[dict], seed: int) -> list[dict]:
    """Step A's answers in the order shown: every disagreement and as many agreed answers (at
    least MIN_AGREED), half from each of the judge's groups where possible, shuffled."""
    rng = random.Random(seed)
    dis = [r for r in rows if r["first"] != r["judge"]]
    agreed = {g: [r for r in rows if r["first"] == r["judge"] == g] for g in ("pass", "fail")}
    for group in agreed.values():
        rng.shuffle(group)
    want = max(MIN_AGREED, len(dis))
    first = rng.choice(("pass", "fail"))
    other = "fail" if first == "pass" else "pass"
    take = {first: want - want // 2, other: want // 2}
    short = {g: max(0, take[g] - len(agreed[g])) for g in take}
    take = {g: min(take[g], len(agreed[g])) for g in take}
    for g, o in ((first, other), (other, first)):
        take[o] = min(len(agreed[o]), take[o] + short[g])
    picks = [{**r, "disagreement": True} for r in dis]
    picks += [{**r, "disagreement": False} for g in ("pass", "fail") for r in agreed[g][:take[g]]]
    rng.shuffle(picks)
    return [{"id": p["id"], "disagreement": p["disagreement"], "first": p["first"],
             "judge": p["judge"]} for p in picks]


def _basis(ws: Workspace) -> dict:
    """What a review is of: the result and the labels and verdicts it was made from."""
    import hashlib

    digest = hashlib.sha256(ws.labels.read_bytes() + b"\0" + ws.pool_judge.read_bytes())
    result = json.loads(ws.result_json.read_text(encoding="utf-8"))
    return {"result_made_at": result.get("made_at"), "sha256": digest.hexdigest()}


def _keep_old(ws: Workspace) -> None:
    """Move an earlier review and its files to history/review-<date>/. Nothing is deleted."""
    stamp = utc_now().replace(":", "-")
    target = ws.history / f"review-{stamp}"
    n = 2
    while target.exists():
        target = ws.history / f"review-{stamp}-{n}"
        n += 1
    target.mkdir(parents=True)
    for p in (ws.review, ws.judge_mistakes, ws.rule_unclear):
        if p.is_file():
            p.replace(target / p.name)


class ReviewSession:
    """The review of one result: step A's picks, the second looks and the step B choices.
    The page gets, in step A, only ids, text and the second looks; in step B, the
    disagreements with both labels and the judge's verdict and reason."""

    def __init__(self, ws: Workspace):
        self.workspace = ws
        self.out = ws.review
        basis = _basis(ws)
        saved = json.loads(ws.review.read_text(encoding="utf-8")) if ws.review.is_file() \
            else None
        if saved is not None and saved.get("basis") != basis:
            _keep_old(ws)
            saved = None
        if saved is None:
            self.seed = secrets.randbelow(2**31)
            self.started_at = utc_now()
            self.items = [{**p, "second": None, "second_at": None, "choice": None,
                           "choice_at": None, "why": None}
                          for p in pick(labeled(ws), self.seed)]
        else:
            self.seed, self.started_at, self.items = (saved["seed"], saved["started_at"],
                                                      saved["items"])
        self.basis = basis
        self.by_id = {i["id"]: i for i in self.items}
        self.raw = {}
        for line in ws.pool.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                self.raw[row["id"]] = row
        _, records = read_run(ws.pool_judge)
        self.reasons = {i: scrub(r.get("rationale") or "") for i, r in records.items()}
        if saved is None:
            self.write()

    # Where the review is ----------------------------------------------------------------

    def disagreements(self) -> list[dict]:
        return [i for i in self.items if i["disagreement"]]

    def step(self) -> str:
        if any(i["second"] is None for i in self.items):
            return "a"
        if any(i["choice"] is None for i in self.disagreements()):
            return "b"
        return "done"

    # Clicks ------------------------------------------------------------------------------

    def update(self, body: dict) -> None:
        """One click: {"id", "second": Correct, Wrong or Not sure, or None to undo} in step
        A, {"id", "choice": one of CHOICES or None} or {"id", "why": text} in step B."""
        item = self.by_id[body["id"]]
        before = dict(item)
        try:
            self._apply(item, body)
            self.write()
        except BaseException:
            item.update(before)
            raise

    def asks_why(self, body: dict) -> bool:
        """Whether the page stays on the answer after this click, for its Why? box: a choice
        that asks why, or the why itself. It moves on with GET /result, not on a timer."""
        return body.get("choice") in WHY_CHOICES or "why" in body

    def _apply(self, item: dict, body: dict) -> None:
        keys = set(body) - {"id"}
        if keys == {"second"}:
            value = body["second"]
            if value is not None and value not in SECOND:
                raise ValueError("second must be pass, fail, unsure or null")
            if any(i["choice"] for i in self.items):
                raise ValueError("the second look is closed once you have seen the judge")
            item["second"], item["second_at"] = value, utc_now() if value else None
        elif keys == {"choice"}:
            value = body["choice"]
            if value is not None and value not in CHOICES:
                raise ValueError(f"choice must be one of {', '.join(CHOICES)} or null")
            if not item["disagreement"]:
                raise ValueError("only a disagreement gets a choice")
            if any(i["second"] is None for i in self.items):
                raise ValueError("look again at every answer first")
            item["choice"], item["choice_at"] = value, utc_now() if value else None
            if value is None:  # undo: the why goes with the choice
                item["why"] = None
        elif keys == {"why"}:
            value = body["why"]
            if value is not None and not isinstance(value, str):
                raise ValueError("why must be text or null")
            if item.get("choice") not in WHY_CHOICES:
                raise ValueError("say why after The judge was wrong or The rule is unclear")
            text = " ".join((value or "").split())
            if len(text) > WHY_MAX:
                raise ValueError(f"why is at most {WHY_MAX} characters")
            item["why"] = scrub(text) or None
        else:
            raise ValueError("expected second, choice or why")

    # What is saved -----------------------------------------------------------------------

    def write(self) -> None:
        ws = self.workspace
        _write_json(ws.review, {"basis": self.basis, "seed": self.seed,
                                "started_at": self.started_at, "updated_at": utc_now(),
                                "items": self.items})
        step_a_done = self.step() != "a"
        if step_a_done:
            for choice, name in FILES.items():
                self._write_rows(ws.dir / name, choice)
        r = json.loads(ws.result_json.read_text(encoding="utf-8"))
        if step_a_done:
            r["review"] = self.block()
        else:
            r.pop("review", None)
        _write_json(ws.result_json, r)
        ws.result_html.write_text(result_html(_scrubbed(r)), encoding="utf-8")

    def _write_rows(self, path, choice: str) -> None:
        with path.open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(COLUMNS)
            for i in self.disagreements():
                if i["choice"] != choice:
                    continue
                raw = self.raw.get(i["id"], {})
                w.writerow([guard_cell(scrub(v)) for v in (
                    i["id"], display(raw.get("input")), display(raw.get("output")), i["first"],
                    i["second"] or "", i["judge"], self.reasons.get(i["id"], ""),
                    i.get("why") or "")])

    def block(self) -> dict:
        """The `review` block of result.json."""
        ws = self.workspace
        data = ws.data()
        groups = {q["id"]: q["group"] for q in data["queue"]}
        labels = {r["id"]: r["first"] for r in labeled(ws)}
        for i in self.items:
            if i["second"] in ("pass", "fail"):
                labels[i["id"]] = i["second"]
        counted = {"pass": [0, 0], "fail": [0, 0]}  # labeled, Correct
        for item_id, label in labels.items():
            g = counted[groups[item_id]]
            g[0] += 1
            g[1] += label == "pass"
        c = weighted.corrected(data["pool"]["pass"], data["pool"]["fail"], *counted["pass"],
                               *counted["fail"])
        from judgekeeper import start_fix

        dis = self.disagreements()

        def changed(items):
            return sum(i["second"] in ("pass", "fail") and i["second"] != i["first"]
                       for i in items)

        chosen = [i["choice"] for i in dis if i["choice"]]
        return {
            "made_at": utc_now(),
            "looked_again": len(self.items),
            "disagreements": len(dis),
            "agreed": len(self.items) - len(dis),
            "changed_disagreements": changed(dis),
            "changed_agreed": changed([i for i in self.items if not i["disagreement"]]),
            "not_sure": sum(i["second"] == "unsure" for i in self.items),
            "second_look": {k: c[k] for k in ("tpr", "tpr_interval", "tnr", "tnr_interval",
                                              "kappa", "groups")},
            "choices": {k: chosen.count(k) for k in CHOICES},
            "chosen": len(chosen),
            "done": len(chosen) == len(dis),
            "files": list(FILES.values()),
            "to_fix": start_fix.to_fix(labeled(ws), self.items),
        }

    # The page ----------------------------------------------------------------------------

    def _text(self, item_id: str) -> dict:
        raw = self.raw.get(item_id, {})
        return {"input": question_view(raw.get("input")), "output": display(raw.get("output"))}

    def state(self) -> dict:
        step = self.step()
        if step == "a":
            items = [{"id": i["id"], **self._text(i["id"]), "second": i["second"]}
                     for i in self.items]
            start = next(n for n, i in enumerate(self.items) if i["second"] is None)
        elif step == "b":
            dis = self.disagreements()
            items = [{"id": i["id"], **self._text(i["id"]), "said": said(i),
                      "judge": VERDICT[i["judge"]], "reason": self.reasons.get(i["id"], ""),
                      "choice": i["choice"], "why": i.get("why")} for i in dis]
            start = next(n for n, i in enumerate(dis) if i["choice"] is None)
        else:
            items, start = [], 0
        return {"step": step, "items": items, "start": start}

    def summary(self) -> dict:
        step = self.step()
        return {"step": step, "done": step == "done"}


def said(item: dict) -> list[tuple[str, bool]]:
    """"You said: Wrong (and Wrong again on a second look)" as (text, bold) parts."""
    parts = [("You said: ", False), (SAID[item["first"]], True)]
    second = item["second"]
    if second == "unsure":
        return parts + [(" (and not sure on a second look)", False)]
    again = " again" if second == item["first"] else ""
    return parts + [(" (and ", False), (SAID[second], True),
                    (f"{again} on a second look)", False)]


def _share(value) -> str:
    return "an unknown share" if value is None else f"about {value:.0%}"


def review_lines(block: dict) -> list[str]:
    """The result's review lines: at most three."""
    cd, ca = block["changed_disagreements"], block["changed_agreed"]
    if cd + ca == 0:
        first = (f"On a second look without the judge, you kept all {block['looked_again']} "
                 "of your labels.")
    else:
        s = block["second_look"]
        first = (f"On a second look without the judge, you changed {cd} of the "
                 f"{_plural(block['disagreements'], 'disagreement')} and {ca} of the "
                 f"{_plural(block['agreed'], 'answer')} you had agreed on. With your "
                 "second-look labels: of the answers that should pass, your judge passed "
                 f"{_share(s['tpr'])}; of those that should fail, it failed "
                 f"{_share(s['tnr'])}.")
    if ca >= SEVERAL:
        first += " You changed several answers on a second look: your rule may be unclear."
    lines = [first]
    if block["chosen"]:
        c = block["choices"]
        when = ("" if block["done"] else
                f" ({block['chosen']} of {block['disagreements']} so far)")
        lines.append(f"After seeing the judge{when}: you called "
                     f"{_plural(c['judge_wrong'], 'judge mistake')} and "
                     f"{_plural(c['rule_unclear'], 'unclear rule')}, and said you were wrong "
                     f"on {_plural(c['slipped'], 'answer')}.")
    lines.append("Your first labels stay the main result.")
    return lines


def files_lines(ws: Workspace) -> list[str]:
    """Where the step B files are, with how many answers each holds."""
    lines = []
    for path, what in ((ws.judge_mistakes, "Your judge's mistakes, to improve its rule with"),
                       (ws.rule_unclear, "Where the rule is unclear, to sharpen it with")):
        if path.is_file():
            with path.open(encoding="utf-8", newline="") as f:
                n = sum(1 for _ in csv.DictReader(f))
            lines.append(f"  {what}: {FOLDER}/{path.name} ({_plural(n, 'answer')})")
    return lines


def page_template(ws: Workspace) -> str:
    about = ws.data()
    return review_page(about.get("description"), about.get("rule"))


def result_maker(ws: Workspace, say):
    """The review server's result function: the saved result, with its review lines."""

    def make(session: ReviewSession, back: str) -> str:
        r = json.loads(ws.result_json.read_text(encoding="utf-8"))
        return result_html(_scrubbed(r))

    return make


def switch(ws: Workspace, say, opened: list):
    """For the labeling server: the review's session, page and result function."""

    def go():
        opened.append(True)
        return ReviewSession(ws), page_template(ws), result_maker(ws, say)

    return go


def finish(ws: Workspace, say, command: str = "judgekeeper start") -> None:
    """Say where the review stopped, or its lines and files once it is done. `command`
    (start.Talk.command) is what the person runs to continue."""
    session = ReviewSession(ws)
    say("")
    if session.step() != "done":
        say(f"Stopped. Every click is saved; run {command} --review to continue.")
        return
    for line in review_lines(session.block()):
        say(line)
    for line in files_lines(ws):
        say(line)


def serve_review(ws: Workspace, port: int, open_browser: bool, say,
                 command: str = "judgekeeper start") -> int:
    """Serve the review page until the review is done, Ctrl-C or 2 hours idle."""
    from judgekeeper import start_fix

    session = ReviewSession(ws)
    server = make_server(session, port, result=result_maker(ws, say), page=page_template(ws),
                         switches={"/fix": start_fix.switch(ws, say)})
    print(f"Review page: {server.url}")  # not scrubbed: the token must stay whole
    say(f"Every click is saved. Press Ctrl-C here to stop; run {command} --review to "
        "continue.")
    sys.stdout.flush()
    if open_browser:
        webbrowser.open(server.url)
    try:
        server.serve()
    except KeyboardInterrupt:
        pass
    finish(ws, say, command)
    return 0


def run(ws: Workspace, talk, port: int, open_browser: bool) -> int:
    """`judgekeeper start --review`, or the menu's review choice."""
    n = count(ws)
    if not n:
        talk.say("You and your judge agree on every answer you labeled: nothing to review.")
        return 0
    session = ReviewSession(ws)
    if session.step() == "done":
        talk.say()
        talk.say(f"You reviewed {_plural(n, 'disagreement')} already.")
        for line in review_lines(session.block()):
            talk.say(line)
        for line in files_lines(ws):
            talk.say(line)
        return 0
    agreed = len(session.items) - len(session.disagreements())
    talk.say()
    talk.say(f"Review the {_plural(n, 'answer')} where you and your judge disagree. Free: no "
             "AI call.")
    talk.say(f"  Step 1: look again at {len(session.items)} answers, with your judge's verdict "
             f"still hidden. {agreed} of them")
    talk.say("  are answers you and your judge agreed on, so being shown one does not mean "
             "you were wrong.")
    talk.say(f"  Step 2: see what your judge said on the {_plural(n, 'disagreement')}.")
    talk.say(f"  Your labels in {FOLDER}/labels.csv stay as they are.")
    if session.step() == "b":
        talk.say(f"You looked again at all {len(session.items)} answers. Carrying on at step 2.")
    talk.say()
    return serve_review(ws, port, open_browser, talk.say, talk.command())


__all__ = ["ReviewSession", "count", "pick", "review_lines", "run", "serve_review", "switch"]
