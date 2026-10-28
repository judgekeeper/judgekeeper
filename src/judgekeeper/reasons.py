"""Why the person disagrees with the judge: the reasons they give on the live result page.

On each disagreement the person can see (never a mark kept aside for `fix`'s fair test), the
result page offers reasons to tap (REASONS), buttons from the parts of their own rule, their
own reasons (kept in .judgekeeper/reasons.json) and "Mark this part" for words in the answer.
Each change is one stamped line in marks.jsonl with the same mark (marks.py); spans are
[start, end] in the answer's text, never the text. The marking page never asks: it shows no
grade, and the person doesn't know yet where they disagree.

"I'm not sure about my own mark" never changes the mark: it is only counted. A mark changed
on the marking page after the grades were shown is stamped "after_result" (saw_grades).

All the rest is plain counting and fixed templates, no AI: `fix`'s first clue, the "missed it
or allowed it" check (mentioned) and suggestions.md. judgekeeper never writes the rule.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from judgekeeper.fingerprint import rule_hash, utc_now
from judgekeeper.redact import one_line, scrub, visible
from judgekeeper.textio import make_private, plural, write_replacing

FILE = "reasons.json"
# id: (words on the button, the judge's grade it is asked on; None for both)
REASONS = {
    "wrong_fact": ("It has a wrong fact", "pass"),
    "no_answer": ("It doesn't answer the question", "pass"),
    "left_out": ("It leaves out something important", "pass"),
    "unsafe": ("It's unsafe or not allowed", "pass"),
    "format_tone": ("Wrong format or tone", "pass"),
    "worded_differently": ("It's right, just worded differently", "fail"),
    "small_slips": ("Small slips don't matter here", "fail"),
    "short_ok": ("Short, but it answers the question", "fail"),
    "not_asked": ("The LLM-as-a-judge wanted something I didn't ask for", "fail"),
    "rule_silent": ("The rule doesn't say how to judge this", None),
    "unsure": ("I'm not sure about my own mark", None),
}
UNSURE = "unsure"
OWN = "own-"
OTHER = "Other…"
FIELDS = ("reasons", "note", "rule_parts", "rule_hash", "spans")  # a reason line's own keys
MAX_NOTE = 500
MAX_SPANS = 3
MAX_OWN = 8
MAX_FILE = 64 * 1024  # bytes of reasons.json read: MAX_OWN buttons are far less
MAX_PARTS = 6
PART_CHARS = 90  # of a rule part shown on its button (short)
SAID_CHARS = 60  # of a rule part quoted in "Your reason: ..." on the result page
TWICE = 2  # taps that make a clue line or a suggested rule line
# The one refusal for an answer the result page lists no reason box for: kept aside, graded
# as the person marked it, or no result shown yet. Which of them it is would tell the judge's
# hidden grade, or which marks are kept aside.
NOT_LISTED = ("this answer is not on your result page yet: reasons are only for the "
              "disagreements it lists")
QUESTION = "Why did you mark it {mark}?"
PART_QUESTION = {"pass": "Which part of your rule does this answer break?",
                 "fail": "Which part did your LLM-as-a-judge get wrong?"}
PARTS_LEFT_OUT = "\u201cOther\u2026\u201d covers the {n} other parts of your rule."
PART_LEFT_OUT = "\u201cOther\u2026\u201d covers the other part of your rule."
ADD = "Add a reason to any answer below. `fix` uses them."


def parts_left_out_line(n: int) -> str:
    """The line under the rule's buttons when `n` of its parts have none."""
    return PART_LEFT_OUT if n == 1 else PARTS_LEFT_OUT.format(n=n)


def offered(judge: str) -> list[str]:
    """The reasons asked on an answer the judge graded `judge`, in order."""
    return [k for k, (_, side) in REASONS.items() if side in (judge, None)]


def lower(text: str) -> str:
    """A button's words inside a sentence: its first letter small ("I" stays)."""
    return text if text.startswith(("I ", "I'")) else text[:1].lower() + text[1:]


