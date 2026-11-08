"""The Next lines of the --labels stops keep what the run already had: the --label-map saved by
an earlier run, and --labels itself when the grades then need a map."""

from __future__ import annotations

import csv

import pytest

from judgekeeper.cli import main

PAGE = ("--no-browser", "--port", "0", "--yes")
CMD = "judgekeeper --port 0 --no-browser"


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with (tmp_path / "results.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["input", "output", "verdict", "human_label"])
        for i in range(40):
            label = "skip" if i == 39 else ("Y" if i % 2 else "N")
            w.writerow([f"Map q {i}", f"Map answer {i}.", "ok" if i < 24 else "bad", label])
    return tmp_path


def run(capsys, *argv) -> tuple[int, str]:
    code = main([*argv, *PAGE])
    out = "".join(capsys.readouterr())
    main(["--stop"])
    capsys.readouterr()
    return code, " ".join(out.split())


def test_the_labels_stop_keeps_the_label_map_saved_before(here, capsys):
    code, out = run(capsys, "--label-map", "ok=pass,bad=fail")
    assert code == 0, out
    code, out = run(capsys, "--labels")
    assert code == 3, out
    assert "Some labels in your results aren't Pass or Fail: N, Y, skip." in out, out
    assert (f'Next: say what each one means, then run `{CMD} --labels --label-map '
            f'"ok=pass,bad=fail,WORD=pass,WORD=fail"`.') in out, out


def test_the_grades_stop_after_labels_keeps_labels(here, capsys):
    code, out = run(capsys, "--labels", "--label-map", "Y=pass,N=fail,skip=error")
    assert code == 3, out
    assert "can't tell which of your LLM-as-a-judge's decisions mean Pass" in out, out
    nxt = out[out.rindex("Next:"):]
    assert "--labels" in nxt, nxt
    assert '"Y=pass,N=fail,skip=error,VALUE=pass,VALUE=fail,VALUE=error"' in nxt, nxt
