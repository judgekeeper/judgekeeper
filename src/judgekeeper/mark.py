"""`judgekeeper mark`: open the marking page to mark more.

It goes through `judgekeeper`'s state table (front.py). When something must be asked (several
tools or judges, a pass mark, an own format), it asks the same question, exit 3. When the
marks are for another LLM-as-a-judge, it asks "Start over with these results?"; a yes moves
the old marks to previous-<date>/ and goes on. Otherwise it prepares the pool if needed, opens
the page and prints the count so far (exit 0), unless every answer is marked with under 15 of
one kind (exit 3, no page).

`--wait` serves the page in this terminal, `--stop` closes it, `--new` starts over (asked
first). Marks from an unreleased 0.2 build (labels.csv) are never used: they have no stamps. The
output holds counts, names and paths, never an answer's or an input's text, and ends with
exactly one `Next:` line.
"""

from __future__ import annotations

from pathlib import Path

from judgekeeper import front
from judgekeeper.label import DEFAULT_PORT

__all__ = ["run"]


class MarkTalk(front.FrontTalk):
    """front.FrontTalk for `judgekeeper mark`: printed commands start `judgekeeper mark`, and
    repeat --new while it is asked about. A choice made at a terminal is repeated as its
    flag."""

    subcommand = "mark"

    def remember(self, flag: str, chosen: str, line: str | None = None) -> None:
        super().remember(flag, chosen, line)
        if flag in front.ASKED:
            self.set(front.ASKED[flag], chosen)


def run(path: str | Path = ".", tool: str | None = None, metric: str | None = None,
        experiment: str | None = None, tracking_uri: str | None = None,
        pass_if: str | None = None, label_map: str | None = None,
        judge_model: str | None = None, yes: bool = False,
        port: int = DEFAULT_PORT, no_browser: bool = False, new: bool = False,
        wait: bool = False, stop: bool = False) -> int:
    """`judgekeeper mark`. Returns the exit code."""
    options = {"tool": tool, "metric": metric, "experiment": experiment,
               "tracking_uri": tracking_uri, "pass_if": pass_if, "label_map": label_map,
               "judge_model": judge_model, "port": port,
               "no_browser": no_browser}
    talk = MarkTalk(yes=yes, path=path, options=options, new=new)
    return front.go(talk, Path(path), wait=wait, stop=stop, marking=True)
