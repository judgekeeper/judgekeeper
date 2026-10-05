# Langfuse fixture: recorded responses from the published schema

No Langfuse server runs offline, so these responses were built from Langfuse's OpenAPI (Fern)
definitions, not recorded from a live server. Source: github.com/langfuse/langfuse at commit
`9a29212e855c60ffb86d1989b62918b3781d9652` (2026-10-01), files
`fern/apis/server/definition/scores-v3.yml`, `evaluators.yml`, `commons.yml` and
`utils/pagination.yml`.

```
python tests/fixtures/langfuse/make_responses.py
```

writes `scores-page-{1,2,3}.json` (`GET /api/public/v3/scores` with
`fields=details,subject,annotation`, cursor-paged), `evaluators.json` and
`evaluators-default-model.json` (`GET /api/public/v2/evaluators`, one with `modelConfig:
null`). `tests/langfuse_stub.py` serves them from a local HTTP server. The docstring of
`make_responses.py` has the scores and the hand-derived numbers.
