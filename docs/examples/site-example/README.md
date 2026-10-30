# Example project (made-up answers)

The example project the terminal screens on the website's home page show: a promptfoo eval of
a support bot with 40 made-up answers, graded by my-judge-v1 (23 Pass, 17 Fail), and
30 made-up marks. No AI was called: the two steps that grade answers again used made-up promptfoo
results.

`report.html` and `result.json` are what judgekeeper wrote for it at the Measure step (step 3),
after the 30 marks and before `judgekeeper fix`. They are made, and checked against the
screens, by `tests/test_website_screens.py`:

    TZ=UTC JK_WRITE_SITE_EXAMPLE=1 pytest tests/test_website_screens.py

`results_date` in `result.json` is in the time zone of the computer that made it (UTC here),
so the test leaves it out of the comparison, with the other times.
