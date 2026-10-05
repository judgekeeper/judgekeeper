"""Gate decisions against hand-built report.json fixtures in tests/fixtures/gate/.

Baseline: kappa per run .78/.80/.82 (mean .80, spread .04), TPR .90-.92, TNR .88-.90,
AB/BA disagreement .05, 4% of items flipped between runs.
"""

import copy
import json
from pathlib import Path

import pytest

from judgekeeper.gate import (
    ANCHORS_CHANGED,
    FAIL,
    FLAKY,
    JUDGE_CHANGED,
    PASS,
    GateConfig,
    GateError,
    evaluate,
    exit_code,
    load_config,
    load_report,
    render_markdown,
)

GATE = Path(__file__).parent / "fixtures" / "gate"


def rep(name: str) -> dict:
    return load_report(GATE / f"{name}.json")


@pytest.fixture
def baseline():
    return rep("baseline")


# --- decisions -----------------------------------------------------------------------------


def test_pass_against_baseline(baseline):
    res = evaluate(rep("pass"), baseline)
    assert res["status"] == PASS
    assert all(c["passed"] for c in res["checks"])


def test_pass_without_baseline_uses_absolute_thresholds_only():
    res = evaluate(rep("pass"))
    assert res["status"] == PASS
    assert {c["kind"] for c in res["checks"]} == {"absolute"}


def test_judge_passes_everything_fails():
    res = evaluate(rep("passes-everything"))
    assert res["status"] == FAIL
    failed = {c["metric"] for c in res["checks"] if not c["passed"]}
    assert failed == {"kappa", "tnr"}
    # single-output report: no AB/BA check
    assert "ab_ba" not in {c["metric"] for c in res["checks"]}


def test_kappa_drop_inside_noise_band_passes(baseline):
    res = evaluate(rep("kappa-drop-inside-band"), baseline)
    assert res["status"] == PASS
    kappa = next(m for m in res["metrics"] if m["metric"] == "kappa")
    assert kappa["baseline"] == pytest.approx(0.80)
    assert kappa["now"] == pytest.approx(0.77)
    assert kappa["delta"] == pytest.approx(-0.03)
    assert kappa["noise_band"] == pytest.approx(0.04)


def test_kappa_drop_outside_noise_band_fails(baseline):
    res = evaluate(rep("kappa-drop-outside-band"), baseline)
    assert res["status"] == FAIL
    failed = [c for c in res["checks"] if not c["passed"]]
    assert [(c["kind"], c["metric"]) for c in failed] == [("relative", "kappa")]
    assert failed[0]["threshold"] == pytest.approx(0.76)


def test_mean_fails_but_best_run_passes_is_flaky(baseline):
    res = evaluate(rep("best-run-passes"), baseline)
    assert res["status"] == FLAKY
    assert "use the majority of more runs" in res["reason"]
    failed = [c for c in res["checks"] if not c["passed"]]
    assert failed and all(c["passed_best"] for c in failed)


def test_best_run_also_fails_is_fail():
    r = rep("best-run-passes")
    r["headline"]["kappa_max"] = 0.58
    r["runs"][2]["kappa"] = 0.58
    assert evaluate(r)["status"] == FAIL


def test_high_flip_share_turns_fail_into_flaky():
    r = rep("passes-everything")
    r["noise_floor"]["items_flipped_fraction"] = 0.2
    res = evaluate(r)
    assert res["status"] == FLAKY
    assert "use the majority of more runs" in res["reason"]


def test_high_flip_share_does_not_fail_a_pass():
    r = rep("pass")
    r["noise_floor"]["items_flipped_fraction"] = 0.2
    res = evaluate(r)
    assert res["status"] == PASS
    assert any("flipped" in w for w in res["warnings"])


def test_fewer_than_three_runs_is_flaky(baseline):
    res = evaluate(rep("two-runs"), baseline)
    assert res["status"] == FLAKY
    assert "noise floor unknown" in res["reason"]


