"""Langfuse: judge and human scores from the public API, read-only, standard library only.

`GET /api/public/v3/scores` (cursor paging, 100 a page, `fields=details,subject,annotation`)
returns judge and human scores alike; the user names which score is which. One
`GET /api/public/v2/evaluators` call gives the judge's model, prompt and version. Shapes are
from the OpenAPI (Fern) definitions in github.com/langfuse/langfuse
(fern/apis/server/definition/scores-v3.yml, evaluators.yml, commons.yml) at commit
9a29212e855c60ffb86d1989b62918b3781d9652; this reader was checked against responses built from
them, not against a live server.

- Host: `LANGFUSE_BASE_URL`, else `LANGFUSE_HOST`, else https://cloud.langfuse.com (EU), as
  the Langfuse Python SDK resolves it. Keys: `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, sent
  as HTTP Basic auth to that host only. There is no flag that takes a key.
- Credentials never appear in output: errors give the status and path, never the header, the
  response body or a URL with credentials. A redirect to another host is refused.
- Bounded: a time window (`--from`/`--to`) or `--max-items` is required. Requests are spaced to
  at most `rate` a minute (30, Langfuse Cloud's Hobby limit, by default). HTTP 429 waits for
  `Retry-After` and retries, up to MAX_RETRIES times.
- `source` (ANNOTATION, API, EVAL) is a check, not the mapping: SDK judges post as API. A
  judge score with source ANNOTATION, or a human score with source EVAL, is noted. When the
  judge and human scores share a name, source splits them: ANNOTATION is the human's.
- Item id is `subject.id`. Values by `dataType`: BOOLEAN pass/fail, NUMERIC a score (needs
  --pass-if), CATEGORICAL a label; TEXT and CORRECTION scores carry no verdict and are skipped.
  Rationale is `comment`. Annotator ids and metadata are never kept.
- Langfuse keeps one judge score per subject and name, so the import is one run.
"""

from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.request
from collections import Counter
from datetime import UTC, datetime
from urllib.parse import urlencode, urlsplit

from judgekeeper.anchors import canonical_json
from judgekeeper.fingerprint import plaintext_warning
from judgekeeper.records import HUMAN, LLM, RecordList, RecordsError, ScoreRecord

DEFAULT_HOST = "https://cloud.langfuse.com"
HOST_VARS = ("LANGFUSE_BASE_URL", "LANGFUSE_HOST")
KEY_VARS = ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY")
SCORES_PATH = "/api/public/v3/scores"
EVALUATORS_PATH = "/api/public/v2/evaluators"
FIELDS = "details,subject,annotation"
PAGE_SIZE = 100
DEFAULT_RATE = 30.0  # requests a minute
MAX_RETRIES = 5
TIMEOUT = 60.0
EXPECTED_SOURCE = {LLM: {"EVAL", "API"}, HUMAN: {"ANNOTATION", "API"}}
VERDICT_TYPES = ("BOOLEAN", "NUMERIC", "CATEGORICAL")
ONE_RUN_NOTE = ("Langfuse keeps one judge score per subject and name: this import is one run, "
                "so the noise floor is unknown. Re-judge the labeled items (--anchors-out) for "
                "a real one.")

# Swapped out by the tests, so rate limiting and back-off never sleep for real.
_clock = time.monotonic
_sleep = time.sleep


class LangfuseError(Exception):
    """A request to Langfuse failed: a runtime failure, not a usage error."""


def host_from_env() -> str:
    for name in HOST_VARS:
        value = os.environ.get(name, "").strip()
        if value:
            return value.rstrip("/")
    return DEFAULT_HOST


def _check_host(host: str) -> str:
    parts = urlsplit(host)
    if "@" in parts.netloc:
        raise RecordsError("the Langfuse host must not contain credentials (user:password@); "
                           "the keys go in LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY")
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise RecordsError("the Langfuse host must be an http:// or https:// URL, e.g. "
                           f"{DEFAULT_HOST}; set LANGFUSE_HOST")
    return host


