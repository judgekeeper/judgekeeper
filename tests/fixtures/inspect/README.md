# Inspect AI fixture

`logs/*.json` is shaped like an Inspect AI log in `.json` format (what `inspect eval
--log-format json` writes, or `inspect log dump` prints for a `.eval` log). `labels.csv` holds
the human labels for the samples nobody edited. Made by `../make_framework_fixtures.py`; no
Inspect run and no API call.

Where the shape comes from (inspect_ai source, checked on 2026-10-01):

- `src/inspect_ai/log/_log.py`: `EvalLog` (`version` 2), `EvalSpec` (`model_roles`,
  `scorers[]` with `name` and `options`), `EvalSample` (`id`, `epoch`, `scores`).
- `src/inspect_ai/model/_model_config.py`: a model role is `{model, config, base_url, args}`.
- `src/inspect_ai/scorer/_metric.py`: `Score` (`value`, `answer`, `explanation`, `metadata`,
  `history`) and `ScoreEdit` (`provenance` None for the original score).
- `src/inspect_ai/log/_score.py`, `edit_score`: on the first edit the original score is put
  first in `history`, then the edit with `provenance` (`timestamp`, `author`, `reason`).
- `src/inspect_ai/scorer/_model.py`: `model_graded_qa` scores carry `explanation` (the
  grader's completion) and `metadata.grading` (`[scoring prompt, grader reply]`).

Traps it exercises: three epochs; one score edited by a reviewer (judge I, human C); a
partial-credit `P` that needs `--label-map`; two scorers.
