"""Download DICES-350 and write it as a Label Studio export with one annotation per rater.

    python3 -I load.py [OUTPUT_FOLDER]

Source: github.com/google-research-datasets/dices-dataset, file
350/diverse_safety_adversarial_dialog_350.csv, pinned to one commit and checked by its SHA-256.
Licence: CC BY 4.0, Copyright Google LLC. Aroyo et al., "DICES Dataset: Diversity in
Conversational AI Evaluation for Safety", NeurIPS 2023 Datasets and Benchmarks, arXiv 2306.11247.
The conversations are adversarial and some are offensive, so nothing from the download is
committed: this script writes only outside the repository, into OUTPUT_FOLDER (default:
judgekeeper-example-people-agree in the system temp folder):
  diverse_safety_adversarial_dialog_350.csv   the download
  label-studio-export.json                    what Label Studio's "JSON" export writes for 350 tasks

The question each of the 123 raters answered is `Q_overall`: is the chatbot's last reply unsafe?
Yes is written as Fail, No as Pass. "Unsure" is left out: that rater has no annotation on that
task. In the export each task has:
  data         input (the conversation before the last reply) and output (the last reply)
  annotations  one per rater who said Yes or No; completed_by is a small integer per rater (1 to
               123), plus one more with completed_by 124: the dataset's own expert label
               `safety_gold` (Yes is Fail, No is Pass), flagged ground_truth
The file also holds each rater's gender, race, age and education. Those columns are never read
into the export, and rater ids are only used to number the raters 1 to 123 (in the order of
their ids). The expert label is one value per conversation, so annotation 124 stands for the
experts as one more person: a number that counts people (such as how much people agree with each
other) counts 124 people, the 123 raters and the experts. Its timestamp is the conversation's
first rating time, because the file has no time for it. The task id is the file's item_id. Every rater is kept, including the 19 whom the
dataset's README lists as removed in some analyses.
"""

import csv
import json
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import example_tools as tools

COMMIT = "b5596d9edd585361967991a591abc7b11fb1f7a3"
URL = ("https://raw.githubusercontent.com/google-research-datasets/dices-dataset/"
       f"{COMMIT}/350/diverse_safety_adversarial_dialog_350.csv")
SHA256 = "63cb8620eb04e64957f9e45b1f7cb3d079c4eed8e8b28909f46e0b7038ce4301"
NOTICE = """DICES-350 is licensed under CC BY 4.0, Copyright Google LLC.
Cite: Aroyo et al., "DICES Dataset: Diversity in Conversational AI Evaluation for Safety",
NeurIPS 2023 Datasets and Benchmarks Track, arXiv 2306.11247."""
LABELS = {"Yes": "Fail", "No": "Pass"}  # Q_overall asks whether the reply is unsafe
USED = ("rater_id", "item_id", "context", "response", "answer_time_ms", "answer_timestamp",
        "Q_overall", "safety_gold")


def stamp(unix_seconds: str) -> str:
    when = datetime.fromtimestamp(int(unix_seconds), tz=UTC)
    return when.strftime("%Y-%m-%dT%H:%M:%S.000000Z")


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else (
        Path(tempfile.gettempdir()) / "judgekeeper-example-people-agree")
    out.mkdir(parents=True, exist_ok=True)
    data = tools.download(URL, out / "diverse_safety_adversarial_dialog_350.csv", SHA256)
    rows = []
    with data.open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            rows.append({k: r[k] for k in USED})  # nothing else is kept
    raters = {rid: n for n, rid in enumerate(sorted({r["rater_id"] for r in rows}, key=int), 1)}
    items: dict[int, dict] = {}
    for r in rows:
        items.setdefault(int(r["item_id"]), {"input": r["context"], "output": r["response"],
                                             "rows": []})["rows"].append(r)
    tasks = []
    ann_id = 0
    experts = len(raters) + 1  # completed_by of the expert label
    counts = {"Pass": 0, "Fail": 0, "Unsure": 0}
    for task_id in sorted(items):
        item = items[task_id]
        annotations = []
        for r in sorted(item["rows"], key=lambda r: raters[r["rater_id"]]):
            if r["Q_overall"] not in LABELS:
                if r["Q_overall"] != "Unsure":
                    sys.exit(f"unexpected Q_overall {r['Q_overall']!r}; stop and look.")
                counts["Unsure"] += 1
                continue
            ann_id += 1
            choice = LABELS[r["Q_overall"]]
            counts[choice] += 1
            annotations.append(tools.annotation(
                ann_id, task_id, 1, raters[r["rater_id"]],
                [tools.choices_region("verdict", "output", choice)],
                stamp(r["answer_timestamp"]), lead_time=int(r["answer_time_ms"]) / 1000))
        golds = {r["safety_gold"] for r in item["rows"]}
        if len(golds) != 1 or not golds <= LABELS.keys():
            sys.exit(f"safety_gold is not one Yes or No on item {task_id}; stop and look.")
        ann_id += 1
        annotations.append(tools.annotation(
            ann_id, task_id, 1, experts,
            [tools.choices_region("verdict", "output", LABELS[golds.pop()])],
            stamp(item["rows"][0]["answer_timestamp"]), ground_truth=True))
        tasks.append(tools.task(task_id, 1, {"input": item["input"], "output": item["output"]},
                                annotations, [], {}, stamp(item["rows"][0]["answer_timestamp"])))
    path = out / "label-studio-export.json"
    path.write_text(json.dumps(tasks, ensure_ascii=False, indent=1), encoding="utf-8")
    print(NOTICE)
    print(f"{len(tasks)} tasks, {len(raters)} raters plus the expert label; Pass {counts['Pass']}, Fail {counts['Fail']},"
          f" Unsure left out {counts['Unsure']}")
    print("wrote", path)


if __name__ == "__main__":
    main()
