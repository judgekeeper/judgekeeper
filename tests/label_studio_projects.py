"""Label Studio exports for tests, made up: a list of tasks as the project's JSON export writes
it (`data`, `annotations`, `predictions`). Nothing here is a real person's or a real answer.
"""

from __future__ import annotations

import json
from pathlib import Path

from tests.conftest import FIXTURES

FIXTURE_DIR = FIXTURES / "label_studio"
ONE_PERSON = FIXTURE_DIR / "one-person.json"
SEVERAL_PEOPLE = FIXTURE_DIR / "several-people.json"
EMAIL = "ada.lovelace@example.com"


def choice(word: str, name: str = "verdict", to: str = "answer") -> dict:
    return {"from_name": name, "to_name": to, "type": "choices", "value": {"choices": [word]}}


def annotation(n: int, who, results: list[dict], *, cancelled: bool = False,
               truth: bool = False, at: str = "2026-11-10T10:00:00.000000Z",
               seconds: float = 12.5) -> dict:
    return {"id": n, "completed_by": who, "result": results, "was_cancelled": cancelled,
            "ground_truth": truth, "created_at": at, "lead_time": seconds}


def prediction(n: int, version: str | None, results: list[dict], score: float = 0.9) -> dict:
    return {"id": n, "model_version": version, "score": score, "result": results}


def task(i: int, labels=(), predictions=(), data: dict | None = None) -> dict:
    """Task `i` (Label Studio's id 100 + i): `labels` are (person, word) pairs; `predictions`
    are (model_version, word) pairs, all on a "verdict" choices control."""
    return {
        "id": 100 + i,
        "data": data if data is not None else {
            "question": f"Question {i}: how do I reset the widget?",
            "answer": f"Answer {i}: hold the button for five seconds."},
        "annotations": [annotation(1000 + i * 10 + n, who, [choice(word)],
                                   at=f"2026-11-1{n}T10:00:00.000000Z", seconds=12.5 + n)
                        for n, (who, word) in enumerate(labels)],
        "predictions": [prediction(5000 + i * 10 + n, version, [choice(word)])
                        for n, (version, word) in enumerate(predictions)]}


def write(path: Path, tasks: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(tasks, indent=1), encoding="utf-8")
    return path


def export(path: Path, humans: list[str], judge: list[str], version: str = "judge-v1",
           person: int = 7, tag: str = "") -> Path:
    """A project export: one person's Pass/Fail words and one grader's, one task each."""
    return write(path, [
        task(i, [(person, h)], [(version, g)] if g else [],
             data={"question": f"Question {i}?{tag}", "answer": f"Answer {i}.{tag}"})
        for i, (h, g) in enumerate(zip(humans, judge, strict=True))])


def kinds(n_pass: int, n_fail: int) -> list[str]:
    return ["Pass"] * n_pass + ["Fail"] * n_fail
