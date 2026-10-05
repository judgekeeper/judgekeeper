# records fixture

`export.csv` stands in for a CSV exported from some other tool, with its own column names
(`trace_id`, `metric`, `value`, `comment`, `source`, `question`, `answer`, `judge_model`).
`tests/test_records.py` maps it onto ScoreRecord fields with `--map`. Hand-written; the
numbers it should produce are derived in that test module's docstring.
