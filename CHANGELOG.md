# Changelog

## 1.2.0 (2026-11-13)

- No LLM-as-a-judge? judgekeeper now reads a CSV, TSV or JSONL file with `input` and `output` columns and no grades, and you mark your AI's answers Pass or Fail. From 10 marks it shows how many passed, with a range.
- The answers you fail that are not kept aside are saved in `.judgekeeper/fix/failed-answers.md` with your reasons, and judgekeeper prints a prompt for your coding agent to improve your AI's prompt. Half of the questions you marked Pass and half of those you marked Fail are kept aside, at random, to test the change.
- After you change your AI and mark its new answers, judgekeeper counts how many were fixed, how many broke and how many stayed the same on the questions kept aside. It says whether the change helped, made it worse, or can't tell yet, and when it can't tell, how many more questions a clear answer needs.
- No answers yet? judgekeeper prints a prompt for your coding agent to write about 40 test questions and save your AI's answers.
- Each run first says what it checks, your LLM-as-a-judge or your AI's answers, and why: whether your results file has LLM-as-a-judge grades. It also says how to switch.
- Find's list of what judgekeeper reads, and `--help`, now say input and output, with a verdict column if an LLM-as-a-judge graded them.
- On the result page, a long reason is shown in full when its row is open. Your own reason buttons are cut to 2 lines, with the full text on hover.
- Text in answers can no longer fake the markers that fence answers off in files written for a coding agent; this also covers mistakes.md.
- The `inspect` extra keeps agent-client-protocol below 1, because Inspect AI 0.3.288 can't import with 1.0.0.
- Quick Pass and Fail clicks count now: only a click in the first quarter second after an answer shows does nothing, so no answer is marked before you see it.
- The "Your result is ready." box no longer blocks the card: a Pass or Fail click marks the answer and closes it.
- Percentages round half up (23 of 40 is 58%).
- A folder you name (`judgekeeper PATH`, `mark PATH`), or a folder with code in it, is always the project: judgekeeper no longer reads results in the folder above it instead. Lines saved with `judgekeeper.record()` still come from the project root, where it saves them. A folder with a `requirements*.txt` file is a project of its own, so a run in the folder above no longer reads its results. `judgekeeper.record()` also takes a folder with `package.json` as the project root, so in a repository with such subfolders it saves in that subfolder's `.judgekeeper/`, not at the repository root.
- Run from the top of a repository, judgekeeper now also names the projects below whose answers have no grades. After reading results of its own there, it no longer says those results belong to a project below.
- Run from a folder above projects of their own, judgekeeper no longer mixes their results into one: it reads only the results that are in no project below, names the projects that hold the rest, and stops when every result is in one.
- With your own CSV, TSV or JSONL file, `fix/marked-answers.csv` now uses your file's column names (such as `input` and `output`), not `question` and `answer`, so your grader runs on it as it is.
- A marked answer that comes back to check your marks now says so on its card.
- On the result page, the kept-aside lines now say what they count: answers you failed, or questions that failed before your change.
- A metric, tool or experiment you pick when judgekeeper asks is now kept in the commands it prints, and judgekeeper no longer asks for it again or stops after a later question.
- Run from the top of a repository or from a folder above several evals, judgekeeper no longer reads files inside a project below that has its own `.judgekeeper/` or project file, and no longer mixes results from two folders that share no questions into one count: it names them and stops. This also holds in a folder with its own results or a tool's config (such as `promptfooconfig.yaml`) and with `--tool`. A file you name inside such a project is checked there, and projects two levels down are named too. A project below's files never change how the folder above it is read: a folder whose only results are in a project below reads the project above it (or its own file in a format of its own), as it would with no project below, and names that project.
- After reading the project folder above, the commands judgekeeper prints name that folder (`judgekeeper .. --tool deepeval`), so they work where you are. `--tool table` with no table found says "No CSV, TSV or JSONL results file found".
- A folder with answers and no grades reads them even when a project below has results; that project is named, never read.
- From an empty subfolder, judgekeeper no longer reads past the nearest project above.
- A newer unrelated file in a subfolder no longer replaces the answers you marked: judgekeeper says it looks like another eval, as it does for one beside your results.
- A project below with its own `.judgekeeper/` is named even when its results file is a link.
- After `--stop`, the command it prints to carry on repeats the file you named. After "No saved ... results found", the Next line says what to run instead of repeating the same command.
- After 3 changes, the result no longer asks for more of the questions kept aside: it says to add new questions.
- With answers and no grades, `judgekeeper fix` names your results file in its Next line, as the result page does.
- A damaged `.judgekeeper/fix/split-answers.json` is said and started again: the questions kept aside before no longer count as a fair test, and your failed answers stay listed.
- A CSV, TSV or JSONL file of answers under other column names, such as `question` and `answer`, with no grades: judgekeeper names its columns and says to rename them `input` and `output`, instead of asking for grades or printing the prompt that writes answers. With grades, the line on how to switch names the file's own grade column.
- `--tool table` with no results now says "your CSV, TSV or JSONL results file".
- A tool's output folder (Inspect logs, DeepEval results) is never a project of its own: `judgekeeper logs` keeps your marks in the project that holds it, so clearing old logs no longer deletes them. Your session's results file is always read, however many other files the project has, and judgekeeper says when it stopped looking. From a code folder in a project with marks, every command points to the project above. A run inside `.judgekeeper/` never reads its files. `Logs/` is found once on a disk that ignores case.

