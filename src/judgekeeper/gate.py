"""CI gate: compare a validation report with fixed thresholds and, optionally, a baseline report.

Decides one status, in this order:
ANCHORS_CHANGED, JUDGE_CHANGED, FLAKY (fewer than 3 runs), then absolute thresholds and the
baseline comparison, where a failure that the best run clears, or a noisy judge, is FLAKY
rather than FAIL.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from judgekeeper.config import load_section
from judgekeeper.fingerprint import is_unknown
from judgekeeper.markdown import md_cell
from judgekeeper.redact import scrub, scrub_fingerprint
from judgekeeper.textio import read_utf8

PASS = "PASS"
FAIL = "FAIL"
ANCHORS_CHANGED = "ANCHORS_CHANGED"
FLAKY = "FLAKY"
JUDGE_CHANGED = "JUDGE_CHANGED"

EXIT_CODES = {PASS: 0, FAIL: 1, ANCHORS_CHANGED: 3, FLAKY: 4, JUDGE_CHANGED: 5}
STATUSES = tuple(EXIT_CODES)

# Looked up relative to the working directory (the CLI) or the pytest rootdir (the plugin).
DEFAULT_BASELINE = Path(".judgekeeper") / "baseline.json"
DEFAULT_CONFIG = Path("judgekeeper.toml")

MIN_RUNS = 3
# Fields compared between baseline and report (created_at is when, not who). A report with no
# `endpoint` reads as None, the provider default. A field unknown on either side cannot be
# compared: that is a warning, because data imported from a spreadsheet or a homemade judge
# rarely records the temperature or the snapshot. `require_fingerprint` makes it JUDGE_CHANGED.
JUDGE_FIELDS = ("provider", "model", "snapshot", "endpoint", "prompt_hash", "rubric_version",
                "temperature")
FLAKY_ADVICE = "use the majority of more runs"
# Float slack so that a value sitting exactly on a threshold passes.
EPS = 1e-9

METRIC_LABELS = {"kappa": "kappa", "tpr": "TPR", "tnr": "TNR", "ab_ba": "AB/BA disagreement"}


class GateError(Exception):
    """Unusable gate inputs: bad report, baseline or config. Maps to the usage-error exit."""


@dataclass(frozen=True)
class GateConfig:
    kappa_min: float = 0.6
    tpr_min: float = 0.8
    tnr_min: float = 0.8
    ab_ba_disagreement_max: float = 0.10
    min_band: float = 0.02
    flip_rate_max: float = 0.10


def load_config(path: str | Path) -> GateConfig:
    return load_section(path, "gate", GateConfig(), GateError)


def load_report(path: str | Path) -> dict:
    """Read a report.json and check it has what the gate needs."""
    path = Path(path)
    try:
        data = json.loads(read_utf8(path, GateError))
    except OSError as e:
        raise GateError(f"cannot read {path}: {e.strerror}") from None
    except json.JSONDecodeError:
        raise GateError(f"{path} is not valid JSON") from None
    if not isinstance(data, dict):
        raise GateError(f"{path} is not a judgekeeper report")
    missing = [k for k in ("anchors", "fingerprint", "n_runs", "headline", "runs", "noise_floor")
               if k not in data]
    if missing:
        raise GateError(f"{path} is not a judgekeeper report (missing {', '.join(missing)})")
    if "sha256" not in data["anchors"]:
        raise GateError(f"{path} is not a judgekeeper report (anchors has no sha256)")
    # The fingerprint is copied into gate.json and shown in its summary; a report written by
    # an older version may hold a key in it.
    data["fingerprint"] = scrub_fingerprint(data["fingerprint"])
    if isinstance(data.get("snapshots_seen"), list):
        data["snapshots_seen"] = [scrub(s) if isinstance(s, str) else s
                                  for s in data["snapshots_seen"]]
    return data


def run_gate(report_path: str | Path, baseline: str | Path | None = None,
             config: str | Path | None = None, root: str | Path = ".",
             allow_judge_change: bool = False, require_fingerprint: bool = False) -> dict:
    """Load a report, its baseline and thresholds, and evaluate. Writes nothing.

    With no `baseline` or `config`, DEFAULT_BASELINE and DEFAULT_CONFIG under `root` are used
    when they exist. The result carries "baseline_path".
    """
    root = Path(root)
    report = load_report(report_path)
    if config is None and (root / DEFAULT_CONFIG).is_file():
        config = root / DEFAULT_CONFIG
    cfg = load_config(config) if config is not None else GateConfig()
    if baseline is None and (root / DEFAULT_BASELINE).is_file():
        baseline = root / DEFAULT_BASELINE
    base = load_report(baseline) if baseline is not None else None
    result = evaluate(report, base, cfg, allow_judge_change=allow_judge_change,
                      require_fingerprint=require_fingerprint)
    return {**result, "baseline_path": str(baseline) if baseline is not None else None}


def exit_code(status: str, flaky_as: str | None = None) -> int:
    if status == FLAKY and flaky_as is not None:
        return {"pass": EXIT_CODES[PASS], "fail": EXIT_CODES[FAIL]}[flaky_as]
    return EXIT_CODES[status]


def _per_run(report: dict, metric: str) -> list[float]:
    return [r[metric] for r in report["runs"] if r.get(metric) is not None]


def _mean(report: dict, metric: str) -> float | None:
    return report["headline"].get(f"{metric}_mean")


def spread(report: dict, metric: str) -> float:
    """Max minus min of a metric over a report's runs: its run-to-run noise."""
    vals = _per_run(report, metric)
    return max(vals) - min(vals) if vals else 0.0


