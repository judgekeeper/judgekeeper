"""`migrate` on the hand-built fixtures in tests/fixtures/migrate/ (see make_fixtures.py).

Ten pairwise items, human i01-i05 A and i06-i10 B; easy = i01 i02 i03 i06 i07 i08, hard = i04
i05 i09 i10. With balanced human labels, chance agreement is 0.5 and kappa = 2 * accuracy - 1.

    H  AAAAA BBBBB   kappa 1.0, TPR 1.0, TNR 1.0
    X  AAAAB BBBBA   wrong on i05, i10: kappa 0.6, TPR 0.8, TNR 0.8
    N  AAABA BBBAB   wrong on i04, i09: kappa 0.6, TPR 0.8, TNR 0.8

Scenarios (old runs vs new runs, three runs each):
    EQUIVALENT  old X X X        new X+i05, X+i05, X+i03 (flips)
    BETTER      old X X X        new H H H
    WORSE       old H H H        new X X X
    DIFFERENT   old X X X        new N N N
"""

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest

from judgekeeper.cli import main
from judgekeeper.migrate import (
    BETTER,
    DIFFERENT,
    EQUIVALENT,
    WORSE,
    MigrateConfig,
    migrate,
    pass_rate_bridge,
    wilson,
)

MIG = Path(__file__).parent / "fixtures" / "migrate"
ANCHORS = MIG / "anchors.jsonl"
SCENARIOS = {
    EQUIVALENT: ("old", "new-equivalent"),
    BETTER: ("old", "new-better"),
    WORSE: ("old-perfect", "new-worse"),
    DIFFERENT: ("old", "new-different"),
}


def run(status: str, config: MigrateConfig | None = None) -> dict:
    old, new = SCENARIOS[status]
    return migrate(ANCHORS, MIG / old, MIG / new, config or MigrateConfig())


def approx(x):
    return pytest.approx(x, abs=1e-4)


# --- statuses and the numbers behind them ------------------------------------------------------


def test_equivalent():
    m = run(EQUIVALENT)
    assert m["status"] == EQUIVALENT
    vh = m["vs_human"]
    # old: X in every run -> kappa .6, TPR .8, TNR .8, no spread
    assert vh["old"]["kappa"] == {"mean": approx(0.6), "min": approx(0.6), "max": approx(0.6)}
    assert vh["old"]["tpr"]["mean"] == approx(0.8) and vh["old"]["tnr"]["mean"] == approx(0.8)
    # new runs: X+i05 (acc .9, kappa .8, TPR 1, TNR .8) twice, X+i03 (acc .7, kappa .4, TPR .6)
    assert vh["new"]["kappa"] == {"mean": approx(2 / 3), "min": approx(0.4), "max": approx(0.8)}
    assert vh["new"]["tpr"] == {"mean": approx(2.6 / 3), "min": approx(0.6), "max": approx(1.0)}
    assert vh["new"]["tnr"] == {"mean": approx(0.8), "min": approx(0.8), "max": approx(0.8)}
    # delta +.0667; band = max(old spread 0, new spread .4, min_band .02) = .4 -> inside
    assert vh["kappa_delta"] == approx(2 / 3 - 0.6)
    assert vh["noise_band"] == approx(0.4)
    jj = m["judge_vs_judge"]
    # majorities: old X; new X with i05 = A (A,A,B) and i03 still A (A,A,B).
    # agreement 9/10, old 5A/5B, new 6A/4B -> pe = (5*6 + 5*4)/100 = .5, kappa (.9-.5)/.5 = .8
    assert jj["kappa"] == approx(0.8)
    assert jj["n_changed"] == 1 and jj["changed_share"] == approx(0.1)
    # i05 changed, but the new judge flipped on it: within noise, not fixed
    assert jj["n_changed_within_noise"] == 1
    assert jj["n_changed_stable"] == 0 and jj["changed_stable_share"] == 0
    assert (jj["n_fixed"], jj["n_broken"], jj["net"]) == (0, 0, 0)
    assert [(c["id"], c["outcome"], c["stable"]) for c in m["changed_items"]] == [
        ("i05", "within_noise", False)]


