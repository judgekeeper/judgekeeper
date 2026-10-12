"""`judgekeeper mark`: for marking more. It goes through `judgekeeper`'s state table
(front.py) and opens the page in every row but two:

| What is there                                  | What mark does                           | Exit |
|------------------------------------------------|------------------------------------------|------|
| something must be asked (several tools,        | the same finding as `judgekeeper`        | 3    |
| judges, a pass mark, an own format...)         | (front.py): a question and its Next:     |      |
| marks for another judge (another metric or     | says so and asks "Start over with these  | 3    |
| tool), or labels.csv from 0.2                  | results?" (the question list, then       |      |
|                                                | --yes); yes moves the old marks to       |      |
|                                                | previous-<date>/ and goes on             |      |
| anything else                                  | prepares the pool if it is not there,    | 0    |
|                                                | opens a new page (page.py) and prints    |      |
|                                                | the count so far                         |      |
| the page could not start in the background     | says so in one line                      | 3    |

The result is `judgekeeper`'s: its Next: line says to run `judgekeeper` when the person is
done. `--wait` serves the page in this terminal instead, `--stop` closes it, `--new` starts
over (asked first). Marks made by judgekeeper 0.2 (labels.csv) are never used: they have no
stamps.

Like `judgekeeper`, the output holds counts, names and paths, never an answer's or an input's
text, and ends with exactly one `Next:` line.
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
        judge_model: str | None = None, fields: str | None = None, yes: bool = False,
        port: int = DEFAULT_PORT, no_browser: bool = False, new: bool = False,
        wait: bool = False, stop: bool = False) -> int:
    """`judgekeeper mark`. Returns the exit code."""
    options = {"tool": tool, "metric": metric, "experiment": experiment,
               "tracking_uri": tracking_uri, "pass_if": pass_if, "label_map": label_map,
               "judge_model": judge_model, "fields": fields, "port": port,
               "no_browser": no_browser}
    talk = MarkTalk(yes=yes, path=path, options=options, new=new)
    return front.go(talk, Path(path), wait=wait, stop=stop, marking=True)
