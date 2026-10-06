"""Temporary projects for `judgekeeper start`, one per eval tool, built from the fixtures.

Each writer takes the judge's verdicts as a list: True (pass), False (fail), or a raw value
written as it is (None for a judge error, "maybe" for a value no label map knows). Answer
`i` has the question `Question {i}?` and the answer `Answer {i}.`; `tag` is put into both, so
a test can look for answer text in what `start` prints.
"""

from __future__ import annotations

import copy
import csv
import json
from pathlib import Path

from tests.conftest import FIXTURES

PROMPTFOO = FIXTURES / "promptfoo" / "results.json"
DEEPEVAL = FIXTURES / "deepeval" / "results" / "test_run_20260930_120000.json"
INSPECT = FIXTURES / "inspect" / "logs" / "2026-09-30T10-00-00+00-00_qa_fixture.json"
RUBRIC = "Is polite and correct.\nSecond line of the rubric."
MODEL = "openai:gpt-4.1-mini"


def question(i: int, tag: str = "") -> str:
    return f"Question {i}?{tag}"


def answer(i: int, tag: str = "") -> str:
    return f"Answer {i}.{tag}"


def _write_json(path: Path, data) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1), encoding="utf-8")
    return path


def promptfoo_data(verdicts, model: str | None = MODEL, rubric: str = RUBRIC,
                   metric: str | None = None, created: str | None = "2026-10-03T14:12:00.000Z",
                   description: str | None = "support bot", tag: str = "",
                   outputs=None) -> dict:
    """A promptfoo results file: the fixture's first row, once per verdict, with only the
    llm-rubric component. `model` None leaves the grader out (promptfoo's default grader)."""
    base = json.loads(PROMPTFOO.read_text(encoding="utf-8"))
    row0 = base["results"]["results"][0]
    rows = []
    for i, v in enumerate(verdicts):
        row = copy.deepcopy(row0)
        row["id"], row["testIdx"] = f"row-{i}", i
        qvars = {"question": question(i, tag)}
        row["vars"] = qvars
        row["testCase"] = {"description": f"t{i}", "vars": qvars, "assert": [],
                           "options": ({"provider": {"id": model, "config": {"temperature": 0}}}
                                       if model else {})}
        row["response"] = {"output": answer(i, tag) if outputs is None else outputs[i]}
        assertion = {"type": "llm-rubric", "value": rubric}
        if metric:
            assertion["metric"] = metric
        score = 1 if v is True else 0 if v is False else None
        component = {"pass": v, "score": score, "reason": f"reason {i}",
                     "assertion": assertion}
        row["gradingResult"] = {"pass": v, "score": component["score"], "reason": "",
                                "componentResults": [component]}
        row["success"] = v
        rows.append(row)
    data = {"evalId": "eval-test", "results": {**base["results"], "results": rows},
            "config": {"description": description} if description else {}}
    if created:
        data["metadata"] = {"evaluationCreatedAt": created}
    return data


def promptfoo_project(root: Path, verdicts, name: str = "results.json", config: bool = True,
                      **kwargs) -> Path:
    if config:
        (root / "promptfooconfig.yaml").parent.mkdir(parents=True, exist_ok=True)
        (root / "promptfooconfig.yaml").write_text(
            "description: support bot\nprompts:\n  - 'Answer: {{question}}'\n", encoding="utf-8")
    return _write_json(root / name, promptfoo_data(verdicts, **kwargs))


def deepeval_data(verdicts, model: str = "gpt-4.1", tag: str = "", start: int = 0) -> dict:
    """A DeepEval test run: the fixture's first case and its GEval metric, once per verdict."""
    base = json.loads(DEEPEVAL.read_text(encoding="utf-8"))
    case0 = base["testCases"][0]
    cases = []
    for n, v in enumerate(verdicts):
        i = start + n
        case = copy.deepcopy(case0)
        case.update(name=f"case-{i}", input=question(i, tag), actualOutput=answer(i, tag),
                    success=v)
        metric = copy.deepcopy(case0["metricsData"][0])
        metric.update(success=v, score=0.9 if v else 0.1, evaluationModel=model,
                      reason=f"reason {i}")
        case["metricsData"] = [metric]
        cases.append(case)
    return {**base, "testFile": "test_support.py", "testCases": cases,
            "conversationalTestCases": []}


