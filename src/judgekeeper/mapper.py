"""Read a results file saved in a project's own format: list its nested paths and guess how to
read it. `judgekeeper setup` shows the guess, asks only what it cannot tell, and saves the map
in judgekeeper.toml; readers/mapped.py then reads the file with it. Standard library only.

A file is a list of units: the lines of a JSONL file, the rows of a CSV, or the one document
of a JSON file. In a unit, `each` is the path to the items (one item holds one judged
answer, or one per side), and the other paths are relative to an item:

    each   = "cases[]"                        the items: every element of the list `cases`
    input  = "prompt"
    output = "{side}.output"                  sides ["A", "B"]: one answer per side
    score  = "{side}.scores.{judge}.score"    judges ["Safe wording", "Plain language"]
    reason = "{side}.scores.{judge}.reason"

Paths are keys joined by dots; `[]` after a key means every element of that list; a key that
is not plain letters, digits, `_` or `-` is written as a JSON string (`"User Question"`).

The guess goes by key names first (input, prompt, question; output, answer, response;
score, verdict, label, grade; reason, explanation) and by value types after that. A guess by
type alone is "unsure": `setup` asks one confirm line. What one item is, and which judge to
check when an item holds several, are told by the file's shape (the list that holds the
answers; the keys that differ between two answers or two scores).
"""

from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from judgekeeper.textio import read_utf8

SIDE, JUDGE = "{side}", "{judge}"
CRITERION = "<criterion>"
EXAMPLE_WIDTH = 60
SAMPLE_UNITS = 50  # units looked at for a guess
MAX_DEPTH = 8
MAX_VERDICT = 20  # characters: a longer text is not a verdict

INPUT_WORDS = ("input", "prompt", "question", "query", "instruction", "message", "request")
OUTPUT_WORDS = ("output", "outputs", "answer", "answers", "response", "responses",
                "completion", "reply", "generation")
SCORE_WORDS = ("score", "verdict", "passed", "pass", "label", "success", "grade", "rating",
               "judgment", "judgement")
REASON_WORDS = ("reason", "reasoning", "explanation", "rationale", "comment", "feedback",
                "justification", "why")
CRITERIA_WORDS = ("scores", "metrics", "criteria", "judges", "evaluations", "grades",
                  "ratings", "results")
ID_KEYS = ("id", "case_id", "item_id", "example_id", "sample_id", "test_id", "uid")
MODEL_KEYS = ("judge_model", "evaluation_model", "evaluator_model", "grader_model", "model",
              "judge", "evaluator", "grader")

