"""Do judgekeeper's ranges hold the true value on real data? The real-data check.

    pip install pyarrow                  # for this script only: MT-Bench is a parquet file
    python scripts/real_data_check.py    # writes docs/examples/real-data-check/

Public datasets exist where an LLM judge and people both decided on the same answers, so how
often the judge agrees with all of the people's labels is known. This script pretends a person
labeled only a few of them, as `judgekeeper start` picks, works out the numbers with
judgekeeper's own weighted.corrected, and counts how often each range held the value worked
out from all of the dataset's human labels. No judge is called; nothing costs money.

The pools (every item has a saved judge verdict and a human label; nothing is dropped because
of what the judge said):

1. LLMBar judged by Claude Haiku 4.5: the items in the committed
   docs/examples/llmbar-haiku/report.json. "Is output A the better one?" Judge pass: run 1
   says A. Human pass: LLMBar's gold label is A.
2. MT-Bench human judgments, GPT-4 as the judge. "Is model_b's answer better than model_a's?",
   model_a and model_b as GPT-4 saw them; people's votes in the other order are flipped.
   Judge pass: GPT-4 says model_b (its ties are not a pass). Human pass: more than half of the
   votes on that question, turn and pair say model_b (ties and split votes are not a pass).
3. The LLMJudge benchmark, three submitted runs as judges: TREC Deep Learning 2023 passages
   graded 0 to 3 by NIST assessors and by each run. Pass: grade 2 or 3 on each side.

One check: shuffle each group of the pool (the judge's passes, its fails), label n from each,
count how many the person marked Correct, and call weighted.corrected. Three designs, CHECKS
checks each with a fixed seed: 25 + 25, 30 + 30, and start's stopping rule (BLOCK from each
group at a time until TARGET Correct and TARGET Wrong). For each, how often the TPR, TNR and
real pass rate ranges held the value from all labels, their average width, the median error,
and the plain rates over the same labels without the correction, for contrast.

The data is downloaded from fixed revisions, checked against its sha256, and kept in a cache
folder outside the repository (--cache DIR to choose it). It is never committed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import statistics
import sys
import urllib.request
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from judgekeeper import weighted

OUT = ROOT / "docs" / "examples" / "real-data-check"
LLMBAR = ROOT / "docs" / "examples" / "llmbar-haiku" / "report.json"
SEED = 20261009
CHECKS = 1000
SIZES = (25, 30)
BLOCK = 5  # from each group: start's blocks of 10, half from each
TARGET = 25  # Correct and Wrong labels before start calls a check reliable
METRICS = ("tpr", "tnr", "real_pass_rate")
DESIGNS = ("25+25", "30+30", "start_rule")
DIGITS = 6  # the report's floats, so the same run gives the same file on every machine

_HF = ("https://huggingface.co/datasets/lmsys/mt_bench_human_judgments/resolve/"
       "f7d2896d2cc5d80f8b55c2bbc722613555233c25/data/")
_GH = ("https://raw.githubusercontent.com/llm4eval/LLMJudge-benchmark/"
       "0e2024814e3192cfc662ecee56dbd16b2536a7de/")
DATASETS = {
    "llmbar": {
        "name": "LLMBar",
        "licence": "MIT",
        "source": "https://github.com/princeton-nlp/LLMBar",
        "revision": "900616bff90b6c6c8e1681f7d079250637c55992",
        "attribution": ("Zeng et al. (2024), Evaluating Large Language Models at Evaluating "
                        "Instruction Following, ICLR 2024. The judge verdicts are judgekeeper's "
                        "own run of claude-haiku-4-5-20251001, kept in "
                        "docs/examples/llmbar-haiku/report.json."),
        "files": [],
    },
    "mtbench": {
        "name": "MT-Bench human judgments",
        "licence": "CC-BY-4.0",
        "source": "https://huggingface.co/datasets/lmsys/mt_bench_human_judgments",
        "revision": "f7d2896d2cc5d80f8b55c2bbc722613555233c25",
        "attribution": ("Zheng et al. (2023), Judging LLM-as-a-Judge with MT-Bench and Chatbot "
                        "Arena, NeurIPS 2023 Datasets and Benchmarks. Licensed CC-BY-4.0. "
                        "Changed here: each item turned into one yes/no question as described "
                        "in this report; no data is copied into this repository."),
        "files": [
            {"file": "mtbench/gpt4_pair.parquet",
             "url": _HF + "gpt4_pair-00000-of-00001-c0b431264a82ddc0.parquet",
             "sha256": "57068327ffb5f8fddb15fedbbfe40b26fe862da2326331e5cf64a42320a00e71"},
            {"file": "mtbench/human.parquet",
             "url": _HF + "human-00000-of-00001-25f4910818759289.parquet",
             "sha256": "4877bc46a40929f4082c3c79593700fb897b1d6c7f4c473032694a01322f5769"},
        ],
    },
    "llmjudge": {
        "name": "LLMJudge benchmark",
        "licence": "MIT",
        "source": "https://github.com/llm4eval/LLMJudge-benchmark",
        "revision": "0e2024814e3192cfc662ecee56dbd16b2536a7de",
        "attribution": ("Rahmani et al. (2024), LLMJudge: LLMs for Relevance Judgments, "
                        "LLM4Eval workshop at SIGIR 2024. Grades by NIST assessors for TREC Deep "
                        "Learning 2023 and by the submitted runs; only grades and ids are read."),
        "files": [
            {"file": "llmjudge/qrels.txt",
             "url": _GH + "llmjudge/qrels/llmjudge_test_qrel_idx.txt",
             "sha256": "3a2169a62cecf8725acf402be3222f53399fd5b3467f9f734aa3b2bbd583426c"},
            {"file": "llmjudge/RMITIR-GPT4o.txt",
             "url": _GH + "submissions/scores/RMITIR-GPT4o.txt",
             "sha256": "7b2a67e6b6215f84377c5b9b3b622aeae6fff54e03806f7b90caec36379293d6"},
            {"file": "llmjudge/willia-umbrela1.txt",
             "url": _GH + "submissions/scores/willia-umbrela1.txt",
             "sha256": "a7a40aca152a13313b7e39e5356d876f3f7b0d1d8f3ddadc3c4185bde350db01"},
            {"file": "llmjudge/NISTRetrieval-instruct0.txt",
             "url": _GH + "submissions/scores/NISTRetrieval-instruct0.txt",
             "sha256": "e4b1d4dc953bed2aa510a111bb221d4c70864778f665b3b26b879f9dae8d8658"},
        ],
    },
}
_RELEVANT = ("Is this passage relevant to the question (grade 2 or 3 of 0 to 3)?",
             "the run's grade is 2 or 3", "the NIST assessor's grade is 2 or 3")
POOLS = {
    "llmbar-haiku": {
        "title": "LLMBar × Claude Haiku 4.5", "dataset": "llmbar", "judge": "Claude Haiku 4.5",
        "question": "Is output A the better of the two?",
        "judge_pass": "run 1 of the saved runs says A",
        "human_pass": "LLMBar's gold label is A"},
    "mtbench-gpt4": {
        "title": "MT-Bench × GPT-4", "dataset": "mtbench", "judge": "GPT-4",
        "question": "Is model_b's answer better than model_a's?",
        "judge_pass": "GPT-4 says model_b; its ties are not a pass",
        "human_pass": "more than half of the expert votes say model_b; ties and split votes "
                      "are not a pass"},
    **{f"llmjudge-{run}": {
        "title": f"LLMJudge × {run}", "dataset": "llmjudge", "judge": run,
        "question": _RELEVANT[0], "judge_pass": _RELEVANT[1], "human_pass": _RELEVANT[2]}
       for run in ("RMITIR-GPT4o", "willia-umbrela1", "NISTRetrieval-instruct0")},
}


# The data --------------------------------------------------------------------------------

class HashMismatch(Exception):
    """A downloaded file is not the one the report was made from."""


def cache_folder(arg: str | None) -> Path:
    """--cache, or a folder in the user's cache. Never inside the repository: the data is
    never committed."""
    if arg:
        folder = Path(arg).resolve()
    else:
        base = os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache"
        folder = Path(base) / "judgekeeper" / "real-data-check"
    if folder.resolve() == ROOT or ROOT in folder.resolve().parents:
        raise SystemExit(f"--cache {arg}: choose a folder outside the repository; the "
                         "downloaded data is never committed")
    return folder


def _download(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=120) as resp:
        return resp.read()


def fetch(source: dict, cache: Path, download=_download) -> Path:
    """The file, from the cache if it is there and matches its sha256, else downloaded and
    checked. A download that does not match is refused and not kept."""
    path = cache / source["file"]
    if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == source["sha256"]:
        return path
    data = download(source["url"])
    got = hashlib.sha256(data).hexdigest()
    if got != source["sha256"]:
        raise HashMismatch(f"{source['file']} from {source['url']} has sha256 {got}, not "
                           f"{source['sha256']}: refusing to use it")
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(path.name + ".part")
    part.write_bytes(data)
    part.replace(path)
    return path


def read_parquet(path: Path, columns: list[str]) -> list[dict]:
    try:
        import pyarrow.parquet as pq
    except ImportError:
        raise SystemExit("MT-Bench is a parquet file: run `pip install pyarrow` for this "
                         "script (judgekeeper itself does not need it)") from None
    return pq.read_table(path, columns=columns).to_pylist()


# The pools: (judge passed, human passed) per item ----------------------------------------

def llmbar_pool(report: dict) -> list[tuple[bool, bool]]:
    pool = [(item["verdicts"][0] == "A", item["human"] == "A") for item in report["items"]]
    if len(pool) != report["anchors"]["n_items"]:
        raise ValueError(f"the report holds {len(pool)} items, not "
                         f"{report['anchors']['n_items']}")
    return pool


def mtbench_pool(gpt4: list[dict], human: list[dict]) -> list[tuple[bool, bool]]:
    """GPT-4's pairwise verdicts and the expert votes on the same question, turn and pair."""
    def key(r, a="model_a", b="model_b"):
        return r["question_id"], r[a], r[b], r["turn"]

    keys = {key(r) for r in gpt4}
    votes: dict[tuple, list[str]] = defaultdict(list)  # in GPT-4's order -> winners
    swap = {"model_a": "model_b", "model_b": "model_a"}
    for r in human:
        if key(r) in keys:
            votes[key(r)].append(r["winner"])
        elif key(r, "model_b", "model_a") in keys:
            votes[key(r, "model_b", "model_a")].append(swap.get(r["winner"], r["winner"]))
    return [(r["winner"] == "model_b", sum(w == "model_b" for w in votes[key(r)]) * 2
             > len(votes[key(r)])) for r in gpt4 if key(r) in votes]


