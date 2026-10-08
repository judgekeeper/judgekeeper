"""How many labels a check needs: one set of targets for every command.

`start` (its result and the line under the labeling page's meters), `check`, `validate` and
`init` all use these. The two kinds of label are the answers marked Correct and Wrong in
`start`, the human pass and fail (or A and B) labels in `check` and `validate`.

- A rough check: at least ROUGH of each kind.
- A reliable result: at least RELIABLE of each kind, and both the TPR range and the TNR range
  no wider than MAX_WIDTH (from the low end to the high end). The TPR range is about the
  answers marked Correct, the TNR range about those marked Wrong.

Why 0.30: about what 25 + 25 gives when the judge agrees with the person about 85% of the
time and passes half the answers, so such checks are reliable at 25 of each as before; when
the judge passes most answers, its TNR range stays wide for longer, and the result is not
called reliable until it is really that narrow (docs/examples/coverage/coverage.md).
"""

from __future__ import annotations

ROUGH = 15
RELIABLE = 25
MAX_WIDTH = 0.30
EPS = 1e-9
START_NAMES = ("answers you marked Correct", "answers you marked Wrong")


def _width(interval) -> float | None:
    if not interval or interval[0] is None or interval[1] is None:
        return None
    return interval[1] - interval[0]


def check(correct: int, wrong: int, tpr_interval, tnr_interval) -> dict:
    """{"check": "too_few" | "rough" | "reliable", "wide": {"tpr" | "tnr": width or None}}.

    `wide` names a range that keeps a check with RELIABLE of each from being reliable: wider
    than MAX_WIDTH, or unknown (None). It is empty below RELIABLE of each."""
    least = min(correct, wrong)
    if least < ROUGH:
        return {"check": "too_few", "wide": {}}
    if least < RELIABLE:
        return {"check": "rough", "wide": {}}
    wide = {}
    for key, interval in (("tpr", tpr_interval), ("tnr", tnr_interval)):
        width = _width(interval)
        if width is None or width > MAX_WIDTH + EPS:
            wide[key] = width
    return {"check": "rough" if wide else "reliable", "wide": wide}


def line(result: dict, names: tuple[str, str] = START_NAMES) -> str:
    """How far along a check is and what to do, in one or two sentences."""
    if result["check"] == "too_few":
        return f"A rough check needs {ROUGH} of each."
    if result["check"] == "reliable":
        return "Reliable result ready."
    wide = result["wide"]
    if not wide:
        return f"Rough check ready. A reliable result needs {RELIABLE} of each."
    sides = [names[0] if key == "tpr" else names[1] for key in wide]
    if None in wide.values():
        unknown = [names[0] if key == "tpr" else names[1] for key, w in wide.items() if w is None]
        return (f"Not reliable yet: the range for {' and '.join(unknown)} is not known yet. "
                "Label more answers.")
    widths = " and ".join(f"{w:.2f}" for w in wide.values())
    if len(sides) == 1:
        return (f"Not reliable yet: the range for {sides[0]} is still {widths} wide. Label "
                "more answers to narrow it.")
    return (f"Not reliable yet: the ranges for {sides[0]} and {sides[1]} are still {widths} "
            "wide. Label more answers to narrow them.")
