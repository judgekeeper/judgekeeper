"""Labeling with `judgekeeper start`: the queue, the `.judgekeeper/` folder, the session the
labeling page writes to, and the result.

The queue: a seeded shuffle of each group (the judge's passes and its fails), then blocks of
10, 5 from each group, shuffled inside the block. When one group runs out the rest comes
from the other. The whole pool is queued. The seed is saved, so the queue can be rebuilt.

`.judgekeeper/` in the project holds:
- start.json: the tool, the results files used, the judge and its fingerprint, the pool
  counts, what was left out, the seed and the queue (ids and groups). Written when labeling
  starts.
- pool.jsonl (id, input, output, in queue order; plus trajectory, outcome and app_version
  when the results have them, never shown on a page) and pool-judge.jsonl (the judge's
  verdict on every pool answer, in the run-file format, each line with the full fingerprint).
  Written when labeling starts.
- labels.csv: the person's labels in the `template` shape, written on every click. A skipped
  answer has no label and the note "skipped".
- anchors.jsonl and its manifest: the labeled answers as a frozen anchor set, so `judge`,
  `baseline` and `gate` work on them later (with the pool's trajectory, outcome and
  app_version, frozen too). Written with each result.
- result.json and result.html, with the earlier result moved to history/.
- review.json, judge-mistakes.csv and rule-unclear.csv: the review of the disagreements
  (start_review.py).
Every string from a results file is scrubbed of credentials before it is written. Nothing is
written anywhere else, and the user's .gitignore is never touched.
"""

from __future__ import annotations

import json
import random
import secrets
import sys
import webbrowser
from datetime import UTC, date, datetime
from pathlib import Path

from judgekeeper import __version__, find, weighted
from judgekeeper.anchors import canonical_hash
from judgekeeper.fingerprint import JudgeFingerprint, utc_now
from judgekeeper.judgments import judgment_to_record, write_run
from judgekeeper.label import LabelSession, make_server
from judgekeeper.records import AGENT_FIELDS
from judgekeeper.redact import scrub_fingerprint, scrub_value
from judgekeeper.report import KAPPA_GATE, RATE_CARE, RATE_GATE
from judgekeeper.runners.base import Judgment
from judgekeeper.start_page import label_page, result_page
from judgekeeper.table import write_anchor_file

FOLDER = ".judgekeeper"
SKIPPED = "skipped"
BLOCK = 10
ROUGH = 15
RELIABLE = 25
SAVED_NOTE = (f"Saved in {FOLDER}/. It holds your answers' text: commit it only if your data "
              "may live in your repo.")
CORRECTED = "Corrected for picking half from the judge's passes and half from its fails."
STATUS = [  # (the fewest of Correct and Wrong, the line under the meters, ready for a result)
    (0, f"A rough check needs {ROUGH} of each.", False),
    (ROUGH, f"Rough check ready. A reliable result needs {RELIABLE} of each.", True),
    (RELIABLE, "Reliable result ready.", True),
]
LEVELS = {  # verdict level: (colour, icon, second line)
    "gate": ("green", "tick", "Keep checking it after changes to its model or rule."),
    "check": ("amber", "warn", "Close to good enough. Labeling more will make this surer."),
    "not_gate": ("red", "cross", "Look at where it disagreed before relying on it."),
    None: ("grey", None, None),
}
MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August",
          "September", "October", "November", "December")
VERDICTS = {
    "gate": "It agrees with you often enough to use as a gate.",
    "check": ("It agrees with you often, but check its fails and passes by hand before "
              "relying on it."),
    "not_gate": "It does not agree with you often enough to use as a gate.",
    None: "Too few labels to tell yet. Label more for a rough check.",
}
CHECKS = {"reliable": "reliable result", "rough": "rough check", "too_few": "too few labels"}
ASKABLE = ("promptfoo", "deepeval", "inspect", "mlflow")  # tools whose judge can be run again
ALL_LABELED = "Every saved answer is labeled. Run your evals again for more answers, then:"


