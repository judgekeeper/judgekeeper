"""A lazy judge, for the judgekeeper tutorial.

It does not check facts. It passes any answer that sounds confident, which here means
the answer says "is" or starts with "There are". Weak AI judges fail in this way: they
reward answers that sound sure of themselves, right or wrong.

judgekeeper calls judge(item) once per question per run. `item` holds the question's
id, input (the question) and output (the answer). It never holds the human's label.
"""


def judge(item):
    answer = item["output"]
    if " is " in answer or answer.startswith("There are"):
        return "pass"
    return "fail"
