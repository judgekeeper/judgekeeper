"""Inspect AI: `.eval` or `.json` logs.

With the optional extra (`pip install "judgekeeper[inspect]"`) any log is read with
`inspect_ai.log.read_eval_log`. Without it `.json` logs are read directly; a `.eval` log is a
zip archive, so it needs the extra or `inspect log dump <file> > log.json` first.

Shape (inspect_ai log/_log.py `EvalSpec`, `EvalSample`; scorer/_metric.py `Score`): `eval`
with `model_roles` (`{grader: {model, config}}`) and `scorers[]` (`{name, options}`);
`samples[]` with `id`, `epoch`, `input`, `output` and `scores.<scorer>`: `value`,
`explanation`, `metadata`, `history[]`.

- Item id is `samples[].id`; run is `samples[].epoch`.
- `samples[].messages` (the conversation, with any tool calls) is kept as the record's
  `trajectory`, in OpenAI-style messages: role, content (text), tool_calls (id, name,
  arguments), tool_call_id. Inspect's message ids, sources and models are left out, so the
  same run read with or without inspect_ai gives the same steps. `start` makes an answer's id
  from its input, output and steps (`sample_key`).
- A score whose value is a dict (rubric and checklist graders report this way) is one judge
  per key, named `<scorer>.<key>`, each with the scorer's prompt.
- The prompt hash covers the scorer's `template` and `instructions` options, or Inspect's
  default for that scorer when they are unset; never the per-sample `metadata.grading`.
- Values `C`/`I` read as pass/fail; `P` (partial) and anything else need --label-map.
- A human edit (`edit_score`, log/_score.py) appends to `history`: the first entry is the
  original score (no provenance), later ones carry `provenance.author`. The original value is
  the judge's verdict and the edited value is the human label.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from judgekeeper.anchors import canonical_json
from judgekeeper.records import (
    HUMAN,
    LLM,
    RecordList,
    RecordsError,
    ScoreRecord,
    derive_record_id,
)
from judgekeeper.textio import read_utf8

DEFAULT_LABELS = {"C": "pass", "I": "fail"}
# Stands in for a template or instructions the scorer leaves at Inspect's default.
DEFAULT_PROMPT = "inspect_ai default for {name}"
EVAL_NEEDS_EXTRA = ("{path}: reading .eval logs needs inspect_ai. Install the extra "
                    "(pip install \"judgekeeper[inspect]\"), or run `inspect log dump {path} > "
                    "log.json` first and import the .json.")


def _load(path: Path) -> dict:
    try:
        from inspect_ai.log import read_eval_log
    except ImportError:
        read_eval_log = None
    if read_eval_log is not None:
        return read_eval_log(str(path)).model_dump(mode="json")
    if path.suffix.lower() == ".eval":
        raise RecordsError(EVAL_NEEDS_EXTRA.format(path=path))
    try:
        return json.loads(read_utf8(path, RecordsError))
    except json.JSONDecodeError as e:
        raise RecordsError(f"{path}: not JSON ({e.msg})") from None


def _model(config) -> tuple[str | None, float | None]:
    if isinstance(config, list):
        models = [c.get("model") for c in config if isinstance(c, dict)]
        temps = {(c.get("config") or {}).get("temperature") for c in config
                 if isinstance(c, dict)}
        return "+".join(sorted(m for m in models if m)) or None, (
            temps.pop() if len(temps) == 1 else None)
    if isinstance(config, dict):
        return config.get("model"), (config.get("config") or {}).get("temperature")
    if isinstance(config, str):
        return config, None
    return None, None


def _text(content):
    """A message's content as text: text parts joined; None when there is no text."""
    if isinstance(content, str) or content is None:
        return content
    if isinstance(content, list):
        texts = [p["text"] for p in content if isinstance(p, dict)
                 and p.get("type") == "text" and isinstance(p.get("text"), str)]
        return "\n".join(texts) if texts else None
    return None


def _step(message: dict) -> dict:
    step = {"role": str(message.get("role") or "unknown"), "content": _text(message.get("content"))}
    calls = [{"id": c.get("id"), "name": str(c.get("function") or c.get("name") or "unknown"),
              "arguments": c.get("arguments")}
             for c in message.get("tool_calls") or [] if isinstance(c, dict)]
    if calls:
        step["tool_calls"] = calls
    if isinstance(message.get("tool_call_id"), str):
        step["tool_call_id"] = message["tool_call_id"]
    return step


