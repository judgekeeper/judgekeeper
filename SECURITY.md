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
- `judgekeeper` and `judgekeeper mark` open the marking page and the result from a local
  web server on 127.0.0.1 with a random token in the URL. It does not listen on the network.
- The pages judgekeeper writes escape the values they show, so a hostile model response,
  item text or model id cannot inject markup. Spreadsheets that judgekeeper writes
  neutralize cells that would run as formulas, the id column included.
  Text from input files is printed to the terminal without control characters.
- The free check on the website (`check.html`) reads the file you give it inside the page:
  its script makes no request, and the page's Content-Security-Policy (`connect-src 'none'`)
  blocks every connection, so the file never leaves your computer.
- `judgekeeper` has no runtime dependencies. The optional extras (`inspect`, `mlflow`)
  are the platform SDKs.

- judgekeeper does not write through links. If `.judgekeeper/`, or anything in it,
  is a link (a symlink, which a cloned repository can hold), it stops before writing and says
  which. Every file there is written as a new file that replaces the old one. The first time
  a check starts in it, the folder gets its own `.gitignore`, so your answers stay off Git.

## What judgekeeper writes

judgekeeper writes only inside `.judgekeeper/` in your project, plus, each only after you say
yes, `judgekeeper.toml` (where your results are and how to read them) and
`promptfoo-results.json` (your last promptfoo run, exported for you). It never edits other
tools' settings: no editor or agent hooks, no git hooks, no `.pre-commit-config.yaml`, no
requirements files. It never runs your judge by itself: `judgekeeper check` says how many AI
calls a re-check needs and asks before it makes them.

## Running judgekeeper through a coding agent

judgekeeper 1.0 is made for a person to run in their own terminal, marking in their own
browser. Running it through a coding agent isn't supported in 1.0. The marks are meant to be
the person's own, so the marking page saves a mark only from a browser on that page: every
request needs the page's random token, and every change also needs to come from the page
itself, its own origin (`Origin: http://127.0.0.1:<port>`, and `Sec-Fetch-Site: same-origin`
when the browser sends it).

## Things that run your own code, by design

Asking your judge again runs your project's own Python and eval tool, from the project
folder. Run it only in projects you trust, as you would run their tests. It happens when
`judgekeeper check` re-checks a changed judge or `judgekeeper fix` tests a new rule, already
while the plan is made, before the "Go ahead?" question: judgekeeper runs the project's
`node_modules/.bin/promptfoo` (or promptfoo on your PATH) to read its version, and for
DeepEval, Inspect AI and MLflow a small script with your Python (the active virtual
environment, else the project's `.venv` or `venv`). Those tools load the project's `.env`
and config as they do when you run your evals. judgekeeper treats a promptfoo judge that
runs code of its own (a `file://` or `exec:` grader or rubric, a `transform`, or a grader
that is a URL) as one it cannot ask again, and uses a promptfoo version from a results file
only when it reads as a plain version number.
