# DeepEval fixture from real runs

`results/test_run_*.json` were written by deepeval 4.2.7 itself:

```
pip install deepeval
cd tests/fixtures/deepeval/real && python make_runs.py
```

`make_runs.py` sets `DEEPEVAL_RESULTS_FOLDER=results` and calls `deepeval.evaluate` three
times on six named test cases (c0-c5) with a plain `BaseMetric` that uses no model: it passes
the cases listed for that run in `PASSES`. Nothing calls an API and telemetry is opted out.
DeepEval writes one `test_run_<YYYYMMDD_HHMMSS>.json` per run; the script waits a second
between runs because the timestamp has one-second resolution. It also writes `.deepeval/` in
the working directory, which the script deletes. `labels.csv` holds the human labels (c0-c2
pass, c3-c5 fail).

A metric without a model records no `evaluationModel`, so the judge model is unknown in the
report. Expected numbers: `tests/test_import_real.py`.