def llmjudge_pool(qrels: str, run: str) -> list[tuple[bool, bool]]:
    """`query 0 passage grade` lines from the assessors and from one run."""
    def read(text):
        out = {}
        for line in text.splitlines():
            if line.strip():
                query, _, passage, grade = line.split()
                out[(query, passage)] = int(float(grade)) >= 2
        return out

    human, judge = read(qrels), read(run)
    if human.keys() != judge.keys():
        raise ValueError("the run did not grade the same passages as the assessors")
    return [(judge[k], human[k]) for k in sorted(human)]


def load_pools(cache: Path) -> dict[str, list[tuple[bool, bool]]]:
    files = {s["file"]: fetch(s, cache) for d in DATASETS.values() for s in d["files"]}
    cols = ["question_id", "model_a", "model_b", "winner", "turn"]
    pools = {"llmbar-haiku": llmbar_pool(json.loads(LLMBAR.read_text(encoding="utf-8"))),
             "mtbench-gpt4": mtbench_pool(read_parquet(files["mtbench/gpt4_pair.parquet"], cols),
                                          read_parquet(files["mtbench/human.parquet"], cols))}
    qrels = files["llmjudge/qrels.txt"].read_text(encoding="utf-8")
    for name in POOLS:
        if name.startswith("llmjudge-"):
            run = files[f"llmjudge/{POOLS[name]['judge']}.txt"].read_text(encoding="utf-8")
            pools[name] = llmjudge_pool(qrels, run)
    return pools


