# Security

## Reporting a problem

Please report it privately: [Report a vulnerability](https://github.com/judgekeeper/judgekeeper/security/advisories/new) (GitHub's private vulnerability reporting). Do not open a public issue for a security problem. I will reply as soon as I can.

## Your keys

judgekeeper needs no API key and makes no AI call. When you grade answers again, your own eval tool reads its keys and makes the calls. judgekeeper never writes a key to a file, and hides keys and anything shaped like one as `[REDACTED]` before it writes or prints text ([which keys](docs/reference.md#your-api-keys)).

It hides:

- the values of key variables (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, and any name ending in `_API_KEY`, `_TOKEN` or `_SECRET`) in your shell, in your project's `.env` files and in promptfoo's config `env:` block (not in one that is a link or over 1 MB: judgekeeper doesn't read that file, and says so);
- keys by their shape: `sk-ant-…`, `sk-…`, `AKIA…`, `ASIA…`, AWS secrets next to their name or key, `ghp_…`, `gho_…`, `ghs_…`, `ghu_…`, `github_pat_…`, `AIza…`, `xoxb-…`, `xoxp-…`, `gsk_…`, `hf_…`, `xai-…` and a JWT;
- `Bearer …` and `Basic …` headers, and the login part of a URL: `https://user:password@`, `https://:password@`, or a long token alone;
- a key split by a hidden character such as a zero-width joiner.

## The marking page

- It runs on 127.0.0.1 only, with a random token in its link.
- Every change must also come from the page itself: `Origin: http://127.0.0.1:<port>`, and `Sec-Fetch-Site: same-origin` when the browser sends it. So marks from another website are refused. A program on your computer could, the same way it could edit your files.
- It stops after 30 minutes without use.

The details are in the [reference](docs/reference.md#judgekeeper-find-mark-measure).

## What judgekeeper writes

- In your project, judgekeeper writes only inside `.judgekeeper/`, plus `judgekeeper.toml` after you say yes.
- Outside your project it writes only a copy of an `mlflow.db` it reads (with its `-wal` and `-shm` files) in your temporary folder (`judgekeeper-mlflow-*`), removed when judgekeeper ends. MLflow makes `mlruns/.trash` when it opens a folder store without one: judgekeeper removes `mlruns/.trash` again.
- It never edits other tools' settings: no editor or agent hooks, no git hooks.
- It never writes through links. Results outside your project are read only when you name them.
- Pages and spreadsheets it writes escape every value.

The details are in the [reference](docs/reference.md#the-judgekeeper-folder).

## It only reads files

judgekeeper never runs your eval tool or your project's code, and the only program it starts is its own marking page. It makes no AI call and costs nothing. To test a new rule (`judgekeeper fix`) or re-check your LLM-as-a-judge (`judgekeeper check`), you grade the answers again with your own eval tool, and judgekeeper reads the results.

## Other things

- judgekeeper has no runtime dependencies. The two optional extras install Inspect AI and MLflow, nothing else.
- The browser check on the website (`check.html`) reads your file inside the page. Its script sends nothing, and the page's Content-Security-Policy (`connect-src 'none'`) blocks every connection, so the file never leaves your computer. The only thing it loads is an example file from the same site, when you click one.
- judgekeeper 1.0 is made for a person to run in their own terminal and mark in their own browser. Running it through a coding agent isn't supported in 1.0.
