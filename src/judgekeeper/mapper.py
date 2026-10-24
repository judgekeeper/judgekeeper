"""Read a results file saved in a project's own format: list its nested paths and guess how to
read it. `judgekeeper` (own_map.py) shows the guess, asks only what it cannot tell, and saves
the map in judgekeeper.toml; readers/mapped.py then reads the file with it. Standard library only.

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

import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path

from judgekeeper.textio import NOT_JSON, jsonl_lines, read_utf8

SIDE, JUDGE = "{side}", "{judge}"
CRITERION = "<criterion>"
EXAMPLE_WIDTH = 60
SAMPLE_UNITS = 50  # units looked at for a guess
MAX_DEPTH = 8

INPUT_WORDS = ("input", "prompt", "question", "query", "instruction", "message", "request")
OUTPUT_WORDS = ("output", "outputs", "answer", "answers", "response", "responses",
                "completion", "reply", "generation")
SCORE_WORDS = ("score", "verdict", "passed", "pass", "label", "success", "grade", "rating",
               "judgment", "judgement")
REASON_WORDS = ("reason", "reasoning", "explanation", "rationale", "comment", "feedback",
                "justification", "why")
# An answer's reference (expected_output, reference_answer, ground_truth): never the answer
REFERENCE_WORDS = ("expected", "reference", "gold", "ideal", "target", "ground", "truth")
CRITERIA_WORDS = ("scores", "metrics", "criteria", "judges", "evaluations", "grades",
                  "ratings", "results")
ID_KEYS = ("id", "case_id", "item_id", "example_id", "sample_id", "test_id", "uid")
MODEL_KEYS = ("judge_model", "evaluation_model", "evaluator_model", "grader_model", "model",
              "judge", "evaluator", "grader")
JUDGE_MODEL_KEYS = MODEL_KEYS[:4]  # say "judge" in their own name, at any depth
JUDGE_PARENTS = ("judge", "judges", "judging", "evaluator", "grader", "grading", "scorer")
PASS_MARK_KEYS = ("pass_mark", "passmark", "threshold", "pass_threshold", "passing_score",
                  "pass_score", "min_score", "cutoff")
# Where a file keeps its judge's settings (pass mark, criteria text): never an answer's parts
SETTING_PARENTS = (*JUDGE_PARENTS, "config", "settings", "criteria", "rubric", "rubrics")
# A part under one of these is a verdict when its values are verdict-like (judge.result)
JUDGE_WORDS = ("judge", "judgment", "judgement", "eval", "evaluation", "grader", "grading")
VERDICT_VALUES = frozenset({
    "pass", "passed", "fail", "failed", "true", "false", "yes", "no", "y", "n", "correct",
    "incorrect", "right", "wrong", "good", "bad", "ok", "accept", "accepted", "reject",
    "rejected", "success", "failure", "partial", "partially correct", "c", "i", "p"})
MOST = 0.8  # the share of an answer's values that must be verdict-like
# A column named for the judge is listed first when a table holds several verdict columns
JUDGE_NAMED = ("judge", "llm")
# A 0/1 column named for a rule in code (keyword_score, regex_match) is not an LLM judge
RULE_WORDS = ("keyword", "keywords", "regex", "exact", "contains")
RULE_VALUES = frozenset({"0", "1", "true", "false"})
# Words a model's name holds (with a digit, a slash or a colon, the sign of a model name):
# a "model" or "grader" column whose values have none of them names a rule, not a model
MODEL_WORDS = ("gpt", "claude", "gemini", "llama", "mistral", "mixtral", "qwen", "deepseek",
               "sonnet", "haiku", "opus", "openai", "anthropic", "azure", "bedrock", "ollama",
               "groq", "cohere", "command", "phi", "gemma", "grok", "openrouter", "vertex",
               "together", "fireworks", "nova", "titan", "palm", "codex")

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


def filled(path: str | None, side: str | None = None, judge: str | None = None) -> str:
    """A path for the screen, with its placeholders filled with real names (A.output, the
    first judge's key): never a placeholder on screen."""
    if not path:
        return ""
    try:
        parts = parse(path)
    except MapError:
        return path
    return write([(side if k == SIDE and side is not None else judge
                   if k == JUDGE and judge is not None else k, many) for k, many in parts])


def _words(key: str) -> set[str]:
    return {w.lower() for w in _WORD.findall(str(key))}


def _is(key: str, words) -> bool:
    return bool(_words(key) & set(words))


# Loading and walking ----------------------------------------------------------------------

def load_numbered(path: str | Path, skipped: list | None = None) -> list[tuple[int, object]]:
    """[(line number, unit)]: JSONL lines, CSV rows (all values text), or a JSON document
    (its elements, when it is a list). Lines that are not JSON are skipped (their numbers
    added to `skipped`)."""
    path = Path(path)
    suffix = path.suffix.lower()
    text = read_utf8(path, MapError).removeprefix("﻿")
    if suffix in (".csv", ".tsv"):
        from judgekeeper.table import csv_numbered, open_quote

        line = open_quote(path)
        if line is not None:  # the rows after it would be read as one cell: never shown
            raise MapError(f"line {line} of {path.name} has a quote that never closes, so the "
                           "rows after it can't be read")
        return [(n, {k: v for k, v in row.items() if k is not None})
                for n, row in csv_numbered(text, suffix)]
    if suffix == ".json":
        try:
            doc = json.loads(text)
        except ValueError:  # never the parser's words: they quote the file
            raise MapError(f"{path.name} is damaged (it isn't valid JSON)") from None
        except RecursionError:
            raise MapError(NOT_JSON.format(file=path.name)) from None
        return list(enumerate(doc, 1)) if isinstance(doc, list) else [(1, doc)]
    units = []
    for n, line in enumerate(jsonl_lines(text), 1):
        if line.strip():
            try:
                units.append((n, json.loads(line)))
            except (ValueError, RecursionError):
                if skipped is not None:
                    skipped.append(n)
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
    and of the keys in `judges` that hold parts of their own only the first, by its real name
    (the others have the same shape); judges that are columns of their own are each listed."""
    out, seen = [], set()

    def walk(obj, prefix, depth):
        if depth > MAX_DEPTH:
            return
        present = [j for j in judges if j in obj]  # the first judge stands for them all
        for key, value in obj.items():
            key = str(key)
            if key in judges and key != present[0] and (prefix or isinstance(value, dict)):
                continue
            seg = [*prefix, (key, False)]
            if isinstance(value, dict) and value:
                walk(value, seg, depth + 1)
            elif isinstance(value, list) and value and all(isinstance(v, dict) for v in value):
                walk(value[0], [*prefix, (key, True)], depth + 1)
            else:
                text = write(seg)
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
    pass_mark_key: str | None = None  # where the file states its pass mark (item or around it)
    pass_mark_given: bool = False  # typed in by the person
    pass_op: str = ">="  # how a score is held against the pass mark (--pass-if's)
    model_key: str | None = None  # a path, in the item or around it (nearest first)
    model: str | None = None  # the model's name in the first item, for showing
    unsure: list[str] = field(default_factory=list)  # roles guessed from value types only
    doubt: str | None = None  # why the whole reading may be wrong (one answer of many)

    def judge_name(self) -> str:
        """The judge's name when the file holds one judge without a name of its own."""
        return parse(self.score)[-1][0]

    def to_map(self) -> dict:
        """What judgekeeper.toml keeps under [start.map]."""
        out = {"each": self.each, "id": self.id, "input": self.input, "output": self.output,
               "sides": list(self.sides), "score": self.score, "reason": self.reason,
               "kind": self.kind, "judges": list(self.judges), "model_key": self.model_key,
               "pass_mark_key": None if self.pass_mark_given else self.pass_mark_key}
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


def _setting(seg: tuple) -> bool:
    """A part under the judge's settings (judge.criteria.answer_quality): never an answer's."""
    return any(str(k).lower() in SETTING_PARENTS for k in seg[:-1])


def _id_like(key: str) -> bool:
    return str(key).lower() in ID_KEYS or bool(_words(key) & {"id", "uid", "uuid"})


def _verdict_value(value) -> bool:
    """A judge's verdict as a value: pass/fail and its kin, true/false, or a number from 0 to
    100 (0 to 1, or a fixed scale such as 1 to 5)."""
    if isinstance(value, bool):
        return True
    n = number(value)
    if n is not None:
        return 0 <= n <= 100
    return isinstance(value, str) and value.strip().lower() in VERDICT_VALUES


def blank(value) -> bool:
    """No score at all: missing, an empty cell, or a word for none (NaN, N/A, null, error: a
    failed call, normalise.NO_DECISION)."""
    from judgekeeper.normalise import NO_DECISION

    if isinstance(value, float):
        return math.isnan(value)
    return value is None or isinstance(value, str) and (
        not value.strip() or value.strip().lower() in NO_DECISION)


def _verdict_like(values) -> bool:
    """Most of an answer's values (MOST, empty ones aside) are verdicts."""
    values = [v for v in values if not blank(v)]
    return bool(values) and sum(map(_verdict_value, values)) >= MOST * len(values)


def _plain_text(value) -> bool:
    """A value that reads as an answer's text: not a number, true/false or a verdict word,
    and not a JSON list or object (a list of keywords)."""
    if not isinstance(value, str) or number(value) is not None:
        return False
    text = value.strip()
    if text.lower() in VERDICT_VALUES:
        return False
    # a list or object, as JSON or as pandas writes a list, is not an answer
    return not (text[:1] in "[{" and text[-1:] in "]}")


def _text_like(values) -> bool:
    """Most of a column's values (MOST, empty ones aside) are text: an answer, not a column
    of numbers, true/false, 0/1 or keyword lists that happens to be named like one."""
    values = [v for v in values if not blank(v)]
    return bool(values) and sum(map(_plain_text, values)) > (1 - MOST) * len(values)


def _outputs(item: dict) -> list[tuple]:
    return [seg for seg, v in _leaves(item) if isinstance(v, str)
            and any(_is(k, OUTPUT_WORDS) for k in seg) and not _is(seg[-1], REASON_WORDS)
            and not _is(seg[-1], REFERENCE_WORDS)  # expected_output: the reference answer
            and not any(_is(k, INPUT_WORDS) for k in seg) and not _setting(seg)]


def _judge_first(judges: list[str]) -> list[str]:
    """The judges with the ones named for a judge (judge_verdict, llm_score) first."""
    named = [j for j in judges if _words(j) & set(JUDGE_NAMED)]
    return named + [j for j in judges if j not in named]


def _judge_column(seg: tuple, values) -> bool:
    """A column named for a judge (llm_judge) holding only 0/1 or true/false: a verdict."""
    if not _is(seg[-1], JUDGE_WORDS) or _setting(seg[:-1]):
        return False
    values = [str(v).strip().lower() for v in values if not blank(v)]
    return bool(values) and all(v in RULE_VALUES for v in values)


def _rule_column(key: str, values) -> bool:
    """A score column that a rule in code made, not an LLM judge: named for the rule
    (keyword_score, regex_match, exact_match, contains_ok) and holding only 0/1."""
    words = _WORD.findall(str(key))
    if not words or words[0].lower() not in RULE_WORDS:
        return False
    values = [str(v).strip().lower() for v in values if not blank(v)]
    return bool(values) and all(v in RULE_VALUES for v in values)


def _model_like(value) -> bool:
    """A value that reads as a model's name: a digit, a slash or a colon in it (gpt-4.1,
    ollama/qwen2.5:3b), or a word a model's name holds. "string_match" is not one."""
    if not isinstance(value, str) or not value.strip():
        return False
    text = value.strip().lower()
    return (any(c.isdigit() or c in "/:" for c in text)
            or bool(_words(text) & set(MODEL_WORDS)))


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
            and seg[0].lower() not in MODEL_KEYS and not _id_like(seg[0])]


