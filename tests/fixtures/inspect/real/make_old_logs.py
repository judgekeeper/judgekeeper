"""Write the older Inspect AI logs in old/ with a real `inspect_ai.eval` run. No API call.

Run from this folder, once with each version installed (0.3.2 has no mockllm and no
--log-format, so the answer model and the grader are a fixed fake registered here):

    pip install inspect-ai==0.3.2 && python make_old_logs.py json      # old/inspect-0.3.2.json
    pip install inspect-ai==0.3.204 && python make_old_logs.py eval    # old/inspect-0.3.204.eval

The task: 2 samples, scored by model_graded_qa() with its default template. The grader says
I for sample 1 (the answer is 5) and C for sample 2 (the answer is Paris).
"""

import shutil
import sys
import tempfile
from pathlib import Path

import inspect_ai
from inspect_ai import Task, eval, task
from inspect_ai.dataset import Sample
from inspect_ai.model import ModelAPI, ModelOutput, modelapi
from inspect_ai.scorer import model_graded_qa
from inspect_ai.solver import generate

HERE = Path(__file__).resolve().parent


class Fixed(ModelAPI):
    """No AI call: the answer model says 5 or Paris; as grader, Grade: C or I."""

    async def generate(self, input, tools, tool_choice, config):
        text = str(input[-1].text if hasattr(input[-1], "text") else input[-1].content)
        if "[Criterion]" in text:
            reply = "Looks right.\nGrade: C" if "Paris" in text else "Wrong.\nGrade: I"
        else:
            reply = "Paris" if "France" in text else "5"
        return ModelOutput.from_content(model=self.model_name, content=reply)


@modelapi(name="fixed")
def fixed():
    return Fixed


@task
def qa():
    return Task(dataset=[Sample(input="What is 2+2?", target="4"),
                         Sample(input="Capital of France?", target="Paris")],
                plan=[generate()], scorer=model_graded_qa(model="fixed/grader"))


if __name__ == "__main__":
    suffix = sys.argv[1]
    with tempfile.TemporaryDirectory() as tmp:
        eval(qa(), model="fixed/answer", log_dir=tmp)
        (log,) = Path(tmp).iterdir()
        assert log.suffix == f".{suffix}", log
        (HERE / "old").mkdir(exist_ok=True)
        shutil.copy(log, HERE / "old" / f"inspect-{inspect_ai.__version__}.{suffix}")