class Workspace:
    """The `.judgekeeper/` folder of one project, or (`folder`) another folder holding a
    check of its own, such as a new judge's confirmation check."""

    def __init__(self, root: str | Path, folder: str | Path | None = None):
        self.root = Path(root)
        self.dir = Path(folder) if folder is not None else self.root / FOLDER
        self.start = self.dir / "start.json"
        self.pool = self.dir / "pool.jsonl"
        self.pool_judge = self.dir / "pool-judge.jsonl"
        self.labels = self.dir / "labels.csv"
        self.anchors = self.dir / "anchors.jsonl"
        self.result_json = self.dir / "result.json"
        self.result_html = self.dir / "result.html"
        self.history = self.dir / "history"
        self.review = self.dir / "review.json"
        self.judge_mistakes = self.dir / "judge-mistakes.csv"
        self.rule_unclear = self.dir / "rule-unclear.csv"

    def data(self) -> dict:
        return json.loads(self.start.read_text(encoding="utf-8"))


def _scrubbed(value):
    """`value` with every string in it scrubbed of credentials."""
    return scrub_value(value)


def _write_json(path: Path, data) -> None:
    path.write_text(json.dumps(_scrubbed(data), indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")


# The queue -------------------------------------------------------------------------------

def build_queue(answers, seed: int) -> list[dict]:
    """[{"id", "group"}] for every answer in the pool, in the order the page shows them."""
    rng = random.Random(seed)
    left = {g: sorted(a.id for a in answers if a.verdict == g) for g in ("pass", "fail")}
    for ids in left.values():
        rng.shuffle(ids)
    half = BLOCK // 2
    queue = []
    while left["pass"] or left["fail"]:
        take = {g: min(half, len(ids)) for g, ids in left.items()}
        short = BLOCK - sum(take.values())
        for g, other in (("pass", "fail"), ("fail", "pass")):
            if take[g] < half:  # this group ran out: the other fills the block
                take[other] = min(take[other] + short, len(left[other]))
        block = [{"id": i, "group": g} for g in ("pass", "fail") for i in left[g][:take[g]]]
        for g, ids in left.items():
            del ids[:take[g]]
        rng.shuffle(block)
        queue += block
    return queue


# Starting to label -----------------------------------------------------------------------

def prepare(found, say, ws: Workspace | None = None) -> Workspace:
    """Write start.json, pool.jsonl and pool-judge.jsonl for `found` (a start.Found), in `ws`
    (default: the project's `.judgekeeper/`).

    When start.json already holds the same pool (the same answers with the same verdicts),
    its seed and queue are kept, so labeling again carries on where it stopped.
    """
    from judgekeeper.start import StartError

    ws = ws or Workspace(found.root)
    answers = {a.id: a for a in found.pool.answers}
    old = ws.data() if ws.start.is_file() else None
    groups = {a.id: a.verdict for a in found.pool.answers}
    if old is not None and {q["id"]: q["group"] for q in old["queue"]} == groups:
        seed, queue, started = old["seed"], old["queue"], old.get("started_at")
    else:
        if ws.labels.is_file():
            raise StartError(f"{FOLDER}/labels.csv holds labels for other results. Move "
                             f"{FOLDER}/ somewhere else to start fresh; nothing was changed.")
        seed = secrets.randbelow(2**31)
        queue, started = build_queue(found.pool.answers, seed), None
    first = old is None
    ws.dir.mkdir(parents=True, exist_ok=True)

    given = found.fingerprint.get("model_source") is not None
    pool, records = [], []
    for q in queue:
        a = answers[q["id"]]
        pool.append({"id": a.id, "input": a.input, "output": a.output, **a.agent})
        fp = a.fingerprint.with_(model=found.fingerprint["model"]) if given else a.fingerprint
        records.append(judgment_to_record(a.id, Judgment(
            verdict=a.verdict, raw_score=a.score, rationale=a.reason), fp))
    pool = _scrubbed(pool)
    ws.pool.write_text("".join(json.dumps(p, ensure_ascii=False) + "\n" for p in pool),
                       encoding="utf-8")
    pool_sha = canonical_hash(pool)
    source = {"kind": found.tool, "file": ", ".join(found.used), "metric": found.metric}
    write_run(ws.pool_judge, 1, pool_sha, JudgeFingerprint.from_dict(found.fingerprint),
              records, source=source)

    newest = found.results[0]
    p = found.pool
    _write_json(ws.start, {
        "judgekeeper_version": __version__,
        "tool": found.tool,
        "results_files": found.used,
        "results_date": f"{newest.date():%Y-%m-%d %H:%M}",
        "metric": found.metric,
        "judge": found.judge,
        "rule": found.rule,
        "description": found.description,
        "app_version": found.app_version,
        **({"mlflow_store": found.store} if found.store else {}),
        "fingerprint": scrub_fingerprint(found.fingerprint),
        "pool": {"answers": len(p.answers), "pass": p.n_pass, "fail": p.n_fail},
        "pool_sha256": pool_sha,
        "left_out": {"no_clear_verdict": p.n_unclear, "unmapped_values": p.unmapped,
                     "repeats_merged": p.n_merged, "human_labels_not_used": p.n_human},
        "seed": seed,
        "queue": queue,
        "started_at": started or utc_now(),
        "updated_at": utc_now(),
    })
    if first:
        say(SAVED_NOTE)
    return ws


# The session the page writes to ----------------------------------------------------------

def display(value) -> str:
    """An input or output as text for the page: a string as written; a dict of fields (such
    as promptfoo's vars) as one `name: value` line each."""
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    if isinstance(value, dict):
        return "\n".join(f"{k}: {v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)}"
                         for k, v in value.items())
    return json.dumps(value, ensure_ascii=False, indent=2)


def question_view(value):
    """A question as the page shows it: text as written; of a set of named values (such as
    promptfoo's vars), one value alone, or several as [[name, value as text], ...]."""
    if isinstance(value, dict) and len(value) > 1:
        return [[str(k), v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)]
                for k, v in value.items()]
    if isinstance(value, dict) and value:
        value = next(iter(value.values()))
    return display(value)


def progress_status(correct: int, wrong: int) -> tuple[str, bool]:
    """The line under the meters on the labeling page, and whether a result is ready."""
    least = min(correct, wrong)
    _, text, ready = [s for s in STATUS if least >= s[0]][-1]
    return text, ready


class StartSession(LabelSession):
    """The pool in queue order and the person's labels. Skip is the label session's defer,
    saved as the note "skipped". The page gets ids, text and the person's labels only."""

    def __init__(self, ws: Workspace):
        self.workspace = ws
        super().__init__(ws.pool, ws.labels)
        raw = [json.loads(line) for line in ws.pool.read_text(encoding="utf-8").splitlines()
               if line.strip()]
        self.raw = {r["id"]: r for r in raw}
        for item in self.items:
            item["deferred"] = item["note"] == SKIPPED

    def _apply(self, item: dict, body: dict) -> None:
        super()._apply(item, body)
        if item["deferred"]:
            item["note"] = SKIPPED
        elif item["note"] == SKIPPED:
            item["note"] = ""

    def counts(self) -> dict:
        labels = [i["label"] for i in self.items]
        return {"correct": labels.count("pass"), "wrong": labels.count("fail"),
                "skipped": sum(i["deferred"] for i in self.items)}

    def summary(self) -> dict:
        counts = self.counts()
        return {"n_items": len(self.items), "n_labeled": counts["correct"] + counts["wrong"],
                "counts": counts, "done": all(i["label"] or i["deferred"] for i in self.items)}

    def state(self) -> dict:
        start = next((n for n, i in enumerate(self.items)
                      if not i["label"] and not i["deferred"]), 0)
        items = [{"id": i["id"], "input": question_view(self.raw[i["id"]].get("input")),
                  "output": display(self.raw[i["id"]].get("output")), "label": i["label"],
                  "skipped": i["deferred"]} for i in self.items]
        return {"items": items, "start": start, "counts": self.counts()}


# The result ------------------------------------------------------------------------------

def _level(r: dict) -> str | None:
    if r["check"] == "too_few":
        return None
    tpr, tnr, kappa = r["tpr"], r["tnr"], r["kappa"]
    if kappa is None or tpr is None or tnr is None or kappa < KAPPA_GATE \
            or min(tpr, tnr) < RATE_GATE:
        return "not_gate"
    return "check" if min(tpr, tnr) < RATE_CARE else "gate"


def describe(corrected: dict) -> dict:
    """The corrected numbers plus the label counts, how far along they are, and the verdict
    (the thresholds of `report`, with wording that only says how often it agrees)."""
    g = corrected["groups"]
    correct = g["pass"]["correct"] + g["fail"]["correct"]
    wrong = g["pass"]["labeled"] + g["fail"]["labeled"] - correct
    least = min(correct, wrong)
    r = dict(corrected)
    r["labels"] = {"correct": correct, "wrong": wrong}
    r["check"] = "reliable" if least >= RELIABLE else "rough" if least >= ROUGH else "too_few"
    r["verdict_level"] = _level(r)
    r["verdict"] = VERDICTS[r["verdict_level"]]
    return r


def _pct(x: float) -> str:
    return f"{x:.0%}"


def sentences(r: dict) -> list[str]:
    if r["check"] == "too_few":
        labels = r["labels"]
        return [(f"A rough check needs {ROUGH} you mark Correct and {ROUGH} you mark Wrong. "
                 f"So far: {labels['correct']} Correct, {labels['wrong']} Wrong.")]
    out = []
    for key, marked, did, does in (("tpr", "Correct", "passed", "passes"),
                                   ("tnr", "Wrong", "failed", "fails")):
        value, (lo, hi) = r[key], r[f"{key}_interval"]
        if value is None:
            out.append(f"How often your judge {does} the answers you mark {marked} is unknown "
                       "yet: label more answers to find out.")
        else:
            out.append(f"Of the answers you marked {marked}, your judge {did} about "
                       f"{_pct(value)} ({_pct(lo)} to {_pct(hi)}).")
    return out


def _number(name: str, value, interval) -> str:
    if value is None:
        return f"{name} unknown"
    if interval is None or interval[0] is None:
        return f"{name} {value:.2f}"
    return f"{name} {value:.2f} ({interval[0]:.2f}–{interval[1]:.2f})"


def pass_rate_line(r: dict) -> str:
    if r["judge_pass_rate"] is None:
        return ""
    line = f"Your judge passes {_pct(r['judge_pass_rate'])} of your app's answers."
    if r["real_pass_rate"] is None:
        return f"{line} How many should pass is unknown yet."
    lo, hi = r["real_pass_rate_interval"]
    return (f"{line} From your labels, about {_pct(r['real_pass_rate'])} should pass "
            f"({_pct(lo)}–{_pct(hi)}).")


def to_review(r: dict) -> int:
    """How many disagreements are left to review: none once the review is done."""
    return 0 if (r.get("review") or {}).get("done") else r.get("disagreements") or 0


def disagreements_words(n: int) -> str:
    return f"the {n} disagreement{'' if n == 1 else 's'}"


def can_ask_again(r: dict) -> bool:
    """Whether judgekeeper can run this judge again (not for verdicts saved by your own code
    or in a table; an older result that does not say which tool is offered as before)."""
    tool = (r.get("judge") or {}).get("tool")
    return tool is None or tool in ASKABLE


def all_labeled(r: dict) -> bool:
    return r.get("left") == 0


def _next(r: dict) -> list[tuple[str, str]]:
    steps = []
    if r["check"] != "reliable" and not all_labeled(r):
        steps.append(("Label more for a reliable result:", "judgekeeper start"))
    if to_review(r):
        steps.append((f"Review {disagreements_words(to_review(r))}:",
                      "judgekeeper start --review"))
    if can_ask_again(r):
        steps.append(("Ask your judge again:", "judgekeeper start --ask-again"))
    if r.get("new_judge"):
        steps.append(("Check your new judge from now on:", "judgekeeper start --new"))
    return steps + [("Check again after your next eval run:", "judgekeeper start")]


def _again_lines(r: dict) -> list[str]:
    from judgekeeper.again.fresh import again_lines

    return again_lines(r["again"]) if r.get("again") else []


def _new_judge_lines(r: dict) -> list[str]:
    from judgekeeper.new_judge import lines

    return lines(r["new_judge"]) if r.get("new_judge") else []


def _review_lines(r: dict) -> list[str]:
    from judgekeeper.start_review import review_lines

    return review_lines(r["review"]) if r.get("review") else []


def result_lines(r: dict, saved: str = FOLDER) -> list[str]:
    """The result as the terminal shows it."""
    labels = r["labels"]
    title = (f"Your result ({CHECKS[r['check']]}: {labels['correct']} Correct, "
             f"{labels['wrong']} Wrong)")
    lines = [title, ""]
    lines += sentences(r)
    lines += [r["verdict"]]
    if r["check"] != "too_few":
        lines.append("")
        lines.append("  " + "   ".join([_number("TPR", r["tpr"], r["tpr_interval"]),
                                        _number("TNR", r["tnr"], r["tnr_interval"]),
                                        _number("kappa", r["kappa"], None)]))
        if pass_rate_line(r):
            lines.append(f"  {pass_rate_line(r)}")
        lines.append(f"  {CORRECTED}")
    if r.get("review"):
        lines += [""] + [f"  {line}" for line in _review_lines(r)]
    if r.get("again"):
        lines += ["", "  Your judge, asked again:"] + [f"  {line}" for line in _again_lines(r)]
    if r.get("new_judge"):
        lines += ["", "  Your new judge:"] + [f"  {line}" for line in _new_judge_lines(r)]
    lines += ["", "Next:"]
    lines += [f"  {text}  {command}" for text, command in _next(r)]
    lines += ["", f"Saved in {saved}/ (result.html is the page you just saw)."]
    return lines


def in_words(day: str) -> str:
    """"2026-10-05" as "5 October 2026"; anything else as it is."""
    try:
        d = date.fromisoformat(day)
    except ValueError:
        return day
    return f"{d.day} {MONTHS[d.month - 1]} {d.year}"


def _made_on(made_at: str | None) -> str | None:
    """The local date a result was made (`made_at` is UTC), in words."""
    try:
        made = datetime.strptime(made_at or "", "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError:
        return None
    return in_words(f"{made.astimezone():%Y-%m-%d}")


def _detail(r: dict) -> str | None:
    """The verdict's second line: for a bad result, the weaker side first."""
    detail = LEVELS[r["verdict_level"]][2]
    tpr, tnr = r["tpr"], r["tnr"]
    if r["verdict_level"] != "not_gate" or tpr is None or tnr is None or tpr == tnr:
        return detail
    side = ("It misses many answers you marked Wrong." if tnr < tpr
            else "It fails many answers you marked Correct.")
    return f"{side} {detail}"


def still_needed(labels: dict) -> str | None:
    """"6 more Correct and 4 more Wrong." for a reliable result, or None once reliable."""
    parts = [f"{RELIABLE - labels[k]} more {name}"
             for k, name in (("correct", "Correct"), ("wrong", "Wrong")) if labels[k] < RELIABLE]
    return f"{' and '.join(parts)}." if parts else None


def _pass_rate(r: dict) -> list[tuple[str, bool]] | None:
    """The pass-rate line as (text, bold) parts."""
    if r["judge_pass_rate"] is None:
        return None
    parts = [("Your judge passes ", False), (_pct(r["judge_pass_rate"]), True),
             (" of your app's answers.", False)]
    if r["real_pass_rate"] is None:
        return parts + [(" How many should pass is unknown yet.", False)]
    lo, hi = r["real_pass_rate_interval"]
    return parts + [(" From your labels, about ", False), (_pct(r["real_pass_rate"]), True),
                    (f" should pass ({_pct(lo)} to {_pct(hi)}).", False)]


def page_content(r: dict) -> dict:
    """The result page's text and numbers (start_page.result_page lays them out)."""
    labels = r["labels"]
    n = labels["correct"] + labels["wrong"]
    kind = [CHECKS[r["check"]].capitalize(),
            f"{labels['correct']} marked Correct, {labels['wrong']} marked Wrong"
            + (f", {r['skipped']} skipped" if r.get("skipped") else "")]
    if _made_on(r.get("made_at")):
        kind.append(_made_on(r.get("made_at")))

    too_few = r["check"] == "too_few"

    def tile(name, plain, value, interval, count):
        if too_few:
            return {"name": name, "plain": plain, "value": "–", "interval": None,
                    "mark": None, "line": count}
        known = value is not None
        span = known and interval is not None and interval[0] is not None
        return {"name": name, "plain": plain,
                "value": f"{value:.2f}" if known else "unknown",
                "interval": (interval[0], interval[1]) if span else None,
                "mark": value if known else None,
                "line": f"{interval[0]:.2f} to {interval[1]:.2f} · {count}" if span else count}

    colour, icon, _ = LEVELS[r["verdict_level"]]
    judge = r.get("judge") or {}
    fingerprint = r.get("fingerprint") or {}
    model = fingerprint.get("model") or "model not named in the results"
    if fingerprint.get("model_source"):
        model += " (as you told me)"
    source = None
    if judge.get("results_files"):
        tool = find.NAMES.get(judge.get("tool"), judge.get("tool"))
        source = f"From {', '.join(judge['results_files'])}" + (f" ({tool})" if tool else "")
        saved = judge.get("results_date")  # "2026-10-05 05:30"
        if saved:
            source += f", saved {in_words(saved[:10])}{saved[10:].replace(' ', ', ', 1)}"
    steps = []
    needed = still_needed(labels)
    if needed and all_labeled(r):
        steps.append({"title": "Make it a reliable result", "text": ALL_LABELED,
                      "command": "judgekeeper start", "link": None, "button": None})
    elif needed:
        steps.append({"title": "Make it a reliable result", "text": needed,
                      "command": "judgekeeper start", "link": "/", "button": "Keep labeling"})
    if to_review(r):
        steps.append({"title": f"Review {disagreements_words(to_review(r))}",
                      "text": ("Each answer where you and your judge disagree, with its "
                               "reason. Free."),
                      "command": "judgekeeper start --review", "link": "/review",
                      "button": "Review them"})
    if can_ask_again(r):
        steps.append({"title": "Ask your judge again",
                      "text": ("How often it changes its mind, and how well it agrees with "
                               "you today. It asks before any call:"),
                      "command": "judgekeeper start --ask-again", "link": None,
                      "button": None})
    if r.get("new_judge"):
        steps.append({"title": "Check your new judge from now on",
                      "text": ("Your last check moves to .judgekeeper/previous-<date>/; nothing "
                               "is deleted:"),
                      "command": "judgekeeper start --new", "link": None, "button": None})
    if not (needed and all_labeled(r)):  # else the first step already says it
        steps.append({"title": "Check again later", "text": "After your next eval run:",
                      "command": "judgekeeper start", "link": None, "button": None})
    review = None
    if r.get("review"):
        review = {"title": "Your review of the disagreements", "lines": _review_lines(r),
                  "files": [f"{FOLDER}/{name}" for name in r["review"].get("files", [])]}
    asked_again = None
    if r.get("again"):
        asked_again = {"title": "Your judge, asked again", "lines": _again_lines(r),
                       "files": [r["again"]["folder"] + "/"]}
    new_judge = None
    if r.get("new_judge"):
        files = [r["new_judge"]["folder"] + "/"]
        new_judge = {"title": "Your new judge", "lines": [x for x in _new_judge_lines(r) if x],
                     "files": files}
    return {
        "kind": " · ".join(kind),
        "sentences": sentences(r),
        "verdict": {"colour": colour, "icon": icon, "text": r["verdict"], "detail": _detail(r)},
        "tiles": [tile("TPR", "Good answers it passed", r["tpr"], r["tpr_interval"],
                       f"from {labels['correct']} Correct"),
                  tile("TNR", "Bad answers it failed", r["tnr"], r["tnr_interval"],
                       f"from {labels['wrong']} Wrong"),
                  tile("kappa", "Agreement beyond chance", r["kappa"], None,
                       f"from {n} labels · {KAPPA_GATE:g} or more is good")],
        "pass_rate": None if too_few else _pass_rate(r),
        "corrected": None if too_few else (
            "Numbers are corrected for picking half from the judge's passes and half from its "
            "fails. The bar under each number shows how sure it is: narrower is surer."),
        "judge": {"name": judge.get("metric") or judge.get("name"), "model": model,
                  "rule": judge.get("rule"), "source": source},
        "review": review,
        "again": asked_again,
        "new_judge": new_judge,
        "next": steps,
        "folder": f"{FOLDER}/",
    }


def result_html(r: dict, back: str | None = None) -> str:
    return result_page(page_content(r), back)


def page_template(about: dict | None = None) -> str:
    """The labeling page for a check whose start.json is `about`: its description and its
    judge's rule are shown; nothing else from it is."""
    about = about or {}
    return label_page(about.get("description"), about.get("rule"), STATUS)


def compute(ws: Workspace, session: StartSession) -> dict:
    data = ws.data()
    groups = {q["id"]: q["group"] for q in data["queue"]}
    counted = {"pass": [0, 0], "fail": [0, 0]}  # labeled, Correct
    disagreements = 0
    for item in session.items:
        if item["label"]:
            g = counted[groups[item["id"]]]
            g[0] += 1
            g[1] += item["label"] == "pass"
            disagreements += item["label"] != groups[item["id"]]
    r = describe(weighted.corrected(data["pool"]["pass"], data["pool"]["fail"],
                                    *counted["pass"], *counted["fail"]))
    r.update(skipped=session.counts()["skipped"], disagreements=disagreements,
             left=sum(1 for item in session.items if not item["label"]),
             made_at=utc_now(),
             judgekeeper_version=__version__, fingerprint=data["fingerprint"],
             judge={"name": data["judge"], "tool": data["tool"], "metric": data["metric"],
                    "rule": data.get("rule"), "description": data.get("description"),
                    "results_files": data["results_files"],
                    "results_date": data.get("results_date")})
    return r


def save_result(ws: Workspace, session: StartSession, say) -> dict:
    """Make a result from the labels so far: anchors, result.json and result.html (the last
    result moves to history/), and say it in the terminal."""
    r = compute(ws, session)
    anchors = [{"id": i["id"], "input": session.raw[i["id"]].get("input", ""),
                "output": session.raw[i["id"]].get("output", ""), "human_label": i["label"],
                **{k: session.raw[i["id"]][k] for k in AGENT_FIELDS if k in session.raw[i["id"]]}}
               for i in session.items if i["label"]]
    if anchors:
        write_anchor_file(ws.anchors, _scrubbed(anchors))
    if ws.result_json.is_file():
        ws.history.mkdir(exist_ok=True)
        try:
            made = json.loads(ws.result_json.read_text(encoding="utf-8")).get("made_at")
        except ValueError:
            made = None
        stamp = (made or utc_now()).replace(":", "-")
        target = ws.history / f"result-{stamp}.json"
        n = 2
        while target.exists():
            target = ws.history / f"result-{stamp}-{n}.json"
            n += 1
        ws.result_json.replace(target)
    _write_json(ws.result_json, r)
    ws.result_html.write_text(result_html(_scrubbed(r)), encoding="utf-8")
    say("")
    for line in result_lines(r):
        say(line)
    return r


def result_maker(ws: Workspace, say, made: list | None = None):
    """The server's result function: each call makes and saves a new result."""

    def make(session: StartSession, back: str) -> str:
        r = save_result(ws, session, say)
        done = session.summary()["done"]
        if made is not None:
            made.append(done)
        return result_html(_scrubbed(r), None if done else back)

    return make


def run_labeling(found, port: int, open_browser: bool, say,
                 command: str = "judgekeeper start") -> int:
    """Save the pool of `found`, then serve the labeling page for it."""
    return serve_workspace(prepare(found, say), port, open_browser, say, command)


def serve_workspace(ws: Workspace, port: int, open_browser: bool, say,
                    command: str = "judgekeeper start") -> int:
    """Serve the labeling page until the last answer, Ctrl-C or 2 hours idle. `command`
    (start.Talk.command) is what the person runs to continue."""
    from judgekeeper import start_review

    session = StartSession(ws)
    made: list[bool] = []
    reviewed: list[bool] = []
    server = make_server(session, port, result=result_maker(ws, say, made),
                         page=page_template(ws.data()),
                         switches={"/review": start_review.switch(ws, say, reviewed)})
    print(f"Labeling page: {server.url}")  # not scrubbed: the token must stay whole
    say(f"Every click is saved. Press Ctrl-C here to stop; run {command} to continue.")
    sys.stdout.flush()
    if open_browser:
        webbrowser.open(server.url)
    try:
        server.serve()
    except KeyboardInterrupt:
        pass
    summary = session.summary()
    if summary["done"] and not any(made):
        save_result(ws, session, say)  # nobody fetched the last result: make it here
    elif not summary["done"]:
        say("")
        say(f"Stopped. {summary['n_labeled']} labeled; run {command} to continue.")
    if reviewed:
        start_review.finish(ws, say, command)
    return 0
