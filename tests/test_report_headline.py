"""The report leads with TPR and TNR, each with a 95% Wilson interval."""

import pytest

from judgekeeper import check_table
from judgekeeper.html_report import render_html
from judgekeeper.metrics import wilson, wilson_interval
from judgekeeper.migrate import wilson as migrate_wilson


def test_wilson_against_hand_computed_values():
    # 8/10: centre (0.8 + 1.96^2/20) / (1 + 1.96^2/10) = 0.99208 / 1.38416 = 0.71674,
    # half 1.96 * sqrt(0.016 + 0.009604) / 1.38416 = 0.22658 -> 0.49016 to 0.94332.
    w = wilson(8, 10)
    assert (w["lo"], w["hi"]) == (pytest.approx(0.49016, abs=1e-5),
                                  pytest.approx(0.94332, abs=1e-5))
    # 0/10: centre = half = 0.19208 / 1.38416 = 0.13877 -> 0 to 0.27754.
    w = wilson(0, 10)
    assert (w["lo"], w["hi"]) == (0.0, pytest.approx(0.27754, abs=1e-5))
    # 10/10 mirrors 0/10.
    assert wilson(10, 10)["lo"] == pytest.approx(1 - 0.27754, abs=1e-5)
    assert wilson_interval(None, 10) == (None, None)
    assert wilson_interval(0.5, 0) == (None, None)
    assert migrate_wilson is wilson


def _report(tmp_path, n_pos_right, n_pos, n_neg_right, n_neg):
    rows = [{"id": f"p{i}", "verdict": "pass" if i < n_pos_right else "fail", "label": "pass"}
            for i in range(n_pos)]
    rows += [{"id": f"n{i}", "verdict": "fail" if i < n_neg_right else "pass", "label": "fail"}
             for i in range(n_neg)]
    return check_table(rows, out=tmp_path)


def test_headline_intervals(tmp_path):
    r = _report(tmp_path, 40, 50, 8, 10)
    h = r["headline"]
    assert h["tpr_mean"] == 0.8 and h["tnr_mean"] == 0.8
    assert (h["tpr_ci"]["n"], h["tnr_ci"]["n"]) == (50, 10)
    assert (h["tnr_ci"]["lo"], h["tnr_ci"]["hi"]) == (pytest.approx(0.49016, abs=1e-5),
                                                      pytest.approx(0.94332, abs=1e-5))
    assert list(h)[:4] == ["tpr_mean", "tpr_ci", "tnr_mean", "tnr_ci"]


def test_html_leads_with_tpr_tnr_then_kappa(tmp_path):
    html = render_html(_report(tmp_path, 48, 50, 48, 50))
    tpr, tnr, kappa = html.index(">TPR<"), html.index(">TNR<"), html.index(">Cohen&#x27;s kappa<")
    assert tpr < tnr < kappa
    assert "95% CI" in html
    assert "chance-corrected agreement" in html and "numbers to act on" in html


@pytest.mark.parametrize("pos_right,neg_right,level,phrase", [
    (48, 48, "usable", "Usable as a gate"),           # 0.96 / 0.96
    (48, 43, "usable_with_care", "Usable with care"),  # 0.96 / 0.86
    (48, 38, "not_trustworthy", "Not trustworthy"),    # 0.96 / 0.76
])
def test_verdict_levels(tmp_path, pos_right, neg_right, level, phrase):
    r = _report(tmp_path, pos_right, 50, neg_right, 50)
    assert r["verdict"]["level"] == level
    assert r["verdict"]["summary"].startswith(phrase)
    assert r["verdict"]["summary"].index("TPR") < r["verdict"]["summary"].index("kappa")


def test_rate_flags(tmp_path):
    r = _report(tmp_path, 38, 50, 43, 50)
    flags = {f["code"]: f["message"] for f in r["verdict"]["flags"]}
    assert flags["low_tpr"] == "TPR is 0.76 (below 0.80): not trustworthy as a gate."
    assert flags["tnr_with_care"] == ("TNR is 0.86 (between 0.80 and 0.90): usable with care.")


def test_existing_kappa_flag_kept(tmp_path):
    # TPR 0.90 and TNR 0.90, but with 1000 positives to 10 negatives chance agreement is
    # high: po 0.9, pe (1000*901 + 10*109)/1010^2 = 0.884, kappa 0.14.
    r = _report(tmp_path, 900, 1000, 9, 10)
    assert "low_kappa" in {f["code"] for f in r["verdict"]["flags"]}
    assert r["verdict"]["level"] == "not_trustworthy"


def test_unknown_fingerprint_shows_unknown_in_html(tmp_path):
    r = _report(tmp_path, 48, 50, 48, 50)
    html = render_html(r)
    assert "<dt>model</dt><dd><code>unknown</code></dd>" in html
    assert "judge identity incomplete: provider, model, snapshot, endpoint, prompt_hash, " \
           "rubric_version, temperature" in html


def test_gate_keys_unchanged(tmp_path):
    """The gate reads these; later versions only add keys."""
    r = _report(tmp_path, 48, 50, 48, 50)
    for key in ("anchors", "fingerprint", "n_runs", "headline", "runs", "noise_floor",
                "position_bias"):
        assert key in r
    for key in ("kappa_mean", "tpr_mean", "tnr_mean", "kappa_min", "kappa_max"):
        assert key in r["headline"]
    assert {"kappa", "tpr", "tnr"} <= set(r["runs"][0])
