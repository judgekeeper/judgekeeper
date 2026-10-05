# With a coding assistant

You can hand the whole job to a coding assistant. It does the typing. You do one thing yourself: the labels.

A coding assistant is a tool that can read your project and run commands in it. There are two ways to tell it about judgekeeper. Pick one.

## Install the skill

A skill is a short instruction file. Your assistant loads it when the job calls for it. This one tells it how to use judgekeeper.

```
npx skills add judgekeeper/judgekeeper
```

No skills tool? Paste the prompt below instead. It tells the assistant the same things.

After the install, ask your assistant: "Check how often my AI judge agrees with human labels."

## Or paste the prompt

Open your assistant in your project folder. Copy all of this text and send it as your message. You do not need to install anything first. The prompt tells the assistant to do that.

```
Please check how often the AI judge in this project agrees with human labels, using judgekeeper.
A judge is a model that grades another model's answers. judgekeeper compares the judge's
verdicts with labels a person gave and says how often the two agree. You do the typing; I do
one thing myself: the labels. I may not write much code, so use plain words with me.

Three rules, each with its reason:
- Never invent, guess or generate a human label, and never let a model fill one in: not as a
  draft, not for the obvious ones, not to save me time. The labels are the only part of this
  check that is not a model's opinion. If a model writes them, the result compares a model with
  a model and proves nothing.
- Keys live in environment variables only (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`). Never write a
  key into a file, a command, a commit or this chat, and never ask me to paste one here: files,
  chats and shell history get shared. If one is missing, ask me to set it myself.
- Judge calls cost money. Tell me the number of judge calls (answers x runs, x 2 when the judge
  compares two answers) before you make any, and wait for my yes.

1. Install it. Run `pip install judgekeeper` (or use this project's own package tool), then
   `judgekeeper --version`, and tell me what it printed.
2. Find the judge: prompts that grade an answer, eval configs (promptfoo, DeepEval, Inspect AI,
   MLflow, Langfuse), code that scores, passes or fails an answer. A plain function that calls
   no model counts too. Tell me what you found. If there is none, say so and offer a rule file
   with `[FILL IN: ...]` parts, from `judgekeeper init --out prompts/judge.md`: ask me what pass
   and fail mean, type my answers in and show me the file. If a judge exists, ask me to say in
   one sentence what pass means before I label: my labels must follow my rule, not the judge's.
3. Collect 30 to 60 real answers from the app (logs, saved eval results or fresh runs), not
   written by you, with ordinary and hard cases and both good and bad answers. Save them as
   `items.jsonl`, one line per answer with `id`, `input` and `output`; renaming the app's own
   field names is fine if the text is copied unchanged. You may read the answers to check they
   are varied, but keep any opinion on which are good out of every file and out of what you tell
   me, so you do not steer my labels. If you cannot find 30, stop and ask me where to find more.
4. Open the labeling page for me: `judgekeeper label items.jsonl --out labels.csv`. It is a
   local page (127.0.0.1); the command keeps running while I label and prints a link that
   includes a token. The page opens only with that full link, and the link changes each time the
   command starts, so ask me to run it in my own terminal, or start it in the background and
   give me the exact link it printed. Keys: 1 pass, 2 fail; the page also has defer, undo and
   note. Stop here and wait until I tell you I am done.
5. Freeze my labels: `judgekeeper import-labels labels.csv -o anchors.jsonl`.
6. Run the judge 3 times: one run cannot show whether it gives the same verdict twice. A judge
   function gets one item as a dict with `id`, `input` and `output` and returns True (pass) or
   False (fail); add a small wrapper file in the project folder if needed:
       judgekeeper judge anchors.jsonl --callable judges:my_judge --runs 3 --out runs/judge/
   A plain function costs nothing, so the count and my yes are only for model calls; still run
   it 3 times, as the report expects. For a rule file from `init`, with the project's model:
       judgekeeper judge anchors.jsonl --runner anthropic --model claude-haiku-4-5-20251001 \
         --prompt prompts/judge.md --runs 3 --out runs/judge/
   Then `judgekeeper validate anchors.jsonl runs/judge/ --out reports/judge/`. If the project
   already saved the judge's verdicts for these answers, put them in one table next to my labels
   and run `judgekeeper check results.csv --judge verdict --human label` instead.
7. Tell me the result: first the plain sentence judgekeeper prints (how often the judge passed
   what people passed, and failed what people failed) and its verdict, then both rates (TPR and
   TNR), kappa and every flag in the report, each in plain words. Never give one "agreement" or
   "accuracy" figure on its own: a judge that passes everything scores high on it and catches
   nothing. Quote the numbers as the report gives them and point me to `report.html`. Under 60
   labels the report flags wide error bars: normal for a first look, so say so.

Stop and ask me whenever a step needs me: the labels, a key, spending money, what the rule
means, or a choice you are not sure about. Do not change my app's code or its CI unless I ask.
`judgekeeper <command> --help` lists every option.
```

The same text is in the file `docs/assistant-prompt.md`.

## What happens next

1. The assistant installs judgekeeper and checks that it runs.
2. It finds how your project grades answers today, and tells you what it found. If your project has no judge yet, it says so and offers to start one with you. If it has one, it asks you to say in one sentence what pass means, so your labels follow your own rule.
3. It collects a sample of 30 to 60 real answers from your app.
4. It starts the labeling page and gives you its link, or asks you to start it in your own terminal. The page runs on your own computer (127.0.0.1). You read each answer and press 1 for pass or 2 for fail.
5. It tells you how many judge calls the check needs, and waits for your yes before it spends anything.
6. It runs the check and tells you the result in plain words: of the answers you passed, how many the judge passed, and of the answers you failed, how many the judge failed.

**You do one thing yourself: the labels.** The assistant must never fill them in for you. The labels are the only part of the check that is not a model's opinion. If a model wrote them, the check would compare one model with another and prove nothing.

The assistant also stops and asks you when it needs a key. A key is the password for a paid AI service. Keep it in an environment variable, which is a setting in your own terminal. Do not paste it into the chat.

## Works with

- Claude Code
- Codex
- Cursor

The prompt uses nothing special to one of them. It needs an assistant that can read your files and run commands in your project.

Chat-only assistants in a browser are out of scope: they cannot run commands in your project.