def _choose_each(units) -> str:
    """The path to the answers: a list of two or more items that hold answers before the
    line itself (a line can name its judge like an answer: answer_quality)."""
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
                if len(found) >= 2 and () in candidates:
                    candidates.remove(())
        if candidates:
            break
    if not candidates and _texts(units[0]):
        return ""  # flat, with an answer that no key names: guessed from the texts
    if not candidates:
        raise MapError("no answers were found in it (no key like output, answer or response "
                       "holding text)")
    return write(candidates[0])


def guess(units: list, each: str | None = None) -> Guess:
    """How to read `units`; MapError when they hold no answers or no scores. `each` (the
    path to the items) is given when the person corrected it."""
    units = [u for u in units[:SAMPLE_UNITS] if isinstance(u, dict)]
    if not units:
        raise MapError("it holds no objects or rows")
    each = _choose_each(units) if each is None else each
    sample = [item for unit in units for item, _ in _safe_items(unit, each)]
    if not sample:
        raise MapError(f"no items at {each or 'the top of each line'}")
    first = sample[0]
    unsure = []

    # the answers, and their sides: a part named like one, holding text (not a column of
    # numbers, true/false or keyword lists)
    outputs = [seg for seg in _outputs(first) if _text_like(_at(sample, seg))]
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

    # the score or verdict, per side and per judge: named so, and verdict-like values
    scores = [seg for seg, v in _leaves(first) if (_named_verdict(seg)
              and (blank(v) or _verdict_value(v))  # the first row's cell may be empty
              and _verdict_like(_at(sample, seg)) or _judge_column(seg, _at(sample, seg)))]
    rules = [seg for seg, _ in _leaves(first) if _rule_column(seg[-1], _at(sample, seg))]
    scores = [seg for seg in scores if seg not in rules]
    if not scores and rules:
        raise MapError(f"its score column {_as_path(rules[0])} is a rule in code (a "
                       f"{_WORD.findall(rules[0][-1])[0].lower()} match), not an LLM-as-a-judge")
    if not scores:
        raise MapError("no LLM-as-a-judge verdicts were found in it")
    if sides:
        placed = []
        for seg in scores:
            hits = [i for i, k in enumerate(seg) if k in sides]
            placed.append(_fill(seg, hits[0], SIDE) if hits else seg)
        scores = list(dict.fromkeys(placed))
    judges: list[str] = []
    if len(scores) > 1:
        at = _differ_at(scores)
        if at is None:  # a score and a verdict per judge (score, passed): the most score-like
            last = min({seg[-1] for seg in scores}, key=_score_rank)
            same = [seg for seg in scores if seg[-1] == last]
            at = _differ_at(same) if len(same) > 1 else None
            scores = same if at is not None else scores
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
    if JUDGE in score_seg:
        judges = _judge_first(_every_judge(sample, score_seg, sides, judges))

    # the input, the reason, the id
    leaves = [(seg, v) for seg, v in _leaves(first) if SIDE not in seg]
    inputs = [seg for seg, v in leaves if isinstance(v, str) and any(
        _is(k, INPUT_WORDS) for k in seg) and seg not in outputs and not _setting(seg)
        and not _id_like(seg[-1])]
    if not inputs:
        texts = [seg for seg, v in leaves if isinstance(v, str) and len(seg) == 1
                 and seg != output_seg and not _is(seg[-1], REASON_WORDS + SCORE_WORDS)
                 and not _id_like(seg[-1])]
        if not texts:
            raise MapError("no question or input was found next to the answers")
        inputs = [texts[0]]
        unsure.append("input")
    reason = None
    parent = score_seg[:-1]
    for seg, v in _leaves(first):
        if len(seg) == len(score_seg) and _is(seg[-1], REASON_WORDS) and isinstance(v, str):
            fitted = _refit(seg, score_seg)
            if fitted[:-1] == parent and fitted != score_seg:  # never the score's own path
                reason = _as_path(fitted)
                break
    id_key = next((k for k in first if str(k).lower() in ID_KEYS), None)

    guess = Guess(each=each, input=_as_path(inputs[0]), output=_as_path(output_seg),
                  score=_as_path(score_seg), reason=reason, id=None if id_key is None
                  else write([(str(id_key), False)]), sides=sides, judges=judges,
                  unsure=list(dict.fromkeys(unsure)))
    _kind_and_pass_mark(guess, sample)
    _pass_mark_in_file(guess, units)
    _model(guess, units)
    guess.doubt = _one_of_many(units, each)
    return guess


