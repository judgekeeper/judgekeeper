"""Change the rule: the second half of Fix your judge (start_fix). No AI call and no key.

judgekeeper writes a prompt the person pastes into any AI assistant: the judge's rule and, from
the answers judgekeeper used (never the ones set aside), its mistakes, the answers whose rule
is unclear and a few it got right, each text cut to CUT characters. The person pastes the new
rule back (or writes it themselves); plain checks say whether it kept the rule's template parts
(a save needs them), whether it is a big change, and whether it copies text from the answers.
Then the hand-over: where the rule probably is in the person's own files (a read-only search,
nothing is imported or run), what to change there, and a prompt for a coding agent.
judgekeeper never edits those files. The new rule is tested inside "Try your new judge", on
the answers set aside (start_fix.Fix.test_new_judge).

Or the person's coding agent does the whole loop (agent_loop_prompt): a prompt with no answer
text, only paths and commands, that has the agent read fix/prompt.txt, save its rule with
`judgekeeper start --fix --rule-file`, put it in place, and run the eval and Try your new
judge after the person's yes.
"""

from __future__ import annotations

import difflib
import json
import re
from pathlib import Path

from judgekeeper.start_label import ASKABLE

CUT = 1500  # characters of each text in the prompt
MAX_MISTAKES, MAX_UNCLEAR, MAX_KEEP = 20, 6, 6
START, END = "NEW RULE START", "NEW RULE END"
MAX_RULE = 20_000  # characters of the new rule (between the lines)
MAX_PASTE = 150_000  # characters of a whole paste: well under what the page can send
TOO_LONG = "Too long to save. Paste only the new rule."
BIG = 1.5  # times the old rule, plus BIG_EXTRA characters, is a big change
BIG_EXTRA = 400
COPIED = 8  # words in a row copied from an answer
SEARCH_CHARS = 60  # of the rule, searched for in the project's files
SOURCE = frozenset({".yaml", ".yml", ".py", ".js", ".ts", ".mjs", ".cjs", ".json", ".toml",
                    ".txt", ".md"})  # searched first, with files named like a config
LINE_SHOWN = 120  # characters of the matched line shown
GRADE = "GRADE: $LETTER"  # the line Inspect's model_graded_qa reads its grade from

PER_TEST = ("Your rule is different for each test, so judgekeeper can't write one prompt for it "
            "yet. The patterns above still show where it goes wrong.")
UNKNOWN = ("Your results do not say your judge's rule, so judgekeeper can't write a prompt for "
           "it. The patterns above still show where it goes wrong.")
EMPTY = "The new rule is empty."
DROPPED = "The new rule dropped {part}: put it back before using it."
BIG_CHANGE = "This is a big change, not a small edit."
COPIES = "It copies text from your answers, so it may only fix these answers."
ASK = ("Make the smallest change that fixes as many mistakes as you can without breaking the\n"
       "KEEP items. Add general guidance only: do not copy text from the answers and do not\n"
       "mention specific answers.")
ECHO = "This looks like judgekeeper's prompt, not a new rule. Paste only the new rule."
# Lines of judgekeeper's own prompt: a rule holding one is the prompt pasted back
PROMPT_LINES = ("THE RULE NOW", "MISTAKES (the person is right)", "KEEP THESE RIGHT",
                "THE RULE DOES NOT DECIDE THESE", "[M1]", "[U1]", "[K1]")
HAND_WRITTEN = ("You wrote this rule after seeing all your disagreements, so this test may look "
                "better than it is.")
FIELDS = {
    "promptfoo": "the `value:` of the llm-rubric assert",
    "deepeval": "`evaluation_steps=[...]` in `GEval(...)`",
    "inspect": "`instructions=` in `model_graded_qa(...)`",
    "mlflow": "`instructions=` in `make_judge(...)`, or the text of `Guidelines(...)`",
}
INSPECT_TEMPLATE = "`template=` in `model_graded_qa(...)`"
OWN_CODE = "where your code keeps the rule"
NOTES = {
    "deepeval": ("If your GEval has only `criteria=`, add `evaluation_steps=` with these steps. "
                 "This also stops DeepEval writing new steps on every run."),
    "mlflow": ("A registered judge: register it again yourself with `.register(name=...)`; "
               "this adds a new version in your store."),
}
_DOUBLE = re.compile(r"\{\{.*?\}\}", re.DOTALL)
_SINGLE = re.compile(r"(?<!\{)\{[A-Za-z_]\w*\}(?!\})")  # Inspect's {question}, {answer}, ...
_GEVAL_PARTS = " \n \n"  # how DeepEval joins the parts of a GEval prompt


