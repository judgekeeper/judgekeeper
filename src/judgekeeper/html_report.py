"""Render report.json as a single self-contained HTML file. No external assets.

Free text (rationales, verdict text) and the judge fingerprint (the model id comes from the
provider) are scrubbed of credentials before they are escaped.
"""

from __future__ import annotations

from html import escape

from judgekeeper.anchors import NEGATIVE
from judgekeeper.fingerprint import is_unknown
from judgekeeper.redact import scrub

CSS = """
:root { --bg:#fff; --fg:#1d1d1f; --muted:#6b6b70; --line:#e3e3e6; --card:#f6f6f8;
  --bad:#b42318; --bad-bg:#fdecea; --ok:#067647; --ok-bg:#e8f6ee; --warn:#93370d;
  --warn-bg:#fef4e6; }
@media (prefers-color-scheme: dark) { :root { --bg:#141416; --fg:#ececf0; --muted:#9a9aa3;
  --line:#2c2c31; --card:#1c1c20; --bad:#ff8a80; --bad-bg:#3a1714; --ok:#7ee2a8;
  --ok-bg:#12301f; --warn:#fdb022; --warn-bg:#3a2a10; } }
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--fg);
  font:15px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
main { max-width: 980px; min-width: 0; margin: 0 auto; padding: 24px 16px 64px; }
h1 { font-size: 24px; margin: 0 0 4px; } h2 { font-size: 18px; margin: 36px 0 8px; }
.muted { color: var(--muted); } code { font-size: 13px; word-break: break-all; }
.verdict { padding: 14px 16px; border-radius: 8px; margin: 16px 0; font-weight: 600; }
.verdict.bad { background: var(--bad-bg); color: var(--bad); }
.verdict.ok { background: var(--ok-bg); color: var(--ok); }
.verdict.warn { background: var(--warn-bg); color: var(--warn); }
.tile .ci { color: var(--muted); font-size: 13px; font-variant-numeric: tabular-nums; }
ul.flags { padding-left: 20px; } ul.flags li { margin: 4px 0; }
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; }
.tile { background: var(--card); border-radius: 8px; padding: 12px 14px; }
.tile .v { font-size: 26px; font-weight: 650; font-variant-numeric: tabular-nums; }
.tile .k { color: var(--muted); font-size: 13px; }
.scroll { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; font-variant-numeric: tabular-nums; }
th, td { text-align: left; padding: 6px 10px; border-bottom: 1px solid var(--line);
  vertical-align: top; }
th { font-weight: 600; color: var(--muted); font-size: 13px; }
td.num, th.num { text-align: right; }
dl { display: grid; grid-template-columns: minmax(0, max-content) minmax(0, 1fr); gap: 4px 16px; margin: 0; }
dt { color: var(--muted); } dd { margin: 0; min-width: 0; }
details summary { cursor: pointer; }
.rationale { white-space: pre-wrap; font-size: 13px; max-height: 12em; overflow: auto; }
"""


def _f(x, digits: int = 3) -> str:
    if x is None:
        return "n/a"
    if isinstance(x, float):
        return f"{x:.{digits}f}"
    return escape(str(x))


def _text(x) -> str:
    """Escaped, scrubbed free text."""
    return escape(scrub(str(x)) or "")


def _pct(x) -> str:
    return "n/a" if x is None else f"{x:.1%}"


def _table(headers: list[str], rows: list[list[str]], num_cols: set[int] = frozenset()) -> str:
    head = "".join(
        f'<th class="num">{escape(h)}</th>' if i in num_cols else f"<th>{escape(h)}</th>"
        for i, h in enumerate(headers)
    )
    body = "".join(
        "<tr>" + "".join(
            f'<td class="num">{c}</td>' if i in num_cols else f"<td>{c}</td>"
            for i, c in enumerate(row)
        ) + "</tr>"
        for row in rows
    )
    return f'<div class="scroll"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def _tile(label: str, value: str, ci: str = "") -> str:
    ci_html = f'<div class="ci">{ci}</div>' if ci else ""
    return (f'<div class="tile"><div class="v">{value}</div>{ci_html}'
            f'<div class="k">{escape(label)}</div></div>')


def _ci(ci: dict | None) -> str:
    if not ci or ci.get("lo") is None:
        return ""
    return f"95% CI {ci['lo']:.2f} to {ci['hi']:.2f} (n={ci['n']})"


def _fp_value(fp: dict, key: str) -> str:
    """A fingerprint field for display: unknown fields say so."""
    value = fp.get(key)
    if key != "created_at" and is_unknown(key, value):
        return "unknown"
    if key == "endpoint" and value is None:
        return "provider default"
    return _text(value) if isinstance(value, str) else _f(value)


_LEVEL_CLASS = {"usable": "ok", "usable_with_care": "warn", "not_trustworthy": "bad"}


