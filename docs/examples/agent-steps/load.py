"""Download AgentProcessBench's gaia_dev runs and write them in two shapes.

    python3 -I load.py [OUTPUT_FOLDER] [--guesses GUESSES.jsonl ...]

Source: huggingface.co/datasets/LulaCola/AgentProcessBench, file gaia_dev/test.jsonl, pinned to
one revision and checked by its SHA-256. Licence: MIT, as the dataset card says (the project's
GitHub repository, github.com/RUCBM/AgentProcessBench, has no LICENSE file). Paper: "AgentProcess
Bench", arXiv 2603.14465. Nothing from the download is committed: this script writes only
outside the repository, into OUTPUT_FOLDER (default: judgekeeper-example-agent-steps in the
system temp folder):
  gaia_dev-test.jsonl        the download
  runs.jsonl                 one run per line: id, task, steps (judgekeeper's runs format)
  label-studio-export.json   what Label Studio's "JSON" export writes for 250 tasks

Steps. One step is one turn of the agent: what the assistant wrote, the tool calls it made, and
everything that came back before its next turn (tool results, and the harness's reminder when
no tool call was made). Step N is `steps[N - 1]`. The system prompt is left out; the user's
question is `task`.

The people's label (first_wrong_step). The dataset gives each assistant turn a label: 1 good,
0 neutral, -1 wrong. The first wrong step is the smallest step number whose label is -1; if no
step is -1 it is 0, which means "all fine". A neutral 0 label is not wrong.

In the export each task has data {task, steps}, one annotation (completed_by 1) with a number
region first_wrong_step, and, for each --guesses file, one prediction whose model_version is the
`model` of its lines and whose created_at is the line's `timestamp`. A guesses file has one line
per run: {"id", "first_wrong_step", "model", "timestamp"}, and may carry the rest of the judge
fingerprint (provider, snapshot, prompt_hash, rubric_version, temperature) for
`judgekeeper steps --reviewer`. Runs the reviewer made no guess for have no prediction. The task
id is the file's total_index. The people's labels have no times in the dataset; their stamp is a
fixed placeholder.
"""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import example_tools as tools

REVISION = "cd81f326aece8b0a3f6359e20df370690d3a98bf"
URL = ("https://huggingface.co/datasets/LulaCola/AgentProcessBench/resolve/"
       f"{REVISION}/gaia_dev/test.jsonl")
SHA256 = "f7b75c668fc1e6ad943e8f6d93a21a9a8f5f076841e1230e1ed2fc6d05ce8192"
STAMP = "2026-03-01T00:00:00.000000Z"  # the file has no times; any fixed value will do
NOTICE = """AgentProcessBench is MIT licensed (dataset card). The GitHub repository has no LICENSE.
Cite: "AgentProcessBench", arXiv 2603.14465."""


def render_step(assistant: dict, after: list[dict]) -> str:
    """Text of one step: the assistant's turn, then what came back before its next turn."""
    parts = []
    if (assistant.get("content") or "").strip():
        parts.append(assistant["content"].strip())
    for call in assistant.get("tool_calls") or []:
        fn = call.get("function") or {}
        parts.append(f"[tool call] {fn.get('name')}({fn.get('arguments')})")
    for m in after:
        if m["role"] == "tool":
            parts.append(f"[tool result: {m.get('name')}]\n{m.get('content')}")
        else:
            parts.append(f"[message to the agent]\n{m.get('content')}")
    return "\n\n".join(parts)


def read_run(row: dict) -> tuple[str, list[str], int]:
    """(task, step texts, human first wrong step) for one run."""
    messages = row["messages"]
    if [m["role"] for m in messages[:2]] != ["system", "user"]:
        sys.exit(f"run {row['total_index']}: does not start with system and user; stop and look.")
    steps = []
    step_of_message = {}
    for i, m in enumerate(messages[2:], 2):
        if m["role"] == "assistant":
            steps.append((m, []))
            step_of_message[i] = len(steps)
        elif steps:
            steps[-1][1].append(m)
        else:
            sys.exit(f"run {row['total_index']}: message {i} comes before any step; stop.")
    wrong = []
    for key, value in row["step_labels"].items():
        if int(key) not in step_of_message:
            sys.exit(f"run {row['total_index']}: label for message {key}, not an assistant "
                     "turn; stop and look.")
        if value not in (-1, 0, 1):
            sys.exit(f"run {row['total_index']}: unexpected label {value!r}; stop and look.")
        if value == -1:
            wrong.append(step_of_message[int(key)])
    return messages[1]["content"], [render_step(a, after) for a, after in steps], min(wrong, default=0)


def main() -> None:
    args = sys.argv[1:]
    guess_files = []
    while "--guesses" in args:
        at = args.index("--guesses")
        guess_files.append(Path(args[at + 1]))
        del args[at:at + 2]
    out = Path(args[0]) if args else (
        Path(tempfile.gettempdir()) / "judgekeeper-example-agent-steps")
    out.mkdir(parents=True, exist_ok=True)
    data = tools.download(URL, out / "gaia_dev-test.jsonl", SHA256)
    with data.open(encoding="utf-8") as f:
        rows = [json.loads(line) for line in f if line.strip()]
    guesses: dict[int, dict[str, tuple[int, str]]] = {}  # run id -> {model: (guess, time)}
    models: list[str] = []
    for path in guess_files:
        for line in path.read_text(encoding="utf-8").splitlines():
            g = json.loads(line)
            guesses.setdefault(int(g["id"]), {})[g["model"]] = (
                int(g["first_wrong_step"]), g["timestamp"])
            if g["model"] not in models:
                models.append(g["model"])
    tasks = []
    ann_id = 0
    pred_id = 0
    all_fine = 0
    with (out / "runs.jsonl").open("w", encoding="utf-8") as runs:
        for row in sorted(rows, key=lambda r: r["total_index"]):
            run_id = row["total_index"]
            task_text, steps, first_wrong = read_run(row)
            all_fine += first_wrong == 0
            runs.write(json.dumps({"id": run_id, "task": task_text,
                                   "steps": [{"role": "assistant", "content": s} for s in steps]},
                                  ensure_ascii=False) + "\n")
            ann_id += 1
            region = [tools.number_region("first_wrong_step", "steps", first_wrong)]
            preds = []
            for model in models:
                if model in guesses.get(run_id, {}):
                    pred_id += 1
                    guess, when = guesses[run_id][model]
                    preds.append(tools.prediction(
                        pred_id, run_id, 1, model,
                        [tools.number_region("first_wrong_step", "steps", guess)],
                        when.removesuffix("Z") + ".000000Z"))
            tasks.append(tools.task(
                run_id, 1,
                {"task": task_text, "steps": [{"role": "assistant", "content": s} for s in steps]},
                [tools.annotation(ann_id, run_id, 1, 1, region, STAMP)], preds, {}, STAMP))
    path = out / "label-studio-export.json"
    path.write_text(json.dumps(tasks, ensure_ascii=False, indent=1), encoding="utf-8")
    print(NOTICE)
    print(f"{len(tasks)} runs: {all_fine} with no wrong step, {len(tasks) - all_fine} with one")
    print("wrote", out / "runs.jsonl")
    print("wrote", path)


if __name__ == "__main__":
    main()