# The rule --------------------------------------------------------------------------------

def deepeval_steps(rule: str) -> list[str]:
    """A GEval rule's evaluation steps: from its "Evaluation Steps:" part, or its numbered
    lines when the rule is the steps alone; [] when it has none."""
    for part in rule.split(_GEVAL_PARTS):
        if part.startswith("Evaluation Steps:"):
            try:
                listed = json.loads(part[len("Evaluation Steps:"):])
            except ValueError:
                return []
            return [" ".join(str(s).split()) for s in listed if str(s).strip()] \
                if isinstance(listed, list) else []
    lines = [line.strip() for line in rule.splitlines() if line.strip()]
    if lines and all(re.match(r"\d+\.\s", line) for line in lines):
        return [re.sub(r"^\d+\.\s+", "", line) for line in lines]
    return []


def rule_text(rule: str, tool: str) -> str:
    """The rule as the person edits it: a GEval's steps, numbered; else the rule itself."""
    if tool == "deepeval":
        steps = deepeval_steps(rule)
        if steps:
            return "\n".join(f"{n}. {s}" for n, s in enumerate(steps, 1))
        return rule.split(_GEVAL_PARTS)[0].strip()
    return rule.strip()


def placeholders(rule: str, tool: str) -> list[str]:
    """The template parts the new rule must keep: {{ ... }}, Inspect's {name} and its grade
    line, in order of appearance."""
    parts = [m.group(0) for m in _DOUBLE.finditer(rule)]
    if tool == "inspect":
        parts += [m.group(0) for m in _SINGLE.finditer(rule)]
        if "GRADE:" in rule:
            parts.append(GRADE)
    return list(dict.fromkeys(parts))


def _same_part(part: str, text: str) -> bool:
    if part == GRADE:
        return "GRADE:" in text
    if part.startswith("{{"):
        inner = " ".join(part[2:-2].split())
        return any(" ".join(m.group(0)[2:-2].split()) == inner for m in _DOUBLE.finditer(text))
    return part in text


# The prompt ------------------------------------------------------------------------------

def _cut(text) -> str:
    text = "" if text is None else str(text)
    return text if len(text) <= CUT else text[:CUT] + " (cut)"


def _said(item: dict) -> str:
    j, f = item["judge"].upper(), item["final"].upper()
    if j == f:
        return f"Both said {j}."
    return f"Judge said {j}, person said {f}."


def _entry(label: str, item: dict) -> str:
    head = [f"[{label}] {_said(item)}"]
    if item.get("why"):
        head.append(f'Person\'s note: "{_cut(item["why"])}".')
    if item.get("reason"):
        head.append(f'Judge\'s reason: "{_cut(item["reason"])}".')
    return (" ".join(head) + f'\n     Question: "{_cut(item["input"])}" '
            f'Answer: "{_cut(item["output"])}"')


