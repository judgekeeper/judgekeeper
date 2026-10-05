"""Attribution: did scores move because the system changed or because the judge changed?

The anchor set is frozen, so the outputs being judged are identical every time: any movement in
verdicts on it comes from the judge. Compare per-item majority verdicts between a baseline
report and a current one. An item counts as moved only if it was stable (unanimous across runs)
in both reports. Judge drift is declared when the moved-and-stable share exceeds
`max_moved_share` or kappa vs humans moved outside the noise band. This works when the declared
fingerprint is identical, which is the silent-provider-update case.

Statuses: STABLE (exit 0); JUDGE_DRIFT (6); SYSTEM_CHANGE (7), only when the anchor set is
stable and the app scores supplied by the user moved by more than the judge's own pass-rate
noise.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

from judgekeeper.anchors import AnchorHashMismatch
from judgekeeper.config import load_section
from judgekeeper.fingerprint import utc_now
from judgekeeper.gate import EPS, JUDGE_FIELDS, spread
from judgekeeper.markdown import md_cell, md_text
from judgekeeper.redact import scrub

STABLE = "STABLE"
JUDGE_DRIFT = "JUDGE_DRIFT"
SYSTEM_CHANGE = "SYSTEM_CHANGE"
EXIT_CODES = {STABLE: 0, JUDGE_DRIFT: 6, SYSTEM_CHANGE: 7}


class AttributionError(Exception):
    """Unusable attribute inputs or config. Maps to the usage-error exit."""


@dataclass(frozen=True)
class AttributeConfig:
    min_band: float = 0.02
    max_moved_share: float = 0.02


def load_config(path: str | Path) -> AttributeConfig:
    return load_section(path, "attribute", AttributeConfig(), AttributionError)


def _stable(verdicts: list) -> bool:
    return bool(verdicts) and verdicts[0] is not None and all(v == verdicts[0] for v in verdicts)


def _rate_spread(report: dict) -> float:
    """Run-to-run spread of the share of items given the positive verdict."""
    pos = report["headline"]["positive_label"]
    items = report["items"]
    n_runs = len(items[0]["verdicts"]) if items else 0
    rates = [sum(row["verdicts"][k] == pos for row in items) / len(items) for k in range(n_runs)]
    return max(rates) - min(rates) if rates else 0.0


def _fmt(x: float | None, signed: bool = False) -> str:
    if x is None:
        return "n/a"
    x = round(x, 2) + 0.0
    return f"{x:+.2f}" if signed else f"{x:.2f}"


def attribute(current: dict, baseline: dict, config: AttributeConfig | None = None,
              app_score_before: float | None = None,
              app_score_after: float | None = None) -> dict:
    cfg = config or AttributeConfig()
    if "items" not in baseline:
        raise AttributionError(
            "the baseline has no per-item verdicts (written before report schema 2); regenerate "
            "it: `judgekeeper validate` the baseline runs, then `judgekeeper baseline set`")
    if "items" not in current:
        raise AttributionError(
            "the current report has no per-item verdicts; regenerate it with "
            "`judgekeeper validate`")
    if baseline["anchors"]["sha256"] != current["anchors"]["sha256"]:
        raise AnchorHashMismatch(
            f"the current report was measured on anchor set {current['anchors']['sha256']}, the "
            f"baseline on {baseline['anchors']['sha256']}: verdicts are not comparable")
    if (app_score_before is None) != (app_score_after is None):
        raise AttributionError("give both --app-score-before and --app-score-after, or neither")
    for x in (app_score_before, app_score_after):
        if x is not None and not 0 <= x <= 1:
            raise AttributionError(f"app scores are pass rates between 0 and 1, got {x}")

    base_rows = {row["id"]: row for row in baseline["items"]}
    moved, within_noise = [], 0
    for row in current["items"]:
        b = base_rows[row["id"]]
        if b["majority"] == row["majority"]:
            continue
        if _stable(b["verdicts"]) and _stable(row["verdicts"]):
            moved.append({"id": row["id"], "slice": row.get("slice"), "human": row["human"],
                          "baseline": b["majority"], "current": row["majority"]})
        else:
            within_noise += 1
    n = len(current["items"])
    moved_share = len(moved) / n if n else 0.0

    base_k = baseline["headline"].get("kappa_mean")
    cur_k = current["headline"].get("kappa_mean")
    delta = None if base_k is None or cur_k is None else cur_k - base_k
    band = max(spread(baseline, "kappa"), spread(current, "kappa"), cfg.min_band)
    share_moved = moved_share > cfg.max_moved_share + EPS
    kappa_moved = delta is not None and abs(delta) > band + EPS
    drift = share_moved or kappa_moved

    bfp, cfp = baseline["fingerprint"], current["fingerprint"]
    declared = [{"field": f, "baseline": bfp.get(f), "now": cfp.get(f)}
                for f in JUDGE_FIELDS if bfp.get(f) != cfp.get(f)]
    snaps = {"baseline": baseline.get("snapshots_seen", []),
             "current": current.get("snapshots_seen", [])}
    snapshot_changed = (bfp.get("snapshot") != cfp.get("snapshot")
                        or set(snaps["baseline"]) != set(snaps["current"]))

    app = None
    if app_score_before is not None:
        app_band = max(_rate_spread(baseline), _rate_spread(current), cfg.min_band)
        app_delta = app_score_after - app_score_before
        app = {"before": app_score_before, "after": app_score_after, "delta": app_delta,
               "noise_band": app_band}

    anchor_text = (f"{len(moved)} of {n} anchor items ({moved_share:.0%}) changed verdict while "
                   f"stable in both reports, and kappa vs humans moved {_fmt(delta, True)} "
                   f"against a ±{_fmt(band)} noise band")
    if drift:
        status = JUDGE_DRIFT
        if declared and any(c["field"] != "snapshot" for c in declared):
            who = ("The declared judge changed ("
                   + ", ".join(c["field"] for c in declared) + ").")
        elif snapshot_changed:
            who = (f"The provider served a different snapshot "
                   f"({', '.join(snaps['baseline']) or 'n/a'} → "
                   f"{', '.join(snaps['current']) or 'n/a'}).")
        else:
            who = ("The declared fingerprint and the served snapshot are identical: a silent "
                   "provider-side change.")
        reason = (f"The judge moved: {anchor_text}. The anchor set is frozen, so this movement "
                  f"comes from the judge, not your system. {who} Re-validate the judge; to keep "
                  "the new behaviour, run `judgekeeper migrate` and rebase.")
        if app is not None:
            reason += (f" Your app score moved {_fmt(app['delta'], True)}, but with the judge "
                       "moving it cannot be attributed to your system.")
    elif app is not None and abs(app["delta"]) > app["noise_band"] + EPS:
        status = SYSTEM_CHANGE
        reason = (f"The judge is stable on the anchor set ({anchor_text}), and your app score "
                  f"moved {_fmt(app['before'])} → {_fmt(app['after'])} "
                  f"({_fmt(app['delta'], True)}, outside the ±{_fmt(app['noise_band'])} judge "
                  "noise band): the change comes from your system.")
    else:
        status = STABLE
        reason = f"The judge is stable on the anchor set: {anchor_text}."
        if app is not None:
            reason += (f" Your app score moved {_fmt(app['delta'], True)}, inside the "
                       f"±{_fmt(app['noise_band'])} judge noise band.")
        if declared:
            reason += (" The declared judge differs from the baseline ("
                       + ", ".join(c["field"] for c in declared) + ").")

    return {
        "status": status,
        "reason": reason,
        "exit_code": EXIT_CODES[status],
        "generated_at": utc_now(),
        "anchors_sha256": current["anchors"]["sha256"],
        "anchor_set": {
            "n_items": n,
            "n_moved": len(moved),
            "moved_share": moved_share,
            "n_moved_within_noise": within_noise,
            "max_moved_share": cfg.max_moved_share,
            "moved_items": moved,
            "kappa_baseline": base_k,
            "kappa_current": cur_k,
            "kappa_delta": delta,
            "noise_band": band,
        },
        "judge": {
            "declared_changes": declared,
            "snapshot_changed": snapshot_changed,
            "snapshots": snaps,
            "baseline_fingerprint": bfp,
            "current_fingerprint": cfp,
        },
        "app_scores": app,
        "config": asdict(cfg),
    }


def _fp_cell(value) -> str:
    return md_cell(scrub(value) if isinstance(value, str) else value)


def render_markdown(result: dict) -> str:
    """Summary for $GITHUB_STEP_SUMMARY."""
    a, j = result["anchor_set"], result["judge"]
    # The reason may quote the served snapshot names, which come from the report files.
    lines = [f"## judgekeeper attribute: {result['status']}", "",
             md_text(scrub(result["reason"])), "",
             "| | baseline | now | delta | noise band |", "|---|---|---|---|---|",
             (f"| kappa vs humans | {_fmt(a['kappa_baseline'])} | {_fmt(a['kappa_current'])} | "
              f"{_fmt(a['kappa_delta'], True)} | {_fmt(a['noise_band'])} |")]
    app = result["app_scores"]
    if app is not None:
        lines.append(f"| app score | {_fmt(app['before'])} | {_fmt(app['after'])} | "
                     f"{_fmt(app['delta'], True)} | {_fmt(app['noise_band'])} |")
    moved = (f"Anchor items moved (stable in both reports): {a['n_moved']} of {a['n_items']} "
             f"({a['moved_share']:.0%}; threshold {a['max_moved_share']:.0%}). Changed but "
             f"flipping in either report: {a['n_moved_within_noise']}.")
    lines += ["", moved,
              f"Served snapshot changed: {'yes' if j['snapshot_changed'] else 'no'}."]
    if j["declared_changes"]:
        lines += ["", "| field | baseline | now |", "|---|---|---|"]
        lines += [f"| {md_cell(c['field'])} | {_fp_cell(c['baseline'])} | {_fp_cell(c['now'])} |"
                  for c in j["declared_changes"]]
    if a["moved_items"]:
        lines += ["", "| item | slice | human | baseline | now |", "|---|---|---|---|---|"]
        lines += [f"| {md_cell(m['id'])} | {md_cell(m['slice'] or '')} | {md_cell(m['human'])} | "
                  f"{md_cell(m['baseline'])} | {md_cell(m['current'])} |" for m in a["moved_items"]]
    return "\n".join(lines) + "\n"
