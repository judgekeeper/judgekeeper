# Security

## Reporting a problem

Use GitHub's private vulnerability reporting on this repository (Security > Report a
vulnerability). Please do not open a public issue for a security problem. You should hear
back within a week.

## What judgekeeper does with your data and keys

- API keys are read from environment variables (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, the
  variable named with `--api-key-env`, the Langfuse and MLflow credentials). They are never
  written to a file, and any report or error text is scrubbed for them before it is written.
  The Anthropic and OpenAI runners do not follow redirects: a key is sent only to the
  endpoint you name.
- `judgekeeper start` opens its pages (marking answers, the review, fixing your judge, the
  result) from a local web server on 127.0.0.1 with a random token in the URL. It does not
  listen on the network.
- Reports (`report.html`, `migration.html`, `gate.md`) escape the values they show, so a
  hostile model response, item text or model id cannot inject markup. Spreadsheets that
  `judgekeeper start` writes neutralise cells that would run as formulas, the id column
  included.
  Text from input files is printed to the terminal without control characters.
- A plain `http://` base URL to a host other than this machine gets a warning: the key would
  travel unencrypted.
- `judgekeeper` has no runtime dependencies. The optional extras (`anthropic`, `openai`,
  `inspect`, `mlflow`) are the provider and platform SDKs.

- `judgekeeper start` does not write through links. If `.judgekeeper/`, or anything in it,
  is a link (a symlink, which a cloned repository can hold), it stops before writing and says
  which. Every file there is written as a new file that replaces the old one. The first time
  a check starts in it, the folder gets its own `.gitignore`, so your answers stay off Git.

## Things that run your own code, by design

`--callable module:function` imports and calls a Python function you name, and `--exec` runs a
command you give. Both exist so that any judge can be measured. They run with your
permissions, like any script you run yourself, so point them only at code you trust. This is
not a vulnerability.

Asking your judge again runs your project's own Python and eval tool, from the project
folder. Run it only in projects you trust, as you would run their tests. It happens when
you pick "Ask your judge again" or "Try your new judge" (`--ask-again`, `--try-new-judge`),
already while the plan is made, before the "Go ahead?" question: judgekeeper runs the
project's `node_modules/.bin/promptfoo` (or promptfoo on your PATH) to read its version, and
for DeepEval, Inspect AI and MLflow a small script with the project's `.venv` Python (or the
one you name with `--python`). Those tools load the project's `.env` and config as they do
when you run your evals. judgekeeper treats a promptfoo judge that runs code of its own (a
`file://` or `exec:` grader or rubric, a `transform`, or a grader that is a URL) as one it
cannot ask again, and uses a promptfoo version from a results file only when it reads as a
plain version number.