# The truth and the checks ----------------------------------------------------------------

def truth(pool: list[tuple[bool, bool]]) -> dict:
    """The numbers from all of the pool's human labels."""
    tp = sum(j and h for j, h in pool)
    fn = sum((not j) and h for j, h in pool)
    fp = sum(j and (not h) for j, h in pool)
    tn = sum((not j) and (not h) for j, h in pool)
    n = len(pool)
    judge_rate, human_rate = (tp + fp) / n, (tp + fn) / n
    chance = judge_rate * human_rate + (1 - judge_rate) * (1 - human_rate)
    return {"n": n, "tp": tp, "fn": fn, "fp": fp, "tn": tn, "tpr": tp / (tp + fn),
            "tnr": tn / (tn + fp), "real_pass_rate": human_rate, "judge_pass_rate": judge_rate,
            "kappa": ((tp + tn) / n - chance) / (1 - chance)}


def fixed_draw(rng: random.Random, passes: list[bool], fails: list[bool], n: int):
    p, f = rng.sample(passes, n), rng.sample(fails, n)
    return n, sum(p), n, sum(f)


def start_rule_draw(rng: random.Random, passes: list[bool], fails: list[bool]):
    """BLOCK from each shuffled group at a time until TARGET Correct and TARGET Wrong, or
    until both groups run out."""
    p, f = passes[:], fails[:]
    rng.shuffle(p)
    rng.shuffle(f)
    n_p = n_f = 0
    while True:
        correct = sum(p[:n_p]) + sum(f[:n_f])
        if min(correct, n_p + n_f - correct) >= TARGET or (n_p >= len(p) and n_f >= len(f)):
            return n_p, sum(p[:n_p]), n_f, sum(f[:n_f])
        n_p, n_f = min(n_p + BLOCK, len(p)), min(n_f + BLOCK, len(f))


