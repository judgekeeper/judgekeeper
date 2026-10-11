# With a coding assistant

You can hand the whole job to a coding assistant. It does the typing. You do one thing yourself: you mark the answers Pass or Fail.

A coding assistant is a tool that can read your project and run commands in it. There are two ways to tell it about judgekeeper. Pick one.

## Install the skill

A skill is a short instruction file. Your assistant loads it when the job calls for it. This one tells it how to use judgekeeper.

```
npx skills add judgekeeper/judgekeeper
```

No skills tool? Paste the prompt below instead. It tells the assistant the same things.

After the install, ask your assistant: "Check how often my LLM-as-a-judge agrees with me."

## Or paste the prompt

Open your assistant in your project folder. Copy all of this text and send it as your message. You do not need to install anything first. The prompt tells the assistant to do that.

```
Please check how often the LLM-as-a-judge in this project agrees with my own labels, using
judgekeeper. A judge is a model that grades another model's answers. judgekeeper reads
the verdicts the judge already saved, shows me some of the same answers to label, and
says how often the judge agrees with me. You do the typing; I do one thing myself: the
labels. I may not write much code, so use plain words with me.

Three rules, each with its reason:
- Never invent, guess or generate a human label, and never let a model fill one in: not
  as a draft, not for the obvious ones, not to save me time. The labels are the only
  part of this check that is not a model's opinion. If a model writes them, the result
  compares a model with a model and proves nothing.
- Keys live in environment variables only (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`). Never
  write a key into a file, a command, a commit or this chat, and never ask me to paste
  one here: files, chats and shell history get shared. If one is missing, ask me to set
  it myself.
- Judge calls cost money. Labeling and the result make none. Before any call,
  judgekeeper's plan shows the number of judge calls and a cost range, and it asks
  `Go ahead? [y/N]`: show me the plan and wait for my yes. I answer that question
  myself; never pass `--allow-calls`.

1. Install it inside this project's own Python environment, never for the whole
   computer: with the project's virtual environment active, run
   `pip install judgekeeper` (or `uv add --dev judgekeeper`, or
   `poetry add --group dev judgekeeper`). Then run `judgekeeper --version` and tell me
   what it printed.
2. Run `judgekeeper start` and tell me what it found: the eval tool, the judge and how
   many answers it graded. Here it does not ask; it stops and prints the flag that
   answers its question. If it found several tools or judges, ask me which one. If it
   finds no results it can read, run `judgekeeper setup` and show me its questions
   instead of answering them for me; it asks once before it changes any file. If the
   judge is code that saves nothing,
   www.judgekeeper.com/assistant.html#add-the-record-line has a prompt that adds one
   line: show me the diff and wait for my yes. If there is no judge at all, say so and
   stop.
3. Ask me to say in one sentence what pass means before I label: my labels must follow
   my rule, not the judge's.
4. Open the labeling page for me: `judgekeeper start --yes --no-browser`. It is a local
   page (127.0.0.1); the command keeps running while I label and prints a link that
   includes a token. The page opens only with that full link, and the link changes each
   time the command starts, so ask me to run `judgekeeper start` in my own terminal, or
   start it in the background and give me the exact link it printed. Keys: ← Fail, →
   Pass, S skip, U undo. Stop here and wait until I tell you I am done.
5. Tell me the result: first the two plain sentences judgekeeper prints ("When you said
   Pass, your judge also said Pass 83% of the time.", and the same for Fail) and its one
   coloured line, then TPR, TNR and kappa with their ranges, and every
   flag, each in plain words. Never give one "agreement" or "accuracy" figure on its
   own: a judge that passes everything scores high on it and catches nothing. Point me
   to `.judgekeeper/result.html`.
6. Then tell me what I can do next, and let me choose: review the disagreements with me
   (`judgekeeper start --review`, free, and I do the marking), ask the judge again
   (`judgekeeper start --ask-again`) or try a changed judge
   (`judgekeeper start --try-new-judge`). Those two make judge calls, so rule 3 applies.

Stop and ask me whenever a step needs me: the labels, a key, spending money, what the
rule means, or a choice you are not sure about. Do not change my app's code or its CI
unless I say yes to the diff. `judgekeeper <command> --help` lists every option.

Advanced, only if I ask: the older commands (judge, validate, check) build the same
check by hand when nothing was saved; www.judgekeeper.com/tutorial.html shows each one.
```

The same text is in the file `docs/assistant-prompt.md`.

## What happens next

1. The assistant installs judgekeeper in your project's environment and checks that it runs.
2. It runs `judgekeeper start` and tells you what it found: your eval tool, your judge and how many answers it graded. If judgekeeper finds nothing it can read, the assistant runs `judgekeeper setup` and shows you its questions to answer. If your project has no judge yet, it says so and stops.
3. It asks you to say in one sentence what pass means, so your marks follow your own rule.
4. It starts the marking page and gives you its link, or asks you to run `judgekeeper start` in your own terminal. The page runs on your own computer (127.0.0.1). You read each answer and press ← for Fail or → for Pass.
5. It tells you the result in plain words: when you said Pass, how often your judge also said Pass; when you said Fail, how often it also said Fail.
6. It tells you what you can do next: see where you and your judge disagree, fix your judge's rule, or try a changed judge. Asking the judge costs money, so judgekeeper shows the number of calls and a cost range first, and you answer its question yourself.

**You do one thing yourself: the marks.** The assistant must never fill them in for you. Your marks are the only part of the check that is not a model's opinion. If a model wrote them, the check would compare one model with another and prove nothing.

The assistant also stops and asks you when it needs a key. A key is the password for a paid AI service. Keep it in an environment variable, which is a setting in your own terminal. Do not paste it into the chat.

## Add the record() line

Your judge runs in your own code and saves nothing judgekeeper reads? One `judgekeeper.record()` line, right where the judge gives each verdict, saves it ([what the line takes](reference.md#record-save-your-own-judges-verdicts-with-one-line)). judgekeeper never edits your code. Paste this prompt into your assistant and it adds the line for you:

```
In this project, my LLM judge runs in my own code. Please add the judgekeeper.record() line,
so that judgekeeper can check my judge against my own labels:

1. judgekeeper must be installed in this project's own Python environment, as a dev tool. If
   it is missing, install it there: for example `uv add --dev judgekeeper`, `poetry add
   --group dev judgekeeper`, or `pip install judgekeeper` with the project's virtual
   environment active.
2. Find where this project's LLM judge produces each score or verdict.
3. Right after it, add one call, with the values the judge just used and gave:

       import judgekeeper
       judgekeeper.record(input=..., output=..., score=..., pass_mark=..., reason=...,
                          judge="<the judge's model>", rule=<the judge's rule or criteria>,
                          name="<the judge's or criterion's name>")

   When the judge gives pass or fail, pass verdict=... instead of score and pass_mark. One
   call per judge or criterion. Only in the eval code, never in code that serves real users
   (it saves inputs and outputs to a file); JUDGEKEEPER_RECORD=0 turns it off.
4. Touch nothing else. record() catches its own errors and returns nothing, so it can never
   change what the program does; do not wrap it in code that could.
5. Show me the diff and wait for my yes before saving.
6. Then run the eval once, run `judgekeeper import records .judgekeeper/records --check`, and
   show me what it prints.
```

## Works with

- Claude Code
- Codex
- Cursor

The prompt uses nothing special to one of them. It needs an assistant that can read your files and run commands in your project.

Chat-only assistants in a browser are out of scope: they cannot run commands in your project.
