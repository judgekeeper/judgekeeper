"""The real-data check (scripts/real_data_check.py) in small: its pools, one design replayed
on a tiny pool, the download it refuses, and the committed report it wrote.

Nothing here touches the network: the pools are built from tiny inline rows, and the download
is a stand-in.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "real_data_check.py"
OUT = ROOT / "docs" / "examples" / "real-data-check"
# Only data whose licence allows reuse.
DATASET_NAMES = ("LLMBar", "MT-Bench human judgments", "LLMJudge benchmark")


def _module():
    spec = importlib.util.spec_from_file_location("real_data_check", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def rdc():
    return _module()


@pytest.fixture(scope="module")
def report():
    return json.loads((OUT / "report.json").read_text(encoding="utf-8"))


# The pools

def _row(q, a, b, winner, turn=1):
    return {"question_id": q, "model_a": a, "model_b": b, "winner": winner, "turn": turn}


def test_mtbench_asks_whether_model_b_is_better_in_the_judges_order(rdc):
    gpt4 = [_row(1, "x", "y", "model_b"), _row(2, "x", "y", "model_a")]
    human = [_row(1, "x", "y", "model_b"),
             _row(2, "y", "x", "model_a")]  # the other order: y won, which is model_b for GPT-4
    assert rdc.mtbench_pool(gpt4, human) == [(True, True), (False, True)]


def test_mtbench_ties_and_split_votes_are_not_a_pass_and_nothing_is_dropped(rdc):
    gpt4 = [_row(1, "x", "y", "tie"), _row(2, "x", "y", "tie (inconsistent)"),
            _row(3, "x", "y", "model_b"), _row(4, "x", "y", "model_b"),
            _row(5, "x", "y", "model_b")]
    human = [_row(1, "x", "y", "model_b"),
             _row(2, "x", "y", "tie"),
             _row(3, "x", "y", "model_b"), _row(3, "y", "x", "model_b"),  # one each: split
             _row(4, "x", "y", "tie"), _row(4, "x", "y", "model_b"),  # 1 of 2: not more than half
             _row(5, "x", "y", "model_b"), _row(5, "y", "x", "model_a"), _row(5, "x", "y", "tie")]
    assert rdc.mtbench_pool(gpt4, human) == [(False, True), (False, False), (True, False),
                                             (True, False), (True, True)]


def test_mtbench_keeps_only_the_items_people_voted_on_and_matches_the_turn(rdc):
    gpt4 = [_row(1, "x", "y", "model_b", turn=1), _row(1, "x", "y", "model_b", turn=2),
            _row(2, "x", "z", "model_b")]
    human = [_row(1, "x", "y", "model_a", turn=2), _row(9, "x", "y", "model_b")]
    assert rdc.mtbench_pool(gpt4, human) == [(True, False)]


def test_llmjudge_passes_grade_two_and_up_on_both_sides(rdc):
    qrels = "q1 0 p1 3\nq1 0 p2 2\nq2 0 p1 1\nq2 0 p3 0\n"
    run = "q2 0 p3 2\nq1 0 p1 1\nq1 0 p2 3.0\nq2 0 p1 0\n"
    # sorted by (query, passage): q1/p1, q1/p2, q2/p1, q2/p3
    assert rdc.llmjudge_pool(qrels, run) == [(False, True), (True, True), (False, False),
                                             (True, False)]


def test_llmjudge_refuses_a_run_that_graded_other_passages(rdc):
    with pytest.raises(ValueError, match="same passages"):
        rdc.llmjudge_pool("q1 0 p1 3\n", "q1 0 p2 3\n")


def test_llmbar_uses_the_first_saved_run_and_the_gold_label(rdc):
    report = {"anchors": {"n_items": 3}, "items": [
        {"human": "A", "verdicts": ["A", "B", "B"]},
        {"human": "B", "verdicts": ["A", "A", "A"]},
        {"human": "A", "verdicts": ["B", "A", "A"]}]}
    assert rdc.llmbar_pool(report) == [(True, True), (True, False), (False, True)]
    report["anchors"]["n_items"] = 4
    with pytest.raises(ValueError):
        rdc.llmbar_pool(report)


def test_the_truth_counts_every_item(rdc):
    pool = [(True, True)] * 6 + [(True, False)] * 2 + [(False, True)] * 3 + [(False, False)] * 9
    t = rdc.truth(pool)
    assert (t["n"], t["tp"], t["fp"], t["fn"], t["tn"]) == (20, 6, 2, 3, 9)
    assert t["tpr"] == pytest.approx(6 / 9)
    assert t["tnr"] == pytest.approx(9 / 11)
    assert t["real_pass_rate"] == pytest.approx(9 / 20)
    assert t["judge_pass_rate"] == pytest.approx(8 / 20)
    chance = 0.4 * 0.45 + 0.6 * 0.55
    assert t["kappa"] == pytest.approx((15 / 20 - chance) / (1 - chance))


# One design, replayed

POOL = [(True, True)] * 8 + [(True, False)] * 2 + [(False, True)] * 3 + [(False, False)] * 7


def test_a_design_that_labels_whole_groups_gives_the_same_counts_every_time(rdc):
    """10 of 10 in each group: every check sees the whole pool, so its ranges are always the
    same, and each range holds the truth in every check or in none."""
    from judgekeeper import weighted

    out = rdc.run(POOL, "fixed", 10, checks=7, seed=1)
    r = weighted.corrected(10, 10, 10, 8, 10, 3)
    t = rdc.truth(POOL)
    assert out["first_check"]["labeled"] == {"pass": {"labeled": 10, "correct": 8},
                                             "fail": {"labeled": 10, "correct": 3}}
    assert out["labels"] == {"mean": 20, "min": 20, "max": 20}
    for key in rdc.METRICS:
        lo, hi = r[f"{key}_interval"]
        held = lo <= t[key] <= hi
        assert out[key]["held"] == (7 if held else 0), key
        assert out[key]["known"] == 7 and out[key]["unknown"] == 0
        assert out[key]["coverage"] == (1.0 if held else 0.0)
        assert out[key]["width_mean"] == pytest.approx(hi - lo)
        assert out[key]["abs_error_median"] == pytest.approx(abs(r[key] - t[key]))
        assert out["first_check"][key] == {"value": r[key], "range": [lo, hi]}
    # Without the correction: of the 11 labeled answers people passed, the judge passed 8.
    assert out["plain"] == {"tpr": pytest.approx(8 / 11), "tnr": pytest.approx(7 / 9)}


def test_coverage_counts_the_checks_whose_range_holds_the_truth(rdc):
    """A stand-in for the maths: the TPR range holds the truth only when all 5 labeled judge
    passes were Correct, the TNR range never, and the real pass rate is unknown."""
    def ranges(n_pool_pass, n_pool_fail, n_p, c_p, n_f, c_f):
        assert (n_pool_pass, n_pool_fail) == (10, 10)
        hit = [0.0, 1.0] if c_p == n_p else [0.0, 0.1]
        return {"tpr": 0.5, "tpr_interval": hit, "tnr": 0.5, "tnr_interval": [0.0, 0.1],
                "real_pass_rate": None, "real_pass_rate_interval": [None, None], "kappa": None}

    import random

    out = rdc.run(POOL, "fixed", 5, checks=200, seed=3, corrected=ranges)
    rng, passes, fails = random.Random(3), [True] * 8 + [False] * 2, [True] * 3 + [False] * 7
    all_correct = sum(rdc.fixed_draw(rng, passes, fails, 5)[1] == 5 for _ in range(200))
    assert out["tpr"]["held"] == all_correct and out["tpr"]["known"] == 200
    assert out["tpr"]["coverage"] == all_correct / 200
    # By hand: the 8 Correct of 10 fill all 5 places in C(8,5)/C(10,5) = 56/252 of draws.
    assert 0.12 < all_correct / 200 < 0.33
    assert out["tnr"]["held"] == 0 and out["tnr"]["coverage"] == 0.0
    assert out["real_pass_rate"] == {"held": 0, "known": 0, "unknown": 200, "coverage": None,
                                     "width_mean": None, "abs_error_median": None}


def test_starts_rule_labels_blocks_of_five_until_enough_correct_and_wrong(rdc):
    import random

    perfect = [True] * 40, [False] * 40  # the human label of each judge pass, each judge fail
    assert rdc.start_rule_draw(random.Random(1), *perfect) == (25, 25, 25, 0)
    # A group that runs out: the other goes on alone, and an empty pool stops it.
    assert rdc.start_rule_draw(random.Random(1), [True] * 7, [False] * 40) == (7, 7, 40, 0)
    passes, fails = [True] * 30 + [False] * 30, [True] * 10 + [False] * 50
    n_p, c_p, n_f, c_f = rdc.start_rule_draw(random.Random(2), passes, fails)
    assert n_p == n_f and n_p % 5 == 0
    correct, wrong = c_p + c_f, n_p + n_f - c_p - c_f
    assert min(correct, wrong) >= 25
    assert rdc.BLOCK == 5 and rdc.TARGET == 25


# The download

def test_a_download_with_the_wrong_hash_is_refused_and_not_kept(rdc, tmp_path):
    source = {"file": "qrels.txt", "url": "https://example.invalid/qrels.txt",
              "sha256": hashlib.sha256(b"right").hexdigest()}
    with pytest.raises(rdc.HashMismatch, match="qrels.txt"):
        rdc.fetch(source, tmp_path, download=lambda url: b"wrong")
    assert list(tmp_path.iterdir()) == []


def test_a_good_download_is_kept_and_then_read_from_the_cache(rdc, tmp_path):
    source = {"file": "a/run.txt", "url": "https://example.invalid/run.txt",
              "sha256": hashlib.sha256(b"right").hexdigest()}
    calls = []

    def download(url):
        calls.append(url)
        return b"right"

    path = rdc.fetch(source, tmp_path, download=download)
    assert path.read_bytes() == b"right" and path == tmp_path / "a" / "run.txt"
    assert rdc.fetch(source, tmp_path, download=download) == path
    assert calls == [source["url"]]
    path.write_bytes(b"changed")  # a cached file that no longer matches is fetched again
    rdc.fetch(source, tmp_path, download=download)
    assert path.read_bytes() == b"right" and len(calls) == 2


def test_the_cache_is_never_inside_the_repository(rdc, tmp_path):
    with pytest.raises(SystemExit):
        rdc.cache_folder(str(ROOT / "docs"))
    assert rdc.cache_folder(str(tmp_path)) == tmp_path
    assert ROOT not in rdc.cache_folder(None).resolve().parents


def test_the_sources_are_pinned_hashed_and_licensed(rdc):
    files = [s for d in rdc.DATASETS.values() for s in d["files"]]
    assert len(files) == 6
    for source in files:
        assert re.fullmatch(r"[0-9a-f]{64}", source["sha256"]), source
        assert re.search(r"/[0-9a-f]{40}/", source["url"]), source  # a fixed revision
    for dataset in rdc.DATASETS.values():
        assert dataset["licence"] in ("MIT", "CC-BY-4.0"), dataset
        assert dataset["attribution"]
    assert sorted(DATASET_NAMES) == sorted(d["name"] for d in rdc.DATASETS.values())
    assert {p["dataset"] for p in rdc.POOLS.values()} == set(rdc.DATASETS)


def test_the_settings_are_the_fixed_ones(rdc):
    assert rdc.SEED == 20261009 and rdc.CHECKS == 1000 and rdc.SIZES == (25, 30)
    assert list(rdc.POOLS) == ["llmbar-haiku", "mtbench-gpt4", "llmjudge-RMITIR-GPT4o",
                               "llmjudge-willia-umbrela1", "llmjudge-NISTRetrieval-instruct0"]


# The committed report

def test_the_report_folder_holds_only_the_report(report):
    assert sorted(p.name for p in OUT.iterdir()) == ["report.json", "report.md"]


def test_the_committed_report_md_is_what_the_script_writes_from_report_json(rdc, report):
    assert (OUT / "report.md").read_text(encoding="utf-8") == rdc.markdown(report)
    assert rdc.text_of(report) == (OUT / "report.json").read_text(encoding="utf-8")


def test_the_report_carries_the_settings_the_data_and_the_licences(rdc, report):
    from judgekeeper import weighted

    s = report["settings"]
    assert s["seed"] == rdc.SEED and s["checks"] == rdc.CHECKS
    assert s["weighted"] == {"level": weighted.LEVEL, "draws": weighted.DRAWS,
                             "seed": weighted.SEED}
    assert report["data"] == rdc.DATASETS
    assert list(report["pools"]) == list(rdc.POOLS)
    llmbar = json.loads((ROOT / "docs/examples/llmbar-haiku/report.json").read_text(
        encoding="utf-8"))
    assert report["pools"]["llmbar-haiku"]["truth"] == rdc.rounded(rdc.truth(rdc.llmbar_pool(llmbar)))


def test_the_summary_is_worked_out_from_the_pools(rdc, report):
    assert report["summary"] == rdc.summarise(report["pools"])
    for pool in report["pools"].values():
        assert list(pool["designs"]) == ["25+25", "30+30", "start_rule"]
        for design in pool["designs"].values():
            for key in rdc.METRICS:
                assert design[key]["known"] + design[key]["unknown"] == rdc.CHECKS


def _flat(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


def test_the_real_data_figures_in_the_docs_come_from_the_committed_report(report):
    def pct(x):
        return f"{x * 100:.1f}"

    def two(x):
        return f"{x:.2f}"

    s = report["summary"]["25+25"]
    c = s["tpr_tnr"]
    result = (f"{s['judges']} real judges from {s['datasets']} public datasets",
              (f"in {pct(c['mean'])} checks in 100 on average (lowest {pct(c['lowest'])}, "
               f"highest {pct(c['highest'])}), over {report['settings']['checks']:,} checks "
               "per judge"))
    mt = report["pools"]["mtbench-gpt4"]
    first, t = mt["designs"]["25+25"]["first_check"], mt["truth"]
    example = (f"TPR {two(first['tpr']['value'])} (range {two(first['tpr']['range'][0])} to "
               f"{two(first['tpr']['range'][1])}), and the value from all {t['n']:,} human "
               f"labels is {two(t['tpr'])}; TNR {two(first['tnr']['value'])} (range "
               f"{two(first['tnr']['range'][0])} to {two(first['tnr']['range'][1])}), and "
               f"from all labels {two(t['tnr'])}")
    grid = json.loads((ROOT / "docs/examples/coverage/coverage.json").read_text(
        encoding="utf-8"))
    level = grid["corrected"]["levels"][str(grid["corrected"]["chosen_level"])]
    simulated = (f"at least {pct(level['min_cell'])} times in 100 in every tested case, and "
                 f"{pct(level['mean'])} on average")
    llmbar = json.loads((ROOT / "docs/examples/llmbar-haiku/report.json").read_text(
        encoding="utf-8"))
    h = llmbar["headline"]
    real_judge = (f"Claude Haiku 4.5 on LLMBar, {llmbar['anchors']['n_items']} items: TPR "
                  f"{two(h['tpr_mean'])}, TNR {two(h['tnr_mean'])}, kappa")
    readme = _flat(ROOT / "README.md")
    for figure in (*result, example, simulated, real_judge, two(h["kappa_mean"]),
                   f"with {s['labels_mean']['lowest']} human labels per check"):
        assert figure in readme, figure
    for path in (ROOT / "docs" / "reference.md", ROOT / "CHANGELOG.md"):
        text = _flat(path)
        for figure in result:
            assert figure in text, (path.name, figure)
    assert "Tested on Python 3.11 to 3.14 on Linux, and on Windows." in readme
    assert "on Python 3.11 to 3.14 on Linux, and on Windows." in _flat(
        ROOT / "website" / "learn.html")
