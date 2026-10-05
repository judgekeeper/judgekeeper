"""Replay runner: returns judgments recorded in a judgments JSONL file. No network."""

from __future__ import annotations

from pathlib import Path

from judgekeeper.fingerprint import JudgeFingerprint
from judgekeeper.runners.base import Judgment


class ReplayRunner:
    def __init__(self, path: str | Path):
        from judgekeeper.judgments import read_run

        self.path = Path(path)
        header, self._records = read_run(self.path)
        self._fingerprint = JudgeFingerprint.from_dict(header["fingerprint"])

    @property
    def fingerprint(self) -> JudgeFingerprint:
        return self._fingerprint

    def judge(self, item: dict) -> Judgment:
        from judgekeeper.judgments import record_to_judgment

        if item["id"] not in self._records:
            raise KeyError(f"no recorded judgment for item {item['id']!r} in {self.path}")
        return record_to_judgment(self._records[item["id"]])
