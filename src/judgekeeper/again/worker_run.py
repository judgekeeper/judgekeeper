"""Asking a Python tool's judge again for real: its worker in "run" mode.

DeepEval, Inspect AI and MLflow each have a worker script (`workers/`) that judgekeeper runs
with the user's own Python, in the project folder, after the person said yes. In "run" mode the
worker grades every asked answer `times` times and writes one line per answer per time:

    {"id": ..., "time": 0, "ok": true, ...what the judge said...}
    {"id": ..., "time": 0, "ok": false, "error": "RateLimitError: ...", "call_failed": true}

and a last line `{"ok": true, "done": true, "version": ...}` when it got to the end. Its output
file is kept in `.judgekeeper/again/<stamp>/<tool>.jsonl`, scrubbed of any key that leaked into
a reason, each answer's error cut to its type (`error_kind`: its text can quote the grading
prompt). The run has no time limit; Ctrl-C stops it.

`count` then keeps an answer only when every time asked came back clean with a clear verdict;
the others are listed with the reason (`fresh.NOT_COUNTED`), and the errors by type and count
("RuntimeError on 13 answers"), never their text. When nothing at all could be counted, the
tool failed: `AgainError`.
"""

from __future__ import annotations

import json
import re
from collections import Counter

from judgekeeper import again
from judgekeeper.again.fresh import AgainError, Fresh, new_folder
from judgekeeper.redact import scrub
from judgekeeper.textio import jsonl_lines, make_private, write_replacing

_TYPED = re.compile(r"([A-Za-z_][\w.]*): ")


def error_kind(error) -> str:
    """An error as its type only ("BadRequestError"), never the text after it; judgekeeper's
    own messages ("Inspect gave no new score") have no type and stay as they are."""
    m = _TYPED.match(str(error))
    return m.group(1) if m else str(error)


def errors_said(kinds: list[str]) -> str:
    """ "RuntimeError on 13 answers, TimeoutError on 1 answer": one kind per answer."""
    return ", ".join(f"{kind} on {n} answer{'' if n == 1 else 's'}"
                     for kind, n in Counter(kinds).most_common())


def ask(ws, plan, talk, name: str, env: dict | None = None,
        drop: tuple = ()) -> tuple[Fresh, dict[str, dict[int, dict]], dict]:
    """Run the plan's worker in "run" mode. Returns the Fresh to fill, the worker's lines by
    answer id and time, and its last line."""
    folder = plan.folder or new_folder(ws)
    make_private(folder)
    out = folder / f"{plan.tool}.jsonl"
    job = {**plan.job, "mode": "run", "times": plan.times,
           "answers": [entry[1] for entry in plan.payload]}
    talk.say(f"Asking your LLM-as-a-judge {plan.calls:,} times through {name}. Ctrl-C stops it.")
    if again.local_model(plan):
        talk.say(again.LOCAL_MODEL)
    progress = again.Progress(talk, len(plan.payload) * plan.times)

    def look():  # one line per answer and time, as the worker writes them
        if out.is_file():
            progress.count(out.read_bytes().count(b'"id":'))

    with again.watching(look):
        proc = again.start_worker(plan.tool, plan.runner[0], job, ws.root, out, env=env,
                                  drop=drop, timeout=None)
    look()  # the last count, also when it ended before the first look
    lines = []
    if out.is_file():
        text = scrub(out.read_text(encoding="utf-8"))
        lines = [json.loads(x) for x in jsonl_lines(text) if x.strip()]
        for line in lines:
            if "id" in line and line.get("error"):
                line["error"] = error_kind(line["error"])
        write_replacing(out, "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in lines))
    done = next((x for x in reversed(lines) if x.get("done")), None)
    if done is None:
        failed = next((x for x in reversed(lines) if "id" not in x and x.get("error")), None)
        raise AgainError(f"{name} did not finish: "
                         + (failed["error"] if failed else again.last_error(proc)))
    got: dict[str, dict[int, dict]] = {}
    for line in lines:
        if "id" in line:
            got.setdefault(line["id"], {})[line["time"]] = line
    return Fresh(folder=folder, source={"kind": plan.tool, "file": out.name}), got, done


def count(fresh: Fresh, plan, got: dict, name: str, verdict_of, differs=None) -> list[dict]:
    """Fill `fresh` from the worker's lines. The plan's payload holds (answer, the worker's
    item, ...) per asked answer. `verdict_of(item, line)` gives "pass", "fail" or None;
    `differs(entry, lines)`, when given, says whether the judge saw other text than it did in
    the saved run. Returns the first clean lines of the counted answers, in order."""
    firsts, errors = [], []
    for entry in plan.payload:
        answer, item = entry[0], entry[1]
        runs = got.get(answer["id"], {})
        lines = [runs.get(t) for t in range(plan.times)]
        bad = [x for x in lines if x is not None and not x.get("ok")]
        if bad:  # one kind per answer: the first time it went wrong
            errors.append(error_kind(bad[0].get("error")))
        if any(x is None for x in lines):
            fresh.not_counted[answer["id"]] = "missing"
        elif any(x.get("call_failed") for x in bad):
            fresh.not_counted[answer["id"]] = "judge call failed"
        elif bad:
            fresh.not_counted[answer["id"]] = "error"
        elif differs is not None and differs(entry, lines):
            fresh.not_counted[answer["id"]] = "grading prompt differs"
        else:
            verdicts = [verdict_of(item, x) for x in lines]
            if any(v not in ("pass", "fail") for v in verdicts):
                fresh.not_counted[answer["id"]] = "no clear verdict"
                continue
            fresh.verdicts[answer["id"]] = verdicts
            fresh.models += [m for x in lines for m in (x.get("models") or [x.get("model")])
                             if isinstance(m, str) and m]  # the model each time, if said
            fresh.scores[answer["id"]] = [x.get("score") for x in lines]
            fresh.reasons[answer["id"]] = [str(x.get("reason") or "") for x in lines]
            firsts.append(lines[0])
    if not fresh.verdicts:
        raise AgainError(f"{name} could not ask your LLM-as-a-judge: " + (
            errors_said(errors) if errors else "no answer came back with a clear verdict"))
    if errors:
        fresh.notes.append(f"The LLM-as-a-judge's calls failed: {errors_said(errors)}.")
    return firsts
