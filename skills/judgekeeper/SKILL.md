---
name: judgekeeper
description: Check how often a project's LLM-as-a-judge agrees with human labels (TPR, TNR, kappa) using judgekeeper. Use when a project grades outputs with an LLM judge, eval framework or rubric model and the user asks how often the judge agrees with people, or wants human labels.
---

# judgekeeper: check an LLM-as-a-judge against the person's marks

judgekeeper reads the results the project's LLM-as-a-judge already saved and checks them for
free. The person marks some answers Pass or Fail on a page in their browser, and judgekeeper
shows how often the judge agrees with them.

Run `uvx judgekeeper@1.0.0b1` in the project folder (or `judgekeeper` if installed). Each run
does the next step and ends with one line that starts with `Next:`: follow each `Next:` line.
Run it again the same way you started it. The person may write little code, so say what you
are doing in plain words. All flags: `judgekeeper --help`.

## Rules

- Only the person marks. Never mark answers, not even as a draft, and never let a model mark
  one: the marks are the only part of the check that is not a model's opinion.
- The page is the person's: never write or edit anything in `.judgekeeper/`, never send
  requests to the marking page, never look for its link or token. judgekeeper opens the page
  in the person's browser itself.
- Never read the answers' text. judgekeeper prints none on purpose; don't open the results
  files to look.
- Ask the person every question judgekeeper prints, word for word, and wait for the answer.
  Then run the command the `Next:` line names; pass `--yes` only after their yes.
- Report TPR, TNR and kappa together, with their ranges and the line "this set can see a drop
  of X" judgekeeper prints. Never report raw agreement on its own.
- Keys only in environment variables; never print or write one. Marking and the result make
  no AI call and need no key.

## The steps

1. The first run says which eval tool and judge it found, checks the judge's verdicts for
   free, and opens the marking page in the person's browser. It shows one answer at a time,
   with the judge's verdict hidden.
2. Tell the person the page is open and to mark answers until the page says it has enough
   (15 Pass and 15 Fail for a first result). Then wait: do nothing until they say they are
   done.
3. Run it again, as the `Next:` line says. With enough marks it prints the result; with too
   few it opens the page again and says how many are marked so far.
4. Tell the result in plain words, quoting the numbers it printed:
   - TPR: of the answers the person passed, how many the judge passed.
   - TNR: of the answers the person failed, how many the judge failed. A judge that passes
     everything has TPR 1.0 and TNR 0.0.
   - Kappa: agreement beyond chance (1 is perfect, 0 is chance).
   - The ranges, and the smallest drop this set of marks can see.

To mark more later: `judgekeeper mark`. To close the page: `judgekeeper --stop`.

If judgekeeper finds no judge in the project, say so and stop.
