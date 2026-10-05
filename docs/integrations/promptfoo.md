# promptfoo

judgekeeper reads the results file promptfoo already writes. Your promptfoo config does not change.

## Produce the file

```
promptfoo eval -o results.json --repeat 3
```

`--repeat 3` judges every test three times, so the report can measure the judge's run-to-run noise. Without it the noise floor is reported as unknown.

## Import it

```
judgekeeper import promptfoo results.json --metric helpfulness --out reports/helpfulness/
```

`--metric` names the judge: an assertion's `metric:` if it has one, otherwise its type (`llm-rubric`, `g-eval`, `factuality`, `model-graded-closedqa`, `model-graded-factuality`, `answer-relevance`, `context-faithfulness`, `context-recall`, `context-relevance`, `conversation-relevance`, `search-rubric`). With only one such judge in the file you can leave it out; with several, judgekeeper lists them. Other assertions (`contains`, `javascript`, ...) are code checks: they are ignored, with a note.

Item ids: `--id-var NAME` reads `vars[NAME]` (best: give every test a stable id var). Otherwise each test's `description` when every test has a unique one. Otherwise a hash of the test's vars (not its output, which can differ between repeats), and the report says the ids were derived. With several prompts, ids get `#prompt<n>`.

## Human labels

Either rate outputs in the promptfoo web UI (`promptfoo view`, thumbs up or down), then export the eval again with `promptfoo export eval <id> -o results.json`: each rating is a component with `assertion.type == "human"`, and judgekeeper reads it as the human label. Or pass a labels table:

```
judgekeeper import promptfoo results.json --metric helpfulness --labels labels.csv --out reports/x/
```

`labels.csv` needs an `id` column (the ids described above) and a `human_label` column (`pass`/`fail`, or any spelling `--label-map` maps). Where both exist, `--labels` wins and the report notes how many labels it replaced.

## Traps

- **A human rating overrides the row's `success` and `pass`.** judgekeeper never reads the judge verdict from them: it reads the model-graded component itself, and the human verdict from the `human` component.
- **`--repeat` rows carry no repeat index.** promptfoo removes `__repeatIndex` before saving and gives every repeat its own `testIdx` (with the same `promptIdx` and identical vars), so `testIdx` does not identify a test. judgekeeper groups rows by item id and `promptIdx` and numbers the repeats in the order they appear in the file, always: the promptfoo reader does `--runs-by-order` by itself. A test's id is the same in every repeat (an id var, its description, or a hash of its vars). If your outputs differ between repeats (no provider cache), each item keeps the output of its first repeat, and the noise floor then includes the variation of your app as well as the judge's.
- **The default grader is not recorded.** With no `provider` on the assertion, the test's `options` or `defaultTest.options`, promptfoo grades with its built-in default model and the results file does not say which. Those judgments get an unknown model and the report flags "default grader model not recorded by promptfoo". Set the grader explicitly:

  ```yaml
  defaultTest:
    options:
      provider:
        id: openai:gpt-4.1-mini
        config:
          temperature: 0
  ```

  The temperature is recorded only when the provider config carries it.
- **The prompt hash** is the assertion's `value` (the rubric) plus `rubricPrompt` when set. A different rubric per test gives a different hash per judgment; the run header then records the prompt as unknown and says so.
- **Several output files** (`-o` from several evals) become separate runs, in the order given.
