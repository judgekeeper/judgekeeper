"""The website's result picture and the README's demo show the sample project of
scripts/make_site_shots.py (40 made-up answers, every one marked). This runs that project
through Find, Mark and Measure, as the pictures do, and checks the numbers against the files
committed in docs/examples/pictures/: result.json, report.html and the Measure screen. To
write them again:

    JK_WRITE_PICTURES=1 pytest tests/test_site_pictures.py
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import pytest

from judgekeeper.cli import main
from judgekeeper.start_label import StartSession, Workspace

pytest.importorskip("pty")  # the pictures' script runs judgekeeper at a pseudo-terminal
ROOT = Path(__file__).resolve().parent.parent
PICTURES = ROOT / "docs" / "examples" / "pictures"
sys.path.insert(0, str(ROOT / "scripts"))
import make_site_shots as shots

# What the result picture and the demo's last frame show
SHOWN = ("13 of 40 answers", "You passed 22 answers. It passed 19 and failed 3",
         "You failed 18 answers. It passed 10 and failed 8")
NUMBERS = ("tpr", "tnr", "kappa", "groups", "disagreements", "check", "verdict",
           "verdict_level", "labels", "tpr_interval", "tnr_interval", "kappa_interval")


def _run(capsys, *argv: str) -> str:
    main(list(argv))
    out, err = capsys.readouterr()
    return out + err


def _report_text(page: str) -> str:
    import html

    page = re.sub(r"<style.*?</style>|<script.*?</script>", "", page, flags=re.DOTALL)
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", page)).split())


@pytest.fixture
def measured(tmp_path, monkeypatch, capsys):
    """The sample project after every answer is marked as the pictures mark it, and Measure:
    (its .judgekeeper/, the Measure screen)."""
    folder = tmp_path / "support-bot"
    folder.mkdir()
    shots.make_project(folder)
    monkeypatch.chdir(folder)
    monkeypatch.setenv("COLUMNS", "80")
    _run(capsys, "--no-browser", "--port", "0")
    session = StartSession(Workspace(folder))
    for item in session.items:
        session.update({"id": item["id"], "label": shots.my_mark(item), "seconds": shots.SECONDS})
    _run(capsys, "--stop")
    return folder / ".judgekeeper", _run(capsys)  # every answer marked: no page opens


def test_the_pictures_numbers_are_the_committed_runs(measured):
    kept, screen = measured
    made = {"result.json": (kept / "result.json").read_text(encoding="utf-8"),
            "report.html": (kept / "report.html").read_text(encoding="utf-8"),
            "measure-screen.txt": screen}
    if os.environ.get("JK_WRITE_PICTURES"):
        for name, text in made.items():
            (PICTURES / name).write_text(text, encoding="utf-8", newline="\n")
    result = json.loads((PICTURES / "result.json").read_text(encoding="utf-8"))
    now = json.loads(made["result.json"])
    assert {k: result[k] for k in NUMBERS} == {k: now[k] for k in NUMBERS}
    # the demo's Find screen: "Your LLM-as-a-judge passed 29 answers and failed 11."
    assert (result["groups"]["pass"]["pool"], result["groups"]["fail"]["pool"]) == (29, 11)
    for report in (PICTURES / "report.html").read_text(encoding="utf-8"), made["report.html"]:
        text = _report_text(report)
        for shown in (*SHOWN, "86%", "44%"):
            assert shown in text, shown
    committed = (PICTURES / "measure-screen.txt").read_text(encoding="utf-8")
    assert " ".join(committed.split()) == " ".join(screen.split())
    for shown in SHOWN[:1]:
        assert shown in " ".join(screen.split()), shown
    assert "it also says Pass: 86%" in screen and "it also says Fail: 44%" in screen
    assert "made-up answers" in (PICTURES / "README.md").read_text(encoding="utf-8")
