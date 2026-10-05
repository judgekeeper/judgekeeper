"""Write recorded Langfuse API responses for tests/test_import_langfuse.py.

Run from the repo root: python tests/fixtures/langfuse/make_responses.py

No Langfuse server is available offline, so these responses are built from the public API's
OpenAPI (Fern) definitions in github.com/langfuse/langfuse at commit
9a29212e855c60ffb86d1989b62918b3781d9652 (2026-10-01):
- fern/apis/server/definition/scores-v3.yml: `GET /api/public/v3/scores` returns
  `{data: [ScoreV3], meta: {limit, cursor?}}`; `ScoreV3` is a union on `dataType` with core
  fields id, projectId, name, value, dataType, source, timestamp, environment, createdAt,
  updatedAt; `fields=details` adds comment, configId, metadata; `fields=subject` adds
  `subject: {kind, id}`; `fields=annotation` adds authorUserId, queueId. `meta.cursor` is
  absent on the final page.
- fern/apis/server/definition/evaluators.yml: `GET /api/public/v2/evaluators` returns
  `{data: [Evaluator], meta: {cursor?}}`; an `llm_as_judge` evaluator has name, version,
  versionId, prompt (chat messages) and modelConfig `{provider, model}` or null.
- commons.yml: `ScoreSource` is ANNOTATION, API or EVAL.

Six traces trace-1..trace-6 carry a judge score `helpfulness` (NUMERIC, source EVAL) and a human
score `helpfulness_human` (BOOLEAN, source ANNOTATION; trace-5's arrived through the API, so its
source is API). trace-7 has a judge score only. With --pass-if 'score>=0.5':
  human:  trace-1..3 true, trace-4..6 false
  judge:  0.9 0.8 0.3 | 0.2 0.1 0.7  (trace-7: 0.6, no human score)
  TP 2, FN 1 (trace-3), TN 2, FP 1 (trace-6) -> TPR 2/3, TNR 2/3,
  po 4/6, judge passes 3 of 6, pe (3*3 + 3*3)/36 = 1/2, kappa (2/3 - 1/2)/(1/2) = 1/3
The 13 scores are served 5, 5 and 3 to a page, as a server may return fewer than `limit`.
"""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT = "proj-fixture"
JUDGE = {1: 0.9, 2: 0.8, 3: 0.3, 4: 0.2, 5: 0.1, 6: 0.7, 7: 0.6}
HUMAN = {1: True, 2: True, 3: True, 4: False, 5: False, 6: False}
PAGE_SIZES = (5, 5, 3)
CURSORS = ("eyJwYWdlIjoyfQ", "eyJwYWdlIjozfQ")  # base64url {"page":2}, {"page":3}
PROMPT = [
    {"role": "system", "content": "You grade answers for helpfulness."},
    {"role": "user", "content": "Input: {{input}}\nOutput: {{output}}\n"
                                "Return a score from 0 to 1 and your reasoning."},
]


def _stamp(n: int, minute: int) -> str:
    return f"2026-09-2{n % 3}T10:{minute:02d}:00.000Z"


def _score(sid, name, data_type, value, source, trace, comment, minute, **annotation):
    stamp = _stamp(trace, minute)
    return {
        "id": sid, "projectId": PROJECT, "name": name, "value": value,
        "dataType": data_type, "source": source, "timestamp": stamp,
        "environment": "default", "createdAt": stamp, "updatedAt": stamp,
        "comment": comment, "configId": None, "metadata": {},
        "authorUserId": annotation.get("author"), "queueId": annotation.get("queue"),
        "subject": {"kind": "trace", "id": f"trace-{trace}"},
    }


def scores() -> list[dict]:
    out = []
    for t in sorted(JUDGE):
        out.append(_score(f"score-judge-{t}", "helpfulness", "NUMERIC", JUDGE[t], "EVAL", t,
                          f"The answer covers {'most' if JUDGE[t] >= 0.5 else 'little'} of "
                          "the question.", 1))
        if t in HUMAN:
            source = "API" if t == 5 else "ANNOTATION"
            out.append(_score(f"score-human-{t}", "helpfulness_human", "BOOLEAN", HUMAN[t],
                              source, t, "reviewed in queue", 5,
                              author="user-ann-1" if source == "ANNOTATION" else None,
                              queue="queue-1" if source == "ANNOTATION" else None))
    return out


def pages() -> list[dict]:
    data, out, start = scores(), [], 0
    for n, size in enumerate(PAGE_SIZES):
        meta = {"limit": 100}
        if n < len(CURSORS):
            meta["cursor"] = CURSORS[n]
        out.append({"data": data[start:start + size], "meta": meta})
        start += size
    assert start == len(data)
    return out


def evaluator(model_config) -> dict:
    stamp = "2026-09-01T09:00:00.000Z"
    return {
        "id": "eval-helpfulness", "name": "helpfulness", "description": None,
        "createdBy": None, "status": "active", "pausedAt": None, "pausedReason": None,
        "pausedMessage": None,
        "evaluationRuleAssignments": [{"evaluationRuleId": "rule-1"}],
        "createdAt": stamp, "updatedAt": stamp, "versionId": "evalv-3", "version": 3,
        "versionCreatedAt": stamp, "versionCreatedBy": None, "type": "llm_as_judge",
        "prompt": PROMPT, "variables": ["input", "output"], "variableMapping": None,
        "modelConfig": model_config,
        "outputDefinition": {"dataType": "NUMERIC", "score": {"description": "0 to 1"},
                             "reasoning": {"description": "why"}},
    }


def main() -> None:
    def dump(name, data):
        (HERE / name).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    for n, page in enumerate(pages(), 1):
        dump(f"scores-page-{n}.json", page)
    other = {**evaluator({"provider": "anthropic", "model": "claude-haiku-4-5"}),
             "id": "eval-tone", "name": "tone"}
    dump("evaluators.json", {"data": [other, evaluator({"provider": "openai",
                                                        "model": "gpt-4.1-mini"})],
                             "meta": {}})
    dump("evaluators-default-model.json", {"data": [evaluator(None)], "meta": {}})


if __name__ == "__main__":
    main()
