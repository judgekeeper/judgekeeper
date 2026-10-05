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
- `judgekeeper label` runs a local web server on 127.0.0.1 with a random token in the URL. It
  does not listen on the network.
- Reports (`report.html`, `migration.html`, `gate.md`) escape the values they show, so a
  hostile model response, item text or model id cannot inject markup. Spreadsheets written by
  `template` and `label` neutralise cells that would run as formulas, the id column included.
  Text from input files is printed to the terminal without control characters.
- A plain `http://` base URL to a host other than this machine gets a warning: the key would
  travel unencrypted.
- `judgekeeper` has no runtime dependencies. The optional extras (`anthropic`, `openai`,
  `inspect`, `mlflow`) are the provider and platform SDKs.

## Things that run your own code, by design

`--callable module:function` imports and calls a Python function you name, and `--exec` runs a
command you give. Both exist so that any judge can be measured. They run with your
permissions, like any script you run yourself, so point them only at code you trust. This is
not a vulnerability.