def _ab_ba(report: dict) -> tuple[float, float] | None:
    """(mean, best run) AB/BA disagreement rate, or None for single-output reports."""
    pb = report.get("position_bias")
    if not pb:
        return None
    per_run = [r["inconsistency_rate"] for r in pb.get("per_run", [])]
    rate = pb["inconsistency_rate"]
    return rate, min(per_run) if per_run else rate


def _check(kind: str, metric: str, op: str, value, threshold: float, best) -> dict:
    def ok(x) -> bool:
        if x is None:
            return False
        return x >= threshold - EPS if op == ">=" else x <= threshold + EPS

    return {
        "kind": kind,
        "metric": metric,
        "op": op,
        "value": value,
        "threshold": threshold,
        "best": best,
        "passed": ok(value),
        "passed_best": ok(best),
    }


def _absolute_checks(report: dict, cfg: GateConfig) -> list[dict]:
    checks = []
    for metric, threshold in (("kappa", cfg.kappa_min), ("tpr", cfg.tpr_min),
                              ("tnr", cfg.tnr_min)):
        vals = _per_run(report, metric)
        checks.append(_check("absolute", metric, ">=", _mean(report, metric), threshold,
                             max(vals) if vals else None))
    ab_ba = _ab_ba(report)
    if ab_ba is not None:
        checks.append(_check("absolute", "ab_ba", "<=", ab_ba[0], cfg.ab_ba_disagreement_max,
                             ab_ba[1]))
    return checks


def _band(report: dict, baseline: dict | None, metric: str, cfg: GateConfig) -> float:
    spreads = [spread(report, metric), cfg.min_band]
    if baseline is not None:
        spreads.append(spread(baseline, metric))
    return max(spreads)


def _relative_checks(report: dict, baseline: dict, cfg: GateConfig) -> list[dict]:
    checks = []
    for metric in ("kappa", "tpr", "tnr"):
        base = _mean(baseline, metric)
        if base is None:
            continue
        band = _band(report, baseline, metric, cfg)
        vals = _per_run(report, metric)
        check = _check("relative", metric, ">=", _mean(report, metric), base - band,
                       max(vals) if vals else None)
        checks.append({**check, "baseline": base, "noise_band": band})
    return checks


def _metrics_table(report: dict, baseline: dict | None, cfg: GateConfig) -> list[dict]:
    rows = []
    for metric in ("kappa", "tpr", "tnr"):
        now = _mean(report, metric)
        base = _mean(baseline, metric) if baseline is not None else None
        rows.append({
            "metric": metric,
            "baseline": base,
            "now": now,
            "delta": now - base if now is not None and base is not None else None,
            "noise_band": _band(report, baseline, metric, cfg),
        })
    ab_ba = _ab_ba(report)
    if ab_ba is not None:
        base_ab_ba = _ab_ba(baseline) if baseline is not None else None
        base = base_ab_ba[0] if base_ab_ba else None
        rows.append({"metric": "ab_ba", "baseline": base, "now": ab_ba[0],
                     "delta": ab_ba[0] - base if base is not None else None,
                     "noise_band": None})
    return rows


