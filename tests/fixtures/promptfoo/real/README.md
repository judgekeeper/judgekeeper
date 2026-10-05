# promptfoo fixture from a real run

`results.json` was written by promptfoo 0.123.1 itself:

```
cd tests/fixtures/promptfoo/real && sh make.sh
```

`make.sh` runs `promptfoo eval --repeat 3 -j 1 --no-cache -o results.json` on
`promptfooconfig.yaml`. Both providers are `exec:` Python scripts, so nothing calls a model or
an API: `answerer.py` answers each question, and `grader.py` is the llm-rubric grader
(`defaultTest.options.provider`), printing `{"pass", "score", "reason"}` JSON. The grader
passes Q0, Q1 and Q5 on every call and Q2 on its second call only, so repeat 2 differs.
`labels.csv` holds the human labels (Q0-Q2 pass, Q3-Q5 fail), keyed by the `qid` var.

What the real file shows, and the hand-built `../results.json` had wrong at first: every
repeat gets its own `testIdx` (0-17 here), all with `promptIdx` 0 and identical vars. The
reader groups by item id, never by `testIdx`. Expected numbers: `tests/test_import_real.py`.