def run(pool, design: str, n: int | None, checks: int, seed: int,
        corrected=weighted.corrected) -> dict:
    """One design, `checks` times: how often each range held the value from all labels."""
    t = truth(pool)
    passes = [h for j, h in pool if j]  # the human label of each answer the judge passed
    fails = [h for j, h in pool if not j]
    cache: dict[tuple, dict] = {}  # corrected is deterministic (a fixed seed)
    rng = random.Random(seed)
    held = {k: 0 for k in METRICS}
    widths, errors = {k: [] for k in METRICS}, {k: [] for k in METRICS}
    labels, plain, first = [], {"tpr": [], "tnr": []}, None
    for i in range(checks):
        if design == "fixed":
            counts = fixed_draw(rng, passes, fails, n)
        else:
            counts = start_rule_draw(rng, passes, fails)
        n_p, c_p, n_f, c_f = counts
        if counts not in cache:
            cache[counts] = corrected(len(passes), len(fails), *counts)
        r = cache[counts]
        labels.append(n_p + n_f)
        if i == 0:
            first = {"labeled": {"pass": {"labeled": n_p, "correct": c_p},
                                 "fail": {"labeled": n_f, "correct": c_f}},
                     **{k: {"value": r[k], "range": list(r[f"{k}_interval"])} for k in METRICS},
                     "kappa": r["kappa"]}
        # Without the correction: the labeled answers as if they were the whole pool.
        if c_p + c_f:
            plain["tpr"].append(c_p / (c_p + c_f))
        if n_p + n_f - c_p - c_f:
            plain["tnr"].append((n_f - c_f) / (n_p + n_f - c_p - c_f))
        for k in METRICS:
            lo, hi = r[f"{k}_interval"]
            if r[k] is None or lo is None or hi is None:
                continue
            held[k] += lo <= t[k] <= hi
            widths[k].append(hi - lo)
            errors[k].append(abs(r[k] - t[k]))
    out = {"labels": {"mean": statistics.mean(labels), "min": min(labels), "max": max(labels)},
           "first_check": first,
           "plain": {k: statistics.mean(v) if v else None for k, v in plain.items()}}
    for k in METRICS:
        known = len(widths[k])
        out[k] = {"held": held[k], "known": known, "unknown": checks - known,
                  "coverage": held[k] / known if known else None,
                  "width_mean": statistics.mean(widths[k]) if known else None,
                  "abs_error_median": statistics.median(errors[k]) if known else None}
    return out


