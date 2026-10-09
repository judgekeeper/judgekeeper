"""Did your judge actually judge? Checks on the judge's own decisions, before anyone labels.

No labels, no AI call, no key: plain Python on the pool `start` already made (start.build_pool)
and the marks the readers set (records.Mark). Four checks:

1. No real decision: the judge's call failed ("error"), its reply could not be read
   ("unreadable"), the tool would not judge an empty answer ("empty_answer_refused": DeepEval
   refuses one), or there is no decision at all ("empty"); and, for DeepEval, a check of
   nothing that still got full marks ("nothing_checked"). These are left out of the pool.
2. Passed an empty answer: the app's answer is empty after trimming spaces and the judge
   passed it. These stay in the pool: a real, bad decision, worth a person's mark.
3. The same decision for everything: the judge passed (or failed) every answer.
4. The reason says the opposite: the judge's own reason states the other decision, in one of a
   few explicit forms only (stated_decisions). Skipped for score judges with a pass mark
   (`--pass-if`, DeepEval's thresholds, record()'s pass_mark, a mapped score), whose reasons
   talk about a score.

Every check is information: none stops `start`. The functions here are pure; start_label
writes judge-check.json and judge-check.csv, and the terminal and the result page say `lines`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from judgekeeper.find import NAMES
from judgekeeper.redact import scrub

ERROR, UNREADABLE, EMPTY, NOTHING_CHECKED = "error", "unreadable", "empty", "nothing_checked"
EMPTY_ANSWER_REFUSED = "empty_answer_refused"
NO_DECISION = (ERROR, UNREADABLE, EMPTY_ANSWER_REFUSED, EMPTY)
LEFT_OUT = (*NO_DECISION, NOTHING_CHECKED)  # left out of the pool
PASSED_EMPTY = "empty_answer_passed"  # kept in the pool: a real decision
OPPOSITE = "reason_says_opposite"
KINDS = (*LEFT_OUT, PASSED_EMPTY, OPPOSITE)
JSON_FILE, CSV_FILE = "judge-check.json", "judge-check.csv"
CSV_PATH = f".judgekeeper/{CSV_FILE}"  # start_label.FOLDER
CSV_COLUMNS = ("id", "problem", "tool_counted_as", "judge_decision", "judge_reason", "input",
               "output")
TITLE = "Did your judge actually judge?"
EVERY_ANSWER = "Your judge made a real decision on every answer."
TOOLS = ("promptfoo", "deepeval", "inspect", "mlflow")  # tools that count verdicts themselves


# The reason says the opposite ------------------------------------------------------------

_WORDS = {"pass": "pass", "passed": "pass", "correct": "pass", "c": "pass",
          "fail": "fail", "failed": "fail", "incorrect": "fail", "i": "fail"}
# The reason's first word, after any markdown or quote marks: PASS, PASSED, FAIL or FAILED.
_FIRST = re.compile(r"\A[\s*\"'`#\[(]*(pass(?:ed)?|fail(?:ed)?)(?!\w)", re.IGNORECASE)
# A marker such as "Verdict: pass" or "Final answer = incorrect".
_MARKER = re.compile(r"\b(?:final verdict|final answer|grade|verdict|result|decision)\s*[:=]"
                     r"\s*[*\"'`]*\s*(pass(?:ed)?|fail(?:ed)?|correct|incorrect)(?!\w)",
                     re.IGNORECASE)
# Inspect's model-graded scorers: "GRADE: C" or "GRADE: I", alone at the end of a line.
_GRADE = re.compile(r"GRADE\s*:\s*([CI])[ \t.*]*$", re.MULTILINE)


def stated_decisions(reason) -> list[str]:
    """The decisions the reason states, "pass" or "fail": its first word when that is PASS,
    PASSED, FAIL or FAILED, then its last marker (`_MARKER`, `_GRADE`). Narrow on purpose (a
    false alarm costs trust): no other words count."""
    if not isinstance(reason, str):
        return []
    stated = []
    m = _FIRST.match(reason)
    if m:
        stated.append(_WORDS[m[1].lower()])
    markers = [(m.start(), m[1]) for pattern in (_MARKER, _GRADE)
               for m in pattern.finditer(reason)]
    if markers:
        stated.append(_WORDS[max(markers)[1].lower()])
    return stated


def says_opposite(reason, decision: str) -> bool:
    """Either form states the other decision (Inspect's "FAIL: ... GRADE: C" on a pass)."""
    return any(stated != decision for stated in stated_decisions(reason))


# Empty answers ---------------------------------------------------------------------------

def is_empty_answer(output, mark) -> bool:
    """The app gave nothing: its output is a text that is empty after trimming spaces, or an
    empty list or dict. A missing output (None) is unknown, not empty, and an answer kept
    elsewhere (a DeepEval conversation's turns) is not empty either."""
    if mark.output_elsewhere:
        return False
    if isinstance(output, str):
        return not output.strip()
    if isinstance(output, list | dict):
        return not output
    return False


# The check -------------------------------------------------------------------------------

@dataclass
class Finding:
    id: str
    problem: str  # one of KINDS
    tool_counted_as: str | None
    judge_decision: str
    judge_reason: str
    input: object = None
    output: object = None

    def to_dict(self) -> dict:
        """As judge-check.json keeps it: no input or output (those are in the CSV)."""
        return {"id": self.id, "problem": self.problem,
                "tool_counted_as": self.tool_counted_as,
                "judge_decision": scrub(self.judge_decision),
                "judge_reason": scrub(self.judge_reason)}


@dataclass
class Result:
    answers: int  # every answer the judge saw: the pool and the left out
    tool: str
    findings: list[Finding] = field(default_factory=list)
    same_decision: str | None = None  # "pass" or "fail" when it is the same for every answer

    def counts(self) -> dict[str, int]:
        return {k: sum(f.problem == k for f in self.findings) for k in KINDS}

    def block(self) -> dict:
        """The counts, as start.json and result.json keep them (the `judge_check` block)."""
        return {"answers": self.answers, **self.counts(), "same_decision": self.same_decision,
                "tool": self.tool, "tool_counted_as": self._counted_as()}

    def to_json(self) -> dict:
        return {"counts": self.block(), "findings": [f.to_dict() for f in self.findings]}

    def _counted_as(self) -> str | None:
        """What the tool counted the answers with no real decision as: "pass", "fail",
        "pass and fail" or "left out"; None when it does not say, or when one phrase does
        not fit them all."""
        said = {f.tool_counted_as for f in self.findings if f.problem in NO_DECISION}
        if self.tool not in TOOLS or not said or None in said:
            return None
        if said == {"pass", "fail"}:
            return "pass and fail"
        return said.pop() if len(said) == 1 else None


def _decision(record) -> str:
    """A left-out record's decision as the tool saved it ("" when there is none)."""
    for value in (record.label, record.score):
        if value is not None:
            return str(value)
    return ""


def check(pool, tool: str, score_judge: bool = False) -> Result:
    """The judge check of a start.Pool. `score_judge`: the decisions come from a score and a
    pass mark, so the reasons are not read for a decision."""
    findings = [Finding(key, kind, r.mark.tool_counted_as, _decision(r), r.explanation or "",
                        r.input, r.output)
                for key, (kind, r) in pool.left.items()]
    for a in pool.answers:
        if a.verdict == "pass" and is_empty_answer(a.output, a.mark):
            findings.append(Finding(a.id, PASSED_EMPTY, None, a.verdict, a.reason, a.input,
                                    a.output))
        if not score_judge and says_opposite(a.reason, a.verdict):
            findings.append(Finding(a.id, OPPOSITE, None, a.verdict, a.reason, a.input,
                                    a.output))
    same = None
    if len(pool.answers) >= 2 and not (pool.n_pass and pool.n_fail):
        same = "pass" if pool.n_pass else "fail"
    return Result(answers=len(pool.answers) + len(pool.left), tool=tool, findings=findings,
                  same_decision=same)


# What it says ----------------------------------------------------------------------------

def _n(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


_NO_DECISION_WORDS = {ERROR: ("error", "errors"),
                      UNREADABLE: ("reply it could not read", "replies it could not read"),
                      EMPTY_ANSWER_REFUSED: ("empty answer it could not judge",
                                             "empty answers it could not judge"),
                      EMPTY: ("empty decision", "empty decisions")}
_COUNTED = {"pass": ("counted it as a pass", "counted them as passes"),
            "fail": ("counted it as a fail", "counted them as fails"),
            "pass and fail": ("counted it as a pass or a fail",
                              "counted them as some passes and some fails"),
            "left out": ("left it out", "left them out")}
_SAME = {"pass": ("Your judge passed every answer. It may not be checking anything: your marks "
                  "will show it."),
         "fail": ("Your judge failed every answer. It may be too strict, or not checking "
                  "anything: your marks will show it.")}


def lines(block: dict | None) -> list[list[str]]:
    """What was found, one list per finding: its first line, then the lines that go on under
    it. [] when nothing was found (EVERY_ANSWER says so)."""
    if not block:
        return []
    out = []
    no_decision = sum(block.get(k, 0) for k in NO_DECISION)
    name = NAMES.get(block.get("tool")) if block.get("tool") in TOOLS else None
    if no_decision:
        one = no_decision == 1
        parts = [_n(block[k], *_NO_DECISION_WORDS[k]) for k in NO_DECISION if block.get(k)]
        counted = _COUNTED.get(block.get("tool_counted_as"))
        said = f"{name} {counted[0 if one else 1]}. " if name and counted else ""
        first = (f"Your judge made no real decision on {no_decision} of {block['answers']} "
                 f"answers: {', '.join(parts)}.")
        out.append([first, f"{said}{'It is' if one else 'They are'} left out here."])
    nothing = block.get(NOTHING_CHECKED, 0)
    if nothing:
        one = nothing == 1
        line = (f"On {_n(nothing, 'answer', 'answers')} your judge checked nothing, and "
                f"{name or 'your eval tool'} gave {'it' if one else 'them'} full marks. "
                f"{'It is' if one else 'They are'} left out here.")
        out.append([line])
    if block.get(PASSED_EMPTY):
        empty = _n(block[PASSED_EMPTY], "empty answer", "empty answers")
        out.append([f"Your judge passed {empty}."])
    if block.get(OPPOSITE):
        line = (f"On {_n(block[OPPOSITE], 'answer', 'answers')}, your judge's reason says the "
                "opposite of its decision.")
        out.append([line])
    if block.get("same_decision") in _SAME:
        out.append([_SAME[block["same_decision"]]])
    return out


def has_rows(block: dict | None) -> bool:
    """Whether judge-check.csv lists any answer."""
    return bool(block) and any(block.get(k) for k in KINDS)


def terminal_lines(block: dict | None, tick: str) -> list[str]:
    """The lines `start` prints: `tick` (textio.tick) in front of the one line when nothing
    was found, else "!" in front of each finding, and where to see the answers."""
    found = lines(block)
    if not found:
        return [f"  {tick} {EVERY_ANSWER}"]
    out = []
    for first, *rest in found:
        out += [f"  ! {first}"] + [f"    {line}" for line in rest]
    if has_rows(block):
        out.append(f"    See them: {CSV_PATH}")
    return out


def page_lines(block: dict | None) -> list[str]:
    """The result page's card: one paragraph per finding."""
    return [" ".join(found) for found in lines(block)]


__all__ = ["CSV_COLUMNS", "EVERY_ANSWER", "KINDS", "LEFT_OUT", "TITLE", "Finding", "Result",
           "check", "has_rows", "is_empty_answer", "lines", "page_lines",
           "says_opposite", "stated_decisions", "terminal_lines"]