def test_changed_snapshot_is_judge_changed(baseline):
    res = evaluate(rep("snapshot-changed"), baseline)
    assert res["status"] == JUDGE_CHANGED
    assert res["judge_changes"] == [{
        "field": "snapshot",
        "baseline": "claude-haiku-4-5-20251001",
        "now": "claude-haiku-4-5-20260101",
    }]
    assert res["checks"] == []


@pytest.mark.parametrize("field,value", [
    ("provider", "openai"), ("model", "gpt-x"), ("prompt_hash", "2" * 64),
    ("rubric_version", "pairwise-v2"), ("temperature", 0.7),
])
def test_any_identity_field_change_is_judge_changed(baseline, field, value):
    r = rep("pass")
    r["fingerprint"][field] = value
    res = evaluate(r, baseline)
    assert res["status"] == JUDGE_CHANGED
    assert [c["field"] for c in res["judge_changes"]] == [field]


def test_created_at_is_not_a_judge_change(baseline):
    r = rep("pass")
    r["fingerprint"]["created_at"] = "2027-01-01T00:00:00Z"
    assert evaluate(r, baseline)["status"] == PASS


def test_allow_judge_change_continues_with_absolute_only(baseline):
    res = evaluate(rep("snapshot-changed"), baseline, allow_judge_change=True)
    assert res["status"] == PASS
    assert {c["kind"] for c in res["checks"]} == {"absolute"}
    assert any("snapshot" in w for w in res["warnings"])
    assert res["judge_changes"]


def test_changed_anchors(baseline):
    res = evaluate(rep("anchors-changed"), baseline)
    assert res["status"] == ANCHORS_CHANGED
    assert res["checks"] == []


def test_anchors_checked_before_judge(baseline):
    r = rep("anchors-changed")
    r["fingerprint"]["snapshot"] = "other"
    assert evaluate(r, baseline)["status"] == ANCHORS_CHANGED


def test_run_count_checked_before_thresholds():
    r = rep("passes-everything")
    r["n_runs"] = 1
    r["runs"] = r["runs"][:1]
    assert evaluate(r)["status"] == FLAKY


def test_ab_ba_disagreement_threshold():
    r = rep("pass")
    r["position_bias"]["inconsistency_rate"] = 0.2
    for row in r["position_bias"]["per_run"]:
        row["inconsistency_rate"] = 0.2
    res = evaluate(r)
    assert res["status"] == FAIL
    assert [c["metric"] for c in res["checks"] if not c["passed"]] == ["ab_ba"]


def test_tpr_relative_uses_its_own_spread(baseline):
    r = rep("pass")
    # baseline TPR mean .91, spread .02; report spread .02 -> band .02, floor .89
    for row, v in zip(r["runs"], [0.86, 0.87, 0.88]):
        row["tpr"] = v
    r["headline"]["tpr_mean"] = 0.87
    res = evaluate(r, baseline)
    assert res["status"] == FAIL
    failed = [c for c in res["checks"] if not c["passed"]]
    assert [(c["kind"], c["metric"]) for c in failed] == [("relative", "tpr")]
    assert failed[0]["threshold"] == pytest.approx(0.89)


def test_min_band_applies_when_runs_agree(baseline):
    b = copy.deepcopy(baseline)
    r = rep("pass")
    for x in (b, r):
        for row in x["runs"]:
            row["kappa"] = x["headline"]["kappa_mean"] = 0.80
        x["headline"]["kappa_min"] = x["headline"]["kappa_max"] = 0.80
    for row in r["runs"]:
        row["kappa"] = 0.785
    r["headline"].update(kappa_mean=0.785, kappa_min=0.785, kappa_max=0.785)
    res = evaluate(r, b)
    kappa = next(m for m in res["metrics"] if m["metric"] == "kappa")
    assert kappa["noise_band"] == pytest.approx(0.02)
    assert res["status"] == PASS


def test_missing_kappa_is_a_breach():
    r = rep("pass")
    r["headline"].update(kappa_mean=None, kappa_min=None, kappa_max=None)
    for row in r["runs"]:
        row["kappa"] = None
    assert evaluate(r)["status"] == FAIL


