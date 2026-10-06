"""`attribute`: did scores move because the system changed or because the judge changed?

Reports are built with `validate` from the fixtures in tests/fixtures/migrate/ (see
make_fixtures.py). The baseline is the old judge, pattern X (wrong on i05 and i10), kappa .6 in
every run. Each current report is the same declared judge re-run a week later:

    old-rerun         X X X                     identical verdicts
    old-noisy         X+i05, X+i05, X           i05's majority moves, but i05 is not stable
    old-drifted       N N N                     i04 i05 i09 i10 move, fingerprint identical
    old-new-snapshot  H H H                     i05 i10 move, served snapshot changed
"""

import json
import shutil
from pathlib import Path

import pytest

from judgekeeper.attribute import (
    JUDGE_DRIFT,
    STABLE,
    SYSTEM_CHANGE,
    AttributeConfig,
    attribute,
    render_markdown,
)
from judgekeeper.cli import main

MIG = Path(__file__).parent / "fixtures" / "migrate"
NAMES = ("old", "old-rerun", "old-noisy", "old-drifted", "old-new-snapshot")


@pytest.fixture(scope="module")
def reports(tmp_path_factory) -> dict[str, Path]:
    root = tmp_path_factory.mktemp("reports")
    out = {}
    for name in NAMES:
        assert main(["validate", str(MIG / "anchors.jsonl"), str(MIG / name),
                     "--out", str(root / name)]) == 0
        out[name] = root / name / "report.json"
    return out


def load(reports, name) -> dict:
    return json.loads(reports[name].read_text(encoding="utf-8"))


def attr(reports, name, **kw) -> dict:
    return attribute(load(reports, name), load(reports, "old"), AttributeConfig(), **kw)


# --- decisions --------------------------------------------------------------------------------


def test_stable(reports):
    res = attr(reports, "old-rerun")
    assert res["status"] == STABLE and res["exit_code"] == 0
    a = res["anchor_set"]
    assert (a["n_items"], a["n_moved"], a["moved_share"]) == (10, 0, 0.0)
    assert a["kappa_delta"] == pytest.approx(0.0) and a["noise_band"] == pytest.approx(0.02)
    assert res["judge"]["declared_changes"] == []
    assert res["judge"]["snapshot_changed"] is False


def test_a_flipping_item_does_not_count_as_moved(reports):
    res = attr(reports, "old-noisy")
    # i05's majority moved B -> A, but the current judge said A, A, B: not stable
    a = res["anchor_set"]
    assert a["n_moved"] == 0 and a["n_moved_within_noise"] == 1
    # kappa .8 .8 .6 -> mean .7333, delta +.1333; band = current spread .2 -> inside
    assert a["kappa_delta"] == pytest.approx(0.4 / 3)
    assert a["noise_band"] == pytest.approx(0.2)
    assert res["status"] == STABLE


def test_judge_drift_with_identical_fingerprint(reports):
    res = attr(reports, "old-drifted")
    assert res["status"] == JUDGE_DRIFT and res["exit_code"] == 6
    a = res["anchor_set"]
    # X vs N: i04 i05 i09 i10 move, all unanimous in both -> 4/10
    assert a["n_moved"] == 4 and a["moved_share"] == pytest.approx(0.4)
    assert [m["id"] for m in a["moved_items"]] == ["i04", "i05", "i09", "i10"]
    assert a["moved_items"][0] == {"id": "i04", "slice": "hard", "human": "A",
                                   "baseline": "A", "current": "B"}
    assert a["kappa_delta"] == pytest.approx(0.0)  # as good as before, on different items
    j = res["judge"]
    assert j["declared_changes"] == [] and j["snapshot_changed"] is False
    assert "silent" in res["reason"]


def test_judge_drift_with_changed_snapshot(reports):
    res = attr(reports, "old-new-snapshot")
    assert res["status"] == JUDGE_DRIFT
    a = res["anchor_set"]
    # X vs H: i05 and i10 move -> .2; kappa .6 -> 1.0, delta .4 outside .02
    assert a["n_moved"] == 2 and a["moved_share"] == pytest.approx(0.2)
    assert a["kappa_delta"] == pytest.approx(0.4)
    j = res["judge"]
    assert j["snapshot_changed"] is True
    assert j["snapshots"] == {"baseline": ["judge-old"], "current": ["judge-old-2027"]}
    assert [c["field"] for c in j["declared_changes"]] == ["snapshot"]
    assert "judge-old-2027" in res["reason"]


def test_system_change(reports):
    res = attr(reports, "old-rerun", app_score_before=0.70, app_score_after=0.60)
    assert res["status"] == SYSTEM_CHANGE and res["exit_code"] == 7
    app = res["app_scores"]
    # "prefers A" rate is .5 in every run of both reports: spread 0 -> band = min_band .02
    assert app["delta"] == pytest.approx(-0.10)
    assert app["noise_band"] == pytest.approx(0.02)


def test_app_score_change_inside_band_is_stable(reports):
    res = attr(reports, "old-rerun", app_score_before=0.70, app_score_after=0.71)
    assert res["status"] == STABLE


def test_app_score_band_uses_the_judges_pass_rate_noise(reports):
    # old-noisy: "prefers A" rate .6, .6, .5 -> spread .1, so a .08 move is noise
    res = attr(reports, "old-noisy", app_score_before=0.70, app_score_after=0.62)
    assert res["app_scores"]["noise_band"] == pytest.approx(0.1)
    assert res["status"] == STABLE


