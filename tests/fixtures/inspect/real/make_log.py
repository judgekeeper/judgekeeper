"""Write the Inspect AI log in logs/ with a real `inspect_ai.eval` run. No API call.

Run from this folder with inspect-ai installed: python make_log.py

The task: 6 samples, epochs=3, scored by model_graded_qa() with its default template and
instructions. Both the solver model and the grader are `mockllm/model`; the grader is bound to
the "grader" role and given `custom_outputs`, so its verdicts are fixed. max_samples=1 makes
the grader calls run in a fixed order: epoch 1 samples 1-6, then epoch 2, then epoch 3.
"""

import shutil
from pathlib import Path

from inspect_ai import Task, eval
from inspect_ai.dataset import Sample
from inspect_ai.model import ModelOutput, ModelUsage, get_model
from inspect_ai.scorer import model_graded_qa
from inspect_ai.solver import generate

HERE = Path(__file__).resolve().parent

# Grader verdict per sample, one letter per epoch.
GRADES = {1: "CCC", 2: "CCC", 3: "ICC", 4: "III", 5: "III", 6: "CII"}


def task() -> Task:
    return Task(
        dataset=[Sample(id=i, input=f"Question {i}: what is {i} + {i}?", target=str(2 * i))
                 for i in GRADES],
        solver=generate(),
        scorer=model_graded_qa(),
    )


def output(text: str) -> ModelOutput:
    # Usage set up front: otherwise mockllm counts tokens with tiktoken, which downloads its
    # encoding from the network.
    out = ModelOutput.from_content("mockllm/model", text)
    out.usage = ModelUsage(input_tokens=1, output_tokens=1, total_tokens=2)
    return out


def main() -> None:
    n = sum(len(g) for g in GRADES.values())
    answerer = get_model("mockllm/model", custom_outputs=[output("Here is my answer.")] * n)
    grader = get_model("mockllm/model", custom_outputs=[
        output(f"The answer looks fine.\nGRADE: {GRADES[i][e]}") for e in range(3) for i in GRADES])
    logs = HERE / "logs"
    shutil.rmtree(logs, ignore_errors=True)
    eval(task(), model=answerer, model_roles={"grader": grader}, epochs=3,
         max_samples=1, log_dir=str(logs), log_format="json", display="none")
    # Inspect names the log after its start time; give it a stable name for the tests.
    (log,) = logs.glob("*.json")
    log.rename(logs / "model_graded_qa.json")


if __name__ == "__main__":
    main()
