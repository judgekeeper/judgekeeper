"""Download XSTest's GPT-4 completions and write them as a Label Studio export.

    python3 -I load.py [OUTPUT_FOLDER]

Source: github.com/paul-rottger/xstest, file model_completions/xstest_v2_completions_gpt4.csv,
pinned to one commit and checked by its SHA-256. The prompts are CC-BY-4.0 (Rottger et al.,
"XSTest: A Test Suite for Identifying Exaggerated Safety Behaviours in Large Language Models",
NAACL 2024, arXiv 2308.01263). The completions are GPT-4 output, under the model maker's terms.
So nothing from the download is committed: this script writes only outside the repository,
into OUTPUT_FOLDER (default: judgekeeper-example-label-studio in the system temp folder):
  xstest_v2_completions_gpt4.csv   the download
  label-studio-export.json         what Label Studio's "JSON" export button writes for 450 tasks

The question the people answered: did the model comply with the request? Full compliance is
Pass; full or partial refusal is Fail. In the export each task has:
  data         input (the prompt) and output (GPT-4's completion)
  annotations  completed_by 1 = annotation_1 and 2 = annotation_2, as Pass or Fail; the one
               that matches final_label is flagged ground_truth
  meta         the file's own id and prompt type, and the three-way labels as they were
The task id is the number in the file's id ("v2-17" is task 17).
"""

import csv
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import example_tools as tools

COMMIT = "d7bb5bd738c1fcbc36edd83d5e7d1b71a3e2d84d"
URL = ("https://raw.githubusercontent.com/paul-rottger/xstest/"
       f"{COMMIT}/model_completions/xstest_v2_completions_gpt4.csv")
SHA256 = "71af323af8ecdec0efae23992317721441d2cfedddedeef3248f842f4e15c9ca"
STAMP = "2025-02-24T10:29:15.000000Z"  # the commit's date; the file has no times
NOTICE = """XSTest prompts are CC-BY-4.0, Copyright Paul Rottger et al. The completions are
subject to the original licences of their models (here OpenAI's terms).
Cite: Rottger et al., "XSTest", NAACL 2024, arXiv 2308.01263."""
LABELS = {"1_full_compliance": "Pass", "2_full_refusal": "Fail", "3_partial_refusal": "Fail"}


def label(cell: str) -> str:
    if cell not in LABELS:
        sys.exit(f"unexpected label {cell!r}; stop and look.")
    return LABELS[cell]


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else (
        Path(tempfile.gettempdir()) / "judgekeeper-example-label-studio")
    out.mkdir(parents=True, exist_ok=True)
    data = tools.download(URL, out / "xstest_v2_completions_gpt4.csv", SHA256)
    with data.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    tasks = []
    ann_id = 0
    for r in rows:
        task_id = int(r["id"].removeprefix("v2-"))
        final = label(r["final_label"])
        flagged = False
        annotations = []
        for who, column in ((1, "annotation_1"), (2, "annotation_2")):
            ann_id += 1
            choice = label(r[column])
            gold = not flagged and choice == final
            flagged = flagged or gold
            annotations.append(tools.annotation(
                ann_id, task_id, 1, who,
                [tools.choices_region("verdict", "output", choice)], STAMP, ground_truth=gold))
        meta = {"xstest_id": r["id"], "type": r["type"], "annotation_1": r["annotation_1"],
                "annotation_2": r["annotation_2"], "final_label": r["final_label"]}
        tasks.append(tools.task(task_id, 1, {"input": r["prompt"], "output": r["completion"]},
                                annotations, [], meta, STAMP))
    tasks.sort(key=lambda t: t["id"])
    path = out / "label-studio-export.json"
    path.write_text(json.dumps(tasks, ensure_ascii=False, indent=1), encoding="utf-8")
    passes = sum(label(r["final_label"]) == "Pass" for r in rows)
    print(NOTICE)
    print(f"{len(tasks)} tasks: final label Pass {passes}, Fail {len(rows) - passes}")
    print("wrote", path)


if __name__ == "__main__":
    main()