def test_drift_wins_over_app_scores(reports):
    res = attr(reports, "old-drifted", app_score_before=0.70, app_score_after=0.50)
    assert res["status"] == JUDGE_DRIFT
    assert "cannot be attributed" in res["reason"]


def test_config_threshold(reports):
    res = attribute(load(reports, "old-drifted"), load(reports, "old"),
                    AttributeConfig(max_moved_share=0.5))
    assert res["status"] == STABLE


def test_markdown(reports):
    md = render_markdown(attr(reports, "old-drifted"))
    assert md.startswith("## judgekeeper attribute: JUDGE_DRIFT\n")
    assert "| i04 | hard | A | A | B |" in md
    assert "accuracy" not in md.lower()


# --- CLI --------------------------------------------------------------------------------------


@pytest.fixture
def work(tmp_path, monkeypatch, reports):
    monkeypatch.chdir(tmp_path)
    for name, path in reports.items():
        (tmp_path / name).mkdir()
        shutil.copy(path, tmp_path / name / "report.json")
    return tmp_path


def cli(name, *extra):
    return main(["attribute", f"{name}/report.json", "--baseline", "old/report.json", *extra])


@pytest.mark.parametrize("name,extra,code", [
    ("old-rerun", [], 0),
    ("old-drifted", [], 6),
    ("old-new-snapshot", [], 6),
    ("old-rerun", ["--app-score-before", "0.7", "--app-score-after", "0.6"], 7),
])
def test_cli_exit_codes(work, name, extra, code):
    assert cli(name, *extra) == code
    res = json.loads((work / name / "attribution.json").read_text(encoding="utf-8"))
    assert res["exit_code"] == code
    assert (work / name / "attribution.md").read_text(
        encoding="utf-8").startswith("## judgekeeper attribute")


def test_cli_default_baseline_and_out(work, capsys):
    assert main(["attribute", "old-rerun/report.json"]) == 2  # no baseline yet
    assert main(["baseline", "set", "old/report.json"]) == 0
    assert main(["attribute", "old-drifted/report.json", "--out", "o"]) == 6
    assert (work / "o" / "attribution.json").exists()
    assert "JUDGE_DRIFT" in capsys.readouterr().out


def test_cli_baseline_without_items_is_usage_error(work, capsys):
    old = json.loads((work / "old" / "report.json").read_text(encoding="utf-8"))
    del old["items"]
    (work / "old" / "report.json").write_text(json.dumps(old), encoding="utf-8")
    assert cli("old-rerun") == 2
    assert "regenerate" in capsys.readouterr().err


def test_cli_current_without_items_is_usage_error(work):
    cur = json.loads((work / "old-rerun" / "report.json").read_text(encoding="utf-8"))
    del cur["items"]
    (work / "old-rerun" / "report.json").write_text(json.dumps(cur), encoding="utf-8")
    assert cli("old-rerun") == 2


def test_cli_anchors_mismatch_exits_3(work):
    cur = json.loads((work / "old-rerun" / "report.json").read_text(encoding="utf-8"))
    cur["anchors"]["sha256"] = "f" * 64
    (work / "old-rerun" / "report.json").write_text(json.dumps(cur), encoding="utf-8")
    assert cli("old-rerun") == 3


@pytest.mark.parametrize("extra", [
    ["--app-score-before", "0.7"],
    ["--app-score-after", "0.7"],
    ["--app-score-before", "70", "--app-score-after", "60"],
])
def test_cli_app_score_usage_errors(work, extra):
    assert cli("old-rerun", *extra) == 2


def test_cli_reads_attribute_table_from_config(work):
    (work / "judgekeeper.toml").write_text("[attribute]\nmax_moved_share = 0.5\n")
    assert cli("old-drifted") == 0


# --- markdown escaping (security audit item 4) ------------------------------------------------


def test_markdown_escapes_table_cells(reports):
    res = attr(reports, "old-drifted")
    res["anchor_set"]["moved_items"][0]["id"] = "i04|x <b>y</b>"
    res["judge"]["declared_changes"] = [{"field": "model", "baseline": "a|b", "now": "`c`"}]
    md = render_markdown(res)
    assert "i04|x" not in md
    assert "| i04\\|x &lt;b&gt;y&lt;/b&gt; | hard |" in md
    assert "| model | a\\|b | \\`c\\` |" in md


def test_markdown_escapes_snapshot_names_in_the_reason(reports):
    """Security review, finding 6: the served snapshot comes from the report file and is
    quoted in the reason, a paragraph of attribution.md."""
    current = load(reports, "old-new-snapshot")
    hostile = "snap |\n\n# INJECTED HEADING\n\n[click](https://evil.example/x) <b>"
    current["snapshots_seen"] = [hostile]
    current["fingerprint"]["snapshot"] = hostile
    res = attribute(current, load(reports, "old"), AttributeConfig())
    assert hostile in res["reason"]  # the JSON field is the plain text, unchanged
    md = render_markdown(res)
    assert "# INJECTED HEADING" not in [line.strip() for line in md.splitlines()]
    assert "[click](" not in md and "<b>" not in md
    assert "\\[click\\](https://evil.example/x) &lt;b&gt;" in md
    assert "run `judgekeeper migrate` and rebase" in md  # our own code span is kept
