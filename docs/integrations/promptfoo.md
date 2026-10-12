# promptfoo

judgekeeper reads the results file promptfoo already writes. Your promptfoo config does not change.

Tested with promptfoo 0.120 to 0.124.

## Produce the file

```
promptfoo eval -o results.json
```

## Read it

```
judgekeeper start
```

`--metric` names the judge: an assertion's `metric:` if it has one, otherwise its type (`llm-rubric`, `g-eval`, `factuality`, `model-graded-closedqa`, `model-graded-factuality`, `answer-relevance`, `context-faithfulness`, `context-recall`, `context-relevance`, `conversation-relevance`, `search-rubric`). With only one such judge in the file you can leave it out; with several, judgekeeper asks which. Other assertions (`contains`, `javascript`, ...) are code checks: they are ignored, with a note.

Item ids: each test's `description` when every test has a unique one. Otherwise a hash of the test's vars (not its output, which can differ between repeats). With several prompts, ids get `#prompt<n>`.

## Traps

- **A human rating overrides the row's `success` and `pass`.** judgekeeper never reads the judge verdict from them: it reads the model-graded component itself.
- **`--repeat` rows carry no repeat index.** promptfoo removes `__repeatIndex` before saving and gives every repeat its own `testIdx` (with the same `promptIdx` and identical vars), so `testIdx` does not identify a test. judgekeeper groups rows by item id and `promptIdx` and numbers the repeats in the order they appear in the file, always. A test's id is the same in every repeat (an id var, its description, or a hash of its vars). If your outputs differ between repeats (no provider cache), each item keeps the output of its first repeat.
- **The default grader is not recorded.** With no `provider` on the assertion, the test's `options`, `defaultTest.options` or `defaultTest.provider` (the model under test, which promptfoo also uses as the judge when no grader is set), promptfoo grades with its built-in default model and the results file does not say which. Those judgments get an unknown model, and judgekeeper says so. Set the grader explicitly:

  ```yaml
  defaultTest:
    options:
      provider:
        id: openai:gpt-4.1-mini
        config:
          temperature: 0
  ```

  The temperature is recorded only when the provider config carries it.
- **A grader set with `--grader`** is saved without its provider, only its model name. judgekeeper records that model, leaves the provider unknown and says so; it is not the default grader.
- **The prompt hash** is the assertion's `value` (the rubric) plus `rubricPrompt` when set. For llm-rubric, promptfoo also saves the exact text it sent the grader (`renderedGradingPrompt`): with the answer and the test's vars put back as placeholders, that is the grading template, and when it is the same on every row its hash is the prompt hash, so a change in promptfoo's own grading prompt shows too. A different rubric per test gives a different hash per judgment.
- **Cached verdicts.** A verdict promptfoo replayed from its cache (`cachedResponse`) may be an old reply; judgekeeper says how many there are.