def test_better():
    m = run(BETTER)
    assert m["status"] == BETTER
    vh = m["vs_human"]
    assert vh["new"]["kappa"]["mean"] == approx(1.0)
    assert vh["new"]["tpr"]["mean"] == approx(1.0) and vh["new"]["tnr"]["mean"] == approx(1.0)
    # delta +.4, both judges unanimous -> band = min_band .02 -> outside, positive
    assert vh["kappa_delta"] == approx(0.4)
    assert vh["noise_band"] == approx(0.02)
    jj = m["judge_vs_judge"]
    # X vs H: agreement 8/10, both 5/5 -> kappa .6. i05 B->A and i10 A->B, both now right.
    assert jj["kappa"] == approx(0.6)
    assert jj["n_changed"] == 2 and jj["changed_share"] == approx(0.2)
    assert jj["n_changed_stable"] == 2 and jj["changed_stable_share"] == approx(0.2)
    assert jj["n_changed_within_noise"] == 0
    assert (jj["n_fixed"], jj["n_broken"], jj["net"]) == (2, 0, 2)
    assert [(c["id"], c["old"], c["new"], c["outcome"]) for c in m["changed_items"]] == [
        ("i05", "B", "A", "fixed"), ("i10", "A", "B", "fixed")]


def test_worse():
    m = run(WORSE)
    assert m["status"] == WORSE
    assert m["vs_human"]["kappa_delta"] == approx(-0.4)
    jj = m["judge_vs_judge"]
    assert jj["kappa"] == approx(0.6)
    assert (jj["n_fixed"], jj["n_broken"], jj["net"]) == (0, 2, -2)
    assert [(c["id"], c["outcome"]) for c in m["changed_items"]] == [
        ("i05", "broken"), ("i10", "broken")]


def test_different():
    m = run(DIFFERENT)
    assert m["status"] == DIFFERENT
    vh = m["vs_human"]
    # both kappa .6 in every run: delta 0, band .02
    assert vh["kappa_delta"] == approx(0.0) and vh["noise_band"] == approx(0.02)
    jj = m["judge_vs_judge"]
    # X vs N agree on 6/10 (differ on i04, i05, i09, i10), both 5A/5B -> kappa .2
    assert jj["kappa"] == approx(0.2)
    assert jj["n_changed"] == 4 and jj["n_changed_stable"] == 4
    assert jj["changed_stable_share"] == approx(0.4)
    # i05, i10 fixed; i04, i09 broken
    assert (jj["n_fixed"], jj["n_broken"], jj["net"]) == (2, 2, 0)
    assert {c["id"]: c["outcome"] for c in m["changed_items"]} == {
        "i04": "broken", "i05": "fixed", "i09": "broken", "i10": "fixed"}


def test_status_thresholds_come_from_config():
    # DIFFERENT's changed-and-stable share is .4; allow up to .5 and it is EQUIVALENT
    assert run(DIFFERENT, MigrateConfig(max_changed_share=0.5))["status"] == EQUIVALENT
    # BETTER's delta of .4 is inside a .5 band, and its changed share .2 is above .02
    assert run(BETTER, MigrateConfig(min_band=0.5))["status"] == DIFFERENT


# --- sections ---------------------------------------------------------------------------------


def test_fingerprints_side_by_side():
    m = run(BETTER)
    fps = m["fingerprints"]
    assert fps["old"]["model"] == "judge-old" and fps["new"]["model"] == "judge-new"
    assert fps["changed_fields"] == ["model", "snapshot"]
    assert m["snapshots_seen"] == {"old": ["judge-old"], "new": ["judge-new"]}


