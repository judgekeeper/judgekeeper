"""The LLM-as-a-judge's setup: everything about it that can change its verdicts, as one dict.

That is more than its model: the eval tool and its version, the kind of judge (one call, a
panel with a vote rule, or an agent with tools), its models, its rule, the grading prompt, the
temperature, the pass mark and the endpoint. All of it is read from the saved results, never
from the eval config: there is no YAML parser here, and the results say what really ran. The
tool's version falls back to the project's lockfile when the results don't hold it.

`.judgekeeper/judge.json` keeps the setup last checked and is rewritten only when the setup's
hash changes, so a committed judge.json changes only when the judge did. Before marking starts
it follows the newest results; once marking starts it keeps the judge of the marks until
`judgekeeper check` has re-checked a new one.

`changes(old, new)` says what changed, in words ("model gpt-4o-mini -> claude-haiku-4-5").
"""

from __future__ import annotations

import hashlib
import json
import re
import tomllib
from pathlib import Path

from judgekeeper import __version__, find
from judgekeeper.fingerprint import rule_hash, utc_now
from judgekeeper.redact import scrub, scrub_value
from judgekeeper.textio import loads, write_replacing

FILE = "judge.json"
ONE_CALL, PANEL, AGENT = "one call", "panel", "agent"
FIELDS = ("tool", "tool_version", "version_from", "kind", "models", "vote", "agent",
          "rule_hash", "prompt_hash", "temperature", "pass_mark", "endpoint")
NOT_HASHED = ("version_from",)  # where the version was read is not the judge
TOOL_ONLY = {"tool_version", "prompt_hash"}  # an eval tool update may change its own prompt
# The package each eval tool is installed as: npm for promptfoo, PyPI for the others
PACKAGES = {"promptfoo": "promptfoo", "deepeval": "deepeval", "inspect": "inspect-ai",
            "mlflow": "mlflow"}
# promptfoo's agent graders: a model with tools (agent-rubric needs one)
AGENT_TYPES = ("agent-rubric",)
WRITES_NOT = {"sandbox_mode": "read-only", "sandboxMode": "read-only",
              "permission_mode": "plan", "permissionMode": "plan"}
