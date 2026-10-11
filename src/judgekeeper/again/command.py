"""The plan for asking your own judge command (`--judge-command`): the `--exec` contract, one
answer as JSON on stdin and the verdict on stdout. It is the user's judge by definition; its
model is what `--judge-model` says, else unknown. It runs the user's code, which they typed
themselves, so the plan says how many times."""

from __future__ import annotations

from judgekeeper import prices
from judgekeeper.again import OWN, Plan, cant
from judgekeeper.again.fresh import AgainError, Fresh, new_folder
from judgekeeper.custom import CustomRunner, exec_judge, split_command
from judgekeeper.keys import provider_of
from judgekeeper.metrics import ERROR
from judgekeeper.normalise import Normaliser
from judgekeeper.redact import scrub
from judgekeeper.start_label import display
from judgekeeper.table import make_fingerprint


def plan(ws, answers: list[dict], opts) -> Plan:
    command = opts.judge_command
    judge = f"your command {command}"
    try:
        argv = split_command(command)
    except ValueError as e:
        return cant("command", judge, f"--judge-command {command!r} cannot be read as a "
                                      f"command: {e}", short="the command cannot be read")
    if not argv:
        return cant("command", judge, "--judge-command is empty", short="no command")
    model = opts.judge_model
    calls = len(answers) * opts.times
    tokens = [prices.tokens_from_text(f"{display(a['input'])}\n{display(a['output'])}")
              for a in answers]
    return Plan(tool="command", judge=judge, status=OWN,
                why=f"This runs `{command}` {calls:,} times", model=model,
                provider=provider_of(model), calls_each=[1] * len(answers), tokens=tokens,
                cost_text=None if model else
                "Cost unknown: name your command's model with --judge-model.",
                side_effects=[("Your app is not run. Your command gets one answer at a time, "
                               "as JSON on stdin.")], payload=list(answers), runner=[command])


MAX_ERROR_SHOWN = 300  # characters of the first error, on one line (as `judge --exec`)


def _failed(judgments) -> tuple[int, str]:
    """How many calls gave no clear verdict, and the first one's error on one line."""
    bad = [j for j in judgments if j.verdict in (ERROR, None)]
    first = next((j.error or j.rationale for j in bad if j.error or j.rationale),
                 "no clear verdict in its output")
    return len(bad), " ".join(scrub(str(first)).split())[:MAX_ERROR_SHOWN]


def run(ws, plan: Plan, talk) -> Fresh:
    """Run the command once per answer per time: {id, input, output} as JSON on stdin. When
    every call fails, nothing is counted (AgainError): the saved numbers stay as they were.
    When some fail, it says how many and the first error."""
    command = plan.runner[0]
    known = {"model": plan.model} if plan.model else {}
    fingerprint = make_fingerprint(known)
    runner = CustomRunner(exec_judge(command), Normaliser(), fingerprint,
                          source={"kind": "command", "command": command})
    folder = plan.folder or new_folder(ws)
    folder.mkdir(parents=True, exist_ok=True)
    fresh = Fresh(folder=folder, fingerprint=fingerprint.to_dict(),
                  source={"kind": "command", "file": command})
    answers = plan.payload_answers()
    got: dict[str, list] = {a["id"]: [] for a in answers}
    for _ in range(plan.times):
        for a in answers:
            got[a["id"]].append(runner.judge({"id": a["id"], "input": a["input"],
                                              "output": a["output"]}))
    every = [j for judgments in got.values() for j in judgments]
    n_failed, first = _failed(every)
    if every and n_failed == len(every):
        raise AgainError(f"Your judge command failed on every call ({n_failed} of "
                         f"{len(every)}). First error: {first}")
    if n_failed:
        talk.say(f"Your judge command failed on {n_failed} of {len(every)} calls; those "
                 f"answers are not counted. First error: {first}")
    for item_id, judgments in got.items():
        if any(j.verdict in (ERROR, None) for j in judgments):
            fresh.not_counted[item_id] = "no clear verdict"
            continue
        fresh.verdicts[item_id] = [j.verdict for j in judgments]
        fresh.scores[item_id] = [j.raw_score for j in judgments]
        fresh.reasons[item_id] = [j.rationale or "" for j in judgments]
    return fresh