def render_html(r: dict) -> str:
    fp = r["fingerprint"]
    h = r["headline"]
    nf = r["noise_floor"]
    pb = r["position_bias"]
    pos = h["positive_label"]
    level = r["verdict"].get("level")
    if level is None:  # reports written before verdict levels existed
        level = "usable" if h["kappa_mean"] is not None and h["kappa_mean"] >= 0.6 \
            else "not_trustworthy"
    src = r.get("source") or {"kind": "judgekeeper"}
    out = []
    out.append(f"<h1>Judge validation report</h1>"
               f'<p class="muted">{_fp_value(fp, "provider")} / '
               f'{_fp_value(fp, "model")} on '
               f'{escape(r["anchors"]["file"])} ({r["anchors"]["n_items"]} {escape(r["anchors"]["kind"])} '
               f'items, {r["n_runs"]} runs). Generated {escape(r["generated_at"])} by judgekeeper '
               f'{escape(r["judgekeeper_version"])}.</p>')

    out.append(f'<div class="verdict {_LEVEL_CLASS.get(level, "bad")}">'
               f'{_text(r["verdict"]["summary"])}</div>')
    if r["verdict"]["flags"]:
        out.append('<ul class="flags">' + "".join(
            f"<li>{_text(f['message'])}</li>" for f in r["verdict"]["flags"]) + "</ul>")
    for note in r.get("notes", []):
        out.append(f'<p class="muted">{_text(note)}</p>')

    out.append("<h2>Headline metrics</h2>")
    out.append('<p class="muted">Mean over runs, judge vs human labels. '
               f'Positive class for TPR/TNR is <code>{escape(pos)}</code>. TPR is the share of '
               "human-positive items the judge also calls positive; TNR the same for negatives."
               "</p>")
    out.append('<div class="tiles">'
               + _tile("TPR", _f(h["tpr_mean"]), _ci(h.get("tpr_ci")))
               + _tile("TNR", _f(h["tnr_mean"]), _ci(h.get("tnr_ci")))
               + _tile("Cohen's kappa", _f(h["kappa_mean"]))
               + _tile("Accuracy", _f(h["accuracy_mean"]))
               + "</div>")
    out.append('<p class="muted">Kappa is chance-corrected agreement with the human labels; '
               "TPR and TNR are the numbers to act on.</p>")
    errors = r.get("errors")
    if errors and errors["n"]:
        out.append(f'<p class="muted">{errors["n"]} of {errors["n_judgments"]} judgments '
                   f'({errors["rate"]:.1%}) were judge errors (raised, returned nothing or '
                   "unparseable). They are left out of every metric above.</p>")
    out.append(f'<p class="muted">Kappa range across runs: {_f(h["kappa_min"])} to '
               f'{_f(h["kappa_max"])}.</p>')
    out.append(_table(
        ["Run", "File", "TPR", "TNR", "Kappa", "Accuracy", "Invalid", "Errors"],
        [[str(x["run"]), escape(x["file"]), _f(x["tpr"]), _f(x["tnr"]), _f(x["kappa"]),
          _f(x["accuracy"]), str(x["n_invalid"]), str(x.get("n_error", 0))] for x in r["runs"]],
        num_cols={2, 3, 4, 5, 6, 7},
    ))

    out.append("<h2>Confusion matrix</h2>")
    out.append('<p class="muted">Majority verdict across runs vs human label. Rows: human. '
               "Columns: judge.</p>")
    mc = nf["majority_vs_human"]["confusion"]
    neg = NEGATIVE[r["anchors"]["kind"]]
    out.append(_table(
        ["Human \\ Judge", f"judge {escape(pos)}", "judge other"],
        [[f"human {escape(pos)}", f"{mc['tp']} (TP)", f"{mc['fn']} (FN)"],
         [f"human {escape(neg)}", f"{mc['fp']} (FP)", f"{mc['tn']} (TN)"]],
        num_cols={1, 2},
    ))
    out.append(f'<p class="muted">"Judge other" includes {mc["invalid"]} items with no majority '
               f'or an unparseable verdict. Majority-vote kappa '
               f'{_f(nf["majority_vs_human"]["kappa"])}, '
               f'TPR {_f(nf["majority_vs_human"]["tpr"])}, '
               f'TNR {_f(nf["majority_vs_human"]["tnr"])}.</p>')

    out.append("<h2>Noise floor</h2>")
    if nf["n_runs"] < 2:
        out.append("<p>Noise floor: <strong>unknown: one run supplied</strong>. Repeatability "
                   "is not measured; judge 3 or more runs, or supply a run column.</p>")
    else:
        out.append('<div class="tiles">'
                   + _tile("Items that flipped", _pct(nf["items_flipped_fraction"]))
                   + _tile("Mean per-item flip rate", _f(nf["mean_item_flip_rate"]))
                   + _tile("Mean run-vs-run kappa", _f(nf["mean_pairwise_kappa"]))
                   + _tile("Test-retest agreement", _f(nf["test_retest_agreement"]))
                   + "</div>")
        out.append('<p class="muted">Per-item flip rate is the share of runs that disagree with '
                   "the item's majority verdict. High test-retest agreement does not mean the "
                   "judge is right: compare with kappa against humans above.</p>")
        out.append(_table(
            ["Runs", "Kappa", "Agreement"],
            [[f"{p['runs'][0]} vs {p['runs'][1]}", _f(p["kappa"]), _f(p["agreement"])]
             for p in nf["pairwise_kappa"]],
            num_cols={1, 2},
        ))
        flipped = [row for row in nf["per_item"] if row["flip_rate"] > 0]
        if flipped:
            out.append(f"<details><summary>{len(flipped)} items that flipped</summary>" + _table(
                ["Item", "Human", "Verdicts by run", "Majority", "Flip rate"],
                [[escape(row["id"]), escape(row["human"]),
                  escape(", ".join(str(v) for v in row["verdicts"])), _f(row["majority"]),
                  _f(row["flip_rate"])] for row in flipped],
                num_cols={4},
            ) + "</details>")

    out.append("<h2>Position bias</h2>")
    if pb is None:
        out.append("<p>Not applicable: single-output anchor set.</p>"
                   if r["anchors"]["kind"] != "pairwise"
                   else "<p>Not measured: no BA-order verdicts were supplied.</p>")
    else:
        out.append('<div class="tiles">'
                   + _tile("AB/BA verdicts disagree", _pct(pb["inconsistency_rate"]))
                   + _tile("P(picks first slot)", _f(pb["p_first"]))
                   + _tile("|P(first) - 0.5|", _f(pb["first_position_bias"]))
                   + _tile("Kappa, BA order", _f(pb["kappa_ba_mean"]))
                   + "</div>")
        out.append('<p class="muted">Each pairwise item is judged twice, once with output A shown '
                   "first and once with output B shown first. Headline metrics use the AB order."
                   "</p>")
        out.append(_table(
            ["Run", "AB/BA disagree", "P(first)", "|P(first) - 0.5|"],
            [[str(x["run"]), _pct(x["inconsistency_rate"]), _f(x["p_first"]),
              _f(x["first_position_bias"])] for x in pb["per_run"]],
            num_cols={1, 2, 3},
        ))

    out.append("<h2>Per-slice breakdown</h2>")
    if not r["slices"]:
        out.append("<p>No slices in this anchor set.</p>")
    else:
        out.append(_table(
            ["Slice", "Items", "Kappa", "TPR", "TNR", "Accuracy"],
            [[escape(s["slice"]), str(s["n"]), _f(s["kappa_mean"]), _f(s["tpr_mean"]),
              _f(s["tnr_mean"]), _f(s["accuracy_mean"])] for s in r["slices"]],
            num_cols={1, 2, 3, 4, 5},
        ))
        out.append('<p class="muted">Means over runs.</p>')

    out.append("<h2>Disagreements</h2>")
    out.append(f'<p class="muted">{len(r["disagreements"])} items where at least one run disagreed '
               "with the human label. Rationale is from the first disagreeing run.</p>")
    if r["disagreements"]:
        out.append(_table(
            ["Item", "Slice", "Human", "Verdicts by run", "Rationale"],
            [[escape(d["id"]), _f(d["slice"]), escape(d["human"]),
              escape(", ".join(str(v) for v in d["verdicts"])),
              (f'<details><summary>run {d["rationale_run"]}</summary>'
              f'<div class="rationale">{_text(d["rationale"])}</div></details>')]
             for d in r["disagreements"]],
        ))

    out.append("<h2>Judge fingerprint</h2><dl>")
    for key in ("provider", "model", "snapshot", "endpoint", "prompt_hash", "rubric_version",
                "temperature", "created_at"):
        out.append(f"<dt>{key}</dt><dd><code>{_fp_value(fp, key)}</code></dd>")
    out.append(f"<dt>source</dt><dd><code>{_text(src.get('kind'))}"
               + (f" (format version {_text(src['version'])})"
                  if src.get("version") is not None else "")
               + (f" {_text(src['file'])}" if src.get("file") else "")
               + (f" ({_text(src['metric'])})" if src.get("metric") else "") + "</code></dd>")
    norm = r.get("normaliser")
    if norm:
        rule = norm.get("pass_if") or "none"
        mapping = ", ".join(f"{k}={v}" for k, v in norm.get("label_map", {}).items())
        out.append(f"<dt>pass-if rule</dt><dd><code>{_text(rule)}</code></dd>"
                   f"<dt>label map</dt><dd><code>{_text(mapping)}</code></dd>")
    out.append(f"<dt>snapshots seen</dt><dd><code>{_text(', '.join(r['snapshots_seen']) or 'n/a')}"
               "</code></dd>")
    out.append(f"<dt>anchor sha256</dt><dd><code>{escape(r['anchors']['sha256'])}</code></dd>")
    out.append("</dl>")

    title = scrub(f"Judge report: {fp.get('model') or 'unknown judge'}")
    return ("<!doctype html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
            f"<title>{escape(title)}</title><style>{CSS}</style></head>"
            f"<body><main>{''.join(out)}</main></body></html>\n")