WORKS_IN = ("working_dir", "workingDir", "cwd")
TRACE = re.compile(r"\{\{\s*trace\s*\}\}")
_PROMPTFOO_VERSION = re.compile(rb'"promptfooVersion"\s*:\s*"([^"\\]{1,40})"')
_PIN = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)(?:\[[^\]]*\])?\s*==\s*([^\s;#,]+)")


# Reading the setup ---------------------------------------------------------------------------

# The fields taken from the results as written, where a key could be: it is hidden there. The
# others (the tool's name, the kind of judge, hashes) are judgekeeper's own, compared and looked
# up as they are; a credential's value that happens to be one of them never changes them.
FROM_RESULTS = ("tool_version", "models", "agent", "endpoint")


def keys_hidden(setup: dict) -> dict:
    """`setup` with any key in a field from the results hidden (FROM_RESULTS)."""
    return {k: scrub_value(v) if k in FROM_RESULTS else v for k, v in setup.items()}


def of(found) -> dict:
    """The setup of the judge `found` (a start.Found) found in the newest results, with any
    key in it hidden, as judge.json keeps it (keys_hidden)."""
    version, source = version_of(found)
    kind, models, vote, agent = _shape(found)
    fp = found.fingerprint or {}
    pm = found.pass_mark
    return keys_hidden({"tool": found.tool, "tool_version": version, "version_from": source,
            "kind": kind, "models": models, "vote": vote, "agent": agent,
            "rule_hash": rule_hash(scrub(found.rule)), "prompt_hash": fp.get("prompt_hash"),
            "temperature": fp.get("temperature"),
            "pass_mark": {"mark": pm["mark"], "op": pm["op"]} if pm else None,
            "endpoint": fp.get("endpoint")})


def version_of(found) -> tuple[str | None, str | None]:
    """(the eval tool's version, "results" or "lockfile"), or (None, None): from the results
    (promptfoo, Inspect AI), else from the project's lockfile."""
    newest = found.results[0].path
    version = None
    try:
        if found.tool == "promptfoo":
            m = _PROMPTFOO_VERSION.search(newest.read_bytes())
            version = m[1].decode("utf-8", errors="replace") if m else None
        elif found.tool == "inspect":
            from judgekeeper.readers.inspect_logs import eval_header

            packages = eval_header(newest).get("packages")
            value = packages.get("inspect_ai") if isinstance(packages, dict) else None
            version = value if isinstance(value, str) else None
    except OSError:
        version = None
    if version:
        return version, "results"
    if found.tool in PACKAGES:
        version = locked(Path(found.root), found.tool)
        if version:
            return version, "lockfile"
    return None, None


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def locked(root: Path, tool: str) -> str | None:
    """The exact version of the eval tool the project pins: package-lock.json for promptfoo;
    uv.lock, poetry.lock, then pyproject.toml and requirements*.txt (`==`) for the Python
    tools."""
    package = PACKAGES[tool]
    if tool == "promptfoo":
        try:
            lock = json.loads((root / "package-lock.json").read_text(encoding="utf-8"))
        except (OSError, ValueError, RecursionError):
            return None
        if not isinstance(lock, dict):
            return None
        entry = ((lock.get("packages") or {}).get(f"node_modules/{package}")
                 or (lock.get("dependencies") or {}).get(package))
        version = entry.get("version") if isinstance(entry, dict) else None
        return version if isinstance(version, str) else None
    for name in ("uv.lock", "poetry.lock"):
        try:
            data = tomllib.loads((root / name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for p in data.get("package") or []:
            if isinstance(p, dict) and _norm(str(p.get("name", ""))) == package:
                version = p.get("version")
                if isinstance(version, str):
                    return version
    for line in _pyproject_requirements(root):
        m = _PIN.match(line)
        if m and _norm(m[1]) == package:
            return m[2]
    for path in sorted(root.glob("requirements*.txt")):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, ValueError):
            continue
        for line in text.splitlines():
            m = _PIN.match(line)
            if m and _norm(m[1]) == package:
                return m[2]
    return None


def _pyproject_requirements(root: Path) -> list[str]:
    """The requirement lines of the project's pyproject.toml: [project] dependencies and
    optional-dependencies, and [dependency-groups]."""
    try:
        data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    project = data.get("project") if isinstance(data.get("project"), dict) else {}
    lists = [project.get("dependencies"), *(project.get("optional-dependencies") or {}).values()]
    groups = data.get("dependency-groups")
    lists += list(groups.values()) if isinstance(groups, dict) else []
    return [x for xs in lists if isinstance(xs, list) for x in xs if isinstance(x, str)]


def _shape(found) -> tuple[str, list[str], str | None, dict | None]:
    """(kind, models, vote, agent) of the judge."""
    models = list(found.models)
    if found.tool == "promptfoo":
        agent = _promptfoo_agent(found)
        if agent is not None:
            return AGENT, models, None, agent
    if found.tool == "inspect":
        panel, vote = _inspect_panel(found)
        if len(panel) > 1:
            return PANEL, panel, vote, None
        if panel:
            models = panel
    if found.tool == "mlflow" and found.rule and TRACE.search(found.rule):
        return AGENT, models, None, {"runtime": "mlflow", "can_write": False,
                                     "looks_at": "trace"}
    return ONE_CALL, models, None, None


def _promptfoo_agent(found) -> dict | None:
    """{runtime, can_write, looks_at} when the judge is one of promptfoo's agent graders."""
    from judgekeeper.readers.promptfoo import (
        _components,
        _options,
        _shaped,
        grader_of,
        judge_type,
    )

    try:
        data = json.loads(found.results[0].path.read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError):
        return None
    default_test = ((data.get("config") or {}).get("defaultTest") or {}) if isinstance(
        data, dict) else {}
    for row in ((data.get("results") or {}).get("results") or []) if isinstance(data, dict) \
            else []:
        if not _shaped(row):  # left out when it was read
            continue
        for c in _components(row.get("gradingResult")):
            a = c.get("assertion") or {}
            kind = a.get("type")
            if (a.get("metric") or kind) != found.metric or judge_type(kind) not in AGENT_TYPES:
                continue
            grader = grader_of(a, _options(row.get("testCase")),
                               default_test if isinstance(default_test, dict) else {})
            config = grader.get("config") if isinstance(grader, dict) else None
            config = config if isinstance(config, dict) else {}
            meta = c.get("metadata") if isinstance(c.get("metadata"), dict) else {}
            runtime = meta.get("agentProvider") or (
                grader if isinstance(grader, str) else (grader or {}).get("id"))
            read_only = any(config.get(k) == v for k, v in WRITES_NOT.items())
            return {"runtime": runtime if isinstance(runtime, str) else None,
                    "can_write": False if read_only else "unknown",
                    "looks_at": "files" if any(config.get(k) for k in WORKS_IN) else "unknown"}
    return None


def _models_of(value) -> list[str]:
    if isinstance(value, list):
        return [m for v in value for m in _models_of(v)[:1]]
    if isinstance(value, dict) and isinstance(value.get("model"), str):
        return [value["model"]]
    if isinstance(value, str):
        return [value]
    return []


def _inspect_panel(found) -> tuple[list[str], str | None]:
    """The grader models of the judge in the order the log declares them, and the vote rule
    (the scorer's `reducer`) when it is written."""
    from judgekeeper.readers.inspect_logs import eval_header

    spec = eval_header(found.results[0].path)
    name = str(found.metric).split(".")[0]
    options = next((s.get("options") or {} for s in spec.get("scorers") or []
                    if isinstance(s, dict) and s.get("name") == name), {})
    options = options if isinstance(options, dict) else {}
    models = _models_of((spec.get("model_roles") or {}).get("grader")) or _models_of(
        options.get("model"))
    reducer = options.get("reducer")
    return models, reducer if isinstance(reducer, str) else None


# judge.json ----------------------------------------------------------------------------------

def hash_of(setup: dict) -> str:
    kept = {k: v for k, v in setup.items() if k not in NOT_HASHED}
    text = json.dumps(kept, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def from_start(data: dict) -> dict:
    """The judge of the marks as start.json keeps it, for a judge.json from before setups:
    only the fields start.json knows."""
    fp = data.get("fingerprint") or {}
    pm = data.get("pass_mark")
    return {"tool": data.get("tool"), "models": [fp["model"]] if fp.get("model") else [],
            "rule_hash": rule_hash(data.get("rule")), "prompt_hash": fp.get("prompt_hash"),
            "temperature": fp.get("temperature"),
            "pass_mark": {"mark": pm.get("mark"), "op": pm.get("op")}
            if isinstance(pm, dict) else None,
            "endpoint": fp.get("endpoint")}


def _saved(ws) -> dict | None:
    from judgekeeper.textio import read_regular

    try:  # a named pipe there is never read (it would wait): make_folder then refuses it
        data = loads(read_regular(ws.dir / FILE).decode("utf-8"))
    except (OSError, ValueError):
        return None
    if isinstance(data, dict) and isinstance(data.get("setup"), dict) \
            and isinstance(data.get("setup_hash"), str):
        return data
    return None


def read(ws) -> dict | None:
    """judge.json (the setup last checked); for an older judge.json, or none, while marking:
    the judge of the marks from start.json. None when there is neither."""
    data = _saved(ws)
    if data is not None:
        return data
    try:
        start = ws.data()
    except (OSError, ValueError):
        return None
    setup = from_start(start)
    return {"setup": setup, "setup_hash": hash_of(setup), "first_seen": start.get("started_at"),
            "judgekeeper_version": start.get("judgekeeper_version")}


def save(ws, setup: dict, metric: str | None = None) -> bool:
    """Write judge.json for `setup` unless it already holds a setup with the same hash, with
    the judge's name in the results (`metric`, not part of the hash: a check in CI, where only
    judge.json and history.jsonl are committed, finds the same judge by it). Returns whether
    it was written."""
    from judgekeeper.start_label import make_folder

    setup = keys_hidden(setup)
    new_hash = hash_of(setup)
    old = _saved(ws)
    if old is not None and old["setup_hash"] == new_hash:
        return False
    make_folder(ws)
    data = {"setup": setup, "setup_hash": new_hash, "first_seen": utc_now(),
            "judgekeeper_version": __version__, **({"metric": scrub(metric)} if metric else {})}
    write_replacing(ws.dir / FILE, json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    return True


# What changed, in words ----------------------------------------------------------------------

def _number(value) -> str:
    return f"{value:g}" if isinstance(value, int | float) and not isinstance(value, bool) \
        else str(value)


def _set(value) -> str:
    return "not set" if value is None else _number(value)


def _pass_mark(pm) -> str:
    if not pm:
        return "not set"
    mark = _number(pm.get("mark"))
    return mark if pm.get("op") in (">=", None) else f"{pm['op']} {mark}"


def _models(models) -> str:
    return ", ".join(models) if models else "not written down"


def _kind(setup: dict) -> str:
    if setup.get("kind") == PANEL:
        vote = f" ({setup['vote']})" if setup.get("vote") else ""
        return f"now a panel of {len(setup.get('models') or [])}{vote}"
    if setup.get("kind") == AGENT:
        runtime = (setup.get("agent") or {}).get("runtime")
        return f"now an agent ({runtime})" if runtime else "now an agent"
    return "now a single LLM-as-a-judge"


def _differ(old: dict, new: dict) -> set[str]:
    return {k for k in FIELDS if k not in NOT_HASHED and k in old and k in new
            and old[k] != new[k]}


def changes(old: dict, new: dict) -> list[str]:
    """What changed between two setups, in words; [] for the same judge. A field only one of
    them has (a judge.json from before setups) is not compared."""
    differ = _differ(old, new)
    tool = find.NAMES.get(new.get("tool"), new.get("tool"))
    out = []
    if "tool" in differ:
        out.append(f"eval tool {find.NAMES.get(old['tool'], old['tool'])} -> {tool}")
    if "tool_version" in differ:
        out.append(f"{tool} {old['tool_version'] or 'version unknown'} -> "
                   f"{new['tool_version'] or 'version unknown'}")
    kind = "kind" in differ
    if kind:
        out.append(_kind(new))
    if "models" in differ and not (kind and PANEL in (old["kind"], new["kind"])):
        several = max(len(old["models"] or []), len(new["models"] or [])) > 1
        out.append(f"{'models' if several else 'model'} {_models(old['models'])} -> "
                   f"{_models(new['models'])}")
    if "vote" in differ and not kind:
        out.append(f"vote {old['vote'] or 'not written down'} -> "
                   f"{new['vote'] or 'not written down'}")
    if "agent" in differ and not kind:
        out.append("agent settings changed")
    if "rule_hash" in differ:
        out.append("rule changed")
    if "prompt_hash" in differ and "rule_hash" not in differ:  # the rule is in the prompt
        out.append("grading prompt changed")
    if "temperature" in differ:
        out.append(f"temperature {_set(old['temperature'])} -> {_set(new['temperature'])}")
    if "pass_mark" in differ:
        out.append(f"pass mark {_pass_mark(old['pass_mark'])} -> {_pass_mark(new['pass_mark'])}")
    if "endpoint" in differ:
        out.append(f"endpoint {old['endpoint'] or 'default'} -> {new['endpoint'] or 'default'}")
    return out


def tool_only(old: dict, new: dict) -> bool:
    """Whether only the eval tool's version changed (and with it, maybe, its own grading
    prompt): the judge's rule, model and pass mark are the same."""
    differ = _differ(old, new)
    return "tool_version" in differ and differ <= TOOL_ONLY


def tool_words(old: dict, new: dict) -> str:
    """"promptfoo 0.124.1 -> 0.125.0"."""
    tool = find.NAMES.get(new.get("tool"), new.get("tool"))
    return (f"{tool} {old.get('tool_version') or 'version unknown'} -> "
            f"{new.get('tool_version') or 'version unknown'}")


def judge_change(old: dict, new: dict) -> str | None:
    """What changed in the judge's identity, in words, or None."""
    parts = []

    def shown(value):
        return "not recorded" if value is None else value

    if old.get("model") != new.get("model"):
        parts.append(f"the model was {shown(old.get('model'))}, now {shown(new.get('model'))}")
    elif old.get("provider") != new.get("provider"):
        parts.append(f"the provider was {shown(old.get('provider'))}, now "
                     f"{shown(new.get('provider'))}")
    if old.get("prompt_hash") != new.get("prompt_hash"):
        if None in (old.get("prompt_hash"), new.get("prompt_hash")):  # unknown is not changed
            was, now = (("recorded" if v else "not recorded")
                        for v in (old.get("prompt_hash"), new.get("prompt_hash")))
            parts.append(f"the prompt was {was}, now {now}")
        else:
            parts.append("the prompt changed")
    if old.get("temperature") != new.get("temperature"):
        parts.append(f"the temperature was {shown(old.get('temperature'))}, now "
                     f"{shown(new.get('temperature'))}")
    return "; ".join(parts) or None


__all__ = ["AGENT", "FILE", "FROM_RESULTS", "ONE_CALL", "PANEL", "changes", "from_start",
           "hash_of", "judge_change", "keys_hidden", "locked", "of", "read", "save", "tool_only",
           "tool_words", "version_of"]