def _fmt(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.2f}"


def _describe(c: dict) -> str:
    label = METRIC_LABELS[c["metric"]]
    if c["kind"] == "relative":
        return (f"{label} mean {_fmt(c['value'])} dropped below {_fmt(c['threshold'])} "
                f"(baseline {_fmt(c['baseline'])} minus noise band {_fmt(c['noise_band'])})")
    if c["value"] is None:
        return f"{label} could not be measured"
    side = "below" if c["op"] == ">=" else "above"
    return f"{label} mean {_fmt(c['value'])} is {side} the {_fmt(c['threshold'])} threshold"


def _result(status: str, reason: str, report: dict, baseline: dict | None, cfg: GateConfig,
            checks=(), judge_changes=(), warnings=(), compare_to: dict | None = None) -> dict:
    return {
        "status": status,
        "reason": reason,
        "checks": list(checks),
        "metrics": _metrics_table(report, compare_to, cfg),
        "judge_changes": list(judge_changes),
        "warnings": list(warnings),
        "n_runs": report["n_runs"],
        "items_flipped_fraction": report["noise_floor"].get("items_flipped_fraction"),
        "anchors_sha256": report["anchors"]["sha256"],
        "fingerprint": report["fingerprint"],
        "baseline": None if baseline is None else {
            "anchors_sha256": baseline["anchors"]["sha256"],
            "fingerprint": baseline["fingerprint"],
            "generated_at": baseline.get("generated_at"),
        },
        "config": asdict(cfg),
    }


def evaluate(report: dict, baseline: dict | None = None, config: GateConfig | None = None,
             allow_judge_change: bool = False, require_fingerprint: bool = False) -> dict:
    cfg = config or GateConfig()
    warnings: list[str] = []

    if baseline is not None and baseline["anchors"]["sha256"] != report["anchors"]["sha256"]:
        return _result(
            ANCHORS_CHANGED,
            "The anchor set is not the one the baseline was measured on, so the scores are not "
            "comparable; re-baseline on purpose if the change was intended.",
            report, baseline, cfg,
        )

    compare_to = baseline
    changes: list[dict] = []
    if baseline is not None:
        bfp, rfp = baseline["fingerprint"], report["fingerprint"]
        unknown = [f for f in JUDGE_FIELDS
                   if is_unknown(f, bfp.get(f)) or is_unknown(f, rfp.get(f))]
        changes = [{"field": f, "baseline": bfp.get(f), "now": rfp.get(f)}
                   for f in JUDGE_FIELDS if f not in unknown and bfp.get(f) != rfp.get(f)]
        unknown_names = ", ".join(unknown)
        if unknown and not changes and require_fingerprint and not allow_judge_change:
            return _result(
                JUDGE_CHANGED,
                f"Cannot prove same judge: {unknown_names} unknown in the baseline or this "
                "report, and --require-fingerprint is set. Record those fields, or drop "
                "--require-fingerprint to gate with a warning.",
                report, baseline, cfg,
                judge_changes=[{"field": f, "baseline": bfp.get(f), "now": rfp.get(f),
                                "unknown": True} for f in unknown],
            )
        if unknown:
            warnings.append(f"Judge identity incomplete: {unknown_names} unknown in the baseline "
                            "or this report, so the judge cannot be proven unchanged; pass "
                            "--require-fingerprint to block on this.")
        if changes:
            names = ", ".join(c["field"] for c in changes)
            if not allow_judge_change:
                return _result(
                    JUDGE_CHANGED,
                    f"The judge changed since the baseline ({names}), and scores are not "
                    "compared across judges; run `judgekeeper migrate` on the old and new runs "
                    "to see what moved, then `--rebase` to make the new judge the baseline.",
                    report, baseline, cfg, judge_changes=changes,
                )
            warnings.append(f"Judge changed since the baseline ({names}); compared against "
                            "absolute thresholds only.")
            compare_to = None

    flipped = report["noise_floor"].get("items_flipped_fraction") or 0.0
    if report["n_runs"] < MIN_RUNS:
        why = ("Noise floor unknown: one run supplied" if report["n_runs"] == 1
               else f"Only {report['n_runs']} runs: noise floor unknown")
        return _result(
            FLAKY,
            f"{why}, so a drop cannot be told apart from run-to-run noise; judge at least "
            f"{MIN_RUNS} runs.",
            report, baseline, cfg, judge_changes=changes, warnings=warnings,
            compare_to=compare_to,
        )

    checks = _absolute_checks(report, cfg)
    if compare_to is not None:
        checks += _relative_checks(report, compare_to, cfg)
    failed = [c for c in checks if not c["passed"]]
    noisy = flipped > cfg.flip_rate_max + EPS
    if noisy:
        warnings.append(f"{flipped:.0%} of items flipped verdict between identical runs (above "
                        f"{cfg.flip_rate_max:.0%}).")

    if not failed:
        status = PASS
        reason = "The judge clears every absolute threshold"
        reason += (" and is within the noise band of the baseline." if compare_to is not None
                   else "; no baseline to compare against.")
    elif noisy or all(c["passed_best"] for c in failed):
        status = FLAKY
        why = "; ".join(_describe(c) for c in failed)
        cause = (f"{flipped:.0%} of items flipped between runs" if noisy
                 else "the best run clears it")
        reason = f"{why[0].upper()}{why[1:]}, but {cause}: {FLAKY_ADVICE}."
    else:
        status = FAIL
        why = "; ".join(_describe(c) for c in failed)
        reason = f"{why[0].upper()}{why[1:]}."

    return _result(status, reason, report, baseline, cfg, checks=checks, judge_changes=changes,
                   warnings=warnings, compare_to=compare_to)


