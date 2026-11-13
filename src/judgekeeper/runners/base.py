"""Runner interface: `judge(item) -> Judgment`."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from judgekeeper.fingerprint import JudgeFingerprint


@dataclass
class Judgment:
    """One judge decision on one item.

    For pairwise items `verdict` comes from the AB ordering (output_a shown first) and
    `swapped` holds the BA ordering. Both verdicts are expressed in the item's original
    labels, so `swapped.verdict == "A"` means the judge preferred output_a even when it was
    shown second. `snapshot` is the model id the results name for this judgment. A grade that
    is no decision ("error", "n/a" and the like, normalise.NO_DECISION) has verdict "error"
    and `error` set.
    """

    verdict: str | None
    raw_score: float | None
    rationale: str
    swapped: Judgment | None = None
    snapshot: str | None = None
    error: str | None = None


class Runner(Protocol):
    @property
    def fingerprint(self) -> JudgeFingerprint: ...

    def judge(self, item: dict) -> Judgment: ...
