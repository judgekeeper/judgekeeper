"""While the LLM-as-a-judge is asked, judgekeeper shows it is working: "12 of 72 asked" as answers come
back (workers and your own command), "Still asking your LLM-as-a-judge: ... so far." when they can't be
counted (promptfoo writes its results at the end), and once, for a model on your computer,
that it can take minutes."""

from __future__ import annotations

import sys
from types import SimpleNamespace

from judgekeeper import again


class Said:
    def __init__(self):
        self.lines = []

    def say(self, text=""):
        self.lines.append(text)


def test_counts_are_said_when_they_move_on_and_the_last_one_always(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(again.time, "monotonic", lambda: clock[0])
    talk = Said()
    progress = again.Progress(talk, 72)
    progress.count(1)  # too soon after the start
    clock[0] += 6
    progress.count(12)
    progress.count(12)  # no change: said once
    clock[0] += 1
    progress.count(20)  # too soon after the last line
    progress.count(72)  # the last one, always
    assert talk.lines == ["  12 of 72 asked", "  72 of 72 asked"]


def test_with_nothing_to_count_it_says_it_is_still_asking(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(again.time, "monotonic", lambda: clock[0])
    talk = Said()
    progress = again.Progress(talk, None)
    clock[0] = 10
    progress.tick()
    clock[0] = 31
    progress.tick()
    clock[0] = 95
    progress.tick()
    assert talk.lines == ["  Still asking your LLM-as-a-judge: 31 s so far.",
                          "  Still asking your LLM-as-a-judge: 1 min 35 s so far."]


def test_run_process_looks_at_the_progress_while_it_waits(tmp_path, monkeypatch):
    monkeypatch.setattr(again, "TICK", 0.1)
    looks = []
    with again.watching(lambda: looks.append(1)):
        proc = again.run_process([sys.executable, "-c", "import time; time.sleep(1)"],
                                 cwd=tmp_path)
    assert proc.returncode == 0 and len(looks) >= 3
    looks.clear()
    again.run_process([sys.executable, "-c", "pass"], cwd=tmp_path)  # not watched: no looks
    assert not looks


def test_a_progress_error_never_stops_the_run(tmp_path, monkeypatch):
    monkeypatch.setattr(again, "TICK", 0.1)

    def broken():
        raise RuntimeError("no")

    with again.watching(broken):
        proc = again.run_process([sys.executable, "-c", "import time; time.sleep(0.5)"],
                                 cwd=tmp_path)
    assert proc.returncode == 0


def test_a_timeout_still_stops_a_watched_program(tmp_path, monkeypatch):
    monkeypatch.setattr(again, "TICK", 0.1)
    with again.watching(lambda: None):
        proc = again.run_process([sys.executable, "-c", "import time; time.sleep(30)"],
                                 cwd=tmp_path, timeout=0.5)
    assert proc.returncode == 124


def test_a_model_on_your_computer():
    assert again.local_model(SimpleNamespace(provider="ollama", model="llama3.2:3b"))
    assert again.local_model(SimpleNamespace(provider=None, model="ollama:chat:llama3.2"))
    assert not again.local_model(SimpleNamespace(provider="openai", model="gpt-4.1-mini"))