_PLAIN = re.compile(r"[A-Za-z0-9_\-]+|\{side\}|\{judge\}")
_BARE = re.compile(r"[^.\[\]\"]+")
_WORD = re.compile(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+")
_NUMBER = re.compile(r"\s*[-+]?(\d+(\.\d*)?|\.\d+)([eE][-+]?\d+)?\s*")


class MapError(Exception):
    """The file cannot be mapped; the message says why, in plain words."""


class Missing(Exception):
    """A path is not in the data."""


# Paths ------------------------------------------------------------------------------------

def write(segments) -> str:
    """[(key, every element)] as path text."""
    parts = []
    for key, many in segments:
        text = key if _PLAIN.fullmatch(key) else json.dumps(key, ensure_ascii=False)
        parts.append(text + ("[]" if many else ""))
    return ".".join(parts)


def parse(text: str) -> list[tuple[str, bool]]:
    """Path text as [(key, every element)]; "" is the unit itself."""
    out, i = [], 0
    decoder = json.JSONDecoder()
    while i < len(text):
        if text[i] == '"':
            key, i = decoder.raw_decode(text, i)
        else:
            m = _BARE.match(text, i)
            if m is None:
                raise MapError(f"cannot read the path {text!r}")
            key, i = m.group(), m.end()
        many = text.startswith("[]", i)
        i += 2 if many else 0
        out.append((key, many))
        if i < len(text):
            if text[i] != ".":
                raise MapError(f"cannot read the path {text!r}")
            i += 1
    return out


def shown(path: str) -> str:
    """A path for people: the placeholders as <side> and <criterion>."""
    return path.replace(SIDE, "<side>").replace(JUDGE, "<criterion>")


def _words(key: str) -> set[str]:
    return {w.lower() for w in _WORD.findall(str(key))}


def _is(key: str, words) -> bool:
    return bool(_words(key) & set(words))


# Loading and walking ----------------------------------------------------------------------

def load_numbered(path: str | Path) -> list[tuple[int, object]]:
    """[(line number, unit)]: JSONL lines, CSV rows (all values text), or a JSON document
    (its elements, when it is a list). Lines that are not JSON are skipped."""
    path = Path(path)
    suffix = path.suffix.lower()
    text = read_utf8(path, MapError).removeprefix("﻿")
    if suffix in (".csv", ".tsv"):
        from judgekeeper.table import _delimiter

        reader = csv.DictReader(io.StringIO(text, newline=""), delimiter=_delimiter(text, suffix))
        return [(reader.line_num, {k: v for k, v in row.items() if k is not None})
                for row in reader]
    if suffix == ".json":
        try:
            doc = json.loads(text)
        except ValueError as e:
            raise MapError(f"{path.name} is not JSON ({e})") from None
        return list(enumerate(doc, 1)) if isinstance(doc, list) else [(1, doc)]
    units = []
    for n, line in enumerate(text.splitlines(), 1):
        if line.strip():
            try:
                units.append((n, json.loads(line)))
            except ValueError:
                continue
    return units


def load(path: str | Path) -> list:
    return [unit for _, unit in load_numbered(path)]


def items(unit, each: str) -> list[tuple[dict, list[dict]]]:
    """[(item, its ancestors, outermost first)] at `each` in `unit`. Missing if not there."""
    found = [(unit, [])]
    for key, many in parse(each):
        nxt = []
        for obj, up in found:
            if not isinstance(obj, dict) or key not in obj:
                raise Missing(key)
            value = obj[key]
            if many:
                if not isinstance(value, list):
                    raise Missing(key)
                nxt += [(v, [*up, obj]) for v in value]
            else:
                nxt.append((value, [*up, obj]))
        found = nxt
    return [(obj, up) for obj, up in found if isinstance(obj, dict)]


def get(obj, path: str, side: str | None = None, judge: str | None = None):
    """The value at `path` in `obj`, with the placeholders filled. Missing if not there."""
    for key, _ in parse(path):
        key = side if key == SIDE else judge if key == JUDGE else key
        if not isinstance(obj, dict) or key is None or key not in obj:
            raise Missing(path)
        obj = obj[key]
    return obj


def _leaves(obj, prefix=(), depth=0):
    """[(segments, value)] of every leaf in a dict, not going into lists."""
    if depth > MAX_DEPTH:
        return
    for key, value in obj.items():
        seg = (*prefix, str(key))
        if isinstance(value, dict) and value:
            yield from _leaves(value, seg, depth + 1)
        else:
            yield seg, value


def number(value) -> float | None:
    """A score as a number: a number, or a number written as text; else None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return value
    if isinstance(value, str) and _NUMBER.fullmatch(value):
        f = float(value)
        return int(f) if f.is_integer() and "." not in value else f
    return None


def _example(value) -> str:
    text = json.dumps(value, ensure_ascii=False)
    return text[:EXAMPLE_WIDTH - 1] + "…" if len(text) > EXAMPLE_WIDTH else text


def listing(unit, judges=()) -> list[tuple[str, str]]:
    """[(path, example value)] of every leaf in a unit: the first element of each list,
    and of the keys in `judges` only the first, shown as <criterion>."""
    out, seen = [], set()

    def walk(obj, prefix, depth):
        if depth > MAX_DEPTH:
            return
        criterion_shown = False
        for key, value in obj.items():
            key = str(key)
            if key in judges:
                if criterion_shown:
                    continue
                criterion_shown, key = True, CRITERION
            seg = [*prefix, (key, False)]
            if isinstance(value, dict) and value:
                walk(value, seg, depth + 1)
            elif isinstance(value, list) and value and all(isinstance(v, dict) for v in value):
                walk(value[0], [*prefix, (key, True)], depth + 1)
            else:
                text = write(seg).replace(json.dumps(CRITERION), CRITERION)
                if text not in seen:
                    seen.add(text)
                    out.append((text, _example(value)))

    if isinstance(unit, dict):
        walk(unit, [], 0)
    return out


# The guess --------------------------------------------------------------------------------

@dataclass
class Guess:
    each: str
    input: str
    output: str
    score: str
    reason: str | None = None
    id: str | None = None
    sides: list[str] = field(default_factory=list)
    judges: list[str] = field(default_factory=list)
    kind: str = "score"  # "score" (a number and a pass mark) or "verdict" (pass/fail values)
    pass_mark: float | None = None
    pass_mark_sure: bool = True
    model_key: str | None = None
    model: str | None = None  # the model's name in the first item, for showing
    unsure: list[str] = field(default_factory=list)  # roles guessed from value types only

    def judge_name(self) -> str:
        """The judge's name when the file holds one judge without a name of its own."""
        return parse(self.score)[-1][0]

    def to_map(self) -> dict:
        """What judgekeeper.toml keeps under [start.map]."""
        out = {"each": self.each, "id": self.id, "input": self.input, "output": self.output,
               "sides": list(self.sides), "score": self.score, "reason": self.reason,
               "kind": self.kind, "judges": list(self.judges), "model_key": self.model_key}
        return {k: v for k, v in out.items() if v not in (None, [])}


def _item_lists(unit, prefix=(), depth=0):
    """Every path (with [] marks) in `unit` whose elements are dicts, outermost first."""
    if depth > MAX_DEPTH or not isinstance(unit, dict):
        return
    for key, value in unit.items():
        if isinstance(value, list) and value and all(isinstance(v, dict) for v in value):
            seg = (*prefix, (str(key), True))
            yield seg
            for element in value[:5]:
                yield from _item_lists(element, seg, depth + 1)
        elif isinstance(value, dict):
            yield from _item_lists(value, (*prefix, (str(key), False)), depth + 1)


def _outputs(item: dict) -> list[tuple]:
    return [seg for seg, v in _leaves(item) if isinstance(v, str)
            and any(_is(k, OUTPUT_WORDS) for k in seg) and not _is(seg[-1], REASON_WORDS)
            and not any(_is(k, INPUT_WORDS) for k in seg)]


def _differ_at(paths: list[tuple]) -> int | None:
    """The one index where paths of the same length differ, else None."""
    if len({len(p) for p in paths}) != 1:
        return None
    differ = [i for i in range(len(paths[0])) if len({p[i] for p in paths}) > 1]
    return differ[0] if len(differ) == 1 else None


def _fill(seg: tuple, at: int, placeholder: str) -> tuple:
    return (*seg[:at], placeholder, *seg[at + 1:])


def _as_path(seg) -> str:
    return write([(k, False) for k in seg])


def _texts(item: dict) -> list[tuple]:
    """Top-level text values that no key name places: candidates for the answer."""
    return [seg for seg, v in _leaves(item) if len(seg) == 1 and isinstance(v, str)
            and not _is(seg[0], INPUT_WORDS + SCORE_WORDS + REASON_WORDS)
            and seg[0].lower() not in ID_KEYS + MODEL_KEYS]


def _choose_each(units) -> str:
    candidates: list = []
    for unit in units:
        if isinstance(unit, dict) and _outputs(unit):
            candidates.append(())
        for seg in _item_lists(unit):
            try:
                found = items(unit, write(seg))
            except Missing:
                continue
            if any(_outputs(item) for item, _ in found):
                candidates.append(seg)
        if candidates:
            break
    if not candidates and _texts(units[0]):
        return ""  # flat, with an answer that no key names: guessed from the texts
    if not candidates:
        raise MapError("no answers were found in it (no key like output, answer or response "
                       "holding text)")
    return write(candidates[0])


def guess(units: list) -> Guess:
    """How to read `units`; MapError when they hold no answers or no scores."""
    units = [u for u in units[:SAMPLE_UNITS] if isinstance(u, dict)]
    if not units:
        raise MapError("it holds no objects or rows")
    each = _choose_each(units)
    sample = [item for unit in units for item, _ in _safe_items(unit, each)]
    first = sample[0]
    unsure = []

    # the answers, and their sides
    outputs = _outputs(first)
    sides: list[str] = []
    if not outputs:  # no key says which text is the answer: the longest one
        texts = _texts(first)
        if not texts:
            raise MapError("no answers were found in it")
        outputs = [max(texts, key=lambda seg: sum(len(str(item.get(seg[0], "")))
                                                  for item in sample))]
        unsure.append("output")
    if len(outputs) > 1:
        at = _differ_at(outputs)
        if at is None:
            outputs, unsure = outputs[:1], [*unsure, "output"]
        else:
            sides = list(dict.fromkeys(p[at] for p in outputs))
            outputs = [_fill(outputs[0], at, SIDE)]
    output_seg = outputs[0]

    # the score or verdict, per side and per judge
    scores = [seg for seg, v in _leaves(first) if _is(seg[-1], SCORE_WORDS)
              and (number(v) is not None or isinstance(v, bool)
                   or (isinstance(v, str) and 0 < len(v) <= MAX_VERDICT))]
    if not scores:
        scores = [seg for seg, v in _leaves(first)
                  if number(v) is not None and not _is(seg[-1], ("id",))]
        if not scores:
            raise MapError("no score or verdict was found next to the answers")
        unsure.append("score")
    if sides:
        placed = []
        for seg in scores:
            hits = [i for i, k in enumerate(seg) if k in sides]
            placed.append(_fill(seg, hits[0], SIDE) if hits else seg)
        scores = list(dict.fromkeys(placed))
    judges: list[str] = []
    if len(scores) > 1:
        at = _differ_at(scores)
        if at is None:
            scores, unsure = scores[:1], [*unsure, "score"]
        else:
            judges = list(dict.fromkeys(p[at] for p in scores))
            scores = [_fill(scores[0], at, JUDGE)]
    score_seg = scores[0]
    if not judges and len(score_seg) >= 3 and SIDE not in score_seg[-2:-1] and any(
            _is(k, CRITERIA_WORDS) for k in score_seg[:-2]):
        judges = [score_seg[-2]]
        score_seg = _fill(score_seg, len(score_seg) - 2, JUDGE)

    # the input, the reason, the id
    leaves = [(seg, v) for seg, v in _leaves(first) if SIDE not in seg]
    inputs = [seg for seg, v in leaves if isinstance(v, str) and any(
        _is(k, INPUT_WORDS) for k in seg) and seg not in outputs]
    if not inputs:
        texts = [seg for seg, v in leaves if isinstance(v, str) and len(seg) == 1
                 and seg != output_seg and not _is(seg[-1], REASON_WORDS + SCORE_WORDS)
                 and seg[-1].lower() not in ID_KEYS]
        if not texts:
            raise MapError("no question or input was found next to the answers")
        inputs = [texts[0]]
        unsure.append("input")
    reason = None
    parent = score_seg[:-1]
    for seg, v in _leaves(first):
        if len(seg) == len(score_seg) and _is(seg[-1], REASON_WORDS) and isinstance(v, str):
            fitted = _refit(seg, score_seg)
            if fitted[:-1] == parent:
                reason = _as_path(fitted)
                break
    id_key = next((k for k in first if str(k).lower() in ID_KEYS), None)

    guess = Guess(each=each, input=_as_path(inputs[0]), output=_as_path(output_seg),
                  score=_as_path(score_seg), reason=reason, id=None if id_key is None
                  else write([(str(id_key), False)]), sides=sides, judges=judges,
                  unsure=list(dict.fromkeys(unsure)))
    _kind_and_pass_mark(guess, sample)
    _model(guess, units)
    return guess


def _refit(seg: tuple, like: tuple) -> tuple:
    """`seg` with the placeholders of `like` where `like` has them."""
    return tuple(p if p in (SIDE, JUDGE) else k for k, p in zip(seg, like, strict=False))


def _safe_items(unit, each):
    try:
        return items(unit, each)
    except Missing:
        return []


def _values(guess: Guess, sample: list[dict]) -> list:
    out = []
    for item in sample:
        for side in guess.sides or [None]:
            for judge in guess.judges or [None]:
                try:
                    out.append(get(item, guess.score, side, judge))
                except Missing:
                    continue
    return out


def _kind_and_pass_mark(guess: Guess, sample: list[dict]) -> None:
    values = [v for v in _values(guess, sample) if v is not None]
    numbers = [number(v) for v in values]
    if values and all(n is not None for n in numbers):
        guess.kind = "score"
        lo, hi = min(numbers), max(numbers)
        if 0 <= lo and hi <= 1:
            guess.pass_mark, guess.pass_mark_sure = 0.5, True
        else:
            mid = (lo + hi) / 2
            guess.pass_mark = int(mid) if float(mid).is_integer() else round(mid, 2)
            guess.pass_mark_sure = False
    else:
        guess.kind, guess.pass_mark = "verdict", None


def _model(guess: Guess, units: list) -> None:
    """The key that names the judge's model, in the item or around it (nearest first)."""
    used = {parse(p)[0][0] for p in (guess.input, guess.output, guess.score) if p}
    for unit in units:
        for item, up in _safe_items(unit, guess.each):
            for obj in (item, *reversed(up)):
                for key in MODEL_KEYS:
                    for k, v in obj.items():
                        if str(k).lower() == key and k not in used and isinstance(
                                v, str) and v.strip():
                            guess.model_key, guess.model = str(k), v
                            return
            return


def judged_values(unit, m: dict):
    """Every (item, side, judge, score value, reason) the map reads in a unit."""
    for item, _ in items(unit, m["each"]):
        for side in m.get("sides") or [None]:
            for judge in judges_read(m):
                try:
                    value = get(item, m["score"], side, judge)
                except Missing:
                    value = None
                reason = None
                if m.get("reason"):
                    try:
                        reason = get(item, m["reason"], side, judge)
                    except Missing:
                        reason = None
                yield item, side, judge, value, reason


def judges_read(m: dict) -> list:
    """The judges the map reads: the chosen one, every one ("*"), or the one unnamed."""
    if JUDGE not in m["score"]:
        return [None]
    judge = m.get("judge")
    return list(m.get("judges") or []) if judge in (None, "*") else [judge]


def made_by_a_rule(value, reason) -> bool:
    """An error instead of a score, or a score made by a rule (a reason starting "Rule")."""
    return value is None or (isinstance(reason, str) and reason.strip().lower().startswith(
        "rule"))


def left_out(units: list, guess: Guess, judges: list[str]) -> int:
    """How many answers of `judges` have an error or a score made by a rule."""
    m = {**guess.to_map(), "judge": "*" if len(judges) != 1 else judges[0]}
    if len(judges) > 1:
        m["judges"] = judges
    n = 0
    for unit in units:
        try:
            n += sum(made_by_a_rule(v, r) for _, _, _, v, r in judged_values(unit, m))
        except Missing:
            continue
    return n


__all__ = ["Guess", "MapError", "Missing", "get", "guess", "items", "judged_values",
           "judges_read", "left_out", "listing", "load", "load_numbered", "made_by_a_rule",
           "number", "parse", "shown", "write"]