def deepeval_project(root: Path, verdicts, name: str = ".deepeval/.latest_run_full.json",
                     **kwargs) -> Path:
    return _write_json(root / name, deepeval_data(verdicts, **kwargs))


def inspect_data(verdicts, tag: str = "") -> dict:
    """An Inspect AI log: the fixture's eval with its model_graded_qa scorer, one sample per
    verdict (True is C, False is I, anything else as written)."""
    base = json.loads(INSPECT.read_text(encoding="utf-8"))
    sample0 = base["samples"][0]
    samples = []
    for i, v in enumerate(verdicts):
        s = copy.deepcopy(sample0)
        value = "C" if v is True else "I" if v is False else v
        s.update(id=i, epoch=1, input=question(i, tag))
        s["output"]["completion"] = answer(i, tag)
        s["scores"] = {"model_graded_qa": {"value": value, "explanation": f"reason {i}",
                                           "history": []}}
        samples.append(s)
    spec = copy.deepcopy(base["eval"])
    spec["scorers"] = [x for x in spec["scorers"] if x["name"] == "model_graded_qa"]
    spec["task_file"] = "support_task.py"
    return {**base, "eval": spec, "samples": samples}


def inspect_project(root: Path, verdicts, name: str = "logs/2026-10-02_support.json",
                    **kwargs) -> Path:
    return _write_json(root / name, inspect_data(verdicts, **kwargs))


def table_project(root: Path, verdicts, name: str = "results.csv", model: str | None = None,
                  verdict_column: str = "verdict", tag: str = "", extra=None) -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = ["input", "output", verdict_column] + (["model"] if model else [])
    columns += list(extra or {})
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(columns)
        for i, v in enumerate(verdicts):
            cell = "pass" if v is True else "fail" if v is False else ("" if v is None else v)
            row = [question(i, tag), answer(i, tag), cell] + ([model] if model else [])
            row += [values[i] for values in (extra or {}).values()]
            w.writerow(row)
    return path


def split(n_pass: int, n_fail: int) -> list[bool]:
    return [True] * n_pass + [False] * n_fail


def own_format_project(root: Path, runs: int = 2, cases: int = 3) -> Path:
    """A made-up project shaped like one that calls a DeepEval metric's measure() itself and
    keeps the scores in its own nested JSONL: runs, then cases, then two answers (A and B)
    with a score per criterion. DeepEval is in the requirements; no DeepEval results file."""
    (root / "requirements.txt").write_text("deepeval==4.2.8\nanthropic\n", encoding="utf-8")
    (root / "evals").mkdir(parents=True, exist_ok=True)
    (root / "evals" / "run_evals.py").write_text(
        "from deepeval.metrics import GEval\n# metric.measure(case) for each answer\n",
        encoding="utf-8")
    lines = []
    for r in range(runs):
        rows = []
        for c in range(cases):
            rows.append({
                "case_id": f"case-{c}", "prompt": question(c),
                "responses": {"A": answer(c, " (A)"), "B": answer(c, " (B)")},
                "scores": {k: {"safe_wording": {"score": 0.9 if c % 2 else 0.2,
                                                "reason": f"reason {c}"}}
                           for k in ("A", "B")}})
        lines.append(json.dumps({"run_id": f"run-{r}", "judge": "claude-opus-5",
                                 "cases": rows}))
    path = root / "data" / "prompt_evals.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def records_project(root: Path, verdicts, name: str = "Safe wording", pid: int = 4101,
                    model: str | None = "claude-opus-5", rule: str | None = "Be polite.",
                    tag: str = "", start: int = 0, day: str = "2026-10-05",
                    mtime: float | None = None) -> Path:
    """One file as judgekeeper.record() writes it, in `.judgekeeper/records/`: one line per
    verdict, the file named <name>-<day>-<pid>.jsonl. `mtime` sets its modified time."""
    import os

    folder = root / ".judgekeeper" / "records"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{name.replace(' ', '-')}-{day}-{pid}.jsonl"
    evaluator = {k: v for k, v in (("model", model), ("rule", rule)) if v is not None}
    with path.open("a", encoding="utf-8") as f:
        for i, v in enumerate(verdicts, start):
            label = "pass" if v is True else "fail" if v is False else v
            f.write(json.dumps({"schema_version": 2, "target_id": None, "name": name,
                                "annotator_kind": "LLM", "label": label, "score": None,
                                "explanation": f"reason {i}", "run": None,
                                "input": question(i, tag), "output": answer(i, tag),
                                "evaluator": evaluator,
                                "created_at": f"{day}T10:00:00Z"}) + "\n")
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


