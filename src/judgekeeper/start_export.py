"""When promptfoo keeps its results only in its own database, judgekeeper offers to run promptfoo's
`export` command for the user, at a terminal only, and Enter is No. The question names the
promptfoo it runs: the project's own (node_modules/.bin, code from the folder) or the one on the
PATH. Without a terminal, or on No, it prints the commands.

The export reads promptfoo's database in the home folder and writes one file; it runs no
tests and calls no model. It runs with promptfoo's telemetry, update check and logs off, in an
empty temp folder (promptfoo would load a promptfooconfig.js from the folder it runs in):

    promptfoo export eval latest -o <project>/.judgekeeper/promptfoo-latest.json

"latest" is the user's last promptfoo run, which may be from another project, so the file is
checked against the promptfoo config Find found (evals/promptfooconfig.yaml, say): its
`config.description`, else its prompts. With no config found it can't be told, so it counts as
another project's. A run from another project is deleted with a message saying how to find the
right one. A match moves to
`promptfoo-results.json` in the project (asking first if that name is taken) and judgekeeper
carries on.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from judgekeeper import again, textio
from judgekeeper.again.fresh import AgainError
from judgekeeper.redact import scrub

LATEST = ".judgekeeper/promptfoo-latest.json"
TARGET = "promptfoo-results.json"
ENV = {"PROMPTFOO_DISABLE_TELEMETRY": "1", "PROMPTFOO_DISABLE_UPDATE": "1",
       "PROMPTFOO_DISABLE_DEBUG_LOG": "1", "PROMPTFOO_DISABLE_ERROR_LOG": "1"}
QUESTION = ("Run this project's promptfoo ({program}) to export your latest results? It runs "
            "code from this folder, like running its tests. No AI call.")
PATH_QUESTION = ("Run promptfoo ({program}) to export your latest results? It reads promptfoo's "
                 "database in your home folder and writes one file here. No AI call.")
UNREADABLE = ("The file promptfoo exported can't be read (it is damaged, or nested too deep), "
              f"so judgekeeper removed it ({LATEST}).")
ANOTHER = ("That was your last promptfoo run, from another project. Find yours with promptfoo "
           "list evals -n 10, then run promptfoo export eval <id> -o promptfoo-results.json.")


def _promptfoo(root: Path) -> str | None:
    return again.node_bin(root, "promptfoo") or again.which("promptfoo")


def _question(root: Path, command: str) -> str:
    """The export question, naming `command`: the project's own promptfoo (node_modules/.bin,
    even when it links out of the project, as in an npm workspace; or any inside the project,
    as written or once its links are followed: also one the PATH leads to), or one on the
    PATH."""
    if command == again.node_bin(root, "promptfoo"):
        return QUESTION.format(program=Path(command).relative_to(root).as_posix())
    for path, folder in ((Path(command).absolute(), Path(root).absolute()),
                         (Path(command).resolve(), Path(root).resolve())):
        try:
            return QUESTION.format(program=path.relative_to(folder).as_posix())
        except ValueError:
            pass
    return PATH_QUESTION.format(program=command)


def _prompts(config: dict) -> list[str]:
    prompts = config.get("prompts") or []
    prompts = prompts if isinstance(prompts, list) else [prompts]
    out = []
    for p in prompts:
        text = p.get("raw") if isinstance(p, dict) else p
        if isinstance(text, str) and text.strip():
            out.append(text.strip())
    return out


def _this_project(path: Path | None, data: dict) -> bool:
    """Whether an exported run is of the promptfoo config at `path` (the one Find found): the
    same description when both have one, else one of its prompts in the config file. No
    config: no."""
    from judgekeeper.start import config_description

    if path is None or not path.is_file():  # a named pipe is not a file: never read
        return False
    config = data.get("config") if isinstance(data.get("config"), dict) else {}
    theirs = config.get("description")
    mine = config_description(path)
    if isinstance(theirs, str) and theirs.strip() and mine:
        return theirs.strip() == mine
    prompts = _prompts(config)
    if not prompts:
        return True
    try:
        text = textio.read_regular(path).decode("utf-8", errors="replace")
    except OSError:
        return False
    return any(p in text for p in prompts)


def offer(talk, root: Path, config: str | None) -> str:
    """Offer to export promptfoo's last run, for the promptfoo config Find found (`config`,
    in `root`). Returns "done" (promptfoo-results.json is now in the project), "stop" (said
    what to do instead) or "commands" (print the commands)."""
    from judgekeeper.start import _interactive
    from judgekeeper.start_label import Workspace, make_folder

    if not _interactive():
        return "commands"
    root = Path(root).absolute()  # the export runs in another folder
    command = _promptfoo(root)
    if command is None:
        talk.say("promptfoo was not found here, so judgekeeper can't run the export for you.")
        return "commands"
    question = _question(root, command)
    if not talk.confirm(question, default=False, with_yes=False, hint=question):
        return "commands"
    make_folder(Workspace(root))
    out = root / LATEST
    try:
        with tempfile.TemporaryDirectory(prefix="judgekeeper-",
                                         ignore_cleanup_errors=True) as tmp:
            proc = again.run_process([command, "export", "eval", "latest", "-o", str(out)],
                                     cwd=Path(tmp), env={**os.environ, **ENV}, timeout=300)
    except AgainError as e:  # a folder path cmd.exe would run part of (run_process)
        talk.say(f"promptfoo export did not start: {e}.")
        return "commands"
    if proc.returncode != 0 or not out.is_file():
        tail = [x for x in (proc.stderr or proc.stdout or "").strip().splitlines() if x.strip()]
        talk.say(f"promptfoo export did not work: {scrub(tail[-1]) if tail else 'no file'}")
        out.unlink(missing_ok=True)
        return "commands"
    try:  # nested thousands deep, a lone surrogate, not UTF-8, not JSON: removed, said
        data = textio.read_json(out, ValueError)
    except (ValueError, OSError):
        out.unlink(missing_ok=True)
        talk.say(UNREADABLE)
        return "commands"
    found = root / config if config else None
    if not isinstance(data, dict) or not _this_project(found, data):
        out.unlink()
        talk.say(ANOTHER)
        return "stop"
    target = root / TARGET
    if target.exists() and not talk.confirm(f"{TARGET} is already here. Replace it?",
                                            default=False, with_yes=False, hint=TARGET):
        talk.say(f"Your last promptfoo run is saved as {LATEST}. To use it: "
                 f"{textio.program()} {LATEST}")
        return "stop"
    out.replace(target)
    talk.say(f"Saved your last promptfoo run as {TARGET}.")
    return "done"
