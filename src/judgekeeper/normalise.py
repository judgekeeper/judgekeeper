"""Turn whatever a judge returned into a verdict. One function for every import path.

Accepted shapes: a bool; a string looked up case-insensitively in a label map (the defaults
below, plus a leading PASS/FAIL token, plus anything from --label-map); a number, which needs a
--pass-if rule such as `score>=0.5`; a `(verdict, reason)` tuple; a dict with the verdict under
`verdict`/`pass`/`passed`/`label`/`score` and the reason under
`reason`/`rationale`/`explanation`/`comment`.

Two failure modes, kept apart on purpose:

- nothing usable (None, an empty string, NaN, a dict with no verdict, a wrong type) is a judge
  error: verdict "error", excluded from agreement metrics and counted in the report. It is
  never turned into a fail.
- a value that looks like a verdict but is not in the map (e.g. "good"), or a number with no
  --pass-if rule, is UnmappedValue: the caller collects them and stops with a usage error that
  lists them. judgekeeper never guesses what "good" means.
"""

from __future__ import annotations

import math
import operator
import re
from dataclasses import dataclass

from judgekeeper.anchors import LABELS, PAIRWISE, SINGLE

ERROR = "error"

DEFAULT_LABEL_MAP = {
    "pass": "pass", "fail": "fail",
    "true": "pass", "false": "fail",
    "yes": "pass", "no": "fail",
    "correct": "pass", "incorrect": "fail",
    "1": "pass", "0": "fail",
}
DEFAULT_PAIRWISE_MAP = {"a": "A", "b": "B"}

VERDICT_KEYS = ("verdict", "pass", "passed", "label", "score")
REASON_KEYS = ("reason", "rationale", "explanation", "comment")

_LEADING = re.compile(r"\A\s*(pass|fail)\b", re.IGNORECASE)
_RULE = re.compile(r"\A\s*([A-Za-z_]\w*)?\s*(>=|<=|==|>|<)\s*(-?\d+(?:\.\d+)?|-?\.\d+)\s*\Z")
_OPS = {">=": operator.ge, "<=": operator.le, ">": operator.gt, "<": operator.lt,
        "==": operator.eq}
_MAX_LISTED = 20
# Double quotes: they work in every shell, cmd.exe included.
PASS_IF_EXAMPLE = '--pass-if "score>=0.5"'


class NormaliseError(Exception):
    """A usage problem: unmapped values, a bad --pass-if rule or --label-map."""


class UnmappedValue(Exception):
    """A value that looks like a verdict but is not in the label map."""

    def __init__(self, value, hint: str = ""):
        self.value = value
        self.hint = hint
        super().__init__(f"unmapped value {value!r}" + (f": {hint}" if hint else ""))


@dataclass(frozen=True)
class Normalised:
    verdict: str  # a label of the anchor kind, or ERROR
    rationale: str = ""
    raw_score: float | None = None
    error: str | None = None


@dataclass(frozen=True)
class PassIf:
    text: str
    name: str | None
    op: str
    threshold: float

    def __call__(self, x: float) -> bool:
        return _OPS[self.op](x, self.threshold)


def parse_pass_if(text: str) -> PassIf:
    m = _RULE.match(text or "")
    if not m:
        raise NormaliseError(f"--pass-if {text!r} is not a rule like score>=0.5 "
                             "(operators: >=, >, <=, <, ==)")
    return PassIf(text=text.strip(), name=m.group(1), op=m.group(2), threshold=float(m.group(3)))


def parse_label_map(text: str | dict | None, kind: str = SINGLE) -> dict[str, str]:
    """`"good=pass,bad=fail"` (or a dict) to {lowercased value: label}."""
    if not text:
        return {}
    labels = {lab.lower(): lab for lab in LABELS[kind]}
    pairs = text.items() if isinstance(text, dict) else (
        part.split("=", 1) if "=" in part else (part, None)
        for part in (p.strip() for p in text.split(",")) if part
    )
    out = {}
    for key, value in pairs:
        key = str(key).strip().lower()
        if not key or value is None:
            raise NormaliseError(f"--label-map entries look like value=label, got {key!r}")
        label = labels.get(str(value).strip().lower())
        if label is None:
            raise NormaliseError(f"--label-map maps {key!r} to {value!r}; labels for "
                                 f"{kind} items are {', '.join(LABELS[kind])}")
        out[key] = label
    return out


def _is_number(x) -> bool:
    return isinstance(x, int | float) and not isinstance(x, bool)


def _error(msg: str, rationale: str = "") -> Normalised:
    return Normalised(verdict=ERROR, rationale=rationale, error=msg)