# The parts of the rule ------------------------------------------------------------------------

_STEP = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+")
_SENTENCE = re.compile(r"(?<=[.!?])\s+")


def short(part: str, width: int = PART_CHARS) -> str:
    """A rule part as its button shows it: cut to `width` characters on a word, with "…" (the
    button's title holds it whole)."""
    if len(part) <= width:
        return part
    cut = part[:width - 1]
    if " " in cut:
        cut = cut[:cut.rindex(" ")]
    return cut.rstrip(" ,;:.") + "…"  # never "….": a cut is not a sentence's end


HEADING_CHARS = 80  # a line up to this long, over a list, with no sentence end: its heading


def _heading(line: str, after: list[str]) -> bool:
    """Whether `line` is a heading over the list that follows: not a step itself, short, with no
    sentence end (or ending with ":"), and the next line with words is a numbered or bulleted
    step."""
    text = line.strip()
    if not text or _STEP.match(line) or len(text) > HEADING_CHARS or (text[-1] in ".!?;," and not text.endswith(":")):
        return False
    following = next((x for x in after if x.strip()), "")
    return bool(_STEP.match(following))


def _all_parts(rule: str | None) -> list[str]:
    """Every part of a rule, by whole step: a numbered or bulleted line ("1.", "2)", "-", "*",
    "•") is one part, whatever its commas and sentences; any other line, one part per
    sentence, but a heading over a list is no part (_heading). Never at commas, ";", "and" or
    "or". No template part ({{ ... }})."""
    parts: list[str] = []
    lines = (rule or "").splitlines()
    for k, line in enumerate(lines):
        if _heading(line, lines[k + 1:]):
            continue
        if _STEP.match(line):
            parts.append(_STEP.sub("", line))
        else:
            parts += _SENTENCE.split(line)
    parts = [p.strip().rstrip(".!?:,;").strip() for p in parts]
    return [p for p in dict.fromkeys(parts) if p and "{" not in p and len(p.split()) >= 2]


def split_rule(rule: str | None) -> list[str]:
    """The parts of a rule (_all_parts), whole. At most MAX_PARTS: the first ones and the last
    (a rule often ends with what to fail). Fewer than two parts: none (the general buttons are
    enough). The one splitting everywhere rule parts show (the result page, mistakes.md and
    suggestions.md), so their numbers match."""
    parts = _all_parts(rule)
    if len(parts) > MAX_PARTS:
        parts = parts[:MAX_PARTS - 1] + parts[-1:]
    return parts if len(parts) > 1 else []


def _rule(data: dict) -> str | None:
    """The rule's text for a check whose start.json is `data`: none without one rule for every
    answer."""
    from judgekeeper.start_fix_rule import rule_text

    if not data.get("rule") or not data.get("one_rule", True):
        return None
    return rule_text(data["rule"], data.get("tool") or "")


def rule_parts(data: dict) -> list[str]:
    """The rule's parts (split_rule) for a check whose start.json is `data`."""
    return split_rule(_rule(data))


def parts_left_out(data: dict) -> int:
    """How many of the rule's parts have no button (more than MAX_PARTS)."""
    return max(len(_all_parts(_rule(data))) - MAX_PARTS, 0)


# The answer's text the spans point into -------------------------------------------------------

def canonical(text: str) -> str:
    """An answer as the result page shows it, before any cut: one kind of line break and no
    hidden character, so an offset counted in the browser points at the same words here."""
    return visible(text.replace("\r\n", "\n").replace("\r", "\n"))


def marked(text: str, spans) -> list[str]:
    """The words of `spans` in an answer's canonical text."""
    return [text[s:e] for s, e in spans or [] if 0 <= s < e <= len(text)]


