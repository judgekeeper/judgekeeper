# Security

## Reporting a problem

Use GitHub's private vulnerability reporting on this repository (Security > Report a
vulnerability). Please do not open a public issue for a security problem. You should hear
back within a week.

## What judgekeeper does with your data and keys

- judgekeeper needs no API key: your own eval tool reads its keys. Any key it can see in an
  environment variable (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, any name ending in `_API_KEY`,
  the Langfuse and MLflow credentials) is never written to a file, and any page or error text
  is scrubbed for it before it is written.
- `judgekeeper start` opens its pages (marking answers, the review, fixing your judge, the
  result) from a local web server on 127.0.0.1 with a random token in the URL. It does not
  listen on the network.
- The pages `judgekeeper start` writes escape the values they show, so a hostile model
  response, item text or model id cannot inject markup. Spreadsheets that
  `judgekeeper start` writes neutralize cells that would run as formulas, the id column
  included.
  Text from input files is printed to the terminal without control characters.
- `judgekeeper` has no runtime dependencies. The optional extras (`inspect`, `mlflow`)
  are the platform SDKs.

- `judgekeeper start` does not write through links. If `.judgekeeper/`, or anything in it,
  is a link (a symlink, which a cloned repository can hold), it stops before writing and says
  which. Every file there is written as a new file that replaces the old one. The first time
  a check starts in it, the folder gets its own `.gitignore`, so your answers stay off Git.

## Turning on automatic checks

Only the person's click on the "Turn on" page is meant to turn on automatic checks, but
judgekeeper cannot prove a person clicked: anything that can write files in your project, a
coding agent included, can write `.judgekeeper/checks.json` by hand. judgekeeper then still
re-checks your judge, and its status says "turned on by a file edit, not on the page". A judge
that can change files runs by itself only after the click on the page, which the page records
in `.judgekeeper/page.log`. Whatever `checks.json` lists, `judgekeeper check --off` changes
only the files turning on writes (`.claude/settings.local.json`, `.cursor/hooks.json`, the git
pre-commit hook, the dev requirements), never through a link.

## Things that run your own code, by design

`judgekeeper start --judge-command` runs a command you give, so that any judge can be
measured. It runs with your permissions, like any script you run yourself, so point it only at code you trust. This is
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
