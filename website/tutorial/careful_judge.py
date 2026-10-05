"""A careful judge, for the judgekeeper tutorial.

It knows the three wrong facts in the tutorial answers and fails them. On one question,
"How many continents are there?", it is unsure: each time it sees that question it
fails it 40% of the time. Real AI judges behave like this. Ask the same question
twice and you can get two different verdicts.

The randomness uses a fixed seed (15), so everyone who runs the tutorial gets the same
result: run 2 fails the continents question, runs 1 and 3 pass it.

judgekeeper calls judge(item) once per question per run, one run after another.
"""

import random

WRONG_FACTS = ["Dickens", "Saturn", "oxygen"]
_coin = random.Random(15)


def judge(item):
    if any(fact in item["output"] for fact in WRONG_FACTS):
        return {"verdict": "fail", "reason": "states a wrong fact"}
    if "continents" in item["input"] and _coin.random() < 0.4:
        return {"verdict": "fail", "reason": "not sure about the count"}
    return {"verdict": "pass", "reason": "correct"}