## 1.1.2 (2026-11-08)

- New result page layout: three big numbers first, then the answers you disagreed on, then what to do next. Pass and Fail are in colour, with fewer small notes.
- The "Your result is ready." box on the marking page now shows only See your result and Keep marking.
- The Measure result in the terminal now shows kappa, as the result page does. It never decides the result.
- Counts of one read right, as in "You have marked the one answer."
- On the marking page, skipped answers now say "Go back to it" or "Go back to them".
- Lines that used "judge" as a verb now say "grade".
- The labels error says numbers can be 1 and 0, and names the numbers it found: "Labels must be Pass or Fail, or 1 and 0, not other numbers: 2." It now has a Next line, with `--label-map`.
- `regrade.yaml` is no longer written for a coding agent as the grader, such as Codex or Claude Code. `fix` prints the steps instead.
- A key or other secret right after a terminal colour code, or with one inside it, is now hidden.
- More secrets are hidden as tools write them: in JSON and `repr` text, after `-` or `_`, in `cat -A` output, AWS secrets under their other names, a URL password with `@` in it, and short `Basic` logins.
- A key near the end of a long line, such as an LLM-as-a-judge's rule, is now hidden before the line is cut short.
- A password in a URL that judgekeeper can't find is now hidden in the "There is no file named" line.
- `fix` no longer says grades are "the same as when you marked" when they are not.
- Labels in your results are now called "labels" until judgekeeper has read them, not "Pass/Fail labels".
- With an LLM-as-a-judge that gave every answer one grade, and every answer marked the same, judgekeeper now says a new answer marked the other way gives the result.
- The marking page no longer counts marks by the LLM-as-a-judge's grade, which showed the hidden grade of the answer just marked. It now says "Keep marking. Your result needs more answers."
- `check` now counts a repeated answer with a different grade the way Measure does.
- With your own CSV, TSV or JSONL file, `fix` and `check` now read `marked-answers.csv` back as it is, with a `verdict` column added. A file judgekeeper can't read now has its columns named in the error.
- After `--labels`, the Next lines keep a `--label-map` saved by an earlier run, and keep `--labels`.
- An MLflow experiment whose name looks like a secret stays hidden, and `fix` and `check` now find it.
- The result page says the same as the terminal when every answer is marked and the LLM-as-a-judge gave one grade: a new answer marked the other way gives the result.
- With every answer marked, Measure's Next line says to run your eval on more questions, as `fix` does.
- "Too early to tell" no longer asks to narrow the ranges when no number has a range.
- Answers that `--labels` marks in the same run are no longer called answers "you haven't seen".
- For an Inspect AI scorer of your own, `fix` names that scorer where the rule goes, not `model_graded_qa(...)`.
- `fix`'s long-answers clue says "usually" for the middle length, and names the answers it compares with.
- A field named after a key, such as a promptfoo var, is now hidden on the marking page and in the files judgekeeper writes.
- The README lists the `verdict` values that work.
- With 2 or more results files in the project folder, every plain run names the one it reads: "Reading results-v2.csv, the newest results here."

