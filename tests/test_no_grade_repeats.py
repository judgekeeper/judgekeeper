"""With answers and no grade, an answer shown again and marked differently the second time is
said in the result, as with an LLM-as-a-judge: only the first mark counts."""
from __future__ import annotations

from judgekeeper import start_label
from tests.test_answers_without_grades import here, write_answers  # noqa: F401
from tests.test_front import flat, run
from tests.test_repeats import _until_offer

CHANGED = "You saw 1 answer twice and marked it differently the second time. Only your first " \
          "mark counts."


def _say(capsys) -> str:
    _code, out, err = run(capsys, "--no-browser", "--port", "0")
    return flat(out + err)


def test_a_repeat_marked_differently_is_said_in_the_result(here, capsys):  # noqa: F811
    write_answers(here, 40)
    _say(capsys)  # the session
    ws = start_label.Workspace(here)
    session = start_label.StartSession(ws)
    _, offer = _until_offer(session)
    first = session.by_id[offer["id"]]["label"]
    session.update({"id": offer["id"], "label": "fail" if first == "pass" else "pass",
                    "again": offer["slot"], "seconds": 3})
    for k, item in enumerate(session.items):
        if not item["label"]:
            session.update({"id": item["id"], "label": "pass" if k % 3 else "fail",
                            "seconds": 3})
    said = _say(capsys)
    assert "You passed" in said, said
    assert CHANGED in said, said
    assert CHANGED in flat(ws.report_html.read_text(encoding="utf-8"))