def test_per_slice():
    slices = {s["slice"]: s for s in run(DIFFERENT)["slices"]}
    # easy: both judges right on all six -> kappa 1 and 1
    assert slices["easy"] == {"slice": "easy", "n": 6, "old_kappa": approx(1.0),
                              "new_kappa": approx(1.0), "delta": approx(0.0),
                              "n_changed_stable": 0}
    # hard (human A A B B): old A B B A, new B A A B -> both 2/4 right, judge 2A/2B -> kappa 0
    assert slices["hard"]["old_kappa"] == approx(0.0)
    assert slices["hard"]["new_kappa"] == approx(0.0)
    assert slices["hard"]["n_changed_stable"] == 4

    eq = {s["slice"]: s for s in run(EQUIVALENT)["slices"]}
    # easy, new run 3 has i03 = B: 5/6 right, judge 2A/4B, pe .5 -> kappa 2/3; mean (1+1+2/3)/3
    assert eq["easy"]["new_kappa"] == approx((2 + 2 / 3) / 3)
    assert eq["easy"]["delta"] == approx((2 + 2 / 3) / 3 - 1)
    # hard, new runs 1-2 have i05 = A: 3/4 right, judge 3A/1B, pe .5 -> kappa .5; run 3 kappa 0
    assert eq["hard"]["new_kappa"] == approx(1 / 3)
    assert eq["hard"]["old_kappa"] == approx(0.0)


def test_changed_items_carry_both_rationales():
    items = {c["id"]: c for c in run(BETTER)["changed_items"]}
    i05 = items["i05"]
    assert (i05["slice"], i05["human"]) == ("hard", "A")
    assert i05["old_rationale"] == "old run1 i05 AB"
    assert i05["new_rationale"] == "new-better run1 i05 AB"


def test_pass_rate_bridge_hand_computed():
    b = run(DIFFERENT)["bridge"]
    assert b["positive_label"] == "A" and b["positive_name"] == "prefers A"
    # old majority X: A on i01 i02 i03 i04 i10; new N says A on i01 i02 i03 of those -> 3/5
    # old B on i05..i09; new says A on i05 and i09 -> 2/5
    a, bb = b["overall"]["a"], b["overall"]["b"]
    assert (a["k"], a["n"], a["p"]) == (3, 5, approx(0.6))
    assert (bb["k"], bb["n"], bb["p"]) == (2, 5, approx(0.4))
    # Wilson 95%, z = 1.96, for 3/5: centre (.6 + 1.9208/5) / (1 + 3.8416/5) = .5566,
    # half-width 1.96 * sqrt(.6 * .4 / 5 + 3.8416 / 100) / 1.76832 = .3258
    assert (a["lo"], a["hi"]) == (pytest.approx(0.2307, abs=1e-3), pytest.approx(0.8824, abs=1e-3))
    assert (bb["lo"], bb["hi"]) == (pytest.approx(0.1176, abs=1e-3),
                                    pytest.approx(0.7693, abs=1e-3))
    assert b["overall"]["n_excluded"] == 0
    # worked example: old rate .8 -> .8 * .6 + .2 * .4 = .56
    assert b["example"]["old_rate"] == 0.8
    assert b["example"]["new_rate"] == approx(0.56)
    assert "old_rate" in b["formula"] and "resembles the anchor set" in b["caveat"]
    per = {s["slice"]: s for s in b["per_slice"]}
    # easy: old A on i01-i03, new keeps all -> 3/3; old B on i06-i08, new A on none -> 0/3
    assert (per["easy"]["a"]["k"], per["easy"]["a"]["n"]) == (3, 3)
    assert (per["easy"]["b"]["k"], per["easy"]["b"]["n"]) == (0, 3)
    # hard: old A on i04, i10, new A on neither -> 0/2; old B on i05, i09, new A on both -> 2/2
    assert (per["hard"]["a"]["k"], per["hard"]["a"]["n"]) == (0, 2)
    assert (per["hard"]["b"]["k"], per["hard"]["b"]["n"]) == (2, 2)
    assert per["hard"]["b"]["lo"] == pytest.approx(0.3424, abs=1e-3)


def test_bridge_single_output_names_pass_and_excludes_no_majority():
    rows = [  # (slice, old majority, new majority)
        ("s", "pass", "pass"), ("s", "pass", "fail"), ("s", "fail", "pass"),
        ("s", "fail", "fail"), ("s", None, "pass"), ("s", "pass", None),
    ]
    old = {f"x{k}": o for k, (_, o, _) in enumerate(rows)}
    new = {f"x{k}": n for k, (_, _, n) in enumerate(rows)}
    slices = {f"x{k}": s for k, (s, _, _) in enumerate(rows)}
    b = pass_rate_bridge(list(old), slices, old, new, positive="pass", kind="single")
    assert b["positive_name"] == "pass"
    # usable items: x0..x3 -> a = 1/2, b = 1/2; x4 and x5 lack a majority
    assert (b["overall"]["a"]["k"], b["overall"]["a"]["n"]) == (1, 2)
    assert (b["overall"]["b"]["k"], b["overall"]["b"]["n"]) == (1, 2)
    assert b["overall"]["n_excluded"] == 2


