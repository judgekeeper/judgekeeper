# Langfuse

judgekeeper reads judge and human scores from Langfuse's public API, read-only. No export step, and nothing in your project changes.

## How scores get there

An LLM-as-a-judge evaluator writes a score (source `EVAL`) on each trace, observation or session it matches. A judge you run in your own code writes one through the SDK (source `API`). People add scores in annotation queues or the trace view (source `ANNOTATION`). All of them are the same kind of record, so one read gives both sides.

## Import it

```
export LANGFUSE_PUBLIC_KEY=pk-lf-...   # Project settings, API keys; in your shell or CI secrets
export LANGFUSE_SECRET_KEY=sk-lf-...
export LANGFUSE_HOST=https://cloud.langfuse.com   # the default; https://us.cloud.langfuse.com, or your own
judgekeeper import langfuse --judge-score helpfulness --human-score helpfulness_human \
  --from 2026-09-01 --to 2026-10-01 --pass-if "score>=0.5" --out reports/helpfulness/
```

No SDK is needed: judgekeeper calls `GET /api/public/v3/scores` (100 a page, cursor paging, `fields=details,subject,annotation`) and, once, `GET /api/public/v2/evaluators`. The host is `LANGFUSE_BASE_URL`, else `LANGFUSE_HOST`, else `https://cloud.langfuse.com` (the EU cloud), as the Langfuse Python SDK resolves it.

- `--judge-score` and `--human-score` name the two scores. They can be the same name; then scores with source `ANNOTATION` are the human's and the rest the judge's.
- `--from DATE` / `--to DATE` (a date or an ISO time, UTC) bound the score timestamps, and `--max-items N` caps the scores read. One of them is required.
- `--rate N` caps requests a minute (default 30, the Hobby plan's limit). On HTTP 429 judgekeeper waits for `Retry-After` and retries, up to 5 times.
- Values by `dataType`: `BOOLEAN` is pass/fail; `NUMERIC` needs `--pass-if`; `CATEGORICAL` uses the label defaults plus `--label-map`. `TEXT` and `CORRECTION` scores have no verdict and are skipped with a note.
- `--labels`, `--pass-if` and `--label-map` work as for every `import`.

## Human labels

Score the same subjects in an annotation queue (or the trace view) with a score config named, for example, `helpfulness_human`, and pass that name as `--human-score`. A labels table also works: `--labels labels.csv` with `id` (the trace, observation or session id) and `human_label` columns; it wins where both exist, with a note.

## Traps

- **`source` is not the mapping.** A judge in your own code posts as `API`, so judgekeeper uses the names you give. It checks `source` anyway: a judge score with source `ANNOTATION`, or a human score with source `EVAL`, is noted in the report.
- **One run.** Langfuse keeps one judge score per subject and name, so the import is one run and the noise floor is "unknown"; the report says so. Use the re-judge path below for a real one.
- **Fingerprint.** The judge's model, prompt and version come from the evaluator with the judge score's name: `modelConfig.provider`, `modelConfig.model`, a hash of `prompt` and `version` (as the rubric version). An evaluator with `modelConfig: null` uses the project's default evaluation model, which the API does not name: model unknown, with a note. A score with no matching evaluator (one pushed from an SDK) leaves the judge unknown, with a note. Langfuse stores no temperature.
- **Item ids** are `subject.id`: the trace, observation or session the score is attached to. Judge and human scores must be on the same subject to pair up.
- **Keys.** Only from the environment, sent as HTTP Basic auth to the configured host and nowhere else; a redirect to another host is refused. Errors give the HTTP status and path, never the header, the response body or the keys. Every file and message is scrubbed of both key values.

This reader was checked against responses built from Langfuse's published OpenAPI definitions (`fern/apis/server/definition/scores-v3.yml` and `evaluators.yml` at commit `9a29212`), not against a live server. If your server answers differently, please open an issue.

## Re-judge the labeled items

```
judgekeeper import langfuse --judge-score helpfulness --human-score helpfulness_human \
  --from 2026-09-01 --pass-if "score>=0.5" --anchors-out anchors/helpfulness.jsonl --out reports/helpfulness/
judgekeeper judge anchors/helpfulness.jsonl --exec "python judge.py" --runs 3 --out runs/helpfulness/
judgekeeper validate anchors/helpfulness.jsonl runs/helpfulness/ --out reports/helpfulness-rejudged/
```

`--anchors-out` writes every item with a human label as a frozen anchor set: the subject id and the label. The scores endpoint returns no trace text, so `input` and `output` are empty; your `--callable` or `--exec` judge looks the item up by `id`. Rationales and annotator ids are never written. Three runs give a real noise floor, and the frozen set is what `gate` and `migrate` work on from then on. This is the recommended path for Langfuse data.