def _named_verdict(seg: tuple) -> bool:
    """A part whose name says it is a verdict (score, verdict, grade, ...) or that sits under
    a judge (judge.result); never an id or a pass mark."""
    last = seg[-1]
    if _id_like(last) or last.lower().replace("-", "_") in PASS_MARK_KEYS:
        return False
    return _is(last, SCORE_WORDS) or any(_is(k, JUDGE_WORDS) for k in seg[:-1]) and not _is(
        last, REASON_WORDS + ("model",))


def _at(sample: list[dict], seg: tuple) -> list:
    """The values at `seg` in each item that has it."""
    out = []
    for item in sample:
        try:
            out.append(get(item, _as_path(seg)))
        except Missing:
            continue
    return out


def _one_of_many(units: list, each: str) -> str | None:
    """Why a reading of one answer is in doubt: the file holds a list of many items."""
    if sum(len(_safe_items(u, each)) for u in units) != 1:
        return None
    lists = [(len(_safe_items(units[0], write(seg))), seg) for seg in _item_lists(units[0])]
    n, seg = max(lists, key=lambda x: x[0], default=(0, None))
    if n < 2:
        return None
    return (f"judgekeeper read 1 answer, but the file holds a list of {n} items "
            f"({shown(write(seg)).removesuffix('[]')}); check the mapping")


