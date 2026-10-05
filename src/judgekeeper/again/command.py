"""The plan for asking your own judge command (`--judge-command`): the `--exec` contract, one
answer as JSON on stdin and the verdict on stdout. It is the user's judge by definition; its
model is what `--judge-model` says, else unknown. It runs the user's code, which they typed
themselves, so the plan says how many times."""

from __future__ import annotations

from judgekeeper import prices
from judgekeeper.again import OWN, Plan, cant
from judgekeeper.custom import split_command
from judgekeeper.keys import provider_of
from judgekeeper.start_label import display


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
                               "as JSON on stdin.")])
