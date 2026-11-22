"""Ask a person to label only the few answers worth their time, as files for Label Studio.

When there are too few labels for a result, judgekeeper has an order in which to ask for them
(start_label.build_queue: the answers by the check's verdict, in blocks). This module turns the
first of that order into `.judgekeeper/ask/`:

  label-these.json   Label Studio import: {"data": {"id", "input", "output"}} per answer. No
                     grade, no prediction and no group: the person is not swayed by what the
                     check said.
  label-config.xml   the labeling screen: the input and output as text, a Pass / Fail choice
                     named `verdict`, and a `reason` box.
  picks.json         for each answer its group and its pick chance (picked / answers the group
                     holds), so that the numbers stay fair when the labels come back (the
                     groups' sizes weigh them, as in weighted.py). Never imported.

One more group beside the check's passes and fails: the answers where two graders differ.
Every answer is in one group, and that one takes the answers that are in two.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from judgekeeper.metrics import ERROR
from judgekeeper.redact import scrub_value
from judgekeeper.textio import make_private, write_replacing

FOLDER = "ask"
IMPORT_FILE = "label-these.json"
CONFIG_FILE = "label-config.xml"
PICKS_FILE = "picks.json"
DISAGREE = "disagree"  # the group of answers two graders gave different verdicts

NEXT_LINE = ("Import .judgekeeper/ask/label-these.json into Label Studio, label them, export, "
             "and run judgekeeper again.")

LABEL_CONFIG = """<View>
  <Header value="Input"/>
  <Text name="input" value="$input"/>
  <Header value="Output"/>
  <Text name="output" value="$output"/>
  <Choices name="verdict" toName="output" choice="single" showInline="true" required="true">
    <Choice value="Pass"/>
    <Choice value="Fail"/>
  </Choices>
  <TextArea name="reason" toName="output" rows="2" placeholder="Why? (optional)"/>
</View>
"""


@dataclass
class Pick:
    id: str
    input: str
    output: str
    group: str  # "pass", "fail" or DISAGREE
    chance: float  # picked / answers in the group


# The groups ----------------------------------------------------------------------------------

def disagreeing(verdicts: dict[str, dict[str, str]]) -> list[str]:
    """The answers two graders gave different verdicts, in the order the first grader lists
    them. `verdicts` is {grader: {answer id: verdict}}; an error is no verdict, and one grader
    never disagrees with itself."""
    out = []
    seen: set[str] = set()
    for graded in verdicts.values():
        for i in graded:
            if i in seen:
                continue
            seen.add(i)
            given = {g[i] for g in verdicts.values() if g.get(i) not in (None, ERROR)}
            if len(given) > 1:
                out.append(i)
    return out


def regroup(groups: dict[str, str], disagree: list[str]) -> dict[str, str]:
    """{answer id: group} with the answers that graders disagree on moved to DISAGREE, so every
    answer is in one group and the groups' sizes add up to the pool."""
    moved = set(disagree)
    return {i: (DISAGREE if i in moved else g) for i, g in groups.items()}


def sizes(groups: dict[str, str]) -> dict[str, int]:
    """How many answers each group holds."""
    out: dict[str, int] = {}
    for g in groups.values():
        out[g] = out.get(g, 0) + 1
    return out


def chances(picked: dict[str, int], pool: dict[str, int]) -> dict[str, float]:
    """The chance of an answer in each group being picked: how many were picked over how many
    the group holds. An empty group is 1.0, never a division by zero."""
    return {g: (min(1.0, n / pool[g]) if pool.get(g) else 1.0) for g, n in picked.items()}


def picks_from(queue: list[dict], count: int, text: dict[str, tuple[str, str]],
               pool: dict[str, int]) -> list[Pick]:
    """The first `count` answers of `queue` ([{"id", "group"}], in the order the marking page
    shows them: no second way of picking), each with its input and output (`text`: {id:
    (input, output)}) and its group's chance, over `pool` (the groups' sizes)."""
    first = [q for q in queue if q["id"] in text][:max(count, 0)]
    taken: dict[str, int] = {}
    for q in first:
        taken[q["group"]] = taken.get(q["group"], 0) + 1
    chance = chances(taken, pool)
    return [Pick(q["id"], *text[q["id"]], q["group"], chance[q["group"]]) for q in first]


# The files -----------------------------------------------------------------------------------

def label_these(picks: list[Pick]) -> list[dict]:
    """The Label Studio import: one task per pick with its id, input and output."""
    return [{"data": {"id": p.id, "input": p.input, "output": p.output}} for p in picks]


def _json(data) -> str:
    return json.dumps(scrub_value(data), indent=2, ensure_ascii=False) + "\n"


def write(folder: str | Path, picks: list[Pick]) -> list[Path]:
    """Write the three files into `folder`; the paths of the two for Label Studio, [] (and
    nothing written) when there are no picks."""
    if not picks:
        return []
    folder = Path(folder)
    make_private(folder)
    tasks, config = folder / IMPORT_FILE, folder / CONFIG_FILE
    write_replacing(tasks, _json(label_these(picks)))
    write_replacing(config, LABEL_CONFIG)
    write_replacing(folder / PICKS_FILE, _json(
        [{"id": p.id, "group": p.group, "chance": p.chance} for p in picks]))
    return [tasks, config]
