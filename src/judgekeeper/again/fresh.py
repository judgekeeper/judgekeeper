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
  report.html. The main result, the person's labels and their numbers do not change.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from judgekeeper.again import CLOSE
from judgekeeper.fingerprint import JudgeFingerprint, utc_now
from judgekeeper.judgments import judgment_to_record, write_run
from judgekeeper.metrics import ERROR
from judgekeeper.runners.base import Judgment
from judgekeeper.textio import PRIVATE_FOLDER, make_private

NOT_COUNTED = {  # key: (one answer, several answers)
    "grading prompt differs": (
        ("its grading prompt differs from the saved one, so the LLM-as-a-judge did not get the "
         "same input"),
        ("their grading prompts differ from the saved ones, so the LLM-as-a-judge did not get the "
         "same input")),
    "no clear verdict": ("the LLM-as-a-judge gave no clear decision",
                         "the LLM-as-a-judge gave no clear decision"),
    "error": ("the LLM-as-a-judge's tool gave an error for it",
              "the LLM-as-a-judge's tool gave an error for them"),
    "judge call failed": ("the LLM-as-a-judge's call for it failed",
                          "the LLM-as-a-judge's calls for them failed"),
    "missing": ("it is missing from the tool's output",
                "they are missing from the tool's output"),
}


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
    models: list = field(default_factory=list)  # the model of each call, where the tool says

    def models_used(self) -> set[str]:
        """The models the counted calls used: each call's, else the fingerprint's."""
        used = self.models or [self.fingerprint.get("model")]
        return {m for m in used if isinstance(m, str) and m}


class AgainError(Exception):
    """The judge's tool did not finish: nothing was counted."""


def new_folder(ws) -> Path:
    stamp = utc_now().replace(":", "-")
    folder = ws.dir / "again" / stamp
    n = 2
    while folder.exists():
        folder = ws.dir / "again" / f"{stamp}-{n}"
        n += 1
    make_private(folder.parent)
    folder.mkdir(mode=PRIVATE_FOLDER)
    return folder


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