class Normaliser:
    def __init__(self, kind: str = SINGLE, pass_if: str | PassIf | None = None,
                 label_map: dict | str | None = None):
        if kind not in LABELS:
            raise NormaliseError(f"unknown item kind {kind!r}")
        self.kind = kind
        if isinstance(pass_if, str):
            pass_if = parse_pass_if(pass_if)
        if pass_if is not None and kind == PAIRWISE:
            raise NormaliseError("--pass-if applies to single-output items (pass/fail), "
                                 "not pairwise A/B verdicts")
        self.pass_if = pass_if
        extra = parse_label_map(label_map, kind)
        base = DEFAULT_PAIRWISE_MAP if kind == PAIRWISE else DEFAULT_LABEL_MAP
        self.label_map = {**base, **{k.lower(): v for k, v in extra.items()}}

    def describe(self) -> dict:
        """What goes into the run header, so the report is reproducible."""
        return {"kind": self.kind, "pass_if": self.pass_if.text if self.pass_if else None,
                "label_map": dict(self.label_map)}

    def __call__(self, raw) -> Normalised:
        if isinstance(raw, tuple | list):
            if len(raw) != 2:
                return _error(f"expected (verdict, reason), got a sequence of {len(raw)}")
            res = self._value(raw[0])
            reason = "" if raw[1] is None else str(raw[1])
            return Normalised(res.verdict, reason or res.rationale, res.raw_score, res.error)
        if isinstance(raw, dict):
            return self._dict(raw)
        return self._value(raw)

    def _dict(self, d: dict) -> Normalised:
        reason = next((str(d[k]) for k in REASON_KEYS if d.get(k) is not None), "")
        if self.pass_if is not None and self.pass_if.name in d:
            res = self._value(d[self.pass_if.name])
        else:
            key = next((k for k in VERDICT_KEYS if k in d), None)
            if key is None:
                return _error(f"no verdict key ({', '.join(VERDICT_KEYS)}) in {sorted(d)}",
                              reason)
            res = self._value(d[key])
        return Normalised(res.verdict, reason or res.rationale, res.raw_score, res.error)

    def _value(self, x) -> Normalised:
        if x is None:
            return _error("judge returned nothing")
        if isinstance(x, bool):
            if self.kind == PAIRWISE:
                raise UnmappedValue(x, "pairwise verdicts are A or B")
            return Normalised("pass" if x else "fail")
        if _is_number(x):
            return self._number(float(x), x)
        if not isinstance(x, str):
            return _error(f"cannot read a verdict from a {type(x).__name__}")
        text = x.strip()
        if not text:
            return _error("judge returned an empty string")
        if self.pass_if is not None:
            try:
                return self._number(float(text), text)
            except ValueError:
                pass
        label = self.label_map.get(text.lower())
        if label is not None:
            return Normalised(label)
        if self.kind == SINGLE:
            m = _LEADING.match(text)
            if m:
                return Normalised(m.group(1).lower(), rationale=x)
        raise UnmappedValue(text, "add it with --label-map value=label")

    def _number(self, f: float, original) -> Normalised:
        if math.isnan(f):
            return _error("judge returned NaN")
        if self.pass_if is None:
            label = self.label_map.get(str(original).strip().lower())
            if label is not None:
                return Normalised(label)
            raise UnmappedValue(original, f"numbers need a rule such as {PASS_IF_EXAMPLE}")
        return Normalised("pass" if self.pass_if(f) else "fail", raw_score=f)


def _numeric(v) -> bool:
    """A number, or text that reads as one (every value of a CSV is text)."""
    if _is_number(v):
        return True
    if not isinstance(v, str):
        return False
    try:
        float(v)
    except ValueError:
        return False
    return True


def unmapped_error(values, what: str = "verdict", pass_if: bool = True) -> NormaliseError:
    """One usage error listing every unmapped value, and what to do about them.

    Words are mapped with --label-map. Numbers need a --pass-if rule; `pass_if=False` is for
    human labels and pairwise verdicts, which take no such rule, so numbers there are mapped
    like words.
    """
    seen = list(dict.fromkeys(values))
    shown = ", ".join(repr(v) for v in seen[:_MAX_LISTED])
    more = f" and {len(seen) - _MAX_LISTED} more" if len(seen) > _MAX_LISTED else ""
    listed = f"unmapped {what} values: {shown}{more}."
    numbers = [v for v in seen if pass_if and _numeric(v)]
    words = [v for v in seen if not (pass_if and _numeric(v))]
    if numbers and not words:
        return NormaliseError(f"{listed} These are numbers: say which scores pass with "
                              f"--pass-if, e.g. {PASS_IF_EXAMPLE}")
    hint = f"; numbers need --pass-if, e.g. {PASS_IF_EXAMPLE}" if numbers else ""
    return NormaliseError(
        f"{listed} judgekeeper does not guess: map them with --label-map, e.g. --label-map "
        f"\"{_example(words)}\"{hint}"
    )


def _example(seen: list) -> str:
    words = [str(v) for v in seen if isinstance(v, str)][:2] or ["good", "bad"]
    return ",".join(f"{w}={lab}" for w, lab in zip(words, ("pass", "fail")))


def normalise_all(norm: Normaliser, values, what: str = "verdict",
                  pass_if: bool = True) -> list[Normalised]:
    """Normalise every value; raise one NormaliseError listing every unmapped value."""
    out, unmapped = [], []
    for v in values:
        try:
            out.append(norm(v))
        except UnmappedValue as e:
            unmapped.append(e.value)
    if unmapped:
        raise unmapped_error(unmapped, what, pass_if=pass_if)
    return out
