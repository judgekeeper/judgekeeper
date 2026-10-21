"""Fixes from the third bug hunt: provider errors read as the judge's Fail, judge columns taken
without asking, report.html after a check that ends Worse, the marking page's reasons, batches
and the reading of damaged files. Every fixture here is made up, with the shape of the files
the hunt used.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from judgekeeper.cli import main
from tests.start_projects import RUBRIC, promptfoo_data, question, split
from tests.test_front import assert_one_next_at_the_end, flat


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def run(capsys, *argv):
    code = main([str(a) for a in argv])
    out, err = capsys.readouterr()
    return code, out + err


def write_csv(path: Path, columns: list[str], rows: list[list]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(columns)
        w.writerows(rows)
    return path


# promptfoo provider errors -----------------------------------------------------------------

def provider_error(row: dict) -> dict:
    """A row as promptfoo saves it when the model under test never answered: the judge never
    ran, so there is no gradingResult."""
    message = "API call error: Request failed after 0 retries: fetch failed"
    row.update({"response": {"error": message}, "error": message, "success": False,
                "score": 0, "failureReason": 2, "gradingResult": None})
    return row


def test_provider_errors_are_never_the_judges_fail(here, capsys):
    data = promptfoo_data(split(24, 16))
    for r in data["results"]["results"]:
        r["testCase"]["assert"] = [{"type": "llm-rubric", "value": RUBRIC}]
    for r in data["results"]["results"][:6]:
        provider_error(r)
    (here / "results.json").write_text(json.dumps(data), encoding="utf-8")
    code, out = run(capsys)
    assert code == 0, out
    assert "Your judge passed 18 answers and failed 16." in out
    assert "failed 22" not in out


def test_a_file_of_provider_errors_only_has_no_judge_decisions(here, capsys):
    data = promptfoo_data(split(2, 0))
    for r in data["results"]["results"]:
        r["testCase"]["assert"] = [{"type": "llm-rubric", "value": RUBRIC}]
        provider_error(r)
    (here / "results.json").write_text(json.dumps(data), encoding="utf-8")
    code, out = run(capsys)
    assert code != 0, out
    assert "failed 2" not in out
    assert "too strict" not in out
    assert "http://127.0.0.1" not in out


# Two judge columns -------------------------------------------------------------------------

def test_a_judge_named_0_1_column_beside_a_score_column_asks_which(here, capsys):
    rows = [[question(i), f"A full answer number {i}.", str(i % 2), ["0.1", "0.5", "0.9"][i % 3],
             str((i + 1) % 2)] for i in range(60)]
    write_csv(here / "results.csv", ["query", "completion", "llm_judge", "passed", "exact_match"],
              rows)
    code, out = run(capsys)
    assert code == 3, out
    assert "http://127.0.0.1" not in out
    assert "llm_judge (60 answers)" in out
    assert "passed (60 answers)" in out
    assert out.index("llm_judge (60 answers)") < out.index("passed (60 answers)")
    assert "--metric NAME" in assert_one_next_at_the_end(out)


def test_a_judge_named_0_1_column_beside_a_verdict_column_asks_which(here, capsys):
    rows = [[question(i), f"A full answer number {i}.", str(i % 2),
             "Fail" if i % 3 == 0 else "Pass"] for i in range(60)]
    write_csv(here / "results.csv", ["input", "output", "llm_judge", "verdict"], rows)
    code, out = run(capsys)
    assert code == 3, out
    assert "http://127.0.0.1" not in out
    assert out.index("llm_judge (60 answers)") < out.index("verdict (60 answers)")
    assert "--metric NAME" in assert_one_next_at_the_end(out)
    code, out = run(capsys, "--metric", "llm_judge")
    assert code == 0, out
    assert "Your judge passed 30 answers and failed 30." in flat(out)


# A judge that gives every answer the same grade ----------------------------------------------

def plain_jeffreys(k: int, n: int, level: float) -> tuple[float, float]:
    """The plain Jeffreys interval for k of n, from Beta(k + 0.5, n - k + 0.5): 0 at the low
    end when k is 0, 1 at the high end when k is n."""
    import random

    rng = random.Random(7)
    draws = sorted(rng.betavariate(k + 0.5, n - k + 0.5) for _ in range(40_000))
    lo, hi = draws[int((1 - level) / 2 * len(draws))], draws[int((1 + level) / 2 * len(draws))]
    return (0.0 if k == 0 else lo), (1.0 if k == n else hi)


@pytest.mark.parametrize("marks", [(23, 17), (12, 8), (30, 10)])
def test_a_judge_that_passes_every_answer_gets_ranges_of_some_width(marks):
    from judgekeeper import targets, weighted

    said_pass, said_fail = marks
    # the judge passed all 40 answers in the pool; the person marked some Pass, some Fail
    out = weighted.corrected(40, 0, said_pass + said_fail, said_pass, 0, 0)
    tpr, tnr = out["tpr_interval"], out["tnr_interval"]
    assert out["tpr"] == 1.0 and out["tnr"] == 0.0
    assert tpr[1] - tpr[0] > 0.01 and tnr[1] - tnr[0] > 0.01
    lo, _ = plain_jeffreys(said_pass, said_pass, weighted.LEVEL)
    _, hi = plain_jeffreys(0, said_fail, weighted.LEVEL)
    assert tpr[0] <= lo + 0.01 and tpr[1] == 1.0
    assert tnr[0] == 0.0 and tnr[1] >= hi - 0.01
    assert targets.level(tpr, tnr) == "not_gate"


@pytest.mark.parametrize("marks", [(17, 23), (8, 12), (10, 30)])
def test_a_judge_that_fails_every_answer_gets_ranges_of_some_width(marks):
    from judgekeeper import targets, weighted

    said_pass, said_fail = marks
    out = weighted.corrected(0, 40, 0, 0, said_pass + said_fail, said_fail)
    tpr, tnr = out["tpr_interval"], out["tnr_interval"]
    assert out["tpr"] == 0.0 and out["tnr"] == 1.0
    assert tpr[1] - tpr[0] > 0.01 and tnr[1] - tnr[0] > 0.01
    _, hi = plain_jeffreys(0, said_pass, weighted.LEVEL)
    lo, _ = plain_jeffreys(said_fail, said_fail, weighted.LEVEL)
    assert tpr[0] == 0.0 and tpr[1] >= hi - 0.01
    assert tnr[0] <= lo + 0.01 and tnr[1] == 1.0
    assert targets.level(tpr, tnr) == "not_gate"



# report.html after a check that ends Worse -------------------------------------------------

@pytest.mark.parametrize("paid", [False, True])
def test_report_after_worse_says_the_last_check_at_the_top(here, capsys, monkeypatch, paid):
    from judgekeeper import again, keys
    from judgekeeper.start_label import StartSession, store_result
    from tests.start_projects import project_promptfoo
    from tests.test_again_run import FakePromptfoo
    from tests.test_check import HAIKU, LENIENT, _marked, _new_outputs, _results
    from tests.test_check import run as check_run

    ws = _marked(here)
    store_result(ws, StartSession(ws))
    before = ws.report_html.read_text(encoding="utf-8")
    assert "Last check" not in before
    if paid:
        project_promptfoo(here)
        for name in keys.all_names():
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setenv("OPENAI_API_KEY", "x" * 30)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "y" * 30)
        monkeypatch.setattr(again, "which", lambda name: None)
        _results(here, LENIENT, model=HAIKU, outputs=_new_outputs())
        monkeypatch.setattr(again, "run_process", FakePromptfoo(ws, version="0.124.1"))
        code, out = check_run(capsys, "--yes")
    else:
        monkeypatch.setattr(again, "run_process", lambda *a, **k: pytest.fail("asked"))
        _results(here, LENIENT, model=HAIKU)
        code, out = check_run(capsys)
    assert code == 1, out
    html = ws.report_html.read_text(encoding="utf-8")
    top = html[html.index("Last check"):html.index('class="verdict')]
    assert "claude-haiku-4-5" in top
    assert "Worse" in top
    assert "9 answers went from right to wrong" in flat(top)
    assert "points lower (between" in top
    assert "Go back to the old judge" in top
    assert html.count("Go back to the old judge") == 1
    assert "Answers you passed" in html or "agreed on all" in html  # the old judge stays