def _score_rank(key: str) -> int:
    """How score-like a key is: its first word in SCORE_WORDS order (score before passed)."""
    found = [SCORE_WORDS.index(w) for w in _words(key) if w in SCORE_WORDS]
    return min(found, default=len(SCORE_WORDS))


def _every_judge(sample: list[dict], score_seg: tuple, sides: list[str],
                 judges: list[str]) -> list[str]:
    """Every key at the judge's place in the score path, across the sample: each criterion
    under the scores' parent is a judge, not only the ones the first item shows."""
    at = score_seg.index(JUDGE)
    parent, rest = score_seg[:at], score_seg[at + 1:]
    found = list(judges)
    for item in sample:
        for side in sides or [None]:
            try:
                scores = get(item, _as_path(parent), side)
            except Missing:
                continue
            for key, value in scores.items() if isinstance(scores, dict) else ():
                try:
                    get(value, _as_path(rest))
                except Missing:
                    continue
                if str(key) not in found:
                    found.append(str(key))

    def verdict(j: str) -> bool:
        values = _values_of(sample, _as_path(score_seg), sides, j)
        seg = (*parent, j, *rest)
        return (_named_verdict(seg) and _verdict_like(values) or _judge_column(seg, values)) \
            and not _rule_column(j, values)

    return [j for j in found if verdict(j)]