def test_config_thresholds_apply():
    cfg = GateConfig(kappa_min=0.9)
    assert evaluate(rep("pass"), config=cfg)["status"] == FAIL


# --- exit codes ----------------------------------------------------------------------------


@pytest.mark.parametrize("status,code", [
    (PASS, 0), (FAIL, 1), (ANCHORS_CHANGED, 3), (FLAKY, 4), (JUDGE_CHANGED, 5),
])
def test_exit_codes(status, code):
    assert exit_code(status) == code


@pytest.mark.parametrize("status,flaky_as,code", [
    (FLAKY, "pass", 0), (FLAKY, "fail", 1),
    (PASS, "fail", 0), (FAIL, "pass", 1), (JUDGE_CHANGED, "pass", 5),
])
def test_flaky_as(status, flaky_as, code):
    assert exit_code(status, flaky_as) == code


# --- config --------------------------------------------------------------------------------


def test_config_defaults():
    cfg = GateConfig()
    assert (cfg.kappa_min, cfg.tpr_min, cfg.tnr_min) == (0.6, 0.8, 0.8)
    assert cfg.ab_ba_disagreement_max == 0.10
    assert cfg.min_band == 0.02
    assert cfg.flip_rate_max == 0.10


def test_config_file_overrides(tmp_path):
    p = tmp_path / "judgekeeper.toml"
    p.write_text("[gate]\nkappa_min = 0.7\nmin_band = 0.05\n")
    cfg = load_config(p)
    assert cfg.kappa_min == 0.7
    assert cfg.min_band == 0.05
    assert cfg.tpr_min == 0.8


def test_config_without_gate_table_is_defaults(tmp_path):
    p = tmp_path / "judgekeeper.toml"
    p.write_text("")
    assert load_config(p) == GateConfig()


@pytest.mark.parametrize("text,needle", [
    ("[gate]\nkapa_min = 0.7\n", "kapa_min"),
    ("[gaet]\nkappa_min = 0.7\n", "gaet"),
    ("[gate]\nkappa_min = 'high'\n", "kappa_min"),
    ("[gate]\nkappa_min = true\n", "kappa_min"),
    ("[gate]\ntpr_min = 1.5\n", "tpr_min"),
    ("[gate\n", "TOML"),
])
def test_config_errors(tmp_path, text, needle):
    p = tmp_path / "judgekeeper.toml"
    p.write_text(text)
    with pytest.raises(GateError, match=needle):
        load_config(p)


def test_config_missing_file(tmp_path):
    with pytest.raises(GateError):
        load_config(tmp_path / "nope.toml")


def test_load_report_rejects_non_reports(tmp_path):
    p = tmp_path / "r.json"
    p.write_text(json.dumps({"hello": 1}))
    with pytest.raises(GateError, match="report"):
        load_report(p)
    p.write_text("{not json")
    with pytest.raises(GateError):
        load_report(p)


# --- markdown ------------------------------------------------------------------------------


def test_markdown_pass(baseline):
    md = render_markdown(evaluate(rep("kappa-drop-inside-band"), baseline))
    assert md.startswith("## judgekeeper gate: PASS\n")
    assert "| metric | baseline | now | delta | noise band |" in md
    assert "| kappa | 0.80 | 0.77 | -0.03 | 0.04 |" in md
    assert "| TPR | 0.91 | 0.91 | +0.00 | 0.02 |" in md
    assert "claude-haiku-4-5-20251001" in md
    assert "pairwise-v1" in md
    assert "accuracy" not in md.lower()


def test_markdown_fail(baseline):
    md = render_markdown(evaluate(rep("kappa-drop-outside-band"), baseline))
    assert md.startswith("## judgekeeper gate: FAIL\n")
    lines = md.splitlines()
    assert lines[2] == ("Kappa mean 0.71 dropped below 0.76 (baseline 0.80 minus noise band "
                        "0.04).")
    assert "| kappa | 0.80 | 0.71 | -0.09 | 0.04 |" in md