def cleaned(text: str) -> str:
    """A file's whole text (mistakes.md, suggestions.md): one kind of line break and no
    hidden character (ESC, BEL, bidirectional controls, invisible marks), and no Unicode line
    or paragraph separator (each a space)."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return visible(text.replace(" ", " ").replace(" ", " "))


def merged(spans, length: int) -> list[tuple[int, int]]:
    """`spans` inside the first `length` characters, sorted, overlaps joined."""
    out: list[list[int]] = []
    for s, e in sorted((max(0, s), min(e, length)) for s, e in spans or []):
        if s >= e:
            continue
        if out and s <= out[-1][1]:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return [(s, e) for s, e in out]


def bold(text: str, spans) -> str:
    """`text` with each span in **bold** (mistakes.md)."""
    for s, e in reversed(merged(spans, len(text))):
        text = f"{text[:s]}**{text[s:e]}**{text[e:]}"
    return text


# reasons.json: the person's own buttons, and when the judge's grades were first shown --------

def _path(ws) -> Path:
    return ws.dir / FILE


def _own_id(value) -> bool:
    number = value[len(OWN):] if isinstance(value, str) and value.startswith(OWN) else ""
    return number.isascii() and number.isdigit()


def read_file(ws) -> dict:
    """reasons.json, checked: {"own": the first MAX_OWN buttons, each cut to MAX_NOTE,
    "next": a number when it is one, "grades_shown_at": text when it is}. A file over MAX_FILE,
    or one that can't be read, holds none."""
    try:
        with _path(ws).open("rb") as f:
            raw = f.read(MAX_FILE + 1)
        data = json.loads(raw.decode("utf-8")) if len(raw) <= MAX_FILE else None
    except (OSError, ValueError, RecursionError):
        data = None
    if not isinstance(data, dict):
        return {"own": []}
    chips = data.get("own") if isinstance(data.get("own"), list) else []
    own = [{**c, "text": c["text"][:MAX_NOTE]} for c in chips
           if isinstance(c, dict) and _own_id(c.get("id")) and isinstance(c.get("text"), str)
           and c["text"]][:MAX_OWN]
    out = {"own": own}
    if isinstance(data.get("next"), int) and not isinstance(data["next"], bool):
        out["next"] = data["next"]
    if isinstance(data.get("grades_shown_at"), str):
        out["grades_shown_at"] = data["grades_shown_at"]
    return out


