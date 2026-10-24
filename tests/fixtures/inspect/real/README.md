# Inspect AI fixture from a real run

`logs/model_graded_qa.json` was written by inspect_ai 0.3.273 itself:

```
pip install inspect-ai
cd tests/fixtures/inspect/real && python make_log.py
```

`make_log.py` runs a 6-sample task for 3 epochs, scored by `model_graded_qa()` with its default
template and instructions. The solver and the grader (bound to the `grader` role) are
`mockllm/model` with `custom_outputs`: the grader replies `GRADE: C` or `GRADE: I` as listed in
`GRADES`, so nothing calls an API. The outputs carry token usage, because otherwise mockllm
counts tokens with tiktoken, which downloads its encoding. Inspect serialises the grader's
`custom_outputs` into `eval.model_roles`, which is most of the file's size.
`labels.csv` holds the human labels (1-3 pass, 4-6 fail).

What the real log shows: `eval.scorers[0].options` is `{}`, and `score.metadata.grading` holds
the rendered grading prompt with each sample's question and answer in it, so it must not be
hashed. The reader hashes the scorer's template and instructions, or Inspect's default for the
scorer when they are unset. Expected numbers: `tests/test_import_real.py`.

## Older logs

`old/inspect-0.3.2.json` and `old/inspect-0.3.204.eval` were written by those versions of
inspect_ai with `make_old_logs.py` (see its docstring): 0.3.2 is the oldest version the
`inspect` extra allows, 0.3.204 is from April 2026. The answer model and the grader are a
fixed fake defined in the script, so nothing calls an API. They check that a log written by an
older inspect_ai is still read when a newer one is installed (`tests/test_import_real.py`).
