"""When promptfoo keeps its results only in its own database, `start` offers to run promptfoo's
`export` command for the user, at a terminal only. Without a terminal, or on No, it prints the
commands.

The export reads promptfoo's database in the home folder and writes one file; it runs no
tests and calls no model. It runs with promptfoo's telemetry, update check and logs off:

    promptfoo export eval latest -o .judgekeeper/promptfoo-latest.json

"latest" is the user's last promptfoo run, which may be from another project, so the file is
checked against this project's config: its `config.description`, else its prompts. A run from
another project is deleted with a message saying how to find the right one. A match moves to
`promptfoo-results.json` in the project (asking first if that name is taken) and `start`
carries on.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from judgekeeper import again, find
from judgekeeper.redact import scrub

LATEST = ".judgekeeper/promptfoo-latest.json"
TARGET = "promptfoo-results.json"
ENV = {"PROMPTFOO_DISABLE_TELEMETRY": "1", "PROMPTFOO_DISABLE_UPDATE": "1",
       "PROMPTFOO_DISABLE_DEBUG_LOG": "1", "PROMPTFOO_DISABLE_ERROR_LOG": "1"}
QUESTION = ("Run promptfoo export for you? It reads promptfoo's database in your home folder "
            "and writes one file here. No AI call.")
ANOTHER = ("That was your last promptfoo run, from another project. Find yours with promptfoo "
           "list evals -n 10, then run promptfoo export eval <id> -o promptfoo-results.json.")


def _promptfoo(root: Path) -> str | None:
    local = root / "node_modules" / ".bin" / "promptfoo"
    return str(local) if local.exists() else again.which("promptfoo")


def _prompts(config: dict) -> list[str]:
    prompts = config.get("prompts") or []
    prompts = prompts if isinstance(prompts, list) else [prompts]
    out = []
    for p in prompts:
        text = p.get("raw") if isinstance(p, dict) else p
        if isinstance(text, str) and text.strip():
            out.append(text.strip())
    return out


def _this_project(root: Path, data: dict) -> bool:
    """Whether an exported run is of this project's config: the same description when both
    have one, else one of its prompts in the config file."""
    from judgekeeper.start import _project_description

    config = data.get("config") if isinstance(data.get("config"), dict) else {}
    theirs = config.get("description")
    mine = _project_description(root)
    if isinstance(theirs, str) and theirs.strip() and mine:
        return theirs.strip() == mine
    prompts = _prompts(config)
    path = next((root / n for n in find.PROMPTFOO_CONFIGS if (root / n).is_file()), None)
    if not prompts or path is None:
        return True
    text = path.read_text(encoding="utf-8", errors="replace")
    return any(p in text for p in prompts)


def offer(talk, root: Path) -> str:
    """Offer to export promptfoo's last run. Returns "done" (promptfoo-results.json is now in
    the project), "stop" (said what to do instead) or "commands" (print the commands)."""
    from judgekeeper.start import _interactive
    from judgekeeper.start_label import Workspace, make_folder

    if not _interactive() or not talk.confirm(QUESTION, default=True, with_yes=False,
                                              hint=QUESTION):
        return "commands"
    command = _promptfoo(root)
    if command is None:
        talk.say("promptfoo was not found here, so judgekeeper can't run the export for you.")
        return "commands"
    make_folder(Workspace(root))
    out = root / LATEST
    proc = again.run_process([command, "export", "eval", "latest", "-o", LATEST], cwd=root,
                             env={**os.environ, **ENV}, timeout=300)
    if proc.returncode != 0 or not out.is_file():
        tail = [x for x in (proc.stderr or proc.stdout or "").strip().splitlines() if x.strip()]
        talk.say(f"promptfoo export did not work: {scrub(tail[-1]) if tail else 'no file'}")
        out.unlink(missing_ok=True)
        return "commands"
    try:
        data = json.loads(out.read_text(encoding="utf-8"))
    except ValueError:
        data = {}
    if not isinstance(data, dict) or not _this_project(root, data):
        out.unlink()
        talk.say(ANOTHER)
        return "stop"
    target = root / TARGET
    if target.exists() and not talk.confirm(f"{TARGET} is already here. Replace it?",
                                            default=False, with_yes=False, hint=TARGET):
        talk.say(f"Your last promptfoo run is saved as {LATEST}. To use it: judgekeeper start "
                 f"{LATEST}")
        return "stop"
    out.replace(target)
    talk.say(f"Saved your last promptfoo run as {TARGET}.")
    return "done"
