A made-up example: the questions, answers and marks were written for this example, not taken from a real AI or real users.

# Checking an AI's answers with no LLM-as-a-judge

A help bot for a made-up online shop answers 20 questions about returns, delivery and
payments. Some of its answers are wrong. There is no LLM-as-a-judge: a person marks each
answer Pass or Fail, and judgekeeper says how many passed.

The shop's facts, which a right answer says: returns within 30 days of delivery; the refund
goes back to the way you paid within 5 working days of the return arriving; standard delivery
in 3 to 5 working days, with no delivery charge on orders over 50 pounds, else 4.95 pounds;
express delivery the next working day if ordered before 2pm, 7.95 pounds; card, PayPal or a
gift card; gift cards can't be refunded; a damaged item: send a photo within 7 days for a
replacement.

## The first run

- `results.csv`: the 20 questions (`input`) and the bot's answers (`output`), with no grades.
- `terminal-1.txt`: what `judgekeeper` printed. The first run found the answers and opened the
  marking page. After every answer was marked, the second run printed the result.
- `marks.jsonl`: the marks, made on the marking page, one line per click. A reason was added
  on the result page to each failed answer it listed.
- `report.html`: the result page. Open it in your browser.
- `failed-answers.md`: the answers failed, with the reasons, for a coding agent.

The result: 12 of 20 answers passed, about 60%, between 39% and 78%. Of the 8 failed, 4 are
kept aside to test a fix, so the result lists the other 4: 3 with a wrong fact, 1 unsafe.

## The second run

The bot's prompt was changed, and it answered the same 20 questions again.

- `results-after.csv`: the new answers. 6 of them say something new; the other 14 say the
  same thing in new words.
- `terminal-2.txt`: what `judgekeeper` printed. The first command opened the marking page for
  the new answers; after every answer was marked, the second printed the result.

The result: 16 of 20 answers passed. On the 10 questions kept aside, 2 were fixed, 1 broke
and 7 stayed the same. So judgekeeper can't tell yet whether the change helped: it leans
toward better, but a split this small could easily be a coincidence. The line it prints
after that, "Mark more questions for a clearer answer.", is the next step here.

Made with judgekeeper from commit `5bced99` (first run) and `3c84b11` (second run) on
2026-11-09.
