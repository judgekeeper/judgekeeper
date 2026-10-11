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
