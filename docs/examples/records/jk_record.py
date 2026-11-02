# Saves each LLM-as-a-judge grade for judgekeeper; run it from your project folder. Standard library only.
# It takes the arguments of judgekeeper.record() and writes the same line.
import json, os, re, time
def jk_record(input=None, output=None, *, verdict=None, score=None, pass_mark=None,
              reason=None, judge=None, rule=None, name=None, temperature=None, id=None,
              metadata=None):
    try:
        name, now = "LLM-as-a-judge" if name is None else str(name), time.gmtime()
        meta = dict(metadata or {})
        if pass_mark is not None:
            meta.setdefault("pass_mark", pass_mark)
        label = verdict
        if isinstance(verdict, bool):
            label = "pass" if verdict else "fail"
        elif isinstance(verdict, str) and verdict.strip().lower() in ("pass", "fail"):
            label = verdict.strip().lower()
        elif verdict is None and score is not None and pass_mark is not None:
            label = "pass" if score >= pass_mark else "fail"
        line = {"schema_version": 2, "target_id": None if id is None else str(id), "name": name,
                "annotator_kind": "LLM", "label": label, "score": score,
                "explanation": None if reason is None else str(reason), "run": None,
                "input": input, "output": output,
                "evaluator": {k: v for k, v in (("model", judge), ("temperature", temperature),
                                                ("rule", rule)) if v is not None},
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", now)}
        if meta:
            line["metadata"] = meta
        folder = os.path.join(".judgekeeper", "records")
        os.makedirs(folder, exist_ok=True)
        file = re.sub(r"[^A-Za-z0-9._]+", "-", name).strip("-.")[:60] or "LLM-as-a-judge"
        file += f"-{time.strftime('%Y-%m-%d', now)}-{os.getpid()}.jsonl"
        with open(os.path.join(folder, file), "a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(line, ensure_ascii=False, default=str) + "\n")
    except Exception:
        pass  # a record never stops your program
