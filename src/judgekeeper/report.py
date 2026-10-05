"""Build the validation report (report.json) from an anchor set and a directory of runs.

Schema version 2 adds `items`: per anchor item, the verdict of every run and the
majority, in AB order and for pairwise sets also in BA order. Version 1 reports have no
`schema_version` field and no `items`.

Later versions add `source.version`, `source.notes` (copied into `notes`) and `source.warnings`
(copied into the verdict flags) for imported results.

Other keys were added without changing any the gate reads: `source`, `normaliser`, `errors`,
`label_quality`, `notes`, `verdict.level`, `headline.tpr_ci` / `tnr_ci` / `n_positive` /
`n_negative`, and `noise_floor.status`. With one run, the noise-floor numbers are null and
`noise_floor.status` says "unknown: one run supplied", never zero.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from judgekeeper import __version__
from judgekeeper.anchors import NEGATIVE, PAIRWISE, POSITIVE, AnchorHashMismatch, load_verified
from judgekeeper.fingerprint import JudgeFingerprint, unknown_fields, utc_now
from judgekeeper.judgments import JudgmentsError, default_source, read_run
from judgekeeper.metrics import ERROR, _mean, agreement, noise_floor, position_bias, wilson_interval
from judgekeeper.redact import scrub, scrub_fingerprint

REPORT_SCHEMA_VERSION = 2

# Verdict thresholds.
KAPPA_GATE = 0.6
POSITION_BIAS_MAX = 0.10
FLIP_RATE_MAX = 0.10
# TPR and TNR are the numbers to act on: below RATE_GATE the judge is not
# trustworthy as a gate, below RATE_CARE it is usable with care.
RATE_GATE = 0.80
RATE_CARE = 0.90
ERROR_RATE_MAX = 0.02
# Label quality: fewer labeled items than this gives wide error bars.
MIN_LABELS = 60
MAX_CLASS_SHARE = 0.80
NOISE_UNKNOWN = "unknown: one run supplied"

TRUSTWORTHY = "usable"
WITH_CARE = "usable_with_care"
NOT_TRUSTWORTHY = "not_trustworthy"


class ReportError(Exception):
    """Inputs are unusable (missing runs, mixed judges, incomplete runs)."""


def _load_runs(runs_dir: Path, items: list[dict], sha: str) -> list[dict]:
    files = sorted(runs_dir.glob("*.jsonl")) if runs_dir.is_dir() else []
    if not files:
        raise ReportError(f"no judgments files (*.jsonl) in {runs_dir}")
    ids = [i["id"] for i in items]
    runs = []
    for n, path in enumerate(files, 1):
        try:
            header, records = read_run(path)
        except JudgmentsError as e:
            raise ReportError(str(e)) from None
        if header.get("anchors_sha256") != sha:
            raise AnchorHashMismatch(
                f"{path} was recorded against anchor set {header.get('anchors_sha256')}, "
                f"not the frozen set {sha}"
            )
        missing = [i for i in ids if i not in records]
        if missing:
            raise ReportError(f"{path} has no judgment for {len(missing)} items, e.g. {missing[0]}")
        runs.append(
            {
                "run": n,
                "file": path.name,
                "fingerprint": JudgeFingerprint.from_dict(header["fingerprint"]),
                "records": records,
                "header": header,
            }
        )
    first = runs[0]["fingerprint"]
    for r in runs[1:]:
        if r["fingerprint"].identity() != first.identity():
            raise ReportError(
                f"{r['file']} was produced by a different judge than {runs[0]['file']} "
                "(provider, model, prompt hash, rubric version or temperature differ)"
            )
    return runs


def _ci(p: float | None, n: int) -> dict:
    lo, hi = wilson_interval(p, n)
    return {"lo": lo, "hi": hi, "n": n}


def _flag(code: str, message: str) -> dict:
    return {"code": code, "message": message}


def _fmt(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.2f}"


def _rate_flags(name: str, value: float | None) -> list[dict]:
    if value is None:
        return [_flag(f"no_{name.lower()}", f"{name} could not be measured: no human "
                                            "labels of that class were scored.")]
    if value < RATE_GATE:
        return [_flag(f"low_{name.lower()}", f"{name} is {_fmt(value)} (below {RATE_GATE:.2f}): "
                                             "not trustworthy as a gate.")]
    if value < RATE_CARE:
        return [_flag(f"{name.lower()}_with_care",
                      f"{name} is {_fmt(value)} (between {RATE_GATE:.2f} and {RATE_CARE:.2f}): "
                      "usable with care.")]
    return []


def label_quality(manifest: dict) -> dict:
    """Warnings about the human labels themselves: too few, or one class dominating."""
    dist = manifest["label_distribution"]
    n = sum(dist.values())
    top_label, top_n = max(dist.items(), key=lambda kv: kv[1]) if dist else (None, 0)
    share = top_n / n if n else None
    flags = []
    if n < MIN_LABELS:
        items = "item" if n == 1 else "items"
        flags.append(_flag("few_labels", f"Only {n} labeled {items}: error bars are wide; aim "
                                         "for about 100."))
    if share is not None and share > MAX_CLASS_SHARE:
        flags.append(_flag("lopsided_labels",
                           f"{share:.0%} of human labels are {top_label!r} (more lopsided than "
                           f"80/20): the rarer class has few examples, so its rate is "
                           "poorly measured; aim for a more even split."))
    return {"n_labeled": n, "largest_class": top_label, "largest_class_share": share,
            "flags": flags}


def _verdict(headline: dict, nf: dict, pb: dict | None, n_runs: int, n_invalid: int,
             errors: dict, unknown: list[str], quality: dict, extra: list[dict]) -> dict:
    flags = []
    kappa, tpr, tnr = headline["kappa_mean"], headline["tpr_mean"], headline["tnr_mean"]
    flags += _rate_flags("TPR", tpr) + _rate_flags("TNR", tnr)
    if kappa is None:
        # Never "n/a (below 0.6)": say that there is no number, and why.
        why = ("every judgment was a judge error, so nothing was scored"
               if errors["n"] == errors["n_judgments"] else
               "the human labels and the judge's verdicts are all the same single answer, so "
               "agreement cannot be told from chance")
        flags.append(_flag("no_kappa", f"Kappa vs human labels could not be computed: {why}. "
                                       "Not trustworthy as a gate."))
    elif kappa < KAPPA_GATE:
        flags.append(_flag(
            "low_kappa",
            f"Kappa vs human labels is {_fmt(kappa)} (below {KAPPA_GATE}): "
            "not trustworthy as a gate.",
        ))
    if pb is not None and pb["inconsistency_rate"] is not None:
        if pb["inconsistency_rate"] > POSITION_BIAS_MAX:
            flags.append(_flag(
                "position_inconsistent",
                f"Swapping the order of the two outputs changes the verdict on "
                f"{pb['inconsistency_rate']:.1%} of items (above {POSITION_BIAS_MAX:.0%}): "
                "position bias.",
            ))
        if pb["first_position_bias"] > POSITION_BIAS_MAX:
            side = "first" if pb["p_first"] > 0.5 else "second"
            flags.append(_flag(
                "position_preference",
                f"The judge picks the {side} output {max(pb['p_first'], 1 - pb['p_first']):.0%} "
                f"of the time (|P(first) - 0.5| = {pb['first_position_bias']:.2f}, above "
                f"{POSITION_BIAS_MAX}): position bias.",
            ))
    if n_runs < 2:
        flags.append(_flag(
            "single_run",
            "Noise floor unknown: one run supplied. Judge 3 or more runs (or supply a run "
            "column) to measure it.",
        ))
    elif nf["items_flipped_fraction"] > FLIP_RATE_MAX:
        flags.append(_flag(
            "noisy",
            f"{nf['items_flipped_fraction']:.1%} of items changed verdict between identical runs "
            f"(above {FLIP_RATE_MAX:.0%}): noisy, use majority of runs.",
        ))
    if n_invalid:
        flags.append(_flag(
            "invalid_verdicts",
            f"{n_invalid} judgments could not be parsed into a verdict; counted as wrong.",
        ))
    if errors["rate"] > ERROR_RATE_MAX:
        flags.append(_flag(
            "judge_errors",
            f"{errors['n']} of {errors['n_judgments']} judgments ({errors['rate']:.1%}) were "
            f"judge errors (raised, returned nothing or unparseable; above "
            f"{ERROR_RATE_MAX:.0%}). They are excluded from the metrics, not counted as fail.",
        ))
    if unknown:
        flags.append(_flag("identity_incomplete",
                           f"judge identity incomplete: {', '.join(unknown)}"))
    flags += quality["flags"]
    flags += extra

    numbers = (f"TPR {_fmt(tpr)}, TNR {_fmt(tnr)}, kappa {_fmt(kappa)} against human labels.")
    rates_known = tpr is not None and tnr is not None
    if (kappa is None or kappa < KAPPA_GATE or not rates_known
            or min(tpr, tnr) < RATE_GATE):
        level, summary = NOT_TRUSTWORTHY, f"Not trustworthy as a gate: {numbers}"
    elif min(tpr, tnr) < RATE_CARE:
        level, summary = WITH_CARE, f"Usable with care: {numbers}"
    else:
        level, summary = TRUSTWORTHY, f"Usable as a gate: {numbers}"
    if level != NOT_TRUSTWORTHY and flags:
        summary += " Read the flags below before relying on it."
    return {"summary": summary, "level": level, "flags": flags}


def load_runs(anchors_path: str | Path, runs_dir: str | Path) -> tuple[list[dict], dict,
                                                                        list[dict]]:
    """Verify the anchor set and load every run in `runs_dir`: (items, manifest, runs)."""
    items, manifest = load_verified(anchors_path)
    return items, manifest, _load_runs(Path(runs_dir), items, manifest["sha256"])


def build_report(anchors_path: str | Path, runs_dir: str | Path) -> dict:
    items, manifest, runs = load_runs(anchors_path, runs_dir)
    return report_from_runs(anchors_path, items, manifest, runs)


def _item_rows(items: list[dict], runs: list[dict], verdicts_by_item: dict,
               majority: dict, pairwise: bool) -> list[dict]:
    if pairwise:
        ba_by_item = {
            i["id"]: [r["records"][i["id"]].get("verdict_ba") for r in runs] for i in items
        }
        majority_ba = noise_floor(ba_by_item)["majority"]
    rows = []
    for i in items:
        row = {
            "id": i["id"],
            "slice": i.get("slice"),
            "human": i["human_label"],
            "verdicts": verdicts_by_item[i["id"]],
            "majority": majority[i["id"]],
        }
        if pairwise:
            row["verdicts_ba"] = ba_by_item[i["id"]]
            row["majority_ba"] = majority_ba[i["id"]]
        rows.append(row)
    return rows


def report_from_runs(anchors_path: str | Path, items: list[dict], manifest: dict,
                     runs: list[dict]) -> dict:
    kind = manifest["kind"]
    pos, neg = POSITIVE[kind], NEGATIVE[kind]
    human = [i["human_label"] for i in items]
    by_id = {i["id"]: i for i in items}

    per_run = []
    for r in runs:
        verdicts = [r["records"][i["id"]].get("verdict") for i in items]
        res = agreement(human, verdicts, pos, neg)
        res["disagreements"] = [
            {
                "id": i["id"],
                "human": i["human_label"],
                "verdict": v,
                "rationale": r["records"][i["id"]].get("rationale", ""),
            }
            for i, v in zip(items, verdicts)
            if v != i["human_label"] and v != ERROR
        ]
        per_run.append({"run": r["run"], "file": r["file"], **res})

    kappas = [r["kappa"] for r in per_run if r["kappa"] is not None]
    # Runs are repeated measures of the same items, so the interval's n is the number of
    # scored human-positive (or negative) items, not items x runs; the smallest over runs.
    n_pos = min(r["confusion"]["tp"] + r["confusion"]["fn"] for r in per_run)
    n_neg = min(r["confusion"]["tn"] + r["confusion"]["fp"] for r in per_run)
    tpr_mean = _mean([r["tpr"] for r in per_run])
    tnr_mean = _mean([r["tnr"] for r in per_run])
    headline = {
        "tpr_mean": tpr_mean,
        "tpr_ci": _ci(tpr_mean, n_pos),
        "tnr_mean": tnr_mean,
        "tnr_ci": _ci(tnr_mean, n_neg),
        "kappa_mean": _mean([r["kappa"] for r in per_run]),
        "kappa_min": min(kappas) if kappas else None,
        "kappa_max": max(kappas) if kappas else None,
        "accuracy_mean": _mean([r["accuracy"] for r in per_run]),
        "positive_label": pos,
        "n_positive": n_pos,
        "n_negative": n_neg,
    }

    verdicts_by_item = {
        i["id"]: [r["records"][i["id"]].get("verdict") for r in runs] for i in items
    }
    nf = noise_floor(verdicts_by_item)
    majority = nf.pop("majority")
    nf["majority_vs_human"] = agreement(human, [majority[i["id"]] for i in items], pos, neg)
    for row in nf["per_item"]:
        row["human"] = by_id[row["id"]]["human_label"]
    if len(runs) < 2:
        # One run measures nothing about repeatability: say unknown, never zero.
        nf["items_flipped_fraction"] = None
        nf["mean_item_flip_rate"] = None
        nf["status"] = NOISE_UNKNOWN
    else:
        nf["status"] = "measured"

    pb = None
    has_ba = any("verdict_ba" in rec for r in runs for rec in r["records"].values())
    if kind == PAIRWISE and has_ba:
        pb_runs = []
        all_ab, all_ba, kappa_ba = [], [], []
        for r in runs:
            ab = [r["records"][i["id"]].get("verdict") for i in items]
            ba = [r["records"][i["id"]].get("verdict_ba") for i in items]
            pb_runs.append({"run": r["run"], **position_bias(ab, ba)})
            all_ab += ab
            all_ba += ba
            kappa_ba.append(agreement(human, ba, pos, neg)["kappa"])
        pb = {**position_bias(all_ab, all_ba), "kappa_ba_mean": _mean(kappa_ba), "per_run": pb_runs}

    slices = []
    slice_ids: dict[str, list[int]] = defaultdict(list)
    for idx, i in enumerate(items):
        if "slice" in i:
            slice_ids[i["slice"]].append(idx)
    for name in sorted(slice_ids):
        idxs = slice_ids[name]
        h = [human[k] for k in idxs]
        results = []
        for r in runs:
            v = [r["records"][items[k]["id"]].get("verdict") for k in idxs]
            results.append(agreement(h, v, pos, neg))
        slices.append({
            "slice": name,
            "n": len(idxs),
            "kappa_mean": _mean([x["kappa"] for x in results]),
            "tpr_mean": _mean([x["tpr"] for x in results]),
            "tnr_mean": _mean([x["tnr"] for x in results]),
            "accuracy_mean": _mean([x["accuracy"] for x in results]),
        })

    disagreements = []
    for i in items:
        vs = verdicts_by_item[i["id"]]
        wrong = [k for k, v in enumerate(vs) if v != i["human_label"] and v != ERROR]
        if not wrong:
            continue
        rec = runs[wrong[0]]["records"][i["id"]]
        disagreements.append({
            "id": i["id"],
            "slice": i.get("slice"),
            "human": i["human_label"],
            "verdicts": vs,
            "majority": majority[i["id"]],
            "rationale": rec.get("rationale", ""),
            "rationale_run": runs[wrong[0]]["run"],
        })

    # Scrubbed here as well as on the way to disk: a run file may predate that, or be imported.
    snapshots = sorted({scrub(s) for s in {
        rec["fingerprint"].get("snapshot") or ""
        for r in runs for rec in r["records"].values()
    } - {""}})
    n_invalid = sum(r["n_invalid"] for r in per_run)
    n_judgments = len(items) * len(runs)
    n_errors = sum(r["n_error"] for r in per_run)
    errors = {
        "n": n_errors,
        "n_judgments": n_judgments,
        "rate": n_errors / n_judgments if n_judgments else 0.0,
        "max_rate": ERROR_RATE_MAX,
        "per_run": [{"run": r["run"], "n": r["n_error"]} for r in per_run],
        "items": sorted({i["id"] for r in runs for i in items
                         if r["records"][i["id"]].get("verdict") == ERROR}),
    }
    fingerprint = scrub_fingerprint(runs[0]["fingerprint"].to_dict())
    unknown = unknown_fields(fingerprint)
    quality = label_quality(manifest)
    header = runs[0]["header"]
    source = {**default_source(), **(header.get("source") or {})}
    notes = []
    if source.get("ids_derived"):
        why = "no id column was given" if source.get("kind") == "table" else \
            "the source has no stable id"
        notes.append(f"Item ids were derived from a hash of each item's input and output ({why}); "
                     "they change if that text changes.")
    notes += [n for n in source.get("notes") or [] if isinstance(n, str)]
    source_flags = [_flag("import_warning", w) for w in source.get("warnings") or []
                    if isinstance(w, str)]
    if kind == PAIRWISE and not has_ba:
        notes.append("Position bias not measured: no BA-order verdicts were supplied.")

    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "judgekeeper_version": __version__,
        "generated_at": utc_now(),
        "anchors": {
            "file": Path(anchors_path).name,
            "sha256": manifest["sha256"],
            "n_items": len(items),
            "kind": kind,
            "label_distribution": manifest["label_distribution"],
            "slice_counts": manifest["slice_counts"],
        },
        "fingerprint": fingerprint,
        "fingerprint_unknown": unknown,
        "source": source,
        "normaliser": header.get("normaliser"),
        "snapshots_seen": snapshots,
        "n_runs": len(runs),
        "headline": headline,
        "verdict": _verdict(headline, nf, pb, len(runs), n_invalid, errors, unknown, quality,
                            source_flags),
        "errors": errors,
        "label_quality": {k: v for k, v in quality.items() if k != "flags"},
        "notes": notes,
        "runs": per_run,
        "noise_floor": nf,
        "position_bias": pb,
        "slices": slices,
        "disagreements": disagreements,
        "items": _item_rows(items, runs, verdicts_by_item, majority, kind == PAIRWISE),
    }


_PLAIN_VERDICT = {TRUSTWORTHY: "It is usable as a gate.", WITH_CARE: "It is usable with care.",
                  NOT_TRUSTWORTHY: "It is not trustworthy as a gate."}


def plain_summary(report: dict) -> str:
    """The result in plain words, printed before the numbers. Print-only: never in a report.

    Always both rates (the mean over runs, as a whole percent), never one combined figure.
    A rate that could not be measured is said in words, with no number.
    """
    h = report["headline"]

    def pct(key: str) -> str | None:
        return None if h.get(key) is None else f"{h[key]:.0%}"

    passed, failed = pct("tpr_mean"), pct("tnr_mean")
    if h.get("positive_label") == "A":  # pairwise: people chose A or B
        if passed is None:
            first = "No answers where people preferred A were in this set."
            second = (None if failed is None else
                      f"When people preferred B, the judge agreed {failed} of the time.")
        else:
            first = f"When people preferred A, the judge agreed {passed} of the time."
            second = None if failed is None else f"When people preferred B, {failed}."
        second = second or "No answers where people preferred B were in this set."
    else:
        first = ("No answers that people passed were in this set." if passed is None else
                 f"Of the answers people passed, the judge passed {passed}.")
        second = ("No answers that people failed were in this set." if failed is None else
                  f"Of the answers people failed, the judge failed {failed}.")
    parts = [first, second, _PLAIN_VERDICT.get(report["verdict"].get("level"))]
    return " ".join(p for p in parts if p)