def _keep(agreed: list[dict]) -> list[dict]:
    """Up to MAX_KEEP agreed answers, half the judge's passes and half its fails; a short side
    is filled from the other."""
    passes = [a for a in agreed if a["final"] == "pass"]
    fails = [a for a in agreed if a["final"] == "fail"]
    n_fail = min(len(fails), MAX_KEEP // 2)
    n_pass = min(len(passes), MAX_KEEP - n_fail)
    n_fail = min(len(fails), MAX_KEEP - n_pass)
    return passes[:n_pass] + fails[:n_fail]


def build_prompt(rule: str, tool: str, mistakes: list[dict], unclear: list[dict],
                 agreed: list[dict]) -> str:
    """The prompt for any AI assistant. Each item: "judge", "final", "why", "reason", "input",
    "output" (text). Mistakes with a why come first; labels are short, never real ids."""
    mistakes = sorted(mistakes, key=lambda m: not m.get("why"))[:MAX_MISTAKES]
    lines = ["You are editing the grading rule of an LLM judge. The judge decides Pass or Fail.",
             "A person checked some of its decisions and found mistakes.", "",
             "THE RULE NOW (keep its meaning, wording and format where you can):",
             rule_text(rule, tool), ""]
    parts = placeholders(rule, tool)
    if parts:
        lines += [f"KEEP EXACTLY these template parts: {' '.join(parts)}", ""]
    lines.append("MISTAKES (the person is right):")
    lines += [_entry(f"M{n}", m) for n, m in enumerate(mistakes, 1)]
    if unclear:
        lines.append("THE RULE DOES NOT DECIDE THESE:")
        lines += [_entry(f"U{n}", m) for n, m in enumerate(unclear[:MAX_UNCLEAR], 1)]
    keep = _keep(agreed)
    if keep:
        lines.append("KEEP THESE RIGHT (the judge and the person agreed):")
        lines += [_entry(f"K{n}", m) for n, m in enumerate(keep, 1)]
    lines += ["", ASK, f"Reply with the new rule only, between the lines {START} and {END}."]
    if tool == "deepeval":
        lines.append("(For DeepEval: reply with the new evaluation steps, one per line, between "
                     "those lines.)")
    return "\n".join(lines) + "\n"


# Paste back -------------------------------------------------------------------------------

def _marker(words: str) -> str:
    """A line holding only `words`, in any case, with markdown or a colon around them:
    **NEW RULE START**, `NEW RULE START`, ## NEW RULE START, NEW RULE START:."""
    return r"^[ \t#>*_`]*" + r"[ \t]+".join(words.split()) + r"[ \t*_`:]*$"


def new_rule_of(text: str) -> str:
    """The text between the NEW RULE START and NEW RULE END lines (to the end when there is
    no end line); the whole text when there is no start line."""
    m = re.search(rf"{_marker(START)}(.*?)(?:{_marker(END)}|\Z)", text,
                  re.MULTILINE | re.DOTALL | re.IGNORECASE)
    return (m.group(1) if m else text).strip()


def _words(text: str) -> list[str]:
    return re.findall(r"\w+", text.lower())


def _runs(words: list[str]) -> set[tuple[str, ...]]:
    return {tuple(words[i:i + COPIED]) for i in range(len(words) - COPIED + 1)}


def echoes_prompt(new: str) -> bool:
    """Whether the new rule holds a line of judgekeeper's own prompt (its headings, or the
    first mistake, unclear or kept item)."""
    return any(line.strip().startswith(PROMPT_LINES) for line in new.splitlines())


def checks(old: str, new: str, tool: str, outputs: list[str]) -> list[dict]:
    """The problems with a new rule, each {"text", "blocking"}: an empty rule, judgekeeper's
    prompt pasted back and a dropped template part block saving it; a big change and text
    copied from the used answers are said."""
    if not new.strip():
        return [{"text": EMPTY, "blocking": True}]
    if echoes_prompt(new):
        return [{"text": ECHO, "blocking": True}]
    out = [{"text": DROPPED.format(part=p), "blocking": True}
           for p in placeholders(old, tool) if not _same_part(p, new)]
    if len(new) > BIG * len(old) + BIG_EXTRA:
        out.append({"text": BIG_CHANGE, "blocking": False})
    copied = _runs(_words(new)) - _runs(_words(old))
    if copied and any(copied & _runs(_words(o)) for o in outputs):
        out.append({"text": COPIES, "blocking": False})
    return out


def _tokens(text: str) -> list[str]:
    return re.findall(r"\s+|\w+|[^\w\s]", text)


def word_diff(old: str, new: str) -> list[list[str]]:
    """Old against new, word by word: [["same" | "del" | "add", text], ...]."""
    a, b = _tokens(old), _tokens(new)
    out: list[list[str]] = []

    def put(kind, text):
        if not text:
            return
        if out and out[-1][0] == kind:
            out[-1][1] += text
        else:
            out.append([kind, text])

    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op == "equal":
            put("same", "".join(a[i1:i2]))
        else:
            put("del", "".join(a[i1:i2]))
            put("add", "".join(b[j1:j2]))
    return out


# The hand-over ----------------------------------------------------------------------------

def field(tool: str, rule_field: str | None = None) -> str:
    """Where a tool keeps the rule; for Inspect, its template when the rule is that."""
    if tool == "inspect" and rule_field == "template":
        return INSPECT_TEMPLATE
    return FIELDS.get(tool, OWN_CODE)


def _needles(rule: str, tool: str) -> list[str]:
    """What to look for: the start of the rule's first line (for DeepEval, of its first step,
    then of its criteria)."""
    texts = []
    if tool == "deepeval":
        texts += deepeval_steps(rule)[:1]
        texts.append(rule.split(_GEVAL_PARTS)[0])
    texts.append(rule)
    out = []
    for text in texts:
        line = next((x.strip() for x in text.splitlines() if x.strip()), "")
        line = re.sub(r"^\d+\.\s+", "", line)[:SEARCH_CHARS]
        if line and line not in out:
            out.append(line)
    return out


def _results_file(path: Path) -> bool:
    """Whether judgekeeper reads `path` as an eval tool's results (find.classify_file)."""
    from judgekeeper.find import classify_file

    try:
        return classify_file(path) is not None
    except (OSError, ValueError):
        return False


def _source(path: Path) -> bool:
    return path.suffix.lower() in SOURCE or "config" in path.name.lower()


def _search_order(root: Path) -> list[Path]:
    """The project's files (start_fix._files), source-like files first, never a file that
    is an eval tool's results: those hold the rule too, but it is not set there."""
    from judgekeeper.start_fix import _files

    files = list(_files(root))
    ordered = [p for p in files if _source(p)] + [p for p in files if not _source(p)]
    return [p for p in ordered if not _results_file(p)]


def _shown(line: str) -> str:
    line = line.strip()
    return line if len(line) <= LINE_SHOWN else line[:LINE_SHOWN - 1] + "…"


def locate_rule(root: Path, rule: str, tool: str) -> tuple[str, int, str] | None:
    """(file, line number, line) where the rule is probably written, or None. It only reads
    the project's text files: nothing is imported or run."""
    root = Path(root)
    files = _search_order(root)
    for needle in _needles(rule, tool):
        for path in files:
            try:
                data = path.read_bytes()
            except OSError:
                continue
            if b"\0" in data[:8192]:
                continue
            for n, line in enumerate(data.decode("utf-8", errors="replace").splitlines(), 1):
                if needle in line:
                    return path.relative_to(root).as_posix(), n, _shown(line)
    return None


def hand_over(root: Path, data: dict, old: str, new: str, n_aside: int) -> dict:
    """Where the rule goes, read-only: {"where", "notes", "agent_prompt", "last"}."""
    from judgekeeper.redact import scrub

    tool = data.get("tool") or ""
    name = field(tool, data.get("rule_field"))
    the = name if name.startswith("the ") else f"the {name}"
    if name == OWN_CODE:
        the = "the judge's rule"
    found = locate_rule(root, old, tool)
    if found:
        where = scrub(f"Probably in {found[0]}, line {found[1]}: {found[2]}")
        place = f"In {found[0]} (probably line {found[1]}), replace {the}"
    else:
        task = data.get("task_file") if tool == "inspect" else None
        where = ("judgekeeper could not find where this rule is written. " + (
            "Change it where your code keeps it." if name == OWN_CODE else
            f"It is {the} of your judge" + (f", probably in {task}." if task else ".")))
        place = f"In your eval's files, replace {the}"
    agent = (f"{place} with the text below. Change only this text, nothing else. Then run the "
             f"eval.\n\n{new}")
    if tool in ASKABLE:
        last = ("Then run your eval and judgekeeper start: it offers Try your new judge on your "
                f"marked answers, and tests it on the {n_aside} kept aside.")
    else:
        last = "Then run your eval and judgekeeper start to check it on new answers."
    return {"where": where, "notes": [NOTES[tool]] if tool in NOTES else [],
            "agent_prompt": agent, "last": last}


# Your coding agent does it ----------------------------------------------------------------

AGENT_FILE = "agent-rule.txt"
HINTS = {"promptfoo": "for example npx promptfoo eval",
         "mlflow": "the script that runs my MLflow evaluation"}
# promptfoo saves a results file only when asked (-o, or outputPath in its config)
OWN_HINT = "the code that runs my judge"
NOT_FOUND = "where my eval keeps the judge's rule"
AGENT_INTRO = ("judgekeeper found where my LLM judge disagrees with me. Please fix the judge's "
               "rule, step by step. Stop and ask me wherever a step says so.")


def tool_hint(tool: str, test_file: str | None = None, task_file: str | None = None,
              results_file: str | None = None) -> str:
    """How the person's eval is probably run, for the agent prompt's step 4. For promptfoo,
    with -o and the results file judgekeeper read: a plain `promptfoo eval` saves none."""
    if tool == "promptfoo" and results_file:
        return f"for example npx promptfoo eval -o {results_file}"
    if tool == "deepeval":
        return (f"for example deepeval test run {test_file}" if test_file else
                "for example deepeval test run with my test file")
    if tool == "inspect":
        return (f"for example inspect eval {task_file}" if task_file else
                "for example inspect eval with my task file")
    return HINTS.get(tool, OWN_HINT)


def place_words(found: tuple[str, int, str] | None) -> str:
    """Where the rule probably is (locate_rule), as the agent prompt's step 3 says it."""
    return f"probably in {found[0]}, line {found[1]}" if found else NOT_FOUND


def agent_loop_prompt(command: str, folder: str, place: str, hint: str,
                      askable: bool) -> str:
    """The prompt for the person's coding agent: the whole loop, with no answer text in it.
    `command` is `judgekeeper start` with the person's own flags (start.Talk.command),
    `folder` the path of .judgekeeper/fix as the agent will use it, `place` and `hint` from
    place_words and tool_hint; `askable`: whether the judge can be asked again (Try your new
    judge), else `judgekeeper start` checks it on new answers."""
    from judgekeeper.textio import quote_arg

    rule_file = quote_arg(f"{folder}/{AGENT_FILE}")
    browser = "" if "--no-browser" in command.split() else " --no-browser"
    steps = [
        (f"Read {folder}/prompt.txt. It holds my judge's rule now, the mistakes I marked and "
         f"how to write a new rule. Write the new rule as it asks into {folder}/{AGENT_FILE}. "
         "Keep the rule general: don't copy text from the answers."),
        (f"Run: {command} --fix --rule-file {rule_file}\n"
         "It checks the rule. If it says the rule can't be saved, change the rule and run it "
         "again. Show me the old rule and the new one."),
        (f"Put the new rule where that command says ({place}). Change only the rule, nothing "
         "else."),
        ("Ask me before you run my eval: it calls my judge's model, which may cost money. Then "
         f"run it the way this project runs it ({hint})."),
    ]
    if askable:
        steps += [
            (f"Run: {command} --try-new-judge{browser}\n"
             "It prints how many judge calls it would make, and stops. Show me that and ask me. "
             "Only after I say yes, run it again with the --allow-calls number it printed."),
            ("Tell me in plain words what it says: how many of the answers kept aside the new "
             "rule fixed and broke, and the old and new numbers on my marked answers. If it "
             "broke more than it fixed, say so and offer to put the old rule back."),
        ]
    else:
        steps += [f"Run: {command}\nIt checks my new judge on new answers.",
                  "Tell me in plain words what it printed."]
    lines = [AGENT_INTRO, ""]
    for n, text in enumerate(steps, 1):
        first, *rest = text.split("\n")
        lines += [f"{n}. {first}", *(f"   {x}" for x in rest)]
    return "\n".join(lines) + "\n"


__all__ = ["agent_loop_prompt", "build_prompt", "checks", "echoes_prompt", "field",
           "hand_over", "locate_rule", "new_rule_of", "place_words", "placeholders",
           "rule_text", "tool_hint", "word_diff"]