def trajectory(sample: dict) -> list[dict] | None:
    """A sample's messages as OpenAI-style steps, or None when it has none."""
    messages = [m for m in sample.get("messages") or [] if isinstance(m, dict)]
    return [_step(m) for m in messages] or None


def sample_key(sample: dict) -> str:
    """The id `start` gives this sample's answer: its input, output and steps."""
    return derive_record_id(sample.get("input"), (sample.get("output") or {}).get("completion"),
                            trajectory(sample))


def _value(v) -> tuple[object, float | None]:
    """(label, score) from a score value."""
    if isinstance(v, bool):
        return ("pass" if v else "fail"), None
    if isinstance(v, int | float):
        return None, None if math.isnan(v) else float(v)
    if isinstance(v, str):
        return v, None
    return None, None  # dict or list values: no single verdict


def scorer_prompt(name: str, options: dict) -> str:
    """The grading prompt's identity: the scorer's template and instructions from
    `eval.scorers[].options`, each standing in as Inspect's default for that scorer when unset.

    Never the rendered prompt in `score.metadata.grading`: it holds each sample's text, so its
    hash would differ per sample. With default instructions, `partial_credit` changes them.
    """
    default = DEFAULT_PROMPT.format(name=name)
    parts = {"template": options.get("template") or default,
             "instructions": options.get("instructions") or default}
    if not options.get("instructions") and options.get("partial_credit"):
        parts["partial_credit"] = True
    return canonical_json(parts)


def _human_edit(score: dict) -> tuple[dict, dict] | None:
    """(original, last human edit) when the score was edited by a named author."""
    history = [h for h in score.get("history") or [] if isinstance(h, dict)]
    edits = [h for h in history if (h.get("provenance") or {}).get("author")]
    if not history or not edits or history[0].get("provenance"):
        return None
    return history[0], edits[-1]


def read_inspect(path: str | Path) -> RecordList:
    """ScoreRecords from one Inspect AI log: one LLM record per scorer per sample and epoch."""
    path = Path(path)
    data = _load(path)
    spec = data.get("eval") if isinstance(data, dict) else None
    if not isinstance(spec, dict):
        raise RecordsError(f"{path}: not an Inspect AI log (no eval)")
    samples = data.get("samples")
    if not samples:
        raise RecordsError(f"{path}: the log has no samples (was it written with "
                           "--no-log-samples?)")
    created_at = spec.get("created")
    grader_model, temperature = _model((spec.get("model_roles") or {}).get("grader"))
    scorer_options = {s.get("name"): s.get("options") or {}
                      for s in spec.get("scorers") or [] if isinstance(s, dict)}

    records = RecordList(version=data.get("version"), label_map=DEFAULT_LABELS)
    for sample in samples:
        item_id = str(sample.get("id"))
        epoch = sample.get("epoch")
        output = (sample.get("output") or {}).get("completion")
        content = {"input": sample.get("input"), "output": output,
                   "trajectory": trajectory(sample)}
        for name, score in (sample.get("scores") or {}).items():
            if not isinstance(score, dict):
                continue
            options = scorer_options.get(name) or {}
            model, temp = grader_model, temperature
            if model is None and options.get("model"):
                model, temp = _model(options["model"])[0], None
            evaluator = {}
            if model:
                evaluator["model"] = model
                if "/" in model and "+" not in model:
                    evaluator["provider"] = model.split("/", 1)[0]
            if temp is not None:
                evaluator["temperature"] = temp
            evaluator["prompt"] = scorer_prompt(name, options)
            edit = _human_edit(score)
            judged = edit[0] if edit else score
            for key, value in _verdicts(name, judged.get("value")):
                label, number = _value(value)
                records.append(ScoreRecord(
                    target_id=item_id, name=key, annotator_kind=LLM, label=label, score=number,
                    explanation=judged.get("explanation") or None, run=epoch, **content,
                    evaluator=dict(evaluator), created_at=created_at))
            if edit:
                provenance = edit[1]["provenance"]
                for key, value in _verdicts(name, score.get("value")):
                    human_label, human_score = _value(value)
                    records.append(ScoreRecord(
                        target_id=item_id, name=key, annotator_kind=HUMAN, label=human_label,
                        score=human_score, explanation=provenance.get("reason") or None,
                        **content, created_at=provenance.get("timestamp")))
    return records


def _verdicts(name: str, value) -> list[tuple[str, object]]:
    """[(judge name, value)]: one per key of a dict value, named scorer.key; else one."""
    if isinstance(value, dict) and value:
        return [(f"{name}.{key}", v) for key, v in value.items()]
    return [(name, value)]
