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
    shown second. `snapshot` is the model id the provider reported serving for this call.
    A custom judge that raised or returned nothing usable has verdict "error" and `error` set.
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