def parse_time(text: str, flag: str) -> datetime:
    """A date (2026-09-01) or an ISO 8601 time; naive times are UTC."""
    try:
        value = datetime.fromisoformat(text.strip())
    except ValueError:
        raise RecordsError(f"{flag} {text!r} is not a date (YYYY-MM-DD) or ISO 8601 "
                           "time") from None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class _SameHostRedirects(urllib.request.HTTPRedirectHandler):
    """Follow a redirect only to the same scheme, host and port: never send the keys away."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        old, new = urlsplit(req.full_url), urlsplit(newurl)
        if (old.scheme, old.hostname, old.port) != (new.scheme, new.hostname, new.port):
            raise LangfuseError(f"Langfuse answered {code} with a redirect to another host "
                                f"({new.hostname}); refused, so the keys stay with "
                                f"{old.hostname}. Check LANGFUSE_HOST.")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class LangfuseClient:
    """GET requests to one Langfuse host, spaced to `rate` a minute, retried on HTTP 429."""

    def __init__(self, host: str, public_key: str, secret_key: str,
                 rate: float = DEFAULT_RATE):
        self.host = _check_host(host)
        self._auth = "Basic " + base64.b64encode(
            f"{public_key}:{secret_key}".encode()).decode()
        self.interval = 60.0 / rate
        self._last: float | None = None
        self._opener = urllib.request.build_opener(_SameHostRedirects())

    def _wait_turn(self) -> None:
        if self._last is not None:
            delay = self._last + self.interval - _clock()
            if delay > 0:
                _sleep(delay)
        self._last = _clock()

    def get(self, path: str, query: dict) -> dict:
        url = f"{self.host}{path}?{urlencode(query)}"
        for attempt in range(MAX_RETRIES + 1):
            self._wait_turn()
            req = urllib.request.Request(url, headers={"Authorization": self._auth,
                                                       "Accept": "application/json"})
            try:
                with self._opener.open(req, timeout=TIMEOUT) as resp:
                    body = resp.read()
            except urllib.error.HTTPError as e:
                if e.code == 429 and attempt < MAX_RETRIES:
                    _sleep(_retry_after(e.headers.get("Retry-After"), attempt))
                    continue
                raise LangfuseError(self._status_message(e.code, path)) from None
            except urllib.error.URLError as e:
                raise LangfuseError(f"cannot reach Langfuse at {urlsplit(self.host).hostname}: "
                                    f"{e.reason}") from None
            try:
                return json.loads(body)
            except ValueError:
                raise LangfuseError(f"Langfuse returned something other than JSON for GET "
                                    f"{path}") from None
        raise AssertionError("unreachable")

    @staticmethod
    def _status_message(code: int, path: str) -> str:
        hint = {401: ": check LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY (and that they "
                     "belong to this host's region)",
                403: ": the key cannot read this project",
                429: f": still rate limited after {MAX_RETRIES} retries; lower --rate"}
        return f"Langfuse answered HTTP {code} to GET {path}{hint.get(code, '')}"


def _retry_after(value: str | None, attempt: int) -> float:
    """Seconds to wait: Retry-After as seconds or an HTTP date, else 2, 4, 8, ..."""
    if value:
        try:
            return max(0.0, float(value))
        except ValueError:
            from email.utils import parsedate_to_datetime

            try:
                when = parsedate_to_datetime(value)
                return max(0.0, (when - datetime.now(UTC)).total_seconds())
            except (TypeError, ValueError):
                pass
    return float(2 ** (attempt + 1))


def _keys() -> tuple[str, str]:
    missing = [k for k in KEY_VARS if not os.environ.get(k)]
    if missing:
        raise RecordsError(f"set {' and '.join(missing)} (Langfuse project settings, API keys) "
                           "in the environment")
    return os.environ[KEY_VARS[0]], os.environ[KEY_VARS[1]]


def _value(score: dict) -> tuple:
    """(label, score) by dataType, or None for a score type with no verdict."""
    v, data_type = score.get("value"), str(score.get("dataType") or "").upper()
    if data_type == "BOOLEAN" or isinstance(v, bool):
        if isinstance(v, bool):
            return ("pass" if v else "fail"), None
        return v, None  # the normaliser reads "true"/"false" spellings
    if data_type == "NUMERIC":
        return None, None if v is None else float(v)
    if data_type == "CATEGORICAL":
        return v, None
    return None


def _evaluator(client: LangfuseClient, name: str) -> tuple[dict, list[str]]:
    """(evaluator fields, notes) for the judge score's name, from one evaluators call."""
    page = client.get(EVALUATORS_PATH, {"limit": PAGE_SIZE})
    found = [e for e in page.get("data") or [] if isinstance(e, dict) and e.get("name") == name]
    more = " among the first 100 evaluators" if (page.get("meta") or {}).get("cursor") else ""
    if not found:
        return {}, [(f"Langfuse has no evaluator named {name!r}{more} (scores pushed from an "
                     "SDK have none): the judge's model, prompt and version are unknown.")]
    if len(found) > 1:
        return {}, [(f"{len(found)} Langfuse evaluators are named {name!r}: the judge's "
                     "model, prompt and version are unknown.")]
    e = found[0]
    ev: dict = {}
    notes = []
    if e.get("version") is not None:
        ev["version"] = str(e["version"])
    if e.get("type") == "code":
        if e.get("sourceCode"):
            ev["prompt"] = e["sourceCode"]
        notes.append(f"Langfuse evaluator {name!r} is a code evaluator: no model.")
        return ev, notes
    if e.get("prompt"):
        ev["prompt"] = canonical_json(e["prompt"])
    config = e.get("modelConfig")
    if isinstance(config, dict) and config.get("model"):
        ev["model"] = config["model"]
        if config.get("provider"):
            ev["provider"] = config["provider"]
    else:
        notes.append(f"Langfuse evaluator {name!r}: modelConfig is null, so it uses the "
                     "project's default evaluation model, which the API does not name. Model "
                     "unknown.")
    return ev, notes


