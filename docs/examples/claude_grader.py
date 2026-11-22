"""Ask a Claude model to grade items, and keep one fingerprinted line per judgment.

Shared by the grade.py scripts of label-studio/, people-agree/ and agent-steps/. It calls the
Anthropic API directly with the `anthropic` package (`pip install anthropic`, not a dependency
of judgekeeper). The key is read from ANTHROPIC_API_KEY by the SDK; this file never touches it.

What every judgment carries (the judge fingerprint), in the raw file and in grades-*.csv:
  provider, model (the id asked for), snapshot (the model id the API returned), prompt_hash
  (SHA-256 of the prompt template file, exactly as committed), rubric_version, temperature,
  effort, timestamp (UTC, when the reply came back).
Temperature: the API now rejects the field (HTTP 400, "Extra inputs are not permitted") for
these models, so it cannot be set, and the fingerprint records it as null.

An item the API refuses, cuts short, cannot fit, or answers with something unreadable is
recorded as an error with its kind, and is never asked again with another prompt. Only a
network or server error (kind api_error) is asked again, with the same prompt, on a re-run.
"""

import argparse
import concurrent.futures
import csv
import hashlib
import json
import re
import threading
from datetime import UTC, datetime
from pathlib import Path

import anthropic

# US$ per million tokens: (input, output). Claude Haiku 5.5 costs more above 100K prompt tokens.
PRICES = {"claude-sonnet-5-5": (2.0, 10.0), "claude-haiku-5-5": (0.10, 0.50)}
HAIKU_LONG = (0.50, 2.50)
SETUPS = {"a": ("setup-a", "claude-sonnet-5-5", "high"),
          "b": ("setup-b", "claude-haiku-5-5", "medium")}  # each model's API default effort
MAX_TOKENS = 16000
FIELDS = ["id", "grade", "error", "provider", "model", "snapshot", "prompt_hash",
          "rubric_version", "temperature", "effort", "timestamp"]


def cost(model: str, input_tokens: int, output_tokens: int) -> float:
    price_in, price_out = PRICES[model]
    if model == "claude-haiku-5-5" and input_tokens > 100_000:
        price_in, price_out = HAIKU_LONG
    return (input_tokens * price_in + output_tokens * price_out) / 1e6


def fill(template: str, **values: str) -> str:
    """Put values into {name} places in one pass, so a value is never read as a place."""
    return re.sub(r"\{(\w+)\}", lambda m: values[m.group(1)] if m.group(1) in values
                  else m.group(0), template)


def read_json_reply(text: str) -> dict:
    """The one JSON object in a reply, optionally inside a code fence."""
    body = text.strip()
    body = re.sub(r"^```(?:json)?\s*|\s*```$", "", body)
    start, end = body.find("{"), body.rfind("}")
    if start < 0 or end < start:
        raise ValueError("no JSON object in the reply")
    try:
        value = json.loads(body[start:end + 1])
    except json.JSONDecodeError as e:
        raise ValueError(f"the reply's JSON does not parse: {e}") from e
    if not isinstance(value, dict):
        raise TypeError("the reply's JSON is not an object")
    return value


def add_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--setup", choices=sorted(SETUPS), required=True,
                        help="a = claude-sonnet-5-5, b = claude-haiku-5-5")
    parser.add_argument("--out", type=Path, required=True,
                        help="folder for the raw replies and grades (outside the repository)")
    parser.add_argument("--limit", type=int, help="grade only this many items, spread evenly")
    parser.add_argument("--count-tokens", action="store_true",
                        help="count prompt tokens for every item and stop (no grading, no cost)")
    parser.add_argument("--workers", type=int, default=6)


