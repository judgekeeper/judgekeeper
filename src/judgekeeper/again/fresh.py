"""After asking the judge again: the numbers, the saved files and what is said.

A tool's `run` returns `Fresh`: each counted answer's fresh verdicts (one per time asked), the
answers not counted and why, and the fingerprint of the fresh judgments. `finish` then:

- writes `.judgekeeper/again/<stamp>/judge-again-<n>.jsonl`, one run file per time asked,
  every line with the full fingerprint plus the tool and its version, the names of setting
  variables that were set, and whether this was exactly the judge or a close copy (and why).
  Answers not counted are error lines, so the file lists them;
- works out steadiness (how often the judge changed its verdict on the same answer), agreement
  today (the person's labels against the first fresh run, weighted by the saved groups) and how
  often the first fresh verdict matched the saved one (weighted.general, weighted.steadiness);
- adds an `again` block to result.json (an earlier one moves to history/) and redraws
  result.html. The main result, the person's labels and their numbers do not change.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from judgekeeper import weighted
from judgekeeper.again import CLOSE
from judgekeeper.fingerprint import JudgeFingerprint, utc_now
from judgekeeper.judgments import judgment_to_record, write_run
from judgekeeper.metrics import ERROR
from judgekeeper.runners.base import Judgment
from judgekeeper.textio import write_replacing

TIMES_WORDS = {1: "once", 2: "twice", 3: "three times", 4: "four times", 5: "five times"}
NOT_COUNTED = {  # key: (one answer, several answers)
    "grading prompt differs": (
        "its grading prompt differs from the saved one, so it was not the same judge input",
        ("their grading prompts differ from the saved ones, so they were not the same judge "
         "input")),
    "no clear verdict": ("the judge gave no clear decision", "the judge gave no clear decision"),
    "error": ("the judge's tool gave an error for it", "the judge's tool gave an error for them"),
    "missing": ("it is missing from the tool's output",
                "they are missing from the tool's output"),
}
MATCH_FLOOR = 0.9


@dataclass
class Fresh:
    folder: Path  # .judgekeeper/again/<stamp>/
    verdicts: dict[str, list[str]] = field(default_factory=dict)  # counted answers only
    scores: dict[str, list] = field(default_factory=dict)
    reasons: dict[str, list[str]] = field(default_factory=dict)
    not_counted: dict[str, str] = field(default_factory=dict)  # id -> a NOT_COUNTED key
    fingerprint: dict = field(default_factory=dict)
    source: dict = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


class AgainError(Exception):
    """The judge's tool did not finish: nothing was counted."""


def new_folder(ws) -> Path:
    stamp = utc_now().replace(":", "-")
    folder = ws.dir / "again" / stamp
    n = 2
    while folder.exists():
        folder = ws.dir / "again" / f"{stamp}-{n}"
        n += 1
    folder.mkdir(parents=True)
    return folder


def _share(value) -> str:
    return "an unknown share" if value is None else f"about {value:.0%}"


def _pct(value) -> str:
    return "unknown" if value is None else f"{value:.0%}"


def write_files(ws, plan, fresh: Fresh, prefix: str = "judge-again",
                metric: str | None = None) -> list[Path]:
    """One run file per time asked (`<prefix>-<n>.jsonl`), every line with the full
    fingerprint. `metric` names the judge when it is not the saved check's (a new judge)."""
    data = ws.data()
    extras = {"tool": plan.tool, "tool_version": plan.tool_version,
              "settings": list(plan.settings),
              "judge_copy": "close copy" if plan.status == CLOSE else "exact",
              "judge_copy_why": [plan.why] if plan.status == CLOSE else []}
    fp = JudgeFingerprint.from_dict(fresh.fingerprint)
    paths = []
    ids = [a["id"] for a in plan.payload_answers()]
    for t in range(plan.times):
        records = []
        for item_id in ids:
            if item_id in fresh.verdicts:
                j = Judgment(verdict=fresh.verdicts[item_id][t],
                             raw_score=(fresh.scores.get(item_id) or [None] * plan.times)[t],
                             rationale=(fresh.reasons.get(item_id) or [""] * plan.times)[t])
            else:
                why = fresh.not_counted.get(item_id, "missing")
                j = Judgment(verdict=ERROR, raw_score=None, rationale="", error=why)
            rec = judgment_to_record(item_id, j, fp)
            rec["fingerprint"].update(extras)
            records.append(rec)
        path = fresh.folder / f"{prefix}-{t + 1}.jsonl"
        write_run(path, t + 1, data["pool_sha256"], fp, records,
                  source={**fresh.source, "metric": metric or data["metric"]})
        paths.append(path)
    return paths