def rounded(value):
    if isinstance(value, float):
        return round(value, DIGITS)
    if isinstance(value, dict):
        return {k: rounded(v) for k, v in value.items()}
    if isinstance(value, list):
        return [rounded(v) for v in value]
    return value


def summarise(pools: dict) -> dict:
    """Per design, across the judges: how often the TPR and TNR ranges held."""
    out = {}
    for design in DESIGNS:
        cells = [(pool["designs"][design][k]["coverage"], name, k)
                 for name, pool in pools.items() for k in ("tpr", "tnr")]
        low, high = min(cells), max(cells)
        labels = [pool["designs"][design]["labels"]["mean"] for pool in pools.values()]
        out[design] = {"judges": len(pools), "datasets": len({p["dataset"]
                                                              for p in pools.values()}),
                       "labels_mean": {"lowest": min(labels), "highest": max(labels)},
                       "tpr_tnr": {"mean": statistics.mean(c for c, _, _ in cells),
                                   "lowest": low[0], "lowest_case": [low[1], low[2]],
                                   "highest": high[0], "highest_case": [high[1], high[2]]}}
    return rounded(out)


def check_all(pools: dict[str, list[tuple[bool, bool]]]) -> dict:
    result = {"made_by": "scripts/real_data_check.py",
              "settings": {"seed": SEED, "checks": CHECKS, "sizes": list(SIZES),
                           "start_rule": {"block": BLOCK, "target": TARGET},
                           "weighted": {"level": weighted.LEVEL, "draws": weighted.DRAWS,
                                        "seed": weighted.SEED}},
              "data": DATASETS, "pools": {}}
    for i, (name, pool) in enumerate(pools.items()):
        designs = {f"{n}+{n}": run(pool, "fixed", n, CHECKS, SEED + 100 * i + n)
                   for n in SIZES}
        designs["start_rule"] = run(pool, "start_rule", None, CHECKS, SEED + 100 * i + 99)
        result["pools"][name] = {**POOLS[name], "truth": truth(pool), "designs": designs}
    result = rounded(result)
    result["summary"] = summarise(result["pools"])
    return result


# The report ------------------------------------------------------------------------------

def text_of(result: dict) -> str:
    return json.dumps(rounded(result), indent=1, ensure_ascii=False) + "\n"


def _pct(x) -> str:
    return "n/a" if x is None else f"{x * 100:.1f}"


def _two(x) -> str:
    return "n/a" if x is None else f"{x:.2f}"


def _design_name(design: str, result: dict) -> str:
    if design == "start_rule":
        rule = result["settings"]["start_rule"]
        return f"start's rule ({rule['target']} Correct + {rule['target']} Wrong)"
    return f"{design} labels"


