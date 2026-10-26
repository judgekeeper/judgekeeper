# Security

## Reporting a problem

Please report it privately: [Report a vulnerability](https://github.com/judgekeeper/judgekeeper/security/advisories/new) (GitHub's private vulnerability reporting). Do not open a public issue for a security problem. I will reply as soon as I can.

## Your keys

judgekeeper needs no API key of its own: your eval tool reads its keys and makes the calls. judgekeeper never writes a key to a file, and hides keys and anything shaped like one as `[REDACTED]` before it writes or prints text ([which keys](docs/reference.md#your-api-keys)).

## The marking page

- It runs on 127.0.0.1 only, with a random token in its link.
- Every change must also come from the page itself: `Origin: http://127.0.0.1:<port>`, and `Sec-Fetch-Site: same-origin` when the browser sends it. So another website can't send marks. A program on your computer could, the same way it could edit your files.
- It stops after 30 minutes without use.

The details are in the [reference](docs/reference.md#judgekeeper-find-mark-measure).

## What judgekeeper writes

- judgekeeper writes only inside `.judgekeeper/` in your project, plus `judgekeeper.toml` after you say yes, and two temporary files next to your promptfoo config while it asks your LLM-as-a-judge again.
- It never edits other tools' settings: no editor or agent hooks, no git hooks.
- It never writes through links. Results outside your project are read only when you name them.
- Pages and spreadsheets it writes escape every value.

The details are in the [reference](docs/reference.md#the-judgekeeper-folder).

## When it runs your project's code

Asking your LLM-as-a-judge again (`judgekeeper fix` and `judgekeeper check`) runs your own eval tool and Python, so use it only in projects you trust. It asks before any AI call. The DeepEval, Inspect AI and MLflow scripts run from an empty temporary folder, so a `.env` or a key file in your project is not picked up by them. What runs before it asks, which promptfoo graders it will and won't run, and the project settings that make it refuse, are in [eval-tools.md](docs/eval-tools.md#asking-again).

## Other things

- judgekeeper has no runtime dependencies. The two optional extras install Inspect AI and MLflow, nothing else.
- The browser check on the website (`check.html`) reads your file inside the page. Its script sends nothing, and the page's Content-Security-Policy (`connect-src 'none'`) blocks every connection, so the file never leaves your computer. The only thing it loads is an example file from the same site, when you click one.
- judgekeeper 1.0 is made for a person to run in their own terminal and mark in their own browser. Running it through a coding agent isn't supported in 1.0.