def read_langfuse(judge_score: str, human_score: str, from_: str | None = None,
                  to: str | None = None, max_items: int | None = None,
                  rate: float = DEFAULT_RATE) -> tuple[str, RecordList]:
    """ScoreRecords from Langfuse: judge scores named `judge_score`, human `human_score`.

    `from_`/`to` bound the score timestamps (a date or ISO time); `max_items` caps the scores
    read. One of them is required. Returns ("langfuse <host>", records): one run.
    """
    if not judge_score or not human_score:
        raise RecordsError("import langfuse needs --judge-score NAME and --human-score NAME")
    if from_ is None and to is None and max_items is None:
        raise RecordsError("import langfuse reads a bounded set: give a time window (--from "
                           "DATE, --to DATE) or --max-items N")
    if max_items is not None and max_items < 1:
        raise RecordsError("--max-items must be at least 1")
    if rate is None or rate <= 0:
        raise RecordsError("--rate must be a positive number of requests a minute")
    start = parse_time(from_, "--from") if from_ else None
    end = parse_time(to, "--to") if to else None
    if start and end and start >= end:
        raise RecordsError("--from must be before --to")
    host = _check_host(host_from_env())
    client = LangfuseClient(host, *_keys(), rate=rate)

    query = {"limit": PAGE_SIZE, "fields": FIELDS,
             "name": ",".join(dict.fromkeys((judge_score, human_score)))}
    if start:
        query["fromTimestamp"] = _iso(start)
    if end:
        query["toTimestamp"] = _iso(end)
    scores: list[dict] = []
    cursor = None
    while True:
        page = client.get(SCORES_PATH, {**query, **({"cursor": cursor} if cursor else {})})
        scores += [s for s in page.get("data") or [] if isinstance(s, dict)]
        cursor = (page.get("meta") or {}).get("cursor")
        if not cursor or (max_items is not None and len(scores) >= max_items):
            break
    truncated = max_items is not None and (len(scores) > max_items or cursor)
    scores = scores[:max_items] if max_items is not None else scores

    evaluator, notes = _evaluator(client, judge_score)
    records = RecordList(notes=[ONE_RUN_NOTE])
    records.notes += notes
    if plaintext := plaintext_warning(host):
        records.warnings.append(plaintext)
    if truncated:
        records.notes.append(f"Stopped at --max-items {max_items}: later scores were not read.")
    same_name = judge_score == human_score
    disagree: Counter = Counter()
    skipped: Counter = Counter()
    for s in scores:
        name, source = s.get("name"), str(s.get("source") or "").upper()
        if same_name:
            kind = HUMAN if source == "ANNOTATION" else LLM
        elif name == judge_score:
            kind = LLM
        elif name == human_score:
            kind = HUMAN
        else:
            continue
        if not same_name and source and source not in EXPECTED_SOURCE[kind]:
            disagree[(name, source, kind)] += 1
        subject = s.get("subject") or {}
        if not subject.get("id"):
            raise RecordsError("Langfuse returned a score without subject.id: the server "
                               "ignored fields=subject (is it older than the v3 scores API?)")
        value = _value(s)
        if value is None:
            skipped[(name, s.get("dataType"))] += 1
            continue
        label, score = value
        records.append(ScoreRecord(
            target_id=str(subject["id"]), name=name, annotator_kind=kind, label=label,
            score=score, explanation=(s.get("comment") or None) if kind == LLM else None,
            evaluator=dict(evaluator) if kind == LLM else {},
            created_at=s.get("timestamp")))
    for (name, source, kind), n in sorted(disagree.items()):
        side = "judge" if kind == LLM else "human"
        scores_have = "score has" if n == 1 else "scores have"
        records.notes.append(f"{n} {name!r} {scores_have} source {source}, but you named "
                             f"{name!r} as the {side} score.")
    if same_name:
        records.notes.append(f"--judge-score and --human-score are both {judge_score!r}: "
                             "scores with source ANNOTATION are read as human, the rest as "
                             "judge.")
    for (name, data_type), n in sorted(skipped.items(), key=str):
        records.notes.append(f"{n} {name!r} score(s) of dataType {data_type} skipped: no "
                             f"verdict (verdict types are {', '.join(VERDICT_TYPES)}).")
    if not any(r.annotator_kind == LLM for r in records):
        raise RecordsError(f"no Langfuse scores named {judge_score!r} in the window read")
    return f"langfuse {urlsplit(host).hostname}", records
