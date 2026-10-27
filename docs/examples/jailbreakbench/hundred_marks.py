"""Mark 100 answers of JailbreakBench's judge-comparison set, many times over, and count how
often judgekeeper's ranges hold the real values on all 300.

    python3 -I hundred_marks.py [--draws 100] [--python PYTHON] [--cache DIR] [--out DIR]

The data is load.py's: it downloads the pinned revision, checks its SHA-256 and writes
results.jsonl in --cache (default cache/ next to this file, whose .gitignore is `*`).
The mapping is load.py's too:
  LLM-as-a-judge = the set's GPT-4 column (gpt4_cf): 0, not jailbroken = pass; 1 = fail
  marks = the three experts' majority (human_majority): 0 = pass, 1 = fail
  --judge-model openai:gpt-4-0613 on every command.

One draw, in a fresh project folder, so judgekeeper picks a new seed (saved in
.judgekeeper/start.json and written to draws.csv):
  1. The project holds the 300 answers. `judgekeeper --wait --yes` reads them and opens the
     marking page. The first 100 answers the page offers, in its order, get the experts'
     majority through the page's own calls (GET /state, POST /label with the token and the
     Origin header), as a click would. The LLM-as-a-judge's grade is never read from the page.
  2. The page is stopped; `judgekeeper` runs Measure; `judgekeeper --stop`.
  3. Inside? The real TPR, TNR and kappa on all 300 answers are compared with the ranges in
     .judgekeeper/result.json.

No AI calls: ANTHROPIC_API_KEY and OPENAI_API_KEY are removed from every command, and stdin
is closed. Ports: --port (default 9750) to --port + 19.

Prompt and response text stays in --cache. --out gets text-free files only, each checked
for dataset text first: draws.csv (one row per draw), summary.json (the real values and the
counts), and draw 1's Measure screen.
"""

from __future__ import annotations

import argparse
import csv
import html
import importlib.util
import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True  # no __pycache__ next to load.py
_spec = importlib.util.spec_from_file_location("jbb_load", HERE / "load.py")
load = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(load)

JUDGE_MODEL = "openai:gpt-4-0613"
MARKS = 100
PORT_SETS = 10  # 2 ports a draw, in sets that rotate
WINDOW = 40  # a piece of dataset text this long must not appear in anything copied out
HEADER = [
    ("Source: JailbreakBench JBB-Behaviors (huggingface.co/datasets/JailbreakBench/"
     "JBB-Behaviors), MIT license, Copyright (c) 2023 JailbreakBench Team"),
    f"Revision: {load.REVISION}",
    "Subset: config judge_comparison, split test (data/judge-comparison.csv, 300 rows)",
    ("Grades: judge: the dataset's gpt4_cf column (GPT-4-0613); marks: its human_majority "
     "column, the majority of three expert annotators (0 = Pass, 1 = Fail)"),
    "Holds: ids, grades and counts only; no prompt or response",
]
SOURCE = {"dataset": HEADER[0].split(": ", 1)[1], "revision": load.REVISION,
          "subset": HEADER[2].split(": ", 1)[1], "grades": HEADER[3].split(": ", 1)[1],
          "text": "ids, grades and counts only; no prompt or response"}


def figures(pairs: list[tuple[str, str]]) -> dict:
    """pairs = (expert, judge): the four counts, TPR, TNR, agreement and Cohen's kappa."""
    n = len(pairs)
    pp = sum(1 for e, j in pairs if e == "pass" and j == "pass")
    pf = sum(1 for e, j in pairs if e == "pass" and j == "fail")
    fp = sum(1 for e, j in pairs if e == "fail" and j == "pass")
    ff = sum(1 for e, j in pairs if e == "fail" and j == "fail")
    po = (pp + ff) / n
    pe = ((pp + pf) * (pp + fp) + (fp + ff) * (pf + ff)) / (n * n)
    return {"n": n, "expert_pass_judge_pass": pp, "expert_pass_judge_fail": pf,
            "expert_fail_judge_pass": fp, "expert_fail_judge_fail": ff,
            "tpr": pp / (pp + pf), "tnr": ff / (fp + ff), "agreement": po,
            "kappa": (po - pe) / (1 - pe)}


def leaks(text: str, texts: list[str]) -> int:
    """How many WINDOW-long pieces of dataset text appear in `text`."""
    flat = " ".join(html.unescape(text).split())
    n = 0
    for t in texts:
        t = " ".join(t.split())
        for k in range(0, max(1, len(t) - WINDOW + 1), WINDOW):
            piece = t[k:k + WINDOW]
            if len(piece) == WINDOW and piece in flat:
                n += 1
    return n


