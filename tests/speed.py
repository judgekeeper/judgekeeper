"""Speed checks that hold on a slow or busy runner.

A check against work that grows faster than its input times the same work at two sizes in the
same run and compares the two. Ten times the input takes about ten times as long when the
work grows with it, and about a hundred times as long when it grows with its square. A runner
ten times slower makes both runs slower, so the ratio holds where a fixed number of seconds
does not.
"""

from __future__ import annotations

import time
from collections.abc import Callable

FLOOR = 0.02  # seconds: a shorter small run is counted as this long (the clock's noise)


def seconds(work: Callable[[], object], tries: int = 2) -> float:
    """The fastest of `tries` runs of work(): a run slowed by the machine counts for less."""
    best = float("inf")
    for _ in range(tries):
        start = time.perf_counter()
        work()
        best = min(best, time.perf_counter() - start)
    return best


def assert_grows_at_most(work_at: Callable[[int], object], small: int, large: int,
                         most: float, tries: int = 2) -> None:
    """work_at(large) takes at most `most` times as long as work_at(small)."""
    a = seconds(lambda: work_at(small), tries)
    b = seconds(lambda: work_at(large), tries)
    assert b <= most * max(a, FLOOR), (
        f"{large:,} took {b:.3f} s, {small:,} took {a:.3f} s: {b / max(a, FLOOR):.1f} times "
        f"as long, more than {most}")
