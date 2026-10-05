"""Write the promptfoo, DeepEval and Inspect AI fixtures for tests/test_import_*.py.

Run from the repo root: python tests/fixtures/make_framework_fixtures.py

The shapes follow each tool's own documentation and
source; each fixture folder has a README saying where its shape came from. The verdicts are
chosen so every number in the tests can be derived by hand (see the test modules' docstrings).
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent / "src"))

from judgekeeper.table import derive_id


def dump(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


# promptfoo ----------------------------------------------------------------------------------
# 7 tests (t0..t6), one prompt, --repeat 3. Humans rated the first repeat of t0..t5 in the web
# UI: t0-t2 pass, t3-t5 fail; t6 has no rating. The helpfulness judge (llm-rubric) passes:
#   repeat 1: t0 t1 t5 t6      repeat 2: t0 t1 t2 t5 t6      repeat 3: as repeat 1
# On t2 and t5 in repeat 1 the human rating overrides the judge, so the row's top-level
# success disagrees with the llm-rubric component. t2 has no grader provider: promptfoo's
# built-in default grader judged it.

PF_RUBRIC = "The answer is helpful and correct."
PF_PROVIDER = {"id": "openai:gpt-4.1-mini", "config": {"temperature": 0}}
PF_JUDGE = {
    1: {"t0", "t1", "t5", "t6"},
    2: {"t0", "t1", "t2", "t5", "t6"},
    3: {"t0", "t1", "t5", "t6"},
}
PF_HUMAN = {"t0": True, "t1": True, "t2": True, "t3": False, "t4": False, "t5": False}


def promptfoo() -> None:
    rows = []
    for repeat in (1, 2, 3):
        for t in range(7):
            name = f"t{t}"
            judge_pass = name in PF_JUDGE[repeat]
            output = f"Answer to question {t}."
            components = [
                {"pass": True, "score": 1, "reason": 'Expected output to contain "Answer"',
                 "assertion": {"type": "contains", "value": "Answer"}},
                {"pass": judge_pass, "score": 1 if judge_pass else 0,
                 "reason": f"repeat {repeat}: {'helpful' if judge_pass else 'not helpful'}",
                 "assertion": {"type": "llm-rubric", "value": PF_RUBRIC,
                               "metric": "helpfulness"}},
                {"pass": True, "score": 1, "reason": "The submission agrees with the reference.",
                 "assertion": {"type": "factuality", "value": f"reference {t}"}},
            ]
            success = all(c["pass"] for c in components)
            if repeat == 1 and name in PF_HUMAN:
                human = PF_HUMAN[name]
                components.append({
                    "pass": human, "score": 1 if human else 0,
                    "reason": "Manual result (overrides all other grading results)",
                    "comment": f"reviewer on {name}",
                    "assertion": {"type": "human"},
                })
                success = human  # the manual rating overrides the row
            options = {} if name == "t2" else {"provider": PF_PROVIDER}
            rows.append({
                "id": f"row-{repeat}-{t}",
                "testIdx": 3 * t + repeat - 1,  # real files: one testIdx per repeat
                "promptIdx": 0,
                "promptId": "prompt-0",
                "testCase": {"description": name, "vars": {"qid": f"Q{t}",
                                                           "question": f"Question {t}?"},
                             "assert": [], "options": options},
                "vars": {"qid": f"Q{t}", "question": f"Question {t}?"},
                "provider": {"id": "openai:gpt-4.1", "label": ""},
                "prompt": {"raw": f"Answer: Question {t}?", "label": "answer"},
                "response": {"output": output},
                "success": success,
                "score": 1 if success else 0,
                "failureReason": 0 if success else 1,
                "latencyMs": 12,
                "namedScores": {"helpfulness": 1 if judge_pass else 0},
                "gradingResult": {
                    "pass": success,
                    "score": 1 if success else 0,
                    "reason": "All assertions passed" if success else "An assertion failed",
                    "namedScores": {"helpfulness": 1 if judge_pass else 0},
                    "componentResults": components,
                },
            })
    dump(HERE / "promptfoo" / "results.json", {
        "evalId": "eval-fixture-2026-09-30",
        "results": {
            "version": 3,
            "timestamp": "2026-09-30T10:00:00.000Z",
            "prompts": [{"raw": "Answer: {{question}}", "label": "answer"}],
            "stats": {"successes": 0, "failures": 0},
            "results": rows,
        },
        "config": {"description": "judgekeeper fixture", "defaultTest": {"options": {}}},
        "shareableUrl": None,
    })


# DeepEval -----------------------------------------------------------------------------------
# 8 test cases with DeepEval's positional default names (test_case_0..7), three runs written
# to a results folder, one file per run. Human labels (labels.csv): c0-c3 pass, c4-c7 fail.
# The Correctness GEval judge passes:
#   run 1: c0-c4      run 2: c0-c2      run 3: c0-c4

DE_CRITERIA = "Is the actual output factually correct given the input?"
DE_STEPS = ["Check each claim in the actual output.", "Penalise any claim that is false."]
DE_JUDGE = {1: {0, 1, 2, 3, 4}, 2: {0, 1, 2}, 3: {0, 1, 2, 3, 4}}
DE_HUMAN = {i: "pass" if i < 4 else "fail" for i in range(8)}


def deepeval_verbose_logs(score: float, reason: str) -> str:
    # deepeval/metrics/g_eval/g_eval.py builds these steps; construct_verbose_logs
    # (deepeval/metrics/utils/verbose.py) joins all but the last with " \n \n".
    steps = [f"Criteria:\n{DE_CRITERIA}",
             "Evaluation Steps:\n[\n    " + ",\n    ".join(f'"{s}"' for s in DE_STEPS) + "\n]",
             "Rubric:\nNone",
             f"Score: {score}",
             f"Reason: {reason}"]
    return " \n \n".join(steps[:-1])


def deepeval_item(i: int) -> dict:
    return {"input": f"What is {i} + {i}?", "output": f"{i} + {i} = {2 * i}."}


def deepeval() -> None:
    stamps = {1: "20260930_100000", 2: "20260930_110000", 3: "20260930_120000"}
    for run, stamp in stamps.items():
        cases = []
        for i in range(8):
            ok = i in DE_JUDGE[run]
            score = 0.9 if ok else 0.2
            reason = f"run {run}: {'correct' if ok else 'a claim is wrong'}"
            item = deepeval_item(i)
            cases.append({
                "name": f"test_case_{i}",
                "input": item["input"],
                "actualOutput": item["output"],
                "expectedOutput": f"{2 * i}",
                "success": ok,
                "order": i,
                "runDuration": 0.5,
                "metricsData": [
                    {"name": "Correctness [GEval]", "threshold": 0.5, "success": ok,
                     "score": score, "reason": reason, "strictMode": False,
                     "evaluationModel": "gpt-4.1", "evaluationCost": 0.0001,
                     "verboseLogs": deepeval_verbose_logs(score, reason)},
                    {"name": "Answer Relevancy", "threshold": 0.5, "success": True,
                     "score": 1.0, "reason": "relevant", "strictMode": False,
                     "evaluationModel": "gpt-4.1", "evaluationCost": 0.0001,
                     "verboseLogs": "Statements:\n[] \n \nVerdicts:\n[]"},
                ],
            })
        dump(HERE / "deepeval" / "results" / f"test_run_{stamp}.json", {
            "testFile": "test_math.py",
            "testCases": cases,
            "conversationalTestCases": [],
            "metricsScores": [],
            "testPassed": sum(c["success"] for c in cases),
            "testFailed": sum(not c["success"] for c in cases),
            "runDuration": 4.0,
            "evaluationCost": 0.0016,
        })
    with (HERE / "deepeval" / "labels.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "input", "output", "human_label", "notes"])
        for i in range(8):
            item = deepeval_item(i)
            w.writerow([derive_id(item), item["input"], item["output"], DE_HUMAN[i], ""])
        # A labeled item no run judged: dropped, with a count in the report.
        w.writerow(["not-in-any-run", "What is 9 + 9?", "18.", "pass", ""])


# Inspect AI ---------------------------------------------------------------------------------
# One .json log: 6 samples (ids 1-6), epochs=3, scorers model_graded_qa and match.
# Human labels: 1-3 pass, 4-6 fail; 3 comes from a score edit in epoch 1 (the judge said I,
# a reviewer changed it to C), the rest from labels.csv. model_graded_qa values:
#   epoch 1: 1 C, 2 C, 3 I (edited to C), 4 I, 5 I, 6 C
#   epoch 2: 1 C, 2 C, 3 C, 4 I, 5 I, 6 I
#   epoch 3: 1 C, 2 C, 3 C, 4 I, 5 P, 6 I     (P needs --label-map P=fail)

IN_INSTRUCTIONS = "Grade the answer as C (correct) or I (incorrect)."
IN_JUDGE = {
    1: ["C", "C", "I", "I", "I", "C"],
    2: ["C", "C", "C", "I", "I", "I"],
    3: ["C", "C", "C", "I", "P", "I"],
}


def _score(value: str, explanation: str, prompt: str) -> dict:
    return {"value": value, "answer": "the answer", "explanation": explanation,
            "metadata": {"grading": [{"role": "user", "content": prompt},
                                     {"role": "assistant", "content": explanation}]},
            "history": []}


def inspect_log() -> None:
    samples = []
    for epoch in (1, 2, 3):
        for sid in range(1, 7):
            value = IN_JUDGE[epoch][sid - 1]
            prompt = f"{IN_INSTRUCTIONS}\nQuestion {sid}\nAnswer {sid}"
            graded = _score(value, f"epoch {epoch}: GRADE: {value}", prompt)
            if epoch == 1 and sid == 3:
                original = {k: graded[k] for k in ("value", "answer", "explanation", "metadata")}
                graded["value"] = "C"
                graded["history"] = [
                    {**original, "reason": None, "provenance": None},
                    {"value": "C", "answer": "UNCHANGED", "explanation": "UNCHANGED",
                     "reason": "UNCHANGED", "metadata": "UNCHANGED",
                     "provenance": {"timestamp": "2026-09-30T12:00:00Z",
                                    "author": "reviewer@example.com",
                                    "reason": "the answer is right", "metadata": {}}},
                ]
            samples.append({
                "id": sid,
                "epoch": epoch,
                "uuid": f"uuid-{epoch}-{sid}",
                "input": f"Question {sid}",
                "target": f"Answer {sid}",
                "output": {"model": "openai/gpt-4.1",
                           "choices": [{"message": {"role": "assistant",
                                                    "content": f"Answer {sid}"}}],
                           "completion": f"Answer {sid}"},
                "messages": [],
                "metadata": {},
                "scores": {"model_graded_qa": graded,
                           "match": {"value": "C", "answer": f"Answer {sid}",
                                     "explanation": None, "history": []}},
            })
    dump(HERE / "inspect" / "logs" / "2026-09-30T10-00-00+00-00_qa_fixture.json", {
        "version": 2,
        "status": "success",
        "eval": {
            "eval_id": "fixture-eval",
            "run_id": "fixture-run",
            "created": "2026-09-30T10:00:00+00:00",
            "task": "qa",
            "task_id": "qa-fixture",
            "model": "openai/gpt-4.1",
            "model_generate_config": {},
            "model_roles": {"grader": {"model": "anthropic/claude-haiku-4-5",
                                       "config": {"temperature": 0.0}, "args": {}}},
            "config": {"epochs": 3},
            "scorers": [
                {"name": "model_graded_qa",
                 "options": {"instructions": IN_INSTRUCTIONS, "partial_credit": True,
                             "model_role": "grader"},
                 "metrics": [{"name": "inspect_ai/accuracy", "options": {}}]},
                {"name": "match", "options": {"location": "end"},
                 "metrics": [{"name": "inspect_ai/accuracy", "options": {}}]},
            ],
        },
        "plan": {"steps": []},
        "results": {"total_samples": 18, "completed_samples": 18, "scores": []},
        "stats": {"started_at": "2026-09-30T10:00:00+00:00",
                  "completed_at": "2026-09-30T10:05:00+00:00"},
        "samples": samples,
    })
    with (HERE / "inspect" / "labels.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "human_label"])
        for sid in (1, 2, 4, 5, 6):
            w.writerow([sid, "pass" if sid <= 3 else "fail"])


if __name__ == "__main__":
    promptfoo()
    deepeval()
    inspect_log()
