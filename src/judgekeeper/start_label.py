"""Labeling with `judgekeeper start`: the queue, the `.judgekeeper/` folder, the session the
labeling page writes to, and the result.

The queue: a seeded shuffle of each group (the judge's passes and its fails), then blocks of
10, 5 from each group, shuffled inside the block. When one group runs out the rest comes
from the other. The whole pool is queued. The seed is saved, so the queue can be rebuilt.

`.judgekeeper/` in the project holds:
- start.json: the tool, the results files used, the judge and its fingerprint, the pool
  counts, what was left out, the seed and the queue (ids and groups). Written when labeling
  starts.
- pool.jsonl (id, input, output, in queue order) and pool-judge.jsonl (the judge's verdict on
  every pool answer, in the run-file format, each line with the full fingerprint). Written
  when labeling starts.
- labels.csv: the person's labels in the `template` shape, written on every click. A skipped
  answer has no label and the note "skipped".
- anchors.jsonl and its manifest: the labeled answers as a frozen anchor set, so `judge`,
  `baseline` and `gate` work on them later. Written with each result.
- result.json and result.html, with the earlier result moved to history/.
Every string from a results file is scrubbed of credentials before it is written. Nothing is
written anywhere else, and the user's .gitignore is never touched.
"""

from __future__ import annotations

import json
import random
import secrets
import sys
import webbrowser
from pathlib import Path

from judgekeeper import __version__, weighted
from judgekeeper.anchors import canonical_hash
from judgekeeper.fingerprint import JudgeFingerprint, utc_now
from judgekeeper.judgments import judgment_to_record, write_run
from judgekeeper.label import LabelSession, make_server
from judgekeeper.redact import scrub, scrub_fingerprint
from judgekeeper.report import KAPPA_GATE, RATE_CARE, RATE_GATE
from judgekeeper.runners.base import Judgment
from judgekeeper.start_page import START_PAGE, result_page
from judgekeeper.table import write_anchor_file

FOLDER = ".judgekeeper"
SKIPPED = "skipped"
BLOCK = 10
ROUGH = 15
RELIABLE = 25
SAVED_NOTE = (f"Saved in {FOLDER}/. It holds your answers' text: commit it only if your data "
              "may live in your repo.")
CORRECTED = "Corrected for picking half from the judge's passes and half from its fails."
VERDICTS = {
    "gate": "It agrees with you often enough to use as a gate.",
    "check": ("It agrees with you often, but check its fails and passes by hand before "
              "relying on it."),
    "not_gate": "It does not agree with you often enough to use as a gate.",
    None: "Too few labels to tell yet. Label more for a rough check.",
}
CHECKS = {"reliable": "reliable result", "rough": "rough check", "too_few": "too few labels"}


class Workspace:
    """The `.judgekeeper/` folder of one project."""

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.dir = self.root / FOLDER
        self.start = self.dir / "start.json"
        self.pool = self.dir / "pool.jsonl"
        self.pool_judge = self.dir / "pool-judge.jsonl"
        self.labels = self.dir / "labels.csv"
        self.anchors = self.dir / "anchors.jsonl"
        self.result_json = self.dir / "result.json"
        self.result_html = self.dir / "result.html"
        self.history = self.dir / "history"

    def data(self) -> dict:
        return json.loads(self.start.read_text(encoding="utf-8"))


def _scrubbed(value):
    """`value` with every string in it scrubbed of credentials."""
    if isinstance(value, str):
        return scrub(value)
    if isinstance(value, list):
        return [_scrubbed(v) for v in value]
    if isinstance(value, dict):
        return {k: _scrubbed(v) for k, v in value.items()}
    return value


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