def _values_of(sample: list[dict], path: str, sides: list[str], judge: str) -> list:
    out = []
    for item in sample:
        for side in sides or [None]:
            try:
                out.append(get(item, path, side, judge))
            except Missing:
                continue
    return out


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
    values = [v for v in _values(guess, sample) if not blank(v)]
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


def _objects(guess: Guess, units: list):
    """The first item, then each object around it, nearest first: where a file states things
    about the whole run (its judge, its pass mark)."""
    for unit in units:
        for item, up in _safe_items(unit, guess.each):
            yield from (item, *reversed(up))
            return


def _around(guess: Guess, units: list):
    """(path, value) of every leaf of _objects, in order."""
    for obj in _objects(guess, units):
        yield from _leaves(obj)


def _pass_mark_in_file(guess: Guess, units: list) -> None:
    """The pass mark the file states (pass_mark, threshold, ...), in the item or around it,
    not inside one answer or one judge's scores. It wins over the guess from the scores."""
    if guess.kind != "score":
        return
    placed = set(guess.sides) | set(guess.judges)
    for seg, value in _around(guess, units):
        key = seg[-1].lower().replace("-", "_")
        if (key in PASS_MARK_KEYS or "".join(_words(seg[-1])) == "passmark") and \
                number(value) is not None and not placed & set(seg):
            guess.pass_mark, guess.pass_mark_sure = number(value), True
            guess.pass_mark_key = _as_path(seg)
            return


def _model_rank(seg: tuple) -> int | None:
    """How surely a path names the judge's model (lower is surer), or None: a key that says
    judge in its own name, or a model key inside a judge object (judge.model), then a key of
    its own in MODEL_KEYS order (model, judge, ...)."""
    last = seg[-1].lower()
    if last in JUDGE_MODEL_KEYS or (len(seg) > 1 and last == "model" and any(
            k.lower() in JUDGE_PARENTS for k in seg[:-1])):
        return 0
    if len(seg) == 1 and last in MODEL_KEYS and last != "model":  # "model" alone: the app's
        return 1 + MODEL_KEYS.index(last)
    return None