def test_wilson_edges():
    assert wilson(0, 0) == {"k": 0, "n": 0, "p": None, "lo": None, "hi": None}
    w = wilson(5, 5)
    assert w["p"] == 1.0 and w["hi"] == pytest.approx(1.0)
    assert w["lo"] == pytest.approx(0.5655, abs=1e-3)


@pytest.mark.parametrize("status,needle", [
    (EQUIVALENT, "keep comparing"),
    (BETTER, "rebase"),
    (WORSE, "do not migrate yet"),
    (DIFFERENT, "not comparable item by item"),
])
def test_verdict_says_what_to_do(status, needle):
    assert needle in run(status)["verdict"].lower()


# --- CLI --------------------------------------------------------------------------------------


@pytest.fixture
def work(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    shutil.copytree(MIG, tmp_path / "mig")
    return tmp_path


def cli(work, status, *extra):
    old, new = SCENARIOS[status]
    return main(["migrate", str(work / "mig" / "anchors.jsonl"), str(work / "mig" / old),
                 str(work / "mig" / new), "--out", str(work / "out"), *extra])


def test_cli_writes_json_and_html(work, capsys):
    assert cli(work, DIFFERENT) == 0
    m = json.loads((work / "out" / "migration.json").read_text(encoding="utf-8"))
    assert m["status"] == DIFFERENT
    html = (work / "out" / "migration.html").read_text(encoding="utf-8")
    assert html.startswith("<!doctype html>")
    assert "<script" not in html and "http://" not in html and "https://" not in html
    for needle in ["DIFFERENT", "judge-old", "judge-new", "new_rate", "Wilson", "i04",
                   "old run1 i04 AB"]:
        assert needle in html
    out = capsys.readouterr().out
    assert "DIFFERENT" in out and "migration.html" in out


@pytest.mark.parametrize("status,fail_on,code", [
    (EQUIVALENT, None, 0), (WORSE, None, 0),
    (WORSE, "worse", 1), (DIFFERENT, "worse", 0), (BETTER, "worse", 0),
    (WORSE, "different", 1), (DIFFERENT, "different", 1), (EQUIVALENT, "different", 0),
    (BETTER, "different", 0),
])
def test_cli_fail_on(work, status, fail_on, code):
    extra = ["--fail-on", fail_on] if fail_on else []
    assert cli(work, status, *extra) == code


def test_cli_anchors_mismatch_exits_3(work):
    run_file = work / "mig" / "new-better" / "run-02.jsonl"
    lines = run_file.read_text(encoding="utf-8").splitlines()
    header = json.loads(lines[0])
    header["anchors_sha256"] = "f" * 64
    run_file.write_text("\n".join([json.dumps(header), *lines[1:]]) + "\n", encoding="utf-8")
    assert cli(work, BETTER) == 3
    assert not (work / "out" / "migration.json").exists()


def test_cli_reads_migrate_table_from_config(work):
    (work / "judgekeeper.toml").write_text("[gate]\nkappa_min = 0.6\n\n[migrate]\n"
                                           "max_changed_share = 0.5\n", encoding="utf-8")
    assert cli(work, DIFFERENT, "--fail-on", "different") == 0
    (work / "judgekeeper.toml").write_text("[migrate]\nmax_changed = 0.5\n", encoding="utf-8")
    assert cli(work, DIFFERENT) == 2


def test_cli_rebase_writes_baseline_and_audit(work, capsys):
    assert cli(work, BETTER, "--rebase") == 0
    baseline = json.loads((work / ".judgekeeper" / "baseline.json").read_text(encoding="utf-8"))
    assert baseline["fingerprint"]["model"] == "judge-new"
    assert baseline["schema_version"] == 2 and len(baseline["items"]) == 10
    audits = sorted((work / ".judgekeeper" / "migrations").glob("*.json"))
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    assert [p.name for p in audits] == [f"{today}-judge-old-to-judge-new.json"]
    audit = json.loads(audits[0].read_text(encoding="utf-8"))
    assert audit == json.loads((work / "out" / "migration.json").read_text(encoding="utf-8"))
    assert "baseline" in capsys.readouterr().out

    # a second rebase the same day keeps the first audit file
    assert cli(work, BETTER, "--rebase") == 0
    names = sorted(p.name for p in (work / ".judgekeeper" / "migrations").glob("*.json"))
    assert names == [f"{today}-judge-old-to-judge-new-2.json",
                     f"{today}-judge-old-to-judge-new.json"]


def test_after_rebase_gate_no_longer_reports_judge_changed(work):
    anchors = str(work / "mig" / "anchors.jsonl")
    assert main(["validate", anchors, str(work / "mig" / "old"), "--out", "old-report"]) == 0
    assert main(["baseline", "set", "old-report/report.json"]) == 0
    assert main(["validate", anchors, str(work / "mig" / "new-better"),
                 "--out", "new-report"]) == 0
    assert main(["gate", "new-report/report.json"]) == 5  # JUDGE_CHANGED
    assert "judgekeeper migrate" in json.loads(
        (work / "new-report" / "gate.json").read_text(encoding="utf-8"))["reason"]
    assert cli(work, BETTER, "--rebase") == 0
    assert main(["gate", "new-report/report.json"]) == 0
    assert json.loads((work / "new-report" / "gate.json").read_text(
        encoding="utf-8"))["status"] == "PASS"


def test_cli_rebase_custom_baseline_path(work):
    assert cli(work, BETTER, "--rebase", "--baseline", "b/base.json") == 0
    assert json.loads((work / "b" / "base.json").read_text(
        encoding="utf-8"))["fingerprint"]["model"] == "judge-new"
    assert len(list((work / "b" / "migrations").glob("*.json"))) == 1


def test_cli_usage_errors(work):
    assert main(["migrate", str(work / "mig" / "anchors.jsonl"), str(work / "mig" / "old")]) == 2
    assert cli(work, BETTER, "--fail-on", "sometimes") == 2
    assert main(["migrate", str(work / "mig" / "anchors.jsonl"), str(work / "mig" / "old"),
                 str(work / "nope"), "--out", str(work / "out")]) == 2


def test_migrate_judges_with_unknown_model(tmp_path, monkeypatch):
    """Callable judges carry no model name; migrate must still render, summarise and rebase."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.syspath_prepend(str(tmp_path))
    rows = ["id,input,output,human_label,notes"]
    for i in range(1, 9):
        rows.append(f"i{i},q{i},a{i},{'pass' if i <= 4 else 'fail'},")
    (tmp_path / "labels.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    (tmp_path / "loose_judge.py").write_text(
        "def judge(item):\n    return 'pass' if item['id'] != 'i8' else 'fail'\n", encoding="utf-8")
    (tmp_path / "exact_judge.py").write_text(
        "def judge(item):\n    return 'pass' if int(item['id'][1:]) <= 4 else 'fail'\n",
            encoding="utf-8")
    assert main(["import-labels", "labels.csv", "-o", "anchors.jsonl"]) == 0
    for name in ("loose", "exact"):
        assert main(["judge", "anchors.jsonl", "--callable", f"{name}_judge:judge",
                     "--runs", "3", "--out", f"runs/{name}"]) == 0

    assert main(["migrate", "anchors.jsonl", "runs/loose", "runs/exact",
                 "--out", "out", "--rebase"]) == 0
    m = json.loads((tmp_path / "out" / "migration.json").read_text(encoding="utf-8"))
    assert m["status"] == BETTER
    assert m["fingerprints"]["old"]["model"] is None
    html = (tmp_path / "out" / "migration.html").read_text(encoding="utf-8")
    assert "None" not in html.split("<h1>", 1)[1].split("</h1>", 1)[0]
    assert "model unknown" in html
    audits = list((tmp_path / ".judgekeeper" / "migrations").glob("*.json"))
    assert len(audits) == 1 and "unknown" in audits[0].name
