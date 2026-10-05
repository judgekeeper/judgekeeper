"""Judge migration: run an old and a new judge over the same frozen anchor set and say what moved.

Both judges are measured against the human labels (kappa, TPR, TNR, never raw agreement alone)
and against each other, item by item on their majority verdicts. A changed item counts as a
real change only when both judges were unanimous on it across their own runs; otherwise either
judge was flipping anyway and the change is within noise. The status:

    BETTER / WORSE  kappa vs humans moved by more than the noise band, by sign
    DIFFERENT       kappa inside the band, but more than `max_changed_share` of items changed
                    while both judges were stable: as good, on different items
    EQUIVALENT      kappa inside the band and changed-and-stable share at most the threshold

The noise band is the larger of each judge's own run-to-run kappa spread and `min_band`.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from html import escape
from pathlib import Path

from judgekeeper import __version__
from judgekeeper.anchors import NEGATIVE, PAIRWISE, POSITIVE
from judgekeeper.config import load_section
from judgekeeper.fingerprint import utc_now
from judgekeeper.gate import EPS, JUDGE_FIELDS, spread
from judgekeeper.html_report import CSS, _f, _pct, _text, _tile
from judgekeeper.metrics import Z95, cohen_kappa, wilson  # noqa: F401 - re-exported
from judgekeeper.redact import scrub, scrub_fingerprint
from judgekeeper.report import load_runs, report_from_runs

EQUIVALENT = "EQUIVALENT"
BETTER = "BETTER"
WORSE = "WORSE"
DIFFERENT = "DIFFERENT"

# --fail-on: which statuses exit 1.
FAIL_ON = {"worse": (WORSE,), "different": (WORSE, DIFFERENT)}

MIGRATION_SCHEMA_VERSION = 1
# Old-judge pass rate used for the worked example of the pass-rate bridge. Illustrative only.
EXAMPLE_OLD_RATE = 0.8


class MigrateError(Exception):
    """Unusable migrate inputs or config. Maps to the usage-error exit."""


@dataclass(frozen=True)
class MigrateConfig:
    min_band: float = 0.02
    max_changed_share: float = 0.02


def load_config(path: str | Path) -> MigrateConfig:
    return load_section(path, "migrate", MigrateConfig(), MigrateError)


def _stable(verdicts: list) -> bool:
    """Unanimous across runs, on a parseable verdict."""
    return bool(verdicts) and verdicts[0] is not None and all(v == verdicts[0] for v in verdicts)


def _range(report: dict, metric: str) -> dict:
    vals = [r[metric] for r in report["runs"] if r.get(metric) is not None]
    return {"mean": report["headline"].get(f"{metric}_mean"),
            "min": min(vals) if vals else None, "max": max(vals) if vals else None}


def pass_rate_bridge(ids: list[str], slices: dict, old: dict, new: dict, positive: str,
                     kind: str) -> dict:
    """P(new says positive | old said positive) and P(new says positive | old did not).

    `old` and `new` map item id to majority verdict. Items where either judge has no majority
    are left out and counted in `n_excluded`.
    """
    def block(sel: list[str]) -> dict:
        usable = [i for i in sel if old[i] is not None and new[i] is not None]
        was_pos = [i for i in usable if old[i] == positive]
        was_neg = [i for i in usable if old[i] != positive]
        return {
            "a": wilson(sum(new[i] == positive for i in was_pos), len(was_pos)),
            "b": wilson(sum(new[i] == positive for i in was_neg), len(was_neg)),
            "n_excluded": len(sel) - len(usable),
        }

    pos_name = "prefers A" if kind == PAIRWISE else positive
    neg_name = "prefers B" if kind == PAIRWISE else NEGATIVE[kind]
    overall = block(ids)
    names = sorted({slices[i] for i in ids if slices.get(i) is not None})
    per_slice = [{"slice": s, **block([i for i in ids if slices.get(i) == s])} for s in names]
    a, b = overall["a"]["p"], overall["b"]["p"]
    example = {"old_rate": EXAMPLE_OLD_RATE,
               "new_rate": None if a is None or b is None
               else EXAMPLE_OLD_RATE * a + (1 - EXAMPLE_OLD_RATE) * b}
    return {
        "positive_label": positive,
        "positive_name": pos_name,
        "negative_name": neg_name,
        "formula": "new_rate ≈ old_rate × a + (1 − old_rate) × b",
        "a_means": f"P(new judge {_says(pos_name)} | old judge {_said(pos_name)})",
        "b_means": f"P(new judge {_says(pos_name)} | old judge {_said(neg_name)})",
        "overall": overall,
        "per_slice": per_slice,
        "example": example,
        "caveat": ("This assumes your production traffic resembles the anchor set (the same mix "
                   "of slices and of easy and hard cases). Where it does not, weight the "
                   "per-slice rows by your own traffic, and read the estimate with at least the "
                   "uncertainty of the intervals."),
    }


def _says(name: str) -> str:
    return name if name.startswith("prefers") else f"says {name}"


def _said(name: str) -> str:
    return name.replace("prefers", "preferred") if name.startswith("prefers") else f"said {name}"


def _rationale(runs: list[dict], item_id: str, majority: str | None) -> str:
    """Rationale from the first run that gave the majority verdict, else from run 1."""
    for r in runs:
        rec = r["records"][item_id]
        if rec.get("verdict") == majority:
            return scrub(rec.get("rationale", "")) or ""
    return scrub(runs[0]["records"][item_id].get("rationale", "")) or ""


def _fmt(x: float | None, signed: bool = False) -> str:
    if x is None:
        return "n/a"
    x = round(x, 2) + 0.0
    return f"{x:+.2f}" if signed else f"{x:.2f}"


def _verdict(status: str, old_k, new_k, delta, band, cs_share, fixed, broken) -> str:
    kappas = f"kappa {_fmt(old_k)} → {_fmt(new_k)}"
    if status == BETTER:
        return (f"The new judge agrees with humans more than the old one ({kappas}, "
                f"{_fmt(delta, True)}, outside the ±{_fmt(band)} noise band). Switch and "
                "rebase: scores will move because the judge improved, not because your system "
                "changed, so do not compare scores across the switch.")
    if status == WORSE:
        return (f"The new judge agrees with humans less than the old one ({kappas}, "
                f"{_fmt(delta, True)}, outside the ±{_fmt(band)} noise band; {broken} items "
                f"broken, {fixed} fixed). Do not migrate yet: try another model or tune the "
                "judge prompt, then run migrate again.")
    if status == DIFFERENT:
        return (f"The judges are about as good ({kappas}, inside the ±{_fmt(band)} noise band) "
                f"but disagree on which items: {cs_share:.0%} of verdicts changed where both "
                f"judges were stable ({fixed} fixed, {broken} broken). Old and new scores are "
                "not comparable item by item; if you switch, rebase and do not compare scores "
                "across the switch.")
    return (f"The new judge agrees with humans as well as the old one ({kappas}, inside the "
            f"±{_fmt(band)} noise band) and changes {cs_share:.0%} of verdicts where both judges "
            "were stable. Safe to switch: keep comparing scores across the switch, and rebase "
            "so the gate tracks the new judge.")


def compare(anchors_path: str | Path, old_dir: str | Path, new_dir: str | Path,
            config: MigrateConfig | None = None) -> tuple[dict, dict, dict]:
    """(migration, old judge's report, new judge's report)."""
    cfg = config or MigrateConfig()
    items, manifest, old_runs = load_runs(anchors_path, old_dir)
    _, _, new_runs = load_runs(anchors_path, new_dir)
    old_rep = report_from_runs(anchors_path, items, manifest, old_runs)
    new_rep = report_from_runs(anchors_path, items, manifest, new_runs)
    kind = manifest["kind"]

    ids = [i["id"] for i in items]
    by_id = {i["id"]: i for i in items}
    old_rows = {row["id"]: row for row in old_rep["items"]}
    new_rows = {row["id"]: row for row in new_rep["items"]}
    old_maj = {i: old_rows[i]["majority"] for i in ids}
    new_maj = {i: new_rows[i]["majority"] for i in ids}

    changed = []
    for i in ids:
        if old_maj[i] == new_maj[i]:
            continue
        human = by_id[i]["human_label"]
        stable = _stable(old_rows[i]["verdicts"]) and _stable(new_rows[i]["verdicts"])
        outcome = ("within_noise" if not stable
                   else "fixed" if new_maj[i] == human else "broken")
        changed.append({
            "id": i,
            "slice": by_id[i].get("slice"),
            "human": human,
            "old": old_maj[i],
            "new": new_maj[i],
            "stable": stable,
            "outcome": outcome,
            "old_rationale": _rationale(old_runs, i, old_maj[i]),
            "new_rationale": _rationale(new_runs, i, new_maj[i]),
        })
    n = len(ids)
    n_fixed = sum(c["outcome"] == "fixed" for c in changed)
    n_broken = sum(c["outcome"] == "broken" for c in changed)
    n_cs = n_fixed + n_broken
    cs_share = n_cs / n

    old_k = old_rep["headline"]["kappa_mean"]
    new_k = new_rep["headline"]["kappa_mean"]
    delta = None if old_k is None or new_k is None else new_k - old_k
    band = max(spread(old_rep, "kappa"), spread(new_rep, "kappa"), cfg.min_band)
    if delta is not None and abs(delta) > band + EPS:
        status = BETTER if delta > 0 else WORSE
    elif cs_share > cfg.max_changed_share + EPS:
        status = DIFFERENT
    else:
        status = EQUIVALENT

    new_slices = {s["slice"]: s for s in new_rep["slices"]}
    slices = []
    for s in old_rep["slices"]:
        o, nw = s["kappa_mean"], new_slices[s["slice"]]["kappa_mean"]
        slices.append({
            "slice": s["slice"],
            "n": s["n"],
            "old_kappa": o,
            "new_kappa": nw,
            "delta": None if o is None or nw is None else nw - o,
            "n_changed_stable": sum(c["stable"] and c["slice"] == s["slice"] for c in changed),
        })

    ofp, nfp = old_rep["fingerprint"], new_rep["fingerprint"]
    migration = {
        "schema_version": MIGRATION_SCHEMA_VERSION,
        "judgekeeper_version": __version__,
        "generated_at": utc_now(),
        "status": status,
        "verdict": _verdict(status, old_k, new_k, delta, band, cs_share, n_fixed, n_broken),
        "anchors": {k: old_rep["anchors"][k] for k in ("file", "sha256", "n_items", "kind")},
        "fingerprints": {
            "old": ofp,
            "new": nfp,
            "changed_fields": [f for f in JUDGE_FIELDS if ofp.get(f) != nfp.get(f)],
        },
        "snapshots_seen": {"old": old_rep["snapshots_seen"], "new": new_rep["snapshots_seen"]},
        "vs_human": {
            "old": {"n_runs": old_rep["n_runs"], **{m: _range(old_rep, m)
                                                    for m in ("kappa", "tpr", "tnr")}},
            "new": {"n_runs": new_rep["n_runs"], **{m: _range(new_rep, m)
                                                    for m in ("kappa", "tpr", "tnr")}},
            "positive_label": POSITIVE[kind],
            "kappa_delta": delta,
            "noise_band": band,
        },
        "judge_vs_judge": {
            "kappa": cohen_kappa([old_maj[i] for i in ids], [new_maj[i] for i in ids]),
            "n_items": n,
            "n_changed": len(changed),
            "changed_share": len(changed) / n,
            "n_changed_stable": n_cs,
            "changed_stable_share": cs_share,
            "n_changed_within_noise": len(changed) - n_cs,
            "n_fixed": n_fixed,
            "n_broken": n_broken,
            "net": n_fixed - n_broken,
        },
        "slices": slices,
        "changed_items": changed,
        "bridge": pass_rate_bridge(ids, {i: by_id[i].get("slice") for i in ids}, old_maj,
                                   new_maj, POSITIVE[kind], kind),
        "config": asdict(cfg),
    }
    return migration, old_rep, new_rep


def migrate(anchors_path: str | Path, old_dir: str | Path, new_dir: str | Path,
            config: MigrateConfig | None = None) -> dict:
    return compare(anchors_path, old_dir, new_dir, config)[0]


def _safe(name: str | None) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", name or "unknown").strip("-.") or "judge"


def model_label(fp: dict, side: str) -> str:
    """The judge's model name, or a readable stand-in when the fingerprint does not record one
    (callable, exec and imported judges often cannot)."""
    return fp.get("model") or f"{side} judge (model unknown)"


def audit_path(migration: dict, directory: Path) -> Path:
    """`<UTC date>-<old model>-to-<new model>.json` in `directory`, never overwriting."""
    fps = migration["fingerprints"]
    stem = (f"{migration['generated_at'][:10]}-{_safe(fps['old']['model'])}-to-"
            f"{_safe(fps['new']['model'])}")
    path = directory / f"{stem}.json"
    n = 2
    while path.exists():
        path = directory / f"{stem}-{n}.json"
        n += 1
    return path


# --- HTML -------------------------------------------------------------------------------------

EXTRA_CSS = """
:root { --warn:#93370d; --warn-bg:#fef0c7; }
@media (prefers-color-scheme: dark) { :root { --warn:#fec84b; --warn-bg:#3d2a09; } }
.verdict.warn { background: var(--warn-bg); color: var(--warn); }
tr.hl td { background: var(--warn-bg); }
.formula { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 14px;
  background: var(--card); padding: 10px 12px; border-radius: 6px; }
"""

_BANNER = {EQUIVALENT: "ok", BETTER: "ok", WORSE: "bad", DIFFERENT: "warn"}


def _rows(headers: list[str], rows: list[list[str]], num: set[int] = frozenset(),
          classes: list[str] | None = None) -> str:
    def cell(tag: str, i: int, c: str) -> str:
        return f'<{tag} class="num">{c}</{tag}>' if i in num else f"<{tag}>{c}</{tag}>"

    head = "".join(cell("th", i, escape(h)) for i, h in enumerate(headers))
    body = []
    for k, row in enumerate(rows):
        cls = f' class="{classes[k]}"' if classes and classes[k] else ""
        body.append(f"<tr{cls}>" + "".join(cell("td", i, c) for i, c in enumerate(row)) + "</tr>")
    return (f'<div class="scroll"><table><thead><tr>{head}</tr></thead>'
            f'<tbody>{"".join(body)}</tbody></table></div>')


def _span(r: dict) -> str:
    if r["mean"] is None:
        return "n/a"
    return f"{_f(r['mean'])} ({_f(r['min'])} to {_f(r['max'])})"


def _prop(w: dict) -> str:
    if w["p"] is None:
        return "n/a (no items)"
    return f"{_f(w['p'])} ({w['k']}/{w['n']}) [{_f(w['lo'])}, {_f(w['hi'])}]"


def render_html(m: dict) -> str:
    fps, vh, jj, br = m["fingerprints"], m["vs_human"], m["judge_vs_judge"], m["bridge"]
    # A migration.json written by an older version may hold a key in a fingerprint.
    fps = {**fps, "old": scrub_fingerprint(fps["old"]), "new": scrub_fingerprint(fps["new"])}
    old_model, new_model = model_label(fps["old"], "old"), model_label(fps["new"], "new")
    out = [f"<h1>Judge migration: {escape(old_model)} → {escape(new_model)}</h1>",
           (f'<p class="muted">{escape(m["anchors"]["file"])} ({m["anchors"]["n_items"]} '
            f'{escape(m["anchors"]["kind"])} items). Generated {escape(m["generated_at"])} by '
            f'judgekeeper {escape(m["judgekeeper_version"])}.</p>'),
           (f'<div class="verdict {_BANNER[m["status"]]}">{escape(m["status"])}: '
            f'{_text(m["verdict"])}</div>')]

    out.append("<h2>1. Who changed</h2>")
    keys = [*JUDGE_FIELDS, "created_at"]
    out.append(_rows(
        ["Field", "Old judge", "New judge"],
        [[k, f"<code>{_f(fps['old'].get(k))}</code>", f"<code>{_f(fps['new'].get(k))}</code>"]
         for k in keys],
        classes=["hl" if k in fps["changed_fields"] else "" for k in keys],
    ))
    seen = m["snapshots_seen"]
    out.append(f'<p class="muted">Highlighted rows changed. Snapshots served: old '
               f'<code>{_text(", ".join(seen["old"]) or "n/a")}</code>, new '
               f'<code>{_text(", ".join(seen["new"]) or "n/a")}</code>.</p>')

    out.append("<h2>2. Each judge against humans</h2>")
    out.append(f'<p class="muted">Mean over runs, with the range across runs. Positive class for '
               f'TPR/TNR is <code>{escape(vh["positive_label"])}</code>.</p>')
    out.append(_rows(
        ["Judge", "Runs", "Kappa", "TPR", "TNR"],
        [[f"old: {escape(old_model)}", str(vh["old"]["n_runs"]), _span(vh["old"]["kappa"]),
          _span(vh["old"]["tpr"]), _span(vh["old"]["tnr"])],
         [f"new: {escape(new_model)}", str(vh["new"]["n_runs"]), _span(vh["new"]["kappa"]),
          _span(vh["new"]["tpr"]), _span(vh["new"]["tnr"])]],
    ))
    out.append(f'<p class="muted">Kappa delta {_fmt(vh["kappa_delta"], True)}; noise band '
               f'±{_fmt(vh["noise_band"])} (the larger of each judge\'s run-to-run kappa spread '
               f'and min_band {_fmt(m["config"]["min_band"])}).</p>')

    out.append("<h2>3. Old judge against new judge</h2>")
    out.append('<div class="tiles">'
               + _tile("Kappa, old vs new majority", _f(jj["kappa"]))
               + _tile("Items whose verdict changed", _pct(jj["changed_share"]))
               + _tile("Changed, both judges stable", _pct(jj["changed_stable_share"]))
               + _tile("Changed within noise", str(jj["n_changed_within_noise"]))
               + _tile("Fixed / broken / net",
                       f'{jj["n_fixed"]} / {jj["n_broken"]} / {jj["net"]:+d}')
               + "</div>")
    out.append('<p class="muted">An item is stable for a judge when every one of its runs gave '
               "the same verdict. A change where either judge was flipping anyway is within "
               "noise. Changed-and-stable items are fixed (the new judge now agrees with the "
               "human label) or broken (it now disagrees).</p>")

    out.append("<h2>4. Per slice</h2>")
    if not m["slices"]:
        out.append("<p>No slices in this anchor set.</p>")
    else:
        out.append(_rows(
            ["Slice", "Items", "Old kappa", "New kappa", "Delta", "Changed and stable"],
            [[escape(s["slice"]), str(s["n"]), _f(s["old_kappa"]), _f(s["new_kappa"]),
              _fmt(s["delta"], True), str(s["n_changed_stable"])] for s in m["slices"]],
            num={1, 2, 3, 4, 5},
        ))

    out.append("<h2>5. Changed items</h2>")
    if not m["changed_items"]:
        out.append("<p>No item's majority verdict changed.</p>")
    else:
        def why(c: dict, side: str) -> str:
            return (f'<details><summary>{escape(side)}</summary>'
                    f'<div class="rationale">{_text(c[side + "_rationale"])}</div></details>')

        out.append(_rows(
            ["Item", "Slice", "Human", "Old", "New", "Outcome", "Rationales"],
            [[escape(c["id"]), _f(c["slice"]), escape(c["human"]), _f(c["old"]), _f(c["new"]),
              escape(c["outcome"].replace("_", " ")), why(c, "old") + why(c, "new")]
             for c in m["changed_items"]],
        ))

    out.append("<h2>6. Pass-rate bridge</h2>")
    pos = br["positive_name"]
    out.append(f'<p>How a production pass rate (here: "{escape(pos)}") is likely to move when you '
               "switch judges, estimated on the anchor set from both judges' majority verdicts, "
               "with Wilson 95% intervals.</p>")
    out.append(f'<p class="formula">{escape(br["formula"])}<br>a = {escape(br["a_means"])}<br>'
               f'b = {escape(br["b_means"])}</p>')
    rows = [["overall", _prop(br["overall"]["a"]), _prop(br["overall"]["b"]),
             str(br["overall"]["n_excluded"])]]
    rows += [[escape(s["slice"]), _prop(s["a"]), _prop(s["b"]), str(s["n_excluded"])]
             for s in br["per_slice"]]
    out.append(_rows(["", "a", "b", "No majority (left out)"], rows))
    ex = br["example"]
    if ex["new_rate"] is not None:
        a, b = br["overall"]["a"]["p"], br["overall"]["b"]["p"]
        out.append(f'<p>Worked example: if the old judge said "{escape(pos)}" on '
                   f'{ex["old_rate"]:.0%} of your production outputs, new_rate ≈ '
                   f"{ex['old_rate']:.2f} × {a:.2f} + {1 - ex['old_rate']:.2f} × {b:.2f} = "
                   f"<strong>{ex['new_rate']:.2f}</strong>.</p>")
    out.append(f'<p class="muted">{escape(br["caveat"])}</p>')

    out.append("<h2>7. Status</h2>")
    cfg = m["config"]
    out.append(
        f'<p><strong>{escape(m["status"])}</strong>. {_text(m["verdict"])}</p>'
        "<ul class=\"flags\">"
        "<li><code>BETTER</code> / <code>WORSE</code>: kappa vs humans moved by more than the "
        "noise band, by sign.</li>"
        "<li><code>DIFFERENT</code>: kappa inside the band, but more than "
        f"{cfg['max_changed_share']:.0%} of items changed while both judges were stable.</li>"
        "<li><code>EQUIVALENT</code>: kappa inside the band and at most "
        f"{cfg['max_changed_share']:.0%} changed and stable.</li></ul>"
    )

    title = f"Judge migration: {old_model} to {new_model}"
    return ("<!doctype html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
            f"<title>{escape(title)}</title><style>{CSS}{EXTRA_CSS}</style></head>"
            f"<body><main>{''.join(out)}</main></body></html>\n")
