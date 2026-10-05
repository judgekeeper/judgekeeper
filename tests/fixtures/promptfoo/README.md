# promptfoo fixture

`results.json` is shaped like the file `promptfoo eval -o results.json --repeat 3` writes.
Made by `../make_framework_fixtures.py`; no promptfoo run and no API call.

Where the shape comes from:

- `OutputFile`, `EvaluateSummaryV3` (`results.version` 3), `EvaluateResult` and
  `GradingResult` in promptfoo's `src/types/index.ts`, and the sample row in
  `site/docs/configuration/outputs.md`.
- The human rating component (`pass`, `score`, `reason: "Manual result (overrides all other
  grading results)"`, `comment`, `assertion: {type: "human"}`) and the override of the row's
  pass flag: `src/app/src/pages/eval/components/ResultsTable.tsx`, checked on 2026-10-01.
- Repeat rows carry no repeat index: promptfoo removes `__repeatIndex` before saving
  (`src/evaluator.ts`, `omitEvalRuntimeVars`), and each repeat gets its own `testIdx` with
  identical vars, as the real run in `real/` shows.

Traps it exercises: three repeats with no index; on t2 and t5 the human rating overrides the
row's `success`; t2 has no grader provider anywhere, so promptfoo's default grader judged it;
a `contains` (code) and a `factuality` component sit next to the llm-rubric judge.
