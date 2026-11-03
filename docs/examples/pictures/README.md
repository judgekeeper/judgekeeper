# The pictures' project (made-up answers)

The project the website's result picture (`website/assets/shots/result.webp`) and the README's
demo (`docs/assets/demo.webp`) show: a support bot with 40 made-up answers, saved with
`judgekeeper.record()` and graded by my-judge-v1, and a made-up mark for every answer. No AI
was called. The answers and marks are in `scripts/make_site_shots.py`, which takes the
pictures; `scripts/make_demo.py` uses the same project.

`result.json`, `report.html` and `measure-screen.txt` are what judgekeeper wrote and printed
at the Measure step (step 3), after every answer was marked. They are made, and checked
against a new run, by `tests/test_site_pictures.py`:

    JK_WRITE_PICTURES=1 pytest tests/test_site_pictures.py

The pictures show the same numbers: 13 of 40 answers disagreed on; of the 22 you passed, it
passed 19 and failed 3; of the 18 you failed, it passed 10 and failed 8; 86% and 44%.
