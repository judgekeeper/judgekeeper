"""Run a judge over an anchor set N times and write one judgments file per run.

A judge call that fails (after the SDK's own retries) stops the run with JudgeCallError and
nothing is written for that run: a failed call is never scored.

A custom judge that raises, or returns nothing usable, gives an "error" judgment instead. Those
are written, and counted on the list `run_judge` returns, so the caller can say that a judge
failed on some items, or on every one.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from judgekeeper.fingerprint import utc_now
from judgekeeper.judgments import judgment_to_record, write_run
from judgekeeper.metrics import ERROR
from judgekeeper.runners.base import Judgment, Runner


class RunFiles(list):
    """The run files written, in order, with a count of the judgments that were errors."""

    def __init__(self):
        super().__init__()
        self.n_judgments = 0
        self.n_errors = 0
        self.first_error: str | None = None  # the first error judgment's message

    def count(self, judgments: list[Judgment]) -> None:
        self.n_judgments += len(judgments)
        for j in judgments:
            if j.verdict == ERROR:
                self.n_errors += 1
                if self.first_error is None:
                    self.first_error = j.error or "the judge returned nothing usable"


class JudgeCallError(Exception):
    """A judge call failed. The cause is chained; the CLI prints it scrubbed."""

    def __init__(self, item_id: str, run: int, cause: BaseException):
        self.item_id = item_id
        self.run = run
        super().__init__(f"judge call failed on item {item_id!r} in run {run}: "
                         f"{type(cause).__name__}: {cause}")


def run_judge(
    items: list[dict],
    runner: Runner,
    runs: int,
    out_dir: str | Path,
    anchors_sha256: str,
    workers: int = 1,
    progress: Callable[[str], None] | None = None,
    source: dict | None = None,
    normaliser: dict | None = None,
    after_run: Callable[[], None] | None = None,
) -> RunFiles:
    """`source` and `normaliser` go into each run header. `after_run` is called once a run's
    judgments are in, before the run is written; it may raise to stop."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written = RunFiles()
    for run in range(1, runs + 1):
        run_started = utc_now()

        def one(item: dict, run: int = run) -> tuple[dict, Judgment, str]:
            try:
                return item, runner.judge(item), utc_now()
            except Exception as e:
                raise JudgeCallError(item["id"], run, e) from e

        if workers > 1:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                results = list(pool.map(one, items))
        else:
            results = [one(item) for item in items]
        if after_run:
            after_run()

        base = runner.fingerprint
        records = []
        for item, judgment, judged_at in results:
            fp = base.with_(snapshot=judgment.snapshot or base.snapshot, created_at=judged_at)
            records.append(judgment_to_record(item["id"], judgment, fp))
        snapshots = Counter(r["fingerprint"]["snapshot"] for r in records)
        header_fp = base.with_(
            snapshot=snapshots.most_common(1)[0][0] if snapshots else base.snapshot,
            created_at=run_started,
        )
        path = out_dir / f"run-{run:02d}.jsonl"
        write_run(path, run, anchors_sha256, header_fp, records, source=source,
                  normaliser=normaliser)
        written.append(path)
        written.count([judgment for _, judgment, _ in results])
        if progress:
            noun = "judgment" if len(records) == 1 else "judgments"
            progress(f"wrote {path} ({len(records)} {noun})")
    return written