## 1.1.1 (2026-11-05)

- Run judgekeeper in a folder below your marks and it uses those marks, with no new empty session. A project already stuck this way recovers by itself.
- With a second results file of other questions, judgekeeper says to put it in its own folder and run judgekeeper there. The refusal has a Next line.
- A missing marks file means no marks, and the page opens. A page that stops by itself is no longer called a busy port: judgekeeper says what happened and points at `page.log`.
- When your marks file holds fewer marks than your last result, judgekeeper says how many of each.
- An LLM-as-a-judge that gave every answer one grade is no longer told it needs 30 answers. The page opens, and the result comes at the first mark the other way.
- "Too early to tell" now says the numbers are your best estimate so far, and that more marks narrow the ranges.
- `check --help` says `--pass-if` replaces the pass mark in use.
- `judgekeeper fix` now gives promptfoo your answers and questions as plain text, whatever characters they hold.
- `regrade.yaml` now carries only plain model graders, settings and rule variables. For anything else, `fix` writes no file and prints the steps.
- On Windows, judgekeeper no longer starts a Python found in the current folder.
- Text that looks like a key is now scrubbed from ids and file names before they are saved.
- The package is built with hatchling 1.33.0.

## 1.1.0 (2026-11-03)

- Bring labels you already have: `judgekeeper --labels <file>` or, for labels already in your results, `judgekeeper --labels`. Mark more on the page if needed.
- The result page links back to the marking page, and says how to mark more after closing it (`judgekeeper mark`).
- "Good enough" and "needs work" now need stronger evidence, so a lucky streak can't decide them. The first numbers wait for 20 marks on answers your LLM-as-a-judge passed and 20 on answers it failed (or all of them, if there are fewer).
- After your first 10 marks, about 1 in 20 marked answers comes back once, so you can see how often your own marks change.
- `fix` and `check` count each mark for its share of your answers, so "Safe to try" is said by mistake less often.
- When you mark every answer, the numbers show no range.
- With every answer marked, the result table has no "Between" column, and nothing asks you to mark more.
- Two range ends that look the same get a second decimal. A number or a range end shows as 100% or 0% only when it is 100% or 0%.
- Opening the result page before there is a result writes nothing. Its "What next" says the same as the terminal.
- "Its reason" shows only when some answers have a reason, and a saved reason closes its box. The marking page's status always agrees with the result page.
- A mark can always be changed. When every answer is marked, the result page links to the marking page.
- When the only answers left to mark are ones you skipped, judgekeeper says to mark those or run your eval on more questions.
- With too few answers left for a result, a plain run and `mark` exit 3, as `fix` and `check` do.
- A labels file is read row by row, with no row cap. An open marking page sees imported marks and skips those answers.
- An import that adds nothing says why. `--label-map WORD=error` skips rows with no decision.
- Labels match answers whose accents are written the other way. A label written `1.0` or `0.0` reads as 1 or 0.
- Scores edited in Inspect AI are not used. Inspect keeps a label only when a person changes a score, so they would be mostly disagreements.
- A labels file takes the same answer column names as a results file (`response`, ...). One with two label columns, both `output` and `answer`, or both `input` and `question` stops and asks you to keep one.
- A CSV whose notes have line breaks is read, not refused.
- A row with more cells than the header stops and names the line. A model column is read the same way in CSV and JSONL files.
- After `check`, labels for answers your LLM-as-a-judge didn't grade Pass or Fail are sorted as before. `--new --labels FILE` keeps `--labels FILE` in the commands it prints.
- What judgekeeper prints names a path from where you run it, or as `~/...`. On Windows, a command that can't run any other way gives the whole path.
- Lines that name a found file use the same form. A path is never split across two lines.
- No line shows a user name. A folder inside another user's home is shortened (`/…/project/`).
- File names in a terminal are plain text, no longer links. A link hid the whole path, user name included.
- Files in `.judgekeeper/` name paths from the project folder or as `~/...`, never with your user name. Older files still read.
- From `/`, a drive, or the folder above your home, judgekeeper no longer searches the folders below. It asks you to go to your project folder.
- Find skips devices, pipes and folders it can't open.
- Next lines name a command that runs as shown, also when `judgekeeper` is not on the PATH (`venv/bin/judgekeeper`, or `python3 -P -m judgekeeper`). They run on Windows in both cmd and PowerShell.
- Commands name plain `judgekeeper` only when that is the same program you ran. With another judgekeeper on the PATH, they name yours.
- A line that says to run a command in your project folder, or sends you to another folder, names the program and the folder as they are from there.
- On a project with scores, every printed command keeps the pass mark in use once there is a result, also after `--stop`.
- report.html and the files in `.judgekeeper/` name the program plainly, and report.html says when you started judgekeeper another way. Stop lines name the program as you started it.
- A folder with a project file (pyproject.toml, package.json, .git, ...) keeps its own marks and never reads the project above it. New results in a folder of their own get their own `.judgekeeper/`.
- A project folder given from another folder is read as the project. Results of the same eval, in the same folder as the marked results, use those marks from whichever folder you run judgekeeper.
- Another eval in that folder is never read or marked. judgekeeper says so and keeps reading the marked file, and `check FILE`, `mark FILE` and `fix FILE` on it exit 3.
- `--stop` also closes a page opened from the folder right below.
- On the marking page, a key pressed the moment a new answer shows, or as the welcome box closes, marks nothing. The welcome box shows while the project has no answer marked or skipped yet, on any port and in any browser.
- Long file names and commands wrap on the marking page. When most marks took under a second, the pages say so.
- A mark the page can't save says how to open it again. There is no welcome box once every answer is marked.
- For your own results file, the page names your LLM-as-a-judge the way the terminal does. Z after changing a mark puts back the earlier mark.
- The marking page's footer names the project folder. A page left open closes when `check` switches to a new LLM-as-a-judge.
- If `.judgekeeper/marks.jsonl` ends in a cut line, the next mark goes on a line of its own and is kept.
- An LLM-as-a-judge that gave every answer one grade gets its result at the first mark the other way.
- `fix` says which marks it used and how many are kept aside. It says to keep the old rule when the marks can't settle it, and names only the new results file in its next step.
- "Tell judgekeeper why you disagree" counts only disagreements with no reason yet. `fix` never asks for more marks than there are answers left.
- `fix` never suggests a pass mark that `check` would call worse, or one a check already found worse. `fix --port` or `--no-browser` says `fix` opens no page.
- mistakes.md names a typed reason by its words, keeps the rule you marked with, and calls a word common only when it is.
- A file graded with the same rule and model as one tested before gets that result. `fix` says on how many answers kept aside its grades differ.
- With Inspect AI, the command to grade your log again is one command. The lines on grading again link the eval tools page on GitHub.
- promptfoo's regrade.yaml keeps the grader's settings (temperature, max_tokens, ...), but never a field that may hold a key. It holds each answer word for word as marked.
- After "Safe to try" with promptfoo, `fix` says to copy the new rule from `.judgekeeper/fix/regrade.yaml` into your promptfoo config.
- When the numbers include marks you looked at to write the new rule, the result page, report.html and the terminal say so under the verdict.
- `check --pass-if RULE` re-checks the pass mark `fix` suggests on your marks. Once `check` switches to it, later `check` and `fix` runs read with it, and `mark` and a plain `judgekeeper` ask for the pass mark again with it as the default.
- A `mark` run on an older results file names the file your last check read in every command it prints.
- The `check` verdict starts "Compared with before:" and names the side that got worse. The worst end of a drop range is rounded up.
- When `check` changes your result, it says the new one, and if that is too early to tell, says to mark more. Its next step names a new results file, never the same one again.
- For a file with only some of your marked answers, `check` says to grade every marked answer again. "Your eval wrote new answers" is said only when it did.
- With results in two folders, `check` names a command for each. A missing file is named with its folder.
- After a Worse or Not sure check, or a check of a results file outside your project, the next runs name the right LLM-as-a-judge and the right next step.
- A plain `check` reads the file your last check read, as a plain `judgekeeper` does, unless your eval wrote newer results. A file outside your home folder is kept by its whole path for this, one in another person's home folder by its name only, and `check` says so.
- After `check` switches to a new LLM-as-a-judge that graded only some of your answers, marks on the other answers wait. They are kept, never counted with an older grade, and counted once `check` brings the new grades, each with its own reason, score and fingerprint.
- The terminal and every page say how many marks wait and what to do. Nothing asks you to mark answers whose marks could only wait.
- `check` on results graded again with the same model and rule compares them when grades on your marked answers changed, and says that your LLM-as-a-judge doesn't always grade the same answer the same way.
- A plain `judgekeeper` that reads a newer results file than last time says which one. "Your answers were graded again" is said once for new results, and never when the same results are read again.
- Some newer results count only once `check` switches to their grades. For these, with any eval tool, judgekeeper says whose grades the numbers still use and names the `check` that compares them (after a check found them worse, that check instead).
- A new `--pass-if` or LLM-as-a-judge given before any mark reads the results again at once. Without a terminal to ask in, the pass mark question names the pass mark in use.
- history.jsonl keeps each result's verdict.
- Ctrl-C always stops with exit code 130 and no Python traceback, also while judgekeeper starts or an Inspect AI log is read. It prints "Stopped." and a Next: line, unless the run had already printed its Next: line.
- An Inspect AI `.eval` log whose header lists no sample ids (one written with inspect_ai's `write_eval_log`) is read. judgekeeper reads the samples it holds.
- Large runs are faster. Marks and answers are read once per run.
- `record()`, `jk_record.py` and `jk_record.ts` name their records `LLM-as-a-judge` by default. Older records still read.
- The README and the start page now cover the MLflow and Inspect AI extras and `--no-browser` for coding agents.
- The reference says what 1.1.0 changed: marks that wait, starting from `/`, labels file rules, the promptfoo re-grade file, and `check --pass-if`.

## 1.0.2 (2026-10-31)
- The marking page's progress bar follows how close your result is, and a "Your result is ready" box tells you when it is.
- The result page says what is saved and what to do next.
- The result page explains why you can add a reason when you disagree, and what is hidden on purpose.
- The two main lines, "When you say Pass" and "When you say Fail", are shown open.
- Bold text and bullet lists in answers show on the marking page and in report.html (not yet in the live result page's rows with a reason box).
- `judgekeeper fix` writes a ready re-grade file for promptfoo (`.judgekeeper/fix/regrade.yaml`) and says the three steps to use it.
- Re-check says to grade your marked answers again, and when your eval wrote new answers it points you to the same steps.
- Re-check says "Better" when a group agrees with you clearly more.
- `judgekeeper fix` shows how the old and new rule agree with you on Pass and on Fail.
- The terminal says "Opening the marking page in your browser…" before it opens it.
- A printed link you asked for gets a softer note.

## 1.0.1 (2026-10-31)
- ™ on the judgekeeper name and logo in the README, on the website and on the marking and report pages, with the trademark notice at the end of the README. The README title's ™ is shown small.
- The example model names are neutral (`my-judge-v1`, `my-judge-v2`), and the example with two LLM-as-a-judge setups on JailbreakBench is now in `docs/examples/jailbreakbench-setups/`.
- The demo is recorded again, with the new frame and the ™.
- Wording fixes in the docs and the examples, and a line for people who use a coding agent, in the README and the Guide.
- No change to what judgekeeper does.

## 1.0.0 (2026-10-30)

The 5 steps: Find. Mark. Measure. Fix. Re-check. In your project folder, in its virtual environment, run `pip install judgekeeper`, then `judgekeeper`; or run `uvx judgekeeper`, which needs no virtual environment.

- `judgekeeper` finds your eval results and their LLM-as-a-judge: promptfoo, DeepEval, Inspect AI, MLflow, a CSV, TSV or JSONL file, or `judgekeeper.record()`.
- You mark answers Pass or Fail in your browser, with the grade hidden. The page accepts marks only from itself, so other websites can't send marks. A program already running on your computer could, just as it can edit your files.
- Then see how often your LLM-as-a-judge agrees with you: TPR and TNR with ranges, and kappa.
- `judgekeeper mark` marks more answers.
- `judgekeeper fix` shows where your LLM-as-a-judge goes wrong and keeps half your marks aside. Grade the marked answers again with your new rule in your eval tool, then `judgekeeper fix <new results file>` tests it on the marks kept aside.
- `judgekeeper check` re-checks it on your marks, from your new results, when something changes: its model, rule, grading prompt, pass mark or temperature, your eval tool's version, and more (the reference lists them all).
- `fix` and `check` find the answers you marked by their text and question. An answer kept aside that a new rule leaves ungraded counts as its mistake.
- judgekeeper only reads files. It never runs your eval tool, makes no AI call and needs no API key.
- It hides keys in what it prints and writes: the key variables in your shell, your project's `.env` and `.env.*` files and promptfoo's `env:` block, and anything shaped like a key.
- Very large Inspect AI logs and MLflow stores are refused with the limit named; the reference lists the limits.
- Reading results: a results file with a `score` column and no verdict column is read with `--pass-if`, or judgekeeper asks for a pass mark (exit 3), and the website's browser check says the same. A promptfoo assertion's `threshold` is its pass mark. In a file of your own format, the model field inside the judge object (`judge.grader`, ...) is offered as the model and written into every judgment's fingerprint, and a `response_time` column is not a second answer. A folder with results in two or more folders below it stops (exit 3) and names them. Long files no longer take time that grows with the square of their size. A CSV or TSV file with scores reads answers that run over many lines, and a quote that never closes, or closes only on a later row, stops with its line named, in the tool and the browser check. In the browser check, plain 1 and 0 scores count no Pass or Fail until a pass mark is given.
- `fix` and `check`: a `fix/split.json` changed by hand stops `fix` (exit 2, Next: `fix --new`). `check` on the results your marks were made from says "back to the one you marked with" every time, not "Worse" from the second run on. A DeepEval GEval's rule leaves out the steps its model wrote for each answer, so a plain re-run no longer says "rule changed". A model given later with `--judge-model` is written into the marks and the history too, and a new results file with its own model column is read (`check` names a model change). "Worse" next to a group that rose says which group dropped. With a wrong MLflow scorer name, `fix` and `check` give the same next step. The README, the reference and SECURITY.md say what the code does.
- Marking page and exits: `--wait` keeps the page open until Ctrl-C (exit 130) and leaves no lock; a second run opens no new tab and says the page is already running; a plain run reuses the `--label-map` kept with your marks; keys pressed while a mark is saved act once it is saved; a save with no answer after 10 seconds says it wasn't saved; only `http://127.0.0.1:<port>` may send marks. A file judgekeeper guessed and can't read exits 2, and Ctrl-C, `--debug` and `--version` keep their exit codes when the output can't be printed.
- Removed since 0.1.3: every 0.1 command, the built-in runners that called an AI, the pytest plugin, the GitHub Action and the agent skill.
- The license is now Apache-2.0 (was MIT).

Earlier versions (0.1.0 to 1.0.0b1): see the PyPI release history.