def _write(ws, data: dict) -> None:
    from judgekeeper import marks

    path = _path(ws)
    marks._refuse_links(path)
    make_private(path.parent)
    write_replacing(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def same_words(a: str, b: str) -> bool:
    """Whether two notes are the same words, as a button matches them: any case, one space
    between words."""
    return " ".join(a.split()).casefold() == " ".join(b.split()).casefold()


def own_chips(ws) -> list[dict]:
    """The person's own buttons: [{"id", "text", "from": the answer whose box it was typed in}]."""
    return read_file(ws)["own"]


def sync_own(ws, item_id: str, note: str | None, tapped: set[str]) -> None:
    """After `item_id`'s "Other…" box was saved: its button follows the words in the box (one
    button per box, so typing on never makes a button per save); an empty box removes it,
    unless another answer tapped it (`tapped`). A button another answer tapped keeps its words:
    new words in the box make a new button. A new button only while there are fewer than
    MAX_OWN, and not for words a button already has."""
    if note is None:
        return
    data = read_file(ws)
    own = data["own"]
    mine = next((c for c in own if c.get("from") == item_id), None)
    text = " ".join(note.split())
    if mine is not None and mine["id"] in tapped and text.casefold() != mine["text"].casefold():
        mine["from"] = None  # what the other answers tapped stays as they tapped it
        mine = None
    taken = {c["text"].casefold() for c in own if c is not mine} | {
        w.casefold() for w, _ in REASONS.values()}
    if mine is not None and (not text or text.casefold() in taken):
        if mine["id"] in tapped:
            mine["from"] = None
        else:
            own.remove(mine)
        mine = None
    if text and text.casefold() not in taken:
        if mine is not None:
            mine["text"] = text
        elif len(own) < MAX_OWN:
            n = max((int(c["id"][len(OWN):]) for c in own), default=0) + 1
            n = max(n, data.get("next") or 1)
            own.append({"id": f"{OWN}{n}", "text": text, "from": item_id})
            data["next"] = n + 1
    _write(ws, data)


def saw_grades(ws) -> None:
    """The judge's grade on single answers was shown (a result page with disagreements): marks
    changed from now on are stamped "after_result"."""
    data = read_file(ws)
    if not data.get("grades_shown_at"):
        data["grades_shown_at"] = utc_now()
        _write(ws, data)


def grades_shown(ws) -> bool:
    return bool(read_file(ws).get("grades_shown_at"))


# Checking a post ------------------------------------------------------------------------------

def _disagreements_shown(ws) -> bool:
    """Whether the judge's grades on single answers were shown: `fix` wrote mistakes.md, or
    the page of the saved result lists the disagreements. Before that, no answer has a
    reason box."""
    from judgekeeper import fix
    from judgekeeper.report_page import shows_disagreements

    if (ws.dir / fix.FOLDER / fix.MISTAKES).is_file():
        return True
    try:
        r = json.loads(ws.result_json.read_text(encoding="utf-8"))
        return isinstance(r, dict) and shows_disagreements(r)
    except (OSError, ValueError, KeyError, TypeError, RecursionError):
        return False


def check(ws, item_id: str, mark: str | None, judge: str | None, body: dict,
          before: dict | None = None) -> dict:
    """The fields of a reason line from a post (`body`: "reasons", "note", "rule_parts",
    "spans"), checked; a ValueError says what is wrong. A field the post leaves out keeps its
    value in `before` (the answer's line now). Only for an answer marked Pass or Fail that the
    judge graded the other way, on the marks the person can see, once the disagreements were
    shown; every other answer gets the same NOT_LISTED."""
    from judgekeeper import fix

    if mark not in ("pass", "fail"):
        raise ValueError("mark this answer Pass or Fail first")
    split = fix.shown_split(ws)[1] if _disagreements_shown(ws) else None  # before any grade
    if split is None or item_id in split.hidden or item_id not in split.seen or judge == mark:
        raise ValueError(NOT_LISTED)
    data = ws.data()
    own = {c["id"] for c in own_chips(ws)}
    saved = of_line(before)
    body = {"reasons": saved["reasons"], "note": saved["note"],
            "rule_parts": saved["rule_parts"] if saved["rule_hash"] == rule_hash(data.get("rule"))
            else [], "spans": saved["spans"], **body}
    got = body.get("reasons", [])
    if not isinstance(got, list) or not all(isinstance(r, str) for r in got) or \
            len(set(got)) != len(got):
        raise ValueError("reasons must be a list of reason ids, each once")
    unknown = [r for r in got if r not in REASONS and r not in own]
    if unknown:
        raise ValueError(f"unknown reason: {unknown[0]}")
    other_side = [r for r in got if r in REASONS and r not in offered(judge)]
    if other_side:  # only a program sends these: the page shows each side its own
        raise ValueError(f"reason {other_side[0]} is not asked on this answer")
    out: dict = {"reasons": list(got)}
    note = body.get("note")
    if note is not None:
        if not isinstance(note, str):
            raise ValueError("note must be a string")
        if len(note) > MAX_NOTE:
            raise ValueError(f"a reason can be at most {MAX_NOTE} characters")
        if note.strip():
            out["note"] = scrub(note.strip())
    parts = body.get("rule_parts") or []
    count = len(rule_parts(data))
    if not isinstance(parts, list) or len(set(map(repr, parts))) != len(parts) or not all(
            isinstance(n, int) and not isinstance(n, bool) and 1 <= n <= count for n in parts):
        raise ValueError(f"rule_parts must be part numbers from 1 to {count}, each once")
    if parts:
        out["rule_parts"] = sorted(parts)
        out["rule_hash"] = rule_hash(data.get("rule"))
    spans = body.get("spans") or []
    length = len(canonical(_output(ws, item_id)))
    if not isinstance(spans, list) or len(spans) > MAX_SPANS or not all(
            isinstance(s, list) and len(s) == 2
            and all(isinstance(x, int) and not isinstance(x, bool) for x in s)
            and 0 <= s[0] < s[1] <= length for s in spans):
        raise ValueError(f"spans must be at most {MAX_SPANS} [start, end] pairs inside the "
                         "answer")
    if spans:
        out["spans"] = [list(s) for s in spans]
    return out


def _output(ws, item_id: str) -> str:
    from judgekeeper.start_label import display
    from judgekeeper.textio import jsonl_lines

    for line in jsonl_lines(ws.pool.read_text(encoding="utf-8")):
        if line.strip():
            row = json.loads(line)
            if row.get("id") == item_id:
                return display(row.get("output"))
    return ""


def of_line(line: dict | None) -> dict:
    """A marks line's reasons, as the page and `fix` read them."""
    line = line or {}
    return {"reasons": [r for r in line.get("reasons") or [] if isinstance(r, str)],
            "note": str(line.get("note") or ""),
            "rule_parts": [n for n in line.get("rule_parts") or [] if isinstance(n, int)],
            "rule_hash": line.get("rule_hash"),
            "spans": [s for s in line.get("spans") or []
                      if isinstance(s, list) and len(s) == 2
                      and all(isinstance(x, int) for x in s)]}


# Counting: `fix`'s clues and suggestions.md ----------------------------------------------------
# A row (fix.Marks.row): "id", "judge", "final", "output", "reason" (the judge's), "why" (the
# note), "reasons" (ids, an own button's id on the answer it was typed for), "words" ({own id:
# its words}), "parts" ([[n, words]]), "spans".

def _words(row: dict, key: str, own: dict | None = None) -> str:
    """A reason as a line says it: a button's name, the person's own words in quotes, or in a
    file (`own`, own_numbers) "your own reason 1", its words fenced apart."""
    if key in REASONS:
        return lower(REASONS[key][0])
    if own and key in own:
        return f"your own reason {own[key]}"
    return f"“{one_line(row.get('words', {}).get(key, key))}”"


OWN_FENCE = "YOUR REASON {n}"


def own_numbers(rows: list[dict]) -> dict[str, int]:
    """The person's own reasons, numbered 1.. most-tapped first: in mistakes.md each is named
    by its number and its words sit in a fence (OWN_FENCE), never in a line."""
    counts = tally(rows)
    return {k: n for n, k in enumerate((k for k in _order(counts) if k.startswith(OWN)), 1)}


def own_fences(rows: list[dict], own: dict[str, int], fence) -> list[str]:
    """Each own reason's words in its fence (OWN_FENCE), in its number's order."""
    words = {}
    for r in rows:
        for k in r.get("reasons") or []:
            if k in own:
                words.setdefault(k, one_line(r.get("words", {}).get(k, k)))
    return [fence(OWN_FENCE.format(n=n), words[k]) for k, n in own.items()]


def tally(rows: list[dict]) -> Counter:
    """How often each reason was tapped, but "not sure"."""
    return Counter(k for r in rows for k in r.get("reasons") or [] if k != UNSURE)


def has_any(rows: list[dict]) -> bool:
    return any(r.get("reasons") or r.get("why") or r.get("parts") or r.get("spans")
               for r in rows)


def _names(rows: list[dict], own: dict | None = None) -> dict[str, str]:
    out: dict[str, str] = {}
    for r in rows:
        for k in r.get("reasons") or []:
            out.setdefault(k, _words(r, k, own))
    return out


def _order(counts: Counter) -> list[str]:
    known = list(REASONS)
    return sorted(counts, key=lambda k: (-counts[k], known.index(k) if k in known else 99, k))


def mentioned(rows: list[dict]) -> tuple[int, int]:
    """Of the answers the judge passed and the person failed with words marked: (how many the
    judge's reason mentions, how many it doesn't). Mentioned: any number, or any word of four
    letters or more that is not a common word, of a marked part is in the reason, ignoring
    case. Rough, so the lines say "seems"."""
    from judgekeeper.fix import STOPWORDS

    yes = no = 0
    for r in rows:
        if r.get("judge") != "pass" or not r.get("spans"):
            continue
        text = " ".join(marked(canonical(r.get("output") or ""), r["spans"])).lower()
        words = set(re.findall(r"\d+(?:[.,]\d+)?", text)) | {
            w for w in re.findall(r"[^\W\d_]{4,}", text) if w not in STOPWORDS}
        reason = (r.get("reason") or "").lower()
        if any(re.search(rf"(?<!\w){re.escape(w)}(?!\w)", reason) for w in words):
            yes += 1
        else:
            no += 1
    return yes, no


def clue_lines(rows: list[dict], fence=None) -> list[str]:
    """The first clue, from the person's reasons on the mistakes they can see: the reasons
    counted, a line when "the rule doesn't say" or "wrong fact" (on the judge's passes) was
    tapped TWICE or more, the rule parts tapped TWICE or more, the "missed it or allowed it"
    check on the answers with words marked, and how many marks the person wasn't sure
    about. `fence` (start_fix_rule.fenced, for mistakes.md) puts a rule part's words in a
    fence below its line, and the person's own reasons by number, their words fenced below
    the reasons counted."""
    own = own_numbers(rows) if fence is not None else {}
    counts, names = tally(rows), _names(rows, own)
    out = []
    if counts:
        out.append("\n".join(["Your reasons for your LLM-as-a-judge's mistakes: "
                              + ", ".join(f"{names[k]} ({counts[k]})" for k in _order(counts))
                              + ".", *own_fences(rows, own, fence)]))
    if counts["rule_silent"] >= TWICE:
        out.append("Your LLM-as-a-judge's rule may be missing something: write in it how to "
                   "judge these answers.")
    if sum("wrong_fact" in (r.get("reasons") or []) for r in rows
           if r.get("judge") == "pass") >= TWICE:
        out.append("Your LLM-as-a-judge says Pass on answers with wrong facts: say in the rule "
                   "that one wrong fact is a Fail.")
    parts = Counter((n, text) for r in rows for n, text in r.get("parts") or [])
    for (n, text), k in sorted(parts.items(), key=lambda x: (-x[1], x[0][0])):
        if k >= TWICE and fence is not None:  # the rule's words are data: fenced below
            out.append(f"Your marks say your LLM-as-a-judge misses rule part {n} ({k}):\n"
                       + fence(RULE_PART, one_line(text)))
        elif k >= TWICE:
            out.append(f"Your marks say your LLM-as-a-judge misses rule part {n}, "
                       f"'{one_line(short(text))}' ({k}).")
    yes, no = mentioned(rows)
    if no:
        out.append(f"Your LLM-as-a-judge didn't mention the part you marked in {no} of "
                   f"{yes + no} answers: it seems to miss these problems. A clearer rule may "
                   "help, or a stronger model.")
    if yes:
        out.append(f"In {plural(yes, 'answer')} your LLM-as-a-judge mentioned the part you "
                   "marked but still said Pass: your rule seems to allow this. Say in the rule "
                   "that it's a Fail.")
    for text, hits in notes(rows):
        if len(hits) >= TWICE and fence is not None:  # the person's words: fenced below
            out.append(f"You wrote the same note on {len(hits)} answers:\n"
                       + fence("YOUR REASON", text))
        elif len(hits) >= TWICE:
            out.append(f"You wrote the same note on {len(hits)} answers: “{text}”.")
    unsure = sum(UNSURE in (r.get("reasons") or []) for r in rows)
    if unsure:
        out.append(f"You weren't sure about {unsure} of your marks: they're listed last in "
                   "mistakes.md.")
    return out


def notes(rows: list[dict]) -> list[tuple[str, list[dict]]]:
    """Each note of the person's once, on one line, with the answers it was given on, the
    most given first: counted the same in the terminal and in suggestions.md. A note that is
    the words of their own button, or what an answer leaves out, is said with that."""
    out: dict[str, list[dict]] = {}
    for r in rows:
        own = r.get("words", {}).values()
        if r.get("why") and not any(same_words(r["why"], w) for w in own) and \
                "left_out" not in (r.get("reasons") or []):
            out.setdefault(one_line(r["why"]), []).append(r)
    return sorted(out.items(), key=lambda x: -len(x[1]))


def said_line(row: dict, own: dict | None = None) -> str | None:
    """"You said: ..." for one mistake in mistakes.md: the reasons tapped (the person's own by
    number, `own`), the rule parts by number, and the marked words (in bold in the answer).
    The note is fenced, not here."""
    said = [_words(row, k, own) for k in row.get("reasons") or [] if not k.startswith(OWN)]
    said += [_words(row, k, own) for k in row.get("reasons") or [] if k.startswith(OWN)
             and not same_words(row.get("words", {}).get(k, ""), row.get("why") or "")]
    said += [f"rule part {n}" for n, _ in row.get("parts") or []]
    if row.get("spans"):
        said.append("the words in bold")
    return f"You said: {'; '.join(said)}." if said else None


def groups(rows: list[dict], own: dict | None = None) -> list[tuple[str, list[dict]]]:
    """The mistakes grouped by their most-tapped reason (the reason of theirs tapped most over
    all mistakes), most-tapped group first; then those with none, then those the person wasn't
    sure about, last. `own`: the person's own reasons by number (own_numbers)."""
    counts, names = tally(rows), _names(rows, own)
    keyed: dict[str, list[dict]] = {}
    for r in rows:
        if UNSURE in (r.get("reasons") or []):
            key = UNSURE
        else:
            mine = [k for k in r.get("reasons") or [] if k != UNSURE]
            key = _order(Counter({k: counts[k] for k in mine}))[0] if mine else ""
        keyed.setdefault(key, []).append(r)
    order = [k for k in _order(Counter({k: counts[k] for k in keyed if k not in ("", UNSURE)}))]
    out = [(f"Your reason: {names[k]} ({len(keyed[k])})", keyed[k]) for k in order]
    if "" in keyed:
        out.append(("No reason given", keyed[""]))
    if UNSURE in keyed:
        out.append(("You weren't sure about your mark", keyed[UNSURE]))
    return out


# suggestions.md ---------------------------------------------------------------------------------

TEMPLATES = {
    "wrong_fact": "Fail an answer with any wrong fact, even a small one.",
    "no_answer": "Fail an answer that doesn't answer the question asked.",
    "left_out": "Fail an answer that leaves out {words}.",
    "unsafe": "Fail an answer that is unsafe or not allowed.",
    "format_tone": "Fail an answer with the wrong format or tone.",
    "worded_differently": "Pass a correct answer even when its words differ from what you "
                          "expect.",
    "small_slips": "Small slips in spelling or format don't make an answer Fail.",
    "short_ok": "A short answer that answers the question is a Pass.",
    "not_asked": "Don't fail an answer for leaving out something the question didn't ask for.",
    "rule_silent": "Your rule doesn't cover {n} answers: write how to judge them.",
}
PART_LINE = "Make rule part {n} more exact: your LLM-as-a-judge missed it {times}."
RULE_PART = "RULE PART"  # the fence its words go in: data, as an answer's
MARKED_PART = "MARKED PART"  # the words of an answer the person marked
SUGGESTIONS = "suggestions.md"
SHOWN = 300  # characters of an answer in suggestions.md


def _line(key: str, side: str, hits: list[dict]) -> tuple[str, list[str]]:
    """A suggested line, and the notes it stands for (fenced below it: the words are data)."""
    if key.startswith(OWN):  # the person's words are data: fenced below
        words = one_line(hits[0].get("words", {}).get(key, key))
        return (f"{'Fail' if side == 'pass' else 'Pass even'} when what you wrote below is "
                f"true"), [words]
    notes = [r["why"] for r in hits if r.get("why")] if key == "left_out" else []
    words = "what you wrote below" if notes else "something important"
    return TEMPLATES[key].format(n=len(hits), words=words), notes


def suggestions(rows: list[dict]) -> tuple[list[tuple[str, int, list]], list[tuple[str, list,
                                                                                    list]]]:
    """(suggested lines with their counts and notes: each reason tapped TWICE or more, by the
    side it was tapped on; seen once: [(line, the answers, notes)] for each reason, rule part,
    marked part and own words given only once). "Not sure" is about the person's mark: it
    makes no line. Every word of the person's on a line is on one line, with no hidden
    character; their notes are fenced apart."""
    by: dict[tuple[str, str], list[dict]] = {}
    for r in rows:
        for k in r.get("reasons") or []:
            if k != UNSURE and (k in TEMPLATES or k.startswith(OWN)):
                side = r["judge"] if k.startswith(OWN) else ""
                by.setdefault((k, side), []).append(r)
    known = list(REASONS)
    keys = sorted(by, key=lambda x: (-len(by[x]), known.index(x[0]) if x[0] in known else 99,
                                     x))
    suggested = [(*_line(k, s, by[(k, s)]), len(by[(k, s)])) for k, s in keys
                 if len(by[(k, s)]) >= TWICE]
    suggested = [(line, n, notes) for line, notes, n in suggested]
    once = [(line, by[(k, s)], notes) for k, s in keys if len(by[(k, s)]) < TWICE
            for line, notes in [_line(k, s, by[(k, s)])]]
    parts: dict[tuple[int, str], list[dict]] = {}
    for r in rows:
        for n, text in r.get("parts") or []:
            parts.setdefault((n, text), []).append(r)
    for (n, text), hits in sorted(parts.items(), key=lambda x: (-len(x[1]), x[0][0])):
        line = PART_LINE.format(n=n, times=plural(len(hits), "time"))
        data = [(RULE_PART, one_line(text))]
        (suggested.append((line, len(hits), data)) if len(hits) >= TWICE
         else once.append((line, hits, data)))
    for text, hits in notes(rows):
        (suggested.append(("Your own words", len(hits), [text])) if len(hits) >= TWICE
         else once.append(("Your own words", hits, [text])))
    for r in rows:
        text = canonical(r.get("output") or "")
        for words in marked(text, merged(r.get("spans"), len(text))):  # as mistakes.md joins
            once.append(("The part you marked:", [r],  # answer text: fenced, as the answer
                         [(MARKED_PART, one_line(" ".join(words.split())))]))
    return suggested, once


def suggestions_md(rows: list[dict]) -> str:
    """.judgekeeper/fix/suggestions.md: the suggested rule lines from the person's reasons on
    the marks they can see, then everything given once, each with its answer fenced as data.
    The warning comes before any of the person's words, and each note is fenced."""
    from judgekeeper.start_fix_rule import DATA_WARNING, MARKS, fenced

    suggested, once = suggestions(rows)
    parts = ["# Suggested rule lines", "",
             ("From your reasons on the answers you can see, counted (no AI). Copy the ones you "
              "agree with into your rule where your eval keeps it. judgekeeper never changes "
              "your rule itself."), ""]
    if suggested or once:
        parts += [f"{DATA_WARNING} {MARKS}", ""]
    def fence(note) -> str:  # the person's note, or a rule part's words (RULE_PART)
        return fenced(*note) if isinstance(note, tuple) else fenced("YOUR REASON",
                                                                     one_line(note))

    for line, n, notes in suggested:
        parts.append(f"- {line} ({plural(n, 'answer')})")
        parts += [fence(note) for note in notes]
    if not suggested:
        parts.append("None yet: a line is suggested once a reason is given on 2 answers.")
    parts += ["", "## Seen once (not suggested yet)", ""]
    for line, hits, notes in once:
        parts.append(f"- {line}")
        parts += [fence(note) for note in notes]
        for r in hits:
            parts.append(fenced("ANSWER", canonical(r.get("output") or "")[:SHOWN]))
        parts.append("")
    if not once:
        parts.append("Nothing.")
    return cleaned(scrub("\n".join(parts).rstrip("\n") + "\n"))
