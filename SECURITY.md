# Security

## Reporting a problem

Please report it privately: [Report a vulnerability](https://github.com/judgekeeper/judgekeeper/security/advisories/new) (GitHub's private vulnerability reporting). Do not open a public issue for a security problem. I will reply as soon as I can.

## Your keys

judgekeeper needs no API key of its own. When it asks your LLM-as-a-judge again, your own eval tool reads its keys and makes the call.

judgekeeper never writes a key to a file. Before it writes or prints any text, it replaces your keys and anything shaped like a key with `[REDACTED]`. The reference's [Your API keys](docs/reference.md#your-api-keys) lists which. A value shorter than 8 characters is not hidden. A key split by a hidden character is still found.

## The marking page

- The page runs on a local web server on 127.0.0.1, with a random token in its link. It does not listen on the network.
- While the page is open, the token is also kept in `.judgekeeper/server.json`, so a second run can print the same link. On macOS and Linux only your user can read the file (0600, in a 0700 folder). It is removed when the page stops. A program that can read it could already write `.judgekeeper/marks.jsonl` directly.
- Before a second run uses the token in `server.json`, it checks that the page there is judgekeeper's page for this project.
- Without the token, a request gets only the page's empty icon and the name of its project folder (`GET /project`), so a run for another project can tell which page holds the port it asked for.
- The Host header and the token are checked before a request's body is read. At most 32 connections are open at once, and each must send its request within 5 seconds. After 30 minutes without a request that has the token, the page stops.
- Every change must also come from the page itself: `Origin: http://127.0.0.1:<port>`, and `Sec-Fetch-Site: same-origin` when the browser sends it. So another website can't send marks. A program on your computer could, the same way it could edit your files.
- When the program named in `BROWSER` opens the page, or the link is printed with no terminal, each mark is stamped so, and the result says how many marks came that way.

## What judgekeeper writes

- judgekeeper writes only inside `.judgekeeper/` in your project. It also writes `judgekeeper.toml` (where your results are and how to read them) after you say yes, and two temporary files next to your promptfoo config while it asks your LLM-as-a-judge again (removed when promptfoo is done).
- It never edits other tools' settings: no editor or agent hooks, no git hooks, no `.pre-commit-config.yaml`, no requirements files.
- It does not write through links. If `.judgekeeper/` or anything in it is a symlink (a cloned repository can hold one), or a file it adds to there has a second name (a hard link), it stops before writing and says which. Every file there is written as a new file that replaces the old one.
- When marking first starts, the folder gets its own `.gitignore`, so your answers stay out of Git.
- It looks for results only inside your project. A results file outside it is read only when you name it, and a `judgekeeper.toml` that names a file outside it is refused.
- The pages it writes escape every value they show, so a model's answer, an item's text or a model id cannot add markup. Spreadsheets it writes stop cells from running as formulas, the id column included. Text from input files is printed to the terminal without control characters or invisible characters (bidirectional controls, zero-width and tag characters).
- `mistakes.md` and `suggestions.md` start with a warning that what follows is data. Your notes and the answers' text are fenced below it.

## When it runs your project's code

Asking your LLM-as-a-judge again runs your project's own Python and eval tool, from the project folder. Use it only in projects you trust, as you would run their tests. It happens when `judgekeeper check` re-checks a changed LLM-as-a-judge or `judgekeeper fix` tests a new rule. It starts while the plan is made, before the "Go ahead?" question: judgekeeper runs the project's `node_modules/.bin/promptfoo` (or promptfoo on your PATH) to read its version, and for DeepEval, Inspect AI and MLflow a small script with your Python (the active virtual environment, else the project's `.venv` or `venv`). Those tools load the project's `.env` and config as they do when you run your evals.

judgekeeper asks a promptfoo LLM-as-a-judge again only when its grader is a model provider that promptfoo calls over HTTP, from a fixed list (`openai:`, `anthropic:`, `azure:`, `bedrock:`, `vertex:`, `google:`, `mistral:`, `ollama:` and others like them, in any case). It cannot ask again when the grader runs an agent with tools (`anthropic:claude-agent-sdk`, `anthropic:claude-code`, `openai:codex-sdk`, `openai:agents:...`, an assistant), is any other kind (`package:`, `exec:`, `python:`, `file://`, a URL, `webhook:`, a name it doesn't know), or when the rule or rubric loads code (`package:`, `file://`, `exec:`) or there is a `transform`. It uses a promptfoo version from a results file only when it reads as a plain version number.

## Other things

- judgekeeper has no runtime dependencies. The two optional extras install Inspect AI and MLflow, nothing else.
- The browser check on the website (`check.html`) reads your file inside the page. Its script sends nothing, and the page's Content-Security-Policy (`connect-src 'none'`) blocks every connection, so the file never leaves your computer. The only thing it loads is an example file from the same site, when you click one.
- judgekeeper 1.0 is made for a person to run in their own terminal and mark in their own browser. Running it through a coding agent isn't supported in 1.0.