def markdown(result: dict) -> str:
    s, pools, summary = result["settings"], result["pools"], result["summary"]
    w = s["weighted"]
    first = summary["25+25"]
    lines = [
        "# Real-data check of judgekeeper's ranges", "",
        "Made by `scripts/real_data_check.py`; do not edit by hand.", "",
        ("Each judge below decided on every answer in a public dataset, and people labeled the "
         "same answers. So how often the judge agrees with the people is known: it is worked "
         "out from all of the dataset's human labels. Each check pretends a person labeled "
         "only a few answers, picked as `judgekeeper start` picks them (as many from the "
         "judge's passes as from its fails), and works out TPR (how often the judge passed "
         "answers people passed), TNR (how often it failed answers people failed) and the real "
         "pass rate with judgekeeper's own maths, each with a range. A range should hold the "
         f"value from all labels about {w['level']:.0%} of the time. No judge was called."), "",
        "## The result", "",
        (f"With {first['labels_mean']['lowest']:.0f} labels per check ("
         f"{s['sizes'][0]} from each group), on {first['judges']} judges from "
         f"{first['datasets']} public datasets, the TPR and TNR ranges held the value from all "
         f"of the dataset's human labels in {_pct(first['tpr_tnr']['mean'])} checks in 100 on "
         f"average (lowest {_pct(first['tpr_tnr']['lowest'])}, highest "
         f"{_pct(first['tpr_tnr']['highest'])}), over {s['checks']:,} checks per judge."), "",
        "| Design | Labels per check | TPR and TNR: held in 100 (average) | Lowest | Highest |",
        "|---|---|---|---|---|"]
    for design in DESIGNS:
        d = summary[design]
        lab = d["labels_mean"]
        span = (f"{lab['lowest']:.0f}" if round(lab["lowest"]) == round(lab["highest"])
                else f"{lab['lowest']:.0f} to {lab['highest']:.0f} on average")
        low, high = d["tpr_tnr"]["lowest_case"], d["tpr_tnr"]["highest_case"]
        lines.append(f"| {_design_name(design, result)} | {span} | {_pct(d['tpr_tnr']['mean'])} | "
                     f"{_pct(d['tpr_tnr']['lowest'])} ({pools[low[0]]['title']}, "
                     f"{low[1].upper()}) | {_pct(d['tpr_tnr']['highest'])} "
                     f"({pools[high[0]]['title']}, {high[1].upper()}) |")
    noise = 196 * math.sqrt(w["level"] * (1 - w["level"]) / s["checks"])
    lines += ["", (f"A {w['level']:.0%} range is expected to miss about "
                   f"{100 - round(w['level'] * 100)} times in 100. With {s['checks']:,} checks, "
                   f"chance alone moves the share it holds by up to about {noise:.1f} either way "
                   "(95 times in 100)."), "",
              "## The judges", "",
              "The values from all of each dataset's human labels.", "",
              "| Judge | Answers | Judge passed | TPR | TNR | Real pass rate | Kappa |",
              "|---|---|---|---|---|---|---|"]
    for p in pools.values():
        t = p["truth"]
        lines.append(f"| {p['title']} | {t['n']:,} | {_pct(t['judge_pass_rate'])}% | "
                     f"{_two(t['tpr'])} | {_two(t['tnr'])} | {_two(t['real_pass_rate'])} | "
                     f"{_two(t['kappa'])} |")
    lines += ["", "## How often each range held, per judge", "",
              f"Held in 100 checks, TPR / TNR / real pass rate, {s['checks']:,} checks each.", "",
              "| Judge | " + " | ".join(_design_name(d, result) for d in DESIGNS) + " |",
              "|---|" + "---|" * len(DESIGNS)]
    for p in pools.values():
        lines.append(f"| {p['title']} | " + " | ".join(
            " / ".join(_pct(p["designs"][d][k]["coverage"]) for k in METRICS)
            for d in DESIGNS) + " |")
    unknown = sum(p["designs"][d][k]["unknown"] for p in pools.values() for d in DESIGNS
                  for k in METRICS)
    lines += ["", f"Checks where a number could not be worked out: {unknown}.", "",
              "## Range width and error", "",
              ("Average width of the range (high end minus low end) and the median distance "
               "from the number to the value from all labels, TPR / TNR."), "",
              "| Judge | " + " | ".join(_design_name(d, result) for d in DESIGNS) + " |",
              "|---|" + "---|" * len(DESIGNS)]
    for p in pools.values():
        lines.append(f"| {p['title']} | " + " | ".join(
            f"width {_two(p['designs'][d]['tpr']['width_mean'])} / "
            f"{_two(p['designs'][d]['tnr']['width_mean'])}, error "
            f"{_two(p['designs'][d]['tpr']['abs_error_median'])} / "
            f"{_two(p['designs'][d]['tnr']['abs_error_median'])}" for d in DESIGNS) + " |")
    lines += ["", "## Without the correction", "",
              ("judgekeeper weighs each group by its size in the pool, because a check labels as "
               "many of the judge's passes as of its fails. Without that, the same labels give "
               f"these rates (average over the {s['checks']:,} checks with "
               f"{s['sizes'][0]} + {s['sizes'][0]} labels):"), "",
              "| Judge | TPR without / value from all labels | TNR without / value from all labels |",
              "|---|---|---|"]
    for p in pools.values():
        plain, t = p["designs"]["25+25"]["plain"], p["truth"]
        lines.append(f"| {p['title']} | {_two(plain['tpr'])} / {_two(t['tpr'])} | "
                     f"{_two(plain['tnr'])} / {_two(t['tnr'])} |")
    lines += ["", "## One check in full", "",
              (f"The first of the {s['checks']:,} checks with {s['sizes'][0]} + "
               f"{s['sizes'][0]} labels for each judge, not picked by hand. Kappa has no "
               "range."), "",
              ("| Judge | Marked Correct (of judge passes / fails) | TPR | TNR | Real pass rate "
               "| Kappa |"), "|---|---|---|---|---|---|"]
    for p in pools.values():
        f, t = p["designs"]["25+25"]["first_check"], p["truth"]
        lab = f["labeled"]
        lines.append(
            f"| {p['title']} | {lab['pass']['correct']} of {lab['pass']['labeled']} / "
            f"{lab['fail']['correct']} of {lab['fail']['labeled']} | " + " | ".join(
                f"{_two(f[k]['value'])} ({_two(f[k]['range'][0])} to {_two(f[k]['range'][1])}), "
                f"all labels {_two(t[k])}" for k in METRICS)
            + f" | {_two(f['kappa'])}, all labels {_two(t['kappa'])} |")
    lines += ["", "## The questions", "",
              ("Each item became one yes/no question, fixed before looking at the results. "
               "Nothing was dropped because of what the judge said."), "",
              "| Judge | Question | Judge pass | Human pass |", "|---|---|---|---|"]
    for p in pools.values():
        lines.append(f"| {p['title']} | {p['question']} | {p['judge_pass']} | "
                     f"{p['human_pass']} |")
    lines += ["", ("The human labels are what each dataset has: LLMBar's gold labels written by "
                   "its authors, MT-Bench's expert votes (often one per item), and one NIST "
                   "assessor per passage in LLMJudge. Each check draws from the dataset without "
                   "putting answers back, as a person labels; the ranges assume an endless pool, "
                   "which makes them a little cautious on the smallest pool."), "",
              "## Data and licences", ""]
    for d in result["data"].values():
        lines.append(f"- **{d['name']}** ({d['licence']}): <{d['source']}>, revision "
                     f"`{d['revision']}`. {d['attribution']}")
        for f in d["files"]:
            lines.append(f"  - `{f['file']}`: sha256 `{f['sha256']}`")
    lines += ["", "## Settings", "",
              (f"Seed {s['seed']}; {s['checks']:,} checks per judge and design; start's rule "
               f"labels {s['start_rule']['block']} from each group at a time. Ranges: "
               f"`weighted.corrected` at level {w['level']}, {w['draws']:,} draws, seed "
               f"{w['seed']}. To run it again: `pip install pyarrow`, then "
               "`python scripts/real_data_check.py`. It downloads the files above into a cache "
               "folder outside the repository, checks each sha256, and writes this report and "
               "`report.json`.")]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--cache", help="the folder for the downloaded data (outside the "
                                    "repository; default: a folder in your user cache)")
    args = ap.parse_args(argv)
    try:
        pools = load_pools(cache_folder(args.cache))
    except HashMismatch as e:
        print(e, file=sys.stderr)
        return 1
    result = check_all(pools)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "report.json").write_text(text_of(result), encoding="utf-8")
    (OUT / "report.md").write_text(markdown(result), encoding="utf-8")
    for design, d in result["summary"].items():
        c = d["tpr_tnr"]
        print(f"{design}: TPR and TNR held {_pct(c['mean'])} in 100 on average "
              f"(lowest {_pct(c['lowest'])}, highest {_pct(c['highest'])})")
    print(f"wrote {OUT / 'report.md'} and report.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