def prepare(found, say) -> Workspace:
    """Write start.json, pool.jsonl and pool-judge.jsonl for `found` (a start.Found).

    When start.json already holds the same pool (the same answers with the same verdicts),
    its seed and queue are kept, so labeling again carries on where it stopped.
    """
    from judgekeeper.start import StartError

    ws = Workspace(found.root)
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
    ws.dir.mkdir(exist_ok=True)

    given = found.fingerprint.get("model_source") is not None
    pool, records = [], []
    for q in queue:
        a = answers[q["id"]]
        pool.append({"id": a.id, "input": a.input, "output": a.output})
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
        items = [{"id": i["id"], "input": display(self.raw[i["id"]].get("input")),
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
    line = f"Your judge passes {_pct(r['judge_pass_rate'])} of your answers."
    if r["real_pass_rate"] is None:
        return f"{line} How many should pass is unknown yet."
    lo, hi = r["real_pass_rate_interval"]
    return (f"{line} From your labels, about {_pct(r['real_pass_rate'])} should pass "
            f"({_pct(lo)}–{_pct(hi)}).")


def _next(r: dict) -> list[tuple[str, str]]:
    steps = [] if r["check"] == "reliable" else [("Label more for a reliable result:",
                                                  "judgekeeper start")]
    return steps + [("Check again after your next eval run:", "judgekeeper start")]


def result_lines(r: dict, saved: str = FOLDER) -> list[str]:
    """The result as the terminal shows it."""
    labels = r["labels"]
    title = (f"Your result ({CHECKS[r['check']]}: {labels['correct']} Correct, "
             f"{labels['wrong']} Wrong)")
    lines = [title, ""]
    lines += sentences(r)
    lines += [r["verdict"], ""]
    lines.append("  " + "   ".join([_number("TPR", r["tpr"], r["tpr_interval"]),
                                    _number("TNR", r["tnr"], r["tnr_interval"]),
                                    _number("kappa", r["kappa"], None)]))
    if pass_rate_line(r):
        lines.append(f"  {pass_rate_line(r)}")
    lines += [f"  {CORRECTED}", "", "Next:"]
    lines += [f"  {text}  {command}" for text, command in _next(r)]
    lines.append(f"  Saved in {saved}/ (result.html is the page you just saw)")
    return lines


def page_content(r: dict) -> dict:
    labels = r["labels"]
    n = labels["correct"] + labels["wrong"]
    skipped = r.get("skipped")
    counted = f"{CHECKS[r['check']].capitalize()}: {labels['correct']} Correct, " \
              f"{labels['wrong']} Wrong" + (f", {skipped} skipped." if skipped else ".")

    def tile(name, value, interval, count):
        shown = "unknown" if value is None else f"{value:.2f}"
        span = ("" if interval is None or interval[0] is None
                else f"{interval[0]:.2f} to {interval[1]:.2f}")
        return {"name": name, "value": shown, "interval": span, "count": count}

    judge = r.get("judge") or {}
    judge_lines = []
    if judge.get("name"):
        judge_lines.append(f"Your judge: {judge['name']}")
    if judge.get("results_files"):
        files = f"Results: {', '.join(judge['results_files'])}"
        judge_lines.append(f"{files}, saved {judge['results_date']}"
                           if judge.get("results_date") else files)
    return {
        "title": "Your result",
        "sentences": sentences(r),
        "verdict": r["verdict"],
        "tiles": [tile("TPR", r["tpr"], r["tpr_interval"],
                       f"from {labels['correct']} marked Correct"),
                  tile("TNR", r["tnr"], r["tnr_interval"],
                       f"from {labels['wrong']} marked Wrong"),
                  tile("kappa", r["kappa"], None, f"from {n} labels")],
        "notes": [counted] + [x for x in (pass_rate_line(r), CORRECTED) if x],
        "judge": judge_lines,
        "next": _next(r),
        "saved": f"Saved in {FOLDER}/ in your project folder; this page is result.html there.",
    }


def result_html(r: dict, back: str | None = None) -> str:
    return result_page(page_content(r), back)


def page_template() -> str:
    return START_PAGE


def compute(ws: Workspace, session: StartSession) -> dict:
    data = ws.data()
    groups = {q["id"]: q["group"] for q in data["queue"]}
    counted = {"pass": [0, 0], "fail": [0, 0]}  # labeled, Correct
    for item in session.items:
        if item["label"]:
            g = counted[groups[item["id"]]]
            g[0] += 1
            g[1] += item["label"] == "pass"
    r = describe(weighted.corrected(data["pool"]["pass"], data["pool"]["fail"],
                                    *counted["pass"], *counted["fail"]))
    r.update(skipped=session.counts()["skipped"], made_at=utc_now(),
             judgekeeper_version=__version__, fingerprint=data["fingerprint"],
             judge={"name": data["judge"], "tool": data["tool"], "metric": data["metric"],
                    "results_files": data["results_files"],
                    "results_date": data.get("results_date")})
    return r


def save_result(ws: Workspace, session: StartSession, say) -> dict:
    """Make a result from the labels so far: anchors, result.json and result.html (the last
    result moves to history/), and say it in the terminal."""
    r = compute(ws, session)
    anchors = [{"id": i["id"], "input": session.raw[i["id"]].get("input", ""),
                "output": session.raw[i["id"]].get("output", ""), "human_label": i["label"]}
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


def run_labeling(found, port: int, open_browser: bool, say) -> int:
    """Save the pool of `found`, then serve the labeling page for it."""
    return serve_workspace(prepare(found, say), port, open_browser, say)


def serve_workspace(ws: Workspace, port: int, open_browser: bool, say) -> int:
    """Serve the labeling page until the last answer, Ctrl-C or 2 hours idle."""
    session = StartSession(ws)
    made: list[bool] = []
    server = make_server(session, port, result=result_maker(ws, say, made),
                         page=page_template())
    print(f"Labeling page: {server.url}")  # not scrubbed: the token must stay whole
    say("Every click is saved. Press Ctrl-C here to stop; run judgekeeper start to continue.")
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
        say(f"Stopped. {summary['n_labeled']} labeled; run judgekeeper start to continue.")
    return 0