def _cell(x: float | None, signed: bool = False) -> str:
    if x is None:
        return "—"
    x = round(x, 2) + 0.0  # avoid "-0.00"
    return f"{x:+.2f}" if signed else f"{x:.2f}"


def _fp_cell(field: str, value) -> str:
    if field != "created_at" and is_unknown(field, value):
        return "unknown"
    return md_cell(scrub(value) if isinstance(value, str) else value)


def render_markdown(result: dict) -> str:
    """Summary for a PR comment or $GITHUB_STEP_SUMMARY."""
    lines = [f"## judgekeeper gate: {result['status']}", "", scrub(result["reason"]), ""]
    lines += ["| metric | baseline | now | delta | noise band |", "|---|---|---|---|---|"]
    for m in result["metrics"]:
        lines.append(f"| {METRIC_LABELS[m['metric']]} | {_cell(m['baseline'])} | "
                     f"{_cell(m['now'])} | {_cell(m['delta'], signed=True)} | "
                     f"{_cell(m['noise_band'])} |")
    flipped = result["items_flipped_fraction"]
    flipped_text = "n/a" if flipped is None else f"{flipped:.0%}"
    lines += ["", f"Runs: {result['n_runs']}. Items that flipped verdict between runs: {flipped_text}."]

    if result["judge_changes"]:
        lines += ["", "**Judge changes since the baseline**", "",
                  "| field | baseline | now |", "|---|---|---|"]
        for c in result["judge_changes"]:
            lines.append(f"| {md_cell(c['field'])} | {_fp_cell(c['field'], c['baseline'])} | "
                         f"{_fp_cell(c['field'], c['now'])} |")

    if result["warnings"]:
        lines += [""] + [f"- Warning: {scrub(w)}" for w in result["warnings"]]

    fp = result["fingerprint"]
    lines += ["", "**Judge fingerprint**", "", "| field | value |", "|---|---|"]
    for f in (*JUDGE_FIELDS, "created_at"):
        lines.append(f"| {f} | {_fp_cell(f, fp.get(f))} |")
    lines.append(f"| anchors sha256 | {md_cell(result['anchors_sha256'])} |")
    return "\n".join(lines) + "\n"
