"""Did your change help? Two graded results, compared question by question.

Each question is its test-case id when the file has its own (start._names_cases), else its
text (no_grades.question_key); its grades are the Pass or Fail of every answer to it in the newest
results. A question is fixed when it failed before and passes now,
and broke when it passed before and fails now (no_grades._fixed and _broke, as they count marks
for answers with no grade). The verdict is no_grades.change_kind at one test: each run is
compared with one baseline, so nothing is corrected for several tests.

The baseline is the results judgekeeper read last in the project (`last-graded.json` in
.judgekeeper/: hashes of each question and of each answer with its question and steps, and
grades, never a question or an answer), or `--before FILE`.
The same results read again are no new baseline, so a run says the same each time. Grades from
another setup of the LLM-as-a-judge (another model, rule or pass mark) say nothing about a
change to the AI: the file keeps a hash of the setup, and a new one starts it again.

Exit 1 on "made it worse" (front.py): this is what a pipeline fails on. Exit 3 when nothing
could be compared (no question in both, or `--before` graded by another setup): a gate never
passes on nothing. With `--before` or in CI the comparison alone sets the exit code.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from judgekeeper import no_grades, start
from judgekeeper.records import RecordsError
from judgekeeper.start import StartError, Stop
from judgekeeper.textio import loads, make_private, path_arg, plural, write_replacing

FILE = "last-graded.json"  # in .judgekeeper/: the results read last and the ones before
# its setup after `check` took on another LLM-as-a-judge's grades (restart): the next results
# start again, as for another setup, whatever their own setup's hash
RESTART = "restart"
EXIT_WORSE = 1

COMPARED = "On the {questions} in both results: fixed {fixed}, broke {broke}, same {same}."
COUNTED = "Counted from the grades in your results, not from your marks."
LEFT_OUT = {1: "{n} question is in only one of the two results and is left out.",
            2: "{n} questions are in only one of the two results and are left out."}
NO_GRADE = {1: "{n} question has no Pass or Fail grade in one of the results and is left out.",
            2: "{n} questions have no Pass or Fail grade in one of the results and are left out."}
REGRADED_LEFT = {
    1: "{n} question with the same answers and another grade is left out.",
    2: "{n} questions with the same answers and other grades are left out."}
NEXT_WORSE = "Next: fix what broke or undo your change, then run your eval again."
NO_MATCH = "No question is in both results, so there is nothing to compare."
NO_MATCH_NEXT = ("Next: give each question an id that stays the same from run to run (such as "
                 "an `id` column), then run your eval again.")
NO_MATCH_IDS_NEXT = ("Next: check that you compare results of the same eval: the two share no "
                     "question id.")
NO_IDS_ONE_SIDE = ("Only one of the two results names its questions by an id, so judgekeeper "
                   "can't tell which questions are the same, and compares nothing.")
NOTHING_GRADED = ("No question has a Pass or Fail grade in both results, so there is nothing to "
                  "compare.")
NOTHING_GRADED_NEXT = ("Next: check why your LLM-as-a-judge gave no Pass or Fail grade, then run "
                       "your eval again.")
RESTARTED = ("Your LLM-as-a-judge setup changed since the last results, so there is nothing to "
             "compare yet. This run is the new starting point.")
OTHER_SETUP = ("The two results were graded by different LLM-as-a-judge setups (the model, rule "
               "or pass mark changed), so judgekeeper does not compare them.")
OTHER_SETUP_NEXT = "Next: compare results graded by the same LLM-as-a-judge setup."
# --before on results that don't say who graded them, told apart only by the bytes of the
# results a check replaced (_one_replaced): the same LLM-as-a-judge may have graded both
UNSURE_SETUP = ("judgekeeper can't tell whether the same LLM-as-a-judge graded both results, "
                "so it does not compare them.")
UNSURE_SETUP_NEXT = "Next: compare two results you know the same LLM-as-a-judge graded."
UNSURE = "unsure"  # _two_judges: only the replaced bytes tell the two apart
# Results that don't say who graded them, with only grades changed on the same answers: the
# setup may have changed, or the same one graded otherwise (regraded_only)
ONLY_GRADES = ("Only the grades changed since the last results, not the answers, so there is "
               "nothing to compare. This run is the new starting point.")
# last-graded.json as judgekeeper 1.4.0 wrote it: no answer hashes to tell an agent change by
OLDER = ("Your last results were saved by an older judgekeeper, so there is nothing to compare "
         "yet. This run is the new starting point.")
ONLY_GRADES_BEFORE = ("Only the grades changed between the two results, not the answers, so "
                      "judgekeeper does not compare them.")
NUMBERED_IDS = ("The questions changed and their ids are plain numbers, so judgekeeper can't tell "
                "they are the same questions.")
NUMBERED_IDS_NEXT = ("run `{command} --before FILE`, with your earlier results as FILE, to "
                     "compare them, or put {file} in a folder of its own to mark it.")
UNREAD = ("judgekeeper can't tell which of the LLM-as-a-judge's decisions in {name} mean Pass "
          "and which mean Fail: {values}.")
LONG_TEXT = "some hold long text"
CANT_READ = ("{name} can't be read the way your results are, so there is nothing to compare "
             "with.")
CANT_READ_NEXT = "give the results file from before your change to --before, then run `{command}`."


@dataclass(frozen=True)
class Comparison:
    n: int  # questions graded in both
    fixed: int
    broke: int
    only: int  # questions in only one of the two, left out
    kind: str  # no_grades.CHANGE's key
    ungraded: int = 0  # in both, with no Pass or Fail grade in one of them: left out
    ids: bool = False  # both name each question by its own id
    one_side_ids: bool = False  # only one of the two does: their questions can't be matched
    regraded: int = 0  # graded otherwise on the same answers: the LLM-as-a-judge's, left out
    changed: int = 0  # in both, with answers that changed or may have (their hashes compared)
    left_out: tuple[str, ...] = ()  # fields new on every answer, the answers the same (_noise)

    @property
    def same(self) -> int:
        return self.n - self.fixed - self.broke

    @property
    def worse(self) -> bool:
        return self.kind == "worse"

    @property
    def exit_code(self) -> int | None:
        """1 when it made it worse, 3 when nothing was compared, else None (the run's own)."""
        return EXIT_WORSE if self.worse else None if self.n else start.EXIT_QUESTION


def grades_of(found: start.Found, numbers: bool = False) -> dict:
    """The newest results' grades as one side of last-graded.json: {"questions": {question
    key: [Pass or Fail of each of its answers]}, "ids": whether each is named by its own id}.
    Not the older results the pool may hold beside them. A question with no Pass or Fail
    grade is there with none. An id that is a plain number names a question only with
    `numbers` (--before: the person chose both files); else its text does. An answer with no
    question text has only its id, so its id is kept."""
    from judgekeeper.project import plain_number

    newest = found.used[0] if found.used else None
    # the answer as the agent gave it: its text and its steps and outcome (records, Inspect AI)
    # and what else of it the grade follows (records.Mark's graded_on and graded_unread)
    answers = [(a.case, a.input, a.verdict, (a.output, a.agent.get("trajectory"),
                                             a.agent.get("outcome"), a.mark))
               for a in found.pool.answers if a.source == newest]
    answers += [(case, r.input, None, (r.output, r.trajectory, r.outcome, r.mark))
                for i, (source, case) in found.pool.left_from.items()
                for r in [found.pool.left[i][1]] if source == newest]  # no Pass or Fail grade
    answers = [(c if c is not None and (numbers or not plain_number(c) or _blank(q)) else None,
                q, v, o) for c, q, v, o in answers]
    sums, fields = _answer_sums(answers)
    side = {"questions": _grades([(c, q, v) for c, q, v, _ in answers]), "answers": sums,
            "ids": bool(answers) and all(case is not None for case, _, _, _ in answers)}
    if fields:
        side["fields"] = fields
    return side


BLANK = "-"  # an answer the results don't hold at all: whether it changed is not known


def _ends(text):
    """Text as an answer is compared: Windows line ends as \n, no spaces at its two ends.
    Every space inside it counts."""
    return text.replace("\r\n", "\n").strip() if isinstance(text, str) else text


def _answer_sums(answers) -> tuple[dict[str, list[str]], dict[str, list]]:
    """{question key: a hash of each of its answers}: whether the answers changed, never
    their text. Each hash holds the whole question (a prompt changed inside it, under the same
    id, is a change), the answer, and its steps and outcome (output, trajectory, outcome),
    their texts without the spaces at their ends (_ends), and what else of the case the grade
    follows (mark.graded_on, and mark.graded_fields but the ones the same on every answer of
    the file: a run number, a date). An answer whose grade follows something the results don't
    hold (mark.graded_unread) is BLANK: compared, as an answer that may have changed. With
    them, for a question with one answer: [the hash of all but its fields, {field: its hash}],
    so compare can tell a field new on every answer (_noise)."""
    from judgekeeper.table import ID_LENGTH, canonical_json

    def digest(data) -> str:
        return hashlib.sha256(canonical_json(data).encode(
            "utf-8", errors="surrogatepass")).hexdigest()[:ID_LENGTH]

    per_run = _per_run([mark.graded_fields for *_, (_, _, _, mark) in answers])
    out: dict[str, list[str]] = {}
    parts: dict[str, list] = {}
    for case, question, _, (output, trajectory, outcome, mark) in answers:
        fields = [list(f) for f in mark.graded_fields or () if f not in per_run]
        every = mark.graded_fields or ()  # _noise sees them all: a field one file fills alike
        base = ["answer", _ends(question), _ends(output), trajectory, outcome] + (
            [mark.graded_on] if mark.graded_on else [])
        blank = mark.graded_unread or (  # empty is an answer
            output is None and trajectory is None and outcome is None)
        key = _key(case, question)
        out.setdefault(key, []).append(BLANK if blank else digest(
            base + ([fields] if fields else [])))
        if every and not blank:
            parts.setdefault(key, []).append([digest(base), {f: h[:8] for f, h in every}])
    return ({k: sorted(v) for k, v in out.items()},
            {k: v[0] for k, v in parts.items() if len(v) == 1 and len(out[k]) == 1})


def _per_run(fields: list) -> set:
    """The (name, value) fields that every answer of a file has the same: what a run gives
    each of its rows (a run number, a date, a version), not an answer of its own. None with
    fewer than two answers."""
    if len(fields) < 2 or any(not f for f in fields):
        return set()
    same = set(fields[0])
    for f in fields[1:]:
        same &= set(f)
        if not same:
            break
    return same


def _blank(question) -> bool:
    """Whether a question has no text to name it by."""
    return question is None or (isinstance(question, str | list | dict) and not (
        question.strip() if isinstance(question, str) else question))


def _grades(answers) -> dict[str, list[str]]:
    """{question key: its grades} of (Answer.case, question, verdict) triples."""
    out: dict[str, list[str]] = {}
    for case, question, verdict in answers:
        grades = out.setdefault(_key(case, question), [])
        if verdict in ("pass", "fail"):
            grades.append(verdict)
    return {k: sorted(v) for k, v in out.items()}


def _key(case: str | None, question) -> str:
    """A question: its test-case id when the file has its own (a table's id column), so a new
    prompt written into each question is still the same case; else its text. Hashed."""
    if case is None:
        return no_grades.question_key(question)
    from judgekeeper.table import ID_LENGTH, canonical_json

    data = canonical_json(["case", case]).encode("utf-8", errors="surrogatepass")
    return hashlib.sha256(data).hexdigest()[:ID_LENGTH]


def setup_of(found: start.Found) -> str:
    """A hash of what decides the grades: the LLM-as-a-judge's setup as judge.json keeps it
    (judge_setup.of: model, rule, prompt, temperature, pass mark...), the metric and the label
    map. Not the eval tool's version, which grades nothing, nor whether your own file is read
    by its column names or with a saved map. Never its text."""
    from judgekeeper import judge_setup
    from judgekeeper.redact import scrub
    from judgekeeper.table import canonical_json

    setup = {k: v for k, v in judge_setup.of(found).items()
             if k not in ("tool_version", "version_from")}
    setup["tool"] = judge_setup.grading_tool(setup.get("tool"))  # not how it is read
    data = canonical_json([setup, scrub(found.metric), found.pool.label_map])
    return hashlib.sha256(data.encode("utf-8", errors="surrogatepass")).hexdigest()


def compare(before: dict, now: dict) -> Comparison:
    """Two sides (grades_of): a question in both is compared when each has a grade for it."""
    b, n = before["questions"], now["questions"]
    both = b.keys() & n.keys()
    graded = {k for k in both if b[k] and n[k]}
    # the same answers graded otherwise: the LLM-as-a-judge's doing, not the agent's (when
    # both sides keep their answers: results read before 1.5.0 don't)
    sums = (before.get("answers"), now.get("answers"))
    unchanged = {k for k in both if None not in sums and k in sums[0]
                 and sums[0][k] == sums[1].get(k) and BLANK not in sums[0][k]}
    noise, alike = _noise(before.get("fields") or {}, now.get("fields") or {}, both)
    unchanged |= alike
    regraded = {k for k in graded if b[k] != n[k] and k in unchanged}
    graded -= regraded
    fixed = sum(no_grades._fixed(b[k], n[k]) for k in graded)
    broke = sum(no_grades._broke(b[k], n[k]) for k in graded)
    return Comparison(n=len(graded), fixed=fixed, broke=broke, only=len(b.keys() ^ n.keys()),
                      kind=no_grades.change_kind(fixed, broke, len(graded), test=1),
                      ungraded=len(both - graded - regraded), ids=before["ids"] and now["ids"],
                      one_side_ids=before["ids"] != now["ids"], regraded=len(regraded),
                      changed=len(both - unchanged) if None not in sums else 0,
                      left_out=noise)


EVERY_ANSWER = 5  # _noise: a field new on every answer of at least this many is per-run


def _noise(before: dict, now: dict, both: set) -> tuple[tuple[str, ...], set]:
    """The fields that changed on every answer compared (at least EVERY_ANSWER of them) while
    the rest of each answer stayed the same: per-run noise (a field each run fills anew), left
    out. A field that changed on only some is the agent's, and compared. With them, the
    questions whose answers are then the same."""
    rows = [k for k in both if k in before and k in now and before[k][0] == now[k][0]]
    if len(rows) < EVERY_ANSWER:
        return (), set()
    names = set().union(*(set(before[k][1]) | set(now[k][1]) for k in rows))
    noise = tuple(sorted(f for f in names
                         if all(before[k][1].get(f) != now[k][1].get(f) for k in rows)))
    if not noise:
        return (), set()

    def rest(fields: dict) -> dict:
        return {f: h for f, h in fields.items() if f not in noise}

    return noise, {k for k in rows if rest(before[k][1]) == rest(now[k][1])}


def regraded_only(c: Comparison | None) -> bool:
    """Only grades changed, on the same answers: nothing the agent did to compare. Every
    answer in both is the same, and no question is in one of them only; else what changed is
    compared as usual, without them. When nothing else has a grade in both, too."""
    return c is not None and bool(c.regraded) and not (c.fixed or c.broke) and (
        not (c.changed or c.only) or not c.n)


LEFT_OUT_EVERY = ("Left out of the comparison: {names}, which changed on every answer, like "
                  "{like}.")


def left_out_line(names: tuple[str, ...]) -> list[str]:
    """The line that names the fields _noise left out; [] for none."""
    if not names:
        return []
    shown = [f"`{_field_name(n)}`" for n in names]
    joined = shown[0] if len(shown) == 1 else ", ".join(shown[:-1]) + " and " + shown[-1]
    return [LEFT_OUT_EVERY.format(names=joined, like="a timestamp" if len(shown) == 1
                                  else "timestamps")]


def _field_name(path: str) -> str:
    """A field as the person wrote it: a column's name, or its place in a record."""
    where, _, rest = path.partition(":")
    if not rest:
        return path
    return rest if where == "extra" else f"{where}.{rest}"


def lines(c: Comparison) -> list[list[str]]:
    """What is said, in paragraphs: the counts and where they come from, then the result, then
    (when it is worse) the Next: line. With nothing compared, why and its Next: line."""
    if not c.n:
        if c.ungraded:
            return [[NOTHING_GRADED], [NOTHING_GRADED_NEXT]]
        return [[NO_MATCH], [NO_MATCH_IDS_NEXT if c.ids else NO_MATCH_NEXT]]
    left = [LEFT_OUT[min(c.only, 2)].format(n=c.only)] if c.only else []
    left += [NO_GRADE[min(c.ungraded, 2)].format(n=c.ungraded)] if c.ungraded else []
    left += [REGRADED_LEFT[min(c.regraded, 2)].format(n=c.regraded)] if c.regraded else []
    left += left_out_line(c.left_out)
    counted = [COMPARED.format(questions=plural(c.n, "question"), fixed=c.fixed, broke=c.broke,
                               same=c.same), COUNTED, *left]
    out = [counted, [no_grades.CHANGE[c.kind]]]
    if c.worse:
        out.append([NEXT_WORSE])
    return out


# The baseline: what the last two results read said ----------------------------------------------

def _path(ws) -> Path:
    return ws.dir / FILE


def _sum(d: dict) -> str:
    from judgekeeper.fix import _sum as checksum

    return checksum(d)


def _side(x) -> dict | None:
    """One side of the file as it is when it is as judgekeeper writes it: {"questions": {key:
    ["pass" or "fail", ...]}, "ids": bool} (a file with no "ids" names none)."""
    if x is None:
        return None
    sums = x.get("answers", {}) if isinstance(x, dict) else None
    fields = x.get("fields", {}) if isinstance(x, dict) else None
    ok = isinstance(x, dict) and set(x) - {"answers", "fields"} in (
        {"questions"}, {"questions", "ids"}) \
        and isinstance(x.get("ids", False), bool) and isinstance(x["questions"], dict) \
        and all(isinstance(k, str) and isinstance(v, list)
                and all(g in ("pass", "fail") for g in v) for k, v in x["questions"].items()) \
        and isinstance(sums, dict) and all(
            isinstance(k, str) and isinstance(v, list) and all(isinstance(h, str) for h in v)
            for k, v in sums.items()) \
        and isinstance(fields, dict) and all(
            isinstance(k, str) and isinstance(v, list) and len(v) == 2 and isinstance(v[0], str)
            and isinstance(v[1], dict) and all(isinstance(f, str) and isinstance(h, str)
                                               for f, h in v[1].items())
            for k, v in fields.items())
    if not ok:
        return False
    side = {"questions": {k: list(v) for k, v in x["questions"].items()},
            "ids": x.get("ids", False)}
    if "answers" in x:  # kept since 1.5.0: which answers changed
        side["answers"] = {k: list(v) for k, v in sums.items()}
    if fields:  # and the fields beside each, to tell one new on every answer (_noise)
        side["fields"] = {k: [v[0], dict(v[1])] for k, v in fields.items()}
    return side


def read(ws) -> dict | None:
    """last-graded.json as {"before": grades or None, "now": grades, "setup": setup_of's hash};
    None when there is none,
    it is a link, can't be read, is not as judgekeeper writes it or was changed by hand:
    nothing is compared, no error."""
    path = _path(ws)
    if path.is_symlink() or not path.is_file():
        return None
    try:
        d = loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(d, dict) or set(d) != {"before", "now", "setup", "sha256"} \
            or d["sha256"] != _sum(d) or not isinstance(d["setup"], str):
        return None
    before, now = _side(d["before"]), _side(d["now"])
    if before is False or not now:
        return None
    return {"before": before, "now": now, "setup": d["setup"]}


def _says_who(found: start.Found) -> bool:
    """The results themselves say who graded them: a model in them (not --judge-model's or
    judgekeeper.toml's), a rule or a prompt."""
    from judgekeeper import judge_setup

    s = judge_setup.of(found)
    return bool(s["rule_hash"] or s["prompt_hash"] or s["models"] and found.model_source is None)


def _two_judges(ws, found: start.Found, other: start.Found) -> bool | str:
    """--before, when the two results don't say who graded them: while a check's take-on
    holds, the grades of the marked answers unchanged in each tell one LLM-as-a-judge's from
    the other's (check.judged_by). When either can't be told that way (its marked answers
    changed, say), the bytes of the results the check replaced may (_one_replaced): UNSURE,
    they are not compared, but nothing says another LLM-as-a-judge graded them."""
    from judgekeeper import check

    one, two = check.judged_by(ws, found), check.judged_by(ws, other)
    if one is not None and two is not None:
        return one != two
    return UNSURE if _one_replaced(ws, found, other) else False


REPLACED = "replaced_sha256"  # start.json: the results files whose grades a check replaced


def _file_sum(path: Path) -> str | None:
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest() if Path(path).is_file() else None
    except OSError:
        return None


def replaced(ws, data: dict, found: start.Found) -> list[str]:
    """For check._adopt, before start.json names the file it takes on: the sums of the
    results files it replaces (start.json's results_files, where they are read), with the
    ones kept from earlier checks. Never the file taken on (graded again in place)."""
    base = start.results_path(ws.root, data)
    base = base if base.is_dir() else base.parent
    taken = {r.path.resolve() for r in found.results}
    sums = [s for s in data.get(REPLACED) or [] if isinstance(s, str)]
    for name in data.get("results_files") or []:
        path = base / name if isinstance(name, str) else None
        if path is not None and path.resolve() not in taken and (s := _file_sum(path)):
            sums.append(s)
    return list(dict.fromkeys(sums))


def _one_replaced(ws, found: start.Found, other: start.Found) -> bool:
    """Exactly one of the two results holds the bytes of results a check replaced (REPLACED),
    so their grades come from two setups though nothing in them says so. Not when both say
    who graded them: their setups decide."""
    if _says_who(found) and _says_who(other):
        return False
    try:
        kept = set(ws.data().get(REPLACED) or [])
    except (OSError, ValueError, AttributeError):
        return False

    def was(f: start.Found) -> bool:
        return len(f.results) == 1 and _file_sum(f.results[0].path) in kept

    return bool(kept) and was(found) != was(other)


def restart(ws) -> None:
    """After `check` took on another LLM-as-a-judge's grades (check._adopt): the grades a
    plain run reads next changed because the LLM-as-a-judge did, so they start again
    (RESTARTED). --before compares the two files it is given, as always."""
    raw = read(ws)
    if raw is not None:
        write(ws, raw["before"], raw["now"], RESTART)


def write(ws, before: dict | None, now: dict, setup: str) -> None:
    """The results read now and the ones read before them. Never written through a link."""
    path = _path(ws)
    if path.is_symlink() or ws.dir.is_symlink():
        return
    d = {"before": before, "now": now, "setup": setup}
    make_private(path.parent)
    write_replacing(path, json.dumps({**d, "sha256": _sum(d)}, indent=2, sort_keys=True) + "\n")


@dataclass
class Look:
    """What a run learned before it said anything: the comparison (None when there is none),
    and what the file holds after it, written once the run is done."""

    comparison: Comparison | None
    before: dict | None  # the results before the newest, as last-graded.json will keep them
    now: dict
    setup: str  # setup_of's hash, kept with them
    had: bool  # last-graded.json was there and could be read
    restarted: bool = False  # it was, for another setup of the LLM-as-a-judge: RESTARTED
    other_setup: bool = False  # --before's file was graded by another setup: OTHER_SETUP
    only_grades: bool = False  # restarted or other_setup since only grades changed (ONLY_GRADES)
    older: bool = False  # restarted: the last results were saved without answer hashes (OLDER)
    unsure: bool = False  # other_setup told only by the bytes a check replaced: UNSURE_SETUP
    left_out: tuple[str, ...] = ()  # only_grades: once fields new on every answer were left out
    # a --before run on another setup than the grades read last (or than a check took on):
    # last-graded.json stays as it is, so no plain run compares grades of two setups
    keep: bool = False

    def paragraphs(self, comparison: Comparison | None,
                   gate: bool = True) -> tuple[list[list[str]], int | None]:
        """What is said where the comparison goes, and the exit code it sets (None: the run's
        own). Outside a gate (`gate`: --before or CI), results that can't be matched because
        only one of them names its questions by id (marked-answers.csv graded again without
        it, say) are one line: the run's own Next: line and exit code stand."""
        if self.other_setup:
            if self.unsure:
                return [[UNSURE_SETUP], [UNSURE_SETUP_NEXT]], start.EXIT_QUESTION
            return [[ONLY_GRADES_BEFORE, *left_out_line(self.left_out)] if self.only_grades
                    else [OTHER_SETUP], [OTHER_SETUP_NEXT]], start.EXIT_QUESTION
        c = comparison
        if c is not None and not gate and not c.n and not c.ungraded and c.one_side_ids:
            return [[NO_IDS_ONE_SIDE]], None
        if comparison is not None:
            return lines(comparison), comparison.exit_code
        said = OLDER if self.older else ONLY_GRADES if self.only_grades else RESTARTED
        return ([[said, *left_out_line(self.left_out)]] if self.restarted else []), None


def look(talk, ws, found: start.Found, given: str | None = None,
         other_judge: bool = False) -> Look | None:
    """The comparison of the newest results with the last ones read here, or with the file
    `given` (--before). A file that can't be read is a usage error (StartError). None when
    the results hold no grade to compare. `other_judge`: the marks here are for another
    LLM-as-a-judge, whose grades say nothing of a change to the AI: the last ones read are
    not kept, whatever the person answers about starting over."""
    now = grades_of(found)
    if not any(now["questions"].values()):
        return None
    setup = setup_of(found)
    raw = read(ws)
    restarted = given is None and raw is not None and raw["setup"] != setup
    state = None if other_judge or restarted else raw  # another setup: its grades start again
    # the same results read again keep the baseline they had; new ones have the last read
    last = (state["before"] if state["now"] == now else state["now"]) if state else None
    baseline = last  # ids that are plain numbers say nothing here: the text does
    if given is not None:
        other = file_found(talk, found, given)
        keep = raw is not None and raw["setup"] != setup
        c = compare(grades_of(other, numbers=True), grades_of(found, numbers=True))
        # a --before that compares nothing leaves the last grades read here as they were
        setups = _judged(found) and _judged(other) and setup_of(other) != setup
        if setups or (two := _two_judges(ws, found, other)):  # two setups, or maybe
            return Look(None, last, now, setup, state is not None, other_setup=True, keep=True,
                        unsure=not setups and two == UNSURE)
        if regraded_only(c):
            return Look(None, last, now, setup, state is not None, other_setup=True, keep=True,
                        only_grades=True, left_out=c.left_out)
        return Look(c, last, now, setup, state is not None, keep=keep or not c.n)
    if baseline is not None and "answers" not in baseline:  # saved by judgekeeper 1.4.0
        return Look(None, None, now, setup, state is not None, restarted=True, older=True)
    c = compare(baseline, now) if baseline is not None else None
    if regraded_only(c):  # graded otherwise: they start again, said once
        return Look(None, None, now, setup, state is not None, restarted=True, only_grades=True,
                    left_out=c.left_out)
    return Look(c, last, now, setup, state is not None, restarted=restarted)


def _judged(found: start.Found) -> bool:
    """Whether the results say who graded them: a model, a rule or a prompt."""
    from judgekeeper import judge_setup

    s = judge_setup.of(found)
    return bool(s["models"] or s["rule_hash"] or s["prompt_hash"])


def file_found(talk, found: start.Found, name: str) -> start.Found:
    """The results file (or MLflow store) `name`, read as these results were: the same eval
    tool and judge, the same label map and pass mark. Grades it can't tell as Pass or Fail
    stop the run, as they do in these results."""
    from judgekeeper.check import no_such

    path = Path(name)
    if not path.exists():
        raise StartError(no_such(name), "check the path, then run `{command}`.")
    o = talk.options
    try:
        other = start.find_judge(path, tool=o["tool"], metric=found.metric,
                                 pass_if=o["pass_if"], label_map=o["label_map"] or found.label_map)
    except RecordsError as e:
        raise start.usage_error(e) from None
    except Stop:
        raise StartError(CANT_READ.format(name=path.name), CANT_READ_NEXT) from None
    if other.pool.unmapped:
        raise _unread(talk, path, other)
    return other


def _unread(talk, path: Path, other: start.Found) -> Stop:
    """The --before file's decisions hold values that are not Pass or Fail: named as the
    main results' are (never long text: it may be an answer), with the --label-map to give."""
    from judgekeeper.front import LABEL_MAP, _shown

    values = list(dict.fromkeys(other.pool.unmapped))
    words = [str(v) for v in values]
    shown = _shown(words) if all(start.verdict_like(v) for v in values) else LONG_TEXT
    talk.para(UNREAD.format(name=path.name, values=shown))
    again = talk.command(*talk.labels_flags(), "--before", path_arg(str(path)), "--label-map",
                         LABEL_MAP)
    return talk.stop(start.EXIT_QUESTION, (
        "decide which of the values above mean Pass, which mean Fail and which mean no "
        f"decision (error), then run `{again}`."))