def numbers(ws, plan, fresh: Fresh) -> dict:
    """The `again` block of result.json."""
    from judgekeeper.start_again import judge_change

    data = ws.data()
    last = json.loads(ws.result_json.read_text(encoding="utf-8"))
    n_pass, n_fail = data["pool"]["pass"], data["pool"]["fail"]
    counted = [a for a in plan.payload_answers() if a["id"] in fresh.verdicts]
    items = [(a["verdict"], a["label"], fresh.verdicts[a["id"]][0]) for a in counted]
    today = weighted.general(items, n_pass, n_fail)
    steady = None
    if plan.times >= 2:
        groups = {g: (sum(a["verdict"] == g for a in counted),
                      sum(a["verdict"] == g and len(set(fresh.verdicts[a["id"]])) > 1
                          for a in counted)) for g in ("pass", "fail")}
        steady = weighted.steadiness(groups, n_pass, n_fail)
    matches = (sum(fresh.verdicts[a["id"]][0] == a["verdict"] for a in counted) / len(counted)
               if counted else None)
    change = judge_change(data["fingerprint"], fresh.fingerprint) if fresh.fingerprint else None
    return {
        "made_at": utc_now(), "folder": f"{ws.dir.name}/again/{fresh.folder.name}",
        "tool": plan.tool, "tool_version": plan.tool_version, "judge": plan.judge,
        "status": plan.status, "why": plan.why, "times": plan.times,
        "asked": plan.answers, "counted": len(counted),
        "not_counted": [{"id": i, "why": w} for i, w in fresh.not_counted.items()],
        "steadiness": steady,
        "today": {k: today[k] for k in ("tpr", "tpr_interval", "tnr", "tnr_interval", "kappa",
                                        "interval_methods", "level", "draws", "seed")},
        "before": {"tpr": last.get("tpr"), "tnr": last.get("tnr")},
        "matches_saved": matches,
        "matches_count": sum(fresh.verdicts[a["id"]][0] == a["verdict"] for a in counted),
        "judge_change": change, "notes": list(fresh.notes),
    }


def again_lines(block: dict) -> list[str]:
    """What is said after asking again. A close copy says why once, first, and each number
    line ends "(close copy)"."""
    close = block["status"] == CLOSE
    tail = " (close copy)" if close else ""
    n, times = block["counted"], block["times"]
    lines = [f"This was a close copy of your judge: {block['why']}."] if close else []
    steady = block.get("steadiness")
    if times < 2 or steady is None:
        lines.append(f"Asked once more: ask at least twice to see whether it changes its "
                     f"mind.{tail}")
    else:
        lo, hi = steady["interval"]
        across = (f" Across all your answers that is {_share(steady['rate'])} ({_pct(lo)} to "
                  f"{_pct(hi)})." if steady["rate"] is not None else "")
        lines.append(f"Asked {TIMES_WORDS.get(times, f'{times} times')} more, your judge "
                     f"changed its mind on {steady['changed']} of your {n} answers."
                     f"{across}{tail}")
    today, before = block["today"], block["before"]
    for key, said in (("tpr", "Pass"), ("tnr", "Fail")):
        lines.append(f"When you said {said}, your judge also said {said} {_share(before[key])} "
                     f"of the time before and {_share(today[key])} now.{tail}")
    if block["matches_saved"] is not None:
        lines.append(f"Its first new decision matched the saved one on {block['matches_count']} "
                     f"of {n} answers ({_pct(block['matches_saved'])}).{tail}")
        if block["matches_saved"] < MATCH_FLOOR:
            change = block.get("judge_change")
            lines.append("Your judge answers differently than when your eval ran. Did its "
                         "model or prompt change?"
                         + (f" Its fingerprint shows: {change}." if change else ""))
    counts: dict[str, int] = {}
    for item in block["not_counted"]:
        counts[item["why"]] = counts.get(item["why"], 0) + 1
    for why, k in counts.items():
        one, many = NOT_COUNTED.get(why, (why, why))
        lines.append(f"1 answer was not counted: {one}." if k == 1 else
                     f"{k} answers were not counted: {many}.")
    lines += list(block.get("notes") or [])
    return lines


def save(ws, block: dict) -> None:
    """Put the block in result.json (an earlier one to history/) and redraw result.html."""
    from judgekeeper.start_label import _scrubbed, _write_json, result_html

    r = json.loads(ws.result_json.read_text(encoding="utf-8"))
    if r.get("again"):
        ws.history.mkdir(exist_ok=True)
        stamp = (r["again"].get("made_at") or utc_now()).replace(":", "-")
        target = ws.history / f"again-{stamp}.json"
        n = 2
        while target.exists():
            target = ws.history / f"again-{stamp}-{n}.json"
            n += 1
        _write_json(target, r["again"])
    r["again"] = block
    _write_json(ws.result_json, r)
    write_replacing(ws.result_html, result_html(_scrubbed(r)))


def finish(ws, plan, fresh: Fresh, talk) -> dict:
    write_files(ws, plan, fresh)
    block = numbers(ws, plan, fresh)
    from judgekeeper.start_label import _write_json

    _write_json(fresh.folder / "again.json", block)
    save(ws, block)
    talk.say()
    for line in again_lines(block):
        talk.say(line)
    talk.say(f"Saved in {block['folder']}/. Your first marks and your result stay as they "
             "were.")
    return block