def _model(guess: Guess, units: list) -> None:
    """The path that names the judge's model, in the item or around it (nearest first): a
    key like judge_model at any depth, a model key inside a judge object (judge.model), or
    a key of its own (model, judge). Never a model elsewhere, such as the app's."""
    used = {parse(p)[0][0] for p in (guess.input, guess.output, guess.score) if p}
    sample = [item for unit in units for item, _ in _safe_items(unit, guess.each)]
    for n, obj in enumerate(_objects(guess, units)):
        found = [(_model_rank(seg), seg, v) for seg, v in _leaves(obj)
                 if seg[0] not in used and isinstance(v, str) and v.strip()]
        # in the items, every value must read as a model's name ("string_match" is a rule)
        found = [x for x in found if x[0] is not None and (n > 0 or all(
            _model_like(v) for v in _at(sample, x[1]) if not blank(v)))]
        if found:
            _, seg, value = min(found, key=lambda x: x[0])
            guess.model_key, guess.model = _as_path(seg), value
            return


def value_around(item: dict, up: list, key: str):
    """The value at `key` (a model_key or pass_mark_key) in the item or around it, nearest
    first; None when it is in none of them."""
    for obj in (item, *reversed(up)):
        if not isinstance(obj, dict):
            continue
        if key in obj:  # a plain key, as older maps saved it
            return obj[key]
        try:
            return get(obj, key)
        except (Missing, MapError):
            continue
    return None


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
    return blank(value) or by_a_rule(reason)


def by_a_rule(reason) -> bool:
    """A score made by a rule, not the judge: its reason starts "Rule"."""
    return isinstance(reason, str) and reason.strip().lower().startswith("rule")


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


# Correcting one part of the guess (after "Is this how ... read FILE?" is answered No) ------------

def _placed(seg: tuple, g: Guess) -> tuple:
    """A leaf path of the first item with its side and judge names as placeholders."""
    out, side_done, judge_done = [], False, False
    for k in seg:
        if not side_done and k in g.sides:
            out.append(SIDE)
            side_done = True
        elif not judge_done and k in g.judges:
            out.append(JUDGE)
            judge_done = True
        else:
            out.append(k)
    return tuple(out)


def choices(units: list, g: Guess, role: str) -> list[tuple[str, str]]:
    """[(path, example value)] the person can choose for one part of the guess: `role` is
    each, input, output, score, reason, id or model_key."""
    units = [u for u in units[:SAMPLE_UNITS] if isinstance(u, dict)]
    if role == "each":
        segs = list(dict.fromkeys(write(seg) for seg in _item_lists(units[0])))
        found = [(path, f"{len(_safe_items(units[0], path))} items") for path in segs]
        return found + [("", "each line or row is one answer")]
    if role == "model_key":
        seen, out = set(), []
        for seg, value in _around(g, units):
            path = _as_path(seg)
            if isinstance(value, str) and value.strip() and path not in seen:
                seen.add(path)
                out.append((path, _example(value)))
        return out
    first = next((item for unit in units for item, _ in _safe_items(unit, g.each)), None)
    if first is None:
        return []
    out, seen = [], set()
    for seg, value in _leaves(first):
        placed = _placed(seg, g) if role != "id" else seg
        if role == "id" and (len(seg) > 1 or isinstance(value, dict | list)):
            continue
        if role in ("input", "output", "reason") and not isinstance(value, str):
            continue
        if role == "score" and not _verdict_value(value):
            continue
        path = _as_path(placed)
        if path not in seen:
            seen.add(path)
            out.append((path, _example(value)))
    return out


def with_part(units: list, g: Guess, role: str, path: str | None) -> Guess:
    """The guess with one part chosen by the person (None: no such part). Choosing what one
    answer is guesses the rest again from there; MapError when nothing can be read so."""
    import dataclasses

    units = [u for u in units[:SAMPLE_UNITS] if isinstance(u, dict)]
    if role == "each":
        return guess(units, each=path)
    new = dataclasses.replace(g, unsure=[r for r in g.unsure if r != role])
    if role == "model_key":
        value = next((v for s, v in _around(g, units) if _as_path(s) == path), None)
        new.model_key, new.model = path, value
        return new
    setattr(new, role, path)
    if role == "score":
        new.judges = list(g.judges) if JUDGE in path else []
        sample = [item for unit in units for item, _ in _safe_items(unit, new.each)]
        new.pass_mark_key, new.pass_mark_given = None, False
        _kind_and_pass_mark(new, sample)
        _pass_mark_in_file(new, units)
    return new


__all__ = ["Guess", "MapError", "Missing", "choices", "filled", "get", "guess", "items",
           "judged_values", "judges_read", "left_out", "listing", "load", "load_numbered",
           "made_by_a_rule", "number", "parse", "shown", "value_around", "with_part", "write"]