def spread(items: list, limit: int | None) -> list:
    if not limit or limit >= len(items):
        return items
    return [items[i * len(items) // limit] for i in range(limit)]


def _too_long(e: anthropic.APIStatusError) -> bool:
    return e.status_code == 400 and bool(re.search(r"too long|exceed|too large", str(e.message),
                                                   re.IGNORECASE))


def count_tokens(client: anthropic.Anthropic, model: str, items: list, workers: int) -> dict:
    """Prompt tokens per item id, by the API's free counter; None where it cannot fit."""
    def one(item):
        try:
            n = client.messages.count_tokens(
                model=model, messages=[{"role": "user", "content": item[1]}]).input_tokens
        except anthropic.APIStatusError as e:
            if _too_long(e) or e.status_code == 413:
                return item[0], None
            raise
        return item[0], n
    with concurrent.futures.ThreadPoolExecutor(workers) as pool:
        return dict(pool.map(one, items))


def _judge(client, setup, item_id, prompt, parse, fingerprint):
    name, model, effort = setup
    rec = {"setup": name, "ok": False, "grade": None, "value": None, "reason": None,
           "error_kind": None, "error": None, "text": None, "stop_reason": None,
           "stop_category": None, "input_tokens": 0, "output_tokens": 0, "request_id": None}
    try:
        reply = client.messages.create(
            model=model, max_tokens=MAX_TOKENS,
            output_config={"effort": effort, "format": {
                "type": "json_schema", "schema": fingerprint["output_schema"]}},
            messages=[{"role": "user", "content": prompt}])
    except anthropic.APIStatusError as e:
        rec["error_kind"] = "too_long" if _too_long(e) else "api_error"
        rec["error"] = f"HTTP {e.status_code}: {str(e.message)[:300]}"
        rec["request_id"] = getattr(e, "request_id", None)
        rec["fingerprint"] = dict(fingerprint, snapshot=None, timestamp=_now())
        return rec
    except (anthropic.APIConnectionError, anthropic.APITimeoutError) as e:
        rec["error_kind"], rec["error"] = "api_error", f"{type(e).__name__}: {e}"[:300]
        rec["fingerprint"] = dict(fingerprint, snapshot=None, timestamp=_now())
        return rec
    rec["fingerprint"] = dict(fingerprint, snapshot=reply.model, timestamp=_now())
    rec["request_id"] = reply._request_id
    rec["stop_reason"] = reply.stop_reason
    rec["input_tokens"] = reply.usage.input_tokens
    rec["output_tokens"] = reply.usage.output_tokens
    text = "".join(b.text for b in reply.content if b.type == "text")
    rec["text"] = text
    if reply.stop_reason == "refusal":
        rec["error_kind"] = "refusal"
        details = getattr(reply, "stop_details", None)
        rec["stop_category"] = getattr(details, "category", None)
        rec["error"] = f"the model refused ({rec['stop_category']})"
    elif reply.stop_reason != "end_turn":
        rec["error_kind"], rec["error"] = "cut_short", f"stop_reason {reply.stop_reason}"
    else:
        try:
            rec["value"], rec["reason"] = parse(text, item_id)
            rec["ok"] = True
        except (ValueError, TypeError) as e:
            rec["error_kind"], rec["error"] = "unreadable", str(e)[:300]
    return rec


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_raw(path: Path) -> dict:
    """The newest raw line per id."""
    out = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rec = json.loads(line)
                out[rec["id"]] = rec
    return out


def grade_items(client, setup_key: str, items: list, parse, template_path: Path,
                rubric_version: str, out: Path, workers: int, label_of,
                header: list[str] | None = None, *, schema: dict) -> list:
    """Grade items = [(id, prompt)], appending raw lines to out/raw-<setup>.jsonl.

    Returns one raw record per item, in order. `label_of(value)` is the text for grades.csv.
    `schema` is the JSON Schema the reply must follow (the API's structured output), so a
    reply cannot come back as broken JSON. It is kept in each raw line's fingerprint.
    """
    name, model, effort = SETUPS[setup_key]
    fingerprint = {"provider": "anthropic", "model": model, "prompt_hash":
                   hashlib.sha256(template_path.read_bytes()).hexdigest(),
                   "rubric_version": rubric_version, "temperature": None, "effort": effort,
                   "output_schema": schema}
    out.mkdir(parents=True, exist_ok=True)
    raw_path = out / f"raw-{name}.jsonl"
    done = {i: r for i, r in load_raw(raw_path).items() if r["error_kind"] != "api_error"}
    todo = [it for it in items if it[0] not in done]
    lock = threading.Lock()
    spent = [0.0, 0]
    print(f"{name} ({model}, effort {effort}): {len(items)} items, {len(done)} already done, "
          f"{len(todo)} to ask", flush=True)

    def work(item):
        rec = _judge(client, SETUPS[setup_key], item[0], item[1], parse, fingerprint)
        rec["id"] = item[0]
        rec["cost_usd"] = cost(model, rec["input_tokens"], rec["output_tokens"])
        with lock:
            with raw_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            spent[0] += rec["cost_usd"]
            spent[1] += 1
            if spent[1] % 25 == 0:
                print(f"  {spent[1]} of {len(todo)} asked, US${spent[0]:.2f} so far", flush=True)
        return rec

    with concurrent.futures.ThreadPoolExecutor(workers) as pool:
        for rec in pool.map(work, todo):
            done[rec["id"]] = rec
    records = [done[i] for i, _ in items]
    write_grades(out / f"grades-{name}.csv", records, label_of, header)
    write_summary(out / f"summary-{name}.json", name, model, effort, records)
    return records


def write_grades(path: Path, records: list, label_of, header: list[str] | None = None) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        for line in header or []:
            f.write(f"# {line}\n")
        w = csv.writer(f, lineterminator="\n")
        w.writerow(FIELDS)
        for r in records:
            fp = r["fingerprint"]
            w.writerow([r["id"], label_of(r["value"]) if r["ok"] else "none",
                        r["error_kind"] or "", fp["provider"], fp["model"], fp["snapshot"] or "",
                        fp["prompt_hash"], fp["rubric_version"], "", fp["effort"],
                        fp["timestamp"]])


def write_records(path: Path, records: list, data: dict, name: str) -> None:
    """The graded items in judgekeeper's records format; items with an error are left out."""
    with path.open("w", encoding="utf-8") as f:
        for r in records:
            if not r["ok"]:
                continue
            fp = r["fingerprint"]
            f.write(json.dumps({
                "schema_version": 2, "target_id": r["id"], "name": name,
                "annotator_kind": "LLM", "label": r["value"], "explanation": r["reason"],
                "input": data[r["id"]]["input"], "output": data[r["id"]]["output"],
                "evaluator": {"provider": fp["provider"], "model": fp["model"],
                              "snapshot": fp["snapshot"], "prompt_hash": fp["prompt_hash"],
                              "version": fp["rubric_version"], "temperature": None},
                "created_at": fp["timestamp"]}, ensure_ascii=False) + "\n")


def write_summary(path: Path, name: str, model: str, effort: str, records: list) -> None:
    errors: dict[str, int] = {}
    for r in records:
        if not r["ok"]:
            errors[r["error_kind"]] = errors.get(r["error_kind"], 0) + 1
    categories: dict[str, int] = {}
    for r in records:
        if r["error_kind"] == "refusal":
            key = str(r["stop_category"])
            categories[key] = categories.get(key, 0) + 1
    summary = {
        "setup": name, "model": model, "effort": effort, "items": len(records),
        "graded": sum(r["ok"] for r in records), "errors": errors,
        "refusal_categories": categories,
        "input_tokens": sum(r["input_tokens"] for r in records),
        "output_tokens": sum(r["output_tokens"] for r in records),
        "cost_usd": round(sum(r["cost_usd"] for r in records), 4),
    }
    path.write_text(json.dumps(summary, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(summary), flush=True)