def test_markdown_judge_changed_lists_fields(baseline):
    md = render_markdown(evaluate(rep("snapshot-changed"), baseline))
    assert "JUDGE_CHANGED" in md
    assert "| snapshot | claude-haiku-4-5-20251001 | claude-haiku-4-5-20260101 |" in md


def test_markdown_without_baseline(baseline):
    md = render_markdown(evaluate(rep("passes-everything")))
    assert "| kappa | — | 0.00 | — |" in md


# --- endpoint ----------------------------------------------------------------------------


def test_changed_endpoint_is_judge_changed(baseline):
    r = rep("pass")
    r["fingerprint"]["endpoint"] = "openrouter.ai"
    res = evaluate(r, baseline)
    assert res["status"] == JUDGE_CHANGED
    assert res["judge_changes"] == [{"field": "endpoint", "baseline": None,
                                     "now": "openrouter.ai"}]


def test_missing_endpoint_field_is_the_provider_default(baseline):
    assert "endpoint" not in baseline["fingerprint"]
    r = rep("pass")
    r["fingerprint"]["endpoint"] = None
    assert evaluate(r, baseline)["status"] == PASS
    b = copy.deepcopy(baseline)
    b["fingerprint"]["endpoint"] = "gw.example.com"
    r["fingerprint"]["endpoint"] = "gw.example.com"
    assert evaluate(r, b)["status"] == PASS



def test_old_report_without_items_still_gates(baseline):
    r = rep("pass")
    assert "items" not in r and "items" not in baseline and "schema_version" not in r
    assert evaluate(r, baseline)["status"] == PASS


def test_judge_changed_points_at_migrate(baseline):
    res = evaluate(rep("snapshot-changed"), baseline)
    assert "judgekeeper migrate" in res["reason"]


# --- markdown escaping (security audit item 4) ------------------------------------------------


HOSTILE = "bad|model <img src=x> `x`"
ESCAPED = "bad\\|model &lt;img src=x&gt; \\`x\\`"


def test_markdown_escapes_fingerprint_cells(baseline):
    r = rep("pass")
    r["fingerprint"]["model"] = HOSTILE
    md = render_markdown(evaluate(r, baseline))
    assert HOSTILE not in md
    # Once in the "judge changes" table, once in the fingerprint table.
    assert md.count(ESCAPED) == 2


def test_markdown_escapes_newlines_in_cells(baseline):
    r = rep("pass")
    r["fingerprint"]["rubric_version"] = "v1\n| injected | row |"
    md = render_markdown(evaluate(r, baseline))
    assert "\n| injected" not in md
    assert "| rubric_version | v1 \\| injected \\| row \\| |" in md


# --- markdown injection (security review, finding 6) --------------------------------------------

HOSTILE_HASH = "abc |\n\n# INJECTED HEADING\n\n[click](https://evil.example/x)"


def test_markdown_escapes_the_anchor_hash():
    r = rep("pass")
    r["anchors"]["sha256"] = HOSTILE_HASH
    md = render_markdown(evaluate(r))
    assert "# INJECTED HEADING" not in [line.strip() for line in md.splitlines()]
    assert "[click](" not in md
    assert md.splitlines()[-1] == ("| anchors sha256 | abc \\|  # INJECTED HEADING  "
                                   "\\[click\\](https://evil.example/x) |")


def test_md_cell_escapes_links_and_images():
    from judgekeeper.markdown import md_cell

    assert md_cell("![x](http://e/p.png) [a](http://e)") == \
        "\\!\\[x\\](http://e/p.png) \\[a\\](http://e)"
    assert md_cell("\\[a]") == "\\\\\\[a\\]"  # an escape in the input cannot undo ours
    assert md_cell("claude-haiku-4-5-20251001") == "claude-haiku-4-5-20251001"
    assert md_cell("a\x1b[2J\x07b") == "a\\[2Jb"  # no terminal control characters either