CRITERIA = ("Safe wording", "Plain language")


def nested_runs_data(runs: int = 3, cases: int = 8, rule_rows: int = 1) -> list[dict]:
    """A made-up results history shaped like a homemade DeepEval setup's: one line per run,
    each run's cases, two answers per case (A and B), a score from 0 to 1 and a reason per
    criterion. Case `c` answer A passes "Safe wording" when c is even, B when c is odd; the
    first `rule_rows` cases of each run have a "Safe wording" score made by a rule."""
    lines = []
    for r in range(runs):
        rows = []
        for c in range(cases):
            case = {"id": f"c{c}", "prompt": question(c, f" (run {r})")}
            for side in ("A", "B"):
                passes = (c % 2 == 0) == (side == "A")
                scores = {}
                for crit in CRITERIA:
                    score = 0.9 if passes else 0.2
                    reason = f"{crit}: {'fine' if passes else 'not fine'} ({side}{c})"
                    if crit == "Safe wording" and c < rule_rows:
                        reason = "Rule: answers with a phone number fail"
                    scores[crit] = {"score": score, "reason": reason}
                case[side] = {"output": answer(c, f" ({side}, run {r})"), "scores": scores}
            rows.append(case)
        lines.append({"run_id": f"2026-10-0{r + 1}T10:00", "judge_model": "claude-opus-5",
                      "cases": rows})
    return lines


def nested_runs_project(root: Path, git: bool = True, requirements_dev: bool = True,
                    **kwargs) -> Path:
    """A project whose homemade judge uses DeepEval: DeepEval in requirements.txt, no
    DeepEval results file, the judge's results only in its own nested JSONL
    (history/evals.jsonl)."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "requirements.txt").write_text("deepeval==4.2.8\nanthropic\n", encoding="utf-8")
    if requirements_dev:
        (root / "requirements-dev.txt").write_text("pytest\n", encoding="utf-8")
    if git:
        (root / ".git").mkdir(exist_ok=True)
    path = root / "history" / "evals.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(line) + "\n" for line in nested_runs_data(**kwargs)),
                    encoding="utf-8")
    return path


def flat_jsonl(path: Path, n: int = 36) -> Path:
    """One judged answer per line, with names of its own: question, model_answer, grade
    (PASS or FAIL) and explanation."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps({"question": question(i), "model_answer": answer(i),
                                        "grade": "PASS" if i % 3 else "FAIL",
                                        "explanation": f"because {i}"}) + "\n"
                            for i in range(n)), encoding="utf-8")
    return path


def odd_csv(path: Path, n: int = 36) -> Path:
    """A CSV with odd column names and scores from 0 to 1 written as text."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Row", "User Question", "Bot Reply", "Judge Score", "Judge Reasoning"])
        for i in range(n):
            w.writerow([i, question(i), answer(i), "0.8" if i % 2 else "0.3", f"why {i}"])
    return path