class Page:
    """One judgekeeper command that serves the marking page with --wait."""

    def __init__(self, cmd: list[str], cwd: Path, env: dict):
        self.p = subprocess.Popen(cmd, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        self.said, url = [], None
        for line in self.p.stdout:
            self.said.append(line.rstrip("\n"))
            if "http://127.0.0.1:" in line and "token=" in line:
                url = line[line.index("http://"):].split()[0].strip()
                break
        threading.Thread(target=lambda: [self.said.append(x.rstrip("\n"))
                                         for x in self.p.stdout], daemon=True).start()
        self.base = None
        if not url:
            try:
                self.p.wait(timeout=60)
            except subprocess.TimeoutExpired:
                self.p.kill()
            return
        parts = urlsplit(url)
        self.base = f"{parts.scheme}://{parts.netloc}"
        self.token = parts.query.split("token=", 1)[1].split("&")[0]

    def call(self, path: str, body: dict | None = None) -> dict:
        req = urllib.request.Request(
            f"{self.base}{path}?token={self.token}",
            method="POST" if body is not None else "GET",
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Content-Type": "application/json", "Origin": self.base,
                     "Sec-Fetch-Site": "same-origin"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())

    def stop(self) -> str:
        time.sleep(1)
        if self.p.poll() is None:
            self.p.send_signal(signal.SIGINT)
        try:
            self.p.wait(timeout=15)
        except subprocess.TimeoutExpired:
            self.p.kill()
        time.sleep(0.5)
        return "\n".join(self.said)


def run(jk: list[str], args: list[str], cwd: Path, env: dict) -> subprocess.CompletedProcess:
    return subprocess.run(jk + args, cwd=cwd, env=env, text=True, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, timeout=600,
                          check=False)


def inside(value: float, interval) -> bool:
    return bool(interval) and interval[0] <= value <= interval[1]


def one_draw(d: int, a, results: Path, expert: dict, by_text: dict, texts: list[str],
             true: dict, env: dict) -> tuple[dict, str]:
    name = f"d{d:03d}"
    project = a.cache / "hundred-marks" / name
    if project.exists():
        raise SystemExit(f"{project} exists: use a new --cache folder")
    project.mkdir(parents=True)
    shutil.copyfile(results, project / "judge-results.jsonl")
    jkdir = project / ".judgekeeper"
    jk = [a.python, "-m", "judgekeeper"]
    port = a.port + 2 * ((d - 1) % PORT_SETS)

    page = Page(jk + ["--wait", "--yes", "--no-browser", "--port", str(port), "--judge-model",
                      JUDGE_MODEL], project, env)
    if page.base is None:
        raise SystemExit(f"{name}: no marking page:\n" + "\n".join(page.said[-15:]))
    with (jkdir / "pool.jsonl").open(encoding="utf-8") as f:
        pool = [json.loads(x) for x in f if x.strip()]
    page_to_row = {q["id"]: by_text[(q["input"], q["output"])] for q in pool}
    items = page.call("/state")["items"]
    todo = [it["id"] for it in items if not it.get("label")][:a.marks]
    for k, pid in enumerate(todo):
        try:
            page.call("/label", {"id": pid, "label": expert[page_to_row[pid]]})
        except (urllib.error.URLError, ConnectionError) as e:  # may close after the last one
            if k != len(todo) - 1:
                raise
            print("last mark:", type(e).__name__)
    screen_page = page.stop()

    r = run(jk, ["--no-browser", "--port", str(port + 1), "--judge-model", JUDGE_MODEL],
            project, env)
    run(jk, ["--stop"], project, env)
    screen = r.stdout
    (project / "screen-page.txt").write_text(screen_page, encoding="utf-8")  # stays in cache
    (project / "screen-measure.txt").write_text(screen, encoding="utf-8")
    res = json.loads((jkdir / "result.json").read_text(encoding="utf-8"))
    start = json.loads((jkdir / "start.json").read_text(encoding="utf-8"))
    labels = res.get("labels") or {}

    row = {"draw": name, "seed": start["seed"], "offered": len(items), "marked": len(todo),
           "marks_counted": sum(v for v in labels.values() if isinstance(v, int)),
           "verdict_level": res.get("verdict_level"),
           "disagreements": res.get("disagreements"), "measure_exit": r.returncode}
    hit = True
    for key in ("tpr", "tnr", "kappa"):
        iv = res.get(f"{key}_interval")
        ok = inside(true[key], iv)
        hit &= ok
        row.update({key: round(res.get(key, float("nan")), 4),
                    f"{key}_low": round(iv[0], 4) if iv else "",
                    f"{key}_high": round(iv[1], 4) if iv else "",
                    f"true_{key}_inside": ok})
    row["all_three_inside"] = hit
    row["screen_text_pieces"] = leaks(screen_page, texts) + leaks(screen, texts)
    return row, screen


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--python", default=sys.executable, help="a python with judgekeeper")
    ap.add_argument("--cache", type=Path, default=HERE / "cache",
                    help="the download and the draws' projects (they hold dataset text)")
    ap.add_argument("--out", type=Path, default=HERE / "hundred-marks", help="text-free files")
    ap.add_argument("--draws", type=int, default=100)
    ap.add_argument("--marks", type=int, default=MARKS)
    ap.add_argument("--port", type=int, default=9750)
    a = ap.parse_args()
    a.cache = a.cache.resolve()

    load.HERE, load.CACHE = a.cache.parent, a.cache
    load.main()  # downloads, checks the SHA-256, writes results.jsonl
    with (a.cache / "judge-comparison.csv").open(newline="", encoding="utf-8") as f:
        rows = sorted(csv.DictReader(f), key=lambda r: int(r["Index"]))
    ids = [f"jbb-{int(r['Index']):03d}" for r in rows]
    expert = {i: load.grade(r["human_majority"]) for i, r in zip(ids, rows)}
    judge = {i: load.grade(r["gpt4_cf"]) for i, r in zip(ids, rows)}
    texts = [r[k] for r in rows for k in ("prompt", "target_response", "goal") if r[k]]
    by_text = {(r["prompt"], r["target_response"]): i for i, r in zip(ids, rows)}
    if len(by_text) != len(rows):
        raise SystemExit("two rows share the same prompt and response")
    true_all = figures([(expert[i], judge[i]) for i in ids])
    true = {k: true_all[k] for k in ("tpr", "tnr", "kappa")}

    env = {k: v for k, v in os.environ.items()
           if k not in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY")}
    env.update(PYTHONUNBUFFERED="1", NO_COLOR="1")
    version = subprocess.run(
        [a.python, "-c", "import judgekeeper; print(judgekeeper.__version__)"],
        env=env, text=True, capture_output=True, check=False).stdout.strip()
    print(f"judgekeeper {version}; {len(rows)} answers; {a.draws} draws of {a.marks} marks")
    print("real on all 300:", {k: round(v, 4) for k, v in true.items()})

    a.out.mkdir(parents=True, exist_ok=True)
    out_rows = []
    for d in range(1, a.draws + 1):
        row, screen = one_draw(d, a, a.cache / "results.jsonl", expert, by_text, texts, true,
                               env)
        out_rows.append(row)
        if d == 1 and row["screen_text_pieces"] == 0:
            head = "".join(f"# {x}\n" for x in HEADER)
            (a.out / "measure-draw-001.txt").write_text(
                head + "# The screen below is judgekeeper's Measure output, copied exactly.\n\n"
                + screen, encoding="utf-8")
        print(f"{row['draw']}: seed {row['seed']}, marked {row['marked']}, counted "
              f"{row['marks_counted']}, TPR {row['true_tpr_inside']}, TNR "
              f"{row['true_tnr_inside']}, kappa {row['true_kappa_inside']}", flush=True)

    with (a.out / "draws.csv").open("w", newline="", encoding="utf-8") as f:
        f.write("".join(f"# {x}\n" for x in HEADER))
        w = csv.DictWriter(f, fieldnames=list(out_rows[0]))
        w.writeheader()
        w.writerows(out_rows)
    n = len(out_rows)
    each = {k: sum(1 for r in out_rows if r[f"true_{k}_inside"]) for k in ("tpr", "tnr", "kappa")}
    width = {k: round(sum(r[f"{k}_high"] - r[f"{k}_low"] for r in out_rows) / n, 4)
             for k in ("tpr", "tnr", "kappa")}
    sound = all(r["marked"] == a.marks and r["marks_counted"] == a.marks
                and r["screen_text_pieces"] == 0 for r in out_rows)
    summary = {"source": SOURCE, "judgekeeper_version": version, "judge_model": JUDGE_MODEL,
               "rows": len(rows), "marks_per_draw": a.marks, "true_all_rows": true_all,
               "draws": n, "inside_each": each,
               "all_three_inside": sum(1 for r in out_rows if r["all_three_inside"]),
               "mean_range_width": width,
               "every_draw_counted_its_marks_and_showed_no_text": sound}
    (a.out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    raise SystemExit(0 if sound else 1)


if __name__ == "__main__":
    main()
